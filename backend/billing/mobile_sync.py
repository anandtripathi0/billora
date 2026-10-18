"""Transactional native sync. The tenant row is the serialization lock shared with web billing.

The compatibility feed fingerprints current records on pull, so web bulk writes/imports
and deletions are included without fragile signal hooks. It is incremental on the wire;
the scan is deliberately not advertised as a scalable CDC implementation.
"""
import hashlib
import json
import uuid
from decimal import Decimal
from zoneinfo import ZoneInfo
from django.core import signing
from django.db import transaction, IntegrityError
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from . import models as m, serializers as s
from .mobile_auth import DeviceAuthentication
from .services import calculate_lines, initial_payment, record_payment, audit


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(',', ':')).encode()).hexdigest()


def identity(business, kind, server_id):
    cache = getattr(business, '_mobile_identities', None)
    if cache is not None:
        return cache.get((kind, str(server_id)), str(uuid.uuid5(business.pk, f'{kind}:{server_id}')))
    mapping = m.MobileMapping.objects.filter(business=business, kind=kind, server_id=str(server_id)).first()
    return str(mapping.local_id) if mapping else str(uuid.uuid5(business.pk, f'{kind}:{server_id}'))


def resolve(business, kind, local_id):
    try: local_id = uuid.UUID(str(local_id))
    except (ValueError, TypeError): raise ValidationError('Invalid record UUID.')
    mapping = m.MobileMapping.objects.filter(business=business, kind=kind, local_id=local_id).first()
    if not mapping: raise ValidationError('A dependency has not synchronized. Sync its creation first.')
    model = {'product': m.Product, 'customer': m.Customer, 'invoice': m.Invoice}[kind]
    obj = model.objects.filter(business=business, pk=mapping.server_id).first()
    if not obj: raise ValidationError('Record was removed on another device.')
    return obj


def wire(business, kind, obj):
    cls = {'business': s.BusinessSerializer, 'product': s.ProductSerializer, 'customer': s.CustomerSerializer,
           'invoice': s.InvoiceSerializer, 'payment': s.PaymentSerializer}[kind]
    data = json.loads(json.dumps(cls(obj).data, default=str))
    data['id'] = str(business.pk) if kind == 'business' else identity(business, kind, obj.pk)
    if kind == 'invoice':
        data['customer'] = identity(business, 'customer', obj.customer_id)
        for item in data['items']: item['product'] = identity(business, 'product', item['product'])
    if kind == 'payment': data['invoice'] = identity(business, 'invoice', obj.invoice_id)
    return data


def refresh_feed(business):
    """Caller holds tenant lock; journal entries and watermark commit atomically."""
    current = {(r.kind, str(r.local_id)): r for r in m.MobileRecord.objects.filter(business=business)}
    business._mobile_identities = {(r.kind, r.server_id): str(r.local_id) for r in m.MobileMapping.objects.filter(business=business)}
    seen = set()
    groups = [('business', [business]), ('product', m.Product.objects.filter(business=business).select_related('category')),
              ('customer', m.Customer.objects.filter(business=business)),
              ('invoice', m.Invoice.objects.filter(business=business).prefetch_related('items')),
              ('payment', m.Payment.objects.filter(business=business).select_related('invoice'))]
    missing, new_records, updated_records, journal = [], [], [], []
    for kind, objects in groups:
        for obj in objects:
            local_id = str(business.pk) if kind == 'business' else identity(business, kind, obj.pk)
            if (kind, str(obj.pk)) not in business._mobile_identities:
                missing.append(m.MobileMapping(business=business, kind=kind, server_id=str(obj.pk), local_id=local_id))
                business._mobile_identities[(kind, str(obj.pk))] = local_id
            if kind == 'invoice': obj.ordered_items = sorted(obj.items.all(), key=lambda i: i.pk)
            data = wire(business, kind, obj)
            key = (kind, local_id); seen.add(key)
            version = fingerprint(data); old = current.get(key)
            if not old or old.version != version or old.deleted:
                if old:
                    old.version = version; old.deleted = False; updated_records.append(old)
                else: new_records.append(m.MobileRecord(business=business, kind=kind, local_id=local_id, version=version))
                journal.append(m.MobileChange(business=business, kind=kind, local_id=local_id, version=version, data=data))
    m.MobileMapping.objects.bulk_create(missing)
    for key, old in current.items():
        if key not in seen and not old.deleted:
            old.deleted = True; old.version = fingerprint({'deleted': True, 'previous': old.version}); updated_records.append(old)
            journal.append(m.MobileChange(business=business, kind=old.kind, local_id=old.local_id, version=old.version, data=None))
    m.MobileRecord.objects.bulk_create(new_records, batch_size=500)
    m.MobileRecord.objects.bulk_update(updated_records, ['version', 'deleted'], batch_size=500)
    m.MobileChange.objects.bulk_create(journal, batch_size=500)


class OperationInput(serializers.Serializer):
    id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=['business.settings', 'product.create', 'product.update', 'product.delete', 'stock.adjust',
        'customer.create', 'customer.update', 'customer.delete', 'invoice.create', 'payment.create'])
    record_id = serializers.UUIDField()
    base_version = serializers.CharField(max_length=64, required=False, allow_blank=True)
    data = serializers.JSONField()


def check_version(business, kind, obj, op):
    if fingerprint(wire(business, kind, obj)) != op.get('base_version'):
        raise ValidationError('Changed on another device. Review both versions before submitting a new operation.')


def apply_operation(user, business, device, op):
    kind, action = op['kind'].split('.')
    body = op['data']
    if not isinstance(body, dict): raise ValidationError('Operation data must be an object.')
    role = user.membership.role
    if role == 'viewer' or (kind in ['business', 'product', 'stock'] or action == 'delete') and role not in ['owner', 'manager']:
        raise PermissionDenied('Your role does not allow this change.')
    if kind == 'business':
        if str(op['record_id']) != str(business.pk): raise PermissionDenied('Invalid business.')
        check_version(business, 'business', business, op)
        if set(body) - {'upi_id','upi_payee_name','receipt_width','invoice_footer'}: raise ValidationError('Unsupported mobile setting.')
        serializer = s.SettingsSerializer(business.settings, data=body, partial=True)
        serializer.is_valid(raise_exception=True); serializer.save()
        audit(user, business, 'mobile.settings.updated', business.pk)
        return {'record_id': str(business.pk)}
    if kind in ['product', 'customer']:
        model = m.Product if kind == 'product' else m.Customer
        cls = s.ProductSerializer if kind == 'product' else s.CustomerSerializer
        obj = resolve(business, kind, op['record_id']) if action != 'create' else None
        if obj: check_version(business, kind, obj, op)
        if action == 'delete':
            # Native deletes retain a tombstoned row and all financial relations.
            obj.is_active = False
            if kind == 'customer':
                obj.name = 'Deleted customer'
                obj.mobile = obj.whatsapp = obj.address = obj.gstin = obj.state_code = ''
                obj.consent_whatsapp = False
            obj.save(); audit(user, business, f'mobile.{kind}.archived', obj.pk)
            return {'record_id': str(op['record_id'])}
        if obj and not obj.is_active: raise ValidationError('Archived records cannot be edited offline.')
        allowed = {'name', 'sku', 'selling_price', 'purchase_price', 'gst_rate', 'unit', 'price_includes_tax', 'hsn_code', 'low_stock_threshold'} if kind == 'product' else {'name', 'mobile', 'whatsapp', 'address', 'gstin', 'state_code', 'consent_whatsapp'}
        if kind == 'product' and action == 'create': allowed.add('stock')
        if set(body) - allowed: raise ValidationError('Unsupported fields. Stock changes require stock.adjust events.')
        if kind == 'customer' and 'mobile' in body:
            from .validation import mobile
            duplicate = m.Customer.objects.filter(business=business, mobile=mobile(body['mobile']), is_active=True, merged_into__isnull=True)
            if obj: duplicate = duplicate.exclude(pk=obj.pk)
            if duplicate.exists(): raise ValidationError('An active customer already has this mobile. Select the existing customer; no automatic merge was performed.')
        serializer = cls(obj, data=body, partial=bool(obj), context={'business': business})
        serializer.is_valid(raise_exception=True); obj = serializer.save(business=business)
        if action == 'create':
            m.MobileMapping.objects.create(business=business, kind=kind, local_id=op['record_id'], server_id=str(obj.pk))
        audit(user, business, f'mobile.{op["kind"]}', obj.pk)
        return {'record_id': str(op['record_id'])}
    if kind == 'stock':
        product = resolve(business, 'product', op['record_id'])
        field = serializers.DecimalField(max_digits=12, decimal_places=3)
        delta = field.run_validation(body.get('delta'))
        reason = str(body.get('reason', '')).strip()
        if not reason or len(reason) > 200 or not delta: raise ValidationError('Provide a nonzero stock change and a reason (up to 200 characters).')
        if not product.is_active: raise ValidationError('Product is archived.')
        product.stock += delta
        if abs(product.stock) > Decimal('999999999.999'): raise ValidationError('Stock exceeds the supported limit.')
        product.save(update_fields=['stock']); audit(user, business, 'mobile.stock.adjusted', product.pk)
        return {'warning': 'Negative stock needs reconciliation.' if product.stock < 0 else ''}
    if kind == 'payment':
        invoice = resolve(business, 'invoice', body.get('invoice'))
        serializer = s.PaymentInput(data={**body, 'idempotency_key': op['id']}); serializer.is_valid(raise_exception=True)
        payment = record_payment(user, business, invoice.pk, serializer.validated_data)
        m.MobileMapping.objects.get_or_create(business=business, kind='payment', local_id=op['record_id'], defaults={'server_id': str(payment.pk)})
        return {'record_id': str(op['record_id'])}
    if kind == 'invoice': return save_sale(user, business, device, op)
    raise ValidationError('Unsupported operation.')


def save_sale(user, business, device, op):
    """Keep an immutable submitted event, revalidate math, and permit audited offline overselling."""
    body = op['data']
    customer = resolve(business, 'customer', body.get('customer'))
    if not customer.is_active: raise ValidationError('Customer was archived. Original bill retained for reconciliation.')
    selections, products = [], {}
    raw_items = body.get('items')
    if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= 100: raise ValidationError('Use 1–100 invoice lines.')
    for item in raw_items:
        if not isinstance(item, dict): raise ValidationError('Invalid invoice line.')
        product = resolve(business, 'product', item.get('product'))
        # Do not reinterpret tax after a product edit. Hold the financial event for review.
        rate = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal(0), max_value=Decimal(100)).run_validation(item.get('gst_rate', '0'))
        includes = serializers.BooleanField().run_validation(item.get('price_includes_tax', False))
        if not product.is_active or includes != product.price_includes_tax or (body.get('gst_enabled') and rate != product.gst_rate):
            raise ValidationError('Product tax/availability changed. Original offline bill is preserved; accountant review required.')
        if any(key in item and str(item[key]) != str(getattr(product, field)) for key, field in [('description', 'name'), ('sku', 'sku'), ('unit', 'unit'), ('hsn_code', 'hsn_code')]):
            raise ValidationError('Product description changed. Original offline bill retained for review.')
        products[product.pk] = product
        selections.append({**item, 'product': product.pk})
    serializer = s.InvoiceInput(data={**body, 'customer': customer.pk, 'items': selections, 'idempotency_key': op['id']})
    serializer.is_valid(raise_exception=True); data = serializer.validated_data
    supply = data.get('supply_state') or customer.state_code or business.state_code
    if data['gst_enabled'] and not business.gstin: raise ValidationError('GSTIN required before issuing a tax invoice.')
    lines, totals = calculate_lines(products, data['items'], data['discount'], data['gst_enabled'], supply != business.state_code)
    if 'expected_total' not in data or data['expected_total'] != totals['total']:
        raise ValidationError('Offline total does not match server rounding. Original document retained.')
    paid = initial_payment(data, totals['total'])
    if paid > totals['total'] or data.get('payment_status') == 'partial' and not 0 < paid < totals['total']:
        raise ValidationError('Invalid payment amount.')
    issued_date = data.get('date')
    if not issued_date: raise ValidationError('Offline issue date required.')
    if issued_date > timezone.now().astimezone(ZoneInfo(business.settings.timezone)).date():
        raise ValidationError('Device issue date is in the future. Correct the device clock and reconcile this document.')
    fiscal = issued_date.year if issued_date.month >= 4 else issued_date.year - 1
    number = body.get('number', '')
    provisional = not number
    if number:
        try:
            prefix, sequence = number.split('-'); sequence = int(sequence)
        except (ValueError, TypeError): raise ValidationError('Invalid reserved number.')
        expected = f'M{fiscal % 100:02d}-{sequence:010d}'
        if number != expected or not m.MobileNumberRange.objects.filter(business=business, device=device, fiscal_year=fiscal, start__lte=sequence, end__gte=sequence).exists():
            raise ValidationError('Invoice number is not allocated to this device for this financial year.')
    else:
        sequence = business.next_invoice_number
        if sequence > 9999999999: raise ValidationError('Number series exhausted.')
        number = f'M{fiscal % 100:02d}-{sequence:010d}'
        business.next_invoice_number += 1; business.save(update_fields=['next_invoice_number'])
    if m.Invoice.objects.filter(business=business, number=number).exists(): raise ValidationError('Invoice number already used. Original bill retained for review.')
    if m.Invoice.objects.filter(pk=op['record_id']).exists(): raise ValidationError('Invoice UUID already used.')
    warning = []
    for line in lines:
        if line['product'].stock < line['quantity']: warning.append(f"Stock reconciliation required: {line['sku']}")
    # Customer and business snapshots are validated against the last pulled version by
    # the client's immutable receipt; original snapshots are also in MobileOperation.payload.
    snapshot_customer = body.get('customer_snapshot', {})
    snapshot_business = body.get('business_snapshot', {})
    if not isinstance(snapshot_customer, dict) or not isinstance(snapshot_business, dict): raise ValidationError('Invalid snapshots.')
    # Use trusted business identity; keep the original device document separately for audit.
    business_snapshot = {k: getattr(business, k) for k in ['name', 'address', 'gstin', 'mobile', 'state_code']}
    business_snapshot.update({k: getattr(business.settings, k) for k in ['upi_id', 'upi_payee_name', 'invoice_footer']})
    customer_snapshot = {k: getattr(customer, k) for k in ['name', 'mobile', 'whatsapp', 'address', 'gstin']}
    for source, trusted in [(snapshot_customer, customer_snapshot), (snapshot_business, business_snapshot)]:
        if any(str(source.get(key, '')) != str(value) for key, value in trusted.items() if key in source):
            raise ValidationError('Business/customer details changed. Original offline snapshot retained for review.')
    invoice = m.Invoice.objects.create(id=op['record_id'], business=business, number=number, idempotency_key=op['id'],
        request_hash=fingerprint(op), customer=customer, customer_snapshot=customer_snapshot, business_snapshot=business_snapshot,
        date=issued_date, supply_state=supply, gst_enabled=data['gst_enabled'], paid_amount=paid,
        payment_method=data['payment_method'], include_upi_qr=data['include_upi_qr'], notes=data.get('notes', ''), created_by=user, **totals)
    m.InvoiceItem.objects.bulk_create([m.InvoiceItem(invoice=invoice, **line) for line in lines])
    for line in lines:
        product = line['product']; product.stock -= line['quantity']; product.save(update_fields=['stock'])
    if paid: m.Payment.objects.create(business=business, invoice=invoice, amount=paid, method=invoice.payment_method, idempotency_key=op['id'], recorded_by=user)
    m.MobileMapping.objects.create(business=business, kind='invoice', local_id=op['record_id'], server_id=str(invoice.pk))
    audit(user, business, 'mobile.invoice.created', invoice.pk)
    return {'record_id': str(op['record_id']), 'number': number, 'finalized_provisional': provisional, 'warning': '; '.join(warning)}


class MobileView(APIView):
    authentication_classes = [DeviceAuthentication]
    permission_classes = [IsAuthenticated]


class SyncPush(MobileView):
    def post(self, request):
        serializer = OperationInput(data=request.data); serializer.is_valid(raise_exception=True)
        op = serializer.validated_data
        if len(json.dumps(request.data)) > 200000: raise ValidationError('Operation too large.')
        business = request.user.membership.business
        with transaction.atomic():
            business = m.Business.objects.select_related('settings').select_for_update(of=('self',)).get(pk=business.pk)
            if not business.is_active: raise PermissionDenied('Business suspended.')
            old = m.MobileOperation.objects.filter(business=business, operation_id=op['id']).first()
            request_hash = fingerprint(request.data)
            if old:
                if old.request_hash != request_hash: return Response({'detail': 'Operation UUID reused with a different payload.'}, status=409)
                return Response(old.result)
            try:
                with transaction.atomic(): result = {'status': 'accepted', **apply_operation(request.user, business, request.auth, op)}
            except (ValidationError, PermissionDenied) as exc:
                result = {'status': 'conflict', 'detail': str(exc.detail)}
            except IntegrityError:
                result = {'status': 'conflict', 'detail': 'Record or number already exists. Review the original event; nothing was overwritten.'}
            m.MobileOperation.objects.create(business=business, device=request.auth, operation_id=op['id'], request_hash=request_hash, payload=request.data, result=result)
        return Response(result)


class SyncPull(MobileView):
    def get(self, request):
        business = request.user.membership.business
        cursor = request.query_params.get('cursor', '')
        after = 0
        if cursor:
            try:
                decoded = signing.loads(cursor, salt='mobile-pull')
                if decoded['business'] != str(business.pk): raise signing.BadSignature()
                after = int(decoded['after'])
            except (signing.BadSignature, KeyError, ValueError, TypeError): raise ValidationError('Invalid tenant cursor.')
        with transaction.atomic():
            business = m.Business.objects.select_related('settings').select_for_update(of=('self',)).get(pk=business.pk)
            refresh_feed(business)
            changes = list(m.MobileChange.objects.filter(business=business, pk__gt=after).order_by('pk')[:201])
            page = changes[:200]
            if page: after = page[-1].pk
            cursor = signing.dumps({'business': str(business.pk), 'after': after}, salt='mobile-pull')
            return Response({'changes': [{'kind': c.kind, 'id': str(c.local_id), 'version': c.version, 'data': c.data} for c in page],
                             'cursor': cursor, 'has_more': len(changes) > 200, 'role': request.user.membership.role})


class NumberRanges(MobileView):
    def get(self, request):
        return Response(list(m.MobileNumberRange.objects.filter(device=request.auth, business_id=request.auth.business_id).values('id', 'fiscal_year', 'start', 'end')))
    def post(self, request):
        if request.user.membership.role not in ['owner', 'manager', 'cashier']: raise PermissionDenied('Billing role required.')
        business = request.user.membership.business
        today = timezone.now().astimezone(ZoneInfo(business.settings.timezone)).date()
        fiscal = today.year if today.month >= 4 else today.year - 1
        with transaction.atomic():
            business = m.Business.objects.select_for_update().get(pk=business.pk)
            # Allocation request UUID is the idempotency key; retry never burns another range.
            try: range_id = uuid.UUID(str(request.data.get('id')))
            except (TypeError, ValueError): raise ValidationError('Allocation UUID required.')
            allocation = m.MobileNumberRange.objects.filter(pk=range_id, device=request.auth).first()
            if not allocation:
                if m.MobileNumberRange.objects.filter(pk=range_id).exists(): raise ValidationError('Allocation UUID already used.')
                start = business.next_invoice_number; end = start + 99
                if end > 9999999999: raise ValidationError('Number series exhausted.')
                allocation = m.MobileNumberRange.objects.create(id=range_id, business=business, device=request.auth, fiscal_year=fiscal, start=start, end=end)
                business.next_invoice_number = end + 1; business.save(update_fields=['next_invoice_number'])
                audit(request.user, business, 'mobile.numbers.reserved', allocation.pk)
            return Response({'id': str(allocation.pk), 'fiscal_year': allocation.fiscal_year, 'start': allocation.start, 'end': allocation.end})
