# Verification and load testing

Backend tests cover authentication/CSRF/throttling, registration, password reset, tenant and role isolation, server-side calculations, largest-remainder discounts, stock rollback, unique numbering, duplicate submissions, snapshots, exact-balance UPI QR, WhatsApp link encoding, payment validation/idempotency, token expiry/revocation, CSV rollback/formula escaping, reports and free pricing.

Three `TransactionTestCase` scenarios require real PostgreSQL: parallel distinct invoice numbers/stock updates, parallel retries with one idempotency key, and simultaneous overselling. They skip with an explicit reason under SQLite test settings. CI supplies PostgreSQL 17.

The Playwright test runs the actual UI and APIs on desktop and mobile. It creates unique test accounts, a product and customer, previews/saves an invoice, records a payment, checks the resulting stock and confirms the personalized greeting. Use a disposable database. It does not use mocked API responses.

## Load harness

The supplied Locust scenario targets 50 users across 50 seeded tenants, product search, invoice creation/database writes, and PDF generation. Run only against disposable infrastructure, with production-like PostgreSQL and ReportLab. Use one Locust process because the seed assigns exactly 50 distinct logins.

```sh
pip install -r backend/requirements-dev.txt
# Set DEBUG=true, ALLOW_LOAD_TEST_SEED=true and a temporary LOAD_TEST_PASSWORD in your shell.
cd backend
python manage.py migrate
python manage.py seed_loadtest
locust -f loadtests/locustfile.py --headless --users 50 --spawn-rate 5 --run-time 5m --host http://localhost:8000 --csv load-results
```

Record p50/p95/p99 latency, throughput, error rate, DB connection/storage/compute use, and PDF memory/CPU. Compare invoice counts against expected successful writes; verify no duplicate numbers and negative stock. Repeat tests for a single busy tenant and for cold-start behavior before sizing deployment. The PDF task exercises new invoices and regenerated payment revisions. Do not treat a passing local test as a guaranteed Neon/Render capacity figure.

## Windows verification fallback

When PostgreSQL/Docker is not installed, use `config.test_settings` for in-memory unit tests. For browser tests only, `BILLORA_E2E_ONLY=true` plus `DJANGO_SETTINGS_MODULE=config.e2e_settings` enables a disposable local `.e2e.sqlite3` file. This is never a deployment configuration. It cannot validate PostgreSQL locking or production persistence. Bind this server to `127.0.0.1` and stop it after testing.

PDF generation uses ReportLab and runs in ordinary Python on Windows and Linux. The PDF tests parse real output with pypdf, verify saved snapshots, totals, QR image embedding, paid revisions, multi-page headers and public downloads without storage. Install `requirements-dev.txt` for the reader used in tests.

The expanded desktop/mobile browser workflow also checks homepage, invalid login, password confirmation, real registration, refresh/session cookies, cream colors, product edit/archive, customer edit/ledger, invoice GST/discounts, exact UPI amount, a real PDF download, public-link access/revocation, logout/relogin and zero uncaught page errors. WhatsApp navigation is intercepted: the URL/message/popup are verified, but no message is sent.

To run real PostgreSQL locking tests in a separate temporary database (the role must have CREATEDB):

```powershell
cd backend
$env:BILLORA_TEST_DATABASE = 'billora_test_' + [Guid]::NewGuid().ToString('N').Substring(0,12)
..\.venv\Scripts\python.exe manage.py test billing.tests.test_concurrency --settings=config.postgres_test_settings --noinput
```

For Neon, the test-only settings derive the matching direct host from the pooled host to prevent idle pooled sessions blocking cleanup. The running application keeps its pooled connection. The test runner removes only its randomly named disposable database after completion. Never configure test database NAME as the application database.
