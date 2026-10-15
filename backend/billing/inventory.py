"""Validated, tenant-scoped starter imports. Existing SKUs are always preserved."""
import csv
import hashlib
import io
import json
from pathlib import Path
from decimal import Decimal
from django.core import signing
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from .models import Business, Category, Product
from .services import audit

CATALOG_PATH = Path(__file__).parent / 'data/kirana_catalog.json'
MAX_BYTES = 1024 * 1024

class CatalogRow(serializers.Serializer):
    business_id = serializers.UUIDField(required=False, allow_null=True)
    sku = serializers.RegexField(r'^[A-Za-z0-9_.-]+$', max_length=64)
    name = serializers.CharField(max_length=180)
    brand = serializers.CharField(max_length=80, allow_blank=True)
    category = serializers.CharField(max_length=80)
    pack_size = serializers.CharField(max_length=100)
    unit = serializers.CharField(max_length=16)
    selling_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'), allow_null=True)
    cost_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, allow_null=True, default=None)
    mrp = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, allow_null=True, default=None)
    opening_stock = serializers.DecimalField(max_digits=12, decimal_places=3)
    current_stock = serializers.DecimalField(max_digits=12, decimal_places=3)
    low_stock_threshold = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=0)
    barcode = serializers.CharField(max_length=80, allow_blank=True, allow_null=True, default=None)
    gst_rate = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100, allow_null=True, default=None)
    price_source_url = serializers.URLField(max_length=600, allow_blank=True)
    price_checked_date = serializers.DateField(allow_null=True)
    source_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, allow_null=True, default=None)
    price_type = serializers.ChoiceField(choices=['national_average','retailer_listing','manual'])
    price_verification_status = serializers.ChoiceField(choices=['national_reference','retailer_observed','manual','needs_review'])
    is_active = serializers.BooleanField()
    price_includes_tax = serializers.BooleanField()
    source_notes = serializers.CharField(max_length=2000, allow_blank=True, default='')

    def validate(self, row):
        if row['opening_stock'] != 100 or row['current_stock'] != 100:
            raise serializers.ValidationError('Every new starter SKU must have opening and current stock exactly 100.')
        if row['low_stock_threshold'] != 10:
            raise serializers.ValidationError('Starter low-stock threshold must be 10.')
        if row['price_checked_date'] and row['price_checked_date'] > timezone.localdate():
            raise serializers.ValidationError('Price checked date cannot be in the future.')
        if row['selling_price'] is None:
            if row['is_active'] or row['price_verification_status'] != 'needs_review':
                raise serializers.ValidationError('An unpriced product must be inactive and marked needs_review.')
        else:
            expected = {'manual':'manual', 'national_average':'national_reference', 'retailer_listing':'retailer_observed'}
            if row['price_verification_status'] != expected[row['price_type']]:
                raise serializers.ValidationError('Price type and verification status must agree; unverified prices must stay blank.')
            if row['price_type'] != 'manual':
                if not row['price_source_url'] or not row['price_checked_date'] or row['source_price'] != row['selling_price']:
                    raise serializers.ValidationError('A reference price requires its source URL, checked date and matching observed source price.')
            if row['mrp'] is not None and row['price_includes_tax'] and row['selling_price'] > row['mrp']:
                raise serializers.ValidationError('Selling price exceeds MRP.')
        return row

def read_catalog(content=None, filename='kirana_catalog.json'):
    content = CATALOG_PATH.read_bytes() if content is None else content
    if len(content) > MAX_BYTES: raise ValidationError('Catalog files must be no larger than 1 MB.')
    try:
        text = content.decode('utf-8-sig')
        if filename.lower().endswith('.csv'):
            reader = csv.DictReader(io.StringIO(text))
            if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise ValueError('Duplicate or missing CSV headers.')
            rows = list(reader)
            nullable = ['business_id','selling_price','cost_price','mrp','barcode','gst_rate','price_checked_date','source_price']
            for row in rows:
                if None in row or None in row.values(): raise ValueError('CSV column count does not match the header.')
                for key in nullable:
                    if row.get(key) == '': row[key] = None
        elif filename.lower().endswith('.json'):
            document = json.loads(text)
            rows = document.get('products') if isinstance(document, dict) else document
        else: raise ValueError('Choose a CSV or JSON file.')
    except (ValueError, UnicodeDecodeError, csv.Error, RecursionError) as exc:
        raise ValidationError(f'Invalid catalog: {exc}')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 500:
        raise ValidationError('Import between 1 and 500 product rows.')
    return rows

def validate_catalog(rows, business):
    result, errors, seen, identities = [], [], set(), set()
    if not isinstance(rows, list) or not 1 <= len(rows) <= 500: raise ValidationError('Import between 1 and 500 product rows.')
    allowed = set(CatalogRow().fields)
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict) or set(row) - allowed:
            errors.append({'row':index, 'errors':'Unknown columns or invalid row.'}); continue
        serializer = CatalogRow(data=row)
        if not serializer.is_valid():
            errors.append({'row':index, 'errors':serializer.errors}); continue
        data = serializer.validated_data
        if data.get('business_id') and data['business_id'] != business.pk:
            errors.append({'row':index, 'errors':'Business ID does not match the selected business.'})
        identity = tuple(data[k].casefold() for k in ['brand','name','pack_size'])
        if data['sku'] in seen or identity in identities:
            errors.append({'row':index, 'errors':'Duplicate SKU or brand/product/pack in this file.'})
        seen.add(data['sku']); identities.add(identity)
        data['business_id'] = business.pk
        result.append(data)
    if errors: raise ValidationError({'rows':errors})
    return result

def json_safe(value): return json.loads(json.dumps(value, default=str))

def fingerprint(rows):
    return hashlib.sha256(json.dumps(json_safe(rows), sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def import_report(business, rows, dry_run=True):
    existing = {p.sku:p for p in Product.objects.filter(business=business, sku__in=[r['sku'] for r in rows])}
    entries = []
    for row in rows:
        old = existing.get(row['sku'])
        entries.append({**json_safe(row), 'action':'skipped_existing' if old else 'would_create' if dry_run else 'created',
            'existing_stock':str(old.stock) if old else None, 'existing_selling_price':str(old.selling_price) if old and old.selling_price is not None else None})
    new_rows = [r for r in rows if r['sku'] not in existing]
    return {'business_id':str(business.pk), 'business_name':business.name, 'dry_run':dry_run,
        'generated_at':timezone.now().isoformat(), 'catalog_digest':fingerprint(rows),
        'total':len(rows), 'create_count':len(new_rows), 'skipped_count':len(existing),
        'priced_count':sum(r['selling_price'] is not None for r in new_rows),
        'needs_review_count':sum(r['selling_price'] is None for r in new_rows),
        'category_count':len({r['category'] for r in rows}), 'opening_stock_per_new_sku':'100.000',
        'rows':entries}

def preview_catalog(user, business, raw_rows):
    rows = validate_catalog(raw_rows, business)
    report = import_report(business, rows)
    report['confirmation_token'] = signing.dumps({'business':str(business.pk), 'user':user.pk, 'digest':fingerprint(rows)}, salt='kirana-import')
    return report

def confirm_catalog(user, business, raw_rows, token, confirmed):
    if confirmed is not True: raise ValidationError('Confirm the catalog preview before importing.')
    rows = validate_catalog(raw_rows, business)
    try: value = signing.loads(token, salt='kirana-import', max_age=900)
    except (signing.BadSignature, TypeError): raise ValidationError('Preview expired or invalid. Review the catalog again.')
    if value != {'business':str(business.pk), 'user':user.pk, 'digest':fingerprint(rows)}:
        raise ValidationError('Catalog or selected business changed. Review a new preview.')
    return import_catalog(business, rows, user=user)

@transaction.atomic
def import_catalog(business, raw_rows, *, user=None, dry_run=False):
    business = Business.objects.select_for_update().get(pk=business.pk)
    if not business.is_active: raise ValidationError('The selected business is suspended.')
    rows = validate_catalog(raw_rows, business)
    report = import_report(business, rows, dry_run=dry_run)
    if dry_run: return report
    new_skus = {r['sku'] for r in report['rows'] if r['action']=='created'}
    new_rows = [r for r in rows if r['sku'] in new_skus]
    categories = {c.name:c for c in Category.objects.filter(business=business)}
    Category.objects.bulk_create([Category(business=business, name=name) for name in sorted({r['category'] for r in new_rows} - categories.keys())])
    categories = {c.name:c for c in Category.objects.filter(business=business)}
    products = []
    for row in new_rows:
        fields = dict(row)
        fields.pop('business_id')
        fields['category'] = categories[fields['category']]
        fields['purchase_price'] = fields.pop('cost_price')
        fields['stock'] = fields.pop('current_stock')
        fields['barcode'] = fields['barcode'] or ''
        products.append(Product(business=business, **fields))
    Product.objects.bulk_create(products)
    audit(user, business, 'inventory.catalog_imported', f"{len(products)} created; {report['skipped_count']} preserved")
    return report
