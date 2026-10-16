'use client';
import Link from 'next/link';
import { PasswordChange } from './password-change';
import { usePathname, useRouter } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, send, type Session } from '@/lib/api';
import { useEffect, useState, createContext, useContext } from 'react';
import { LayoutDashboard, Package, Users, ReceiptText, ChartNoAxesCombined, Wallet, Settings2, LogOut, Sparkles, Menu, X, ChevronDown, Shield, Layers3, Flag, ScrollText, Building2, ArrowUpRight } from 'lucide-react';
import { Loading, ErrorState } from './common';
import { Button } from './ui/button';
import { useNotice } from './providers';

const SessionContext = createContext<Session | null>(null);
export const useSession = () => useContext(SessionContext)!;
export function Logo() { return <Link href="/" className="logo"><span className="logo-mark"><Layers3 size={24} strokeWidth={2.5}/></span>billora<span className="logo-dot">.</span></Link>; }
export function Shell({children, admin = false}: {children: React.ReactNode; admin?: boolean}) {
  const {data, error, isPending, refetch} = useQuery({queryKey: ['session'], queryFn: () => api<Session>('auth/me/'), retry: false});
  const path = usePathname(); const router = useRouter(); const client = useQueryClient(); const notice = useNotice(); const [open, setOpen] = useState(false);
  useEffect(() => { if (error && 'status' in error && error.status === 401) router.replace('/login'); }, [error, router]);
  useEffect(() => {setOpen(false);}, [path]);
  if (isPending) return <div className="screen-center"><Loading/></div>;
  if (error) return <div className="screen-center"><ErrorState error={error} retry={() => refetch()}/><Link href="/login">Go to sign in</Link></div>;
  if (!data) return null;
  if (data.user.must_change_password) return <main className="main-content" style={{maxWidth:760,margin:'auto'}}><Logo/><div style={{marginTop:30}}><PasswordChange required onDone={()=>router.replace(data.user.is_superuser?'/super-admin':'/dashboard')}/></div><Button variant="ghost" onClick={async()=>{await send('auth/logout/',{});client.clear();router.replace('/login');}}>Sign out</Button></main>;
  if (admin && !data.user.is_superuser) return <div className="screen-center"><h1>Access restricted</h1><Link href="/dashboard">Back to dashboard</Link></div>;
  if (!admin && !data.business) return <div className="screen-center"><h1>Platform administrator</h1><Button asChild><Link href="/super-admin">Open platform dashboard</Link></Button></div>;
  if (!admin && !data.business?.is_active) return <div className="screen-center"><h1>Business suspended</h1><p>Contact your platform administrator.</p><Button onClick={async () => {await send('auth/logout/', {}); client.clear(); router.replace('/login');}}>Sign out</Button></div>;
  const navigation = admin ? [ ['Overview', '/super-admin', Shield], ['Businesses', '/super-admin/businesses', Building2], ['Subscription plans', '/super-admin/plans', Layers3], ['Feature flags', '/super-admin/flags', Flag], ['Audit logs', '/super-admin/audit', ScrollText] ] as const : [ ['Overview', '/dashboard', LayoutDashboard], ['Invoices', '/invoices', ReceiptText], ['Products', '/products', Package], ['Customers', '/customers', Users], ['Customer Collection', '/collection', Wallet], ['Payments', '/payments', Wallet], ['Reports', '/reports', ChartNoAxesCombined] ] as const;
  return <SessionContext.Provider value={data}><div className="app-shell">{open && <button className="sidebar-overlay" aria-label="Close navigation" onClick={() => setOpen(false)}/>}
    <aside className={`sidebar ${open ? 'sidebar-open' : ''}`}><div className="sidebar-brand"><Logo/><button className="mobile-only" onClick={() => setOpen(false)} aria-label="Close menu"><X size={20}/></button></div>
      <div className="business-switch"><div className="business-avatar">{(data.business?.name || 'Admin').slice(0, 1).toUpperCase()}</div><div><strong>{data.business?.name || 'Platform admin'}</strong><small>{admin ? 'Administration' : 'Your workspace'}</small></div><ChevronDown size={15}/></div>
      <div className="nav-label">{admin ? 'PLATFORM' : 'WORKSPACE'}</div><nav>{navigation.map(([label, href, Icon]) => <Link key={href} href={href} className={`nav-item ${path === href || (href !== '/super-admin' && path.startsWith(`${href}/`)) ? 'active' : ''}`}><Icon size={19}/>{label}{label === 'Invoices' && <span className="nav-hint">↗</span>}</Link>)}</nav>
      <div className="sidebar-bottom">{!admin && <div className="launch-card"><span><Sparkles size={16}/> A little head start</span><p>Every feature. Yours to use.</p><Link href="/pricing">Free during launch <ArrowUpRight size={14}/></Link></div>}
        {!admin && <Link href="/settings" className={`nav-item ${path === '/settings' ? 'active' : ''}`}><Settings2 size={19}/>Business settings</Link>}
        <Link className="profile-card" href={admin ? '/super-admin' : '/profile'}><div className="avatar">{data.user.first_name.slice(0, 1) || 'A'}</div><div><strong>{data.user.first_name || data.business?.name || 'Administrator'}</strong><small>{data.role}</small></div></Link>
        <button className="logout" onClick={async () => {try {await send('auth/logout/', {}); client.clear(); router.replace('/login');} catch(e) {notice((e as Error).message, true);}}}><LogOut size={15}/>Sign out</button></div>
    </aside><div className="main-shell"><header className="topbar"><div className="breadcrumb"><button className="mobile-only" aria-label="Open menu" onClick={() => setOpen(true)}><Menu size={21}/></button><span>{admin ? 'Platform' : data.business?.name}</span><span>/</span><strong>{navigation.find(([,href]) => path === href)?.[0] || (path === '/invoices/new' ? 'Create invoice' : 'Workspace')}</strong></div><div className="actions"><span className="launch-pill"><span/> Free launch</span><Link href="/profile" className="avatar avatar-small" aria-label="Open profile">{data.user.first_name.slice(0,1)}</Link></div></header><main className="main-content">{children}</main><footer className="app-footer"><span>Made for the way you do business.</span><span>Billora · INR</span></footer></div></div></SessionContext.Provider>;
}
