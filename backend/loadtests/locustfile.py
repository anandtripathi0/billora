"""Run only against a disposable database seeded with seed_loadtest."""
import itertools
import os
import uuid
from locust import HttpUser, task, between

counter = itertools.count(1)

class BillingUser(HttpUser):
    wait_time = between(1, 3)
    def on_start(self):
        user = next(counter)
        password = os.environ['LOAD_TEST_PASSWORD']
        self.client.get('/api/auth/csrf/')
        self.client.headers['X-CSRFToken'] = self.client.cookies.get('csrftoken')
        response = self.client.post('/api/auth/login/',json={'email':f'load{user}@billora.local','password':password})
        response.raise_for_status()
        self.client.headers['X-CSRFToken'] = self.client.cookies.get('csrftoken')
        self.product = self.client.get('/api/products/').json()['results'][0]['id']
        self.customer = self.client.get('/api/customers/').json()['results'][0]['id']
        self.invoice = None
    @task(5)
    def search_products(self): self.client.get('/api/products/?search=Load', name='Product search')
    @task(2)
    def create_invoice(self):
        response = self.client.post('/api/invoices/',json={'customer':self.customer,'items':[{'product':self.product,'quantity':'1'}],
            'idempotency_key':str(uuid.uuid4()),'gst_enabled':False},name='Invoice creation / database write')
        if response.status_code == 201: self.invoice = response.json()['id']
    @task(1)
    def pdf(self):
        if self.invoice: self.client.get(f'/api/invoices/{self.invoice}/pdf/',name='Invoice PDF generation')
