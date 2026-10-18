import {SCHEMA, TABLES, Kind} from './schema';
import {calculate, decimal, indiaDate, Line, normalizeMobile, scaled} from './money';

// Small SQL boundary shared by expo-sqlite and the real-SQLite integration tests.
export interface SQL {
  execAsync(sql: string): Promise<void>;
  runAsync(sql: string, ...args: any[]): Promise<any>;
  getFirstAsync<T = any>(sql: string, ...args: any[]): Promise<T | null>;
  getAllAsync<T = any>(sql: string, ...args: any[]): Promise<T[]>;
}
export interface Database extends SQL {withExclusiveTransactionAsync(task: (tx: SQL) => Promise<void>): Promise<void>; closeAsync?(): Promise<void>}
export type RecordData = {[key: string]: any; id: string; version?: string};
export type Operation = {id: string; kind: string; record_id: string; base_version?: string; data: any};
export type Outbox = {seq: number; id: string; payload: string; status: string; attempts: number; retry_at: number; record_id: string; kind: string};
export type Change = {kind: Kind; id: string; version: string; data: any | null};

export class Store {
  private tail: Promise<any> = Promise.resolve();
  role = 'viewer';
  constructor(public db: Database, public business: string, public uuid: () => string) {}
  async transaction<T>(task: (tx: SQL) => Promise<T>): Promise<T> {
    const execute = async () => {let value!: T; await this.db.withExclusiveTransactionAsync(async tx => {value = await task(tx);}); return value;};
    const result = this.tail.then(execute); this.tail = result.catch(() => {}); return result;
  }
  async init() {
    await this.db.execAsync('PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;');
    await this.transaction(async tx => {
      const version = await tx.getFirstAsync<{user_version: number}>('PRAGMA user_version');
      if ((version?.user_version ?? 0) > 1) throw new Error('This database needs a newer Billora app. No data was changed.');
      await tx.execAsync(SCHEMA);
      const owner = await tx.getFirstAsync<{value: string}>('SELECT value FROM metadata WHERE key=?', 'business');
      if (owner && owner.value !== this.business) throw new Error('This database belongs to another shop.');
      await tx.runAsync('INSERT OR IGNORE INTO metadata(key,value) VALUES(?,?)', 'business', this.business);
      await tx.runAsync('INSERT OR IGNORE INTO sync_checkpoints(business) VALUES(?)', this.business);
      await tx.execAsync('PRAGMA user_version=1;');
    });
  }
  async list(kind: Kind, tx: SQL = this.db): Promise<RecordData[]> {
    const rows = await tx.getAllAsync<{body: string; version: string}>(`SELECT body,version FROM ${TABLES[kind]} WHERE business=?`, this.business);
    return rows.map(r => ({...JSON.parse(r.body), version: r.version}));
  }
  async get(kind: Kind, id: string, tx: SQL = this.db): Promise<RecordData> {
    const row = await tx.getFirstAsync<{body: string; version: string}>(`SELECT body,version FROM ${TABLES[kind]} WHERE business=? AND id=?`, this.business, id);
    if (!row) throw new Error('Record unavailable on this device. Sync first.');
    return {...JSON.parse(row.body), version: row.version};
  }
  private authorize(kind: string) {
    if (this.role === 'viewer' || (kind.startsWith('business.') || kind.startsWith('product.') || kind.startsWith('stock.') || kind.endsWith('.delete')) && !['owner', 'manager'].includes(this.role)) throw new Error('Your role does not allow this change.');
  }
  async enqueue(kind: string, id: string, data: any, base = '') {
    this.authorize(kind);
    return this.transaction(async tx => {
      // One pending profile edit at a time avoids inventing versions for unsynced edits.
      const pending = await tx.getFirstAsync('SELECT id FROM sync_outbox WHERE business=? AND record_id=? AND status!=? AND kind NOT IN (?,?)', this.business, id, 'synced', 'stock.adjust', 'invoice.create');
      if (pending && !['stock.adjust','payment.create'].includes(kind)) throw new Error('Sync this record’s previous change first.');
      if (kind.startsWith('customer.') && data.mobile) data.mobile = normalizeMobile(data.mobile);
      if (kind === 'customer.create' || kind === 'customer.update') {
        const customers = await this.list('customer', tx);
        if (!String(data.name || '').trim()) throw new Error('Customer name required.');
        if (customers.some(c => c.id !== id && c.is_active !== false && c.mobile === data.mobile)) throw new Error('This mobile already belongs to a customer.');
      }
      if (kind === 'product.create' || kind === 'product.update') {
        if (!String(data.name || '').trim() || !String(data.sku || '').trim()) throw new Error('Product name and SKU required.');
        if (scaled(data.selling_price) < 0 || scaled(data.gst_rate || '0') < 0 || scaled(data.gst_rate || '0') > 10000) throw new Error('Invalid price or GST.');
        if (kind === 'product.create' && scaled(data.stock || '0', 3) < 0) throw new Error('Opening stock cannot be negative.');
        const products = await this.list('product', tx);
        if (products.some(p => p.id !== id && p.sku === data.sku)) throw new Error('SKU already exists.');
      }
      if (kind === 'stock.adjust' && (!scaled(data.delta, 3) || !String(data.reason).trim())) throw new Error('Enter a nonzero adjustment and reason.');
      if (kind === 'business.settings' && data.upi_id && !/^[A-Za-z0-9._-]{2,100}@[A-Za-z0-9.-]{2,30}$/.test(data.upi_id)) throw new Error('Enter a valid UPI ID.');
      const op: Operation = {id: this.uuid(), kind, record_id: id, base_version: base, data};
      await this.insertOp(tx, op); await this.rebuild(tx); return op;
    });
  }
  private async insertOp(tx: SQL, op: Operation) {
    await tx.runAsync('INSERT INTO sync_outbox(business,id,record_id,kind,payload,created_at) VALUES(?,?,?,?,?,?)',
      this.business, op.id, op.record_id, op.kind, JSON.stringify(op), new Date().toISOString());
  }
  async saveBill(input: {id: string; customer: string; items: Line[]; discount: string; gst: boolean; paid: string; includeQR: boolean; payment_method: string}) {
    this.authorize('invoice.create');
    return this.transaction(async tx => {
      const old = await tx.getFirstAsync<{body: string}>('SELECT body FROM original_receipts WHERE business=? AND id=?', this.business, input.id);
      if (old) return JSON.parse(old.body); // repeated tap / retry uses the persisted draft UUID.
      const customer = await this.get('customer', input.customer, tx), business = await this.get('business', this.business, tx);
      if (customer.is_active === false || customer.sync_status === 'conflict') throw new Error('Choose an active customer without unresolved sync issues.');
      if (input.gst && !business.gstin) throw new Error('Configure GSTIN on the website and sync first.');
      const items: Line[] = [];
      for (const item of input.items) {
        const p = await this.get('product', item.product, tx);
        if (p.is_active === false || p.selling_price == null || p.sync_status === 'conflict') throw new Error('Product is unavailable or has an unresolved sync issue.');
        if (input.gst && p.gst_rate == null) throw new Error('Verify the product GST rate first.');
        if (!business.settings.allow_negative_stock && scaled(p.stock, 3) < scaled(item.quantity, 3)) throw new Error(`Insufficient stock for ${p.name}.`);
        items.push({...item, unit_price: item.unit_price, gst_rate: p.gst_rate || '0', price_includes_tax: p.price_includes_tax || false, description: p.name, sku: p.sku, unit: p.unit, hsn_code: p.hsn_code || ''});
      }
      const supply = customer.state_code || business.state_code;
      const {totals, lines} = calculate(items, input.discount, input.gst, supply !== business.state_code);
      const paid = input.paid === 'full' ? totals.total : scaled(input.paid);
      if (paid < 0 || paid > totals.total || paid > 999999999999) throw new Error('Payment must be between zero and the total within the supported limit.');
      const date = indiaDate(), year = Number(date.slice(0, 4)), fiscal = Number(date.slice(5, 7)) >= 4 ? year : year - 1;
      const range = await tx.getFirstAsync<{id: string; next_number: number}>('SELECT id,next_number FROM number_ranges WHERE business=? AND fiscal_year=? AND next_number<=end_number ORDER BY next_number LIMIT 1', this.business, fiscal);
      const number = range ? `M${String(fiscal % 100).padStart(2, '0')}-${String(range.next_number).padStart(10, '0')}` : '';
      if (range) await tx.runAsync('UPDATE number_ranges SET next_number=next_number+1 WHERE business=? AND id=?', this.business, range.id);
      const bs = Object.fromEntries(['name','address','gstin','mobile','state_code'].map(k => [k, business[k] || '']));
      for (const key of ['upi_id','upi_payee_name','invoice_footer']) bs[key] = business.settings[key] || '';
      if (input.includeQR && (!bs.upi_id || !bs.upi_payee_name)) throw new Error('Configure UPI settings on the website and sync first.');
      const cs = Object.fromEntries(['name','mobile','whatsapp','address','gstin'].map(k => [k, customer[k] || '']));
      const data = {id: input.id, customer: input.customer, items, number, date, supply_state: supply,
        gst_enabled: input.gst, discount: decimal(totals.discount), paid_amount: decimal(paid), payment_method: input.payment_method,
        include_upi_qr: input.includeQR, expected_total: decimal(totals.total), customer_snapshot: cs, business_snapshot: bs};
      const receipt = {...data, ...Object.fromEntries(Object.entries(totals).map(([k, v]) => [k, decimal(v)])),
        items: lines.map(l => ({...l, ...Object.fromEntries(['subtotal','discount','cgst','sgst','igst','total'].map(k => [k, decimal((l as any)[k])]))})),
        provisional: !number, device_reference: input.id, cancelled_at: null, sync_status: 'pending'};
      await tx.runAsync('INSERT INTO original_receipts(business,id,body) VALUES(?,?,?)', this.business, input.id, JSON.stringify(receipt));
      await this.insertOp(tx, {id: input.id, record_id: input.id, kind: 'invoice.create', data});
      await this.rebuild(tx); return receipt;
    });
  }
  async pay(invoiceId: string, amount: string, method: string) {
    this.authorize('payment.create');
    return this.transaction(async tx => {
      const invoice = await this.get('invoice', invoiceId, tx), value = scaled(amount);
      if (invoice.cancelled_at || value <= 0 || value > scaled(invoice.total) - scaled(invoice.paid_amount)) throw new Error('Payment exceeds the outstanding balance.');
      const op = {id: this.uuid(), record_id: this.uuid(), kind: 'payment.create', data: {invoice: invoiceId, amount, method}};
      await this.insertOp(tx, op); await this.rebuild(tx);
    });
  }
  async rebuild(tx: SQL) {
    // Derived tables are rebuilt atomically; source snapshots, receipts and outbox are never erased.
    const entities = new Map<string, RecordData>();
    const rows = await tx.getAllAsync<{kind: Kind; id: string; version: string; body: string | null}>('SELECT * FROM server_records WHERE business=?', this.business);
    for (const row of rows) if (row.body) entities.set(`${row.kind}:${row.id}`, {...JSON.parse(row.body), version: row.version});
    const ops = await tx.getAllAsync<Outbox>('SELECT * FROM sync_outbox WHERE business=? AND status!=? ORDER BY seq', this.business, 'synced');
    for (const row of ops) {
      const op: Operation = JSON.parse(row.payload), [kind, action] = op.kind.split('.'), key = `${kind}:${op.record_id}`;
      if (kind === 'business') {
        const business = entities.get(key);
        if (business) business.settings = {...business.settings, ...op.data};
      } else if (kind === 'product' || kind === 'customer') {
        const old = entities.get(key) || {id: op.record_id};
        entities.set(key, {...old, ...op.data, is_active: action !== 'delete', sync_status: row.status});
      } else if (kind === 'stock') {
        const product = entities.get(`product:${op.record_id}`);
        if (product) {product.stock = decimal(scaled(product.stock || '0', 3) + scaled(op.data.delta, 3), 3); if (row.status === 'conflict') product.sync_status = 'conflict';}
      } else if (kind === 'invoice') {
        const original = await tx.getFirstAsync<{body: string}>('SELECT body FROM original_receipts WHERE business=? AND id=?', this.business, op.record_id);
        if (original) entities.set(key, {...JSON.parse(original.body), sync_status: row.status});
        if (scaled(op.data.paid_amount) > 0) entities.set(`payment:${op.record_id}`, {id:op.record_id, invoice:op.record_id, amount:op.data.paid_amount, method:op.data.payment_method, sync_status:row.status});
        // Accepted events are removed from this overlay only when a complete pull commits.
        for (const item of op.data.items) {
          const product = entities.get(`product:${item.product}`);
          if (product) product.stock = decimal(scaled(product.stock || '0', 3) - scaled(item.quantity, 3), 3);
        }
      } else if (kind === 'payment') {
        entities.set(key, {id: op.record_id, ...op.data, sync_status: row.status});
        const invoice = entities.get(`invoice:${op.data.invoice}`);
        if (invoice) invoice.paid_amount = decimal(scaled(invoice.paid_amount) + scaled(op.data.amount));
      }
    }
    for (const table of Object.values(TABLES)) await tx.runAsync(`DELETE FROM ${table} WHERE business=?`, this.business);
    await tx.runAsync('DELETE FROM stock_balances WHERE business=?', this.business);
    await tx.runAsync('DELETE FROM invoice_items WHERE business=?', this.business);
    for (const [key, entity] of entities) {
      const kind = key.split(':')[0] as Kind;
      if (kind === 'invoice') {entity.total_paise = scaled(entity.total); entity.paid_paise = scaled(entity.paid_amount);}
      await tx.runAsync(`INSERT INTO ${TABLES[kind]}(business,id,body,version) VALUES(?,?,?,?)`, this.business, entity.id, JSON.stringify(entity), entity.version || '');
      if (kind === 'product') await tx.runAsync('INSERT INTO stock_balances VALUES(?,?,?)', this.business, entity.id, scaled(entity.stock || '0', 3));
      if (kind === 'invoice') for (const [index, item] of (entity.items || []).entries()) await tx.runAsync('INSERT INTO invoice_items VALUES(?,?,?,?)', this.business, entity.id, index, JSON.stringify(item));
    }
  }
  async pending() {return this.db.getAllAsync<Outbox>('SELECT * FROM sync_outbox WHERE business=? AND status=? ORDER BY seq', this.business, 'pending');}
  async acknowledge(id: string, result: {status: string; detail?: string; warning?: string}) {
    await this.transaction(async tx => {
      await tx.runAsync('UPDATE sync_outbox SET status=?,result=? WHERE business=? AND id=?', result.status, JSON.stringify(result), this.business, id);
      if (result.status === 'conflict' || result.warning) await tx.runAsync('INSERT OR REPLACE INTO sync_conflicts(business,id,detail) VALUES(?,?,?)', this.business, id, result.detail || result.warning || 'Review required.');
    });
  }
  async pullPage(changes: Change[], cursor: string, final: boolean) {
    await this.transaction(async tx => {
      for (const c of changes) {
        if (!TABLES[c.kind]) throw new Error('Server returned an unsupported record type.');
        await tx.runAsync('INSERT OR REPLACE INTO sync_incoming(business,kind,id,version,body) VALUES(?,?,?,?,?)', this.business, c.kind, c.id, c.version, c.data ? JSON.stringify(c.data) : null);
        if (!c.data) await tx.runAsync('INSERT OR REPLACE INTO tombstones VALUES(?,?,?,?)', this.business, c.kind, c.id, c.version);
      }
      await tx.runAsync('UPDATE sync_checkpoints SET cursor=? WHERE business=?', cursor, this.business);
      if (final) {
        await tx.runAsync('INSERT OR REPLACE INTO server_records SELECT * FROM sync_incoming WHERE business=?', this.business);
        await tx.runAsync('DELETE FROM sync_incoming WHERE business=?', this.business);
        await tx.runAsync('UPDATE sync_outbox SET status=? WHERE business=? AND status=?', 'synced', this.business, 'accepted');
        await tx.runAsync('UPDATE sync_checkpoints SET completed_at=? WHERE business=?', new Date().toISOString(), this.business);
        await this.rebuild(tx);
      }
    });
  }
  async retryLater(row: Outbox) {
    const delay = Math.min(300000, 2000 * 2 ** Math.min(row.attempts, 7));
    await this.transaction(tx => tx.runAsync('UPDATE sync_outbox SET attempts=attempts+1,retry_at=? WHERE business=? AND id=?', Date.now() + delay, this.business, row.id));
  }
  async addRange(range: {id: string; fiscal_year: number; start: number; end: number}) {
    await this.transaction(tx => tx.runAsync('INSERT OR IGNORE INTO number_ranges VALUES(?,?,?,?,?)', this.business, range.id, range.fiscal_year, range.start, range.end));
  }
  async status() {
    return {pending: await this.db.getFirstAsync<{n: number}>('SELECT COUNT(*) n FROM sync_outbox WHERE business=? AND status!=?', this.business, 'synced'),
      invoices: await this.db.getFirstAsync<{n: number}>('SELECT COUNT(*) n FROM sync_outbox WHERE business=? AND kind=? AND status!=?', this.business, 'invoice.create', 'synced'),
      checkpoint: await this.db.getFirstAsync<{cursor: string; completed_at: string | null}>('SELECT * FROM sync_checkpoints WHERE business=?', this.business),
      conflicts: await this.db.getAllAsync<{id: string; detail: string}>('SELECT id,detail FROM sync_conflicts WHERE business=? AND resolved=0', this.business)};
  }
  async exportData() {
    return this.transaction(async tx => {
      const out: any = {format: 'billora-device-backup-v1', business: this.business, exported_at: new Date().toISOString()};
      for (const table of ['server_records','sync_incoming','sync_outbox','sync_checkpoints','sync_conflicts','original_receipts','number_ranges','tombstones','app_settings']) out[table] = await tx.getAllAsync(`SELECT * FROM ${table} WHERE business=?`, this.business);
      return JSON.stringify(out, null, 2);
    });
  }
}
