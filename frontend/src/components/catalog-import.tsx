'use client';
import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api, send, type RecordData } from '@/lib/api';
import { currency, human } from '@/lib/utils';
import { Modal, Loading, Pagination } from './common';
import { Button } from './ui/button';

export function CatalogImport({file, onClose}: {file?: File; onClose:()=>void}) {
  const client = useQueryClient();
  const [report,setReport]=useState<RecordData|null>(null);
  const [error,setError]=useState(''); const [busy,setBusy]=useState(false);
  const [confirmed,setConfirmed]=useState(false); const [finished,setFinished]=useState(false);
  const [search,setSearch]=useState(''); const [page,setPage]=useState(1);
  const [attempt,setAttempt]=useState(0);
  async function request(path:string, body:RecordData={}) {
    if (!file) return send<RecordData>(path,body);
    const form=new FormData(); form.set('file',file);
    Object.entries(body).forEach(([key,value])=>form.set(key,String(value)));
    return api<RecordData>(path,{method:'POST',body:form});
  }
  useEffect(()=>{let alive=true;
    setError(''); setReport(null);
    request('products/catalog-preview/').then(data=>{if(alive)setReport(data);}).catch(e=>{if(alive)setError(e.message);});
    return ()=>{alive=false;};
  },[file,attempt]);
  async function importNow() {
    if(!report||!confirmed||busy)return;
    setBusy(true);setError('');
    try {const result=await request('products/catalog-import/',{confirmed:true,confirmation_token:report.confirmation_token});
      setReport(result);setFinished(true);void client.invalidateQueries();
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  function downloadReport() {
    const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));
    const anchor=document.createElement('a');anchor.href=url;anchor.download=finished?'inventory-import-report.json':'inventory-preview.json';anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  const rows=(report?.rows||[]).filter((r:RecordData)=>`${r.name} ${r.sku} ${r.brand} ${r.category}`.toLowerCase().includes(search.toLowerCase()));
  return <Modal wide title={finished?'Inventory import complete':'Review starter grocery catalog'} onClose={()=>{if(!busy)onClose();}}>
    {!report&&!error&&<Loading/>}
    {report&&<>
      <p className="muted">{file?.name||'Billora researched starter catalog'} · <strong>{report.business_name}</strong></p>
      <div className="summary-grid catalog-summary"><div><small>{finished?'Created':'New products'}</small><strong>{report.create_count}</strong></div><div><small>Existing SKUs preserved</small><strong>{report.skipped_count}</strong></div><div><small>New products needing a price</small><strong>{report.needs_review_count}</strong></div><div><small>Stock per new SKU</small><strong>100</strong></div></div>
      <div className="notice-box">National averages and public retailer observations are reference prices; check them against your shop prices. Each multipack is one stock unit. Prices include tax where indicated. Unknown GST rates, costs, MRPs and barcodes stay blank. Products without a price stay inactive until you edit and activate them. Existing stock and prices are preserved.</div>
      <div className="catalog-preview-toolbar"><input aria-label="Search catalog preview" placeholder="Search products, brands or categories…" value={search} onChange={e=>{setSearch(e.target.value);setPage(1);}}/><Button variant="outline" size="sm" onClick={downloadReport}>Download {finished?'report':'preview'}</Button></div>
      <div className="table-wrap catalog-table"><table><thead><tr><th>Product / pack</th><th>Price / status</th><th>Source</th><th>Stock / action</th></tr></thead><tbody>{rows.slice((page-1)*20,page*20).map((r:RecordData)=><tr key={r.sku}>
        <td><strong>{r.name}</strong><small className="catalog-meta">{r.category}<br/>{r.sku}</small></td>
        <td><strong>{r.selling_price===null?'Price needed':currency(r.selling_price)}</strong><small className="catalog-meta">{human(r.price_verification_status)}<br/>{r.price_includes_tax?'Tax included':'Tax excluded'}<br/>MRP: {r.mrp===null?'Unknown':currency(r.mrp)}</small></td>
        <td>{r.price_source_url?<a className="text-link" href={r.price_source_url} target="_blank" rel="noopener noreferrer">{r.price_type==='national_average'?'DoCA national reference':'Retailer source'}</a>:<span>Shopkeeper review</span>}<small className="catalog-meta">{r.price_checked_date||'Not checked'}</small><details><summary>Source notes</summary><p className="muted-small">{r.source_notes}</p></details></td>
        <td><strong>{r.action==='skipped_existing'?Number(r.existing_stock):100} {r.unit}</strong><small className="catalog-meta">{human(r.action)}{r.action==='skipped_existing'&&<><br/>Current price: {r.existing_selling_price===null?'Unset':currency(r.existing_selling_price)}</>}</small></td>
      </tr>)}</tbody></table></div>
      <Pagination page={page} count={rows.length} next={page*20<rows.length} previous={page>1} onChange={setPage}/>
      {!finished&&<label className="check-label catalog-confirm"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>I reviewed these reference prices and confirm 100 opening stock units for each new SKU in {report.business_name}.</label>}
      <div className="form-actions"><Button variant="outline" disabled={busy} onClick={onClose}>{finished?'Done':'Cancel'}</Button>{!finished&&<Button disabled={!confirmed||busy||!report.create_count} onClick={importNow}>{busy?'Importing…':'Confirm import'}</Button>}</div>
    </>}
    {error&&<div className="form-error" role="alert"><p>{error}</p>{!finished&&<Button variant="outline" disabled={busy} onClick={()=>{setConfirmed(false);setAttempt(attempt+1);}}>Reload preview</Button>}</div>}
  </Modal>;
}
