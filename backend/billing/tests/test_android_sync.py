import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless
from datetime import timedelta
from decimal import Decimal
from django.test import TestCase, TransactionTestCase, override_settings
from django.db import connection, close_old_connections
from django.utils import timezone
from .https_client import HTTPSAPIClient
from billing import models as m
from billing.mobile_sync import identity, fingerprint, wire
from billing.services import create_invoice
from .test_billing import fixture, payload


class AndroidSyncTests(TestCase):
    def setUp(self):
        self.user, self.business, self.product, self.customer = fixture()
        self.client = HTTPSAPIClient(enforce_csrf_checks=True)
        self.login()
        self.page = self.client.get('/api/mobile/pull/').data
        self.pid = identity(self.business, 'product', self.product.pk)
        self.cid = identity(self.business, 'customer', self.customer.pk)

    def login(self, client=None, user=None, device_id=None):
        client, user = client or self.client, user or self.user
        response = client.post('/api/mobile/login/', {'mobile': user.login_mobile, 'password': 'Test-Password-2026!', **({'device_id': device_id} if device_id else {})}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        client.credentials(HTTP_AUTHORIZATION='Bearer ' + response.data['token'])
        if client == self.client: self.device = response.data['device_id']
        return response.data

    def op(self, kind, record_id=None, data=None, base=''):
        return {'id': str(uuid.uuid4()), 'kind': kind, 'record_id': record_id or str(uuid.uuid4()), 'base_version': base, 'data': data or {}}

    def push(self, operation, client=None):
        response = (client or self.client).post('/api/mobile/push/', operation, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def sale(self, **changes):
        return self.op('invoice.create', data={
            'customer': self.cid, 'date': timezone.localdate().isoformat(), 'number': '',
            'items': [{'product': self.pid, 'quantity': '2.000', 'unit_price': '100.00', 'gst_rate': '18.00', 'price_includes_tax': False}],
            'gst_enabled': True, 'discount': '10.00', 'paid_amount': '100.00', 'payment_method': 'cash', 'expected_total': '224.20', **changes})

    @override_settings(TESTING=False, DEBUG=False, SECURE_SSL_REDIRECT=False)
    def test_production_mobile_login_requires_https(self):
        data = {'mobile': self.user.login_mobile, 'password': 'Test-Password-2026!'}
        client = HTTPSAPIClient()
        rejected = client.post('/api/mobile/login/', data, format='json', HTTP_X_FORWARDED_PROTO='http')
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(str(rejected.data['detail']), 'HTTPS is required.')
        self.assertEqual(client.post('/api/mobile/login/', data, format='json').status_code, 200)

    def test_tokens_are_hashed_revocable_and_browser_auth_is_unchanged(self):
        device = m.MobileDevice.objects.get(pk=self.device)
        self.assertEqual(len(device.token_digest), 64)
        self.assertNotIn('sessionid', self.client.cookies)
        anonymous = HTTPSAPIClient(); self.assertEqual(anonymous.get('/api/mobile/pull/').status_code, 401)
        anonymous.force_login(self.user)
        self.assertEqual(anonymous.get('/api/mobile/pull/').status_code, 401)
        self.assertEqual(self.client.post('/api/mobile/devices/', {}, format='json').status_code, 200)
        self.assertEqual(self.client.get('/api/mobile/pull/').status_code, 401)

    def test_password_change_expiry_and_business_suspension_revoke_device(self):
        self.user.set_password('Changed-Password-2026!'); self.user.save()
        self.assertEqual(self.client.get('/api/mobile/pull/').status_code, 401)
        self.user.set_password('Test-Password-2026!'); self.user.save(); self.login(device_id=self.device)
        m.MobileDevice.objects.filter(pk=self.device).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.client.get('/api/mobile/pull/').status_code, 401)
        self.login(device_id=self.device); self.business.is_active=False;self.business.save()
        self.assertEqual(self.client.get('/api/mobile/pull/').status_code, 401)

    def test_device_reactivation_cannot_switch_business(self):
        other, _, _, _ = fixture('other@example.com')
        response = HTTPSAPIClient().post('/api/mobile/login/', {'mobile':other.login_mobile,'password':'Test-Password-2026!','device_id':self.device},format='json')
        self.assertEqual(response.status_code,403)

    def test_invoice_replay_preserves_stock_payment_and_original(self):
        op=self.sale();first=self.push(op);second=self.push(op)
        self.assertEqual(first['status'],'accepted');self.assertEqual(first,second)
        self.assertEqual(m.Invoice.objects.count(),1);self.assertEqual(m.Payment.objects.count(),1)
        invoice=m.Invoice.objects.get();self.assertEqual(invoice.total,Decimal('224.20'))
        self.product.refresh_from_db();self.assertEqual(self.product.stock,18)
        self.assertEqual(m.MobileOperation.objects.get().payload,op)
        op['data']['discount']='11.00'
        self.assertEqual(self.client.post('/api/mobile/push/',op,format='json').status_code,409)

    def test_offline_products_customers_and_invoice_dependencies(self):
        p=self.op('product.create',data={'name':'Rice','sku':'RICE','selling_price':'60.00','gst_rate':'5.00','stock':'10.000'})
        c=self.op('customer.create',data={'name':'Ravi','mobile':'9876543213'})
        self.assertEqual(self.push(p)['status'],'accepted');self.assertEqual(self.push(c)['status'],'accepted')
        self.pid=p['record_id'];self.cid=c['record_id']
        sale=self.sale(items=[{'product':self.pid,'quantity':'1','unit_price':'60.00','gst_rate':'5.00'}],discount='0',expected_total='63.00',paid_amount='0')
        self.assertEqual(self.push(sale)['status'],'accepted')
        self.assertEqual(m.Invoice.objects.get().customer.mobile,'+919876543213')

    def test_two_devices_overselling_preserves_both_sales_and_warns(self):
        self.product.stock=2;self.product.save()
        other=HTTPSAPIClient();self.login(other)
        self.assertEqual(self.push(self.sale())['status'],'accepted')
        result=self.push(self.sale(),other)
        self.assertEqual(result['status'],'accepted');self.assertIn('Stock reconciliation',result['warning'])
        self.product.refresh_from_db();self.assertEqual(self.product.stock,-2);self.assertEqual(m.Invoice.objects.count(),2)

    def test_reserved_ranges_do_not_overlap_web_or_other_phone(self):
        key=str(uuid.uuid4())
        first=self.client.post('/api/mobile/ranges/',{'id':key},format='json').data
        self.assertEqual(self.client.post('/api/mobile/ranges/',{'id':key},format='json').data,first)
        other=HTTPSAPIClient();self.login(other)
        second=other.post('/api/mobile/ranges/',{'id':str(uuid.uuid4())},format='json').data
        self.assertGreater(second['start'],first['end'])
        web,_=create_invoice(self.user,self.business,payload(self.product,self.customer))
        self.assertTrue(web.number.endswith('000201'))
        number=f"M{first['fiscal_year']%100:02d}-{first['start']:010d}"
        sale=self.sale(number=number)
        self.assertEqual(self.push(sale)['number'],number)
        self.assertEqual(self.push(self.sale(number=number),other)['status'],'conflict')

    def test_bad_totals_tax_or_number_preserve_event_without_mutating_finances(self):
        for change in [{'expected_total':'1.00'},{'number':'FORGED-1'}, {'items':[{'product':self.pid,'quantity':'2','unit_price':'100','gst_rate':'5'}]}]:
            self.assertEqual(self.push(self.sale(**change))['status'],'conflict')
        self.assertEqual(m.MobileOperation.objects.count(),3);self.assertFalse(m.Invoice.objects.exists())
        self.product.refresh_from_db();self.assertEqual(self.product.stock,20)

    def test_incremental_feed_sees_web_bulk_stock_and_deletions(self):
        cursor=self.page['cursor']
        unchanged=self.client.get('/api/mobile/pull/',{'cursor':cursor}).data
        self.assertEqual(unchanged['changes'],[])
        m.Product.objects.filter(pk=self.product.pk).update(stock=Decimal('17'))
        changed=self.client.get('/api/mobile/pull/',{'cursor':cursor}).data
        products=[r for r in changed['changes'] if r['kind']=='product']
        self.assertEqual(products[0]['data']['stock'],'17.000')
        self.customer.delete()
        tombstones=self.client.get('/api/mobile/pull/',{'cursor':changed['cursor']}).data['changes']
        self.assertTrue(any(c['kind']=='customer' and c['data'] is None for c in tombstones))

    def test_versions_prevent_profile_overwrite_but_stock_is_additive(self):
        base=fingerprint(wire(self.business,'product',self.product))
        self.product.selling_price=200;self.product.save()
        edit=self.op('product.update',self.pid,{'selling_price':'5'},base)
        self.assertEqual(self.push(edit)['status'],'conflict')
        adjust=self.op('stock.adjust',self.pid,{'delta':'3','reason':'Delivery'})
        self.assertEqual(self.push(adjust)['status'],'accepted');self.push(adjust)
        self.product.refresh_from_db();self.assertEqual(self.product.stock,23);self.assertEqual(self.product.selling_price,200)

    def test_cross_tenant_cursor_records_and_number_ranges_are_denied(self):
        other,_,_,_=fixture('other@example.com');client=HTTPSAPIClient();self.login(client,other)
        self.assertEqual(client.get('/api/mobile/pull/',{'cursor':self.page['cursor']}).status_code,400)
        result=self.push(self.op('stock.adjust',self.pid,{'delta':'100','reason':'Attack'}),client)
        self.assertEqual(result['status'],'conflict');self.product.refresh_from_db();self.assertEqual(self.product.stock,20)

    def test_payment_replay_deletion_and_refund_projection(self):
        sale=self.sale();self.push(sale)
        payment=self.op('payment.create',data={'invoice':sale['record_id'],'amount':'24.20','method':'cash'})
        self.push(payment);self.push(payment)
        self.assertEqual(m.Invoice.objects.get().paid_amount,Decimal('124.20'))
        base=fingerprint(wire(self.business,'customer',self.customer))
        self.assertEqual(self.push(self.op('customer.delete',self.cid,{},base))['status'],'accepted')
        invoice=m.Invoice.objects.get();self.assertEqual(invoice.customer_snapshot['name'],'A Customer')
        self.customer.refresh_from_db();self.assertFalse(self.customer.is_active)
        from billing.services import cancel_invoice
        cancel_invoice(self.user,self.business,invoice.pk,'Returned',True)
        feed=self.client.get('/api/mobile/pull/').data
        latest=[r for r in feed['changes'] if r['kind']=='invoice'][-1]
        self.assertIsNotNone(latest['data']['cancelled_at'])
        self.assertEqual(m.Refund.objects.get().amount,Decimal('124.20'))

    def test_viewer_and_cashier_permissions(self):
        member=self.user.membership;member.role='viewer';member.save()
        self.assertEqual(self.push(self.sale())['status'],'conflict')
        self.assertEqual(self.client.post('/api/mobile/ranges/',{'id':str(uuid.uuid4())},format='json').status_code,403)
        member.role='cashier';member.save()
        self.assertEqual(self.push(self.op('stock.adjust',self.pid,{'delta':'1','reason':'Stock'}))['status'],'conflict')
        self.assertEqual(self.push(self.sale())['status'],'accepted')

    def test_settings_update_versions_and_paginated_pull(self):
        base=fingerprint(wire(self.business,'business',self.business))
        op=self.op('business.settings',str(self.business.pk),{'upi_id':'new@upi','upi_payee_name':'New Payee'},base)
        self.assertEqual(self.push(op)['status'],'accepted')
        self.business.settings.refresh_from_db();self.assertEqual(self.business.settings.upi_id,'new@upi')
        stale=self.op('business.settings',str(self.business.pk),{'upi_id':'stale@upi'},base)
        self.assertEqual(self.push(stale)['status'],'conflict')
        m.Product.objects.bulk_create([m.Product(business=self.business,name=f'Item {i}',sku=f'NEW-{i}',selling_price=1) for i in range(205)])
        first=self.client.get('/api/mobile/pull/',{'cursor':self.page['cursor']}).data
        self.assertEqual(len(first['changes']),200);self.assertTrue(first['has_more'])
        second=self.client.get('/api/mobile/pull/',{'cursor':first['cursor']}).data
        self.assertFalse(second['has_more']);self.assertEqual(len(second['changes']),6)


@skipUnless(connection.vendor == 'postgresql', 'Row locks require PostgreSQL')
class AndroidConcurrentSyncTests(TransactionTestCase):
    def setUp(self):
        self.user,self.business,self.product,self.customer=fixture()
        client=HTTPSAPIClient()
        login=client.post('/api/mobile/login/',{'mobile':self.user.login_mobile,'password':'Test-Password-2026!'},format='json')
        self.assertEqual(
            login.status_code,
            200,
            getattr(login, "data", login.content.decode("utf-8", errors="replace")),
        )
        self.token=login.data['token'];client.credentials(HTTP_AUTHORIZATION='Bearer '+self.token)
        self.assertEqual(client.get('/api/mobile/pull/').status_code,200)
        self.pid=identity(self.business,'product',self.product.pk);self.cid=identity(self.business,'customer',self.customer.pk)

    def call(self,path,data):
        close_old_connections()
        try:
            client=HTTPSAPIClient();client.credentials(HTTP_AUTHORIZATION='Bearer '+self.token)
            response=client.post('/api/mobile/'+path+'/',data,format='json')
            return response.status_code,response.data
        finally: close_old_connections()

    def sale(self):
        key=str(uuid.uuid4())
        return {'id':key,'record_id':key,'kind':'invoice.create','data':{'customer':self.cid,'date':timezone.localdate().isoformat(),
            'items':[{'product':self.pid,'quantity':'2','unit_price':'100','gst_rate':'18'}],
            'gst_enabled':True,'discount':'0','paid_amount':'0','expected_total':'236.00'}}

    def test_concurrent_replay_commits_only_once(self):
        op=self.sale()
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda _:self.call('push',op),range(2)))
        self.assertTrue(all(code==200 and body['status']=='accepted' for code,body in results),results)
        self.assertEqual(m.Invoice.objects.count(),1);self.product.refresh_from_db();self.assertEqual(self.product.stock,18)

    def test_concurrent_ranges_are_disjoint(self):
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda _:self.call('ranges',{'id':str(uuid.uuid4())}),range(2)))
        self.assertTrue(all(code==200 for code,_ in results),results)
        ranges=sorted([body for _,body in results],key=lambda r:r['start'])
        self.assertLess(ranges[0]['end'],ranges[1]['start'])

    def test_concurrent_offline_sales_preserve_stock_discrepancy(self):
        self.product.stock=2;self.product.save()
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda _:self.call('push',self.sale()),range(2)))
        self.assertTrue(all(code==200 and body['status']=='accepted' for code,body in results),results)
        self.assertTrue(any(body.get('warning') for _,body in results))
        self.product.refresh_from_db();self.assertEqual(self.product.stock,-2);self.assertEqual(m.Invoice.objects.count(),2)
