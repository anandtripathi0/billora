import os
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from billing.models import User, Business, BusinessSettings, Membership, Product, Customer

class Command(BaseCommand):
    help = 'Seed 50 isolated load-test tenants on a disposable development PostgreSQL database.'
    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG or os.environ.get('ALLOW_LOAD_TEST_SEED') != 'true':
            raise CommandError('Requires DEBUG=true and ALLOW_LOAD_TEST_SEED=true on a disposable database.')
        password = os.environ.get('LOAD_TEST_PASSWORD')
        if not password: raise CommandError('Set LOAD_TEST_PASSWORD first.')
        for i in range(1,51):
            email = f'load{i}@billora.local'
            if User.objects.filter(email=email).exists(): continue
            user = User.objects.create_user(username=email,email=email,password=password,first_name=f'Load {i}')
            business = Business.objects.create(name=f'Load test {i}')
            BusinessSettings.objects.create(business=business)
            Membership.objects.create(user=user,business=business)
            Product.objects.create(business=business,name='Load product',sku='LOAD',selling_price='100',purchase_price='50',stock='100000')
            Customer.objects.create(business=business,name='Load customer',mobile='+919876543210')
        self.stdout.write('50 disposable load-test workspaces are ready. Run a single Locust process.')
