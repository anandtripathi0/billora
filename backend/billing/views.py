import csv
import hashlib
import io
import logging
import secrets
import uuid
from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from django.conf import settings
from django.core import signing
from django.db import transaction, IntegrityError, connection
from django.db.models import Sum, F, Q, Count, DecimalField, ExpressionWrapper
from django.db.models.functions import Coalesce, TruncMonth
from django.http import HttpResponse
from rest_framework.generics import get_object_or_404
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.views import APIView
from . import models as m, serializers as s
from .permissions import TenantPermission, SuperAdminPermission, tenant
from .services import create_invoice, prepare_invoice, record_payment, audit, upi_uri, whatsapp_link, quote_payload, initial_payment, cancel_invoice
from .collections import customer_totals
from .validation import mobile as normalize_mobile
from .pdf import qr_data, invoice_pdf, pdf_response, render_pdf
from .auth import rate_limit
from .flags import require_feature

def aggregate_money(qs, expression):
    return qs.aggregate(value=Coalesce(Sum(expression), Decimal(0), output_field=DecimalField()))['value']

class TenantViewSet(viewsets.ModelViewSet):
    permission_classes = [TenantPermission]
    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    def get_queryset(self): return self.queryset.filter(business=tenant(self.request)).order_by('-pk')
    def get_serializer_context(self): return {**super().get_serializer_context(), 'business': tenant(self.request)}
    def perform_create(self, serializer):
        try:
            with transaction.atomic():
                business = m.Business.objects.select_for_update().get(pk=tenant(self.request).pk)
                obj = serializer.save(business=business)
                audit(self.request.user, obj.business, f'{obj._meta.model_name}.created', obj.pk)
        except IntegrityError: raise ValidationError('A record with this identifier already exists.')
    def perform_update(self, serializer):
        try:
            with transaction.atomic():
                # Stock edits and invoice creation lock the tenant in the same order.
                m.Business.objects.select_for_update().get(pk=tenant(self.request).pk)
                serializer.instance = get_object_or_404(type(serializer.instance).objects.select_for_update(), pk=serializer.instance.pk, business=tenant(self.request))
                if isinstance(serializer.instance, m.Customer) and not serializer.instance.is_active:
                    raise ValidationError('This customer has been deleted and cannot be edited.')
                obj = serializer.save()
                audit(self.request.user, obj.business, f'{obj._meta.model_name}.updated', obj.pk)
        except IntegrityError: raise ValidationError('A record with this identifier already exists.')

    def destroy(self, request, pk=None):
        if request.user.membership.role not in ['owner', 'manager']:
            raise PermissionDenied('Only store owners and managers can delete records.')
        model = self.queryset.model
        if model not in [m.Product, m.Customer]: raise PermissionDenied('Deletion is not supported.')
        with transaction.atomic():
            # Use the same tenant-first lock order as invoices, imports and stock edits.
            business = m.Business.objects.select_for_update().get(pk=tenant(request).pk)
            obj = get_object_or_404(model.objects.select_for_update(), pk=pk, business=business)
            object_id = obj.pk
            protected = m.InvoiceItem.objects.filter(product=obj).exists() if model == m.Product else (
                obj.invoices.exists() or m.Customer.objects.filter(merged_into=obj).exists())
            if protected:
                obj.is_active = False
                if model == m.Customer:
                    obj.name = 'Deleted customer'
                    obj.mobile = obj.whatsapp = obj.address = obj.gstin = obj.state_code = ''
                    obj.consent_whatsapp = False
                    obj.save(update_fields=['is_active', 'name', 'mobile', 'whatsapp', 'address', 'gstin', 'state_code', 'consent_whatsapp'])
                else: obj.save(update_fields=['is_active'])
                outcome = 'archived'
            else:
                obj.delete()
                outcome = 'deleted'
            audit(request.user, business, f'{model._meta.model_name}.{outcome}', object_id)
        label = 'Product' if model == m.Product else 'Customer'
        return Response({'outcome': outcome, 'detail': f'{label} deleted.' if outcome == 'deleted' else
            f'{label} removed from active lists. Invoice and payment history is preserved.'})

class CategoryViewSet(TenantViewSet):
    queryset = m.Category.objects.all()
    serializer_class = s.CategorySerializer
    write_roles = ['owner', 'manager']
    search_fields = ['name']

class ProductViewSet(TenantViewSet):
    http_method_names = [*TenantViewSet.http_method_names, 'delete']
    queryset = m.Product.objects.select_related('category')
    serializer_class = s.ProductSerializer
    search_fields = ['name', 'sku', 'barcode', 'brand', 'pack_size']
    write_roles = ['owner', 'manager']
    def get_queryset(self):
        qs = super().get_queryset()
        review = self.request.query_params.get('needs_review') == 'true'
        if self.action == 'list' and self.request.query_params.get('archived') != 'true' and not review: qs = qs.filter(is_active=True)
        if review: qs = qs.filter(price_verification_status='needs_review')
        if self.request.query_params.get('brand'): qs = qs.filter(brand=self.request.query_params['brand'])
        category = self.request.query_params.get('category')
        if category:
            if not category.isdigit(): raise ValidationError('Invalid category.')
            qs = qs.filter(category_id=int(category))
        if self.request.query_params.get('low_stock') == 'true': qs = qs.filter(stock__lte=F('low_stock_threshold'))
        return qs
    @action(detail=False, methods=['get'])
    def filters(self, request):
        business = tenant(request)
        return Response({'brands':list(m.Product.objects.filter(business=business).exclude(brand='').order_by('brand').values_list('brand', flat=True).distinct()),
            'categories':list(m.Category.objects.filter(business=business).order_by('name').values('id','name'))})
    def catalog_rows(self, request):
        from .inventory import read_catalog, MAX_BYTES
        require_feature('CSV_IMPORT_ENABLED')
        if request.user.membership.role != 'owner': raise PermissionDenied('The business owner must confirm starter inventory imports.')
        upload = request.FILES.get('file')
        if upload:
            if upload.size > MAX_BYTES: raise ValidationError('Catalog files must be no larger than 1 MB.')
            return read_catalog(upload.read(), upload.name)
        return read_catalog()
    @action(detail=False, methods=['post'], url_path='catalog-preview')
    def catalog_preview(self, request):
        from .inventory import preview_catalog
        return Response(preview_catalog(request.user, tenant(request), self.catalog_rows(request)))
    @action(detail=False, methods=['post'], url_path='catalog-import')
    def catalog_import(self, request):
        from .inventory import confirm_catalog
        rows = self.catalog_rows(request)
        confirmed = request.data.get('confirmed')
        if request.FILES: confirmed = confirmed == 'true'
        return Response(confirm_catalog(request.user, tenant(request), rows, request.data.get('confirmation_token'), confirmed))
    @action(detail=False, methods=['get'], url_path='catalog-file')
    def catalog_file(self, request):
        import json
        from .inventory import read_catalog, validate_catalog, json_safe
        rows = json_safe(validate_catalog(read_catalog(), tenant(request)))
        extension = request.query_params.get('export', 'json')
        if extension == 'csv':
            output = io.StringIO(); writer = csv.DictWriter(output, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
            response = HttpResponse('\ufeff'+output.getvalue(), content_type='text/csv; charset=utf-8')
        elif extension == 'json': response = HttpResponse(json.dumps({'products':rows}, indent=2), content_type='application/json')
        else: raise ValidationError('Choose csv or json.')
        response['Content-Disposition'] = f'attachment; filename="kirana_catalog.{extension}"'
        return response
    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        with transaction.atomic():
            business = tenant(request)
            m.Business.objects.select_for_update().get(pk=business.pk)
            obj = self.get_object(); obj.is_active = False; obj.save(update_fields=['is_active'])
            audit(request.user, business, 'product.archived', obj.pk)
        return Response({'detail': 'Product archived.'})
    @action(detail=False, methods=['post'], url_path='import-csv')
    def import_csv(self, request):
        require_feature('CSV_IMPORT_ENABLED')
        upload = request.FILES.get('file')
        if not upload or upload.size > 1024 * 1024: raise ValidationError('Upload a CSV file smaller than 1 MB.')
        try: rows = list(csv.DictReader(io.StringIO(upload.read().decode('utf-8-sig'))))
        except (UnicodeDecodeError, csv.Error): raise ValidationError('Invalid UTF-8 CSV file.')
        if not rows or len(rows) > 500: raise ValidationError('Import between 1 and 500 rows at a time.')
        business = tenant(request)
        with transaction.atomic():
            m.Business.objects.select_for_update().get(pk=business.pk)
            for index, row in enumerate(rows, 2):
                row = {k: v for k, v in row.items() if v not in ['', None] and k in ['name', 'sku', 'selling_price', 'purchase_price', 'gst_rate', 'hsn_code', 'stock', 'unit', 'barcode', 'description', 'low_stock_threshold']}
                serializer = self.get_serializer(data=row)
                if not serializer.is_valid(): raise ValidationError({'row': index, 'errors': serializer.errors})
                serializer.save(business=business)
            audit(request.user, business, 'products.imported', len(rows))
        return Response({'imported': len(rows)})

class CustomerViewSet(TenantViewSet):
    http_method_names = [*TenantViewSet.http_method_names, 'delete']
    queryset = m.Customer.objects.all()
    serializer_class = s.CustomerSerializer
    search_fields = ['name', 'mobile', 'gstin']
    def get_queryset(self):
        qs = super().get_queryset().filter(merged_into__isnull=True)
        if self.action not in ['retrieve', 'ledger']: qs = qs.filter(is_active=True)
        return customer_totals(qs)
    @action(detail=False, methods=['get'])
    def lookup(self, request):
        phone = normalize_mobile(request.query_params.get('mobile', ''))
        row = self.get_queryset().filter(mobile=phone).first()
        return Response({'customer': self.get_serializer(row).data if row else None, 'mobile': phone})
    @action(detail=False, methods=['post'])
    def quick(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            business = m.Business.objects.select_for_update().get(pk=tenant(request).pk)
            row = self.get_queryset().filter(mobile=serializer.validated_data['mobile']).first()
            created = row is None
            if created:
                row = serializer.save(business=business)
                audit(request.user, business, 'customer.created', row.pk)
            return Response(self.get_serializer(row).data, status=201 if created else 200)
    @action(detail=True, methods=['get'])
    def ledger(self, request, pk=None):
        customer = self.get_object()
        invoices = customer.invoices.order_by('date', 'created_at', 'pk')
        page = self.paginate_queryset(invoices)
        return self.get_paginated_response(s.InvoiceListSerializer(page, many=True).data)

class InvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [TenantPermission]
    search_fields = ['number', 'customer_snapshot__name']
    def get_queryset(self):
        qs = m.Invoice.objects.filter(business=tenant(self.request)).order_by('-date', '-created_at')
        if self.action == 'list': qs = qs.defer('business_snapshot', 'notes', 'request_hash')
        status = self.request.query_params.get('status')
        if status == 'cancelled': qs = qs.filter(cancelled_at__isnull=False)
        elif status: qs = qs.filter(cancelled_at__isnull=True)
        if status == 'paid': qs = qs.filter(paid_amount=F('total'))
        if status == 'unpaid': qs = qs.filter(paid_amount=0, total__gt=0)
        if status == 'partial': qs = qs.filter(paid_amount__gt=0, paid_amount__lt=F('total'))
        return qs
    def get_serializer_class(self): return s.InvoiceListSerializer if self.action == 'list' else s.InvoiceSerializer
    def create(self, request):
        serializer = s.InvoiceInput(data=request.data); serializer.is_valid(raise_exception=True)
        invoice, created = create_invoice(request.user, tenant(request), serializer.validated_data)
        data = dict(s.InvoiceSerializer(invoice).data)
        try:
            invoice_pdf(invoice)  # Generate from the committed snapshot, without persisting a file.
            data['pdf_ready'] = True
        except Exception:
            logging.getLogger(__name__).exception('PDF generation failed for saved invoice %s', invoice.pk)
            data['pdf_ready'] = False
        data['pdf_url'] = f'/api/invoices/{invoice.pk}/pdf/'
        return Response(data, status=201 if created else 200)
    @action(detail=False, methods=['post'])
    def preview(self, request):
        serializer = s.InvoiceInput(data=request.data); serializer.is_valid(raise_exception=True)
        _, _, lines, totals = prepare_invoice(tenant(request), serializer.validated_data)
        return Response({'items': [{k: str(v) if isinstance(v, Decimal) else v for k, v in line.items() if k not in ['product', 'purchase_price']} for line in lines],
            **{key: str(value) for key, value in totals.items()}, 'balance': str(totals['total'] - initial_payment(serializer.validated_data, totals['total'])),
            'quote_token': signing.dumps(quote_payload(lines, totals), salt='invoice-preview', compress=True)})
    @action(detail=True, methods=['get'])
    def pdf(self, request, pk=None):
        invoice = self.get_object()
        rate_limit('pdf', str(request.user.pk), limit=40, seconds=60)
        try: return pdf_response(invoice_pdf(invoice), f'{invoice.number}.pdf', download=request.query_params.get('download') == '1')
        except Exception:
            logging.getLogger(__name__).exception('Invoice PDF generation failed for %s', invoice.pk)
            return Response({'detail': 'Your invoice is saved. PDF generation is temporarily unavailable. Please retry the download.'}, status=503)
    @action(detail=True, methods=['get'])
    def qr(self, request, pk=None):
        invoice = self.get_object(); uri = upi_uri(invoice)
        return Response({'uri': uri, 'image': qr_data(uri), 'upi_id': invoice.business_snapshot.get('upi_id', ''), 'balance': str(invoice.balance)})
    @action(detail=True, methods=['get'])
    def receipt(self, request, pk=None):
        from .printing import receipt_data
        return Response(receipt_data(self.get_object()))
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        if request.user.membership.role not in ['owner', 'manager']: raise PermissionDenied('Only owners and managers can cancel invoices.')
        invoice = self.get_object()
        reason = request.data.get('reason', '')
        confirmed = request.data.get('refund_confirmed', False)
        if not isinstance(reason, str) or len(reason) > 300 or not isinstance(confirmed, bool): raise ValidationError('Invalid cancellation details.')
        return Response(s.InvoiceSerializer(cancel_invoice(request.user, tenant(request), invoice.pk, reason, confirmed)).data)
    @action(detail=True, methods=['post'])
    def pay(self, request, pk=None):
        invoice = self.get_object()
        serializer = s.PaymentInput(data=request.data); serializer.is_valid(raise_exception=True)
        payment = record_payment(request.user, tenant(request), invoice.pk, serializer.validated_data)
        return Response(s.PaymentSerializer(payment).data, status=201)
    @action(detail=True, methods=['post'])
    def share(self, request, pk=None):
        require_feature('INVOICE_SHARING_ENABLED')
        invoice = self.get_object()
        rate_limit('share', str(request.user.pk), limit=30, seconds=60)
        # Verify rendering before creating a link; PDF bytes are discarded after the check.
        try: invoice_pdf(invoice)
        except Exception:
            logging.getLogger(__name__).exception('Share PDF unavailable for %s', invoice.pk)
            return Response({'detail': 'The invoice is saved, but its PDF could not be generated. Please retry sharing.'}, status=503)
        raw = secrets.token_urlsafe(32)
        token = m.SharingToken.objects.create(invoice=invoice, digest=hashlib.sha256(raw.encode()).hexdigest(), expires_at=timezone.now() + timedelta(days=7))
        url = f'{settings.FRONTEND_URL}/api/shared/{raw}/'
        m.MessageLog.objects.create(business=invoice.business, invoice=invoice, status='link_prepared')
        audit(request.user, invoice.business, 'invoice.share_created', invoice.pk)
        return Response({'url': url, 'expires_at': token.expires_at, 'status': 'link_prepared', **whatsapp_link(invoice, url)})
    @action(detail=True, methods=['post'], url_path='revoke-links')
    def revoke_links(self, request, pk=None):
        invoice = self.get_object()
        invoice.sharing_tokens.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
        audit(request.user, invoice.business, 'invoice.links_revoked', invoice.pk)
        return Response({'detail': 'All sharing links for this invoice have been revoked.'})

@api_view(['GET'])
@permission_classes([AllowAny])
def shared_invoice(request, token):
    rate_limit('public-share-requests', request.META.get('REMOTE_ADDR', ''), limit=300, seconds=60)
    if len(token) > 80: return Response(status=404)
    digest = hashlib.sha256(token.encode()).hexdigest()
    link = get_object_or_404(m.SharingToken.objects.select_related('invoice'), digest=digest,
        revoked_at__isnull=True, expires_at__gt=timezone.now(), invoice__business__is_active=True)
    rate_limit('public-share-render', digest, limit=30, seconds=60)
    try: return pdf_response(invoice_pdf(link.invoice), f'{link.invoice.number}.pdf')
    except Exception:
        logging.getLogger(__name__).exception('Public PDF generation failed for invoice %s', link.invoice_id)
        return Response({'detail': 'The PDF is temporarily unavailable.'}, status=503)

class PaymentViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [TenantPermission]
    serializer_class = s.PaymentSerializer
    def get_queryset(self): return m.Payment.objects.filter(business=tenant(self.request)).select_related('invoice').order_by('-created_at')

class SettingsView(APIView):
    permission_classes = [TenantPermission]
    write_roles = ['owner', 'manager']
    def get(self, request): return Response(s.BusinessSerializer(tenant(request)).data)
    def patch(self, request):
        with transaction.atomic():
            business = m.Business.objects.select_for_update().get(pk=tenant(request).pk)
            serializer = s.BusinessSerializer(business, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            config = s.SettingsSerializer(business.settings, data=request.data.get('settings', {}), partial=True)
            config.is_valid(raise_exception=True)
            serializer.save(); config.save()
            audit(request.user, business, 'business.settings_updated', business.pk)
        return Response(s.BusinessSerializer(business).data)

class MembershipView(APIView):
    permission_classes = [TenantPermission]
    write_roles = ['owner']
    def get(self, request):
        if request.user.membership.role != 'owner': raise PermissionDenied('Only the owner can manage staff.')
        rows = tenant(request).memberships.select_related('user').order_by('pk')
        return Response([{'id': row.pk, 'name': row.user.first_name, 'mobile': row.user.login_mobile or row.user.mobile, 'role': row.role, 'is_active': row.user.is_active} for row in rows])
    def post(self, request):
        from django.contrib.auth.password_validation import validate_password
        mobile = normalize_mobile(request.data.get('mobile', ''))
        if m.User.objects.filter(Q(login_mobile=mobile) | Q(legacy_mobile_candidate=mobile, login_mobile__isnull=True)).exists():
            raise ValidationError('This mobile number already belongs to an account. Contact the platform administrator.')
        role = request.data.get('role', 'cashier')
        if role not in ['manager', 'cashier', 'viewer']: raise ValidationError('Invalid staff role.')
        name = str(request.data.get('name', '')).strip()[:100]
        if not name: raise ValidationError('Staff name is required.')
        password = request.data.get('password', '')
        validate_password(password, m.User(username=mobile, first_name=name))
        try:
            with transaction.atomic():
                user = m.User(username=f'account-{uuid.uuid4().hex}', first_name=name, mobile=mobile, login_mobile=mobile, must_change_password=True, password_reset_at=timezone.now())
                user.set_password(password); user.save()
                member = m.Membership.objects.create(user=user, business=tenant(request), role=role)
                audit(request.user, tenant(request), 'staff.created', member.pk)
        except IntegrityError: raise ValidationError('This mobile number is already registered.')
        return Response({'id': member.pk}, status=201)
    def patch(self, request):
        member = get_object_or_404(m.Membership, pk=request.data.get('id'), business=tenant(request))
        if member.role == 'owner': raise ValidationError('The owner account cannot be changed here.')
        role = request.data.get('role', member.role)
        if role not in ['manager', 'cashier', 'viewer']: raise ValidationError('Invalid staff role.')
        active = request.data.get('is_active', member.user.is_active)
        if not isinstance(active, bool): raise ValidationError('is_active must be a boolean.')
        with transaction.atomic():
            member.role = role; member.save(update_fields=['role'])
            member.user.is_active = active; member.user.save(update_fields=['is_active'])
            audit(request.user, tenant(request), 'staff.updated', member.pk)
        return Response({'detail': 'Staff account updated.'})

class DashboardView(APIView):
    permission_classes = [TenantPermission]
    def get(self, request):
        business = tenant(request)
        today = timezone.now().astimezone(ZoneInfo(business.settings.timezone)).date()
        invoices = m.Invoice.objects.filter(business=business, cancelled_at__isnull=True)
        products = m.Product.objects.filter(business=business, is_active=True)
        section = request.query_params.get('section', 'all')
        if section not in ['all', 'summary', 'widgets']: raise ValidationError('Invalid dashboard section.')
        month_index = today.year * 12 + today.month - 1 - 5
        first_month = date(month_index // 12, month_index % 12 + 1, 1)
        revenue = invoices.filter(date__gte=first_month, date__lte=today).annotate(month=TruncMonth('date')).values('month').annotate(revenue=Sum('total')).order_by('month')
        top = m.InvoiceItem.objects.filter(invoice__business=business, invoice__cancelled_at__isnull=True).values('product_id', 'description').annotate(quantity=Sum('quantity'), revenue=Sum('total')).order_by('-revenue')[:5]
        result = {}
        if section != 'widgets':
            result.update(invoices.aggregate(
                today_sales=Sum('total', filter=Q(date=today), default=Decimal(0)),
                monthly_sales=Sum('total', filter=Q(date__gte=today.replace(day=1), date__lte=today), default=Decimal(0)),
                total_invoices=Count('pk'), pending_payments=Sum(F('total')-F('paid_amount'), default=Decimal(0))))
            result.update(products.aggregate(total_products=Count('pk'), low_stock_count=Count('pk', filter=Q(stock__lte=F('low_stock_threshold')))))
            result.update(today=str(today), total_customers=m.Customer.objects.filter(business=business, merged_into__isnull=True, is_active=True).count(),
                low_stock=s.ProductSerializer(products.filter(stock__lte=F('low_stock_threshold')).select_related('category').order_by('stock')[:5], many=True).data,
                recent_invoices=s.InvoiceListSerializer(invoices.defer('business_snapshot', 'notes', 'request_hash').order_by('-created_at')[:5], many=True).data)
        if section != 'summary':
            result.update(revenue=list(revenue), top_products=list(top))
        return Response(result)

class ReportsView(APIView):
    permission_classes = [TenantPermission]
    def get(self, request):
        business = tenant(request)
        today = timezone.now().astimezone(ZoneInfo(business.settings.timezone)).date()
        try:
            start = date.fromisoformat(request.query_params.get('start', str(today.replace(day=1))))
            end = date.fromisoformat(request.query_params.get('end', str(today)))
        except ValueError: raise ValidationError('Dates must use YYYY-MM-DD.')
        if start > end: raise ValidationError('Start date must precede end date.')
        qs = m.Invoice.objects.filter(business=business, date__range=[start, end], cancelled_at__isnull=True)
        items = m.InvoiceItem.objects.filter(invoice__in=qs)
        cost = aggregate_money(items, ExpressionWrapper(F('purchase_price') * F('quantity'), output_field=DecimalField()))
        sales = aggregate_money(qs, 'total')
        tax = aggregate_money(qs, F('cgst') + F('sgst') + F('igst'))
        missing_cost = items.filter(purchase_price__isnull=True).count()
        summary = {'sales': sales, 'tax': tax, 'collected': aggregate_money(qs, 'paid_amount'),
            'outstanding': aggregate_money(qs, F('total') - F('paid_amount')), 'estimated_profit': None if missing_cost else sales - tax - cost,
            'missing_cost_lines':missing_cost, 'invoices': qs.count()}
        kind = request.query_params.get('kind', 'daily')
        if kind == 'daily': rows = qs.values('date').annotate(invoices=Count('id'), sales=Sum('total'), collected=Sum('paid_amount')).order_by('-date')
        elif kind == 'monthly': rows = qs.annotate(month=TruncMonth('date')).values('month').annotate(invoices=Count('id'), sales=Sum('total')).order_by('-month')
        elif kind == 'products': rows = items.values('description', 'sku').annotate(quantity=Sum('quantity'), sales=Sum('total')).order_by('-sales')
        elif kind == 'customers': rows = qs.values('customer__name', 'customer__mobile').annotate(invoices=Count('id'), sales=Sum('total'), outstanding=Sum(F('total') - F('paid_amount'))).order_by('-sales')
        elif kind == 'outstanding': rows = qs.filter(paid_amount__lt=F('total')).values('number', 'customer__name', 'date', 'total', 'paid_amount').annotate(balance=F('total') - F('paid_amount')).order_by('date')
        elif kind == 'stock': rows = m.Product.objects.filter(business=business, is_active=True).values('name', 'sku', 'stock', 'unit', 'purchase_price', 'selling_price').order_by('name')
        else: raise ValidationError('Unknown report type.')
        export = request.query_params.get('format', '')
        # Avoid DRF's format override by using export=csv/pdf in the UI.
        export = request.query_params.get('export', export)
        count = rows.count()
        if export in ['csv', 'pdf']:
            if count > 5000: raise ValidationError('Narrow your date range to export fewer than 5,000 rows.')
            values = list(rows)
            if export == 'csv':
                response = HttpResponse(content_type='text/csv'); response['Content-Disposition'] = f'attachment; filename="billora-{kind}.csv"'
                writer = csv.writer(response)
                if values:
                    writer.writerow(values[0].keys())
                    for row in values:
                        writer.writerow(["'" + str(v) if str(v).startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else str(v) for v in row.values()])
                return response
            try:
                return pdf_response(render_pdf('billing/report.html', {'business': business, 'kind': kind, 'start': start, 'end': end,
                    'summary': summary, 'headers': values[0].keys() if values else [], 'rows': [list(v.values()) for v in values]}), f'billora-{kind}.pdf')
            except Exception:
                logging.getLogger(__name__).exception('Report PDF generation failed for business %s', business.pk)
                return Response({'detail': 'PDF rendering is unavailable. Try CSV export.'}, status=503)
        try: page = max(1, int(request.query_params.get('page', 1)))
        except ValueError: raise ValidationError('Invalid page.')
        return Response({'summary': summary, 'start': start, 'end': end, 'count': count, 'results': list(rows[(page-1)*25:page*25]),
            'next': page*25 < count, 'previous': page > 1})

@api_view(['GET'])
@permission_classes([AllowAny])
def plans(request):
    return Response({'billing_enabled': settings.BILLING_ENABLED, 'collection_enabled': False,
        'plans': s.PlanSerializer(m.SubscriptionPlan.objects.filter(is_active=True).order_by('price'), many=True).data})

@api_view(['GET'])
@permission_classes([AllowAny])
def health(request):
    try:
        with connection.cursor() as cursor: cursor.execute('SELECT 1')
        return Response({'status': 'ok'})
    except Exception: return Response({'status': 'database_unavailable'}, status=503)

class AdminOverview(APIView):
    permission_classes = [SuperAdminPermission]
    def get(self, request):
        return Response({'businesses': m.Business.objects.count(), 'active_businesses': m.Business.objects.filter(is_active=True).count(),
            'invoices': m.Invoice.objects.count(), 'users': m.User.objects.count(),
            'billing_enabled': settings.BILLING_ENABLED, 'automatic_whatsapp_enabled': False, 'collection_enabled': False})

class AdminBusinessViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [SuperAdminPermission]
    queryset = m.Business.objects.select_related('settings').order_by('-created_at')
    serializer_class = s.BusinessSerializer
    search_fields = ['name', 'memberships__user__email']
    @action(detail=True, methods=['post'])
    def status(self, request, pk=None):
        active = request.data.get('is_active')
        if not isinstance(active, bool): raise ValidationError('is_active must be a boolean.')
        with transaction.atomic():
            business = self.get_queryset().select_for_update().get(pk=self.get_object().pk)
            business.is_active = active; business.save(update_fields=['is_active'])
            audit(request.user, business, 'business.activated' if active else 'business.suspended', business.pk)
        return Response(s.BusinessSerializer(business).data)

class AdminPlanViewSet(viewsets.ModelViewSet):
    permission_classes = [SuperAdminPermission]
    queryset = m.SubscriptionPlan.objects.all().order_by('price')
    serializer_class = s.PlanSerializer
    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    search_fields = ['name']
    def perform_create(self, serializer):
        obj = serializer.save(); audit(self.request.user, None, 'plan.created', obj.pk)
    def perform_update(self, serializer):
        obj = serializer.save(); audit(self.request.user, None, 'plan.updated', obj.pk)

class AdminFlagViewSet(AdminPlanViewSet):
    queryset = m.FeatureFlag.objects.all().order_by('key')
    serializer_class = s.FeatureFlagSerializer
    search_fields = ['key', 'description']
    def perform_create(self, serializer):
        obj = serializer.save(); audit(self.request.user, None, 'flag.created', obj.pk)
    def perform_update(self, serializer):
        obj = serializer.save(); audit(self.request.user, None, 'flag.updated', obj.pk)

class AuditSerializer(s.serializers.ModelSerializer):
    actor_email = s.serializers.CharField(source='actor.email', read_only=True, default='System')
    business_name = s.serializers.CharField(source='business.name', read_only=True, default='Platform')
    class Meta: model = m.AuditLog; fields = ['id', 'actor_email', 'business_name', 'action', 'object_id', 'verification_reference', 'created_at']

class AdminAuditViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [SuperAdminPermission]
    queryset = m.AuditLog.objects.select_related('actor', 'business').all()
    serializer_class = AuditSerializer
    search_fields = ['action', 'actor__email', 'business__name']
