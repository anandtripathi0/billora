'use client';
import { useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api, send, type Session } from '@/lib/api';
import { Button } from './ui/button';
import { Field } from './common';
import { useNotice } from './providers';
export function PasswordChange({required=false,onDone}:{required?:boolean;onDone?:()=>void}) {
  const client=useQueryClient();const notice=useNotice();const lock=useRef(false);
  const [busy,setBusy]=useState(false);const [error,setError]=useState('');
  async function submit(e:React.FormEvent<HTMLFormElement>){
    e.preventDefault();if(lock.current)return;const form=e.currentTarget;const body=Object.fromEntries(new FormData(form));
    setError('');if(body.password!==body.confirm_password){setError('New passwords do not match.');return;}
    lock.current=true;setBusy(true);
    try{await send('profile/',body);form.reset();await client.cancelQueries({queryKey:['session']});const data=await api<Session>('auth/me/');client.setQueryData(['session'],data);notice('Password changed. Other sessions have been signed out.');onDone?.();}
    catch(err){setError((err as Error).message);}finally{lock.current=false;setBusy(false);}
  }
  return <section className="panel content-pad"><h2 style={{marginBottom:22}}>{required?'Set your new password':'Change Password'}</h2>{required&&<p className="notice-box" style={{marginBottom:20}}>Your administrator issued a temporary password. Replace it with a password only you know before opening your workspace.</p>}<form onSubmit={submit}><div className="form-grid"><Field label="Current Password"><input name="old_password" type="password" autoComplete="current-password" required maxLength={128}/></Field><Field label="New Password" hint="At least 10 characters; avoid common passwords."><input name="password" type="password" autoComplete="new-password" required minLength={10} maxLength={128}/></Field><Field label="Confirm New Password"><input name="confirm_password" type="password" autoComplete="new-password" required minLength={10} maxLength={128}/></Field></div>{error&&<p className="form-error" role="alert">{error}</p>}<div className="form-actions"><Button type="submit" disabled={busy}>{busy?'Updating…':'Update password'}</Button></div></form></section>;
}
