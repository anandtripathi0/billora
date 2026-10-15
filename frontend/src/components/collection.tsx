'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { api, Page, RecordData } from '@/lib/api';
import { currency } from '@/lib/utils';
import { PageHeading, useSearch, Loading, ErrorState, Pagination } from './common';
export function CustomerCollection(){
  const {search,setSearch,debounced}=useSearch();const [page,setPage]=useState(1);
  useEffect(()=>setPage(1),[debounced]);
  const rows=useQuery({queryKey:['collection',page,debounced],queryFn:()=>api<Page<RecordData>>(`customers/?page=${page}&search=${encodeURIComponent(debounced)}`)});
  return <><PageHeading eyebrow="EVERY CUSTOMER, ONE CLEAR RECORD" title="Customer Collection" description="Lifetime purchases, payments received after refunds, and the balance still due."/><section className="panel"><div className="toolbar"><input aria-label="Search customer collection" placeholder="Search name or mobile…" value={search} onChange={e=>setSearch(e.target.value)}/></div>{rows.isPending?<Loading/>:rows.error?<ErrorState error={rows.error}/>:<div className="table-wrap"><table><thead><tr>{['Customer','Mobile','Orders','Total purchases','Payments received','Outstanding','Last purchase'].map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{rows.data?.results.map(c=><tr key={c.id}><td><Link className="text-link" href={`/customers/${c.id}`}>{c.name}</Link></td><td>{c.mobile}</td><td>{c.order_count}</td><td>{currency(c.purchases)}</td><td>{currency(c.payments_received)}</td><td>{currency(c.outstanding)}</td><td>{c.last_purchase||'—'}</td></tr>)}</tbody></table>{!rows.data?.count&&<p className="content-pad">No matching customers.</p>}</div>}{rows.data&&<Pagination {...rows.data} page={page} onChange={setPage}/>}</section></>;
}
