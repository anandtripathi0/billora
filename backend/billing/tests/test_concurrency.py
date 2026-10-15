from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest import skipUnless
from django.db import connection, close_old_connections
from django.test import TransactionTestCase
from billing.models import User, Business, Product, Invoice
from billing.services import create_invoice
from rest_framework.exceptions import ValidationError
from .test_billing import fixture, payload

@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL row-level locks; SQLite cannot validate concurrency.')
class ConcurrentInvoiceTests(TransactionTestCase):
    def setUp(self): self.user,self.business,self.product,self.customer=fixture()
    def test_parallel_catalog_import_is_idempotent_and_preserves_sales(self):
        from billing.inventory import read_catalog, import_catalog
        rows=read_catalog()[:2]
        def run_import(_):
            close_old_connections()
            try:return import_catalog(Business.objects.get(pk=self.business.pk),rows)['create_count']
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:counts=list(pool.map(run_import,range(2)))
        self.assertEqual(sorted(counts),[0,2])
        product=Product.objects.get(business=self.business,sku=rows[0]['sku'])
        data=payload(product,self.customer,gst_enabled=False,items=[{'product':product.pk,'quantity':'1.125'}])
        with ThreadPoolExecutor(max_workers=2) as pool:
            imported=pool.submit(run_import,0)
            invoice=pool.submit(self.run_invoice,data)
            self.assertEqual(imported.result(),0);self.assertNotEqual(invoice.result(),'rejected')
        product.refresh_from_db();self.assertEqual(product.stock,Decimal('98.875'))
    def run_invoice(self, data):
        close_old_connections()
        try:
            user=User.objects.get(pk=self.user.pk);business=Business.objects.get(pk=self.business.pk)
            return str(create_invoice(user,business,data)[0].pk)
        except ValidationError: return 'rejected'
        finally: close_old_connections()
    def test_parallel_numbers_are_unique_and_stock_atomic(self):
        data=[payload(self.product,self.customer,items=[{'product':self.product.pk,'quantity':'1'}]) for _ in range(10)]
        with ThreadPoolExecutor(max_workers=5) as pool: results=list(pool.map(self.run_invoice,data))
        self.assertNotIn('rejected',results);self.assertEqual(len(set(results)),10)
        self.product.refresh_from_db();self.assertEqual(self.product.stock,10)
        self.assertEqual(len(set(Invoice.objects.values_list('number',flat=True))),10)
    def test_parallel_duplicate_submission(self):
        data=payload(self.product,self.customer)
        with ThreadPoolExecutor(max_workers=5) as pool: results=list(pool.map(self.run_invoice,[data]*5))
        self.assertEqual(len(set(results)),1);self.product.refresh_from_db();self.assertEqual(self.product.stock,18)
    def test_parallel_oversell_is_prevented(self):
        data=[payload(self.product,self.customer,items=[{'product':self.product.pk,'quantity':'15'}]) for _ in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(self.run_invoice,data))
        self.assertEqual(results.count('rejected'),1);self.product.refresh_from_db();self.assertEqual(self.product.stock,5)

    def test_parallel_customer_mobile_upsert(self):
        from rest_framework.test import APIClient
        from billing.models import Customer
        def quick(_):
            close_old_connections()
            try:
                client=APIClient();client.force_authenticate(User.objects.get(pk=self.user.pk))
                response=client.post('/api/customers/quick/',{'name':'Concurrent customer','mobile':'9876543299'},format='json')
                return response.status_code,response.data.get('id')
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=5) as pool: results=list(pool.map(quick,range(5)))
        self.assertEqual([r[0] for r in results].count(201),1)
        self.assertEqual(len({r[1] for r in results}),1)
        self.assertEqual(Customer.objects.filter(business=self.business,mobile='+919876543299').count(),1)

    def test_parallel_payments_and_cancel_do_not_double_refund(self):
        from billing.services import record_payment,cancel_invoice
        from billing.models import Refund,Payment
        import uuid
        invoice=create_invoice(self.user,self.business,payload(self.product,self.customer))[0]
        data={'amount':Decimal('36'),'method':'cash','idempotency_key':uuid.uuid4()}
        def pay(_):
            close_old_connections()
            try:return record_payment(User.objects.get(pk=self.user.pk),Business.objects.get(pk=self.business.pk),invoice.pk,data).pk
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=5) as pool: results=list(pool.map(pay,range(5)))
        self.assertEqual(len(set(results)),1);self.assertEqual(Payment.objects.count(),1)
        def cancel(_):
            close_old_connections()
            try:return cancel_invoice(User.objects.get(pk=self.user.pk),Business.objects.get(pk=self.business.pk),invoice.pk,'Returned',True).pk
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=3) as pool: list(pool.map(cancel,range(3)))
        self.assertEqual(Refund.objects.count(),1);self.product.refresh_from_db();self.assertEqual(self.product.stock,20)
