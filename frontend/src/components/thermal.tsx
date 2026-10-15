'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, send, RecordData, Session } from '@/lib/api';
import { Button } from './ui/button';
import { Field, ErrorState, Loading } from './common';
import { currency } from '@/lib/utils';

export function PrinterSettings(){
  const client=useQueryClient();const [busy,setBusy]=useState(false),[code,setCode]=useState(''),[error,setError]=useState('');
  const devices=useQuery({queryKey:['print-devices'],queryFn:()=>api<RecordData[]>('printing/devices/'),refetchInterval:10000});
  return <section className="panel content-pad" style={{marginTop:24}}><h2>Thermal printer</h2><p className="muted-small">Browser printing works with an installed printer. For direct ESC/POS printing, pair the local agent on your shop PC.</p>
    <form className="form-grid" style={{marginTop:16}} onSubmit={async e=>{e.preventDefault();setBusy(true);setError('');try{const result=await send<RecordData>('printing/devices/',Object.fromEntries(new FormData(e.currentTarget)));setCode(result.pairing_code);client.invalidateQueries({queryKey:['print-devices']});}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}><Field label="Printer label"><input name="name" required maxLength={80} placeholder="Counter printer"/></Field><Field label="Printer paper width"><select name="width"><option value="80">80 mm</option><option value="58">58 mm</option></select></Field><Button disabled={busy}>Create pairing code</Button></form>
    {code&&<div className="notice-box" style={{marginTop:16}}>Enter this one-time code in the local agent within 10 minutes:<br/><code style={{overflowWrap:'anywhere',userSelect:'all'}}>{code}</code><p>Run <code>python printer_bridge/agent.py setup</code> on the printer PC. The agent asks for your Billora URL, this code, and printer connection.</p></div>}
    {(error||devices.error)&&<p role="alert" className="form-error">{error||devices.error?.message}</p>}
    {devices.data?.map(d=><div className="toolbar" key={d.id}><span><b>{d.name}</b> · {d.width} mm · {d.online?'Agent online':d.paired?'Agent offline':'Awaiting pairing'}</span><Button variant="ghost" disabled={busy} onClick={async()=>{setBusy(true);try{await send('printing/devices/',{id:d.id},'DELETE');client.invalidateQueries({queryKey:['print-devices']});}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}>Unpair</Button></div>)}
    <p className="muted-small">Online indicates that the agent is connected. Spool acceptance does not prove paper output; check the receipt if the printer is disconnected or out of paper.</p></section>;
}

export function PrintActions({id,width,auto=false}:{id:string;width:number;auto?:boolean}){
  const devices=useQuery({queryKey:['print-devices'],queryFn:()=>api<RecordData[]>('printing/devices/'),refetchInterval:10000});
  const [device,setDevice]=useState(''),[job,setJob]=useState<RecordData|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const lock=useRef(false),started=useRef(false),key=useRef('');
  useEffect(()=>{key.current=sessionStorage.getItem(`print:${id}`)||crypto.randomUUID();sessionStorage.setItem(`print:${id}`,key.current);},[id]);
  const result=useQuery({queryKey:['print-job',job?.id],queryFn:()=>api<RecordData>(`printing/jobs/${job!.id}/`),enabled:!!job,refetchInterval:q=>['queued','processing'].includes(q.state.data?.status||'queued')?1500:false});
  const current=result.data||job;
  async function direct(target?:string){if(lock.current)return;lock.current=true;setBusy(true);setError('');try{const selected=target||device||devices.data?.find(d=>d.online)?.id;if(!selected)throw Error('No paired agent is online. Use Browser print or start your agent.');const saved=await send<RecordData>('printing/jobs/',{invoice:id,device:selected,width,idempotency_key:key.current});setJob(saved);}catch(e){setError((e as Error).message);}finally{lock.current=false;setBusy(false);}}
  useEffect(()=>{if(auto&&devices.isSuccess&&!started.current){started.current=true;direct();}},[auto,devices.isSuccess]);
  const pending=!!current&&['queued','processing'].includes(current.status);
  const terminal=!!current&&!pending;
  return <div className="print-controls"><div className="actions"><Button onClick={()=>window.print()}>Browser print</Button><a className="btn btn-outline" href={`/api/invoices/${id}/pdf/?download=1`}>Download PDF</a><select aria-label="Direct printer" value={device} disabled={pending} onChange={e=>setDevice(e.target.value)}><option value="">First online printer</option>{devices.data?.map(d=><option key={d.id} value={d.id}>{d.name} · {d.online?'online':'offline'}</option>)}</select><Button variant="outline" disabled={busy||pending||terminal} onClick={()=>direct()}>{busy?'Sending…':'Direct print / retry request'}</Button></div>
    {current&&<p role="status">{current.status==='spooled'?'Accepted by the local spooler / printer connection. Paper output is not confirmed.':current.status==='queued'?'Waiting for local agent…':current.status==='processing'?'Agent is sending the receipt…':`${current.status}: ${current.detail}`}</p>}
    {terminal&&<Button variant="ghost" onClick={()=>{key.current=crypto.randomUUID();sessionStorage.setItem(`print:${id}`,key.current);setJob(null);}}>Request another copy (check paper first)</Button>}
    {(error||result.error||devices.error)&&<p className="form-error" role="alert">{error||result.error?.message||devices.error?.message} Use Browser print if needed.</p>}
    <p className="muted-small">Browser print opens the system dialog. Choose the correct paper width, 100% scale, no headers/footers and no extra margins. Direct printing needs a paired compatible ESC/POS printer.</p></div>;
}

export function ThermalReceipt({id}:{id:string}){
  const [width,setWidth]=useState(80),[auto,setAuto]=useState(false),[height,setHeight]=useState(200);const receipt=useRef<HTMLElement>(null);
  const data=useQuery({queryKey:['thermal',id],queryFn:()=>api<RecordData>(`invoices/${id}/receipt/`),refetchOnWindowFocus:true});
  const session=useQuery({queryKey:['session'],queryFn:()=>api<Session>('auth/me/')});
  useEffect(()=>{const p=new URLSearchParams(window.location.search);setWidth(p.get('width')==='58'?58:p.get('width')==='80'?80:Number(session.data?.business?.settings.receipt_width||80));setAuto(p.get('direct')==='1');},[session.data]);
  useEffect(()=>{if(!receipt.current)return;const observer=new ResizeObserver(()=>{if(receipt.current)setHeight(Math.ceil(receipt.current.scrollHeight*25.4/96)+4);});observer.observe(receipt.current);return()=>observer.disconnect();},[data.data,width]);
  if(data.isPending||session.isPending)return <Loading/>;if(data.error||!data.data)return <ErrorState error={data.error} retry={()=>data.refetch()}/>;
  const r=data.data;
  return <div className="thermal-page"><style>{`@media print { @page { size: ${width}mm ${height}mm; margin: 0; } html,body { width: ${width}mm!important; margin:0!important; padding:0!important; } }`}</style><div className="print-controls"><Link href={`/invoices/${id}`} className="text-link">← Back to invoice</Link><h1>Thermal receipt</h1><Field label="Receipt width"><select value={width} onChange={e=>setWidth(Number(e.target.value))}><option value="58">58 mm</option><option value="80">80 mm</option></select></Field><PrintActions id={id} width={width} auto={auto}/></div>
    <article className="thermal-receipt" data-width={width} ref={receipt} style={{width:`${width}mm`}}><header><h2>{r.business.name}</h2><p>{r.business.address}</p><p>{r.business.mobile}</p>{r.business.gstin&&<p>GSTIN {r.business.gstin}</p>}</header><div className="thermal-rule"><b>{r.number}</b><p>{r.date} · {r.status.toUpperCase()}</p><p>{r.customer.name}<br/>{r.customer.mobile}</p></div>{r.status==='cancelled'&&<p><b>CANCELLED</b> · Refunded {currency(r.refunded)}<br/>{r.cancellation_reason}</p>}
    {r.items.map((item:RecordData,i:number)=><div className="thermal-item" key={i}><b>{item.description}</b><div><span>{Number(item.quantity)} {item.unit} × {currency(item.unit_price)}{item.price_includes_tax?" incl. tax":""}</span><strong>{currency(item.total)}</strong></div></div>)}
    <div className="thermal-rule">{[['Subtotal',r.subtotal],['Discount',r.discount],['CGST',r.cgst],['SGST',r.sgst],['IGST',r.igst]].filter(([label,value])=>label==='Subtotal'||Number(value)>0).map(([label,value])=><div className="thermal-row" key={label}><span>{label}</span><span>{currency(value)}</span></div>)}<div className="thermal-row thermal-total"><b>TOTAL</b><b>{currency(r.total)}</b></div><div className="thermal-row"><span>{r.status==='cancelled'?'Received before refund':'Paid'}</span><span>{currency(r.paid_amount)}</span></div><div className="thermal-row"><b>Pending</b><b>{currency(r.balance)}</b></div></div>
    {r.qr_image&&<div className="thermal-qr"><img src={r.qr_image} alt={`UPI QR for ${currency(r.balance)}`}/><p>Scan to pay {currency(r.balance)}<br/>{r.business.upi_id}</p></div>}<footer>{r.business.invoice_footer}<br/>Billora</footer></article></div>;
}
