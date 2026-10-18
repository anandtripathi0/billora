import {test} from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {randomUUID} from 'node:crypto';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {Store, Database, SQL, Change} from '../src/store';
import {calculate, decimal, indiaDate, normalizeMobile, scaled} from '../src/money';
import {SyncEngine} from '../src/sync';
import {SessionExpired} from '../src/api';
import {invoiceHTML, upiURI, qrData} from '../src/receipt';

class TestDB implements Database {
  connection: DatabaseSync;
  constructor(path=':memory:'){this.connection=new DatabaseSync(path);}
  async execAsync(sql:string){this.connection.exec(sql);}
  async runAsync(sql:string,...args:any[]){return this.connection.prepare(sql).run(...args);}
  async getFirstAsync<T=any>(sql:string,...args:any[]):Promise<T|null>{return this.connection.prepare(sql).get(...args) as T||null;}
  async getAllAsync<T=any>(sql:string,...args:any[]):Promise<T[]>{return this.connection.prepare(sql).all(...args) as T[];}
  async withExclusiveTransactionAsync(task:(tx:SQL)=>Promise<void>){this.connection.exec('BEGIN IMMEDIATE');try{await task(this);this.connection.exec('COMMIT');}catch(e){this.connection.exec('ROLLBACK');throw e;}}
  close(){this.connection.close();}
}
const business=randomUUID(),pid=randomUUID(),cid=randomUUID();
const initial:Change[]=[
  {kind:'business',id:business,version:'b1',data:{id:business,name:'Test Store',state_code:'27',gstin:'27ABCDE1234F1Z5',settings:{allow_negative_stock:false,upi_id:'test@upi',upi_payee_name:'Test Store'}}},
  {kind:'product',id:pid,version:'p1',data:{id:pid,name:'Rice',sku:'R1',selling_price:'100.00',stock:'20.000',gst_rate:'18.00',price_includes_tax:false,unit:'kg',is_active:true}},
  {kind:'customer',id:cid,version:'c1',data:{id:cid,name:'Rahul',mobile:'+919876543210',state_code:'27',is_active:true}}
];
async function setup(path?:string){const db=new TestDB(path),store=new Store(db,business,randomUUID);store.role='owner';await store.init();await store.pullPage(initial,'initial',true);return{db,store};}
function bill(overrides:any={}){return {id:randomUUID(),customer:cid,items:[{product:pid,quantity:'2',unit_price:'100.00',gst_rate:'18.00',price_includes_tax:false}],discount:'10.00',gst:true,paid:'100.00',includeQR:true,payment_method:'cash',...overrides};}

test('exact GST, discount remainder, tax-inclusive and fractional quantity rules',()=>{
  const item={product:'1',quantity:'2',unit_price:'100',gst_rate:'18',price_includes_tax:false};
  const result=calculate([item],'10',true,false);assert.equal(result.totals.total,22420);assert.equal(result.totals.cgst,1710);
  assert.equal(calculate([{...item,quantity:'1',unit_price:'118',price_includes_tax:true}],'0',true,false).totals.total,11800);
  assert.equal(calculate([{...item,quantity:'0.125',unit_price:'1',gst_rate:'0'}],'0',false,false).totals.total,13);
  const tiny=[0,1,2].map(i=>({...item,product:String(i),quantity:'1',unit_price:'0.01',gst_rate:'0'}));
  const discount=calculate(tiny,'0.01',false,false);assert.equal(discount.lines[2].discount,1);assert.equal(discount.totals.total,2);
  assert.throws(()=>calculate([item,item],'0',false,false));assert.throws(()=>scaled('1.001'));
  assert.equal(decimal(123),'1.23');assert.equal(normalizeMobile('98765 43210'),'+919876543210');
});
test('offline invoice, stock, collection and duplicate Save are one durable transaction',async()=>{
  const {db,store}=await setup();const draft=bill();const first=await store.saveBill(draft),again=await store.saveBill(draft);
  assert.equal(first.id,again.id);assert.equal((await store.list('invoice')).length,1);assert.equal((await store.get('product',pid)).stock,'18.000');
  assert.equal((await store.pending()).length,1);const collection=await db.getFirstAsync('SELECT * FROM customer_collection');assert.equal(collection.total_paise,22420);assert.equal(collection.paid_paise,10000);
  await store.pay(first.id,'24.20','cash');assert.equal((await store.get('invoice',first.id)).paid_amount,'124.20');db.close();
});
test('failed invoice rolls back stock, number allocation, receipt and outbox',async()=>{
  const {db,store}=await setup();await assert.rejects(store.saveBill(bill({paid:'9999'})));assert.equal((await store.pending()).length,0);assert.equal((await store.get('product',pid)).stock,'20.000');assert.equal((await store.list('invoice')).length,0);db.close();
});
test('restart preserves unsynced receipts and scoped encrypted-database ownership metadata',async()=>{
  const folder=mkdtempSync(join(tmpdir(),'billora-mobile-')),file=join(folder,'test.db');let {db,store}=await setup(file);const receipt=await store.saveBill(bill());db.close();
  db=new TestDB(file);store=new Store(db,business,randomUUID);await store.init();assert.equal((await store.get('invoice',receipt.id)).total,'224.20');assert.equal((await store.pending()).length,1);
  await assert.rejects(new Store(db,randomUUID(),randomUUID).init(),/another shop/);db.close();rmSync(folder,{recursive:true});
});
test('official range allocation survives replay; exhausted devices issue provisional documents',async()=>{
  const {db,store}=await setup();const date=indiaDate(),year=Number(date.slice(0,4)),fy=Number(date.slice(5,7))>=4?year:year-1;
  const range={id:randomUUID(),fiscal_year:fy,start:1,end:1};await store.addRange(range);const first=await store.saveBill(bill());assert.equal(first.number,`M${fy%100}-0000000001`);
  await store.addRange(range);const second=await store.saveBill(bill());assert.equal(second.number,'');assert.equal(second.provisional,true);db.close();
});
test('offline product and customer creation is searchable and emits persistent operations',async()=>{
  const {db,store}=await setup();const product=randomUUID(),customer=randomUUID();
  await store.enqueue('product.create',product,{name:'Oil',sku:'O1',selling_price:'120',gst_rate:'5',stock:'3'});
  await store.enqueue('customer.create',customer,{name:'Ravi',mobile:'9876543211'});
  assert.equal((await store.get('customer',customer)).mobile,'+919876543211');assert.equal((await store.pending()).length,2);
  await assert.rejects(store.enqueue('customer.create',randomUUID(),{name:'Duplicate',mobile:'+919876543211'}));
  await store.enqueue('stock.adjust',product,{delta:'2',reason:'Delivery'});assert.equal((await store.get('product',product)).stock,'5.000');db.close();
});
test('staged partial pull cannot double-decrement stock during concurrent local billing',async()=>{
  const {db,store}=await setup();const receipt=await store.saveBill(bill());await store.acknowledge(receipt.id,{status:'accepted'});
  await store.pullPage([{...initial[1],version:'p2',data:{...initial[1].data,stock:'18.000'}},{kind:'invoice',id:receipt.id,version:'i1',data:{...receipt,sync_status:'synced',number:'M26-0000000001'}}],'partial',false);
  await store.enqueue('stock.adjust',pid,{delta:'3',reason:'Delivered'});assert.equal((await store.get('product',pid)).stock,'21.000');
  await store.pullPage([],'complete',true);assert.equal((await store.get('product',pid)).stock,'21.000');assert.equal((await store.list('invoice')).length,1);db.close();
});
test('tombstones retain historical invoice snapshots and financial conflicts retain original events',async()=>{
  const {db,store}=await setup();const receipt=await store.saveBill(bill());await store.acknowledge(receipt.id,{status:'conflict',detail:'Tax changed'});
  await store.pullPage([{kind:'customer',id:cid,version:'deleted',data:null}],'end',true);
  assert.equal((await store.get('invoice',receipt.id)).customer_snapshot.name,'Rahul');assert.equal((await store.status()).conflicts.length,1);assert.match(await store.exportData(),/Tax changed/);db.close();
});
test('sync timeout retries same UUID; revoked session locks without dropping data',async()=>{
  const {db,store}=await setup();const receipt=await store.saveBill(bill()),session:any={token:'test',business:{id:business},role:'owner'};let blocked=false;
  const engine=new SyncEngine(store,session,(_,expired)=>{blocked=!!expired;},async()=>{}, {push:async()=>{throw new Error('Network timeout');},pull:async()=>{throw new Error('Must not pull after failed push');}});
  await engine.run();assert.equal((await store.pending())[0].id,receipt.id);assert.equal((await store.pending())[0].attempts,1);
  const revoked=new SyncEngine(store,session,(_,expired)=>{blocked=!!expired;},async()=>{}, {push:async()=>{throw new SessionExpired('Revoked');},pull:async()=>({})});
  await revoked.run(true);assert.equal(blocked,true);assert.equal(session.blocked,true);assert.equal((await store.pending()).length,1);db.close();
});
test('successful mocked sync acknowledges only after complete pull and replay stays unique',async()=>{
  const {db,store}=await setup();const receipt=await store.saveBill(bill());const ids:string[]=[];const engine=new SyncEngine(store,{token:'t',role:'owner'} as any,()=>{},async()=>{}, {
    push:async(op:any)=>{ids.push(op.id);return{status:'accepted'};},
    pull:async()=>({role:'owner',cursor:'done',has_more:false,changes:[{...initial[1],version:'p2',data:{...initial[1].data,stock:'18.000'}},{kind:'invoice',id:receipt.id,version:'i1',data:{...receipt,number:'M26-0000000001',sync_status:'synced'}}]})});
  await engine.run();await engine.run();assert.deepEqual(ids,[receipt.id]);assert.equal((await store.pending()).length,0);assert.equal((await store.get('product',pid)).stock,'18.000');assert.equal((await store.list('invoice')).length,1);db.close();
});
test('offline PDF markup escapes customer content and UPI requests only exact unpaid balance',async()=>{
  const {db,store}=await setup();const receipt=await store.saveBill(bill());
  receipt.customer_snapshot.name='<script>alert(1)</script>';
  const html=invoiceHTML(receipt);assert.ok(html.includes('&lt;script&gt;'));assert.ok(!html.includes('<script>'));
  assert.ok(html.includes('PROVISIONAL BILL'));const uri=new URL(upiURI(receipt));assert.equal(uri.searchParams.get('am'),'124.20');assert.equal(uri.searchParams.get('tr'),receipt.id);
  assert.match(qrData(upiURI(receipt)),/^data:image\/gif;base64,/);
  receipt.paid_amount=receipt.total;assert.equal(upiURI(receipt),'');db.close();
});
test('UPI settings are durable offline changes; a failed product update blocks further local sales',async()=>{
  const {db,store}=await setup();await store.enqueue('business.settings',business,{upi_id:'new@upi',upi_payee_name:'New Payee'},'b1');
  assert.equal((await store.get('business',business)).settings.upi_id,'new@upi');
  const op=await store.enqueue('product.update',pid,{name:'Rice',sku:'R1',selling_price:'90',gst_rate:'18'},'p1');await store.acknowledge(op.id,{status:'conflict',detail:'Concurrent edit'});
  await store.pullPage([],'done',true);await assert.rejects(store.saveBill(bill()),/sync issue/);db.close();
});
