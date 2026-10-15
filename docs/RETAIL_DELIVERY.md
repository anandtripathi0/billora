# Retail update — 15 October 2026

## Delivered behavior

- Mobile-first customer lookup and quick creation, normalized per business, with database uniqueness and transaction locking.
- Editable invoice line prices, integer-based instant totals, paid/partial/unpaid selection, optional default UPI QR, direct Save and Save & Print.
- Immutable checkout summary records previous purchases and the new total. Collection totals are separately aggregated from finalized invoices, payments and refunds.
- Customer Collection page and chronological customer history. Full cancellation restores stock once, preserves payments and records a manually confirmed refund when required.
- Dedicated 58/80 mm browser receipt page, PDF download and reprint without another invoice.
- Paired local Windows RAW / LAN ESC/POS agent, HTTPS pull queue, revocation, expiring jobs, durable local deduplication and honest spool/uncertain status.
- PostgreSQL client connection reuse to avoid repeating TLS setup for each billing request.

## Files changed

Backend:

- `backend/billing/models.py`, `services.py`, `serializers.py`, `views.py`, `pdf.py`
- `backend/billing/collections.py`, `printing.py`
- `backend/billing/migrations/0006_printdevice_printjob_refund_and_more.py`
- `backend/billing/tests/test_retail.py`, `test_concurrency.py`
- `backend/config/urls.py`, `settings.py`, `postgres_test_settings.py`
- `backend/requirements.txt`, `requirements.lock`

Frontend:

- `frontend/src/components/invoices.tsx`, `records.tsx`, `reports.tsx`, `settings.tsx`, `shell.tsx`
- `frontend/src/components/collection.tsx`, `thermal.tsx`
- `frontend/src/app/(business)/collection/page.tsx`, `frontend/src/app/print/[id]/page.tsx`
- `frontend/src/app/api/[...path]/route.ts`, `frontend/src/app/globals.css`
- `frontend/src/lib/billing-totals.ts`, `frontend/tests/billing-totals.test.ts`
- `frontend/e2e/invoice.spec.ts`, `retail.spec.ts`

Local bridge/docs:

- `printer_bridge/agent.py`, `receipt.py`, `test_agent.py`, `requirements.txt`, `__init__.py`
- `.gitignore`, `README.md`, `docs/THERMAL_PRINTING.md`, this report.

## Verification

- Django: 70 discovered; 65 passed with SQLite and 5 PostgreSQL-only concurrency tests skipped there.
- The same 5 concurrency tests passed against an isolated disposable Neon database; it was removed afterward.
- Frontend unit tests: 12 passed.
- Bridge tests: 7 passed, including both widths, raster QR output, duplicate jobs, restart uncertainty, disconnect handling, mock transport, HTTPS validation and local Host/Origin restrictions.
- Final production Next build/TypeScript passed with 26 prerendered pages and dynamic receipt/API routes.
- Migration 0006 applied to the configured Neon business database. No migration drift. `pip check` passed.
- Connection reuse measurement on this computer: fresh connection ~33 seconds, reused query 0.56 seconds; subsequent app health checks HTTP 200 in ~2–3 seconds. These are observations, not a production latency guarantee.
- Browser workflows: 4 passed across desktop Chrome and Pixel 7 viewport runs (existing full billing workflow plus new retail/thermal workflow on each). Synthetic accounts used the real Neon connection.
- Thermal browser exports: both 58 mm and 80 mm PDFs contain one page, with measured widths 57.83 mm and 80.09 mm (Chromium rounding). Print controls are hidden, long product names wrap without clipping, UPI QR is visible, and the browser print action is invoked.
- A real HTTP pairing/claim/ack exchange with local mock raster output passed; a repeated print request retained one job and did not create an invoice. Physical printing remains unverified.

## Run locally

From the repository root in terminal 1:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.lock
.\.venv\Scripts\python.exe backend/manage.py migrate --noinput
.\.venv\Scripts\python.exe backend/manage.py runserver 127.0.0.1:8000
```

In terminal 2:

```powershell
cd frontend
npm.cmd run build
npm.cmd run start
```

Open http://localhost:3000. Use your own business login. Synthetic automated test accounts are isolated test businesses.

## Deployment, pairing and limitations

See [THERMAL_PRINTING.md](THERMAL_PRINTING.md) for Render steps, required deployment ENV, bridge installation/pairing, width/dot configuration, printer tests and recovery.

No new required ENV variables were introduced. The existing Neon connection remains in the ignored root `.env`. UPI ID/payee/default and paper width belong in Business settings. Printer pairing stores a revocable token only in the shop PC's private configuration. Optional `DB_POOL_ENABLED=false` disables the client connection pool for troubleshooting.

Physical hardware remains unverified. Mock spool acceptance is not proof of paper output. Partial returns/credit notes are outside this full-cancellation workflow. Actual Render deployment, SMTP delivery and real UPI/WhatsApp transfers were not performed in this update.
