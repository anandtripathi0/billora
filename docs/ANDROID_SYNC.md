# Native sync protocol v1

Repository audit confirmed Django session authentication, tenant memberships, exact-decimal invoice arithmetic, atomic tenant-first locks, protected financial foreign keys, payment idempotency, full cancellation/refunds, immutable snapshots, manual WhatsApp links, ReportLab PDF and the optional Python ESC/POS bridge. `render.yaml` remains two web services. Missing capabilities were native device credentials, durable operation replay/audit, mobile UUID mappings, offline number reservations and a pull cursor; those are added without changing browser APIs.

## Endpoints

All paths have trailing slashes. Mobile authentication is `Authorization: Bearer <opaque-token>`; do not send browser cookies.

| Endpoint | Request/result |
| --- | --- |
| `POST /api/mobile/login/` | `mobile`, `password`, optional `device_id` for reactivation and `name`. Returns one 30-day opaque token, device ID, user ID, tenant business/settings and role. Password-reset-required accounts must first use the website. Rate limited. |
| `GET /api/mobile/devices/` | Only devices owned by the authenticated user in the same tenant. |
| `POST /api/mobile/devices/` | Revoke own `device_id` (defaults to current device). Admin revocation is also available in Django Admin. |
| `GET /api/mobile/pull/?cursor=...` | Up to 200 journal changes `{kind,id,version,data}`; `data:null` is a tombstone. Returns signed tenant-bound cursor, `has_more`, current role. |
| `POST /api/mobile/push/` | One immutable operation `{id,kind,record_id,base_version?,data}`. Returns `status:accepted` or `status:conflict`, optional detail/warning/number. Exact replay returns original response; altered reuse of UUID returns HTTP 409. |
| `GET /api/mobile/ranges/` | Current device's reservations. |
| `POST /api/mobile/ranges/` | `{id: allocation-request-UUID}`; reserves 100 numbers atomically or returns the same reservation on retry. |

Operations: `business.settings`, `product.create/update/delete`, `customer.create/update/delete`, `stock.adjust`, `invoice.create`, `payment.create`. Server roles are enforced independently of the device UI. Business comes exclusively from the authenticated membership/device, never a submitted tenant ID. Reactivation cannot attach another account to an existing device database.

Products/customers retain existing integer database PKs; `MobileMapping` supplies tenant-scoped UUID identities. Legacy records receive deterministic UUIDv5 mappings. New mobile records retain their client UUID mapping. Invoice PKs remain UUIDs. Mappings for deleted records remain for tombstone/dependency diagnostics.

## Transaction and replay guarantees

1. The phone commits domain changes, original receipt, number consumption and serialized outbox payload together. UUIDs survive restarts. Money uses integer paise; quantity uses thousandths.
2. Server push locks the tenant row, checks immutable operation UUID/hash, then executes the existing domain validations/services in a nested transaction.
3. Successful writes and their durable operation receipt commit together. Validation failure rolls back all domain writes and stores an immutable conflict receipt with the original event. An unexpected exception rolls everything back so retry remains possible.
4. The original operation payload includes the issued document's snapshots. Server invoice totals are recalculated by `calculate_lines`. Changed tax/description/business/customer identity, invalid allocation and inconsistent totals become conflicts; concurrent stock exhaustion is accepted with a reconciliation warning rather than losing the sale.
5. Incremental pulls materialize differences from authoritative existing tables. Per-tenant serialization ensures journal order and version changes commit together, including web `bulk_update` and hard deletes. New/changed rows are batched; this still scans full tenant state and needs scaling work for large histories.
6. Phone downloads go to `sync_incoming` with a durable cursor. Only the last page atomically publishes the staged server state, removes accepted overlays and recomputes local projections. Conflict/pending operations remain. No partial download replaces live projected stock.
7. One sync engine per store runs at a time; local billing can proceed while fetch waits. If authorization fails, lock the app and retain the database. Backoff state survives process restarts. Never clear an outbox on a timeout.

Original local receipts are immutable; finalized server representations can show subsequent payments or cancellations. For provisional bills, preserve the original provisional copy when the server assigns the final number. Server event records are read-only in Django Admin. Financial conflict resolution must be explicit and audited; a self-service repair wizard is outside this slice.

## Security and operational limits

Tokens are random 384-bit values; only SHA-256 digests are stored server-side. Devices are bound to a user, business and Django password-session stamp. Password changes, suspension and revoked/expired sessions fail authentication. The mobile token is valid only on mobile endpoints; website CSRF behavior is unchanged. SQLite is SQLCipher-encrypted with a random key in Android-backed SecureStore; device lock gates access. HTTPS is mandatory in release builds.

No public refresh-token endpoint is implemented: after 30 days the owner signs in online again using the same device identity. Offline revocation cannot be instantaneous. Local backups are explicit plaintext exports, not automatic cloud backups, and currently require administrator-assisted recovery.

Number allocation increments the same existing counter as web invoicing; device/date/range checks plus unique invoice constraints prevent collision. Never reclaim unused ranges automatically. Mobile numbering is 14 characters, but wider GST compliance and existing website prefix policy need review before production. See the [mobile release guide](../mobile/README.md).
