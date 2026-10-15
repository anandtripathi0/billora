"""Repeatable ORM/request benchmarks in an explicitly isolated database."""
import json
import math
import re
import statistics
import time
import uuid
from pathlib import Path
from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.test import Client
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone
from billing.models import User, Business, BusinessSettings, Membership, Customer, Product, Invoice, InvoiceItem

class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('--report', required=True)
        parser.add_argument('--samples', type=int, default=20)

    def handle(self, *args, **options):
        if not re.fullmatch(r'billora_perf_[a-f0-9]{12}', connection.settings_dict['NAME']):
            raise CommandError('Use config.performance_settings with an isolated performance database.')
        n = options['samples']
        if not 1 <= n <= 20: raise CommandError('Use 1–20 samples to retain real login rate limits.')
        tag = uuid.uuid4().hex[:10]
        password = 'Benchmark-only#42Strong'
        hashed = make_password(password)
        business = Business.objects.create(name='Synthetic performance fixture')
        BusinessSettings.objects.create(business=business)
        users = [User.objects.create(username=f'perf-{tag}-{i}@example.com', email=f'perf-{tag}-{i}@example.com', password=hashed) for i in range(5)]
        for user in users: Membership.objects.create(user=user, business=business, role='owner')
        customer = Customer.objects.create(business=business, name='Synthetic buyer', mobile='+919876543210')
        products = Product.objects.bulk_create([Product(business=business, name=f'Benchmark rice {i}', sku=f'PERF-{i}', selling_price=Decimal('10.00'), purchase_price=Decimal('5.00'), gst_rate=0, stock=10000) for i in range(200)])
        invoices = Invoice.objects.bulk_create([Invoice(business=business, number=f'SEED-{i}', idempotency_key=uuid.uuid4(), request_hash='', customer=customer, customer_snapshot={'name':'Synthetic buyer'}, business_snapshot={}, date=timezone.localdate(), supply_state='27', subtotal=10, total=10, created_by=users[0]) for i in range(1000)])
        InvoiceItem.objects.bulk_create([InvoiceItem(invoice=inv, product=products[i%200], description=products[i%200].name, sku=products[i%200].sku, unit='pcs', quantity=1, unit_price=10, purchase_price=5, gst_rate=0, subtotal=10, total=10, discount=0, cgst=0, sgst=0, igst=0) for i,inv in enumerate(invoices)])
        results = {}
        client = Client(enforce_csrf_checks=True)
        def measure(label, method, path, data=None, csrf=None):
            timings=[]
            def wrapper(execute, sql, params, many, context):
                start=time.perf_counter()
                try: return execute(sql,params,many,context)
                finally: timings.append((time.perf_counter()-start)*1000)
            start=time.perf_counter()
            with connection.execute_wrapper(wrapper):
                response=getattr(client,method)(path, data=json.dumps(data) if data is not None else None, content_type='application/json', HTTP_X_CSRFTOKEN=csrf or '', HTTP_ORIGIN='http://testserver')
            duration=(time.perf_counter()-start)*1000
            if response.status_code >= 400: raise CommandError(f'{label} failed with status {response.status_code}')
            results.setdefault(label,[]).append({'ms':round(duration,2),'queries':len(timings),'db_ms':round(sum(timings),2)})
            return response
        measure('first_csrf','get','/api/auth/csrf/')
        for i in range(n):
            token=measure('csrf','get','/api/auth/csrf/').json()['csrfToken']
            user=users[i%5]
            measure('login','post','/api/auth/login/',{'email':user.email,'password':password},token)
            token=client.cookies['csrftoken'].value
            measure('me','get','/api/auth/me/')
            measure('dashboard','get','/api/dashboard/')
            measure('products','get','/api/products/?search=rice')
            measure('customer_lookup','get','/api/customers/lookup/?mobile=9876543210')
            measure('invoice','post','/api/invoices/',{'customer':customer.pk,'items':[{'product':products[0].pk,'quantity':'1'}],'gst_enabled':False,'idempotency_key':str(uuid.uuid4())},token)
            measure('logout','post','/api/auth/logout/',{},token)
        for i in range(3):
            token=measure('csrf','get','/api/auth/csrf/').json()['csrfToken']
            measure('register','post','/api/auth/register/',{'email':f'reg-{tag}-{i}@example.com','owner_name':'Synthetic owner','business_name':'Synthetic store','mobile':'9876543211','password':password,'confirm_password':password},token)
        hashes=[]
        for _ in range(5):
            start=time.perf_counter(); check_password(password,hashed); hashes.append((time.perf_counter()-start)*1000)
        summary={}
        for label,rows in results.items():
            values=sorted(r['ms'] for r in rows)
            summary[label]={'n':len(rows),'p50_ms':round(statistics.median(values),2),'p95_ms':values[math.ceil(.95*len(values))-1] if len(values)>=20 else None,'queries_median':statistics.median(r['queries'] for r in rows),'db_p50_ms':round(statistics.median(r['db_ms'] for r in rows),2)}
        plans={
            'email_lookup':User.objects.filter(email__iexact=users[0].email).explain(format='json'),
            'product_search':Product.objects.filter(business=business,is_active=True,name__icontains='rice').order_by('-pk')[:25].explain(format='json'),
            'invoice_history':Invoice.objects.filter(business=business,cancelled_at__isnull=True).order_by('-date','-created_at')[:25].explain(format='json'),
            'customer_lookup':Customer.objects.filter(business=business,mobile=customer.mobile,merged_into__isnull=True).explain(format='json')}
        # Query plans can contain synthetic IDs/values only; no real tenant is queried.
        report={'environment':'Local Django test client, real Neon PostgreSQL, real Argon2; isolated synthetic data; excludes HTTP proxy/browser','fixture':{'products':200,'invoices':1000},'summary':summary,'samples':results,'password_verify_ms':hashes,'plans':{k:json.loads(v) for k,v in plans.items()}}
        Path(options['report']).write_text(json.dumps(report,indent=2),encoding='utf-8')
        self.stdout.write(json.dumps(summary,indent=2))
