# Billora Android — implementation and release handoff

This is a native React Native/Expo application, not a website wrapper. It uses the existing Django accounts, business models and Neon connection through authenticated HTTPS APIs. The existing Next.js website remains in `frontend/`.

**Status: offline billing/sync core is implemented. The GitHub Actions workflow below builds an internal testing APK without local Java or Android Studio. Production signing and physical-device acceptance remain separate release requirements. Only a successful workflow upload confirms an APK exists.**

## Download an internal APK from GitHub Actions

Open **Actions → Build Billora APK**, choose **Run workflow → codex/billora**. Changes to mobile files on that branch also trigger it. If GitHub does not show manual dispatch until the workflow is on the default branch, use the automatic push run; the workflow always checks out codex/billora.

Repository **Settings → Secrets and variables → Actions → Variables** must contain **BILLORA_API_URL** with the confirmed public HTTPS Django origin. It is mapped to EXPO_PUBLIC_API_BASE_URL during bundling; no database or Django secrets are passed to the build. Missing/invalid origins fail before compilation.

A successful run uploads **billora-android-test-apk** in its **Artifacts** section. Extract the ZIP and install **billora-internal-test-arm64.apk** on an ARM64 Android phone. It uses the standard Android **debug signing** key but the standalone release variant embeds Hermes/JavaScript and needs no Metro server. This is **INTERNAL TEST ONLY**, not production signing. The package remains **com.billora.app**. The artifact includes its SHA-256 checksum and is retained for 30 days. Do not uninstall an existing app containing unsynced data to resolve a signing mismatch.

The runner uses Node 22, Temurin JDK 17, SDK/build tools 36, NDK 27.1.12297006 and CMake 3.22.1. Prebuild verifies SQLCipher and thermal-printer registration; Gradle compiles the native modules and APK. Compiler errors appear in the job log and the failure artifact.

For production signing later, use the existing EAS **production** profile below with **persistent EAS-managed Android credentials**. Initialize your actual account/project, import an existing package keystore when applicable, and retain the same credentials for all updates. Never generate a new release key per workflow run. Missing EAS credentials do not block the GitHub internal APK.

## Configuration and APK build

Use Node 22 LTS. The lockfile pins Expo SDK 55, React 19.2, React Native 0.83 and their compatible native modules. `expo-doctor` checks compatibility. No Expo Go workflow is supported because the database requires SQLCipher and printing includes a custom native module.

```powershell
cd mobile
npm install
Copy-Item .env.example .env.local
npx expo-doctor
```

The only mobile environment variable is:

```dotenv
EXPO_PUBLIC_API_BASE_URL=https://billora-api-0mml.onrender.com
```

This owner-supplied origin was verified on 18 October 2026: `/api/health/` returned 200 and `/api/mobile/login/` OPTIONS returned the Django Device Login API. This checks endpoint identity, not account activation or database migration completeness. Edit `.env.local` to the actual public **Django origin**, without `/api`, query parameters, credentials or a trailing path. Nothing falls back to a hardcoded URL. The application rejects HTTP in release mode. Never place `DATABASE_URL`, `DJANGO_SECRET_KEY`, signing passwords, admin credentials or private API keys in `EXPO_PUBLIC_*`.

Configure EAS interactively using your own account:

```powershell
npx eas-cli login
npx eas-cli whoami
npx eas-cli init
npx eas-cli env:create --environment preview --name EXPO_PUBLIC_API_BASE_URL --value https://YOUR-CONFIRMED-DJANGO-HOST --visibility plaintext
npx eas-cli build --platform android --profile preview
```

`eas init` links the real project ID; no account, owner or project UUID has been invented. Configure the same variable in EAS's production environment before an AAB build. When asked, let EAS generate/manage the Android signing keystore, or supply your existing keystore if this package has been released before. Export a secure backup using `npx eas-cli credentials --platform android`; retain its passwords outside Git and outside this app. Reuse the same keystore and increment `android.versionCode` for updates.

Only after authentication, project linking, API configuration and signing credentials are ready may a noninteractive build use `--non-interactive`. Preview produces an APK; production produces an AAB:

```powershell
npx eas-cli build --platform android --profile production
```

The EAS command will return the actual build page/download link. Install the downloaded preview APK on an Android phone, enable installation from that trusted source, and run the acceptance checklist below with Metro stopped.

The configured identifier is `com.billora.app`; it matches the generated native package and has no conflicting native app in this repository. Global Play Console availability/ownership cannot be verified without your Play Console account. To change it before the first release, edit `android.package` in `app.json`, then regenerate with `npx expo prebuild --platform android`. The printer module uses a separate Java namespace and continues to register through its config plugin. Changing the application ID after installation creates a separate app/data sandbox.

Optional local build once Android Studio, SDK and JDK 17 are installed:

```powershell
npx expo prebuild --platform android
npx expo run:android
```

For a locally signed release, configure a private Gradle signing configuration, then run `android\gradlew.bat -p android assembleRelease`. Do not distribute the template debug-keystore release as a production build. The intended release path here is EAS managed signing. Generated `android/`, signing files and APKs are ignored by Git; `plugins/withBilloraPrinter.js` reproducibly installs the printer source during prebuild.

## Backend deployment

No new Render service or direct phone-to-PostgreSQL connection is needed. Deploy the updated existing backend after reviewing migration `0010_mobiledevice_mobilenumberrange_mobilechange_and_more.py`:

```sh
cd backend
python manage.py migrate --plan
python manage.py migrate --noinput
```

The migration only adds mobile session/mapping/outbox-audit/feed/number-allocation tables. It does not update users, existing invoices, balances or stock. Tests applied it to isolated databases; this task did not apply it to the live shop database or deploy Render. The existing Docker startup already runs migrations. Existing Django environment variables remain unchanged; no new backend secret is required. Keep HTTPS, an appropriate `ALLOWED_HOSTS`, and the existing session/CSRF settings for the website. Mobile Bearer authentication is restricted to `/api/mobile/*`; it does not replace browser cookie authentication.

Legacy accounts still require a verified `login_mobile` mapping. No new account can authenticate offline. Temporary-password users must change their password on the website before activating a phone. A platform administrator must exist to review conflicts/revoke lost devices; none was silently created.

For local development, use the emulator's `http://10.0.2.2:8000` or your PC's LAN address in a **development** build, bind Django to an appropriate interface and allow that host. Release builds continue to require HTTPS. The tests use mock transport responses plus isolated Django/SQLite/PostgreSQL fixtures; they do not call the Render API.

## Implemented native workflows

- Mobile/password activation; device screen-lock/biometric unlock after activation; foreground/resume lock; token and per-device 256-bit SQLCipher key in SecureStore. Raw passwords are never persisted.
- Cream native navigation: Login, Dashboard, Create Bill, Invoices/detail, Products/edit/stock adjustment, Customers/edit, Customer Collection, Settings and Sync Status.
- Durable SQLite tables for businesses, products, customers, stock, invoice lines, invoices, payments, settings, receipts, outbox, checkpoint, staged pull records, conflicts, ranges and tombstones.
- Product creation, price edits, stock delta events, search/low stock, customer mobile lookup, customer creation and archive operations offline. Previously pending profile changes must sync before another edit to that record.
- Invoice save is an exclusive local transaction: persistent draft UUID deduplication, original receipt, number consumption, outbox event, stock and collection projection. The network is never part of Save.
- Exact paise/milli-quantity arithmetic with BigInt intermediates, per-line half-up GST rounding and largest-remainder discount allocation matching Django. Invoice snapshots keep issued prices; server totals are recomputed, never trusted from the phone.
- Cash full/partial/unpaid sales and subsequent cash payments. The backend protocol also accepts UPI/bank/card methods; richer method selection is not yet exposed in the minimal UI.
- Offline native PDF creation, Android print/share sheets, UPI QR, and WhatsApp selection through Android's share sheet. Delivery needs connectivity. QR generation does not mark anything paid.
- Local UPI ID/payee edits are durable operations and synchronize before bills that depend on them. Store identity/GSTIN configuration remains on the existing website.
- Explicit Sync Now, connectivity/foreground checks and a one-minute active-app sync interval; 75-second connection timeout, persistent bounded exponential retry and no background-execution guarantee.
- Backup JSON export and read-only platform admin mobile event audit. Financial conflicts remain visible for manual reconciliation; an automated financial conflict-resolution or backup-import wizard is **not implemented**.

## Synchronization contract and conflict policy

See [the protocol reference](../docs/ANDROID_SYNC.md) for endpoints and storage guarantees.

| Record/event | Policy |
| --- | --- |
| Product/customer/business settings | Version fingerprint must match. Concurrent edits become explicit conflicts. No last-write-wins. Duplicate customer mobiles require review, not automatic merging. |
| Stock | Idempotent additive adjustment with reason. Sales subtract stock under the existing tenant lock. Negative results are retained with a reconciliation warning. |
| Invoice | Immutable submitted operation retained on the server. Recompute using shared Django arithmetic; reject inconsistent tax/identity/totals into an auditable conflict. Never discard an offline sale or overwrite another invoice. |
| Payment | Existing payment service, immutable operation UUID, exact balance validation; replay does not collect twice. Overpayment/cancelled-sale conflicts remain visible. |
| Deletion | Archive native product/customer rows, preserve financial relations/snapshots. Web hard deletions appear as tombstones. |
| Refund | Existing backend full cancellation/refund flow downloads the cancelled invoice and refunded-payment state. Collections exclude cancelled sales and refunded receipts. Mobile refund initiation is not included. |

Collections derive from invoice totals and paid amounts, including local pending bills, rather than incrementing a counter. Accepted operations remain overlaid until an entire paginated download commits. Interrupted pulls are staged separately, so local billing during a partial download cannot double-decrement stock. Cursor and staged data persist across restarts.

The feed fingerprints existing tenant records, including website bulk imports/stock changes, under the same business lock. It sends incremental journal pages but still scans the tenant's current records. This is a compatibility-first implementation for small shops, not database CDC. Large histories need measured pagination/CDC work before rollout. The journal and original operation records currently have no retention pruning; do not delete them casually because they provide idempotency/audit history.

## Offline numbering and GST limits

Settings reserves 100 numbers online for the current Indian financial year. Allocation consumes a nonoverlapping portion of `Business.next_invoice_number` under the same row lock as website invoicing. Range requests themselves are UUID-idempotent. Mobile numbers use `MYY-NNNNNNNNNN` (14 characters); year, device ownership and range membership are validated server-side, and existing invoice uniqueness constraints remain in force. Previously issued numbers never change during sync. Ranges are never recycled after logout, reinstall or device loss.

If a range is missing/exhausted/outside the financial year, the original PDF says **PROVISIONAL BILL — NOT A TAX INVOICE** and uses a UUID device reference. Sync assigns a number to a separate finalized representation; the original provisional copy remains available. Do not present the provisional document as a final GST invoice.

[CBIC Rule 46](https://taxinformation.cbic.gov.in/content-page/explore-rules/1000136/1000001) requires a consecutive serial number, at most 16 characters, unique within the financial year, and other prescribed particulars. The mobile series fits the character/length/year constraint, but statutory timing, gaps/voided reserved numbers, invoice particulars, signatures, e-invoicing applicability and the existing website prefix policy require an accountant's review. This implementation is **not certified production GST compliance**.

## Printing support and limitations

The custom Android adapter supports generic ESC/POS over paired **Bluetooth Classic SPP**, **LAN TCP port 9100**, or **USB OTG bulk OUT**. Open **Printer setup** from the dashboard or an invoice (also available in Settings). Bluetooth is selected by default. Android 12+ requests Nearby Devices/Bluetooth Connect permission; USB permission is granted by Android. BLE-only/proprietary printers are not assumed compatible. Generic text receipts use ASCII (`Rs`); use PDF/system printing for Hindi or other Unicode scripts. ESC/POS QR commands require compatible firmware; raster QR printing is not implemented.

Bluetooth setup on the installed native APK:

1. Turn on the thermal printer. Tap **Pair printer / turn on Bluetooth** and pair using Android settings (use the printer manufacturer’s PIN if prompted).
2. Return to Billora and unlock. The app restores the printer page in memory. Tap **Refresh printer list** and allow **Nearby devices**. If permission was permanently denied, use **Android app permissions**.
3. Tap the printer’s name in the paired-device list. Choose **58 mm** or **80 mm**, then **Connect & save printer**. The app opens a bounded SPP connection to verify reachability and saves the printer for this shop on this phone. It closes that test connection and reconnects for each receipt; the UI does not claim a permanent live connection.
4. Tap **Print test receipt** and check the paper. Create/save an invoice, or open an existing invoice, then tap **Print thermal receipt**. Use **Printer setup / Bluetooth** on that screen to change the printer. No internet connection is needed for printing saved invoices.
5. **Forget saved printer** removes the app selection without unpairing it from Android. Bluetooth-off, unavailable adapter, unpaired devices and failed connections report actionable errors. Close Android device discovery and disconnect another phone if it is already using the printer.

This native-module change requires a new EAS APK build and install; refreshing Metro/Expo Go or localhost does not add Android Bluetooth support. No new environment variables or backend changes are required. Pairing uses the Android system UI; the app lists bonded devices and does not request location or Bluetooth scanning permissions. The connection code follows [Android BluetoothSocket APIs](https://developer.android.com/reference/android/bluetooth/BluetoothSocket).

Print attempts are recorded locally before sending bytes. A repeat asks for explicit reprint; no automatic transport retries occur. A successful write means bytes were sent, not that paper was printed. Check the device after an uncertain result. Reprinting cannot create another invoice. No request is sent to Render to reach a local printer.

Bluetooth, LAN and USB paths are source/prebuild validated only; physical hardware, PDF rendering on Android, permission prompts and native Kotlin compilation remain unverified. Use Android's print service fallback where appropriate.

## Device data and recovery

SQLCipher is enabled by the config plugin and checked at runtime; the app refuses unencrypted SQLite/Expo Go. SQL is parameterized except fixed schema statements and a validated hexadecimal cipher key. SQLite uses WAL and versioned, transactional initialization; newer unsupported schemas fail closed rather than being wiped. Per-device databases and explicit business metadata prevent cross-shop reuse. Android automatic backup is disabled; SecureStore keys are excluded from transferable backups.

Device unlock is required and screenshots are blocked. This does not protect a rooted/unlocked compromised OS or a user who exports plaintext backups. Exported JSON contains customer data and should be stored privately; temporary share files are removed after sharing returns. A lost device cannot learn about revocation while completely offline. Sessions expire after 30 days; password changes, account/business suspension, admin revocation and token expiry block the next online request. Pending data is retained when authorization fails.

Logout requires a successful online revocation and no pending/conflicted operations, then removes the database and its key. Lock is always available without losing records. Uninstalling, clearing app storage or losing the keystore can destroy unsynced data. Do not claim offline data is already backed up to Neon. Restore/export reconciliation is currently an administrator-assisted process; do not copy a backup onto a second active phone, which could reuse reserved numbers.

## Testing evidence and remaining release gates

Executed locally:

- Mobile tests: 18 passed, including six printer regressions covering paper widths, ESC/POS encoding/QR amount, control-character sanitization, printer validation, failed/repeated prints, concurrent taps and cancellation before sending. Native-core tests use real SQLite through Node's SQLite driver, covering money, offline save, repeated taps, transactional failure, restart, tenant binding, number exhaustion, CRUD, staged/interrupted pulls, tombstones, retry/revocation, mocked sync, PDF HTML escaping, offline QR and UPI settings.
- Django suite: 127 discovered; 116 passed, 11 PostgreSQL-only skips in SQLite mode.
- After final settings/pagination/admin changes: focused Django suite 36 discovered; 32 passed, 4 PostgreSQL-only skips. This includes the additional paginated-feed/settings test.
- Disposable Neon PostgreSQL: 4 tests passed, covering concurrent duplicate sync, concurrent range reservation, simultaneous offline overselling and invoice replay/stock/payment correctness. Test database destroyed; existing shop records untouched.
- Website: production build and 19 Vitest tests passed.
- Mobile: TypeScript passed; Expo Doctor 20/20 passed; Android prebuild generated SQLCipher configuration, manifest and native printer registration; Metro/Hermes Android export succeeded. These are **not APK installation tests**.
- `makemigrations --check --dry-run`: no model drift. Added migration is additive.

`npm audit` reports upstream Expo/React Native build-tool advisories (33 findings at first audit, including unpatched braces/node-forge/sprintf-js chains). Its suggested forced fixes downgrade Expo or change React Native outside the SDK compatibility set. Those were not blindly applied. Review current upstream patches before a production release; this source is an internal-validation build candidate.

Still required: EAS account/project/signing setup; confirmed deployed HTTPS backend with migration; actual release APK compilation; emulator/physical-device launch without Metro; offline activation/unlock, app background/resume and keystore-loss checks; real Android SQLCipher/PDF/share/QR rendering; physical printer tests; device-to-Render cold-start/network switching; website verification of a phone-created invoice; Android install/update preserving pending data; accountant numbering/GST review and final dependency review.

Use a dedicated test shop for the 27 acceptance scenarios in the original request. Do not conduct destructive verification on existing customers or live stock. Stop rollout on any mismatch between an original receipt, server total or collection balance.

Reproduce automated checks:

```powershell
cd mobile
npm ci
npm test
npm run typecheck
npx expo-doctor
npx expo prebuild --platform android --no-install
npx expo export --platform android
```

Reference documentation: [Expo SDK 55 SQLite/SQLCipher](https://docs.expo.dev/versions/v55.0.0/sdk/sqlite/), [native print/PDF](https://docs.expo.dev/versions/v55.0.0/sdk/print/), [device authentication](https://docs.expo.dev/versions/v55.0.0/sdk/local-authentication/), [local Android builds](https://docs.expo.dev/guides/local-app-overview/).
