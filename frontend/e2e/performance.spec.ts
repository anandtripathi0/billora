import { test, expect } from '@playwright/test';
import { writeFileSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

test('authentication, session navigation and warm timings', async ({page}, info) => {
  test.skip(!process.env.PERF_PHASE, 'Opt-in measurement against an isolated database.');
  test.setTimeout(900000);
  const samples:Record<string,number[]> = {}; const requests:string[] = [];
  const errors:string[]=[]; page.on('pageerror',e=>errors.push(e.message));
  const cdp = await page.context().newCDPSession(page); await cdp.send('Performance.enable');
  page.on('request',r=>{const p=new URL(r.url()).pathname;if(p.startsWith('/api/'))requests.push(p);});
  async function timed(name:string, action:()=>Promise<void>) {const start=Date.now();await action();(samples[name]??=[]).push(Date.now()-start);}
  const email=`browser-perf-${Date.now()}-${info.project.name}@example.com`;const password='Browser-Performance#2026';
  await timed('homepage',async()=>{await page.goto('/');await expect(page.getByRole('link',{name:/get started free/i}).first()).toBeVisible();});
  await page.goto('/register');
  await page.getByLabel('Your full name',{exact:true}).fill('Performance Test');
  await page.getByLabel('Business name',{exact:true}).fill('Isolated performance test');
  await page.getByLabel('Mobile number',{exact:true}).fill('9876543212');
  await page.getByLabel('Email address',{exact:true}).fill(email);
  await page.getByLabel('Password',{exact:true}).fill(password);
  await page.getByLabel('Confirm password',{exact:true}).fill(password);
  await timed('registration_to_dashboard',async()=>{await page.getByRole('button',{name:'Create free account',exact:true}).click();await expect(page.getByText("Today's sales",{exact:true})).toBeVisible({timeout:120000});});
  for(let i=0;i<3;i++) {
    await page.getByRole('button',{name:'Sign out',exact:true}).click();await expect(page).toHaveURL(/\/login/,{timeout:90000});
    await page.getByLabel('Email address',{exact:true}).fill(email);await page.getByLabel('Password',{exact:true}).fill(password);
    await timed('login_to_dashboard',async()=>{await page.getByRole('button',{name:'Sign in to your workspace',exact:true}).click();await expect(page.getByText("Today's sales",{exact:true})).toBeVisible({timeout:120000});});
    const before=requests.filter(p=>p==='/api/auth/me/').length;
    await timed('products_navigation',async()=>{await page.locator('nav').getByRole('link',{name:'Products',exact:true}).click();await expect(page.getByLabel('Search products',{exact:true})).toBeVisible();});
    await timed('dashboard_navigation',async()=>{await page.locator('nav').getByRole('link',{name:'Overview',exact:true}).click();await expect(page.getByText("Today's sales",{exact:true})).toBeVisible();});
    expect(requests.filter(p=>p==='/api/auth/me/').length).toBe(before);
  }
  await page.reload();await expect(page.getByText("Today's sales",{exact:true})).toBeVisible({timeout:120000});
  const counts=Object.fromEntries([...new Set(requests)].map(p=>[p,requests.filter(r=>r===p).length]));
  expect(errors).toEqual([]);
  if(process.env.PERF_PHASE==='after')expect(counts['/api/auth/csrf/']).toBe(1);
  mkdirSync(resolve('../.buildtemp'),{recursive:true});
  const metrics = await cdp.send('Performance.getMetrics');
  const browserCpu = Object.fromEntries(metrics.metrics.filter((m:{name:string})=>['ScriptDuration','LayoutDuration','RecalcStyleDuration','TaskDuration'].includes(m.name)).map((m:{name:string,value:number})=>[m.name,m.value]));
  writeFileSync(resolve(`../.buildtemp/browser-${process.env.PERF_PHASE}-${info.project.name}.json`),JSON.stringify({samples,counts,errors,browserCpu},null,2));
});
