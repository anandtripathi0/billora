import copy
import io
import json
from decimal import Decimal
from unittest.mock import patch
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError
from billing import models as m
from billing.inventory import read_catalog, validate_catalog, import_catalog, CATALOG_PATH
from billing.services import create_invoice, cancel_invoice, calculate_lines
from billing.printing import receipt_data
from billing.pdf import invoice_pdf
from .test_billing import fixture, payload

class InventoryTests(TestCase):
    def setUp(self):
        self.user,self.business,self.product,self.customer=fixture()
        self.client=APIClient();self.client.force_login(self.user)
        self.rows=read_catalog()
    def test_catalog_files_agree_and_cover_all_categories(self):
        json_rows=validate_catalog(self.rows,self.business)
        csv_rows=validate_catalog(read_catalog(CATALOG_PATH.with_suffix('.csv').read_bytes(),'catalog.csv'),self.business)
        self.assertEqual(json_rows,csv_rows);self.assertEqual(len(json_rows),200)
        self.assertEqual(len({r['category'] for r in json_rows}),23)
        self.assertEqual(sum(r['selling_price'] is None for r in json_rows),14)
        self.assertTrue(all(r['gst_rate'] is None and r['cost_price'] is None and r['mrp'] is None and r['barcode'] is None for r in json_rows))
        oils=[r for r in json_rows if r['category']=='Edible oils and ghee' and r['price_type']=='national_average']
        self.assertTrue(all(r['unit']=='kg' and r['pack_size']=='1 kg' for r in oils))
    def test_dry_run_has_no_side_effects(self):
        before=(m.Product.objects.count(),m.Category.objects.count(),m.AuditLog.objects.count())
        report=import_catalog(self.business,self.rows,dry_run=True)
        self.assertEqual(report['create_count'],200)
        self.assertEqual(before,(m.Product.objects.count(),m.Category.objects.count(),m.AuditLog.objects.count()))
    def test_exact_initial_stock_duplicate_import_and_manual_changes(self):
        report=import_catalog(self.business,self.rows)
        products=m.Product.objects.filter(sku__startswith='KIR-')
        self.assertEqual(products.count(),200)
        self.assertFalse(products.exclude(stock=100,opening_stock=100,low_stock_threshold=10).exists())
        product=products.get(sku=self.rows[0]['sku']);product.stock=Decimal('93.125');product.selling_price=Decimal('59.37');product.price_type='manual';product.save()
        second=import_catalog(self.business,self.rows)
        product.refresh_from_db()
        self.assertEqual((product.stock,product.selling_price),(Decimal('93.125'),Decimal('59.37')))
        self.assertEqual((second['create_count'],second['skipped_count']),(0,200))
        self.assertEqual(report['needs_review_count'],14)
    def test_tenant_isolation_and_mismatched_business_id(self):
        _,other,other_product,_=fixture('other@example.com')
        import_catalog(self.business,self.rows[:2])
        self.assertEqual(m.Product.objects.filter(business=other).count(),1)
        other_product.refresh_from_db();self.assertEqual(other_product.stock,20)
        rows=copy.deepcopy(self.rows[:1]);rows[0]['business_id']=str(other.pk)
        with self.assertRaises(ValidationError):import_catalog(self.business,rows)
    def test_invalid_later_row_rolls_back_whole_file(self):
        rows=copy.deepcopy(self.rows[:2]);rows[1]['current_stock']='99'
        with self.assertRaises(ValidationError):import_catalog(self.business,rows)
        self.assertFalse(m.Product.objects.filter(sku=self.rows[0]['sku']).exists())
        self.assertEqual(m.Category.objects.count(),0)
    def test_transaction_rolls_back_on_database_failure(self):
        with patch('billing.inventory.Product.objects.bulk_create', side_effect=RuntimeError('test failure')):
            with self.assertRaises(RuntimeError):import_catalog(self.business,self.rows[:2])
        self.assertEqual(m.Category.objects.count(),0)
    def test_duplicate_nonfinite_and_unverified_price_rejected(self):
        for mutation in ['duplicate','NaN','0','unverified']:
            rows=copy.deepcopy(self.rows[:1])
            if mutation=='duplicate':rows.append(copy.deepcopy(rows[0]))
            elif mutation=='unverified':rows[0]['price_verification_status']='needs_review'
            else:rows[0]['selling_price']=mutation
            with self.assertRaises(ValidationError):import_catalog(self.business,rows)
    def test_unknown_price_cannot_be_activated_or_billed_even_with_override(self):
        row=next(r for r in self.rows if r['selling_price'] is None)
        import_catalog(self.business,[row]);product=m.Product.objects.get(sku=row['sku'])
        self.assertFalse(product.is_active);self.assertIsNone(product.selling_price)
        with self.assertRaises(ValidationError):create_invoice(self.user,self.business,payload(product,self.customer,gst_enabled=False,items=[{'product':product.pk,'quantity':'1','unit_price':'0'}]))
        url=f'/api/products/{product.pk}/'
        self.assertEqual(self.client.patch(url,{'is_active':True},format='json').status_code,400)
        response=self.client.patch(url,{'selling_price':'99.25','is_active':True},format='json')
        self.assertEqual(response.status_code,200);self.assertEqual(response.data['price_verification_status'],'manual')
        product.refresh_from_db();invoice,_=create_invoice(self.user,self.business,payload(product,self.customer,gst_enabled=False))
        self.assertEqual(invoice.total,Decimal('198.50'))
    def test_stock_invoice_cancellation_snapshot_and_unknown_cost(self):
        import_catalog(self.business,self.rows[:1]);product=m.Product.objects.get(sku=self.rows[0]['sku'])
        invoice,_=create_invoice(self.user,self.business,payload(product,self.customer,gst_enabled=False,items=[{'product':product.pk,'quantity':'1.125'}]))
        self.assertEqual(invoice.total,Decimal('53.42'))
        product.refresh_from_db();self.assertEqual(product.stock,Decimal('98.875'))
        self.assertIsNone(invoice.items.get().purchase_price)
        receipt=receipt_data(invoice);self.assertEqual(receipt['items'][0]['unit_price'],'47.48');self.assertEqual(receipt['total'],'53.42')
        self.assertTrue(invoice_pdf(invoice).startswith(b'%PDF'))
        summary=self.client.get('/api/reports/').data['summary'];self.assertIsNone(summary['estimated_profit']);self.assertEqual(summary['missing_cost_lines'],1)
        self.assertEqual(self.client.get('/api/reports/?export=pdf').status_code,200)
        cancel_invoice(self.user,self.business,invoice.pk,'Test return');cancel_invoice(self.user,self.business,invoice.pk,'Retry')
        product.refresh_from_db();self.assertEqual(product.stock,100)
    def test_unknown_gst_rejected_and_inclusive_tax_not_added_twice(self):
        import_catalog(self.business,self.rows[:1]);product=m.Product.objects.get(sku=self.rows[0]['sku'])
        with self.assertRaises(ValidationError):create_invoice(self.user,self.business,payload(product,self.customer))
        product.selling_price=Decimal('118');product.gst_rate=Decimal('18');product.save()
        for interstate in [False,True]:
            lines,totals=calculate_lines({product.pk:product},[{'product':product.pk,'quantity':Decimal('2')}],Decimal('11.80'),True,interstate)
            self.assertEqual(totals['total'],Decimal('224.20'))
            self.assertEqual(totals['cgst']+totals['sgst']+totals['igst'],Decimal('34.20'))
            self.assertEqual(totals['subtotal']-totals['discount']+Decimal('34.20'),totals['total'])
    def test_preview_requires_owner_confirmation_and_signed_unchanged_file(self):
        preview=self.client.post('/api/products/catalog-preview/',{},format='json')
        self.assertEqual(preview.status_code,200);self.assertEqual(preview.data['total'],200)
        self.assertEqual(m.Product.objects.count(),1)
        token=preview.data['confirmation_token']
        self.assertEqual(self.client.post('/api/products/catalog-import/',{'confirmation_token':token},format='json').status_code,400)
        response=self.client.post('/api/products/catalog-import/',{'confirmation_token':token,'confirmed':True},format='json')
        self.assertEqual(response.status_code,200);self.assertEqual(response.data['create_count'],200)
        response=self.client.post('/api/products/catalog-import/',{'confirmation_token':token,'confirmed':True},format='json')
        self.assertEqual(response.data['create_count'],0)
    def test_upload_preview_change_detection_and_role_restriction(self):
        def upload(rows):return SimpleUploadedFile('catalog.json',json.dumps({'products':rows}).encode(),content_type='application/json')
        preview=self.client.post('/api/products/catalog-preview/',{'file':upload(self.rows[:1])},format='multipart')
        changed=copy.deepcopy(self.rows[:1]);changed[0]['name']='Changed'
        response=self.client.post('/api/products/catalog-import/',{'file':upload(changed),'confirmed':'true','confirmation_token':preview.data['confirmation_token']},format='multipart')
        self.assertEqual(response.status_code,400)
        m.Membership.objects.filter(user=self.user).update(role='cashier')
        self.assertEqual(self.client.post('/api/products/catalog-preview/',{},format='json').status_code,403)
    def test_search_brand_filters_review_and_template_tenant_id(self):
        import_catalog(self.business,self.rows)
        response=self.client.get('/api/products/?search=Sunlite&brand=Fortune')
        self.assertEqual(response.status_code,200);self.assertEqual(response.data['count'],2)
        self.assertEqual(self.client.get('/api/products/?needs_review=true').data['count'],14)
        response=self.client.get('/api/products/catalog-file/?export=json')
        self.assertEqual(json.loads(response.content)['products'][0]['business_id'],str(self.business.pk))
        self.assertEqual(len(self.client.get('/api/products/filters/').data['categories']),23)
    def test_cli_requires_confirm_and_dry_run_is_safe(self):
        output=io.StringIO()
        with self.assertRaises(CommandError):call_command('import_kirana_inventory',business_id=str(self.business.pk),stdout=output)
        call_command('import_kirana_inventory',business_id=str(self.business.pk),dry_run=True,stdout=output)
        self.assertEqual(m.Product.objects.count(),1)
        call_command('import_kirana_inventory',business_id=str(self.business.pk),confirm=True,stdout=output)
        self.assertEqual(m.Product.objects.filter(business=self.business).count(),201)
