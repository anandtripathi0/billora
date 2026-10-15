import uuid
from datetime import timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from billing import models as m
from billing.services import create_invoice, record_payment, cancel_invoice, upi_uri
from billing.collections import customer_totals
from billing.printing import digest
from .test_billing import fixture, payload

class RetailTests(TestCase):
    def setUp(self):
        self.user,self.business,self.product,self.customer=fixture()
        self.other,self.ob,self.op,self.oc=fixture('different@example.com')
        self.client=APIClient();self.client.force_login(self.user)
    def sale(self,**kw): return create_invoice(self.user,self.business,payload(self.product,self.customer,**kw))[0]
    def summary(self): return customer_totals(m.Customer.objects.filter(pk=self.customer.pk)).get()
    def test_mobile_lookup_normalizes_and_is_tenant_scoped(self):
        response=self.client.get('/api/customers/lookup/',{'mobile':'98765 43211'})
        self.assertEqual(response.data['customer']['id'],self.customer.pk)
        self.assertNotEqual(response.data['customer']['id'],self.oc.pk)
    def test_quick_customer_deduplicates_and_does_not_overwrite_name(self):
        first=self.client.post('/api/customers/quick/',{'name':'First','mobile':'9876543219'})
        second=self.client.post('/api/customers/quick/',{'name':'Overwrite','mobile':'+91 (98765) 43219'})
        self.assertEqual(first.status_code,201);self.assertEqual(second.status_code,200)
        self.assertEqual(first.data['id'],second.data['id']);self.assertEqual(second.data['name'],'First')
        duplicate=self.client.post('/api/customers/',{'name':'Duplicate','mobile':'9876543219'})
        self.assertEqual(duplicate.status_code,400)
    def test_duplicate_mobile_update_rejected(self):
        other=m.Customer.objects.create(business=self.business,name='B',mobile='+919876543299')
        response=self.client.patch(f'/api/customers/{other.pk}/',{'mobile':'9876543211'})
        self.assertEqual(response.status_code,400)
    def test_price_override_and_initial_payment_status(self):
        invoice=self.sale(items=[{'product':self.product.pk,'quantity':'2','unit_price':'125'}],payment_status='paid')
        self.assertEqual(invoice.total,Decimal('295'));self.assertEqual(invoice.paid_amount,invoice.total)
        self.assertEqual(invoice.payments.get().amount,invoice.total)
        self.product.refresh_from_db();self.assertEqual(self.product.selling_price,100)
    def test_invalid_partial_and_negative_price(self):
        for changes in [{'payment_status':'partial','paid_amount':'0'},{'payment_status':'partial','paid_amount':'236'}]:
            response=self.client.post('/api/invoices/',payload(self.product,self.customer,**changes),format='json')
            self.assertEqual(response.status_code,400)
        response=self.client.post('/api/invoices/preview/',{'items':[{'product':self.product.pk,'quantity':'1','unit_price':'-1'}]},format='json')
        self.assertEqual(response.status_code,400)
    def test_fast_save_checks_displayed_total_before_writing(self):
        response=self.client.post('/api/invoices/',payload(self.product,self.customer,expected_total='235'),format='json')
        self.assertEqual(response.status_code,400);self.assertEqual(m.Invoice.objects.count(),0)
        response=self.client.post('/api/invoices/',payload(self.product,self.customer,expected_total='236'),format='json')
        self.assertEqual(response.status_code,201)
    def test_aggregation_multiple_invoices_and_payments_no_multiplication(self):
        first=self.sale(gst_enabled=False,paid_amount='50');second=self.sale(gst_enabled=False,paid_amount='25')
        self.assertEqual(Decimal(second.customer_snapshot['previous_purchases']),200)
        self.assertEqual(Decimal(second.customer_snapshot['purchases_after']),400)
        payment={'amount':Decimal('30'),'method':'cash','idempotency_key':uuid.uuid4()}
        record_payment(self.user,self.business,first.pk,payment);record_payment(self.user,self.business,first.pk,payment)
        c=self.summary();self.assertEqual((c.order_count,c.purchases,c.payments_received,c.outstanding),(2,400,105,295))
    def test_unpaid_cancel_restores_stock_once_and_excludes_all_reports(self):
        invoice=self.sale()
        for _ in range(2): cancel_invoice(self.user,self.business,invoice.pk,'Customer returned all items')
        self.product.refresh_from_db();self.assertEqual(self.product.stock,20)
        c=self.summary();self.assertEqual((c.order_count,c.purchases,c.outstanding),(0,0,0))
        self.assertEqual(self.client.get('/api/dashboard/').data['total_invoices'],0)
        self.assertEqual(self.client.get('/api/reports/').data['summary']['sales'],0)
    def test_paid_cancel_requires_confirmed_refund_preserves_payment_history(self):
        invoice=self.sale(paid_amount='36')
        url=f'/api/invoices/{invoice.pk}/cancel/'
        self.assertEqual(self.client.post(url,{'reason':'Return'},format='json').status_code,400)
        for _ in range(2): self.assertEqual(self.client.post(url,{'reason':'Return','refund_confirmed':True},format='json').status_code,200)
        self.assertEqual(m.Refund.objects.get().amount,36);self.assertEqual(invoice.payments.count(),1)
        self.assertEqual((self.summary().payments_received,self.summary().outstanding),(0,0))
        invoice.refresh_from_db();self.assertEqual(invoice.status,'cancelled');self.assertEqual(upi_uri(invoice),'')
        response=self.client.post(f'/api/invoices/{invoice.pk}/pay/',{'amount':'1','method':'cash','idempotency_key':str(uuid.uuid4())},format='json')
        self.assertEqual(response.status_code,400)
    def test_cancel_tenant_and_role_checks(self):
        invoice=self.sale();m.Membership.objects.filter(user=self.user).update(role='cashier')
        self.assertEqual(self.client.post(f'/api/invoices/{invoice.pk}/cancel/',{'reason':'x'}).status_code,403)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(f'/api/invoices/{invoice.pk}/cancel/',{'reason':'x'}).status_code,404)
    def test_receipt_exact_balance_qr_and_disable(self):
        invoice=self.sale(paid_amount='36')
        r=self.client.get(f'/api/invoices/{invoice.pk}/receipt/').data
        self.assertEqual(parse_qs(urlsplit(r['upi_uri']).query)['am'],['200.00']);self.assertTrue(r['qr_image'].startswith('data:image/png;base64,'))
        invoice.include_upi_qr=False;invoice.save()
        self.assertEqual(self.client.get(f'/api/invoices/{invoice.pk}/receipt/').data['qr_image'],'')
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(f'/api/invoices/{invoice.pk}/receipt/').status_code,404)
    def test_history_chronological_and_cancelled_retained(self):
        a=self.sale(date='2026-01-01');b=self.sale(date='2026-02-01');cancel_invoice(self.user,self.business,a.pk,'Returned')
        r=self.client.get(f'/api/customers/{self.customer.pk}/ledger/').data['results']
        self.assertEqual([x['id'] for x in r],[str(a.pk),str(b.pk)]);self.assertEqual(r[0]['status'],'cancelled')

class PrintQueueTests(TestCase):
    def setUp(self):
        self.user,self.business,self.product,self.customer=fixture()
        self.invoice=create_invoice(self.user,self.business,payload(self.product,self.customer))[0]
        self.client=APIClient();self.client.force_login(self.user)
        response=self.client.post('/api/printing/devices/',{'name':'Counter','width':58},format='json')
        self.device_id=response.data['id'];self.code=response.data['pairing_code']
        self.agent=APIClient()
        paired=self.agent.post('/api/printing/agent/pair/',{'code':self.code},format='json')
        self.token=paired.data['token'];self.agent.credentials(HTTP_AUTHORIZATION='Bearer '+self.token)
        self.agent.post('/api/printing/agent/poll/',{},format='json')
    def body(self): return {'invoice':str(self.invoice.pk),'device':self.device_id,'width':58,'idempotency_key':str(uuid.uuid4())}
    def test_pair_one_use_and_no_browser_pairing(self):
        public=APIClient()
        self.assertEqual(public.post('/api/printing/agent/pair/',{'code':self.code},format='json').status_code,404)
        self.assertEqual(self.agent.post('/api/printing/agent/poll/',{},format='json',HTTP_ORIGIN='https://evil.example').status_code,401)
        self.assertEqual(public.post('/api/printing/agent/poll/',{},format='json').status_code,401)
        device=m.PrintDevice.objects.get();self.assertEqual(device.token_digest,digest(self.token));self.assertNotEqual(device.token_digest,self.token)
        self.assertNotIn('token',self.client.get('/api/printing/devices/').data[0])
    def test_queue_retry_dedup_claim_once_ack_once(self):
        body=self.body();a=self.client.post('/api/printing/jobs/',body,format='json');b=self.client.post('/api/printing/jobs/',body,format='json')
        self.assertEqual(a.status_code,201);self.assertEqual(a.data['id'],b.data['id'])
        claimed=self.agent.post('/api/printing/agent/poll/',{},format='json').data['job'];self.assertEqual(claimed['width'],58);self.assertEqual(claimed['receipt']['number'],self.invoice.number)
        self.assertIsNone(self.agent.post('/api/printing/agent/poll/',{},format='json').data['job'])
        for _ in range(2): self.agent.post('/api/printing/agent/ack/',{'job':a.data['id'],'status':'spooled','detail':'Mock accepted'},format='json')
        self.assertEqual(m.PrintJob.objects.get().status,'spooled');self.assertEqual(m.Invoice.objects.count(),1)
        self.assertEqual(m.PrintJob.objects.count(),1);self.product.refresh_from_db();self.assertEqual(self.product.stock,18)
    def test_offline_and_stale_jobs_do_not_print_later(self):
        m.PrintDevice.objects.filter(pk=self.device_id).update(last_seen=timezone.now()-timedelta(minutes=1))
        self.assertEqual(self.client.post('/api/printing/jobs/',self.body(),format='json').status_code,503)
        self.agent.post('/api/printing/agent/poll/',{},format='json')
        r=self.client.post('/api/printing/jobs/',self.body(),format='json')
        m.PrintJob.objects.filter(pk=r.data['id']).update(created_at=timezone.now()-timedelta(minutes=1))
        self.assertIsNone(self.agent.post('/api/printing/agent/poll/',{},format='json').data['job'])
        self.assertEqual(m.PrintJob.objects.get().status,'failed')
    def test_processing_timeout_is_uncertain_and_never_reclaimed(self):
        r=self.client.post('/api/printing/jobs/',self.body(),format='json')
        self.agent.post('/api/printing/agent/poll/',{},format='json')
        m.PrintJob.objects.update(claimed_at=timezone.now()-timedelta(minutes=3))
        self.assertEqual(self.client.get('/api/printing/jobs/'+r.data['id']+'/').data['status'],'uncertain')
        self.assertIsNone(self.agent.post('/api/printing/agent/poll/',{},format='json').data['job'])
    def test_revoke_stops_jobs_and_token(self):
        self.client.post('/api/printing/jobs/',self.body(),format='json')
        self.assertEqual(self.client.delete('/api/printing/devices/',{'id':self.device_id},format='json').status_code,200)
        self.assertEqual(m.PrintJob.objects.get().status,'cancelled')
        self.assertEqual(self.agent.post('/api/printing/agent/poll/',{},format='json').status_code,401)
    def test_print_tenant_isolation_and_cancellation(self):
        other,ob,op,oc=fixture('other@example.com');self.client.force_login(other)
        self.assertEqual(self.client.post('/api/printing/jobs/',self.body(),format='json').status_code,404)
        self.client.force_login(self.user);body=self.body();self.client.post('/api/printing/jobs/',body,format='json')
        cancel_invoice(self.user,self.business,self.invoice.pk,'Returned')
        self.assertEqual(m.PrintJob.objects.get().status,'cancelled')
        self.assertIsNone(self.agent.post('/api/printing/agent/poll/',{},format='json').data['job'])
