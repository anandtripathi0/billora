import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from unittest import skipUnless
from django.db import connection, close_old_connections
from django.test import TestCase, TransactionTestCase, Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.exceptions import Throttled
from billing.models import Category, Product, RateLimit
from billing.auth import rate_limit
from .test_billing import fixture, payload
from billing.services import create_invoice

class PerformanceSecurityTests(TestCase):
    def setUp(self):
        self.user,self.business,self.product,self.customer=fixture()
        self.client=Client(enforce_csrf_checks=True)
        self.client.force_login(self.user,backend='billing.authentication.TenantBackend')

    def test_joined_session_and_csrf_query_budgets(self):
        with self.assertNumQueries(0):
            self.assertEqual(self.client.get('/api/auth/csrf/').status_code,200)
        with self.assertNumQueries(2):
            self.assertEqual(self.client.get('/api/auth/me/').status_code,200)
        with self.assertNumQueries(4):
            self.assertEqual(self.client.get('/api/products/?search=Notebook').status_code,200)

    def test_dashboard_aggregates_and_query_count_are_bounded(self):
        invoice,_=create_invoice(self.user,self.business,payload(self.product,self.customer))
        cat=Category.objects.create(business=self.business,name='Test')
        for i in range(6):Product.objects.create(business=self.business,category=cat,name=f'Low {i}',sku=f'LOW{i}',selling_price=1,stock=0)
        with self.assertNumQueries(7):
            summary=self.client.get('/api/dashboard/?section=summary').json()
        self.assertEqual(summary['total_invoices'],1)
        self.assertEqual(Decimal(str(summary['today_sales'])),invoice.total)
        self.assertEqual(len(summary['low_stock']),5)
        self.assertNotIn('revenue',summary)
        with self.assertNumQueries(4):
            widgets=self.client.get('/api/dashboard/?section=widgets').json()
        self.assertEqual(len(widgets['top_products']),1)
        self.assertNotIn('today_sales',widgets)

    def test_csrf_rotation_rejection_and_legacy_session(self):
        old=self.client.get('/api/auth/csrf/').json()['csrfToken']
        response=self.client.post('/api/auth/login/',json.dumps({'email':self.user.email.upper(),'password':'Test-Password-2026!'}),content_type='application/json',HTTP_X_CSRFTOKEN=old)
        self.assertEqual(response.status_code,200)
        rotated=response.json()['csrfToken']; self.assertNotEqual(old,rotated)
        bad=self.client.post('/api/categories/',{'name':'Must not create'},HTTP_X_CSRFTOKEN=old)
        self.assertEqual(bad.status_code,403);self.assertEqual(bad.json()['code'],'csrf_failed')
        self.assertFalse(Category.objects.filter(name='Must not create').exists())
        good=self.client.post('/api/categories/',{'name':'Allowed'},HTTP_X_CSRFTOKEN=rotated)
        self.assertEqual(good.status_code,201)
        self.client.force_login(self.user,backend='django.contrib.auth.backends.ModelBackend')
        self.assertEqual(self.client.get('/api/auth/me/').status_code,200)

    def test_timing_contains_no_identity_query_or_token(self):
        with self.assertLogs('billora.performance',level='INFO') as logs:
            response=self.client.get('/api/products/?search=private-person-and-token',HTTP_X_REQUEST_ID='malicious-header')
        data=json.loads(logs.records[-1].message)
        self.assertIn('db_ms',data); self.assertIn('total_ms',data)
        self.assertNotIn('private-person',logs.output[0]);self.assertNotIn('malicious-header',logs.output[0])
        self.assertNotIn(self.user.email,logs.output[0]);self.assertIn('Server-Timing',response)

    def test_limits_still_block_and_reset(self):
        rate_limit('unit','private',limit=2);rate_limit('unit','private',limit=2)
        with self.assertRaises(Throttled):rate_limit('unit','private',limit=2)
        RateLimit.objects.update(reset_at=timezone.now()-timedelta(seconds=1))
        rate_limit('unit','private',limit=2)
        self.assertEqual(RateLimit.objects.get().attempts,1)

    def test_default_access_logs_cannot_expose_query_values(self):
        from billing.timing import SafeRequestLog
        for name in ['django.server','django.request','django.security.csrf']:
            record=logging.LogRecord(name,logging.WARNING,'',0,'GET /api/customers/lookup/?mobile=private-value',(),None)
            SafeRequestLog().filter(record)
            self.assertNotIn('private-value',record.getMessage())
            self.assertIn('see_request_timing',record.getMessage())

@skipUnless(connection.vendor=='postgresql','Requires atomic PostgreSQL upsert.')
class ConcurrentThrottleTests(TransactionTestCase):
    def test_parallel_attempts_never_exceed_limit(self):
        def attempt(_):
            close_old_connections()
            try:
                rate_limit('parallel','synthetic',limit=7)
                return True
            except Throttled:return False
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=6) as pool: results=list(pool.map(attempt,range(20)))
        self.assertEqual(sum(results),7);self.assertEqual(RateLimit.objects.get().attempts,7)
