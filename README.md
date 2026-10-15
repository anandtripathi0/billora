# Billora

Retail billing now includes mobile lookup, customer collections, full cancellation/refund records, 58/80 mm receipts and an optional paired local ESC/POS agent. See [thermal printing and deployment setup](docs/THERMAL_PRINTING.md).

A Next.js + Django billing workspace for Indian businesses, with a premium cream interface with bundled Geist typography, real session authentication, tenant-isolated records, inventory, invoices, payments, and reports.

## What is implemented

- Registration, login/logout, CSRF-protected server sessions, Argon2 passwords, database-backed login throttling, email password resets, profile/password updates, onboarding, and staff roles.
- Business dashboard with a database-backed greeting, sales totals, revenue chart, recent invoices, low-stock alerts, and best sellers.
- Products, categories, search, archive, atomic CSV import, decimal prices, stock levels, and customer ledgers.
- Server-calculated invoice previews; transactional numbering, stock deduction and idempotency; GST/non-GST invoices; CGST/SGST or IGST; permanent price, cost, customer and business snapshots.
- Invoice details, print, in-memory ReportLab PDF generation, revocable seven-day links, user-confirmed WhatsApp sharing, and exact-balance UPI QR codes.
- Partial/full manual payment recording with idempotency and regenerated PDF/QR revisions.
- Daily/monthly/product/customer/outstanding/stock reports, date filtering, CSV and PDF exports, and clearly labeled estimated profit.
- Free-launch pricing (₹49 monthly, ₹89 monthly, ₹399 yearly); plan/subscription models; separate super-admin pages; business suspension, plans, flags, audit trail, and Django Admin.
- Consistent light cream theme, mobile layout, keyboard-accessible native dialogs, reduced-motion support, lazy charts, query caching and pagination.
- Docker Compose, Render Blueprint, PostgreSQL migrations, CI, automated tests, and a 50-user load-test harness.

**No payment collection or automatic WhatsApp delivery is enabled.** The green sharing action prepares a message for the user to send. It never reports delivered. Core features are free during launch, regardless of subscription records.

## Quick start with Docker

1. Install Docker Desktop and enable its Linux container engine.
2. Copy `.env.example` to `.env`. The defaults are for local use. The Compose profile uses its own local PostgreSQL; native development uses DATABASE_URL (including Neon).
3. Run:

```sh
docker compose up --build
```

4. Open [Billora](http://localhost:3000), register, and complete Business settings.
5. Create the platform administrator:

```sh
docker compose exec backend python manage.py createsuperuser
```

Sign in with that account's **email** at `/login`; it opens `/super-admin`. Django Admin is at the backend's `/admin/` URL. Never use sample credentials in production.

Optional development seed (only allowed with `DEBUG=true`):

```sh
docker compose exec backend python manage.py seed_demo --email owner@billora.local --password 'Choose-A-Local-Only-Password'
```

The example UPI ID in the seed is a development placeholder; replace it with your real verified business UPI ID before using any invoice for payment.

## Native development

Use Python 3.12+, Node 22+, and PostgreSQL 14+ or Neon. PDFs work directly on Windows and Linux; native PDF libraries and cloud file storage are not required.

```sh
python -m venv .venv
# Activate .venv using your shell, then:
pip install -r backend/requirements.txt -c backend/requirements.lock
cp .env.example .env
cd backend
python manage.py migrate
python manage.py runserver
```

In a second terminal:

```sh
cd frontend
cp .env.example .env.local
npm ci
npm run dev
```

On PowerShell use `Copy-Item` in place of `cp` if needed, and `.\.venv\Scripts\Activate.ps1` to activate the virtual environment. Use your local PostgreSQL or a Neon development branch in `DATABASE_URL`.

## Tests

```sh
# Full suite against disposable PostgreSQL; the database role needs CREATEDB.
cd backend
pip install -r requirements-dev.txt
python manage.py test billing.tests

# Isolated unit/API fallback, without PostgreSQL. Never use this setting to host the app.
python manage.py test billing.tests --settings=config.test_settings

cd ../frontend
npm test
npm run build

# With the frontend and backend running against a disposable database:
npx playwright install chromium
npm run test:e2e
```

SQLite is confined to explicitly named test settings. Normal development and production settings require PostgreSQL. The three concurrency tests deliberately skip on SQLite. CI runs them against PostgreSQL and exercises desktop/mobile registration → catalog → invoice → payment → stock checks.

See [verification notes](docs/VERIFICATION.md) for the checks actually executed in this workspace and [load testing](docs/TESTING.md) for capacity testing. A load-test harness is not evidence of production capacity.

## Deploy and configure

Read [deployment instructions](docs/DEPLOYMENT.md). The short version:

1. Create a Neon project and copy its **pooled** PostgreSQL connection URL with `sslmode=require`.
2. Optionally connect an SMTP provider for real password-reset emails.
3. Push this repository to your GitHub account and create a Render Blueprint using `render.yaml`.
4. Set the service-specific environment variables below, deploy, create a superuser, and complete the smoke checks.

Do not run SQLite test settings, development sample seeds, or `DEBUG=true` on a public deployment. Free-tier hosting can sleep and has resource limits; capacity and uptime are not guaranteed.

## Environment variables to add

**Django backend / `billora-api`:**

| Variable | Production value |
| --- | --- |
| `DJANGO_SECRET_KEY` | Long random secret; Render Blueprint generates one. Keep stable across deploys. |
| `DATABASE_URL` | Neon pooled PostgreSQL connection string ending in `?sslmode=require`. |
| `DEBUG` | `false` |
| `DB_SSL_REQUIRE` | `true` |
| `ALLOWED_HOSTS` | Backend hostname, no scheme; e.g. `billora-api-xxxx.onrender.com`. Comma-separated for additional hosts. |
| `FRONTEND_URL` | Full frontend origin, e.g. `https://billora-web-xxxx.onrender.com`. |
| `CSRF_TRUSTED_ORIGINS` | Same frontend origin; comma-separated if using a custom domain too. No trailing slash. |
| `SECURE_SSL_REDIRECT` | `true` |
| `BILLING_ENABLED` | `false` |
| `EMAIL_HOST` | SMTP server hostname. |
| `EMAIL_PORT` | Provider's STARTTLS port. Render free blocks `587`; use a supported alternative such as `2525` or a suitable paid host. |
| `EMAIL_HOST_USER` | SMTP username. |
| `EMAIL_HOST_PASSWORD` | SMTP credential/app password. |
| `EMAIL_USE_TLS` | `true` for STARTTLS. |
| `DEFAULT_FROM_EMAIL` | Verified sender, e.g. `Billora <billing@yourdomain.com>`. |

**Next.js frontend / `billora-web`:**

| Variable | Production value |
| --- | --- |
| `BACKEND_URL` | Full backend origin, e.g. `https://billora-api-xxxx.onrender.com`. No `/api` suffix. |
| `NEXT_TELEMETRY_DISABLED` | `1` |

`PORT` is supplied by Render. Optional backend tuning: `WEB_CONCURRENCY` (default 2), `LOG_LEVEL` (default INFO), and `EMAIL_BACKEND`. Redis, Celery, WhatsApp API credentials and payment-gateway credentials are **not required** for the current app. Business UPI IDs belong in Business settings, not environment variables. No `NEXT_PUBLIC_*` secrets are needed.

## This workspace's local connection

The private root `.env` contains the supplied Neon connection; `frontend/.env.local` points to `http://127.0.0.1:8000`. Both files are ignored by Git and Docker. Never put DATABASE_URL in a NEXT_PUBLIC variable. New normal local accounts/products/invoices persist in Neon; the older `.e2e.sqlite3` fixture is not used by the running application.

PowerShell, from the project folder (dependencies are already installed in this workspace):

```powershell
# Terminal 1
$env:DJANGO_SETTINGS_MODULE = 'config.settings'
.\.venv\Scripts\python.exe backend\manage.py migrate --noinput
.\.venv\Scripts\python.exe backend\manage.py runserver 127.0.0.1:8000
```

```powershell
# Terminal 2
cd frontend
npm.cmd run dev
# Or: npm.cmd run build, then npm.cmd run start
```

Open http://localhost:3000 and create your own account. The production start command now launches Next's standalone server with its static assets copied into place. No seeded production login is required.

Local console email prints password-reset links to the backend terminal. Real email needs SMTP configuration. A localhost invoice link only works on this computer; use the deployed HTTPS FRONTEND_URL for customer-accessible links. WhatsApp sharing is free and manual: the shopkeeper presses Send. UPI settings belong in the business form, not .env.

### Starter kirana inventory

See [catalog research, import commands, test results and environment notes](docs/KIRANA_INVENTORY.md). Open Products and choose **Import Starter Grocery Catalog** to review 200 SKUs and explicitly confirm 100 opening units per new SKU. Existing SKUs are preserved.
