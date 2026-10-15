import base64
import io
import re
from decimal import Decimal
from PIL import Image, UnidentifiedImageError
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from . import models as m
from .validation import mobile as normalize_mobile, gstin, state, timezone_name

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.User
        fields = ['id', 'first_name', 'email', 'mobile', 'is_superuser']
        read_only_fields = ['id', 'email', 'is_superuser']
    validate_mobile = staticmethod(normalize_mobile)

class RegisterSerializer(serializers.Serializer):
    owner_name = serializers.CharField(max_length=100)
    business_name = serializers.CharField(max_length=160)
    email = serializers.EmailField(max_length=254)
    mobile = serializers.CharField(max_length=20)
    password = serializers.CharField(write_only=True, max_length=128)
    confirm_password = serializers.CharField(write_only=True, max_length=128)
    validate_mobile = staticmethod(normalize_mobile)
    def validate_email(self, value):
        value = value.strip().lower()
        if m.User.objects.filter(email__iexact=value).exists(): raise serializers.ValidationError('An account already uses this email.')
        return value
    def validate(self, data):
        if data.pop('confirm_password') != data['password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})
        validate_password(data['password'], m.User(username=data['email'], email=data['email'], first_name=data['owner_name']))
        return data

class SettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.BusinessSettings
        exclude = ['id', 'business']
    validate_timezone = staticmethod(timezone_name)
    def validate_invoice_prefix(self, value):
        if not re.fullmatch(r'[A-Za-z0-9-]{1,12}', value): raise serializers.ValidationError('Use 1–12 letters, numbers or hyphens.')
        return value.upper()
    def validate_upi_id(self, value):
        if value and not re.fullmatch(r'[A-Za-z0-9._-]{2,100}@[A-Za-z0-9.-]{2,30}', value): raise serializers.ValidationError('Enter a valid UPI ID, such as shop@upi.')
        return value
    def validate_logo_data(self, value):
        if not value: return ''
        if len(value) > 280000: raise serializers.ValidationError('Logo must be smaller than 200 KB.')
        try:
            prefix, encoded = value.split(',', 1)
            if prefix not in ['data:image/png;base64', 'data:image/jpeg;base64']: raise ValueError()
            decoded = base64.b64decode(encoded, validate=True)
            img = Image.open(io.BytesIO(decoded))
            if img.width * img.height > 4_000_000: raise ValueError()
            img.thumbnail((320, 160))
            out = io.BytesIO(); img.convert('RGBA').save(out, format='PNG')
            if len(out.getvalue()) > 150000: raise ValueError()
            return 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode()
        except (ValueError, UnidentifiedImageError, OSError, Image.DecompressionBombError): raise serializers.ValidationError('Upload a small PNG or JPEG logo.')

class BusinessSerializer(serializers.ModelSerializer):
    settings = SettingsSerializer(read_only=True)
    class Meta:
        model = m.Business
        fields = ['id', 'name', 'address', 'gstin', 'state_code', 'mobile', 'is_active', 'created_at', 'settings']
        read_only_fields = ['id', 'is_active', 'created_at', 'settings']
    validate_gstin = staticmethod(gstin)
    validate_mobile = staticmethod(normalize_mobile)
    validate_state_code = staticmethod(state)
    def validate(self, data):
        tax_id = data.get('gstin', getattr(self.instance, 'gstin', ''))
        code = data.get('state_code', getattr(self.instance, 'state_code', '27'))
        if tax_id and not tax_id.startswith(code): raise serializers.ValidationError('GSTIN must match the business state code.')
        return data

class CategorySerializer(serializers.ModelSerializer):
    class Meta: model = m.Category; fields = ['id', 'name']; validators = []

class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True, default='Uncategorized')
    class Meta:
        model = m.Product
        exclude = ['business']
        read_only_fields = ['id', 'created_at', 'opening_stock', 'price_source_url', 'price_checked_date', 'source_price', 'price_type', 'price_verification_status', 'source_notes']
        validators = []
    def validate_category(self, value):
        if value and value.business_id != self.context['business'].pk: raise serializers.ValidationError('Invalid category.')
        return value
    def validate(self, data):
        business = self.context['business']
        sku = data.get('sku', getattr(self.instance, 'sku', ''))
        qs = m.Product.objects.filter(business=business, sku=sku)
        if self.instance: qs = qs.exclude(pk=self.instance.pk)
        if qs.exists(): raise serializers.ValidationError({'sku': 'This SKU already exists.'})
        if data.get('stock', Decimal(0)) < 0 and not business.settings.allow_negative_stock:
            raise serializers.ValidationError({'stock': 'Negative stock is disabled.'})
        price = data.get('selling_price', getattr(self.instance, 'selling_price', None))
        active = data.get('is_active', getattr(self.instance, 'is_active', True))
        if active and price is None:
            raise serializers.ValidationError({'selling_price': 'Enter a selling price before activating this product.'})
        if active and self.instance and self.instance.opening_stock is not None and price <= 0:
            raise serializers.ValidationError({'selling_price': 'Starter catalog products need a positive selling price before activation.'})
        if price is None:
            data['price_verification_status'] = 'needs_review'
        elif 'selling_price' in data and (not self.instance or price != self.instance.selling_price):
            data.update(price_type='manual', price_verification_status='manual')
        return data

class CustomerSerializer(serializers.ModelSerializer):
    mobile = serializers.CharField(max_length=32)
    whatsapp = serializers.CharField(max_length=32, required=False, allow_blank=True)
    outstanding = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True, default=Decimal(0))
    purchases = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True, default=Decimal(0))
    payments_received = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True, default=Decimal(0))
    refunds = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True, default=Decimal(0))
    order_count = serializers.IntegerField(read_only=True, default=0)
    last_purchase = serializers.DateField(read_only=True, allow_null=True, default=None)
    class Meta: model = m.Customer; exclude = ['business', 'merged_into']; read_only_fields = ['id', 'created_at']; validators = []
    validate_mobile = staticmethod(normalize_mobile)
    validate_gstin = staticmethod(gstin)
    def validate_whatsapp(self, value): return normalize_mobile(value) if value else ''
    def validate_state_code(self, value): return state(value) if value else ''
    def validate(self, data):
        tax_id = data.get('gstin', getattr(self.instance, 'gstin', ''))
        code = data.get('state_code', getattr(self.instance, 'state_code', ''))
        if tax_id and code and not tax_id.startswith(code): raise serializers.ValidationError('GSTIN must match the customer state code.')
        return data

class InvoiceLineInput(serializers.Serializer):
    product = serializers.IntegerField(min_value=1)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal('0.001'))
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal(0), required=False)

class InvoiceInput(serializers.Serializer):
    expected_total = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal(0), required=False)
    payment_status = serializers.ChoiceField(choices=['paid','partial','unpaid'], required=False)
    quote_token = serializers.CharField(max_length=4096, required=False)
    customer = serializers.IntegerField(min_value=1)
    items = InvoiceLineInput(many=True, allow_empty=False, max_length=100)
    idempotency_key = serializers.UUIDField()
    date = serializers.DateField(required=False)
    due_date = serializers.DateField(required=False, allow_null=True)
    supply_state = serializers.CharField(max_length=2, required=False, allow_blank=True)
    gst_enabled = serializers.BooleanField(default=False)
    discount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal(0), default=Decimal(0))
    paid_amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal(0), default=Decimal(0))
    payment_method = serializers.ChoiceField(choices=['cash', 'upi', 'bank', 'card', 'credit'], default='cash')
    include_upi_qr = serializers.BooleanField(default=False)
    notes = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    def validate_supply_state(self, value): return state(value) if value else ''
    def validate(self, data):
        if data.get('date') and data.get('due_date') and data['due_date'] < data['date']:
            raise serializers.ValidationError('Due date cannot precede invoice date.')
        return data

class InvoiceItemSerializer(serializers.ModelSerializer):
    class Meta: model = m.InvoiceItem; exclude = ['invoice', 'purchase_price']

class PaymentSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source='invoice.number', read_only=True)
    refunded = serializers.SerializerMethodField()
    def get_refunded(self, obj): return obj.invoice.cancelled_at is not None
    class Meta: model = m.Payment; exclude = ['business', 'recorded_by']; read_only_fields = ['id', 'created_at']

class InvoiceSerializer(serializers.ModelSerializer):
    business_snapshot = serializers.SerializerMethodField()
    items = InvoiceItemSerializer(source='ordered_items', many=True, read_only=True)
    balance = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    status = serializers.CharField(read_only=True)
    def get_business_snapshot(self, obj): return {**obj.business_snapshot, 'logo_data': obj.logo_data}
    class Meta: model = m.Invoice; exclude = ['business', 'request_hash', 'idempotency_key']

class InvoiceListSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer_snapshot.name', read_only=True)
    balance = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    status = serializers.CharField(read_only=True)
    class Meta: model = m.Invoice; fields = ['id', 'number', 'customer_name', 'date', 'total', 'paid_amount', 'balance', 'status']

class PaymentInput(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    method = serializers.ChoiceField(choices=['cash', 'upi', 'bank', 'card'])
    reference = serializers.CharField(max_length=120, required=False, allow_blank=True)
    idempotency_key = serializers.UUIDField()

class PlanSerializer(serializers.ModelSerializer):
    class Meta: model = m.SubscriptionPlan; fields = '__all__'

class FeatureFlagSerializer(serializers.ModelSerializer):
    class Meta: model = m.FeatureFlag; fields = '__all__'
    def validate(self, data):
        key = data.get('key', getattr(self.instance, 'key', ''))
        if key.upper() in ['BILLING_ENABLED', 'AUTOMATIC_WHATSAPP_ENABLED'] and data.get('enabled'):
            raise serializers.ValidationError('Payments and automatic messaging require a separately reviewed integration; they cannot be activated here.')
        return data
