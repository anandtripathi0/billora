# Billora performance investigation — 15 October 2026

The application is running locally, not on Render (confirmed by the owner). The changes reduce measured warm request times substantially, but **several actions still take seconds across the current localhost-to-Neon connection**. This report does not promise sub-second authentication or Render wake-up.

## Method and limits

Baseline source: commit `20015ef`. Both passes used the same Windows computer, real Argon2 password hashing, the same Neon endpoint/pool configuration, and an isolated `billora_perf_…` database. Each pass created a separate synthetic tenant with 200 products and 1,000 starting invoices. No real users, invoices, customers or stock were edited or deleted by the benchmark. Index migration 0008 was also applied to the existing application database; it only adds indexes.

The API table measures Django's test client against real PostgreSQL, including middleware, authentication, rendering, SQL/network waits and transactions. It **excludes HTTP proxy/browser time**. There are 20 sequential samples per main endpoint, and three registrations. p95 is the nearest-rank sample estimate, not a production service guarantee. Other isolated verification activity and network variability can influence wall times; query-count reductions are the more stable evidence. Connections and the database were already in use for these warm measurements.

Full production-browser tests separately measured the same-origin Next proxy, authentication and dashboard display. Homepage timings measure production HTTP response completion, not a fully rendered browser page. A first request after starting a local process is not evidence of a suspended Render or Neon service waking up.

Raw measurements and plans are in [performance/](performance/). They contain synthetic fixtures only, not credentials or real business data.

## Warm API results

| Action | Before p50 | After p50 | Before p95 | After p95 | SQL queries before → after |
|---|---:|---:|---:|---:|---:|
| Login | 12.886 s | 4.967 s | 16.853 s | 6.964 s | 16 → 8 |
| Registration (n=3) | 10.652 s | 7.006 s | — | — | 23 → 15 |
| Session /me | 2.474 s | 0.756 s | 3.820 s | 1.357 s | 5 → 2 |
| Full dashboard API | 8.038 s | 3.394 s | 11.272 s | 4.672 s | 16 → 9 |
| Product search | 3.028 s | 1.692 s | 4.642 s | 2.646 s | 6 → 4 |
| Customer mobile lookup | 2.547 s | 1.030 s | 3.187 s | 1.940 s | 5 → 3 |
| Invoice creation, including PDF check | 9.829 s | 5.403 s | 11.095 s | 7.660 s | 17 → 13 |

The UI requests the dashboard summary first (7 queries), then its optional chart and best sellers (4 queries including that request's authentication). The full API remains available with its original combined response. The split intentionally uses one extra HTTP request and two additional auth queries overall, so expensive optional reports do not delay the main dashboard. Financial totals are always calculated from tenant-scoped data; no shared financial cache was introduced.

CSRF bootstrap is now unauthenticated and performs **zero database queries**, including when a session cookie is already present. The mixed anonymous/authenticated bootstrap sample has before/after p95 of 655.05/5.19 ms. Its median is approximately 3 ms in both passes. The larger benefit is removing those requests from normal mutations.

## Browser results

Production Chrome, same-origin proxy, separate synthetic accounts; these small samples do not justify a browser p95:

| Interaction | Before | Final after | Samples per pass |
|---|---:|---:|---:|
| Login click → dashboard totals visible, median | 15.557 s | 8.964 s | 3 |
| Registration click → dashboard totals visible | 24.621 s | 15.700 s | 1 |
| Products navigation → search controls visible, median | 235 ms | 248 ms | 3 |
| Return to dashboard totals, median | 208 ms | 203 ms | 3 |
| CSRF bootstrap requests in the workflow | 7 | 1 | one registration, three logins/logouts |

Navigation timings measure visible controls/totals, not completion of all inventory/chart requests. Both passes made one `/auth/me/` call for the explicit reload and none for the tested client-side navigations. Dashboard HTTP calls intentionally increased from 5 to 10 because summary and optional widgets are separate; this is not duplicate fetching. The final trace had no page JavaScript errors.

Chrome's final-document metrics report script time 0.121 s, layout 0.018 s, style recalculation 0.026 s and task time 0.686 s. These are browser diagnostics, not React component render counts. The inspected query subscriptions, debounced searches and bounded lists did not establish an excessive-rerender bottleneck; no speculative memoization rewrite was applied. A detailed React component profile was not collected.

## Confirmed bottlenecks and changes

1. **Serial database round trips dominate.** After changes, `SELECT 1` itself measured p50 **352.96 ms**, p95 **1,041.50 ms**, n=20; initial pool checkout in that process took **3,874.31 ms**. Representative SQL plan execution was only **0.044 ms** for email lookup and **0.151 ms** for invoice history. These are separate measurements, not identical requests. This distinguishes network/connection waits from SQL computation.
2. **Authentication performed repeated lookups and transactions.** `TenantBackend` loads user, membership, business and settings together. Login uses one account lookup. PostgreSQL throttling now uses one atomic conditional upsert per bucket, keeping the existing per-identity and service limits. Invalid users still incur password hashing. Legacy Django sessions remain accepted until logout/expiry; those sessions retain the old query pattern until signing in again.
3. **Every mutation previously fetched CSRF again.** The client now reuses the current CSRF cookie/token, shares simultaneous bootstrap requests, observes cookie rotation across tabs, and accepts a rotated token from login/register/logout. It refreshes/retries once only for an explicit CSRF rejection before the view runs. It does not replay a mutation on a timeout or generic 403. HTTP-only sessions, secure production cookies, same-origin proxying and CSRF validation remain enabled.
4. **Unnecessary refetches delayed completed actions.** Product/customer/invoice updates no longer invalidate the session query, and successful saves no longer wait for unrelated list refreshes before closing or navigating. Business queries still invalidate. Session cache duration remains the original 30 seconds; persistent layouts and the login response avoid redundant navigation checks.
5. **Dashboard aggregation needed too many queries.** Conditional sums/counts combine compatible aggregates. Lists stay capped at five; product categories are joined to prevent low-stock N+1 queries. The chart was already dynamically imported; it remains lazy and now waits for optional widget data.
6. **Invoice serialization and PDF generation reread the same immutable items.** The ordered item snapshot is cached on the request's model instance. Business settings are loaded with the locked business row. Invoice, stock, payment and cancellation transactions, lock order and database constraints remain intact.

Argon2 verification alone measured **131.60 ms median** in the baseline's five dedicated samples. Password hashing was not weakened. The residual delay is not explained by password work alone.

## Index and pooling review

- Before: `UPPER(email)` filtering could not use the unique plain-email index, even when sequential scans were discouraged. Migration 0008 adds `billing_user_email_upper`. With only a few synthetic users the optimizer still normally chooses a cheap sequential scan; an index-eligibility check now selects the new expression index. This is a scaling improvement, not a claim that tiny-table lookup became measurably faster.
- Before: invoice history sorted matching rows by date/creation time. After: `billing_invoice_history` supplies `(business_id, date DESC, created_at DESC)` order directly. The measured plan uses that index and avoids the sort.
- Customer lookup already uses `unique_active_customer_mobile`; no duplicate index was added.
- Tenant and existing inventory indexes were reviewed. The 200-product wildcard search is inexpensive inside PostgreSQL; no speculative trigram extension or large GIN index was added.
- Existing psycopg pooling remains enabled, with `CONN_MAX_AGE=0`, `min_size=0`, `max_size=5` per process, connection health checks and disabled server-side cursors. That avoids per-request TLS connection creation while remaining compatible with Neon's transaction pool. Pools can shrink to zero when idle; no keep-alive service was added. [Neon pooling documentation](https://neon.com/docs/connect/connection-pooling).

## Frontend, startup and cold requests

| Production homepage HTTP measurement | Before | After |
|---|---:|---:|
| First request after local process start, n=1 | 324.34 ms | 348.36 ms |
| Warm p50, n=20 | 11.83 ms | 11.93 ms |
| Warm p95, n=20 | 20.94 ms | 16.77 ms |

The homepage was already quick once the local process was listening; these measurements do not support a homepage speedup claim. The Next standalone server reported readiness with config-loading times of 34 ms before and 24 ms after, excluding npm/process launch. A separate after-change Django import/setup sample took 4,794.63 ms on this Windows host. Gunicorn startup was inspected but not executed on Windows; there is no measured Linux/Render startup comparison.

The production build generated 26 pages. Aggregate raw static chunk bytes changed from 1,526,462 to 1,492,789 in the final build; this is **all chunks**, not one page's compressed transfer size. There was no redesign or new heavy dependency. Route loading UI and immediate auth loading states provide feedback. After eight seconds the form explicitly reports that it is still waiting. Proxy timeouts return a real 504, not a fabricated success.

Backend static collection moved from every startup into the Docker image build. Migrations remain at startup so schema changes are not silently skipped. Gunicorn's access log omits raw URLs/queries and authentication headers; Django's default request/error logs are also sanitized so they cannot reintroduce lookup phone numbers or sharing tokens. Structured request timing supplies safe route templates instead. Hosting size, payment plans and architecture were not changed.

## Timing instrumentation

`billing/timing.py` wraps database execution through Django's supported [execute_wrapper hook](https://docs.djangoproject.com/en/5.2/topics/db/instrumentation/). It logs JSON containing a generated/validated request ID, route template, method, status, total milliseconds, SQL execution milliseconds/count, worker age, and first-request state. Authentication also records throttle/password spans. It never logs SQL, parameters, bodies, credentials, emails, phone numbers or actual sharing tokens.

`Server-Timing` exposes application/SQL timings; the Next proxy propagates those and adds its elapsed duration and the same request ID. **Proxy duration includes upstream time**, so do not add it to app time. SQL duration excludes pool checkout and commit waits; these remain part of total request time. `X-Worker-State: cold` means the first API request in this worker, not proof that Render or Neon was asleep. Proxy worker state is separate. Health checks can consume a worker's first request.

## Render limitations and next deployment

There is no deployed URL to test. Render documents that a free web service sleeps after 15 idle minutes and can take about a minute to wake. Two free services can introduce separate wake-up delays; code cannot guarantee an instant response through them. No paid upgrade or external keep-alive was configured. [Render Free documentation](https://render.com/docs/free).

Retain the server frontend: a static export would remove the current `/api` same-origin session proxy and would need a separately verified authentication architecture. It is not a drop-in performance switch. When deploying, choose backend/database regions close to each other; the measured network delay makes region placement worth checking. No database was moved.

Update an existing checkout and build:

```sh
git checkout codex/billora
git pull --ff-only origin codex/billora
python -m pip install -r backend/requirements.txt -c backend/requirements.lock
python backend/manage.py migrate --noinput
cd frontend
npm ci
npm run build
npm run start
```

For a Linux backend outside Docker, after configuring its environment:

```sh
cd backend
python manage.py collectstatic --noinput
python manage.py migrate --noinput
gunicorn config.wsgi:application --config config/gunicorn.conf.py
```

For Render, create a Blueprint from this repository's `render.yaml` on **codex/billora**, configure the existing environment values from [DEPLOYMENT.md](DEPLOYMENT.md), and deploy both services. Subsequent pushes deploy when auto-deploy is enabled:

```sh
git push origin codex/billora
```

Free Render services do not provide shell access; the backend Docker startup runs migration 0008 automatically. No new environment variables are required for normal operation. `BILLORA_PERF_DATABASE` and `PERF_PHASE` are test-only controls and must not be added to the hosted application.

## Changed code

- Authentication/security: `backend/billing/auth.py`, `authentication.py`, `exceptions.py`, `backend/config/settings.py`, `frontend/src/lib/api.ts`, `frontend/src/components/auth-form.tsx`.
- Queries and snapshots: `backend/billing/views.py`, `models.py`, `services.py`, `serializers.py`, `pdf.py`, migration `0008_performance_indexes.py`.
- Dashboard/navigation/save feedback: `frontend/src/components/dashboard.tsx`, `records.tsx`, `invoices.tsx`, `catalog-import.tsx`, `frontend/src/app/(business)/loading.tsx`.
- Safe timing/startup: `backend/billing/timing.py`, `backend/config/gunicorn.conf.py`, `backend/Dockerfile`, `frontend/src/app/api/[...path]/route.ts`.
- Reproducible verification: `benchmark_performance.py`, `config/performance_settings.py`, `billing/tests/test_performance.py`, `frontend/e2e/performance.spec.ts`, `frontend/tests/api.test.ts`, and the existing invoice test's inactive-product label assertion.

## Verification

- Full Django suite: **92 discovered, 85 passed on SQLite, 7 PostgreSQL-only tests skipped there**. The final logging configuration was also checked to ensure all three Django request loggers sanitize their output.
- Separate real PostgreSQL run: **12 passed**, including all seven concurrency cases and five security/query-budget cases. Covers atomic throttle caps, parallel imports, oversell, duplicate invoice submissions, unique numbering, mobile upsert, payment and cancellation/refund safety. The uniquely named PostgreSQL test database was removed by Django after success.
- Frontend: **19 Vitest tests passed**, including CSRF reuse, concurrent bootstrap, rotation, definitive-rejection retry and no replay after permission/timeout failures.
- Production Next build and TypeScript passed; 26 pages generated. Migration drift check passed. Build-time static collection was verified: 163 files, 777 post-processed assets.
- The initial broad browser run passed both inventory and both retail workflows. Its invoice tests reached the final archive assertion and found the old expected text `Archived`; the existing UI says `Inactive`. Only that stale test assertion was corrected.
- Both invoice workflows passed on rerun against the final production build. **All six desktop/mobile billing workflows passed**, plus the dedicated final authentication/navigation performance workflow. These include real session persistence, customer lookup, product search, invoice totals, PDF, QR, manual sharing handoff, stock, collection, payment and cancellation checks.

Tests run against synthetic tenants in a separate database. The isolated profiling database was removed after saving the measurements. Physical printer hardware, Docker image execution and Render/Gunicorn runtime were not exercised on this Windows host. Printer browser tests use a paired mock device.

## Reproducing safe measurements

Use a separate disposable PostgreSQL database named `billora_perf_` followed by 12 hexadecimal characters, provisioned on the same test endpoint. The command refuses the real application's database name. It inserts synthetic fixtures but does not remove any records.

```sh
export BILLORA_PERF_DATABASE=billora_perf_REPLACE_WITH_12_HEX
python backend/manage.py migrate --settings=config.performance_settings
python backend/manage.py benchmark_performance --settings=config.performance_settings --samples 20 --report performance.json
```

Run that backend on port 8100. In a separate shell start the production frontend with `BACKEND_URL=http://127.0.0.1:8100 PORT=3100`, then:

```sh
cd frontend
E2E_BASE_URL=http://localhost:3100 PERF_PHASE=after npx playwright test e2e/performance.spec.ts --project=chromium
```

Do not run the profiling settings as the real application. The browser benchmark verifies CSRF request counts, session persistence and navigation, and writes measurements to `.buildtemp/`.
