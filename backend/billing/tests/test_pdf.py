import io
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from pypdf import PdfReader
from rest_framework.test import APIClient
from billing.pdf import invoice_pdf, paragraph
from billing.services import create_invoice, record_payment
from .test_billing import fixture, payload

class PdfRenderingTests(TestCase):
    def setUp(self):
        self.user,self.business,self.product,self.customer=fixture()
        self.invoice,_=create_invoice(self.user,self.business,payload(self.product,self.customer))

    def text(self, content):
        return '\n'.join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)

    def test_pdf_snapshot_and_qr_render_without_storage(self):
        with patch('pathlib.Path.write_bytes', side_effect=AssertionError('No persistent PDFs')):
            content=invoice_pdf(self.invoice)
        self.assertTrue(content.startswith(b'%PDF-'))
        reader=PdfReader(io.BytesIO(content))
        text=self.text(content)
        for value in ['Test Store', 'A Customer', 'INV-000001', 'Notebook', '236.00', 'UNPAID', 'store@upi']:
            self.assertIn(value,text)
        self.assertEqual(len(reader.pages),1)
        self.assertTrue(any(page.images for page in reader.pages))
        self.product.name='Edited product';self.product.save()
        self.customer.name='Edited customer';self.customer.save()
        self.assertIn('Notebook',self.text(invoice_pdf(self.invoice)))
        self.assertNotIn('Edited customer',self.text(invoice_pdf(self.invoice)))

    def test_download_and_public_share_use_real_pdf(self):
        from urllib.parse import urlparse
        client=APIClient();client.force_login(self.user)
        response=client.get(f'/api/invoices/{self.invoice.pk}/pdf/?download=1')
        self.assertEqual(response.status_code,200)
        self.assertIn('attachment',response['Content-Disposition'])
        response=client.post(f'/api/invoices/{self.invoice.pk}/share/',{},format='json')
        self.assertEqual(response.status_code,200)
        path=urlparse(response.data['url']).path
        response=APIClient().get(path)
        self.assertEqual(response.status_code,200)
        self.assertIn('Notebook',self.text(response.content))
        self.assertEqual(response['Cache-Control'],'private, no-store')

    def test_paid_pdf_has_updated_balance_and_no_qr(self):
        import uuid
        record_payment(self.user,self.business,self.invoice.pk,{'amount':Decimal('236'),'method':'cash','idempotency_key':uuid.uuid4()})
        self.invoice.refresh_from_db()
        content=invoice_pdf(self.invoice)
        self.assertIn('PAID',self.text(content))
        self.assertFalse(any(page.images for page in PdfReader(io.BytesIO(content)).pages))

    def test_multipage_product_table_and_untrusted_text(self):
        from billing.models import InvoiceItem
        original=self.invoice.items.get()
        for index in range(40):
            original.pk=None;original.description=f'Item {index} <b>Literal text</b>';original.save()
        content=invoice_pdf(self.invoice)
        reader=PdfReader(io.BytesIO(content))
        self.assertGreater(len(reader.pages),1)
        self.assertIn('<b>Literal text</b>',self.text(content))
        self.assertIn('PRODUCT / HSN',reader.pages[1].extract_text())

    def test_report_pdf(self):
        self.assertEqual(paragraph(Decimal('0.00')).getPlainText(), '0.00')
        client=APIClient();client.force_login(self.user)
        response=client.get('/api/reports/?kind=stock&export=pdf')
        self.assertEqual(response.status_code,200)
        self.assertIn('Notebook',self.text(response.content))

    def test_public_render_rate_limit_prevents_another_pdf(self):
        import hashlib
        from datetime import timedelta
        from django.utils import timezone
        from billing.models import SharingToken, RateLimit
        raw='public-render-limit-test'
        digest=hashlib.sha256(raw.encode()).hexdigest()
        SharingToken.objects.create(invoice=self.invoice,digest=digest,expires_at=timezone.now()+timedelta(days=1))
        key=hashlib.sha256(f'public-share-render:{digest}'.encode()).hexdigest()
        RateLimit.objects.create(key=key,attempts=30,reset_at=timezone.now()+timedelta(seconds=60))
        with patch('billing.views.invoice_pdf') as render:
            self.assertEqual(APIClient().get(f'/api/shared/{raw}/').status_code,429)
            render.assert_not_called()
