'use client';
import { useEffect, useRef, useState, useId, Children, isValidElement, cloneElement } from 'react';
import { Inbox, LoaderCircle, X, ChevronLeft, ChevronRight, ArrowUpRight } from 'lucide-react';
import { Button } from './ui/button';
import { currency, human } from '@/lib/utils';
import type { RecordData } from '@/lib/api';
import Link from 'next/link';

export function PageHeading({eyebrow, title, description, children}: {eyebrow?: string; title: string; description?: string; children?: React.ReactNode}) { return <div className="page-heading"><div>{eyebrow && <div className="eyebrow">{eyebrow}</div>}<h1>{title}</h1>{description && <p>{description}</p>}</div><div className="actions">{children}</div></div>; }
export function Empty({title = 'Nothing here yet', text = 'Your records will appear here.', action}: {title?: string; text?: string; action?: React.ReactNode}) { return <div className="empty"><div className="empty-icon"><Inbox size={25}/></div><h3>{title}</h3><p>{text}</p>{action}</div>; }
export function Loading() { return <div className="loading" role="status"><LoaderCircle className="spin" size={24}/> Loading your workspace…</div>; }
export function ErrorState({error, retry}: {error: Error | null; retry?: () => void}) { return <div className="error-state" role="alert"><h3>We couldn’t load this</h3><p>{error?.message || 'Check your connection and try again.'}</p>{retry && <Button variant="outline" onClick={retry}>Try again</Button>}</div>; }
export function Badge({status}: {status: string}) { return <span className={`badge badge-${status}`}>{human(status)}</span>; }
export function Pagination({page, next, previous, count, onChange}: {page: number; next: unknown; previous: unknown; count: number; onChange: (page: number) => void}) { return <div className="pagination"><span>{count} records · Page {page}</span><div><Button variant="outline" size="sm" disabled={!previous} aria-label="Previous page" onClick={() => onChange(page - 1)}><ChevronLeft size={16}/></Button><Button variant="outline" size="sm" disabled={!next} aria-label="Next page" onClick={() => onChange(page + 1)}><ChevronRight size={16}/></Button></div></div>; }
export function Modal({title, onClose, children, wide=false}: {title: string; onClose: () => void; children: React.ReactNode; wide?: boolean}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {const el = ref.current; el?.showModal(); return () => el?.close();}, []);
  return <dialog className={`modal${wide?' catalog-modal':''}`} ref={ref} onCancel={e=>{e.preventDefault();onClose();}}><div className="modal-head"><h2>{title}</h2><Button variant="ghost" size="icon" onClick={onClose} aria-label="Close dialog"><X size={20}/></Button></div>{children}</dialog>;
}
export function useSearch() { const [search, setSearch] = useState(''); const [debounced, setDebounced] = useState(''); useEffect(() => { const id = setTimeout(() => setDebounced(search), 300); return () => clearTimeout(id); }, [search]); return {search, setSearch, debounced}; }
export function InvoiceTable({rows}: {rows: RecordData[]}) { return rows.length ? <div className="table-wrap"><table><thead><tr><th>Invoice</th><th>Customer</th><th>Date</th><th>Amount</th><th>Status</th><th></th></tr></thead><tbody>{rows.map(row => <tr key={row.id}><td><Link className="text-link" href={`/invoices/${row.id}`}>{row.number}</Link></td><td><span className="cell-name">{row.customer_name}</span></td><td>{row.date}</td><td className="amount">{currency(row.total)}</td><td><Badge status={row.status}/></td><td><Link className="icon-link" href={`/invoices/${row.id}`} aria-label={`View ${row.number}`}><ArrowUpRight size={17}/></Link></td></tr>)}</tbody></table></div> : <Empty title="Your first invoice starts here" text="Create an invoice to start keeping track of your sales." action={<Button asChild><Link href="/invoices/new">Create an invoice</Link></Button>}/>; }
export function Field({label, hint, children}: {label: string; hint?: string; children: React.ReactNode}) {
  const id = useId();
  return <div className="field"><label htmlFor={id}>{label}</label>{Children.map(children, child => isValidElement<{id?:string; 'aria-describedby'?:string}>(child) && typeof child.type === 'string' && ['input','select','textarea'].includes(child.type) ? cloneElement(child, {id, 'aria-describedby': hint ? `${id}-hint` : undefined}) : child)}{hint && <small id={`${id}-hint`}>{hint}</small>}</div>;
}
