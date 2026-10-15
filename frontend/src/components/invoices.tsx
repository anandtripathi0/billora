'use client';

import { useEffect, useState, useRef } from 'react';

import { useRouter } from 'next/navigation';

import Link from 'next/link';

import { useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError, api, send, type Page, type RecordData } from '@/lib/api';

import { Button } from './ui/button';

import { PageHeading, Field, Loading, ErrorState, Empty, InvoiceTable, Pagination, useSearch, Modal, Badge } from './common';

import { useSession } from './shell';

import { useNotice } from './providers';

import { billingTotals } from '@/lib/billing-totals';

import { RecordEditor } from './records';

import { currency } from '@/lib/utils';

import { Plus, Search, Trash2, ArrowLeft, Eye, Download, Printer, MessageCircle, Copy, QrCode, Wallet, Link2Off, ArrowRight, ShieldCheck } from 'lucide-react';



export function InvoiceHistory() {

  const [page,setPage]=useState(1);const [status,setStatus]=useState('');const {search,setSearch,debounced}=useSearch();const session=useSession();

  useEffect(()=>{setPage(1);},[debounced,status]);

  const {data,error,isPending,refetch}=useQuery({queryKey:['invoices',page,debounced,status],queryFn:()=>api<Page<RecordData>>(`invoices/?page=${page}&search=${encodeURIComponent(debounced)}&status=${status}`)});

  return <><PageHeading eyebrow="EVERY SALE HAS A STORY" title="Your invoices" description="Created, shared, and accounted for.">{session.role!=='viewer'&&<Button asChild><Link href="/invoices/new"><Plus size={17}/>Create invoice</Link></Button>}</PageHeading><section className="panel"><div className="toolbar"><div className="search"><Search size={16}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search invoice or customer…" aria-label="Search invoices"/></div><select aria-label="Filter payment status" value={status} onChange={e=>setStatus(e.target.value)}><option value="">All statuses</option><option value="paid">Paid</option><option value="partial">Partially paid</option><option value="unpaid">Unpaid</option><option value="cancelled">Cancelled</option></select></div>{isPending?<Loading/>:error?<ErrorState error={error} retry={()=>refetch()}/>:<InvoiceTable rows={data?.results||[]}/>} {data&&<Pagination {...data} page={page} onChange={setPage}/>}</section></>;

}



type Line={product:RecordData;quantity:string;price:string};

export function InvoiceComposer() {

  const session=useSession();const notice=useNotice();const router=useRouter();const client=useQueryClient();

  const mobileSearch=useSearch(); const [newName,setNewName]=useState(''); const [paymentStatus,setPaymentStatus]=useState('unpaid'); const saveLock=useRef(false); const saveBody=useRef<RecordData|null>(null);

  const [customer,setCustomer]=useState<RecordData|null>(null);const [lines,setLines]=useState<Line[]>([]);const customerSearch=useSearch();const productSearch=useSearch();const [addCustomer,setAddCustomer]=useState(false);

  const [discount,setDiscount]=useState('0');const [paid,setPaid]=useState('0');const [gst,setGst]=useState(Boolean(session.business?.gstin));const [upi,setUpi]=useState(Boolean(session.business?.settings.qr_default));const [method,setMethod]=useState('cash');const [supply,setSupply]=useState(session.business?.state_code||'27');const [notes,setNotes]=useState('');const [due,setDue]=useState('');

  const [date,setDate]=useState(()=>new Intl.DateTimeFormat('en-CA',{timeZone:session.business?.settings.timezone||'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()));

  const [key,setKey]=useState(()=>crypto.randomUUID());const [busy,setBusy]=useState(false);const [preview,setPreview]=useState<RecordData|null>(null);const [reviewed,setReviewed]=useState<RecordData|null>(null);

  const customers=useQuery({queryKey:['customers-select',customerSearch.debounced],queryFn:()=>api<Page<RecordData>>(`customers/?search=${encodeURIComponent(customerSearch.debounced)}`)});

  const products=useQuery({queryKey:['products-select',productSearch.debounced],queryFn:()=>api<Page<RecordData>>(`products/?search=${encodeURIComponent(productSearch.debounced)}`)});

  const normalized=mobileSearch.search.replace(/[\s()+-]/g,'').replace(/^91(?=\d{10}$)/,'');

  const lookup=useQuery({queryKey:['mobile-lookup',mobileSearch.debounced],queryFn:()=>api<RecordData>(`customers/lookup/?mobile=${encodeURIComponent(mobileSearch.debounced)}`),enabled:/^[6-9]\d{9}$/.test(normalized)&&mobileSearch.search===mobileSearch.debounced,retry:false});

  useEffect(()=>{if(lookup.data?.customer){setCustomer(lookup.data.customer);setSupply(lookup.data.customer.state_code||session.business?.state_code);}},[lookup.data,session.business?.state_code]);

  let instant={subtotal:'0',discount:'0',tax:'0',total:'0'}, totalsError='';

  try{if(gst&&lines.some(l=>l.product.gst_rate===null))throw Error('Verify the GST rate for selected products in Inventory before creating a GST invoice.');instant=billingTotals(lines.map(l=>({quantity:l.quantity,price:l.price,gst:String(l.product.gst_rate??0),inclusive:l.product.price_includes_tax})),discount,gst,supply!==session.business?.state_code);}catch(e){totalsError=(e as Error).message;}

  const lookupReady=mobileSearch.search===mobileSearch.debounced&&lookup.isSuccess&&!lookup.isFetching&&/^[6-9]\d{9}$/.test(normalized);

  async function quickCustomer(){if(customer)return customer;if(!lookupReady||!lookup.data)throw Error('Wait for the mobile lookup to finish.');if(lookup.data.customer)return lookup.data.customer;if(!newName.trim())throw Error('Enter the new customer name.');const row=await send<RecordData>('customers/quick/',{name:newName,mobile:mobileSearch.search});setCustomer(row);return row;}

  async function fastSave(print=false){if(saveLock.current)return;saveLock.current=true;setBusy(true);try{if(!saveBody.current){const selected=await quickCustomer();const body={...payload(),customer:selected.id};saveBody.current={...body,expected_total:instant.total};}const invoice=await send<RecordData>('invoices/',saveBody.current);void client.invalidateQueries({predicate: query => query.queryKey[0] !== 'session'});notice('Invoice saved.');router.push(print?`/print/${invoice.id}?direct=1`:`/invoices/${invoice.id}`);}catch(e){if(e instanceof ApiError&&e.status>=400&&e.status<500){saveBody.current=null;setKey(crypto.randomUUID());}notice((e as Error).message,true);}finally{saveLock.current=false;setBusy(false);}}

  if(session.role==='viewer')return <Empty title="Read-only access" text="Ask your business owner for permission to create invoices."/>;

  const payload=()=>({customer:customer?.id,items:lines.map(l=>({product:l.product.id,quantity:l.quantity,unit_price:l.price})),payment_status:paymentStatus,idempotency_key:key,date,due_date:due||null,supply_state:supply,gst_enabled:gst,discount,paid_amount:paid,payment_method:method,include_upi_qr:upi,notes});

  async function prepare(e:React.FormEvent) {e.preventDefault();if(!customer||!lines.length){notice('Choose a customer and add at least one product.',true);return;}setBusy(true);try{const body=payload();const result=await send<RecordData>('invoices/preview/',body);setReviewed({...body,quote_token:result.quote_token});setPreview(result);}catch(error){notice((error as Error).message,true);}finally{setBusy(false);}}

  async function finalize(){setBusy(true);try{const invoice=await send<RecordData>('invoices/',reviewed);void client.invalidateQueries({predicate: query => query.queryKey[0] !== 'session'});notice(invoice.pdf_ready === false ? 'Invoice saved. PDF is temporarily unavailable; retry its download.' : 'Invoice created. PDF is ready, and stock is updated.', invoice.pdf_ready === false);router.push(`/invoices/${invoice.id}`);}catch(error){notice((error as Error).message,true);}finally{setBusy(false);}}

  return <><PageHeading eyebrow="MAKE YOUR NEXT SALE OFFICIAL" title="Create an invoice" description="A few details. One beautifully clear invoice."><Button asChild variant="outline"><Link href="/invoices"><ArrowLeft size={15}/>All invoices</Link></Button></PageHeading>{!session.business?.address&&<div className="onboarding-hint">Add your business address, logo, GSTIN, and UPI details in <Link href="/settings">Business settings</Link> to complete your invoices.</div>}

    <form onSubmit={prepare}><div className="invoice-workspace"><div className="section-stack"><section className="panel content-pad"><div className="form-section-heading"><h2>01 · Who are we billing?</h2><p>Enter a mobile number to find their purchases immediately.</p></div><div className="form-grid"><Field label="Customer mobile"><input autoFocus type="tel" inputMode="tel" maxLength={20} value={mobileSearch.search} onChange={e=>{mobileSearch.setSearch(e.target.value);setCustomer(null);}} placeholder="98765 43210" autoComplete="tel"/></Field>{mobileSearch.search&&<div className="muted-small" role="status">{lookup.isFetching?'Finding customer…':lookup.error?lookup.error.message:lookup.data?.customer?`Welcome back, ${lookup.data.customer.name}`:/^[6-9]\d{9}$/.test(normalized)?'New customer — enter their name below.':'Enter a valid 10-digit Indian mobile.'}</div>}{lookup.data&&!lookup.data.customer&&<Field label="New customer name"><input value={newName} onChange={e=>setNewName(e.target.value)} maxLength={160} autoComplete="name"/></Field>}<Field label="Find a customer"><input value={customerSearch.search} onChange={e=>customerSearch.setSearch(e.target.value)} placeholder="Search name or mobile…"/></Field><Field label="Customer"><select required value={customer?.id||''} onChange={e=>{const row=customers.data?.results.find(c=>String(c.id)===e.target.value);if(row){setCustomer(row);setSupply(row.state_code||session.business?.state_code);}}}><option value="">Choose a customer</option>{customer&&!customers.data?.results.find(c=>c.id===customer.id)&&<option value={customer.id}>{customer.name}</option>}{customers.data?.results.map(c=><option key={c.id} value={c.id}>{c.name} · {c.mobile}</option>)}</select></Field></div>{customers.error&&<p className="form-error">{customers.error.message}</p>}<Button type="button" variant="ghost" size="sm" onClick={()=>setAddCustomer(true)} style={{marginTop:13}}><Plus size={14}/>Quick add customer</Button>{customer&&<div className="notice-box" style={{marginTop:14}}><strong>{customer.name}</strong> · {customer.mobile}{customer.address&&<><br/>{customer.address}</>}<br/>Previous purchases: {currency(customer.purchases)} · Received: {currency(customer.payments_received)} · Outstanding: {currency(customer.outstanding)}</div>}</section>

      <section className="panel content-pad"><div className="form-section-heading"><h2>02 · What’s in the sale?</h2><p>Add items, edit the selling price, and see totals instantly.</p></div><div className="form-grid"><Field label="Find a product"><input value={productSearch.search} onChange={e=>productSearch.setSearch(e.target.value)} placeholder="Search name, SKU or barcode…"/></Field><Field label="Add product"><select value="" onChange={e=>{const product=products.data?.results.find(p=>String(p.id)===e.target.value);if(product&&!lines.some(l=>l.product.id===product.id))setLines([...lines,{product,quantity:'1',price:String(product.selling_price)}]);else if(product)notice('This product is already added. Adjust its quantity below.');}}><option value="">Select a product to add</option>{products.data?.results.filter(p=>p.selling_price!==null).map(p=><option key={p.id} value={p.id}>{p.name} · {currency(p.selling_price)} · {Number(p.stock)} left</option>)}</select></Field></div>{products.error&&<p className="form-error">{products.error.message}</p>}{!lines.length?<Empty title="Your invoice is a blank canvas" text="Add a product above to begin."/>:lines.map((line,index)=><div className="invoice-line" key={line.product.id}><div><strong>{line.product.name}</strong><small>{line.product.sku} · {currency(line.product.selling_price)} / {line.product.unit} · GST {line.product.gst_rate===null?"unknown":`${Number(line.product.gst_rate)}%`} · {Number(line.product.stock)} in stock · {line.product.price_includes_tax?"Tax included":"Tax excluded"}</small></div><Field label="Quantity"><input aria-label={`Quantity for ${line.product.name}`} required type="number" min="0.001" step="0.001" value={line.quantity} onChange={e=>setLines(lines.map((l,i)=>i===index?{...l,quantity:e.target.value}:l))}/></Field><Field label="Price (₹)"><input aria-label={`Price for ${line.product.name}`} required type="number" min="0" step="0.01" value={line.price} onChange={e=>setLines(lines.map((l,i)=>i===index?{...l,price:e.target.value}:l))}/></Field><Button type="button" size="icon" variant="ghost" aria-label={`Remove ${line.product.name}`} onClick={()=>setLines(lines.filter((_,i)=>i!==index))}><Trash2 size={15}/></Button></div>)}</section>

      <section className="panel content-pad"><div className="form-section-heading"><h2>03 · The finishing touches</h2></div><div className="form-grid"><Field label="Invoice date"><input type="date" value={date} onChange={e=>setDate(e.target.value)} required/></Field><Field label="Due date (optional)"><input type="date" value={due} min={date} onChange={e=>setDue(e.target.value)}/></Field><Field label="Place of supply (state code)"><input value={supply} onChange={e=>setSupply(e.target.value)} maxLength={2} pattern="[0-9]{2}" required/></Field><Field label="Payment method"><select value={method} onChange={e=>setMethod(e.target.value)}>{['cash','upi','bank','card','credit'].map(m=><option key={m} value={m}>{m.toUpperCase()}</option>)}</select></Field><div className="full-width"><Field label="Notes for your customer"><textarea value={notes} onChange={e=>setNotes(e.target.value)} maxLength={2000} placeholder="A personal note, payment terms, or a thank you…"/></Field></div></div></section></div>

      <aside className="panel content-pad invoice-sidebar"><h2 style={{marginBottom:23}}>Make it official</h2><div className="form-stack"><Field label="Invoice discount (₹)"><input required type="number" min="0" step="0.01" value={discount} onChange={e=>setDiscount(e.target.value)}/></Field><Field label="Payment status"><select value={paymentStatus} onChange={e=>setPaymentStatus(e.target.value)}><option value="unpaid">Unpaid</option><option value="partial">Partial</option><option value="paid">Paid</option></select></Field>{paymentStatus==='partial'&&<Field label="Amount already paid (₹)"><input required type="number" min="0.01" step="0.01" value={paid} onChange={e=>setPaid(e.target.value)}/></Field>}<label className="check-label"><input type="checkbox" checked={gst} onChange={e=>setGst(e.target.checked)} disabled={!session.business?.gstin}/>Apply GST</label><label className="check-label"><input type="checkbox" checked={upi} onChange={e=>setUpi(e.target.checked)}/>Include UPI QR</label><p className="muted-small">QR uses the exact remaining balance. Payment confirmation is always a separate step.</p><div className="totals-list" aria-live="polite"><div><span>Subtotal</span><b>{currency(instant.subtotal)}</b></div><div><span>Tax</span><b>{currency(instant.tax)}</b></div><div className="total-row"><span>Grand total</span><b>{currency(instant.total)}</b></div><div><span>Amount received</span><b>{currency(paymentStatus==='paid'?instant.total:paymentStatus==='partial'?paid:0)}</b></div><div><span>Remaining</span><b>{currency(Number(instant.total)-(paymentStatus==='paid'?Number(instant.total):paymentStatus==='partial'?Number(paid):0))}</b></div>{customer&&<><div><span>Previous purchases</span><b>{currency(customer.purchases)}</b></div><div><span>Updated purchases</span><b>{currency(Number(customer.purchases||0)+Number(instant.total))}</b></div></>}</div>{totalsError&&<p className="form-error">{totalsError}</p>}<Button type="button" disabled={busy||!lines.length||!!totalsError||(!customer&&(!newName||!lookupReady))} onClick={()=>fastSave(false)}>{busy?'Saving…':'Save Invoice'}</Button><Button type="button" variant="outline" disabled={busy||!lines.length||!!totalsError||(!customer&&(!newName||!lookupReady))} onClick={()=>fastSave(true)}><Printer size={16}/>Save &amp; Print</Button><Button type="submit" disabled={busy||!lines.length||!customer||!!totalsError}><Eye size={16}/>{busy?'Calculating…':'Preview invoice'}</Button><p className="muted-small" style={{textAlign:'center'}}>Saving updates stock and customer purchases once.</p></div></aside></div></form>

    {addCustomer&&<RecordEditor kind="customers" onClose={()=>setAddCustomer(false)} onSaved={c=>{setCustomer(c);setSupply(c.state_code||session.business?.state_code);}}/>}

    {preview&&<Modal title="Review your invoice" onClose={()=>{if(!busy)setPreview(null);}}><div className="notice-box" style={{marginBottom:20}}>{customer?.name} · {date}<br/>{gst?'GST invoice':'Non-GST invoice'} · {lines.length} product{lines.length!==1?'s':''}</div><div className="table-wrap"><table><thead><tr><th>Item</th><th>Qty</th><th>Total</th></tr></thead><tbody>{preview.items.map((item:RecordData,i:number)=><tr key={i}><td>{item.description}</td><td>{item.quantity}</td><td>{currency(item.total)}</td></tr>)}</tbody></table></div><div className="totals-list" style={{marginTop:22}}>{['subtotal','discount','cgst','sgst','igst'].map(k=><div key={k}><span>{k.toUpperCase()}</span><b>{currency(preview[k])}</b></div>)}<div className="total-row"><span>Grand total</span><b>{currency(preview.total)}</b></div><div><span>Balance due</span><b>{currency(preview.balance)}</b></div></div><div className="form-actions"><Button variant="outline" disabled={busy} onClick={()=>setPreview(null)}>Back to editing</Button><Button disabled={busy} onClick={finalize}>{busy?'Saving invoice…':'Generate invoice'}<ArrowRight size={16}/></Button></div></Modal>}

  </>;

}



export function InvoiceDetail({id}: {id:string}) {

  const session=useSession();const notice=useNotice();const client=useQueryClient();const canWrite=session.role!=='viewer';

  const {data,error,isPending,refetch}=useQuery({queryKey:['invoice',id],queryFn:()=>api<RecordData>(`invoices/${id}/`)});

  const qr=useQuery({queryKey:['invoice-qr',id,data?.revision],queryFn:()=>api<RecordData>(`invoices/${id}/qr/`),enabled:!!data?.include_upi_qr});

  const [cancel,setCancel]=useState(false);const [share,setShare]=useState<RecordData|null>(null);const [busy,setBusy]=useState(false);const [pay,setPay]=useState(false);const [paymentKey,setPaymentKey]=useState(()=>crypto.randomUUID());const [revoke,setRevoke]=useState(false);

  async function shareInvoice(copyKind?:'url'|'message'){setBusy(true);try{const result=share||await send<RecordData>(`invoices/${id}/share/`,{});setShare(result);if(copyKind)await copy(result[copyKind]);}catch(e){notice((e as Error).message,true);}finally{setBusy(false);}}

  async function copy(value:string){try{await navigator.clipboard.writeText(value);notice('Copied to clipboard.');}catch{notice('Clipboard access is unavailable. Select and copy the text manually.',true);}}

  if(isPending)return <Loading/>;if(error||!data)return <ErrorState error={error} retry={()=>refetch()}/>;

  return <><PageHeading eyebrow="SAVED & ACCOUNTED FOR" title={data.number} description={`Created for ${data.customer_snapshot.name}`}><Button variant="outline" asChild><Link href="/invoices"><ArrowLeft size={15}/>Back</Link></Button><Button variant="outline" asChild><Link href={`/print/${id}`}><Printer size={16}/>Reprint</Link></Button><Button variant="outline" asChild><a href={`/api/invoices/${id}/pdf/?download=1`} target="_blank" rel="noopener noreferrer"><Download size={16}/>Download PDF</a></Button>{canWrite&&<Button variant="success" disabled={busy} onClick={()=>shareInvoice()}><MessageCircle size={17}/>{busy?'Preparing…':'Share on WhatsApp'}</Button>}</PageHeading>

    {data.customer_snapshot.previous_purchases!==undefined&&!data.cancelled_at&&<div className="notice-box no-print" style={{marginBottom:16}}>At checkout · Previous purchases: {currency(data.customer_snapshot.previous_purchases)} + New invoice: {currency(data.total)} = Updated purchases: <b>{currency(data.customer_snapshot.purchases_after)}</b>. <Link href={`/customers/${data.customer}`}>View current collection</Link></div>}

    <div className="actions no-print" style={{marginBottom:22}}><Badge status={data.status}/><span className="muted-small">Balance due: {currency(data.balance)}</span>{canWrite&&Number(data.balance)>0&&<Button size="sm" variant="outline" onClick={()=>setPay(true)}><Wallet size={14}/>Record payment</Button>}{canWrite&&<Button size="sm" variant="ghost" onClick={()=>setRevoke(true)}><Link2Off size={14}/>Revoke sharing links</Button>}{canWrite&&<><Button size="sm" variant="outline" disabled={busy} onClick={()=>shareInvoice('url')}><Copy size={14}/>Copy Invoice Link</Button><Button size="sm" variant="outline" disabled={busy} onClick={()=>shareInvoice('message')}><Copy size={14}/>Copy Invoice Message</Button></>}</div>

    {data.cancelled_at&&<div className="notice-box">Cancelled: {data.cancellation_reason}. Refunded: {currency(data.paid_amount)}. This sale is excluded from purchases.</div>}{!data.cancelled_at&&['owner','manager'].includes(session.role)&&<Button className="no-print" variant="ghost" size="sm" onClick={()=>setCancel(true)}>Cancel invoice</Button>}

    {cancel&&<Modal title="Cancel invoice and restore stock" onClose={()=>setCancel(false)}><form onSubmit={async e=>{e.preventDefault();const form=new FormData(e.currentTarget);setBusy(true);try{await send(`invoices/${id}/cancel/`,{reason:form.get('reason'),refund_confirmed:form.has('refund')});setCancel(false);setShare(null);void client.invalidateQueries({predicate: query => query.queryKey[0] !== 'session'});notice('Invoice cancelled. Collection totals updated.');}catch(e){notice((e as Error).message,true);}finally{setBusy(false);}}}><Field label="Cancellation reason"><input name="reason" required maxLength={300}/></Field>{Number(data.paid_amount)>0&&<label className="check-label"><input type="checkbox" name="refund" required/>I have returned {currency(data.paid_amount)} to the customer. No money is sent by Billora.</label>}<p className="muted-small">All items must be returned to stock. This full cancellation is irreversible.</p><div className="form-actions"><Button variant="outline" type="button" onClick={()=>setCancel(false)}>Keep invoice</Button><Button variant="danger" disabled={busy}>Confirm cancellation</Button></div></form></Modal>}

    <article className="invoice-paper"><div className="paper-top"><div>{data.business_snapshot.logo_data&&<img src={data.business_snapshot.logo_data} alt="Business logo" style={{maxWidth:160,maxHeight:70,marginBottom:12}}/>}<h2>{data.business_snapshot.name}</h2><p>{data.business_snapshot.address}</p><p>{data.business_snapshot.mobile}</p>{data.business_snapshot.gstin&&<p>GSTIN: {data.business_snapshot.gstin}</p>}</div><div><h1>INVOICE</h1><p>{data.number}</p><p>Date: {data.date}{data.due_date&&<><br/>Due: {data.due_date}</>}</p><p>{data.gst_enabled?'Tax invoice':'Non-GST invoice'}</p></div></div><div className="paper-customer"><div><span style={{fontSize:10,color:'#796955',letterSpacing:1}}>BILL TO</span><h2 style={{marginTop:8}}>{data.customer_snapshot.name}</h2><p>{data.customer_snapshot.mobile}<br/>{data.customer_snapshot.address}</p>{data.customer_snapshot.gstin&&<p>GSTIN: {data.customer_snapshot.gstin}</p>}</div><div><p>Place of supply: {data.supply_state}<br/>Payment method: {data.payment_method.toUpperCase()}<br/>Status: {data.status.toUpperCase()}</p></div></div><div className="table-wrap"><table><thead><tr><th>Item / HSN</th><th>Quantity</th><th>Rate</th><th>Discount</th><th>GST</th><th>Total</th></tr></thead><tbody>{data.items.map((item:RecordData)=><tr key={item.id}><td><b>{item.description}</b><br/><small>{item.hsn_code}</small></td><td>{Number(item.quantity)} {item.unit}</td><td>{currency(item.unit_price)}{item.price_includes_tax&&<small className="catalog-meta">Tax included</small>}</td><td>{currency(item.discount)}</td><td>{Number(item.gst_rate)}%</td><td>{currency(item.total)}</td></tr>)}</tbody></table></div><div className="paper-totals">{['subtotal','discount',...(data.gst_enabled?['cgst','sgst','igst']:[])].map(k=><div key={k}><span>{k.toUpperCase()}</span><span>{currency(data[k])}</span></div>)}<div className="total-row"><span>Grand total</span><span>{currency(data.total)}</span></div><div><span>Paid</span><span>{currency(data.paid_amount)}</span></div><div><b>Balance due</b><b>{currency(data.balance)}</b></div></div>{qr.data?.image&&<div className="qr-section"><img src={qr.data.image} alt={`UPI QR to pay ${currency(data.balance)}`}/><div><h3>Scan to pay {currency(data.balance)}</h3><p>{data.business_snapshot.upi_payee_name}<br/>{qr.data.upi_id}</p><Button className="no-print" size="sm" variant="outline" onClick={()=>copy(qr.data!.upi_id)} style={{marginTop:8}}><Copy size={13}/>Copy UPI ID</Button></div></div>}{qr.error&&<p className="form-error">Could not load the QR. Refresh to try again.</p>}{data.notes&&<p style={{marginTop:25}}><b>Notes</b><br/>{data.notes}</p>}<footer>{data.business_snapshot.invoice_footer}<br/>Created with Billora</footer></article>

    {share&&<Modal title="Ready for your customer" onClose={()=>setShare(null)}><div className="notice-box">Your secure link expires in 7 days. WhatsApp opens with a prepared message; you must confirm sending. Delivery is not tracked.</div><Field label="Message"><textarea readOnly value={share.message} rows={5} style={{marginTop:15}}/></Field><div className="form-actions">{typeof navigator!=='undefined'&&!!navigator.share&&<Button variant="outline" onClick={async()=>{try{await navigator.share({title:data.number,text:share.message});}catch(error){if((error as Error).name!=='AbortError')notice('Sharing is unavailable. Copy the message instead.',true);}}}>Share via…</Button>}<Button variant="outline" onClick={()=>copy(share.url)}><Copy size={14}/>Copy Invoice Link</Button><Button variant="outline" onClick={()=>copy(share.message)}>Copy Invoice Message</Button><Button variant="success" asChild><a href={share.whatsapp_url} target="_blank" rel="noopener noreferrer"><MessageCircle size={16}/>Open WhatsApp</a></Button></div></Modal>}

    {pay&&<Modal title="Record a confirmed payment" onClose={()=>{if(!busy)setPay(false);}}><p className="muted-small" style={{marginBottom:20}}>Record only money you have received. Generating or scanning a QR does not confirm a payment.</p><form onSubmit={async e=>{e.preventDefault();const form=new FormData(e.currentTarget);setBusy(true);try{await send(`invoices/${id}/pay/`,{...Object.fromEntries(form),idempotency_key:paymentKey});setPaymentKey(crypto.randomUUID());setPay(false);setShare(null);client.invalidateQueries({predicate: query => query.queryKey[0] !== 'session'});notice('Payment recorded. Balance and QR updated.');}catch(error){notice((error as Error).message,true);}finally{setBusy(false);}}}><div className="form-grid"><Field label="Amount received (₹)"><input name="amount" required type="number" min="0.01" max={data.balance} step="0.01" defaultValue={data.balance}/></Field><Field label="Method"><select name="method">{['cash','upi','bank','card'].map(m=><option key={m} value={m}>{m.toUpperCase()}</option>)}</select></Field><div className="full-width"><Field label="Transaction reference (optional)"><input name="reference" maxLength={120}/></Field></div></div><div className="form-actions"><Button disabled={busy}>{busy?'Saving…':'Confirm payment'}</Button></div></form></Modal>}

    {revoke&&<Modal title="Revoke all sharing links?" onClose={()=>setRevoke(false)}><p className="muted">Existing links for this invoice will stop working. You can create a new link later.</p><div className="form-actions"><Button variant="outline" onClick={()=>setRevoke(false)}>Cancel</Button><Button disabled={busy} variant="danger" onClick={async()=>{setBusy(true);try{await send(`invoices/${id}/revoke-links/`,{});setRevoke(false);setShare(null);notice('Sharing links revoked.');}catch(e){notice((e as Error).message,true);}finally{setBusy(false);}}}>Revoke links</Button></div></Modal>}

  </>;

}



