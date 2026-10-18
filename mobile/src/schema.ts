export const SCHEMA = `
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS server_records (
 business TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL, version TEXT NOT NULL, body TEXT,
 PRIMARY KEY(business,kind,id));
CREATE TABLE IF NOT EXISTS sync_incoming (
 business TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL, version TEXT NOT NULL, body TEXT,
 PRIMARY KEY(business,kind,id));
CREATE TABLE IF NOT EXISTS businesses (business TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL, version TEXT NOT NULL DEFAULT '', PRIMARY KEY(business,id));
CREATE TABLE IF NOT EXISTS products (business TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL, version TEXT NOT NULL DEFAULT '', PRIMARY KEY(business,id));
CREATE TABLE IF NOT EXISTS customers (business TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL, version TEXT NOT NULL DEFAULT '', PRIMARY KEY(business,id));
CREATE TABLE IF NOT EXISTS invoices (business TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL, version TEXT NOT NULL DEFAULT '', PRIMARY KEY(business,id));
CREATE TABLE IF NOT EXISTS payments (business TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL, version TEXT NOT NULL DEFAULT '', PRIMARY KEY(business,id));
CREATE TABLE IF NOT EXISTS invoice_items (business TEXT NOT NULL, invoice_id TEXT NOT NULL, line_no INTEGER NOT NULL, body TEXT NOT NULL, PRIMARY KEY(business,invoice_id,line_no));
CREATE TABLE IF NOT EXISTS stock_balances (business TEXT NOT NULL, product_id TEXT NOT NULL, quantity_milli INTEGER NOT NULL, PRIMARY KEY(business,product_id));
CREATE TABLE IF NOT EXISTS app_settings (business TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(business,key));
CREATE TABLE IF NOT EXISTS sync_outbox (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, business TEXT NOT NULL, id TEXT NOT NULL UNIQUE, record_id TEXT NOT NULL, kind TEXT NOT NULL,
 payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
 retry_at INTEGER NOT NULL DEFAULT 0, result TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS outbox_pending ON sync_outbox(business,status,seq);
CREATE INDEX IF NOT EXISTS outbox_record ON sync_outbox(business,record_id,status);
CREATE TABLE IF NOT EXISTS sync_checkpoints (business TEXT PRIMARY KEY, cursor TEXT NOT NULL DEFAULT '', completed_at TEXT);
CREATE TABLE IF NOT EXISTS sync_conflicts (business TEXT NOT NULL, id TEXT NOT NULL, detail TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(business,id));
CREATE TABLE IF NOT EXISTS tombstones (business TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL, version TEXT NOT NULL, PRIMARY KEY(business,kind,id));
CREATE TABLE IF NOT EXISTS original_receipts (business TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(business,id));
CREATE TABLE IF NOT EXISTS number_ranges (business TEXT NOT NULL, id TEXT NOT NULL, fiscal_year INTEGER NOT NULL, next_number INTEGER NOT NULL, end_number INTEGER NOT NULL, PRIMARY KEY(business,id));
CREATE VIEW IF NOT EXISTS customer_collection AS
 SELECT business, json_extract(body,'$.customer') AS customer_id,
 COUNT(*) AS orders,
 SUM(json_extract(body,'$.total_paise')) AS total_paise,
 SUM(json_extract(body,'$.paid_paise')) AS paid_paise
 FROM invoices WHERE json_extract(body,'$.cancelled_at') IS NULL GROUP BY business,customer_id;
`;
export const TABLES = {business: 'businesses', product: 'products', customer: 'customers', invoice: 'invoices', payment: 'payments'} as const;
export type Kind = keyof typeof TABLES;
