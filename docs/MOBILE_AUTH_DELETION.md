# Mobile authentication and safe deletion — 16 October 2026

This update keeps the existing cream UI, invoice calculations, PDF/thermal printing, payments and tenant boundaries. It changes authentication and record deletion in the existing application.

## Authentication

- Signup asks for **Store Name, Mobile Number, Password** only. It validates Indian numbers, normalizes them to `+91XXXXXXXXXX`, applies the existing password validators and Argon2 hashing, creates the user/store/settings/owner membership atomically, signs in and redirects to `/dashboard`.
- Login asks for **Mobile Number and Password** only, with a show/hide control, Forgot Password and Create Account links. It uses one indexed account lookup with joined tenant settings, the existing session/CSRF protections, normalized rate-limit buckets and immediate submission feedback. A successful login populates the session cache. Visiting login while authenticated redirects to the workspace.
- The dashboard greeting reads the actual database store name. Staff creation now uses a mobile number too; staff must replace their temporary password on first use.
- Public email reset links have been removed. Old reset routes return HTTP 410 and do not change any password. The old reset page redirects to Forgot Password. No OTP, recovery code, Firebase, email verification or public mobile-plus-new-password reset exists.
- Forgot Password says: “Forgot your password? Contact Billora Support/Admin to reset your password.” The owner declined to supply contact details, so **Contact Admin / Support** shows instructions to contact the installation's administrator directly; it does not invent an email or phone number.
- Account settings contains Current Password, New Password and Confirm New Password. It checks the current password, requires a different strong replacement, records an audit event, retains the current session and invalidates other sessions.

## Administrator-assisted recovery

The backend `/admin/` interface is restricted to active platform superusers with a personal password. Both administrator login and account assistance are rate limited. Store owners/managers and ordinary Django staff cannot use it.

1. Independently verify that the requester owns the account/store. A mobile number alone is not proof. Refuse the reset if verification is incomplete.
2. Open **Users → Verify mobile / reset password** for the correct account.
3. If needed, choose **Link a verified login mobile**. This changes only the login mapping; the old contact number, username and password hash are retained. Already-assigned login numbers are refused. Accounts are never merged.
4. To reset a password, choose the reset operation. Enter and confirm a strong temporary password, tick the ownership-verification declaration, provide a non-sensitive case reference/method, and re-enter the administrator's own password.
5. Deliver that temporary password privately only after verification. It expires in 24 hours. It authenticates only into the password-change screen; protected API routes reject access until the user replaces it with a personal password.

The reset transaction records the administrator, account/store, timestamp and verification reference, and invalidates existing sessions through Django's password-derived session hash. Passwords are not written to audit records or request logs. The ordinary Django admin password-change route redirects to this verified workflow. Audit records are read-only in administration.

The session behavior follows [Django's session invalidation mechanism](https://docs.djangoproject.com/en/5.2/topics/auth/default/#session-invalidation-on-password-change). The custom admin site uses Django's supported [AdminSite extension](https://docs.djangoproject.com/en/5.2/ref/contrib/admin/#adminsite-objects).

## Existing accounts and migration

Migration **0009_mobile_auth_and_safe_deletion**:

- Adds nullable, unique `User.login_mobile`, a legacy mobile candidate, and temporary-password state. Makes email optional without deleting existing emails.
- Derives a normalized **candidate** from each valid old contact number. It does not assume the number is verified. Duplicate candidates are retained and blocked from new signup until an administrator resolves the relevant account; no account is merged or removed.
- Preserves every existing username, password hash, business and membership. Existing sessions remain valid. New mobile logins for legacy accounts require the administrator's verified mapping.
- Adds `Customer.is_active`, updates the active-customer mobile uniqueness constraint, and adds an administrative audit reference.

If no platform administrator exists, the installation owner must explicitly choose one or create one interactively from a trusted terminal:

```powershell
.\.venv\Scripts\python.exe backend/manage.py createsuperuser
```

Sign in with that administrator's **username** at `http://localhost:8000/admin/` (the backend HTTPS `/admin/` URL when deployed). No production administrator is seeded automatically, and no sample credentials are created in the application database.

## Customer and product deletion

Visible Delete controls exist on Customers, customer details, Products and product details. Confirmation identifies the record and shows the customer's name/mobile. Only the store's owner or manager can delete. The API performs tenant-scoped lookups and returns 404 for another store's records.

Deletion takes a transaction and the same business-first lock used by invoice creation and stock updates:

- An unused customer/product is permanently deleted from PostgreSQL.
- A customer linked to any invoice (including cancelled invoices) is removed from active lists and new billing. Unneeded name/contact/address/GST fields are anonymized on the customer record; immutable invoice snapshots remain untouched. Merge references are conservatively retained. Its ledger remains available by ID for financial history.
- A referenced product is deactivated; its stock quantity and invoice item descriptions/prices remain intact. It can be inspected through the existing archived inventory view.
- Invoice/payment/refund rows are protected. Payments and cancellation/refund stock restoration continue to work after archival. No financial record is cascade-deleted.
- After a successful request, cached lists remove the row immediately and financial/list queries refresh without a full-page reload. Session queries are not invalidated by deletion.

## Changed files

- Models/migration: `backend/billing/models.py`, `migrations/0009_mobile_auth_and_safe_deletion.py`.
- Authentication/admin: `auth.py`, `authentication.py`, `serializers.py`, `validation.py`, `admin.py`, `admin_accounts.py`, `admin_site.py`, `admin_config.py`, admin assistance template, `backend/config/settings.py`.
- Deletion and invoice checks: `backend/billing/views.py`, `services.py`.
- UI: `auth-form.tsx`, `password-change.tsx`, `settings.tsx`, `shell.tsx`, `dashboard.tsx`, `records.tsx`, product detail route, reset redirect, `frontend/src/lib/api.ts`, small password-control CSS.
- Regression coverage and tools: Django mobile/deletion tests, existing authentication tests, browser workflows, demo/load/benchmark commands and Locust mobile credentials.
- Documentation: README, deployment/testing/printing instructions and `.env.example` remove obsolete SMTP recovery setup.

## Validation

- Production Next build and TypeScript passed; 19 frontend unit tests passed.
- The final complete Django suite discovered **111 tests: 103 passed on SQLite and eight PostgreSQL-only cases were skipped there**.
- 30 selected tests passed against a disposable **real PostgreSQL** database, including mobile auth, CSRF, admin reset, migration preservation, tenant isolation, query budgets, all eight concurrency cases, and invoice/payment/refund integrity. The database was removed by the test runner. The separate browser-test database and its temporary administrator credentials were also removed after testing.
- All four new desktop/mobile browser workflows passed against a separate Neon database with real Argon2 hashing. These cover exact signup/login field counts, show/hide password, authenticated redirects, persistence, logout, change-password confirmation, duplicate mobile rejection, disabled public reset, hard/soft deletion from lists/details, retained PDF/stock/payment data, and a real browser administrator-assisted reset followed by forced password replacement.
- Final mobile login and signup screenshots were inspected at 390 px width. The cream theme and exactly two/three form inputs were confirmed.
- Migration 0009 was applied to the existing application database. Before/after checks confirmed the same account identity/password-hash digest, business/customer/product counts, aggregate stock, invoice totals/paid amounts, payment totals and refund totals. No existing account or business data was removed.
- Migration drift check and Docker-style build-time static collection passed (163 existing assets, 734 post-processed). Production security settings passed with only the existing `security.W021` warning: HSTS preload enrollment remains intentionally disabled. The Render Blueprint is unchanged. No actual Render deployment, Docker execution or physical thermal printer test was performed; browser printing tests use the existing paired mock.
- All six existing desktop/mobile inventory, invoice and retail workflows passed, making **10 passing browser workflows** with the four new cases. The invoice tests required a selector correction for the existing customer Mobile number label; both passed on rerun. Real PDFs, QR, sharing handoff, collections, payment, refunds, stock and the paired printing mock were exercised. No new performance benchmark or guaranteed response-time claim is made.

**Installation setup still needs an administrator choice:** the existing database had no active platform administrator. No existing account was promoted without the owner's identification/authorization. Legacy accounts retain their current sessions and passwords, but their next mobile login requires a verified mapping. The new recovery UI is functional; operating it requires a configured platform administrator.

## Deployment and environment

No new application environment variables, SMS provider, SMTP credentials or Firebase configuration are required. Keep the current `DATABASE_URL`, `DJANGO_SECRET_KEY`, backend/frontend origins and secure production cookie settings. The Render Blueprint and Docker startup architecture are unchanged. The backend startup applies migration 0009.

```sh
git checkout codex/billora
git pull --ff-only origin codex/billora
python backend/manage.py migrate --noinput
cd frontend
npm ci
npm run build
npm run start
```

For Render, deploy `codex/billora` using the existing Blueprint and backend environment. There is no live deployment to validate in this workspace. Configure the platform administrator and link verified legacy login mobiles before asking old users to log out. Preserve the existing Django secret so sessions remain valid.
