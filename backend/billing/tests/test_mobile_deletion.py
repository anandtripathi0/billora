import uuid
from datetime import timedelta
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless
from django.test import TestCase, TransactionTestCase, Client
from django.db import connection, close_old_connections, IntegrityError, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from django.contrib.auth.hashers import make_password
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError
from billing import models as m
from billing.services import create_invoice, record_payment, cancel_invoice
from .test_billing import fixture, payload

PASSWORD='Test-Password-2026!'
NEW_PASSWORD='New-Personal#Password-2026'
TEMP_PASSWORD='Temporary#Support-2026'

class MobileAuthenticationTests(TestCase):
    def setUp(self):
        self.user,self.business,self.product,self.customer=fixture()
        self.client=APIClient(enforce_csrf_checks=True)
    def post(self,path,body,client=None):
        client=client or self.client
        token=client.get('/api/auth/csrf/').data['csrfToken']
        return client.post('/api/'+path,body,format='json',HTTP_X_CSRFTOKEN=token)
    def test_normalized_mobile_uniqueness_and_private_signup(self):
        for i,mobile in enumerate(['98765 43210','+91 9876543210','919876543210']):
            response=self.post('auth/register/',{'store_name':'Sharma Store','mobile':mobile,'password':PASSWORD})
            self.assertEqual(response.status_code,201 if i==0 else 400)
        user=m.User.objects.get(login_mobile='+919876543210')
        self.assertTrue(user.check_password(PASSWORD));self.assertNotEqual(user.password,PASSWORD)
        self.assertIsNone(user.email);self.assertEqual(user.membership.business.name,'Sharma Store')
        self.assertEqual(user.membership.role,'owner');self.assertNotEqual(user.membership.business_id,self.business.pk)
        with self.assertRaises(IntegrityError),transaction.atomic():
            m.User.objects.create(username='duplicate',login_mobile=user.login_mobile)
    def test_mobile_validation_and_wrong_credentials(self):
        for mobile in ['123','1234567890','+449876543210','9abcdefghj']:
            self.assertEqual(self.post('auth/register/',{'store_name':'Bad','mobile':mobile,'password':PASSWORD}).status_code,400)
        self.assertEqual(self.post('auth/login/',{'mobile':self.user.login_mobile,'password':'wrong'}).status_code,400)
        self.assertEqual(self.post('auth/login/',{'email':self.user.email,'password':PASSWORD}).status_code,400)
        self.assertEqual(self.post('auth/login/',{'mobile':self.user.login_mobile[3:],'password':PASSWORD}).status_code,200)
        self.assertEqual(self.client.get('/api/auth/me/').status_code,200)
    def test_legacy_number_is_reserved_not_auto_verified(self):
        self.user.login_mobile=None;self.user.legacy_mobile_candidate='+919876543210';self.user.save()
        self.assertEqual(self.post('auth/register/',{'store_name':'Duplicate claim','mobile':'9876543210','password':PASSWORD}).status_code,400)
        self.assertEqual(self.post('auth/login/',{'mobile':'9876543210','password':PASSWORD}).status_code,400)
        self.client.force_login(self.user,backend='django.contrib.auth.backends.ModelBackend')
        self.assertEqual(self.client.get('/api/auth/me/').status_code,200)
    def test_change_password_checks_confirmation_and_revokes_other_sessions(self):
        self.client.force_login(self.user,backend='billing.authentication.TenantBackend')
        other=APIClient();other.force_login(self.user,backend='billing.authentication.TenantBackend')
        self.assertEqual(self.post('profile/',{'old_password':'wrong','password':NEW_PASSWORD,'confirm_password':NEW_PASSWORD}).status_code,400)
        self.assertEqual(self.post('profile/',{'old_password':PASSWORD,'password':NEW_PASSWORD,'confirm_password':'different'}).status_code,400)
        self.assertEqual(self.post('profile/',{'old_password':PASSWORD,'password':PASSWORD,'confirm_password':PASSWORD}).status_code,400)
        self.assertEqual(self.post('profile/',{'old_password':PASSWORD,'password':NEW_PASSWORD,'confirm_password':NEW_PASSWORD}).status_code,200)
        self.assertEqual(self.client.get('/api/auth/me/').status_code,200)
        self.assertEqual(other.get('/api/auth/me/').status_code,401)
        self.user.refresh_from_db();self.assertTrue(self.user.check_password(NEW_PASSWORD))
        self.assertTrue(m.AuditLog.objects.filter(action='auth.password_changed',object_id=str(self.user.pk)).exists())
    def test_profile_cannot_reassign_login_identity(self):
        self.client.force_login(self.user)
        token=self.client.get('/api/auth/csrf/').data['csrfToken']
        self.client.patch('/api/profile/',{'login_mobile':'+919999999999','mobile':'+919999999999','must_change_password':False},format='json',HTTP_X_CSRFTOKEN=token)
        self.user.refresh_from_db();self.assertNotEqual(self.user.login_mobile,'+919999999999')
    def test_temporary_password_expires_and_blocks_workspace(self):
        self.user.must_change_password=True;self.user.password_reset_at=timezone.now();self.user.save()
        self.assertEqual(self.post('auth/login/',{'mobile':self.user.login_mobile,'password':PASSWORD}).status_code,200)
        for endpoint in ['dashboard/','products/','customers/','invoices/','admin/overview/']:
            self.assertEqual(self.client.get('/api/'+endpoint).status_code,403)
        self.assertEqual(self.post('profile/',{'old_password':PASSWORD,'password':NEW_PASSWORD,'confirm_password':NEW_PASSWORD}).status_code,200)
        self.assertEqual(self.client.get('/api/dashboard/').status_code,200)
        m.User.objects.filter(pk=self.user.pk).update(must_change_password=True,password_reset_at=timezone.now()-timedelta(hours=25))
        self.assertEqual(self.post('auth/login/',{'mobile':self.user.login_mobile,'password':NEW_PASSWORD}).status_code,400)

class AdministrativeAssistanceTests(TestCase):
    def setUp(self):
        self.user,self.business,self.product,self.customer=fixture()
        self.admin=m.User.objects.create_superuser(username='platform-admin',email='admin@example.com',password=PASSWORD)
        self.client=Client(enforce_csrf_checks=True);self.client.force_login(self.admin)
        self.url=f'/admin/billing/user/{self.user.pk}/assist/'
        self.body={'operation':'reset_password','temporary_password':TEMP_PASSWORD,'confirm_password':TEMP_PASSWORD,
            'ownership_verified':'on','verification_reference':'CASE-TEST: ownership independently verified','admin_password':PASSWORD}
    def submit(self,body):
        page=self.client.get(self.url);self.assertEqual(page.status_code,200)
        return self.client.post(self.url,body,HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)
    def test_superuser_verified_reset_is_audited_and_invalidates_sessions(self):
        old=APIClient();old.force_login(self.user)
        response=self.submit(self.body);self.assertEqual(response.status_code,302)
        self.user.refresh_from_db();self.assertTrue(self.user.must_change_password);self.assertTrue(self.user.check_password(TEMP_PASSWORD))
        self.assertEqual(old.get('/api/auth/me/').status_code,401)
        log=m.AuditLog.objects.get(action='admin.password_reset');self.assertEqual(log.actor,self.admin)
        self.assertEqual(log.verification_reference,self.body['verification_reference']);self.assertNotIn(TEMP_PASSWORD,str(log.__dict__))
    def test_verification_admin_password_and_csrf_required(self):
        before=self.user.password
        for overrides in [{'ownership_verified':''},{'verification_reference':''},{'admin_password':'wrong'},{'confirm_password':'wrong'}]:
            response=self.submit({**self.body,**overrides});self.assertEqual(response.status_code,200);self.assertTrue(response.context['form'].errors)
        self.assertEqual(self.client.post(self.url,self.body).status_code,403)
        self.user.refresh_from_db();self.assertEqual(self.user.password,before);self.assertFalse(m.AuditLog.objects.filter(action='admin.password_reset').exists())
    def test_unprivileged_staff_and_public_cannot_reset(self):
        for staff in [False,True]:
            self.user.is_staff=staff;self.user.save();client=Client();client.force_login(self.user)
            self.assertIn(client.get(self.url).status_code,[302,403])
            self.assertIn(client.post(self.url,self.body).status_code,[302,403])
        public=Client();self.assertEqual(public.post(self.url,self.body).status_code,302)
    def test_legacy_link_preserves_hash_and_rejects_duplicate(self):
        before=self.user.password;self.user.login_mobile=None;self.user.save()
        response=self.submit({**self.body,'operation':'link_mobile','mobile':'98765 43210'})
        self.assertEqual(response.status_code,302);self.user.refresh_from_db()
        self.assertEqual(self.user.login_mobile,'+919876543210');self.assertEqual(self.user.password,before)
        other,*_=fixture('second@example.com')
        response=self.submit({**self.body,'operation':'link_mobile','mobile':other.login_mobile})
        self.assertEqual(response.status_code,200);self.assertTrue(response.context['form'].errors)
        self.assertEqual(m.AuditLog.objects.filter(action='admin.login_mobile_verified').count(),1)
    def test_platform_login_is_throttled_and_temporary_admin_cannot_enter(self):
        public=Client()
        for _ in range(11): response=public.post('/admin/login/',{'username':self.admin.username,'password':'wrong'})
        self.assertContains(response,'Too many administrator sign-in attempts')
        self.admin.must_change_password=True;self.admin.save()
        self.assertEqual(self.client.get('/admin/').status_code,302)
        self.assertEqual(self.client.get(self.url).status_code,302)
    def test_builtin_admin_password_route_uses_verified_workflow(self):
        response=self.client.get(f'/admin/billing/user/{self.user.pk}/password/')
        self.assertRedirects(response,self.url,fetch_redirect_response=False)
        self.assertEqual(self.client.get(f'/admin/billing/user/{self.user.pk}/change/').status_code,200)

class SafeDeletionTests(TestCase):
    def setUp(self):
        self.user,self.business,self.product,self.customer=fixture()
        self.other,self.other_business,self.other_product,self.other_customer=fixture('other@example.com')
        self.client=APIClient();self.client.force_login(self.user)
    def test_unused_customer_and_product_are_hard_deleted(self):
        for kind,obj in [('customers',self.customer),('products',self.product)]:
            pk=obj.pk;response=self.client.delete(f'/api/{kind}/{pk}/')
            self.assertEqual(response.status_code,200);self.assertEqual(response.data['outcome'],'deleted')
            self.assertFalse(type(obj).objects.filter(pk=pk).exists());self.assertEqual(self.client.get(f'/api/{kind}/{pk}/').status_code,404)
    def test_invoice_history_snapshots_payments_and_stock_preserved(self):
        invoice,_=create_invoice(self.user,self.business,payload(self.product,self.customer,paid_amount='36'))
        snapshot=invoice.customer_snapshot;item=invoice.items.get();self.product.refresh_from_db();stock=self.product.stock
        for kind,obj in [('customers',self.customer),('products',self.product)]:
            result=self.client.delete(f'/api/{kind}/{obj.pk}/');self.assertEqual(result.status_code,200);self.assertEqual(result.data['outcome'],'archived')
            obj.refresh_from_db();self.assertFalse(obj.is_active)
            self.assertEqual(self.client.get(f'/api/{kind}/').data['count'],0)
        invoice.refresh_from_db();item.refresh_from_db();self.product.refresh_from_db();self.customer.refresh_from_db()
        self.assertEqual(invoice.customer_snapshot,snapshot);self.assertEqual(invoice.total,Decimal('236'))
        self.assertEqual(invoice.paid_amount,Decimal('36'));self.assertEqual(m.Payment.objects.filter(invoice=invoice).count(),1)
        self.assertEqual(item.description,'Notebook');self.assertEqual(item.unit_price,Decimal('100'));self.assertEqual(self.product.stock,stock)
        self.assertEqual(self.customer.mobile,'');self.assertEqual(self.customer.name,'Deleted customer')
        ledger=self.client.get(f'/api/customers/{self.customer.pk}/');self.assertEqual(ledger.data['purchases'],'236.00')
        self.assertEqual(ledger.data['outstanding'],'200.00')
        self.assertIsNone(self.client.get('/api/customers/lookup/?mobile=9876543211').data['customer'])
        self.assertEqual(self.client.get(f'/api/invoices/{invoice.pk}/pdf/').status_code,200)
        with self.assertRaises(ValidationError):create_invoice(self.user,self.business,payload(self.product,self.customer))
        self.assertEqual(self.client.patch(f'/api/customers/{self.customer.pk}/',{'name':'Restore'}).status_code,404)
        record_payment(self.user,self.business,invoice.pk,{'amount':Decimal('200'),'method':'cash','idempotency_key':uuid.uuid4()})
        cancel_invoice(self.user,self.business,invoice.pk,'Returned',True)
        self.assertEqual(m.Refund.objects.get(invoice=invoice).amount,Decimal('236'))
        self.product.refresh_from_db();self.assertEqual(self.product.stock,20)
        self.assertEqual(self.client.post('/api/customers/',{'name':'New customer','mobile':'9876543211'},format='json').status_code,201)
    def test_cross_tenant_and_cashier_delete_forbidden(self):
        for kind,obj in [('products',self.other_product),('customers',self.other_customer)]:
            self.assertEqual(self.client.delete(f'/api/{kind}/{obj.pk}/').status_code,404)
            self.assertTrue(type(obj).objects.filter(pk=obj.pk).exists())
        for role in ['cashier','viewer']:
            m.Membership.objects.filter(user=self.user).update(role=role)
            for kind,obj in [('products',self.product),('customers',self.customer)]:
                self.assertEqual(self.client.delete(f'/api/{kind}/{obj.pk}/').status_code,403)
        m.Membership.objects.filter(user=self.user).update(role='manager')
        self.assertEqual(self.client.delete(f'/api/customers/{self.customer.pk}/').status_code,200)
    def test_delete_requires_csrf(self):
        client=APIClient(enforce_csrf_checks=True);client.force_login(self.user)
        self.assertEqual(client.delete(f'/api/products/{self.product.pk}/').status_code,403)
        self.assertTrue(m.Product.objects.filter(pk=self.product.pk).exists())
    def test_malformed_delete_identifier_is_not_found(self):
        for kind in ['products', 'customers']:
            self.assertEqual(self.client.delete(f'/api/{kind}/not-a-number/').status_code,404)
        self.assertTrue(m.Product.objects.filter(pk=self.product.pk).exists())
        self.assertTrue(m.Customer.objects.filter(pk=self.customer.pk).exists())

class LegacyMigrationTests(TransactionTestCase):
    def test_migration_reserves_duplicates_and_preserves_passwords_and_contacts(self):
        executor=MigrationExecutor(connection);executor.migrate([('billing','0008_performance_indexes')])
        try:
            old=executor.loader.project_state([('billing','0008_performance_indexes')]).apps.get_model('billing','User')
            hashed=make_password('Preserve#ThisPassword')
            for index,number in enumerate(['98765 43210','+919876543210','invalid']):
                old.objects.create(username=f'legacy-{index}',email=f'legacy-{index}@example.com',password=hashed,mobile=number)
            executor=MigrationExecutor(connection);executor.migrate([('billing','0009_mobile_auth_and_safe_deletion')])
            for user in m.User.objects.filter(username__startswith='legacy-'):
                self.assertEqual(user.password,hashed);self.assertIsNone(user.login_mobile)
                self.assertEqual(user.legacy_mobile_candidate,None if user.mobile=='invalid' else '+919876543210')
            self.assertEqual(m.User.objects.filter(username__startswith='legacy-').count(),3)
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())

@skipUnless(connection.vendor=='postgresql','Requires PostgreSQL row locks.')
class DeleteConcurrencyTests(TransactionTestCase):
    def test_sale_and_deletion_preserve_protected_rows(self):
        user,business,product,customer=fixture()
        data=payload(product,customer)
        def sell():
            close_old_connections()
            try:
                create_invoice(m.User.objects.get(pk=user.pk),m.Business.objects.get(pk=business.pk),data)
                return 'sold'
            except ValidationError:return 'unavailable'
            finally:close_old_connections()
        def remove():
            close_old_connections()
            try:
                client=APIClient();client.force_login(m.User.objects.get(pk=user.pk))
                return client.delete(f'/api/products/{product.pk}/').status_code
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            sale=pool.submit(sell);deletion=pool.submit(remove);result=sale.result();self.assertEqual(deletion.result(),200)
        if result=='sold':
            product.refresh_from_db();self.assertFalse(product.is_active);self.assertEqual(product.stock,18)
            self.assertEqual(m.InvoiceItem.objects.get().product_id,product.pk);self.assertEqual(m.Invoice.objects.get().total,236)
        else:
            self.assertFalse(m.Product.objects.filter(pk=product.pk).exists());self.assertEqual(m.Invoice.objects.count(),0)
