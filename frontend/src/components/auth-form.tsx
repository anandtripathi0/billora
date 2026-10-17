'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { api, csrfToken, send, type Session } from '@/lib/api';
import { ArrowRight, Eye, EyeOff, LoaderCircle, ShieldCheck, Sparkles } from 'lucide-react';
import { Logo } from './shell';
import { Button } from './ui/button';
import { Field, Modal } from './common';

type Mode = 'login' | 'register' | 'forgot-password';
export function AuthForm({mode}: {mode: Mode}) {
  const router = useRouter(); const client = useQueryClient();
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const [visible, setVisible] = useState(false); const [support, setSupport] = useState(false);
  const [slow, setSlow] = useState(false); const submitting = useRef(false);
  
const [serverStatus, setServerStatus] = useState<
  'checking' | 'ready' | 'failed'
>('checking');

const [retryConnection, setRetryConnection] = useState(0);

useEffect(() => {
  let cancelled = false;
  const controller = new AbortController();

  async function checkBackend() {
    setServerStatus('checking');

    for (let attempt = 0; attempt < 6; attempt++) {
      if (cancelled) return;

      try {
        const response = await fetch('/api/health/', {
          cache: 'no-store',
          signal: AbortSignal.any([
            controller.signal,
            AbortSignal.timeout(25000),
          ]),
        });

        if (response.ok) {
          if (!cancelled) setServerStatus('ready');
          return;
        }
      } catch {
        // The backend may still be waking up.
      }

      if (attempt < 5 && !cancelled) {
        await new Promise<void>((resolve) => {
          setTimeout(resolve, 5000);
        });
      }
    }

    if (!cancelled) setServerStatus('failed');
  }

  void checkBackend();

  return () => {
    cancelled = true;
    controller.abort();
  };
}, [retryConnection]);

  const session = useQuery({queryKey:['session'], queryFn:()=>api<Session>('auth/me/'), retry:false, enabled: mode !== 'forgot-password' && serverStatus === 'ready'});
  const destination = (data:Session) => data.user.must_change_password ? '/profile' : data.user.is_superuser ? '/super-admin' : '/dashboard';
  useEffect(() => { if(mode !== 'forgot-password' && serverStatus === 'ready') {void csrfToken().catch(()=>{}); router.prefetch('/dashboard');} }, [mode, router,serverStatus]);
  useEffect(() => {if(session.data)router.replace(destination(session.data));}, [session.data, router]);
  useEffect(() => {if(!busy){setSlow(false);return;}const id=setTimeout(()=>setSlow(true),8000);return()=>clearTimeout(id);},[busy]);
  async function submit(event:React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

if (serverStatus !== 'ready') {
  setError('Server is connecting. Please wait.');
  return;
}

if (submitting.current) return;
    submitting.current=true;setBusy(true);setError('');
    try {
      const data=await send<Session>(`auth/${mode}/`,Object.fromEntries(new FormData(event.currentTarget)));
      await client.cancelQueries({queryKey:['session']});client.clear();client.setQueryData(['session'],data);
      router.replace(destination(data));
    } catch(e){setError((e as Error).message);} finally{submitting.current=false;setBusy(false);}
  }
  const title=mode==='register'?'Your store starts here.':mode==='login'?'Welcome back.':'Forgot your password?';
  return <div className="auth-layout"><aside className="auth-story"><Logo/><div className="auth-story-copy"><span className="launch-pill" style={{width:'max-content'}}><Sparkles size={12}/>Currently free during launch</span><h1>Big ambitions.<br/>Small details.<br/><span>All in balance.</span></h1><p>A beautiful space to manage your invoices, inventory, and the people who keep your business moving.</p><div className="notice-box" style={{marginTop:32}}><ShieldCheck size={20}/><br/>Your business has its own private workspace, protected by secure sessions and access controls.</div></div><small>Built for independent Indian businesses.</small></aside><Link className="auth-top-link" href="/">← Back to home</Link><main className="auth-main"><div className="auth-form"><h1>{title}</h1><p>{mode==='register'?'Three details. One workspace for your business.':mode==='login'?'Sign in with your registered mobile number.':'Forgot your password? Contact Billora Support/Admin to reset your password.'}</p>
    {mode==='forgot-password'?<><Button onClick={()=>setSupport(true)}>Contact Admin / Support</Button><p className="auth-bottom"><Link href="/login">Back to sign in</Link></p></>:<form onSubmit={submit}>
      {mode==='register'&&<Field label="Store Name"><input name="store_name" autoComplete="organization" required maxLength={160} placeholder="e.g. Sharma Kirana Store"/></Field>}
      <Field label="Mobile Number"><input name="mobile" type="tel" inputMode="tel" autoComplete="username" required maxLength={20} placeholder="98765 43210"/></Field>
      <div className="password-field"><Field label="Password" hint={mode==='register'?'Use at least 10 characters. Avoid common passwords.':undefined}><input name="password" type={visible?'text':'password'} autoComplete={mode==='login'?'current-password':'new-password'} required minLength={mode==='login'?1:10} maxLength={128} placeholder="Enter your password"/><button className="password-toggle" type="button" aria-label={visible?'Hide password':'Show password'} aria-pressed={visible} onClick={()=>setVisible(!visible)}>{visible?<EyeOff size={18}/>:<Eye size={18}/>}</button></Field></div>
      {mode==='login'&&<Link href="/forgot-password" className="text-link password-link">Forgot password?</Link>}{error&&<p className="form-error" role="alert">{error}</p>}
      
{serverStatus === 'checking' && (
  <p role="status" style={{ color: '#79634D' }}>
    <LoaderCircle size={16} className="spin" />
    {' '}Connecting to Billora server…
    Please wait.
  </p>
)}

{serverStatus === 'ready' && (
  <p role="status" style={{ color: '#3F8A69' }}>
    ✓ Server connected
  </p>
)}

{serverStatus === 'failed' && (
  <div role="alert">
    <p>Server connection failed. Please try again.</p>
    <button
      type="button"
      onClick={() => setRetryConnection(n => n + 1)}
    >
      Retry Connection
    </button>
  </div>
)}

      <Button type="submit" disabled={busy || serverStatus !== 'ready'} aria-busy={busy}>{busy&&<LoaderCircle size={17} className="spin"/>}{busy?(mode==='login'?'Signing in…':'Creating account…'):(mode==='login'?'Login':'Create Account')}<ArrowRight size={17}/></Button>
      {slow&&<p role="status">The server is taking longer than usual. Please keep this page open; your request is still waiting for a response.</p>}
    </form>}
    {mode!=='forgot-password'&&<p className="auth-bottom">{mode==='login'?'New to Billora?':'Already have an account?'} <Link href={mode==='login'?'/register':'/login'}>{mode==='login'?'Create Account':'Login'}</Link></p>}
    </div></main>{support&&<Modal title="Contact your administrator" onClose={()=>setSupport(false)}><p>Contact the administrator who manages your Billora installation directly. They must independently verify that you own the account or store before resetting access.</p><p className="muted" style={{marginTop:16}}>No support email or phone number has been provided for this installation. If ownership cannot be verified, the administrator must refuse the reset.</p><div className="form-actions"><Button onClick={()=>setSupport(false)}>Close</Button></div></Modal>}</div>;
}
