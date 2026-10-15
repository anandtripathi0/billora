# Verification performed — 12 October 2026

## Completed checks

- **Neon PostgreSQL:** live client connection verified with TLS enabled; all existing Django migrations applied. The provided database started empty. Normal localhost sessions and billing records now persist in Neon.
- **Backend:** 50 tests discovered; 47 passed in isolated in-memory test settings and 3 PostgreSQL-specific concurrency tests skipped in that run. The same 3 concurrency tests then passed separately on Neon using a randomly named temporary database and the direct endpoint. Temporary database teardown completed successfully. The application database was not deleted or reset.
- **PDF:** actual ReportLab output parsed with pypdf, including amounts, immutable product/customer snapshots, embedded QR, paid revisions, multi-page headers, literal user-supplied text, reports, real private/public downloads, no persistent PDF writes, and public render throttling. The six PDF tests were rerun after correcting zero-valued report cells and all passed.
- **Frontend:** 8 Vitest tests passed. Final Next.js production build passed, including TypeScript and all 25 static pages plus dynamic routes. Geist is bundled locally.
- **Migrations and dependencies:** no ungenerated model changes; Django system check passed; pip reported no broken dependencies.
- **Production settings check:** no errors; one intentional security.W021 warning because browser HSTS preload is not enabled.
- **Local HTTP:** homepage, login page and database-backed API health endpoint returned 200. Running servers bind to loopback.
- **Visual:** cream homepage, desktop/mobile dashboard, and the rendered real invoice PDF were inspected. The invoice has clear headers, aligned amounts, GST/discount details, a readable QR, and page numbering without clipped content. Screenshots are retained under `docs/screenshots/`.

## Browser verification

**2 browser tests passed** in the final run (desktop Chrome at 1280×720 and Pixel 7 viewport), using the production Next.js build and normal Neon-backed Django settings. Total parallel runtime: 5.2 minutes.

Both complete workflows verify homepage access, unauthorized redirect, useful invalid-login errors, password confirmation, registration, actual first-name greeting, HTTP-only sessions surviving refresh, settings persistence, product create/edit/reload/archive, customer create/edit/ledger, exact GST and discounted totals, saved invoice/PDF readiness, exact unpaid UPI amount, a real PDF download, the correct WhatsApp number/message and popup, unauthenticated public PDF access, rejection of unauthenticated private access, clipboard copying, recorded payment/QR removal, public-link revocation, no horizontal page overflow, logout and successful login again. Both finished with zero uncaught browser page errors.

A separate focused browser check also passed real login, chart rendering, screenshot capture and scroll-to-logout at a short desktop viewport. The final sidebar is scrollable. Screenshots wait for the revenue chart to load.

Test accounts are synthetic, uniquely named, and isolated from the user's business. WhatsApp navigation is intercepted to verify the actual deep-link URL without sending a message. Synthetic account records remain isolated in Neon; no real business records were deleted.

## Not verified or not configured

- No Render deployment, Docker image build, GitHub push, or hosted cookie/CSRF smoke test was performed.
- Real SMTP delivery is not configured. Local reset emails go to the backend console.
- No real WhatsApp message or UPI payment was sent. The application prepares a message and records shopkeeper-confirmed payments; it never treats a QR or message link as payment/delivery confirmation.
- Localhost share URLs cannot be opened from a customer's separate phone. Deploy with a public HTTPS FRONTEND_URL for that use.
- The load harness was not run; no capacity, latency or uptime guarantees are claimed.

R2/WeasyPrint are removed from the active implementation. No cloud file-storage credentials or WhatsApp API credentials are required. No business data or original migrations were deleted.
