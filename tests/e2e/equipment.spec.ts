import { expect, test, type Page } from '@playwright/test';
import jsQR from 'jsqr';

test.use({ trace: 'off', ignoreHTTPSErrors: true });
async function login(page: Page, master: boolean) {
  await page.getByLabel('Логин', { exact: true }).fill(`${process.env.E2E_LOGIN!}-${master ? 'master-' : ''}t11-qr`);
  await page.getByLabel('Пароль или ПИН').fill(process.env.E2E_PASSWORD!);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Выйти', exact: true })).toBeVisible();
}

test('equipment URL preserves login destination, scoped history and prefilled creation on small screens', async ({ page, browser }, testInfo) => {
  await page.setViewportSize({width:360,height:800});
  await page.goto('/'); await login(page, true);
  const catalog = await (await page.request.get('/api/v1/catalog/equipment?limit=200')).json();
  const equipment = catalog.items.find((item: {name:string})=>item.name==='Демо насос Т04');
  const path = `/equipment/${equipment.id}`;
  await page.goto(path);
  await expect(page.getByRole('heading',{name:equipment.name,exact:true}).first()).toBeVisible();
  const card = await (await page.request.get(`/api/v1/equipment/${equipment.id}`)).json();
  let destination = path;
  if (new URL(page.url()).protocol === 'https:') {
    expect(card.public_url).toBe(new URL(path, page.url()).href);
    const qr = page.getByRole('img',{name:`QR: ${equipment.name}`,exact:true});
    await expect(qr).toBeVisible();
    const pixels = await qr.evaluate(async (element: HTMLImageElement) => {
      await element.decode();
      const canvas=document.createElement('canvas'); canvas.width=512; canvas.height=512;
      const context=canvas.getContext('2d')!; context.drawImage(element,0,0,512,512);
      return Array.from(context.getImageData(0,0,512,512).data);
    });
    destination=jsQR(new Uint8ClampedArray(pixels),512,512)!.data;
    expect(destination).toBe(card.public_url);
    for(const name of ['Скачать QR','Скачать наклейку']) {
      const image = await page.getByRole('link',{name,exact:true}).evaluate(async (element: HTMLAnchorElement) => {
        const image=new Image(); image.src=element.href; await image.decode();
        const canvas=document.createElement('canvas'); canvas.width=image.naturalWidth; canvas.height=image.naturalHeight;
        const ctx=canvas.getContext('2d')!; ctx.drawImage(image,0,0);
        return {width:canvas.width,height:canvas.height,pixels:Array.from(ctx.getImageData(0,0,canvas.width,canvas.height).data)};
      });
      expect(jsQR(new Uint8ClampedArray(image.pixels),image.width,image.height)?.data).toBe(card.public_url);
      const downloaded=page.waitForEvent('download'); await page.getByRole('link',{name,exact:true}).click();
      const download=await downloaded; expect(download.suggestedFilename()).toContain(equipment.id);
      expect(await download.failure()).toBeNull();
    }
    await page.emulateMedia({media:'print'});
    await expect(page.getByRole('navigation',{name:'Разделы приложения'})).not.toBeVisible();
    await expect(qr).toBeVisible();
    await page.screenshot({path:testInfo.outputPath('equipment-print.png')});
    await page.emulateMedia({media:'screen'});
  } else {
    expect(card.public_url).toBeNull();
    await expect(page.getByText('QR доступен на HTTPS-стенде.')).toBeVisible();
  }
  await page.getByRole('button',{name:'Выйти',exact:true}).click();
  await page.goto(destination); await login(page,true);
  await expect(page).toHaveURL(new RegExp(`${path}$`));
  await page.getByRole('link',{name:'Создать наряд',exact:true}).click();
  await expect(page.getByRole('button',{name:equipment.name,exact:true})).toHaveAttribute('aria-pressed','true');
  await expect(page.locator('.choice-group').filter({has:page.locator('legend', {hasText:'Участок'})}).getByRole('button',{pressed:true})).toHaveCount(1);
  const assignee = page.locator('select[name="assignee_id"]');
  const lookup = await browser.newContext({baseURL:new URL(page.url()).origin,ignoreHTTPSErrors:true});
  let workerId: string;
  try {
    const worker=await lookup.newPage(); await worker.goto('/'); await login(worker,false);
    workerId=(await (await worker.request.get('/api/v1/auth/me')).json()).user.id;
  } finally {await lookup.close();}
  await assignee.selectOption(workerId);
  const description=`T11 QR ${crypto.randomUUID()}`;
  await page.getByLabel('Описание работ',{exact:true}).fill(description);
  const creation=page.waitForRequest(request=>request.url().endsWith('/api/v1/work-orders')&&request.method()==='POST');
  await page.getByRole('button',{name:'Выдать наряд',exact:true}).click();
  const request=await creation;
  await expect(page).toHaveURL(/\/orders\/[0-9a-f-]+$/);
  const orderId=new URL(page.url()).pathname.split('/').at(-1)!;
  const body=request.postDataJSON();
  expect(body.equipment_id).toBe(equipment.id); expect(body.area_id).toBe(equipment.area_id);
  const me=await (await page.request.get('/api/v1/auth/me')).json();
  const headers={'Origin':new URL(page.url()).origin,'X-CSRF-Token':me.csrf_token,'Idempotency-Key':request.headers()['idempotency-key']};
  const replay=await page.request.post('/api/v1/work-orders',{headers,data:body});
  expect(replay.status()).toBe(201); expect((await replay.json()).id).toBe(orderId);
  expect((await page.request.post('/api/v1/work-orders',{headers,data:{...body,description:'Conflict'}})).status()).toBe(409);
  const action={action:'reprioritize',expected_version:1,priority:'high'};
  expect((await page.request.post(`/api/v1/work-orders/${orderId}/actions`,{headers:{...headers,'Idempotency-Key':crypto.randomUUID()},data:action})).status()).toBe(200);
  expect((await page.request.post(`/api/v1/work-orders/${orderId}/actions`,{headers:{...headers,'Idempotency-Key':crypto.randomUUID()},data:action})).status()).toBe(409);
  await page.goto(path);
  await expect(page.getByRole('region',{name:'Последние 10 нарядов'})).toContainText(description);
  for(const width of [360,390]) {
    await page.setViewportSize({width,height:844});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:testInfo.outputPath(`equipment-${width}.png`)});
  }
  const context=await browser.newContext({baseURL:new URL(page.url()).origin,ignoreHTTPSErrors:true,viewport:{width:390,height:844}});
  try {
    const worker=await context.newPage(); await worker.goto(destination); await login(worker,false);
    await expect(worker).toHaveURL(new RegExp(`${path}$`));
    await expect(worker.getByRole('link',{name:'Создать наряд',exact:true})).toHaveCount(0);
    await worker.locator(`.equipment-orders a[href="/orders/${orderId}"]`).click();
    await expect(worker.getByText(description,{exact:true})).toBeVisible();
    await worker.getByRole('link',{name:'Оборудование и история нарядов',exact:true}).click();
    await expect(worker).toHaveURL(new RegExp(`${path}$`));
  } finally {await context.close();}
});
