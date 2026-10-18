import { test, expect } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';

test('mobile-first sale, collection, thermal widths, paired mock printing and cancellation',async({page,request},testInfo)=>{
  test.setTimeout(600000);const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/register');
  await page.getByLabel('Store Name',{exact:true}).fill('Retail test store');
  await page.getByLabel('Mobile Number',{exact:true}).fill('9'+String(Math.floor(Math.random()*1e9)).padStart(9,'0'));
  await page.getByLabel('Password',{exact:true}).fill('Retail#Secure2026');
  await page.getByRole('button',{name:'Create Account'}).click();await expect(page).toHaveURL(/\/dashboard$/);
  async function post(path:string,data:unknown,method='POST'){
    const csrf=(await (await page.request.get('/api/auth/csrf/')).json()).csrfToken;
    const r=await page.request.fetch('/api/'+path,{method,data,headers:{'X-CSRFToken':csrf,'Origin':new URL(page.url()).origin}});
    expect(r.ok(),`${path}: ${await r.text()}`).toBe(true);return r.json();
  }
  await post('settings/',{settings:{upi_id:'test-not-a-real-payee@upi',upi_payee_name:'Retail test store',qr_default:true,receipt_width:58}},'PATCH');
  await post('products/',{name:'Premium notebook with a long product name to check receipt wrapping',sku:'THERMAL-1',selling_price:'100',purchase_price:'30',stock:'20',gst_rate:'0',unit:'pcs'});
  await page.goto('/invoices/new');await page.getByLabel('Customer mobile',{exact:true}).fill('98765 43219');
  await page.getByLabel('New customer name').fill('Rahul Retail');await page.getByLabel('Add product',{exact:true}).selectOption({index:1});
  await page.getByLabel('Quantity for Premium').fill('2');await page.getByLabel('Price for Premium').fill('125');
  await page.getByLabel('Payment status',{exact:true}).selectOption('partial');await page.getByLabel('Amount already paid').fill('50');
  await expect(page.getByLabel('Include UPI QR')).toBeChecked();
  await expect(page.locator('.invoice-sidebar')).toContainText('₹250.00');
  await page.screenshot({path:testInfo.outputPath('fast-billing.png'),fullPage:true});
  await page.getByRole('button',{name:'Save & Print',exact:true}).click();await expect(page).toHaveURL(/\/print\/.+\?direct=1/,{timeout:45000});
  const id=new URL(page.url()).pathname.split('/').pop()!;
  await expect(page.locator('.print-controls .form-error')).toContainText('No paired agent is online');
  for(const width of ['58','80']){
    await page.getByLabel('Receipt width',{exact:true}).selectOption(width);
    const receipt=page.locator('.thermal-receipt');await expect(receipt).toHaveAttribute('data-width',width);
    await expect(receipt).toContainText('₹200.00');await expect(receipt.locator('img')).toBeVisible();
    const dimensions=await receipt.evaluate(el=>({width:el.getBoundingClientRect().width,scroll:el.scrollWidth,client:el.clientWidth}));
    expect(Math.abs(dimensions.width-Number(width)*96/25.4)).toBeLessThan(1);expect(dimensions.scroll).toBeLessThanOrEqual(dimensions.client+1);
    await page.emulateMedia({media:'print'});await expect(page.getByRole('button',{name:'Browser print'})).toBeHidden();
    await page.screenshot({path:testInfo.outputPath(`thermal-${width}.png`),fullPage:true});
    if(testInfo.project.name==='chromium'){
      await page.pdf({path:testInfo.outputPath(`thermal-${width}.pdf`),preferCSSPageSize:true,printBackground:true});
    }
    await page.emulateMedia({media:'screen'});
  }
  await page.evaluate(()=>{(window as any).__printCalled=0;window.print=()=>{(window as any).__printCalled++;};});
  await page.getByRole('button',{name:'Browser print'}).click();expect(await page.evaluate(()=>(window as any).__printCalled)).toBe(1);
  await page.goto('/collection');await page.getByLabel('Search customer collection').fill('Rahul');
  const row=page.getByRole('row').filter({hasText:'Rahul Retail'});await expect(row).toContainText('₹250.00');await expect(row).toContainText('₹50.00');await expect(row).toContainText('₹200.00');
  await page.goto('/invoices/new');await page.getByLabel('Customer mobile',{exact:true}).fill('+91 9876543219');
  await expect(page.getByRole('status').filter({hasText:'Welcome back'})).toContainText('Rahul Retail');await expect(page.getByText('Previous purchases:')).toContainText('₹250.00');
  await page.getByLabel('Add product',{exact:true}).selectOption({index:1});await page.getByLabel('Payment status',{exact:true}).selectOption('paid');
  await page.getByRole('button',{name:'Save Invoice',exact:true}).click();await expect(page).toHaveURL(/\/invoices\/[0-9a-f-]+$/);
  await page.goto('/collection');await expect(page.getByRole('row').filter({hasText:'Rahul Retail'})).toContainText('₹350.00');
  // A real HTTP pairing/claim/ack exchange, with local raster rendering and mock hardware.
  const device=await post('printing/devices/',{name:'Mock counter',width:58});
  const pair=await request.post('/api/printing/agent/pair/',{data:{code:device.pairing_code}});expect(pair.ok()).toBe(true);const agent=await pair.json();
  const auth={Authorization:`Bearer ${agent.token}`};await request.post('/api/printing/agent/poll/',{data:{},headers:auth});
  const body={invoice:id,device:device.id,width:58,idempotency_key:crypto.randomUUID()};
  const first=await post('printing/jobs/',body),second=await post('printing/jobs/',body);expect(second.id).toBe(first.id);
  const claimed=await (await request.post('/api/printing/agent/poll/',{data:{},headers:auth})).json();expect(claimed.job.id).toBe(first.id);
  const python=process.env.PYTHON_EXECUTABLE || (process.platform==='win32' ? resolve('..','.venv','Scripts','python.exe') : 'python3');
  const mock=spawnSync(python,['-c',"import json,sys,tempfile;from pathlib import Path;from printer_bridge.agent import Ledger; j=json.load(sys.stdin); folder=Path(sys.argv[1]); folder.mkdir(parents=True,exist_ok=True); db=Ledger(folder/'jobs.sqlite3'); cfg={'width':58,'connection':'mock','mock_file':str(folder/'receipt.bin')}; result=db.process(j,cfg); again=db.process(j,cfg); assert result==again; print(json.dumps({'status':result[0],'detail':result[1]})); db.db.close()",testInfo.outputPath('bridge')],{cwd:resolve('..'),input:JSON.stringify(claimed.job),encoding:'utf8'});
  expect(mock.status,mock.stderr).toBe(0);const result=JSON.parse(mock.stdout);expect(result.status).toBe('spooled');
  expect((await request.post('/api/printing/agent/ack/',{data:{job:first.id,...result},headers:auth})).ok()).toBe(true);
  expect((await (await page.request.get(`/api/printing/jobs/${first.id}/`)).json()).status).toBe('spooled');
  expect((await (await page.request.get('/api/invoices/')).json()).count).toBe(2);
  await post(`invoices/${id}/pay/`,{amount:'25',method:'cash',idempotency_key:crypto.randomUUID()});
  await page.goto(`/invoices/${id}`);await page.getByRole('button',{name:'Cancel invoice',exact:true}).click();
  await page.getByLabel('Cancellation reason').fill('Full return in automated test');await page.getByRole('checkbox').check();await page.getByRole('button',{name:'Confirm cancellation'}).click();
  await expect(page.getByText('Cancelled',{exact:true})).toBeVisible();
  await page.goto('/collection');const final=page.getByRole('row').filter({hasText:'Rahul Retail'});await expect(final).toContainText('₹100.00');await expect(final).toContainText('₹0.00');
  await post('printing/devices/',{id:device.id},'DELETE');
  expect(errors).toEqual([]);
});
