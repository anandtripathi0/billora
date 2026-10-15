# Deployment: Neon + Render

## Neon PostgreSQL

1. Create a Neon project near the Render region. Use a separate development branch/database for tests.
2. Copy the **pooled** connection string from Neon's Connect dialog. Put it in the backend's `DATABASE_URL`; retain `sslmode=require`.
3. Billora sets `CONN_MAX_AGE=0` and disables server-side cursors for compatibility with transaction pooling. One tenant is locked during invoice creation, then products are locked in primary-key order. Unique database constraints enforce invoice numbers and idempotency keys.
4. Migrations run during backend startup for the initial single-instance deployment. For multiple instances, run migrations once as a release operation before rolling out workers; remove the startup migration command to avoid concurrent schema operations.
5. Monitor database storage, compute usage, connection counts, query latency and cold starts. Free quotas are finite. Use `cleanup_expired` periodically to remove old sessions and throttle buckets. Keep invoices and audit logs.

## PDF generation without storage

ReportLab generates PDFs in memory from saved invoice snapshots at creation and on each download/share request. No R2, S3, B2, storage keys, persistent disk, Pango, or PDF service is required. Current payment status and remaining-balance QR are generated from the saved payment state; original product/customer/business snapshots remain unchanged. A failed render leaves the saved invoice intact and is logged for diagnosis.

## Render

1. Create a GitHub repository and push the project. In Render select **New → Blueprint**, connect the repository, and use `render.yaml`.
2. The Blueprint creates `billora-api` and `billora-web` Docker services. Before completing setup, enter the secrets requested by the Blueprint.
3. Once Render assigns the public service hostnames, update:
   - API `ALLOWED_HOSTS`: backend hostname only. Render's `RENDER_EXTERNAL_HOSTNAME` is also automatically added by Django settings.
   - API `FRONTEND_URL` and `CSRF_TRUSTED_ORIGINS`: the frontend's HTTPS origin.
   - Web `BACKEND_URL`: the backend's HTTPS origin.
4. Keep backend `DEBUG=false`, `DB_SSL_REQUIRE=true`, `SECURE_SSL_REDIRECT=true`, and `BILLING_ENABLED=false`.
5. Deploy both services. The backend applies migrations, collects admin static files and starts Gunicorn. The frontend builds a Next.js standalone server. Its runtime proxy keeps browser requests and session cookies on the frontend origin.
6. Check `/api/health/` on the backend and `/health` on the frontend. Backend health includes a PostgreSQL query.
7. Create a superuser through an available trusted Render shell, or run `python manage.py createsuperuser` locally with the production backend environment configured securely. Avoid putting passwords into command arguments or committing them. Sign in at the frontend with the superuser's email.
8. Configure a business, add a product and customer, create an invoice, download its PDF, test the UPI amount, record a partial payment, and verify the QR changes. Prepare and manually send a WhatsApp message, then revoke the link and verify access fails.
9. Test password-reset email with a real mailbox. Render's free web services block outbound SMTP ports **25, 465, and 587**. Set `EMAIL_PORT` to a provider-supported permitted alternative such as 2525 with STARTTLS, or move the API to a plan that permits your provider's port. Do not use the generic local default of 587 on Render free. [Render's documented restrictions](https://render.com/docs/free#other-limitations).

Pricing and free service availability can change. Review your Render and Neon dashboards before selecting plans. The two web services share Render's workspace free-instance-hour allowance; the documented 750 hours are not a separate allowance for each service. Free services also sleep when idle. This configuration does not guarantee continuous free uptime. [Render free usage rules](https://render.com/docs/free#monthly-usage-limits).

`check --deploy` deliberately reports `security.W021`: HSTS preload is not enabled. HTTPS, secure cookies, HSTS and subdomain HSTS are enabled in production, but the project does not enroll an unverified user domain into browser preload policy. Review all domain/subdomain HTTPS requirements before a deliberate preload decision.

## Production smoke checklist

- [ ] `DEBUG=false`; unique stable secret; PostgreSQL SSL; HTTPS origins configured.
- [ ] `python manage.py check --deploy` reviewed; secure session and CSRF cookies confirmed in the browser.
- [ ] Migrations applied; separate backup and restore tested.
- [ ] Two businesses cannot read each other's customers, products, invoices, or payments.
- [ ] Manager/cashier/viewer permissions tested; super-admin endpoints denied to owners.
- [ ] PDFs regenerate from database snapshots after application restarts.
- [ ] GST/supply/rounding configuration reviewed for the business's actual invoicing requirements.
- [ ] Partial payment updates PDF and UPI amount; scanning a QR never changes payment state.
- [ ] Expired/revoked sharing tokens fail; no customer details leak into logs or public lists.
- [ ] Real SMTP reset flow tested; credentials remain server-side.
- [ ] PostgreSQL concurrency tests and realistic load tests run against target-like infrastructure.
- [ ] Logging, database limits, application errors and availability monitored.
- [ ] Automatic messaging and payment collection remain disabled until their integrations are implemented and reviewed.

## Backup and restore

Use Neon's recovery features according to your actual plan and maintain encrypted independent backups. Use a **direct, non-pooled** connection URL for backup/restore tools. Store it in your secret manager as `DIRECT_DATABASE_URL` when running these commands; the app itself does not require that variable.

```sh
pg_dump --dbname="$DIRECT_DATABASE_URL" --format=custom --no-owner --file=billora-backup.dump
# Restore only into a NEW empty database, never over live data:
pg_restore --dbname="$RESTORE_DATABASE_URL" --no-owner --no-acl billora-backup.dump
```

Invoice data, payments, immutable logos and sharing-token digests live in PostgreSQL. Restore the database into an isolated environment and regenerate PDFs; there are no PDF files to back up. Test invoice totals and tenant access before a deliberate cutover.

## Useful references

- [Django PostgreSQL and transaction-pool notes](https://docs.djangoproject.com/en/5.2/ref/databases/)
- [Neon Django guidance](https://neon.com/blog/python-django-and-neons-serverless-postgres)
- [Render Blueprint specification](https://render.com/docs/blueprint-spec)
- [ReportLab PDF generation](https://docs.reportlab.com/reportlab/userguide/ch5_platypus/)

## Environment values

Backend required: `DATABASE_URL` (Neon pooled URL with SSL), `DJANGO_SECRET_KEY` (generated by Blueprint), `FRONTEND_URL=https://<web-service>.onrender.com`, `CSRF_TRUSTED_ORIGINS` (same frontend origin), and `ALLOWED_HOSTS=<api-service>.onrender.com`.

Backend flags: `DEBUG=false`, `DB_SSL_REQUIRE=true`, `SECURE_SSL_REDIRECT=true`, `BILLING_ENABLED=false`. Render supplies `PORT`.

Frontend required: `BACKEND_URL=https://<api-service>.onrender.com` with no `/api` suffix. Optional `NEXT_TELEMETRY_DISABLED=1`.

SMTP variables are intentionally omitted from the Blueprint setup prompts. For real password-reset email only, add `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS=true` and a verified `DEFAULT_FROM_EMAIL`. These do not block registration, login, invoices, PDF or manual sharing. Do not enter WhatsApp or payment-gateway credentials; those integrations are not used.

The browser uses the frontend's same-origin `/api` proxy. Django's HTTP-only session cookie and CSRF cookie are Secure and SameSite=Lax in production; cookies do not need cross-site SameSite=None. Keep the actual frontend HTTPS origin trusted. The proxy lets Render derive HTTPS from the backend connection, avoiding internal HTTP scheme overrides and redirect loops.

No Render deployment was performed during this repair; connect your repository in Render and follow the steps above.
