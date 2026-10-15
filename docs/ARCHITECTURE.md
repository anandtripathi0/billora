# Architecture and operational boundaries

Browser → same-origin Next.js `/api/*` proxy → Django REST Framework → PostgreSQL. Django generates PDFs in memory with ReportLab and streams the resulting bytes. The browser never receives database credentials. UI records and real sessions live in PostgreSQL. Authentication does not use localStorage.

## Access and consistency

One active business membership per user keeps tenant selection unambiguous. Owners create staff directly with a password they share securely; staff can change it. Owners/managers manage catalogs and settings. Cashiers create customers/invoices and record payments. Viewers can read reports, ledgers and invoices. All roles are checked on the server. Superusers use a separate administration interface.

Invoice numbers are monotonically increasing per tenant, with a configurable prefix. Number allocation, item snapshots, initial payment, stock changes and audit entry are committed in one transaction. Invoice creation and payment calls require UUID idempotency keys. Reusing an invoice key with different validated input is rejected. Stock is locked and checked on the server. Prices are always read from current product records; previews are recalculated at finalization because stock or prices may have changed.

Money is `Decimal`, rounded half up to paise. Percentage GST applies after an invoice-level fixed discount. Discount is allocated by largest remainder so line discounts add up exactly. Intrastate CGST and SGST are rounded separately per line; interstate IGST is rounded per line. Existing invoices cannot be silently edited. Corrections/returns/credit notes, e-invoicing, e-way bills, GST filing, full accounting and verified gateway settlement are outside this launch implementation.

## PDF and sharing lifecycle

Invoice persistence is synchronous and independent of PDF rendering. Print works from invoice details. PDF generation runs from the saved snapshot after invoice creation and on subsequent PDF/share requests. Download and public-share rendering have database-backed rate limits. No PDF bytes are persisted. The renderer accepts validated inline PNGs only and blocks network/file fetches. Logo uploads are resized/validated and bounded to 150 KB; invoice snapshots reference an immutable, tenant-owned logo record. Identical logos are deduplicated per business so creating 1,000 invoices does not create 1,000 copies of the same logo.

Share tokens have 256 bits of entropy, are stored only as SHA-256 digests, expire in seven days, and can be revoked together per invoice. Business suspension also invalidates access. Sharing links are bearer capabilities: anyone with a currently valid link can see that one invoice. There is no invoice listing through the public route. WhatsApp deep links only prepare a message. `MessageLog.status=link_prepared` never implies delivery.

## Free launch and future subscriptions

Plans are seeded via migrations. Plans, subscriptions and future subscription payments have database models. `BILLING_ENABLED=false` is the deployment default. There is no checkout, subscription creation side effect, automatic charge, or paywall in this version. Changing the flag alone cannot collect money. Enable billing only through a future reviewed provider integration and verified webhook lifecycle.

## Optional Celery + Redis architecture (not enabled)

For automatic WhatsApp messaging, add a PostgreSQL outbox row in the invoice transaction containing the template ID, consent record and immutable delivery payload. A dispatcher hands pending jobs to Celery through a persistent Redis broker. A dedicated worker uses the official Meta Cloud API; jobs carry an idempotency key and retry transient errors with exponential backoff and a maximum attempt count. Keep provider message IDs and every state transition in message logs. A scheduled reconciler retries orphaned jobs from the durable database outbox after worker/broker outages. Use signed, verified webhooks for sent/delivered/read/failed statuses, and deduplicate webhook event IDs.

Sending outside permitted windows requires approved templates and customer consent. Include a dead-letter review interface and tests for provider errors, duplicate jobs, rate limits and webhook replay. Set credentials only on the backend/worker. Deploy the worker and durable broker before enabling automatic sending. This version deliberately exposes no automatic-send switch that pretends this infrastructure exists. The current manual-sharing workflow needs neither Celery nor Redis.

## Performance and limits

Queries are tenant-filtered, lists paginated at 25, product/customer lookups indexed, charts lazy-loaded, and frontend queries cached for 30 seconds without polling. CSV imports are transactional and capped at 500 rows / 1 MB. Report exports are capped at 5,000 rows; invoice lines at 100. Database connection lifetime is zero to avoid leaving idle client connections on Neon. Invoice writes for one tenant serialize; independent tenants can proceed concurrently. Profile actual workloads before widening worker counts or claiming 1,000 invoices/day or 50 simultaneous users.

Application login throttles are database-backed so they are shared across workers. The API's service-level throttle sees the proxy address when accessed through Next.js; it deliberately uses a higher cap, with stricter per-account throttles. For high-volume public traffic add a trusted edge rate limiter, monitor abuse, and tune limits based on measured traffic. Unknown forwarded client-IP headers are not blindly trusted.

