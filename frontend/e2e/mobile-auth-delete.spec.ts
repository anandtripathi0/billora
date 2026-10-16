import { test, expect } from '@playwright/test';

test('three-field signup, mobile login, password settings and safe deletion',async({page,context},info)=>{
  test.setTimeout(600000);const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  const mobile='9'+String(Math.floor(Math.random()*1e9)).padStart(9,'0');const password='Mobile#Signup2026';const changed='Changed#Account2026';
  await page.goto('/forgot-password');await expect(page.getByText('Forgot your password? Contact Billora Support/Admin to reset your password.')).toBeVisible();
  await expect(page.locator('.auth-form input')).toHaveCount(0);await page.getByRole('button',{name:'Contact Admin / Support'}).click();await expect(page.getByRole('dialog')).toContainText('independently verify');await page.getByRole('button',{name:'Close',exact:true}).click();
  await page.goto('/register');await expect(page.locator('.auth-form input')).toHaveCount(3);
  await page.getByLabel('Store Name',{exact:true}).fill('Simple Mobile Store');await page.getByLabel('Mobile Number',{exact:true}).fill(mobile);await page.getByLabel('Password',{exact:true}).fill(password);
  await page.getByRole('button',{name:'Show password',exact:true}).click();await expect(page.getByLabel('Password',{exact:true})).toHaveAttribute('type','text');await page.getByRole('button',{name:'Hide password',exact:true}).click();
  await page.screenshot({path:info.outputPath('signup-three-fields.png'),fullPage:true});
  await page.getByRole('button',{name:'Create Account',exact:true}).click();await expect(page).toHaveURL(/\/dashboard$/,{timeout:60000});
  await expect(page.getByRole('heading',{name:'Hii, Simple Mobile Store! 👋'})).toBeVisible();
  expect((await context.cookies()).find(c=>c.name==='sessionid')?.httpOnly).toBe(true);
  await page.goto('/login');await expect(page).toHaveURL(/\/dashboard$/);await page.reload();await expect(page.getByRole('heading',{name:'Hii, Simple Mobile Store! 👋'})).toBeVisible();
  await page.goto('/profile');await page.getByLabel('Current Password',{exact:true}).fill(password);await page.getByLabel('New Password',{exact:true}).fill(changed);await page.getByLabel('Confirm New Password',{exact:true}).fill('Mismatch#2026');await page.getByRole('button',{name:'Update password'}).click();await expect(page.locator('.form-error[role="alert"]')).toContainText('New passwords do not match');
  await page.getByLabel('Confirm New Password',{exact:true}).fill(changed);await page.getByRole('button',{name:'Update password'}).click();await expect(page.locator('.toast[role="status"]')).toContainText('Password changed');
  if(info.project.name==='mobile')await page.getByRole('button',{name:'Open menu',exact:true}).click();
  await page.getByRole('button',{name:'Sign out',exact:true}).click();await expect(page).toHaveURL(/\/login$/);
  await expect(page.locator('.auth-form input')).toHaveCount(2);await page.getByLabel('Mobile Number',{exact:true}).fill(mobile);await page.getByLabel('Password',{exact:true}).fill(password);await page.getByRole('button',{name:'Login',exact:true}).click();await expect(page.locator('.form-error[role="alert"]')).toContainText('Invalid mobile number or password');
  await page.getByLabel('Password',{exact:true}).fill(changed);await page.getByRole('button',{name:'Login',exact:true}).click();await expect(page).toHaveURL(/\/dashboard$/,{timeout:60000});
  async function request(path:string,data?:unknown,method='POST'){
    const token=(await(await page.request.get('/api/auth/csrf/')).json()).csrfToken;
    return page.request.fetch('/api/'+path,{method,data,headers:{'X-CSRFToken':token,'Origin':new URL(page.url()).origin},timeout:60000});
  }
  const forbidden=await request('auth/reset-password/',{mobile,password:'Anonymous#Reset2026'});expect(forbidden.status()).toBe(410);
  const duplicate=await request('auth/register/',{store_name:'Duplicate',mobile:'+91'+mobile,password:changed});expect(duplicate.status()).toBe(400);
  const unusedCustomer=await(await request('customers/',{name:'Unused Buyer',mobile:'9876543201'})).json();
  const unusedProduct=await(await request('products/',{name:'Unused Item',sku:'UNUSED',selling_price:'40',stock:'5',gst_rate:'0'})).json();
  const customer=await(await request('customers/',{name:'Historical Buyer',mobile:'9876543202',address:'Private contact address'})).json();
  const product=await(await request('products/',{name:'Historical Item',sku:'HISTORY',selling_price:'100',stock:'10',gst_rate:'0'})).json();
  const created=await request('invoices/',{customer:customer.id,items:[{product:product.id,quantity:'2'}],idempotency_key:crypto.randomUUID(),paid_amount:'50',payment_method:'cash'});expect(created.status()).toBe(201);const invoice=await created.json();
  await page.goto('/customers');await page.getByRole('button',{name:'Delete Unused Buyer',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('+919876543201');await page.getByRole('button',{name:'Cancel',exact:true}).click();await expect(page.getByRole('link',{name:'Unused Buyer',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Delete Unused Buyer',exact:true}).click();await page.getByRole('button',{name:'Delete customer',exact:true}).click();await expect(page.getByRole('link',{name:'Unused Buyer',exact:true})).toHaveCount(0);expect((await page.request.get(`/api/customers/${unusedCustomer.id}/`)).status()).toBe(404);
  await page.goto(`/products/${unusedProduct.id}`);await page.getByRole('button',{name:'Delete Unused Item',exact:true}).click();await page.getByRole('button',{name:'Delete product',exact:true}).click();await expect(page).toHaveURL(/\/products$/);expect((await page.request.get(`/api/products/${unusedProduct.id}/`)).status()).toBe(404);
  await page.getByRole('button',{name:'Delete Historical Item',exact:true}).click();await page.getByRole('button',{name:'Delete product',exact:true}).click();await expect(page.getByRole('link',{name:'Historical Item',exact:true})).toHaveCount(0);
  await page.goto(`/customers/${customer.id}`);await page.getByRole('button',{name:'Delete Historical Buyer',exact:true}).click();await page.getByRole('button',{name:'Delete customer',exact:true}).click();await expect(page).toHaveURL(/\/customers$/);await expect(page.getByRole('link',{name:'Historical Buyer',exact:true})).toHaveCount(0);
  const saved=await(await page.request.get(`/api/invoices/${invoice.id}/`)).json();expect(saved.total).toBe('200.00');expect(saved.paid_amount).toBe('50.00');expect(saved.customer_snapshot.name).toBe('Historical Buyer');expect(saved.items[0].description).toBe('Historical Item');
  expect((await page.request.get(`/api/invoices/${invoice.id}/pdf/`)).status()).toBe(200);
  const archived=await(await page.request.get(`/api/products/${product.id}/`)).json();expect(archived.is_active).toBe(false);expect(Number(archived.stock)).toBe(8);
  await page.goto(`/invoices/${invoice.id}`);await expect(page.getByText('Historical Buyer',{exact:true}).first()).toBeVisible();await page.screenshot({path:info.outputPath('preserved-invoice.png'),fullPage:true});expect(errors).toEqual([]);
});

test('restricted administrator reset requires verification and a new personal password',async({page,browser},info)=>{
  test.skip(!process.env.BILLORA_TEST_ADMIN_PASSWORD,'Requires an explicitly provisioned isolated test administrator.');test.setTimeout(300000);
  const mobile='9'+String(Math.floor(Math.random()*1e9)).padStart(9,'0');const initial='Owner#BeforeReset2026';const temporary='Temporary#Account2026';const personal='Private#AfterReset2026';
  await page.goto('/register');await page.getByLabel('Store Name').fill('Verified Reset Test');await page.getByLabel('Mobile Number').fill(mobile);await page.getByLabel('Password',{exact:true}).fill(initial);await page.getByRole('button',{name:'Create Account',exact:true}).click();await expect(page).toHaveURL(/\/dashboard$/,{timeout:60000});
  const account=await(await page.request.get('/api/auth/me/')).json();
  const adminContext=await browser.newContext();const admin=await adminContext.newPage();
  await admin.goto('http://localhost:8100/admin/login/');await admin.getByLabel('Username').fill('mobile-test-admin');await admin.getByLabel('Password').fill(process.env.BILLORA_TEST_ADMIN_PASSWORD!);await admin.getByRole('button',{name:'Log in',exact:true}).click();await expect(admin).toHaveURL(/\/admin\/$/);
  await admin.goto(`http://localhost:8100/admin/billing/user/${account.user.id}/assist/`);
  await admin.getByLabel('Operation').selectOption('reset_password');await admin.getByLabel('Temporary password').fill(temporary);await admin.getByLabel('Confirm password').fill(temporary);await admin.getByLabel('Verification reference').fill('BROWSER-TEST: independently verified synthetic owner');await admin.getByLabel('Your administrator password').fill(process.env.BILLORA_TEST_ADMIN_PASSWORD!);
  await admin.getByLabel('I independently verified ownership of this account and store').check();await admin.getByRole('button',{name:'Save verified account change'}).click();await expect(admin.locator('.success')).toContainText('updated and audited');
  await page.goto('/dashboard');await expect(page).toHaveURL(/\/login$/);await page.getByLabel('Mobile Number').fill(mobile);await page.getByLabel('Password',{exact:true}).fill(temporary);await page.getByRole('button',{name:'Login',exact:true}).click();await expect(page.getByRole('heading',{name:'Set your new password'})).toBeVisible({timeout:60000});
  expect((await page.request.get('/api/products/')).status()).toBe(403);
  await page.getByLabel('Current Password',{exact:true}).fill(temporary);await page.getByLabel('New Password',{exact:true}).fill(personal);await page.getByLabel('Confirm New Password',{exact:true}).fill(personal);await page.getByRole('button',{name:'Update password'}).click();await expect(page).toHaveURL(/\/dashboard$/,{timeout:60000});await expect(page.getByRole('heading',{name:'Hii, Verified Reset Test! 👋'})).toBeVisible();await adminContext.close();
});
