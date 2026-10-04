import { Buffer } from 'node:buffer';
import { expect, test, type Page } from '@playwright/test';

test.use({ trace: 'off' });
const scenario = 't05-execution';
async function login(page: Page, master: boolean) {
  await page.goto('/');
  await page.getByLabel('Логин', { exact: true }).fill(`${process.env.E2E_LOGIN!}-${master ? 'master-' : ''}${scenario}`);
  await page.getByLabel('Пароль или ПИН').fill(process.env.E2E_PASSWORD!);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('heading', { name: master ? 'Панель смены' : 'Вы вошли', exact: true })).toBeVisible();
}
async function action(page: Page, label: string, reason?: string) {
  await page.getByRole('button', { name: label, exact: true }).click();
  if (reason) await page.getByLabel('Причина', { exact: true }).fill(reason);
  await page.getByRole('button', { name: 'Применить', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Применить', exact: true })).toHaveCount(0);
}
async function demoPhoto(page: Page, type: 'до' | 'после') {
  const encoded = await page.evaluate(() => {
    const canvas = document.createElement('canvas'); canvas.width = 1800; canvas.height = 1200;
    const context = canvas.getContext('2d')!;
    for (let y = 0; y < 1200; y += 12) for (let x = 0; x < 1800; x += 12) {
      context.fillStyle = `rgb(${(x * 13 + y) % 255},${(y * 7) % 255},${(x + y * 11) % 255})`; context.fillRect(x, y, 12, 12);
    }
    return canvas.toDataURL('image/png').split(',')[1];
  });
  const section = page.getByRole('region', { name: `Фото ${type}`, exact: true });
  await section.locator('input[type="file"]').setInputFiles({ name: 'camera.png', mimeType: 'image/png', buffer: Buffer.from(encoded, 'base64') });
  await expect(section.getByAltText('Предпросмотр выбранного фото')).toBeVisible();
  const uploaded = page.waitForResponse(response => response.url().endsWith('/photos') && response.request().method() === 'POST');
  await section.getByRole('button', { name: 'Загрузить фото', exact: true }).click();
  const response = await uploaded; expect(response.status()).toBe(201);
  const photo = await response.json();
  await expect(section.getByAltText(`Загруженное фото ${type}`)).toBeVisible();
  const read = await page.request.get(photo.read_url);
  expect(read.status()).toBe(200); expect(read.headers()['content-type']).toContain('image/jpeg');
  expect((await read.body()).length).toBeLessThanOrEqual(500 * 1024);
  return photo.id as string;
}

test('worker executes, compresses protected photos and retries an immutable report after a lost response', async ({ page, browser }, testInfo) => {
  await login(page, true);
  await page.locator('.worker-card').filter({ hasText: `Исполнитель ${scenario}` }).getByRole('link', { name: 'Выдать', exact: true }).click();
  await page.getByRole('button', { name: 'Демо насос Т04', exact: true }).click();
  const description = `T05 проверка исполнения ${crypto.randomUUID().slice(0, 8)}`;
  await page.getByLabel('Описание работ', { exact: true }).fill(description);
  await page.getByRole('button', { name: 'Выдать наряд', exact: true }).click();
  await expect(page).toHaveURL(/\/orders\/[0-9a-f-]+$/);
  const id = new URL(page.url()).pathname.split('/').at(-1)!;
  const context = await browser.newContext({ baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173', viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const worker = await context.newPage();
  let completed = false;
  try {
    await login(worker, false);
    await worker.getByRole('link', { name: 'Мои наряды', exact: true }).click();
    await worker.locator('.order-card').filter({ hasText: description }).click();
    await expect(worker).toHaveURL(new RegExp(`/orders/${id}/execute$`));
    await action(worker, 'В очередь'); await expect(worker.getByText('Очередь', { exact: true })).toBeVisible();
    await action(worker, 'Принять');
    await demoPhoto(worker, 'до');
    await action(worker, 'Начать работу');
    await action(worker, 'Приостановить', 'Ожидание материала'); await expect(worker.getByText('Пауза', { exact: true })).toBeVisible();
    await action(worker, 'Продолжить');
    const workDescription = worker.locator('textarea[name="work_description"]');
    await workDescription.fill('Устранена течь, проверены соединения');
    const codes = worker.locator('select[name="fault_code_id"]');
    await expect.poll(() => codes.locator('option').count(), { message: 'Synthetic work-code catalog must be seeded' }).toBeGreaterThan(1);
    await codes.selectOption(await codes.locator('option').nth(1).getAttribute('value') as string);
    await worker.getByRole('button', { name: 'Добавить материал', exact: true }).click();
    const material = worker.locator('select[name="material_id-0"]');
    await expect.poll(() => material.locator('option').count(), { message: 'Synthetic material catalog must be seeded' }).toBeGreaterThan(1);
    await material.selectOption(await material.locator('option').nth(1).getAttribute('value') as string);
    await worker.getByLabel('Количество', { exact: true }).fill('1.25');
    const afterId = await demoPhoto(worker, 'после');
    await worker.evaluate(() => window.dispatchEvent(new Event('online')));
    await expect(workDescription).toHaveValue('Устранена течь, проверены соединения');
    const sent: { body: string; key: string }[] = [];
    await worker.route(`**/api/v1/work-orders/${id}/submissions`, async route => {
      sent.push({ body: route.request().postData()!, key: route.request().headers()['idempotency-key'] });
      if (sent.length === 1) { const result = await route.fetch(); expect(result.status()).toBe(201); await route.abort('failed'); }
      else await route.continue();
    });
    await worker.getByRole('button', { name: 'Передать на проверку', exact: true }).click();
    await expect(worker.getByRole('button', { name: 'Повторить отправку', exact: true })).toBeVisible();
    await worker.getByRole('button', { name: 'Повторить отправку', exact: true }).click();
    await expect(worker.getByRole('region', { name: 'Предыдущий отчёт', exact: true })).toContainText('Устранена течь, проверены соединения');
    expect(sent).toHaveLength(2); expect(sent[1]).toEqual(sent[0]);
    expect(JSON.parse(sent[0].body)).toMatchObject({ after_photo_ids: [afterId], materials: [{ quantity: '1.25' }], no_materials_used: false });
    await expect(worker.getByText('На приёмке', { exact: true })).toBeVisible();
    await expect(worker.getByRole('button', { name: 'Передать на проверку', exact: true })).toBeDisabled();
    expect(await worker.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await worker.goto(`/orders/${id}`); await expect(worker.getByText(description, { exact: true })).toBeVisible();
    testInfo.annotations.push({ type: 'photo-compression', description: 'Canvas JPEG ≤500 KiB; browser/mobile emulation, not physical phone or cellular timing.' });
    completed = true;
  } finally {
    if (!completed) {
      try {
        const auth = await (await page.request.get('/api/v1/auth/me')).json();
        const current = await (await page.request.get(`/api/v1/work-orders/${id}`)).json();
        if (current.allowed_actions?.includes('cancel')) await page.request.post(`/api/v1/work-orders/${id}/actions`, { headers: { Origin: new URL(page.url()).origin, 'X-CSRF-Token': auth.csrf_token, 'Idempotency-Key': crypto.randomUUID() }, data: { action: 'cancel', expected_version: current.version, reason: 'Очистка незавершённого браузерного теста' } });
      } catch { /* Keep the original failure; the environment can be reset separately. */ }
    }
    await context.close();
  }
});
