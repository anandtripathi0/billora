import uuid
from decimal import Decimal
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.functional import cached_property
from django.db.models.functions import Upper

ZERO = Decimal('0.00')

class User(AbstractUser):
    username = models.CharField(max_length=254, unique=True)
    email = models.EmailField(unique=True)
    mobile = models.CharField(max_length=16, blank=True)
    class Meta:
        verbose_name = 'user'
        verbose_name_plural = 'users'
        abstract = False
        indexes = [models.Index(Upper('email'), name='billing_user_email_upper')]

class Business(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160)
    address = models.TextField(blank=True)
    gstin = models.CharField(max_length=15, blank=True)
    state_code = models.CharField(max_length=2, default='27')
    mobile = models.CharField(max_length=16, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    next_invoice_number = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return self.name

class BusinessSettings(models.Model):
    business = models.OneToOneField(Business, on_delete=models.CASCADE, related_name='settings')
    timezone = models.CharField(max_length=64, default='Asia/Kolkata')
    invoice_prefix = models.CharField(max_length=12, default='INV')
    upi_id = models.CharField(max_length=120, blank=True)
    upi_payee_name = models.CharField(max_length=120, blank=True)
    qr_default = models.BooleanField(default=False)
    receipt_width = models.PositiveSmallIntegerField(default=80, choices=[(58, '58 mm'), (80, '80 mm')])
    allow_negative_stock = models.BooleanField(default=False)
    invoice_footer = models.CharField(max_length=300, default='Thank you for your business!')
    logo_data = models.TextField(blank=True)  # Validated, resized PNG only, max 150 KB.

class Membership(models.Model):
    ROLES = [('owner', 'Owner'), ('manager', 'Manager'), ('cashier', 'Cashier'), ('viewer', 'Viewer')]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='membership')
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField(max_length=10, choices=ROLES, default='owner')

class TenantModel(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: abstract = True

class Category(TenantModel):
    name = models.CharField(max_length=80)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['business', 'name'], name='unique_category_per_business')]

class InvoiceLogo(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    digest = models.CharField(max_length=64)
    data = models.TextField()
    class Meta:
        constraints = [models.UniqueConstraint(fields=['business','digest'], name='unique_logo_per_business')]

class Product(TenantModel):
    name = models.CharField(max_length=180)
    sku = models.CharField(max_length=64)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(ZERO)])
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, default=None, validators=[MinValueValidator(ZERO)])
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, default=None, validators=[MinValueValidator(ZERO), MaxValueValidator(100)])
    brand = models.CharField(max_length=80, blank=True)
    pack_size = models.CharField(max_length=100, blank=True)
    mrp = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(ZERO)])
    opening_stock = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    price_includes_tax = models.BooleanField(default=False)
    price_source_url = models.URLField(max_length=600, blank=True)
    price_checked_date = models.DateField(null=True, blank=True)
    source_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    price_type = models.CharField(max_length=20, default='manual', choices=[(s, s) for s in ['national_average', 'retailer_listing', 'manual']])
    price_verification_status = models.CharField(max_length=24, default='manual', choices=[(s, s) for s in ['national_reference', 'retailer_observed', 'manual', 'needs_review']])
    source_notes = models.TextField(blank=True)
    hsn_code = models.CharField(max_length=16, blank=True)
    stock = models.DecimalField(max_digits=12, decimal_places=3, default=ZERO)
    low_stock_threshold = models.DecimalField(max_digits=12, decimal_places=3, default=5, validators=[MinValueValidator(ZERO)])
    unit = models.CharField(max_length=16, default='pcs')
    barcode = models.CharField(max_length=80, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['business', 'sku'], name='unique_sku_per_business'),
            models.CheckConstraint(condition=Q(selling_price__gte=0, purchase_price__gte=0, gst_rate__gte=0, gst_rate__lte=100), name='valid_product_prices'),
            models.CheckConstraint(condition=Q(is_active=False) | Q(selling_price__isnull=False), name='active_product_has_price')]
        indexes = [models.Index(fields=['business', 'is_active', 'name'])]
    def __str__(self): return self.name

class Customer(TenantModel):
    name = models.CharField(max_length=160)
    mobile = models.CharField(max_length=16)
    whatsapp = models.CharField(max_length=16, blank=True)
    address = models.TextField(blank=True)
    gstin = models.CharField(max_length=15, blank=True)
    state_code = models.CharField(max_length=2, blank=True)
    consent_whatsapp = models.BooleanField(default=False)
    merged_into = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, editable=False)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['business', 'mobile'], condition=Q(merged_into__isnull=True), name='unique_active_customer_mobile')]
        indexes = [models.Index(fields=['business', 'name']), models.Index(fields=['business', 'mobile'])]
    def __str__(self): return self.name

class Invoice(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=40)
    idempotency_key = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='invoices')
    customer_snapshot = models.JSONField()
    business_snapshot = models.JSONField()
    date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    supply_state = models.CharField(max_length=2)
    gst_enabled = models.BooleanField(default=False)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2)
    discount = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    cgst = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    sgst = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    igst = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    total = models.DecimalField(max_digits=14, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    payment_method = models.CharField(max_length=12, default='cash')
    include_upi_qr = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    revision = models.PositiveIntegerField(default=1)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=300, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['business', 'number'], name='unique_invoice_number'),
            models.UniqueConstraint(fields=['business', 'idempotency_key'], name='unique_invoice_submission'),
            models.CheckConstraint(condition=Q(total__gte=0, paid_amount__gte=0, paid_amount__lte=models.F('total')), name='valid_invoice_payment')]
        indexes = [models.Index(fields=['business', '-date']), models.Index(fields=['business', 'customer']),
            models.Index(fields=['business', '-date', '-created_at'], name='billing_invoice_history')]
    @property
    def balance(self): return ZERO if self.cancelled_at else self.total - self.paid_amount
    @property
    def status(self): return 'cancelled' if self.cancelled_at else 'paid' if self.balance == 0 else 'partial' if self.paid_amount > 0 else 'unpaid'
    @cached_property
    def logo_data(self):
        key = self.business_snapshot.get('logo_key')
        if not key: return self.business_snapshot.get('logo_data', '')
        return InvoiceLogo.objects.filter(pk=key, business_id=self.business_id).values_list('data', flat=True).first() or ''
    @cached_property
    def ordered_items(self):
        # Immutable invoice snapshots, cached only on this request's instance.
        return list(self.items.order_by('id'))

class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    description = models.CharField(max_length=180)
    sku = models.CharField(max_length=64)
    hsn_code = models.CharField(max_length=16, blank=True)
    unit = models.CharField(max_length=16)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    price_includes_tax = models.BooleanField(default=False)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2)
    discount = models.DecimalField(max_digits=14, decimal_places=2)
    cgst = models.DecimalField(max_digits=14, decimal_places=2)
    sgst = models.DecimalField(max_digits=14, decimal_places=2)
    igst = models.DecimalField(max_digits=14, decimal_places=2)
    total = models.DecimalField(max_digits=14, decimal_places=2)

class Payment(TenantModel):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    method = models.CharField(max_length=12)
    reference = models.CharField(max_length=120, blank=True)
    idempotency_key = models.UUIDField(default=uuid.uuid4)
    recorded_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['business', 'idempotency_key'], name='unique_payment_submission'),
            models.CheckConstraint(condition=Q(amount__gt=0), name='positive_payment')]
        indexes = [models.Index(fields=['business', '-created_at'])]

class Refund(TenantModel):
    """Full, manually confirmed refund when cancelling a finalized sale."""
    invoice = models.OneToOneField(Invoice, on_delete=models.PROTECT, related_name='refund')
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    recorded_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    class Meta:
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name='positive_refund')]

class PrintDevice(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=80)
    token_digest = models.CharField(max_length=64, blank=True)
    pairing_digest = models.CharField(max_length=64, blank=True)
    pairing_expires_at = models.DateTimeField()
    last_seen = models.DateTimeField(null=True)
    width = models.PositiveSmallIntegerField(default=80)
    is_active = models.BooleanField(default=True)

class PrintJob(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(PrintDevice, on_delete=models.PROTECT)
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT)
    idempotency_key = models.UUIDField()
    width = models.PositiveSmallIntegerField(default=80)
    status = models.CharField(max_length=20, default='queued', choices=[(s, s) for s in ['queued','processing','spooled','failed','uncertain','cancelled']])
    detail = models.CharField(max_length=300, blank=True)
    claimed_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['business', 'idempotency_key'], name='unique_print_submission')]
        indexes = [models.Index(fields=['device', 'status', 'created_at'])]

class SharingToken(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='sharing_tokens')
    digest = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

class MessageLog(TenantModel):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE)
    status = models.CharField(max_length=32, default='link_prepared')
    provider_id = models.CharField(max_length=160, blank=True)

class AuditLog(models.Model):
    business = models.ForeignKey(Business, null=True, on_delete=models.SET_NULL)
    actor = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=100)
    object_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    class Meta: ordering = ['-created_at']

class SubscriptionPlan(models.Model):
    name = models.CharField(max_length=60, unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(ZERO)])
    interval = models.CharField(max_length=10, choices=[('month', 'Month'), ('year', 'Year')])
    is_active = models.BooleanField(default=True)

class Subscription(TenantModel):
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, default='free_launch')
    ends_at = models.DateTimeField(null=True)

class SubscriptionPayment(TenantModel):
    subscription = models.ForeignKey(Subscription, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    provider_reference = models.CharField(max_length=120, unique=True)
    verified_at = models.DateTimeField(null=True)

class FeatureFlag(models.Model):
    key = models.CharField(max_length=80, unique=True)
    enabled = models.BooleanField(default=False)
    description = models.CharField(max_length=250, blank=True)

class RateLimit(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    attempts = models.PositiveIntegerField(default=0)
    reset_at = models.DateTimeField(db_index=True)
