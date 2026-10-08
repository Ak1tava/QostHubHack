import { Buffer } from 'node:buffer';
import { expect, test, type Page } from '@playwright/test';

test.use({ trace: 'off' });
const scenario = 't12-template';
async function login(page: Page, master: boolean) {
  await page.goto('/');
  await page.getByLabel('Логин', { exact: true }).fill(`${process.env.E2E_LOGIN!}-${master ? 'master-' : ''}${scenario}`);
  await page.getByLabel('Пароль или ПИН').fill(process.env.E2E_PASSWORD!);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('heading', { name: master ? 'Панель смены' : 'Мои наряды', exact: true })).toBeVisible();
}
async function action(page: Page, name: string) {
  await page.getByRole('button', { name, exact: true }).click();
  await page.getByRole('button', { name: 'Применить', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Применить', exact: true })).toHaveCount(0);
}
async function photo(page: Page, type: 'до' | 'после') {
  const encoded = await page.evaluate(() => {
    const canvas = document.createElement('canvas'); canvas.width = 800; canvas.height = 600;
    const context = canvas.getContext('2d')!; context.fillStyle = '#c88'; context.fillRect(0, 0, 800, 600);
    context.fillStyle = '#333'; context.fillRect(150, 100, 400, 200);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  const section = page.getByRole('region', { name: `Фото ${type}`, exact: true });
  await section.locator('input[type="file"]').setInputFiles({ name: 'synthetic.png', mimeType: 'image/png', buffer: Buffer.from(encoded, 'base64') });
  await expect(section.getByAltText('Предпросмотр выбранного фото')).toBeVisible();
  const response = page.waitForResponse(response => response.url().endsWith('/photos') && response.request().method() === 'POST');
  await section.getByRole('button', { name: 'Загрузить фото', exact: true }).click();
  expect((await response).status()).toBe(201);
  await expect(section.getByAltText(`Загруженное фото ${type}`)).toBeVisible();
}

test('template refuses partial evidence and persists the complete checklist for worker and master', async ({ page, browser }) => {
  await login(page, true);
  await page.locator('.worker-card').filter({ hasText: `Исполнитель ${scenario}` }).getByRole('link', { name: 'Выдать', exact: true }).click();
  await page.getByRole('button', { name: 'Демо насос Т04', exact: true }).click();
  await expect(page.getByLabel('Шаблон', { exact: true })).toHaveValue('');
  await page.getByLabel('Шаблон', { exact: true }).selectOption('visible_leak');
  const description = `T12 синтетическая течь ${crypto.randomUUID().slice(0, 8)}`;
  await page.getByLabel('Описание работ', { exact: true }).fill(description);
  await page.getByRole('button', { name: 'Выдать наряд', exact: true }).click();
  await expect(page).toHaveURL(/\/orders\/[0-9a-f-]+$/);
  const id = new URL(page.url()).pathname.split('/').at(-1)!;
  const context = await browser.newContext({ baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173' });
  const worker = await context.newPage();
  try {
    await login(worker, false); await worker.goto(`/orders/${id}/execute`);
    await action(worker, 'Принять'); await action(worker, 'Начать работу');
    const current = await (await worker.request.get(`/api/v1/work-orders/${id}`)).json();
    const codes = worker.locator('select[name="fault_code_id"]');
    await expect.poll(() => codes.locator('option').count()).toBeGreaterThan(1);
    const code = (await codes.locator('option').nth(1).getAttribute('value'))!;
    const auth = await (await worker.request.get('/api/v1/auth/me')).json();
    const partial = await worker.request.post(`/api/v1/work-orders/${id}/submissions`, {
      headers: { Origin: new URL(worker.url()).origin, 'X-CSRF-Token': auth.csrf_token, 'Idempotency-Key': crypto.randomUUID() },
      data: { expected_version: current.version, assignment_version: current.assignment_version, work_description: 'Видимый участок восстановлен', fault_code_id: code, materials: [], no_materials_used: true, after_photo_ids: [], template_answers: [] },
    });
    expect(partial.status()).toBe(422);
    const unchanged = await (await worker.request.get(`/api/v1/work-orders/${id}`)).json();
    expect(unchanged.submission).toBeNull(); expect(unchanged.version).toBe(current.version);
    await worker.getByLabel('Выполненные работы', { exact: true }).fill('Видимый участок восстановлен');
    await codes.selectOption(code); await worker.getByLabel('Материалы не потребовались').check();
    const submit = worker.getByRole('button', { name: 'Передать на проверку', exact: true });
    await expect(submit).toBeDisabled();
    for (const item of current.template_snapshot.checklist) await worker.locator(`input[name="template-${item.id}"]`).check();
    await photo(worker, 'после'); await expect(submit).toBeDisabled();
    await photo(worker, 'до'); await expect(submit).toBeEnabled();
    await submit.click();
    const saved = worker.getByRole('region', { name: 'Сохранённый чек-лист', exact: true });
    await expect(saved).toBeVisible();
    for (const item of current.template_snapshot.checklist) await expect(saved).toContainText(`${item.label}: Выполнено`);
    const complete = await (await worker.request.get(`/api/v1/work-orders/${id}`)).json();
    expect(complete.submission.template_answers).toEqual(current.template_snapshot.checklist.map((item: { id: string }) => ({ id: item.id, checked: true })));
    expect(complete.before_photo_count).toBe(1);
    await page.goto(`/orders/${id}`);
    await expect(page.getByRole('region', { name: 'Сохранённый чек-лист', exact: true })).toContainText('Выполнено');
  } finally { await context.close(); }
});
