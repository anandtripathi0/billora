# Billora repair — 12 October 2026

## Confirmed causes

- No root `.env` or live database connection was configured. The supplied Neon database was empty. Normal Django settings require PostgreSQL, so a complete real account/session workflow needed environment setup and migrations.
- The previous PDF engine required native Pango libraries that were absent on Windows. Production PDF/share requests also required R2 keys, contrary to the revised free-storage brief.
- `npm start` invoked `next start` despite the standalone build configuration. It now launches the standalone server and supplies the required static/public directories.
- Registration lacked password confirmation and opened onboarding settings. It now validates matching passwords on both server and UI and opens the personalized dashboard.
- On a 720-pixel-high desktop viewport, the fixed sidebar pushed Sign out below the viewport. The sidebar now scrolls, keeping account actions reachable.
- The old theme and theme toggle selected dark navy. The app now uses a consistent cream palette and locally bundled Geist typography.
- Next.js normalized slash-terminated API requests with an unnecessary HTTP 307. Django-style API paths now reach the proxy directly.
- The proxy previously overrode the forwarded scheme using Next's internal URL. It now lets the backend hosting proxy supply the actual HTTPS scheme, avoiding a production redirect-loop risk. This production improvement still needs verification after Render deployment.

## Completed changes

Real HTTP-only Django sessions and CSRF protection are preserved. The existing business model, migrations, transactional invoice logic and business records are preserved. Neon is connected over TLS and every existing migration was applied.

PDFs are generated with ReportLab in memory after saving an invoice and regenerated on download. No PDF is stored on local disk or in cloud object storage. Saved business/customer/product snapshots determine historic content; current payment state determines balance and UPI amount. PDFs support repeated table headers across pages, logos, GST breakdown, discounts, customer/business details and payment QR.

Invoice actions include Download PDF, Print Invoice, Share on WhatsApp, Copy Invoice Link and Copy Invoice Message. Supporting browsers expose a native share-sheet action. WhatsApp uses the saved normalized number and an actual invoice message. Tokens are random, hashed in the database, expire in seven days and can be revoked. Public rendering is rate-limited. No message delivery is claimed.

Dashboard values, product/customer CRUD, invoice records, payments and sessions use Neon. Registration, product search/edit/archive, customer editing and purchase history are covered by the expanded browser workflow. Basic ₹49/month, Pro ₹89/month and Yearly ₹399/year remain free during launch with BILLING_ENABLED=false.

## Files changed

- Private local configuration: root `.env`, `frontend/.env.local` (ignored; no credentials in this report).
- Frontend: `src/app/globals.css`, `src/app/layout.tsx`, `src/app/api/[...path]/route.ts`, authentication, shell, providers, public pages, dashboard, revenue chart and invoice components; Next configuration; package manifest/lock; `scripts/start.mjs`; Playwright configuration and workflow.
- Backend: `config/settings.py`, `config/postgres_test_settings.py`, PDF generator, invoice/share/report views, registration serializer, WhatsApp message builder and backend tests; dependency requirements/constraints; Dockerfile.
- Deployment/documentation: `.env.example`, `render.yaml`, `compose.yaml`, CI workflow, README, deployment/architecture/testing/verification guides.

## Remaining external setup

- Render has not been deployed; create the two services from `render.yaml` after connecting this repository. Full instructions and all environment values are in `DEPLOYMENT.md`.
- Real SMTP email is not configured. Local password-reset emails print to the backend console. Set SMTP variables to deliver email to users.
- A localhost sharing URL is only reachable on this machine. Customer-accessible links need the deployed HTTPS FRONTEND_URL.
- No WhatsApp message or live UPI payment was sent during testing. Opening WhatsApp requires the shopkeeper to press Send; QR generation never marks an invoice paid.
- Hosted performance, load/capacity, backups and Render Docker deployment remain unverified.

See `VERIFICATION.md` for final test counts and `../README.md` for local PowerShell run commands.
