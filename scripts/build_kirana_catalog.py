"""Build distributable catalog files from the reviewed public observations. No network."""
import csv
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'backend/billing/data'
DATE = '2026-10-15'
CATEGORIES = ['Rice, wheat, atta and flour', 'Pulses and dals', 'Edible oils and ghee',
    'Sugar, salt and jaggery', 'Spices and masalas', 'Tea, coffee and beverages',
    'Biscuits, cookies and rusks', 'Chips, namkeen and snacks', 'Noodles, pasta and instant foods',
    'Breakfast cereals and oats', 'Milk and dairy', 'Bread, bakery and spreads',
    'Pickles, sauces and condiments', 'Dry fruits and nuts', 'Chocolates, candies and toffees',
    'Bath soaps and body wash', 'Shampoo and hair oil', 'Toothpaste and toothbrushes',
    'Detergent and laundry products', 'Floor cleaners and dishwashing products',
    'Tissue, paper and household essentials', 'Baby-care essentials', 'Stationery and miscellaneous']
rows = []
def add(name, brand, category, pack, price=None, source='', status='needs_review', kind='manual', unit='pack', notes=''):
    identity = f'{brand}|{name}|{pack}'
    sku = 'KIR-' + re.sub('[^A-Z0-9]+', '-', brand.upper()).strip('-')[:18] + '-' + hashlib.sha256(identity.encode()).hexdigest()[:12].upper()
    rows.append(dict(business_id=None, sku=sku, name=f'{name} {pack}', brand=brand,
        category=CATEGORIES[category-1], pack_size=pack, unit=unit,
        selling_price=price, cost_price=None, mrp=None, opening_stock='100.000', current_stock='100.000',
        low_stock_threshold='10.000', barcode=None, gst_rate=None, price_source_url=source,
        price_checked_date=DATE if source else None, source_price=price, price_type=kind,
        price_verification_status=status, is_active=price is not None, price_includes_tax=True, source_notes=notes))

references = [
    ('Rice',1,'47.48'), ('Wheat',1,'32.06'), ('Atta',1,'37.75'), ('Chana Dal',2,'91.70'),
    ('Arhar Dal',2,'130.54'), ('Urad Dal',2,'124.22'), ('Moong Dal',2,'113.62'), ('Masoor Dal',2,'90.58'),
    ('Broken Rice',1,'34.18'), ('Groundnut Oil',3,'210.83'), ('Mustard Oil',3,'204.92'),
    ('Vanaspati',3,'169.06'), ('Soybean Oil',3,'167.90'), ('Sunflower Oil',3,'191.04'), ('Palm Oil',3,'153.49'),
    ('Potato',23,'22.75'), ('Onion',23,'52.68'), ('Tomato',23,'41.13'), ('Sugar',4,'57.42'),
    ('Jaggery',4,'66.33'), ('Loose Tea',6,'275.33'), ('Packed Iodised Salt',4,'22.25'), ('Milk',11,'61.40')]
for name, category, price in references:
    add(name, 'Unbranded', category, '1 L' if name=='Milk' else '1 kg', price,
        'https://fcainfoweb.nic.in/Default.aspx', 'national_reference', 'national_average',
        'L' if name=='Milk' else 'kg', 'DoCA all-India average for 15 October 2026, observed on the public page. Reference only; not a local shop quote. Oil references stay per kg; milk follows the supplied per-litre basis.')

observations = json.loads((DATA/'retailer_observations.json').read_text(encoding='utf-8'))
for row in observations:
    # Discount banners belong to the following card, not to an unavailable product.
    if row['brand']=='Tata Tea' and row['pack_size'].startswith('32.5'): row['price']=None
    if row['name']=='Lux Shower Gel Freesia Scent & Aloe Vera Bodywash': row['displayed_reference_price']=None
    if row['brand']=="Haldiram's": row['category_number']=8
    if row['brand']=='Parle': row['category_number']=15 if 'Candy' in row['name'] else 7
    if row['brand']=='Cadbury' and 'Cookies' in row['name']: row['category_number']=7
    price = row['price']
    notes = 'Public retailer listing observed 15 October 2026; location not selected. Pack/multipack sold as one inventory unit. Availability and local checkout price may differ.'
    if row['displayed_reference_price']:
        notes += f" Other displayed reference price: INR {row['displayed_reference_price']}; not independently confirmed as pack MRP."
    if price is None: notes += ' No purchasable price displayed; needs shopkeeper review.'
    add(row['name'], row['brand'], row['category_number'], row['pack_size'], price, row['source'],
        'retailer_observed' if price else 'needs_review', 'retailer_listing', notes=notes)
(DATA/'retailer_observations.json').write_text(json.dumps(observations, indent=2)+'\n', encoding='utf-8')

for name, cat, pack, supplied in [('Sunpure Sunflower Oil',3,'1 L','171'), ('Sunpure Atta',1,'5 kg','303')]:
    add(name,'Sunpure',cat,pack,source='https://bbnow.bigbasket.com/pb/sunpure/',kind='retailer_listing',
        notes=f'User supplied INR {supplied}. Source was inaccessible during research; no verified selling price imported.')
for name,cat,pack,unit in [('Raisins',14,'250 g','pack'), ('Dates',14,'500 g','pack'),
        ('Walnuts',14,'250 g','pack'), ('Peanuts',14,'500 g','pack'), ('White Bread',12,'400 g','pack'),
        ('Mango Pickle',13,'500 g','pack'), ('Coconut Hair Oil',17,'200 ml','bottle'),
        ('Baby Wipes',22,'80 wipes','pack'), ('Matchboxes',23,'10 boxes','pack')]:
    add(name,'Unbranded',cat,pack,unit=unit,notes='Suggested local assortment and pack size. Verify the actual pack and enter your shop price before activation; no retailer price researched.')
assert len(rows)==200 and len({r['sku'] for r in rows})==200
assert len({r['category'] for r in rows})==23
document = {'version':1, 'researched_on':DATE, 'currency':'INR',
    'notice':'Review prices and stock before confirming. National averages and retailer observations are reference prices, not guaranteed local prices. GST, cost and MRP are unknown. No automatic tenant import.', 'products':rows}
(DATA/'kirana_catalog.json').write_text(json.dumps(document,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
with (DATA/'kirana_catalog.csv').open('w',encoding='utf-8-sig',newline='') as out:
    writer=csv.DictWriter(out,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
print(f"Built {len(rows)} SKUs / 23 categories; {sum(r['selling_price'] is not None for r in rows)} priced; {sum(r['selling_price'] is None for r in rows)} need review.")
