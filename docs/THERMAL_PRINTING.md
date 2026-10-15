# Retail billing and thermal printing

Billora saves invoices and payments in PostgreSQL. Receipt/PDF generation is on demand. No object storage or printer service subscription is needed.

## Fast billing

Open **Invoices → Create invoice**. Enter the customer's mobile first. Existing customers and their lifetime purchases load automatically; a new number needs only a name. Add products, change quantities/prices, select Paid / Partial / Unpaid, and choose **Save Invoice** or **Save & Print**. The server verifies the displayed calculation and commits stock, payment and invoice together. Retries use the same submission key. Preview remains available.

**Customer Collection** shows valid order count, lifetime purchases, net payments, outstanding and last purchase date. Payments are aggregated separately to prevent multiplication when an invoice has several payments. Customer history is oldest first. These are finalized sales; drafts are never persisted as purchases.

Owners/managers can fully cancel a sale after all items are returned. For a paid or partial sale they must first return the money and explicitly confirm the refund. Billora records the full refund, retains payment history, restores stock once and excludes the cancelled sale from sales/purchases. It does not transfer money. Partial returns, partial refunds and credit notes are not supported by this workflow.

Migration 0006 normalizes existing mobile numbers and combines duplicate histories into the earliest customer within each business. Original duplicate customer rows are retained with `merged_into`, and invoice snapshots remain unchanged. Take a database snapshot before any production migration as usual. Do not reverse this migration to try to split merged histories.

## Browser printing (58 mm / 80 mm)

1. Install the printer using its manufacturer's Windows/macOS driver.
2. Set the default paper width in **Business settings**.
3. Open an invoice and select **Reprint**, or choose **Save & Print** when billing.
4. On the receipt page, select **58 mm** or **80 mm**, then **Browser print**.
5. In the system dialog, select the printer, matching roll width, 100% scale, zero extra margins and disable browser headers/footers. Driver preferences may override custom page size; select the matching roll media there too.

The receipt page has no application sidebar, uses monochrome text, wraps long names, and measures the receipt for a custom roll page height. Extremely long receipts can still be split by driver limits. Browser printing always uses the system dialog; it is also the fallback when the agent is unavailable. Printing/reprinting never creates another invoice.

## Optional direct ESC/POS agent

Supported transports: **Windows RAW spooler** to a locally installed USB/network printer, or **TCP LAN** (normally port 9100) on Windows/Linux/macOS. The printer must support ESC/POS `GS v 0` raster images. Bluetooth is supported only when its vendor exposes a compatible installed Windows printer; generic BLE/mobile silent printing is not implemented. A normal A4 printer is not necessarily ESC/POS compatible.

The agent runs on the shop PC, never on Render. It polls Billora over outbound HTTPS every two seconds. The browser sends authenticated requests to its own Billora origin; it never contacts the local printer/agent. This is the supported alternative to browser-to-loopback requests that can be blocked by mixed-content / Local Network Access policies. Do not disable browser security or expose a local port to the internet.

Install Python 3.12+ on the printer PC. Copy this repository (or the `printer_bridge` directory) there. In PowerShell from the repository root:

```powershell
py -3 -m venv .printer-venv
.\.printer-venv\Scripts\python.exe -m pip install -r printer_bridge/requirements.txt
.\.printer-venv\Scripts\python.exe printer_bridge/agent.py setup
```

Before running setup, open **Business settings → Thermal printer**, enter a label and 58/80 mm width, and create a pairing code. Setup prompts for:

- Your final Billora frontend origin, e.g. `https://billora-web.onrender.com` (local development: `http://localhost:3000`). No `/api` suffix.
- The one-time code, valid for 10 minutes; paste into the hidden prompt.
- `windows`, `lan`, or `mock` transport.
- Exact Windows printer name from **Printers & scanners**, or local LAN IP/hostname and port.
- Printable dot width: normally 384 for 58 mm and 576 for 80 mm; choose 512 for 80 mm devices that require it.

Then test and run:

```powershell
.\.printer-venv\Scripts\python.exe printer_bridge/agent.py test
.\.printer-venv\Scripts\python.exe printer_bridge/agent.py run
```

The test prints a setup receipt and a harmless example.com QR, not a payment request. Check wrapping, darkness, feed and QR scan quality before live billing. Cutter commands are off by default; set `"cut": true` in local config only if the printer has a compatible cutter. You may set `"font"` to an installed font path for language support. Verify glyph shaping on your hardware, especially non-Latin scripts.

Configuration lives in `%LOCALAPPDATA%\BilloraPrinter\config.json` on Windows (or `~/.config/BilloraPrinter/config.json` elsewhere). Keep it private to the operator's OS account; on shared Windows PCs use file ACLs to deny other accounts access. It contains a revocable device token. No permanent token is placed in frontend JavaScript. The server stores only its SHA-256 digest. **Unpair** in Settings immediately revokes it. Already-spooled hardware jobs cannot be recalled.

The optional local diagnostic service binds **127.0.0.1:8765**. It validates Host/Origin, exposes only `/health`, has no printing/configuration POST endpoint, and supplies no wildcard CORS headers. Choose another loopback port with `--status-port 8766` if occupied. The authenticated job queue, not this diagnostic service, controls printing.

## Status and disconnect recovery

- **Agent online** means its last poll was within 20 seconds; it does not prove the printer has paper.
- **Queued** jobs expire after 30 seconds if not claimed. They will not unexpectedly print when an offline PC reconnects later.
- **Processing** means receipt data was claimed once. A missing acknowledgement after two minutes becomes **uncertain**, with no automatic redelivery.
- **Spooled** means Windows accepted the RAW job or the LAN socket accepted bytes. Physical completion cannot be confirmed universally. Windows error/offline/paper status is checked when the driver provides it; LAN transport provides no paper sensor guarantee.
- **Failed** means delivery was not attempted or was rejected before any bytes could be sent. Fix the connection and request another copy.
- **Uncertain** means a crash/write/acknowledgement failure could have left a receipt in the printer. Check the paper/spool queue first. Then use **Request another copy** only if needed; this creates a new print job, never a new invoice.

The local `jobs.sqlite3` stores only job IDs/status/error text for deduplication, not customers/invoices. Durable intent is written before hardware I/O. After a crash the agent never blindly repeats a started job. Do not delete its ledger while outstanding jobs are being investigated. Network acknowledgements are retried independently of printing.

Use **Browser print** if direct printing is unavailable. If a direct job is processing/uncertain, inspect the paper first to avoid two physical copies. True exactly-once physical printing cannot be guaranteed across arbitrary printer/network failures; Billora reports the ambiguity.

## UPI

Configure UPI ID/payee and **Enable QR by default** in Settings. Each invoice can override **Include UPI QR**. Python `qrcode` encodes the exact unpaid amount and invoice reference. Paid/cancelled invoices and QR-disabled invoices contain no payable QR. ESC/POS prints the QR as a monochrome raster with integer scaling and quiet zones. Scanning/displaying a QR never records payment. Old printed receipts cannot change after a later payment; reprint for the current balance.

## Render deployment and environment

Keep the two Docker web services in `render.yaml`, connected to the existing Neon PostgreSQL database. The bridge does not need a Render worker, disk, inbound local connection, or a new environment secret. Django reuses up to five client connections per process via psycopg-pool to avoid repeated TLS setup during billing. Optional `DB_POOL_ENABLED=false` disables this pool for troubleshooting; no new required ENV is introduced.

1. Push the reviewed repository to your Git host and create/update a Render Blueprint using `render.yaml`.
2. Set backend `DATABASE_URL` to the Neon SSL connection string; set `ALLOWED_HOSTS`, `FRONTEND_URL` and `CSRF_TRUSTED_ORIGINS` to the deployed domains. Keep `DEBUG=false`, `DB_SSL_REQUIRE=true`, and a generated `DJANGO_SECRET_KEY`.
3. Set frontend `BACKEND_URL` to the backend's final HTTPS origin. Keep `BILLING_ENABLED=false` unless a separate subscription integration is implemented.
4. Deploy backend first; its existing Docker entrypoint runs migrations and collectstatic. Deploy/rebuild frontend next. Test login, a synthetic invoice, PDF and both receipt widths.
5. Pair the printer PC using the production **frontend** URL. Keep the agent running during billing. Free Render instances may sleep; allow a cold start before beginning a queue session.

SMTP variables are optional for actual password-reset email delivery; see [DEPLOYMENT.md](DEPLOYMENT.md). Local console email needs no SMTP. No new ENV variables are required for this retail/printing feature.

## References

- [Microsoft: sending RAW data to the Windows spooler](https://learn.microsoft.com/en-us/windows/win32/printdocs/sending-data-directly-to-a-printer)
- [Epson ESC/POS reference](https://download4.epson.biz/sec_pubs/pos/reference_en/escpos/index.html)
- [Chrome Local Network Access restrictions](https://developer.chrome.com/blog/local-network-access)

Physical printer output remains unverified until the operator runs the setup test on the actual device. Automated tests use mock spool/LAN delivery and rendered receipts.
