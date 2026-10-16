import hashlib
import uuid
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlparse, parse_qs
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError
from billing import models as m
from billing.services import create_invoice, record_payment, calculate_lines, upi_uri, whatsapp_link
from billing.pdf import qr_data, safe_fetcher
from billing.serializers import InvoiceInput

def fixture(email='owner@example.com', name='Priya'):
    login_mobile = '+919' + str(int(hashlib.sha256(email.encode()).hexdigest()[:12],16) % 1000000000).zfill(9)
    user = m.User.objects.create_user(login_mobile=login_mobile, username=email, email=email, password='Test-Password-2026!', first_name=name, mobile='+919876543210')
    business = m.Business.objects.create(name='Test Store', gstin='27ABCDE1234F1Z5', state_code='27', mobile='+919876543210')
    m.BusinessSettings.objects.create(business=business, upi_id='store@upi', upi_payee_name='Test Store & More')
    m.Membership.objects.create(user=user, business=business)
    product = m.Product.objects.create(business=business, name='Notebook', sku='NB-1', selling_price='100.00', purchase_price='50.00', stock='20.000', gst_rate='18.00')
    customer = m.Customer.objects.create(business=business, name='A Customer', mobile='+919876543211', state_code='27')
    product.refresh_from_db()
    return user, business, product, customer

def payload(product, customer, **changes):
    raw = {'customer':customer.pk, 'items':[{'product':product.pk,'quantity':'2.000'}], 'idempotency_key':str(uuid.uuid4()),
           'discount':'0.00','paid_amount':'0.00','gst_enabled':True,'include_upi_qr':True,'payment_method':'upi', **changes}
    serializer = InvoiceInput(data=raw); serializer.is_valid(raise_exception=True)
    return serializer.validated_data

class InvoiceTests(TestCase):
    def setUp(self): self.user,self.business,self.product,self.customer = fixture()
    def create(self, **changes): return create_invoice(self.user,self.business,payload(self.product,self.customer,**changes))[0]
    def test_intrastate_calculation_and_stock(self):
        invoice = self.create(discount='10.00')
        self.assertEqual(invoice.subtotal,Decimal('200.00'))
        self.assertEqual(invoice.cgst,Decimal('17.10')); self.assertEqual(invoice.sgst,Decimal('17.10'))
        self.assertEqual(invoice.total,Decimal('224.20'))
        self.product.refresh_from_db(); self.assertEqual(self.product.stock,18)
    def test_interstate_igst(self):
        invoice=self.create(supply_state='29'); self.assertEqual(invoice.igst,Decimal('36.00')); self.assertEqual(invoice.cgst,0)
    def test_non_gst(self): self.assertEqual(self.create(gst_enabled=False).total,Decimal('200.00'))
    def test_gst_requires_business_gstin(self):
        self.business.gstin='';self.business.save()
        with self.assertRaises(ValidationError):self.create()
    def test_duplicate_request_does_not_deduct_stock_twice(self):
        data=payload(self.product,self.customer)
        first,created=create_invoice(self.user,self.business,data);second,repeated=create_invoice(self.user,self.business,data)
        self.assertTrue(created);self.assertFalse(repeated);self.assertEqual(first.pk,second.pk)
        self.product.refresh_from_db();self.assertEqual(self.product.stock,18);self.assertEqual(m.Invoice.objects.count(),1)
    def test_key_reuse_with_changed_body_is_rejected(self):
        data=payload(self.product,self.customer);create_invoice(self.user,self.business,data);data['discount']=Decimal('1.00')
        with self.assertRaises(ValidationError):create_invoice(self.user,self.business,data)
    def test_numbering_and_uniqueness(self):
        self.assertEqual(self.create().number,'INV-000001');self.assertEqual(self.create().number,'INV-000002')
    def test_failed_stock_is_atomic(self):
        with self.assertRaises(ValidationError):self.create(items=[{'product':self.product.pk,'quantity':'21'}])
        self.assertEqual(m.Invoice.objects.count(),0);self.business.refresh_from_db();self.assertEqual(self.business.next_invoice_number,1)
        self.product.refresh_from_db();self.assertEqual(self.product.stock,20)
    def test_negative_stock_explicit_opt_in(self):
        m.BusinessSettings.objects.filter(business=self.business).update(allow_negative_stock=True)
        self.create(items=[{'product':self.product.pk,'quantity':'21'}]);self.product.refresh_from_db();self.assertEqual(self.product.stock,-1)
    def test_duplicate_products_rejected(self):
        with self.assertRaises(ValidationError):self.create(items=[{'product':self.product.pk,'quantity':'1'},{'product':self.product.pk,'quantity':'1'}])
    def test_invoice_snapshots_are_immutable(self):
        invoice=self.create();self.product.name='Changed';self.product.selling_price=900;self.product.save();self.customer.name='Changed';self.customer.save()
        invoice.refresh_from_db();self.assertEqual(invoice.items.get().description,'Notebook');self.assertEqual(invoice.customer_snapshot['name'],'A Customer');self.assertEqual(invoice.total,236)
    def test_logo_snapshot_is_deduplicated_and_preserved(self):
        m.BusinessSettings.objects.filter(business=self.business).update(logo_data='data:image/png;base64,test-fixture-only')
        first=self.create();second=self.create()
        self.assertEqual(m.InvoiceLogo.objects.count(),1)
        self.assertEqual(first.business_snapshot['logo_key'],second.business_snapshot['logo_key'])
        m.BusinessSettings.objects.filter(business=self.business).update(logo_data='')
        self.assertEqual(first.logo_data,'data:image/png;base64,test-fixture-only')
    def test_payment_idempotency_and_balance(self):
        invoice=self.create();data={'amount':Decimal('36.00'),'method':'upi','reference':'confirmed-1','idempotency_key':uuid.uuid4()}
        first=record_payment(self.user,self.business,invoice.pk,data);second=record_payment(self.user,self.business,invoice.pk,data)
        self.assertEqual(first.pk,second.pk);invoice.refresh_from_db();self.assertEqual(invoice.balance,200);self.assertEqual(invoice.status,'partial');self.assertEqual(invoice.revision,2)
    def test_overpayment_rejected(self):
        invoice=self.create()
        with self.assertRaises(ValidationError):record_payment(self.user,self.business,invoice.pk,{'amount':Decimal('237'),'method':'cash','idempotency_key':uuid.uuid4()})
        invoice.refresh_from_db();self.assertEqual(invoice.paid_amount,0)
    def test_qr_exact_balance_encoding_and_no_automatic_payment(self):
        invoice=self.create(paid_amount='36.00');uri=upi_uri(invoice);params=parse_qs(urlparse(uri).query)
        self.assertEqual(params['am'],['200.00']);self.assertEqual(params['cu'],['INR']);self.assertEqual(params['pn'],['Test Store & More'])
        self.assertIn(invoice.number,params['tn'][0]);self.assertTrue(qr_data(uri).startswith('data:image/png;base64,'));self.assertEqual(invoice.status,'partial')
    def test_paid_invoice_has_no_payment_qr(self): self.assertEqual(upi_uri(self.create(paid_amount='236.00')),'')
    def test_whatsapp_message_is_encoded(self):
        invoice=self.create();result=whatsapp_link(invoice,'https://example.com/a')
        parsed=urlparse(result['whatsapp_url']);self.assertEqual(parsed.path,'/919876543211');self.assertIn(invoice.number,parse_qs(parsed.query)['text'][0])
    def test_large_discount_allocation_never_goes_negative(self):
        products={}
        for i in range(8):
            product=m.Product(id=i+1,name=str(i),sku=str(i),selling_price=Decimal('.01'),purchase_price=Decimal(0),gst_rate=Decimal(0),unit='pcs')
            products[product.pk]=product
        lines,totals=calculate_lines(products,[{'product':pid,'quantity':Decimal(1)} for pid in products],Decimal('.04'),False,False)
        self.assertEqual(totals['discount'],Decimal('.04'));self.assertTrue(all(line['total']>=0 for line in lines));self.assertEqual(totals['total'],Decimal('.04'))
    def test_pdf_fetcher_blocks_network_and_files(self):
        for value in ['http://169.254.169.254/','file:///etc/passwd','https://example.com/logo.png']:
            with self.assertRaises((ValueError, OSError)):safe_fetcher(value)

class ApiTests(TestCase):
    def setUp(self):
        self.user,self.business,self.product,self.customer=fixture();self.other,self.other_business,self.other_product,self.other_customer=fixture('other@example.com','Aman')
        self.client=APIClient();self.client.force_login(self.user)
    def test_tenant_list_and_detail_isolation(self):
        response=self.client.get('/api/products/');self.assertEqual(response.status_code,200);self.assertEqual(response.data['count'],1)
        self.assertEqual(self.client.get(f'/api/products/{self.other_product.pk}/').status_code,404)
        self.assertEqual(self.client.patch(f'/api/customers/{self.other_customer.pk}/',{'name':'Stolen'}).status_code,404)
    def test_cross_tenant_product_and_customer_rejected(self):
        for data in [payload(self.other_product,self.customer),payload(self.product,self.other_customer)]:
            response=self.client.post('/api/invoices/',data,format='json');self.assertEqual(response.status_code,400)
        self.assertEqual(m.Invoice.objects.count(),0)
    def test_category_cross_tenant_rejected(self):
        category=m.Category.objects.create(business=self.other_business,name='Private')
        response=self.client.patch(f'/api/products/{self.product.pk}/',{'category':category.pk},format='json');self.assertEqual(response.status_code,400)
    def test_read_only_role_cannot_mutate(self):
        m.Membership.objects.filter(user=self.user).update(role='viewer')
        self.assertEqual(self.client.post('/api/invoices/',{},format='json').status_code,403)
        self.assertEqual(self.client.patch('/api/settings/',{},format='json').status_code,403)
        self.assertEqual(self.client.get('/api/dashboard/').status_code,200)
    def test_cashier_cannot_change_stock_or_staff(self):
        m.Membership.objects.filter(user=self.user).update(role='cashier')
        self.assertEqual(self.client.patch(f'/api/products/{self.product.pk}/',{'stock':999},format='json').status_code,403)
        self.assertEqual(self.client.post('/api/memberships/',{},format='json').status_code,403)
    def test_superadmin_apis_require_superuser(self): self.assertEqual(self.client.get('/api/admin/overview/').status_code,403)
    def test_suspended_tenant_denied(self):
        self.business.is_active=False;self.business.save();self.assertEqual(self.client.get('/api/dashboard/').status_code,403)
    def test_dashboard_is_real_and_personalized(self):
        response=self.client.get('/api/auth/me/');self.assertEqual(response.data['user']['first_name'],'Priya')
        self.assertEqual(self.client.get('/api/dashboard/').data['total_invoices'],0)
        create_invoice(self.user,self.business,payload(self.product,self.customer))
        self.assertEqual(self.client.get('/api/dashboard/').data['total_invoices'],1)
    def test_invoice_end_to_end_api(self):
        response=self.client.post('/api/invoices/',payload(self.product,self.customer),format='json');self.assertEqual(response.status_code,201)
        invoice_id=response.data['id'];self.assertEqual(self.client.get(f'/api/invoices/{invoice_id}/').data['total'],'236.00')
        self.assertEqual(self.client.post(f'/api/invoices/{invoice_id}/pay/',{'amount':'236.00','method':'cash','idempotency_key':str(uuid.uuid4())},format='json').status_code,201)
        self.assertEqual(self.client.get(f'/api/invoices/{invoice_id}/').data['status'],'paid')
    def test_price_change_after_preview_requires_new_confirmation(self):
        data=payload(self.product,self.customer)
        preview=self.client.post('/api/invoices/preview/',data,format='json')
        self.assertEqual(preview.status_code,200)
        data['quote_token']=preview.data['quote_token']
        m.Product.objects.filter(pk=self.product.pk).update(selling_price='101.00')
        response=self.client.post('/api/invoices/',data,format='json')
        self.assertEqual(response.status_code,400);self.assertEqual(m.Invoice.objects.count(),0)
    @patch('billing.views.invoice_pdf',return_value=b'%PDF-1.4 fake-test-only')
    def test_sharing_expiry_revocation_and_delivery_status(self, render):
        invoice=create_invoice(self.user,self.business,payload(self.product,self.customer))[0]
        response=self.client.post(f'/api/invoices/{invoice.pk}/share/',{},format='json');self.assertEqual(response.status_code,200);self.assertEqual(response.data['status'],'link_prepared')
        path=urlparse(response.data['url']).path;public=APIClient();self.assertEqual(public.get(path).status_code,200)
        self.client.post(f'/api/invoices/{invoice.pk}/revoke-links/',{},format='json');self.assertEqual(public.get(path).status_code,404)
        raw='expired-token';m.SharingToken.objects.create(invoice=invoice,digest=hashlib.sha256(raw.encode()).hexdigest(),expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(public.get(f'/api/shared/{raw}/').status_code,404)
    def test_report_and_csv_formula_safety(self):
        self.product.name='=HYPERLINK("example")';self.product.save()
        response=self.client.get('/api/reports/?kind=stock&export=csv');self.assertEqual(response.status_code,200);self.assertIn(b"'=HYPERLINK",response.content)
    def test_invalid_report_date_is_validation_error(self): self.assertEqual(self.client.get('/api/reports/?start=bad').status_code,400)
    def test_csv_import_rolls_back_all_rows(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        upload=SimpleUploadedFile('products.csv',b'name,sku,selling_price\nGood,NEW,12\nBad,BAD,-1\n',content_type='text/csv')
        response=self.client.post('/api/products/import-csv/',{'file':upload},format='multipart');self.assertEqual(response.status_code,400);self.assertFalse(m.Product.objects.filter(sku='NEW').exists())
    def test_launch_plans_are_seeded_and_no_collection(self):
        response=self.client.get('/api/plans/');self.assertFalse(response.data['collection_enabled']);self.assertEqual(len(response.data['plans']),3)
    def test_feature_flag_disables_registration(self):
        m.FeatureFlag.objects.filter(key='REGISTRATION_ENABLED').update(enabled=False)
        self.assertEqual(self.client.post('/api/auth/register/',{},format='json').status_code,403)

class AuthTests(TestCase):
    def setUp(self): self.user,self.business,self.product,self.customer=fixture();self.client=APIClient(enforce_csrf_checks=True)
    def csrf(self): return self.client.get('/api/auth/csrf/').data['csrfToken']
    def test_login_rejects_missing_csrf(self): self.assertEqual(self.client.post('/api/auth/login/',{'mobile':self.user.login_mobile,'password':'Test-Password-2026!'},format='json').status_code,403)
    def test_login_logout_session(self):
        response=self.client.post('/api/auth/login/',{'mobile':self.user.login_mobile,'password':'Test-Password-2026!'},format='json',HTTP_X_CSRFTOKEN=self.csrf())
        self.assertEqual(response.status_code,200);self.assertTrue(response.cookies['sessionid']['httponly']);self.assertEqual(self.client.get('/api/auth/me/').status_code,200)
        self.assertEqual(self.client.post('/api/auth/logout/',{},format='json',HTTP_X_CSRFTOKEN=self.csrf()).status_code,200)
        self.assertEqual(self.client.get('/api/auth/me/').status_code,401)
    def test_login_rate_limit(self):
        token=self.csrf()
        for _ in range(10): self.client.post('/api/auth/login/',{'mobile':self.user.login_mobile,'password':'wrong'},format='json',HTTP_X_CSRFTOKEN=token)
        self.assertEqual(self.client.post('/api/auth/login/',{'mobile':self.user.login_mobile,'password':'wrong'},format='json',HTTP_X_CSRFTOKEN=token).status_code,429)
    def test_register_creates_private_business(self):
        response=self.client.post('/api/auth/register/',{'store_name':'Aman Store','mobile':'9876543210','password':'Unique#Pass2026'},format='json',HTTP_X_CSRFTOKEN=self.csrf())
        self.assertEqual(response.status_code,201);self.assertEqual(response.data['user']['login_mobile'],'+919876543210')
        self.assertEqual(response.data['business']['name'],'Aman Store');self.assertEqual(response.data['role'],'owner')
    def test_weak_registration_password_is_rejected(self):
        response=self.client.post('/api/auth/register/',{'store_name':'Aman Store','mobile':'9876543210','password':'password'},format='json',HTTP_X_CSRFTOKEN=self.csrf())
        self.assertEqual(response.status_code,400)
        self.assertFalse(m.User.objects.filter(login_mobile='+919876543210').exists())
    def test_public_password_reset_is_removed(self):
        from django.core import mail
        before=self.user.password
        for action in ['forgot-password','reset-password']:
            response=self.client.post(f'/api/auth/{action}/',{'mobile':self.user.login_mobile,'password':'Replacement#2026Secure'},format='json',HTTP_X_CSRFTOKEN=self.csrf())
            self.assertEqual(response.status_code,410)
        self.user.refresh_from_db();self.assertEqual(self.user.password,before);self.assertEqual(len(mail.outbox),0)
