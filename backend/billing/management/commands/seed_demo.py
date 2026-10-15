from decimal import Decimal
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from billing.models import User, Business, BusinessSettings, Membership, Category, Product, Customer

class Command(BaseCommand):
    help = 'Create development-only sample records. Never runs in production.'
    def add_arguments(self, parser):
        parser.add_argument('--email', default='owner@billora.local')
        parser.add_argument('--password', required=True, help='Development-only account password.')
    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG: raise CommandError('Sample data is permitted only when DEBUG=true.')
        email = options['email'].lower()
        if User.objects.filter(email=email).exists(): raise CommandError('This account already exists; existing records were not changed.')
        user = User.objects.create_user(username=email, email=email, password=options['password'], first_name='Aarav', mobile='+919876543210')
        business = Business.objects.create(name='The Everyday Store', address='12, Market Road, Pune, Maharashtra 411001', mobile=user.mobile)
        BusinessSettings.objects.create(business=business, upi_id='example@upi', upi_payee_name=business.name)
        Membership.objects.create(user=user, business=business)
        category = Category.objects.create(business=business, name='Daily essentials')
        for name, sku, price, cost, stock in [('Hardcover notebook','NB-001','249','160','45'),('Ceramic coffee mug','MG-001','399','240','4'),('Canvas tote bag','TB-001','349','200','28')]:
            Product.objects.create(business=business, category=category, name=name, sku=sku, selling_price=Decimal(price), purchase_price=Decimal(cost), stock=Decimal(stock), gst_rate=18)
        Customer.objects.create(business=business, name='Sample Customer', mobile='+919876543211', state_code='27')
        self.stdout.write(self.style.SUCCESS(f'Development workspace created for {email}. No sample invoices or payments were created.'))
