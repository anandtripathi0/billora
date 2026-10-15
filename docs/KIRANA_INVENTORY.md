# Kirana catalog research and delivery report

Research date: 15 October 2026. Catalog: **200 distinct SKUs, 23 categories, 186 priced references, 14 inactive products needing review**. The priced rows comprise 23 DoCA national references and 163 retailer observations. Every newly imported SKU, including inactive drafts, receives exactly 100 opening/current stock units and a threshold of 10.

## What the prices mean

The [Department of Consumer Affairs public price monitoring page](https://fcainfoweb.nic.in/Default.aspx) displayed the 15 October 2026 values supplied in the brief. These are all-India averages, not local shop quotes. Six edible-oil references remain per **kilogram**. They are never converted to litres. The milk row follows the brief's per-litre basis; the public table labels milk with an @ marker.

Public BigBasket brand listings were reviewed through web retrieval on 15 October 2026. Retailer pages may be cached, location was not selected, and availability/checkout prices can differ. The files record the exact displayed pack or multipack and selling price; they are a dated reference catalog, not a live pricing feed. No login, CAPTCHA bypass, checkout, or restricted endpoint was used.

The user-supplied Sunpure 1 L oil (INR 171) and 5 kg atta (INR 303) could not be independently checked because the bbnow source was inaccessible. Both remain unpriced, inactive, and Needs Review. Three Tata Tea variants had no purchasable price displayed. Nine unbranded local-assortment drafts also need the shopkeeper to verify the pack and price. Discount banners were excluded from price observations.

**Costs, GST rates, barcodes and MRPs are not invented.** All are blank in this starter catalog. Where a retailer card displayed a second reference price, it is retained in source notes and the observation file, not asserted to be the pack MRP. Selling prices are separate from this reference figure. Manual price edits change the status to Manual while preserving the original source observation.

Each packaged SKU's stock counts whole displayed packs, including multipacks. For example, 100 units of a 3 x 1 L multipack means 100 multipacks, not 100 litres. Loose commodity rows use kg (milk uses L), enabling fractional quantities. Product names include the exact pack so invoices and receipts distinguish variants.

## Category coverage

| Category | SKUs |
|---|---:|
| Baby-care essentials | 7 |
| Bath soaps and body wash | 16 |
| Biscuits, cookies and rusks | 15 |
| Bread, bakery and spreads | 7 |
| Breakfast cereals and oats | 8 |
| Chips, namkeen and snacks | 7 |
| Chocolates, candies and toffees | 3 |
| Detergent and laundry products | 7 |
| Dry fruits and nuts | 7 |
| Edible oils and ghee | 14 |
| Floor cleaners and dishwashing products | 7 |
| Milk and dairy | 8 |
| Noodles, pasta and instant foods | 5 |
| Pickles, sauces and condiments | 5 |
| Pulses and dals | 7 |
| Rice, wheat, atta and flour | 13 |
| Shampoo and hair oil | 5 |
| Spices and masalas | 9 |
| Stationery and miscellaneous | 11 |
| Sugar, salt and jaggery | 11 |
| Tea, coffee and beverages | 15 |
| Tissue, paper and household essentials | 6 |
| Toothpaste and toothbrushes | 7 |

## Source index

Every row in the JSON and CSV contains its URL, checked date, observed price, price type, verification status, and source notes. The index below counts researched or attempted rows, not guaranteed available products.

| Source | Rows |
|---|---:|
| [sunpure](https://bbnow.bigbasket.com/pb/sunpure/) | 2 |
| [DoCA](https://fcainfoweb.nic.in/Default.aspx) | 23 |
| [aashirvaad](https://www.bigbasket.com/pb/aashirvaad/) | 7 |
| [amul](https://www.bigbasket.com/pb/amul/) | 8 |
| [britannia](https://www.bigbasket.com/pb/britannia/) | 7 |
| [cadbury](https://www.bigbasket.com/pb/cadbury/) | 7 |
| [classmate](https://www.bigbasket.com/pb/classmate/) | 7 |
| [colgate](https://www.bigbasket.com/pb/colgate/) | 7 |
| [dove](https://www.bigbasket.com/pb/dove/) | 6 |
| [everest](https://www.bigbasket.com/pb/everest/) | 7 |
| [fortune](https://www.bigbasket.com/pb/fortune/) | 7 |
| [haldirams](https://www.bigbasket.com/pb/haldirams/) | 7 |
| [kissan](https://www.bigbasket.com/pb/kissan/) | 7 |
| [lifebuoy](https://www.bigbasket.com/pb/lifebuoy/) | 7 |
| [lux](https://www.bigbasket.com/pb/lux/) | 7 |
| [maggi](https://www.bigbasket.com/pb/maggi/) | 7 |
| [nescafe](https://www.bigbasket.com/pb/nescafe/) | 7 |
| [origami](https://www.bigbasket.com/pb/origami/) | 6 |
| [pampers](https://www.bigbasket.com/pb/pampers/) | 6 |
| [parle](https://www.bigbasket.com/pb/parle/) | 8 |
| [quaker](https://www.bigbasket.com/pb/quaker/) | 7 |
| [surf-excel](https://www.bigbasket.com/pb/surf-excel/) | 7 |
| [tata-salt](https://www.bigbasket.com/pb/tata-salt/) | 7 |
| [tata-sampann](https://www.bigbasket.com/pb/tata-sampann/) | 8 |
| [tata-tea](https://www.bigbasket.com/pb/tata-tea/) | 5 |
| [vim](https://www.bigbasket.com/pb/vim/) | 7 |

## Files and import behavior

- `backend/billing/data/kirana_catalog.csv` — UTF-8 CSV; empty money fields mean unknown, not zero.
- `backend/billing/data/kirana_catalog.json` — structured catalog, metadata and product rows.
- `backend/billing/data/retailer_observations.json` — retailer pack/price observations and separate displayed reference prices.
- `scripts/build_kirana_catalog.py` — reproducible offline builder; it never changes a business database.
- `backend/billing/inventory.py` — validation, preview signing, atomic import and detailed reports.
- `backend/billing/management/commands/import_kirana_inventory.py` — CLI with business selection, dry-run and explicit confirmation.
- `frontend/src/components/catalog-import.tsx` — owner preview, source links, search, confirmation and report download.

The portable files have a null/blank Business ID. The importer binds it to the explicitly selected business. Downloads from the Products screen fill in the logged-in business ID. An explicit ID for another tenant is rejected.

Imports validate the complete file before writing, lock the business in the same order as invoices, and create rows in one transaction. Existing SKUs are **skipped in full**: current stock, opening stock, price, activation and metadata are preserved. A repeated confirmation is safe. Preview tokens expire after 15 minutes and bind the user, business and exact catalog content. Files are limited to 1 MB / 500 rows, duplicate SKUs and malformed/nonfinite amounts are rejected, and new starter stock must equal 100. Imports require the owner in the UI; managers retain their existing product-edit permissions. The legacy simple CSV API remains available for existing integrations.

Unknown selling prices remain NULL and inactive; even a caller-supplied invoice price cannot bill an inactive product. The editor requires a positive price before activating imported products. Unknown GST prevents a GST invoice until the shopkeeper verifies a rate. Enter 0 only when verified. Costs remain unknown on saved invoice snapshots and estimated profit displays Unavailable when any sold item lacks cost.

Retail reference prices include tax. GST is extracted from inclusive line amounts, never added twice. The invoice discount is allocated across entered line amounts; included tax is extracted after discount. Exclusive prices retain the original behavior. Frontend integer arithmetic matches backend Decimal arithmetic, including fractional quantities and rounding. Stored names, prices, quantities, tax basis and totals flow to the PDF, thermal page and printer bridge. Finalization locks stock; cancellation restores it once, with explicit full-refund confirmation when money was received.

## Local review

Open http://localhost:3000/products. Choose **Import Starter Grocery Catalog**, inspect sources/prices, check the confirmation box and click **Confirm import**. This action applies to that logged-in business only. To finish unpriced items, enable **Needs review**, edit the price and verified tax rate, then check **Active for invoicing**.

The real user business has not been populated automatically. Schema migration 0007 adds metadata and nullable unknown prices/costs/GST while preserving existing values. Only isolated test accounts receive test imports during browser verification.

## Render / Neon commands

The catalog ships inside the existing backend Docker image at `/app/billing/data/`. There is no import on startup or migration. Run the following in the **backend** Render shell (the Docker WORKDIR is `/app`). Replace `BUSINESS_ID` with the selected store UUID. If needed, list business identities first:

```sh
python manage.py shell -c "from billing.models import Business; print(list(Business.objects.filter(is_active=True).values('id','name')))"
python manage.py migrate --noinput
python manage.py import_kirana_inventory --business-id BUSINESS_ID --dry-run --report /tmp/kirana-preview.json
cat /tmp/kirana-preview.json
```

After the owner reviews that preview, explicitly confirm:

```sh
python manage.py import_kirana_inventory --business-id BUSINESS_ID --confirm --report /tmp/kirana-import-report.json
cat /tmp/kirana-import-report.json
```

For a reviewed custom file, pass the same `--file` in both steps:

```sh
python manage.py import_kirana_inventory --business-id BUSINESS_ID --file /app/billing/data/kirana_catalog.csv --dry-run --report /tmp/kirana-preview.json
python manage.py import_kirana_inventory --business-id BUSINESS_ID --file /app/billing/data/kirana_catalog.csv --confirm --report /tmp/kirana-import-report.json
```

Save reports before the ephemeral Render filesystem is recycled, or use the UI's **Download report**. Where the hosting plan does not provide a shell, use the same authenticated Products import UI. No Render deployment was performed in this session.

## Environment

**No new environment variables are required for inventory imports.** Existing `DATABASE_URL`, `DJANGO_SECRET_KEY`, `DB_SSL_REQUIRE`, `ALLOWED_HOSTS`, `FRONTEND_URL`, `CSRF_TRUSTED_ORIGINS`, and frontend `BACKEND_URL` continue to apply. Local Neon is already configured. Never paste credentials into seed files or reports. No retailer API key, GST API key, storage bucket or printer setting is required for this catalog feature.

## Validation results

- Django: 85 discovered, 79 passed on isolated SQLite; 6 PostgreSQL-specific concurrency tests skipped there.
- Real Neon PostgreSQL: 2 focused concurrency tests passed (parallel import/re-import with sale, and oversell protection); uniquely named disposable test database removed afterward.
- Frontend: 14 Vitest tests passed; production Next.js build and TypeScript passed, 26 pages generated.
- Printer bridge: 7 tests passed with mock hardware.
- Browser: 2 final Playwright workflows passed on desktop Chrome and Pixel 7 emulation (preview without writes, explicit owner confirmation, 200-SKU import, unpriced activation, manual price, GST-inclusive invoice totals and split-tax rounding, PDF, thermal receipt, re-import preservation and cancellation).
- Neon schema migration 0007 applied successfully; no automatic catalog import into the user business.

The initial build was blocked by the previous local production server holding its build directory; after stopping that owned process the build passed. Printer tests required normal temporary SQLite access outside the restricted sandbox and passed there. Physical printing and Render deployment were not performed.
