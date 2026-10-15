import { test, expect } from '@playwright/test';

test('owner previews catalog, activates an unpriced SKU, invoices and safely reimports',async({page},testInfo)=>{
  test.setTimeout(600000);
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  async function post(path:string,data:unknown,method='POST'){
    const token=(await(await page.request.get('/api/auth/csrf/')).json()).csrfToken;
    const r=await page.request.fetch('/api/'+path,{method,data,timeout:60000,headers:{'X-CSRFToken':token,'Origin':'http://localhost:3000'}});
    expect(r.ok(),`${path}: ${await r.text()}`).toBe(true);return r.json();
  }
  await post('auth/register/',{owner_name:'Catalog Test',business_name:`Catalog test ${testInfo.project.name}`,email:`catalog-${Date.now()}-${testInfo.project.name}@example.com`,mobile:'9876543210',password:'Catalog#Secure2026',confirm_password:'Catalog#Secure2026'});
  await page.goto('/products');
  await page.getByRole('button',{name:'Import Starter Grocery Catalog',exact:true}).click();
  const modal=page.getByRole('dialog');await expect(modal).toContainText('200',{timeout:60000});
  await expect(modal.getByRole('button',{name:'Confirm import',exact:true})).toBeDisabled();
  expect((await(await page.request.get('/api/products/?archived=true')).json()).count).toBe(0);
  await modal.getByLabel('Search catalog preview').fill('Sunpure');await expect(modal).toContainText('Price needed');
  await page.screenshot({path:testInfo.outputPath('catalog-preview.png'),fullPage:true});
  await modal.getByRole('checkbox').check();await modal.getByRole('button',{name:'Confirm import',exact:true}).click();
  await expect(modal).toContainText('Inventory import complete',{timeout:60000});await modal.getByRole('button',{name:'Done',exact:true}).click();
  const all=await(await page.request.get('/api/products/?archived=true')).json();expect(all.count).toBe(200);
  await page.getByLabel('Needs review',{exact:true}).check();await page.getByLabel('Search products',{exact:true}).fill('Sunpure Sunflower');
  const row=page.getByRole('row').filter({hasText:'Sunpure Sunflower Oil'});await expect(row).toContainText('Price needed');await expect(row).toContainText('100');
  await row.getByRole('button',{name:/Edit Sunpure/}).click();
  await modal.getByLabel('Selling price (₹)',{exact:true}).fill('171.50');
  await modal.getByLabel('GST rate (%, blank if unknown)',{exact:true}).fill('5');
  await modal.getByLabel('Purchase price (₹, optional)',{exact:true}).fill('100');
  await modal.getByLabel('Active for invoicing (price required)',{exact:true}).check();
  await modal.getByRole('button',{name:'Save product',exact:true}).click();await expect(modal).toBeHidden();
  await page.getByLabel('Needs review',{exact:true}).uncheck();await expect(row).toContainText('₹171.50');await expect(row).toContainText('Manual');
  await page.screenshot({path:testInfo.outputPath('inventory.png'),fullPage:true});
  const products=await(await page.request.get('/api/products/?search=Sunpure%20Sunflower')).json();const product=products.results[0];
  const settings=await post('settings/',{gstin:'27ABCDE1234F1Z5',state_code:'27'},'PATCH');
  expect(settings.gstin).toBe('27ABCDE1234F1Z5');
  // The values entered above are synthetic test values, not researched tax/cost data.
  const customer=await post('customers/quick/',{name:'Catalog Test Buyer',mobile:'9876543219'});
  await page.goto('/invoices/new');await page.getByLabel('Customer',{exact:true}).selectOption(String(customer.id));
  await page.getByLabel('Find a product',{exact:true}).fill('Sunpure Sunflower');
  await expect(page.getByLabel('Add product',{exact:true})).toContainText('Sunpure Sunflower Oil');
  await page.getByLabel('Add product',{exact:true}).selectOption(String(product.id));
  await page.getByLabel('Quantity for Sunpure Sunflower Oil 1 L',{exact:true}).fill('2');
  await expect(page.getByLabel('Apply GST',{exact:true})).toBeChecked();
  await expect(page.locator('.invoice-sidebar .total-row')).toContainText('₹343.00');
  await page.getByRole('button',{name:'Save Invoice',exact:true}).click();await expect(page).toHaveURL(/\/invoices\/[0-9a-f-]+$/,{timeout:60000});
  const id=page.url().split('/').pop()!;
  const saved=await(await page.request.get(`/api/invoices/${id}/`)).json();expect(saved.total).toBe('343.00');expect(saved.cgst).toBe('8.17');expect(saved.sgst).toBe('8.16');
  expect((await(await page.request.get(`/api/products/${product.id}/`)).json()).stock).toBe('98.000');
  const pdf=await page.request.get(`/api/invoices/${id}/pdf/`);expect(pdf.ok()).toBe(true);expect((await pdf.body()).subarray(0,4).toString()).toBe('%PDF');
  await page.goto(`/print/${id}`);await expect(page.locator('.thermal-receipt')).toContainText('Sunpure Sunflower Oil 1 L');await expect(page.locator('.thermal-total')).toContainText('₹343.00');
  await page.screenshot({path:testInfo.outputPath('catalog-receipt.png'),fullPage:true});
  await page.goto('/products');await page.getByRole('button',{name:'Import Starter Grocery Catalog',exact:true}).click();
  await expect(modal).toContainText('Existing SKUs preserved');await expect(modal.getByRole('button',{name:'Confirm import',exact:true})).toBeDisabled();
  await modal.getByLabel('Search catalog preview').fill('Sunpure Sunflower');await expect(modal).toContainText('98 pack');await expect(modal).toContainText('₹171.50');await modal.getByRole('button',{name:'Cancel',exact:true}).click();
  await page.goto(`/invoices/${id}`);await page.getByRole('button',{name:'Cancel invoice',exact:true}).click();
  await page.getByLabel('Cancellation reason').fill('Inventory test returned goods');await page.getByRole('button',{name:'Confirm cancellation'}).click();
  await expect(page.getByText('Cancelled',{exact:true})).toBeVisible();
  expect((await(await page.request.get(`/api/products/${product.id}/`)).json()).stock).toBe('100.000');
  expect(errors).toEqual([]);
});
