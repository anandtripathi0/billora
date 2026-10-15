'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { send, type Session } from '@/lib/api';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { ArrowRight, LoaderCircle, ShieldCheck, Sparkles } from 'lucide-react';
import { Logo } from './shell';
import { Button } from './ui/button';
import { Field } from './common';

const schema = z.object({email: z.email('Enter a valid email address.').optional(), password: z.string().optional(), owner_name: z.string().optional(), business_name: z.string().optional(), mobile: z.string().optional(), confirm_password: z.string().optional()});
type Values = z.infer<typeof schema>;
type Mode = 'login' | 'register' | 'forgot-password' | 'reset-password';
export function AuthForm({mode}: {mode: Mode}) {
  const router = useRouter(); const client = useQueryClient(); const [error, setError] = useState(''); const [success, setSuccess] = useState('');
  const {register, handleSubmit, formState: {errors, isSubmitting}} = useForm<Values>({resolver: zodResolver(schema)});
  const titles = {login: ['Welcome back.', 'Good to see you. Let’s get back to business.'], register: ['Your next chapter starts here.', 'Create your free workspace. No credit card needed.'], 'forgot-password': ['Forgot your password?', 'We’ll email you a secure link to reset it.'], 'reset-password': ['A fresh start.', 'Choose a strong new password for your account.']};
  async function submit(values: Values) {
    setError(''); setSuccess('');
    if(mode === 'register' && values.password !== values.confirm_password){setError('Passwords do not match.');return;}
    try {
      const params = new URLSearchParams(window.location.search);
      const data = await send<Session & {detail?: string}>(`auth/${mode}/`, {...values, ...(mode === 'reset-password' ? {uid: params.get('uid'), token: params.get('token')} : {})});
      if (mode === 'forgot-password' || mode === 'reset-password') {setSuccess(data.detail || 'Done.'); return;}
      client.clear(); client.setQueryData(['session'], data);
      router.push(data.user.is_superuser ? '/super-admin' : '/dashboard');
    } catch(e) {setError((e as Error).message);}
  }
  return <div className="auth-layout"><aside className="auth-story"><Logo/><div className="auth-story-copy"><span className="launch-pill" style={{width: 'max-content'}}><Sparkles size={12}/> Currently free during launch</span><h1>Big ambitions.<br/>Small details.<br/><span>All in balance.</span></h1><p>A beautiful space to manage your invoices, inventory, and the people who keep your business moving.</p><div className="notice-box" style={{marginTop:32}}><ShieldCheck size={20} style={{marginBottom:8}}/><br/>Your business has its own private workspace, protected by secure sessions and access controls.</div></div><small>Built for independent Indian businesses.</small></aside><Link className="auth-top-link" href="/">← Back to home</Link><main className="auth-main"><div className="auth-form"><h1>{titles[mode][0]}</h1><p>{titles[mode][1]}</p>{success ? <div className="notice-box" role="status">{success}<br/><Link className="text-link" href="/login">Back to sign in →</Link></div> : <form onSubmit={handleSubmit(submit)}>
    {mode === 'register' && <><Field label="Your full name"><input {...register('owner_name')} autoComplete="name" placeholder="e.g. Priya Sharma" required maxLength={100}/></Field><Field label="Business name"><input {...register('business_name')} autoComplete="organization" placeholder="Your business, your identity" required maxLength={160}/></Field><Field label="Mobile number"><input {...register('mobile')} autoComplete="tel" placeholder="98765 43210" type="tel" required maxLength={20}/></Field></>}
    {mode !== 'reset-password' && <Field label="Email address"><input {...register('email')} type="email" autoComplete="email" placeholder="you@yourbusiness.com" required/>{errors.email && <span className="form-error">{errors.email.message}</span>}</Field>}
    {mode !== 'forgot-password' && <Field label={mode === 'reset-password' ? 'New password' : 'Password'} hint={mode === 'register' || mode === 'reset-password' ? 'Use at least 10 characters. Avoid common passwords.' : undefined}><input {...register('password')} type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} required minLength={mode === 'login' ? 1 : 10} maxLength={128} placeholder="Enter your password"/></Field>}
    {mode === 'register' && <Field label="Confirm password"><input {...register('confirm_password')} type="password" autoComplete="new-password" required minLength={10} maxLength={128} placeholder="Re-enter your password"/></Field>}
    {mode === 'login' && <Link href="/forgot-password" className="text-link password-link">Forgot password?</Link>}{error && <p className="form-error" role="alert">{error}</p>}
    <Button disabled={isSubmitting} type="submit">{isSubmitting ? <LoaderCircle size={17} className="spin"/> : null}{mode === 'login' ? 'Sign in to your workspace' : mode === 'register' ? 'Create free account' : mode === 'forgot-password' ? 'Send reset link' : 'Update password'}<ArrowRight size={17}/></Button></form>}
    {['login', 'register'].includes(mode) && <p className="auth-bottom">{mode === 'login' ? 'New to Billora?' : 'Already have an account?'} <Link href={mode === 'login' ? '/register' : '/login'}>{mode === 'login' ? 'Get started free' : 'Sign in'}</Link></p>}</div></main></div>;
}
