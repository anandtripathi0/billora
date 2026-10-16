import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlencode, quote
from zoneinfo import ZoneInfo
from django.db import transaction
from django.db.models import Sum
from django.core import signing
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from .models import Business, Product, Customer, Invoice, InvoiceItem, Payment, AuditLog, InvoiceLogo, Refund, PrintJob

CENT = Decimal('0.01')
def money(value): return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)

def audit(user, business, action, object_id=''):
    AuditLog.objects.create(actor=user, business=business, action=action, object_id=str(object_id))

def calculate_lines(products, selections, discount, gst_enabled, interstate):
    lines = []
    seen = set()
    for selection in selections:
        pid = selection['product']
        if pid in seen: raise ValidationError('Combine duplicate products into a single line.')
        seen.add(pid)
        product = products.get(pid)
        if not product or not product.is_active: raise ValidationError('A selected product is unavailable.')
        if product.selling_price is None: raise ValidationError(f'Enter a selling price for {product.name} before billing.')
        if gst_enabled and product.gst_rate is None: raise ValidationError(f'Verify and enter the GST rate for {product.name} before creating a GST invoice.')
        quantity = selection['quantity']
        price = selection.get('unit_price', product.selling_price)
        subtotal = money(price * quantity)
        lines.append(dict(product=product, description=product.name, sku=product.sku, hsn_code=product.hsn_code,
            unit=product.unit, quantity=quantity, unit_price=price, purchase_price=product.purchase_price,
            gst_rate=product.gst_rate if gst_enabled else Decimal(0), subtotal=subtotal, price_includes_tax=product.price_includes_tax))
    subtotal = sum((line['subtotal'] for line in lines), Decimal(0))
    discount = money(discount)
    if discount < 0 or discount > subtotal: raise ValidationError('Discount must be between zero and the subtotal.')
    # Largest-remainder allocation ensures discounts add up exactly, including many tiny lines.
    allocated = []
    for index, line in enumerate(lines):
        exact = discount * line['subtotal'] / subtotal if subtotal else Decimal(0)
        floor = exact.quantize(CENT, rounding='ROUND_DOWN')
        line['discount'] = floor
        allocated.append((exact - floor, index))
    remaining = int((discount - sum((line['discount'] for line in lines), Decimal(0))) / CENT)
    for _, index in sorted(allocated, reverse=True)[:remaining]: lines[index]['discount'] += CENT
    for line in lines:
        taxable = line['subtotal'] - line['discount']
        if line['price_includes_tax'] and gst_enabled:
            net = money(taxable * 100 / (100 + line['gst_rate']))
            tax = taxable - net
            cgst = Decimal(0) if interstate else money(tax / 2)
            line.update(cgst=cgst, sgst=Decimal(0) if interstate else tax - cgst, igst=tax if interstate else Decimal(0))
            # Keep the observed unit price; subtract included tax from accounting subtotal.
            line['subtotal'] -= tax
            taxable = net
        elif interstate:
            line.update(cgst=Decimal(0), sgst=Decimal(0), igst=money(taxable * line['gst_rate'] / 100))
        else:
            half_tax = money(taxable * line['gst_rate'] / 200)
            line.update(cgst=half_tax, sgst=half_tax, igst=Decimal(0))
        line['total'] = taxable + line['cgst'] + line['sgst'] + line['igst']
    totals = {key: sum((line[key] for line in lines), Decimal(0)) for key in ['subtotal', 'discount', 'cgst', 'sgst', 'igst', 'total']}
    if totals['total'] > Decimal('999999999999.99'): raise ValidationError('Invoice amount exceeds the supported limit.')
    return lines, totals

def prepare_invoice(business, data, lock=False):
    try: customer = Customer.objects.get(pk=data['customer'], business=business, merged_into__isnull=True, is_active=True)
    except Customer.DoesNotExist: raise ValidationError({'customer': 'Customer does not belong to this business.'})
    qs = Product.objects.filter(business=business, pk__in=[i['product'] for i in data['items']]).order_by('pk')
    if lock: qs = qs.select_for_update()
    products = {p.pk: p for p in qs}
    settings = business.settings
    supply = data.get('supply_state') or customer.state_code or business.state_code
    if data['gst_enabled'] and not business.gstin: raise ValidationError('Configure your business GSTIN before creating GST invoices.')
    lines, totals = calculate_lines(products, data['items'], data['discount'], data['gst_enabled'], supply != business.state_code)
    for line in lines:
        if not settings.allow_negative_stock and line['product'].stock < line['quantity']:
            raise ValidationError(f"Insufficient stock for {line['description']} ({line['product'].stock} available).")
    paid = initial_payment(data, totals['total'])
    if paid > totals['total']: raise ValidationError('Paid amount cannot exceed invoice total.')
    if data.get('payment_status') == 'partial' and not 0 < paid < totals['total']:
        raise ValidationError('Partial payment must be greater than zero and less than the total.')
    if data['include_upi_qr'] and (not settings.upi_id or not settings.upi_payee_name):
        raise ValidationError('Configure your UPI ID and payee name in Settings first.')
    return customer, supply, lines, totals

def initial_payment(data, total):
    status = data.get('payment_status')
    return total if status == 'paid' else Decimal(0) if status == 'unpaid' else data['paid_amount']

def quote_payload(lines, totals):
    data = {'totals': {key:str(value) for key,value in totals.items()}, 'items': [
        {key:str(line[key]) for key in ['sku','description','unit_price','gst_rate','quantity','total']} for line in lines]}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

@transaction.atomic
def create_invoice(user, business, data):
    # Serializes numbers and all writes for a tenant; locks are held until every row is committed.
    business = Business.objects.select_related('settings').select_for_update(of=('self',)).get(pk=business.pk)
    if not business.is_active: raise ValidationError('This business is suspended.')
    request_hash = hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
    existing = Invoice.objects.filter(business=business, idempotency_key=data['idempotency_key']).first()
    if existing:
        if existing.request_hash != request_hash: raise ValidationError('This submission key was already used for a different invoice.')
        return existing, False
    customer, supply, lines, totals = prepare_invoice(business, data, lock=True)
    if 'expected_total' in data and data['expected_total'] != totals['total']:
        raise ValidationError('The total changed. Refresh the product list and review the amounts before saving.')
    if data.get('quote_token'):
        try: quoted = signing.loads(data['quote_token'], salt='invoice-preview', max_age=600)
        except signing.BadSignature: raise ValidationError('Your preview has expired. Preview the invoice again before saving.')
        if quoted != quote_payload(lines, totals):
            raise ValidationError('Product prices or tax rates changed after your preview. Preview the invoice again before saving.')
    settings = business.settings
    logo_key = ''
    previous = Invoice.objects.filter(business=business, customer=customer, cancelled_at__isnull=True).aggregate(value=Sum('total'))['value'] or Decimal(0)
    if settings.logo_data:
        logo, _ = InvoiceLogo.objects.get_or_create(business=business, digest=hashlib.sha256(settings.logo_data.encode()).hexdigest(), defaults={'data':settings.logo_data})
        logo_key = str(logo.pk)
    invoice = Invoice.objects.create(business=business, number=f'{settings.invoice_prefix}-{business.next_invoice_number:06d}',
        idempotency_key=data['idempotency_key'], request_hash=request_hash, customer=customer,
        customer_snapshot={**{key: getattr(customer, key) for key in ['name', 'mobile', 'whatsapp', 'address', 'gstin']},
                           'previous_purchases': str(previous), 'purchases_after': str(previous + totals['total'])},
        business_snapshot={**{key: getattr(business, key) for key in ['name', 'address', 'gstin', 'mobile', 'state_code']},
            **{key: getattr(settings, key) for key in ['upi_id', 'upi_payee_name', 'invoice_footer']}, 'logo_key':logo_key},
        date=data.get('date') or timezone.now().astimezone(ZoneInfo(settings.timezone)).date(),
        due_date=data.get('due_date'), supply_state=supply, gst_enabled=data['gst_enabled'],
        paid_amount=initial_payment(data, totals['total']), payment_method=data['payment_method'], include_upi_qr=data['include_upi_qr'],
        notes=data.get('notes', ''), created_by=user, **totals)
    InvoiceItem.objects.bulk_create([InvoiceItem(invoice=invoice, **line) for line in lines])
    for line in lines:
        product = line['product']
        product.stock -= line['quantity']
    Product.objects.bulk_update([line['product'] for line in lines], ['stock'])
    business.next_invoice_number += 1
    business.save(update_fields=['next_invoice_number'])
    if invoice.paid_amount:
        Payment.objects.create(business=business, invoice=invoice, amount=invoice.paid_amount,
            method=invoice.payment_method, recorded_by=user)
    audit(user, business, 'invoice.created', invoice.pk)
    return invoice, True

@transaction.atomic
def record_payment(user, business, invoice_id, data):
    # Lock business first everywhere to maintain deterministic lock order and safe idempotency across invoices.
    locked_business = Business.objects.select_for_update().get(pk=business.pk)
    if not locked_business.is_active: raise ValidationError('This business is suspended.')
    try: invoice = Invoice.objects.select_for_update().get(pk=invoice_id, business=business)
    except Invoice.DoesNotExist: raise ValidationError('Invoice not found.')
    existing = Payment.objects.filter(business=business, idempotency_key=data['idempotency_key']).first()
    if existing:
        if (existing.invoice_id != invoice.pk or existing.amount != data['amount'] or existing.method != data['method']
                or existing.reference != data.get('reference', '')):
            raise ValidationError('This submission key was already used for a different payment.')
        return existing
    if invoice.cancelled_at: raise ValidationError('Cancelled invoices cannot receive payments.')
    if data['amount'] > invoice.balance: raise ValidationError('Payment exceeds the remaining balance.')
    payment = Payment.objects.create(business=business, invoice=invoice, recorded_by=user, **data)
    invoice.paid_amount += payment.amount
    invoice.revision += 1
    invoice.save(update_fields=['paid_amount', 'revision'])
    audit(user, business, 'payment.recorded', payment.pk)
    return payment

@transaction.atomic
def cancel_invoice(user, business, invoice_id, reason, refund_confirmed=False):
    Business.objects.select_for_update().get(pk=business.pk)
    invoice = Invoice.objects.select_for_update().get(pk=invoice_id, business=business)
    if invoice.cancelled_at: return invoice
    if not reason.strip(): raise ValidationError('Enter a cancellation reason.')
    if invoice.paid_amount and not refund_confirmed:
        raise ValidationError('Refund the full received amount first, then confirm the refund. No money is sent automatically.')
    if PrintJob.objects.filter(invoice=invoice, status='processing').exists():
        raise ValidationError('A print job is in progress. Wait for its result before cancelling.')
    if invoice.paid_amount:
        Refund.objects.create(business=business, invoice=invoice, amount=invoice.paid_amount, recorded_by=user)
    for item in invoice.items.order_by('product_id'):
        product = Product.objects.select_for_update().get(pk=item.product_id, business=business)
        product.stock += item.quantity
        product.save(update_fields=['stock'])
    invoice.cancelled_at = timezone.now()
    invoice.cancellation_reason = reason.strip()
    invoice.revision += 1
    invoice.save(update_fields=['cancelled_at', 'cancellation_reason', 'revision'])
    invoice.sharing_tokens.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
    PrintJob.objects.filter(invoice=invoice, status='queued').update(status='cancelled', detail='Invoice cancelled.')
    audit(user, business, 'invoice.cancelled', invoice.pk)
    return invoice

def upi_uri(invoice):
    if not invoice.include_upi_qr or invoice.balance <= 0: return ''
    snapshot = invoice.business_snapshot
    return 'upi://pay?' + urlencode({'pa': snapshot['upi_id'], 'pn': snapshot['upi_payee_name'],
        'am': f'{invoice.balance:.2f}', 'cu': 'INR', 'tn': f'Invoice {invoice.number}', 'tr': str(invoice.pk)}, quote_via=quote)

def whatsapp_link(invoice, url):
    from .validation import mobile
    phone = mobile(invoice.customer_snapshot.get('whatsapp') or invoice.customer_snapshot['mobile']).lstrip('+')
    message = (f"Hello {invoice.customer_snapshot['name']} 👋\n\n"
               f"Thank you for shopping with {invoice.business_snapshot['name']}!\n\n"
               f"Invoice: {invoice.number}\nAmount: ₹{invoice.total:,.2f}\nBalance due: ₹{invoice.balance:,.2f}\n\n"
               f"View or download your invoice:\n{url}\n\nThank you for your business!")
    return {'message': message, 'whatsapp_url': f'https://wa.me/{phone}?text={quote(message)}'}
