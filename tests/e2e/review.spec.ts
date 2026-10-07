import { expect, test, type Page } from '@playwright/test';

// Runs against the real API and its no-key AI worker, never a model fixture.
test.use({ trace: 'off' });
const scenario = 't07-review';
async function login(page: Page, master: boolean) {
  await page.goto('/');
  await page.getByLabel('Логин', { exact: true }).fill(`${process.env.E2E_LOGIN!}-${master ? 'master-' : ''}${scenario}`);
  await page.getByLabel('Пароль или ПИН').fill(process.env.E2E_PASSWORD!);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('heading', { name: master ? 'Панель смены' : 'Мои наряды', exact: true })).toBeVisible();
}
async function action(page: Page, label: string) {
  await page.getByRole('button', { name: label, exact: true }).click();
  await page.getByRole('button', { name: 'Применить', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Применить', exact: true })).toHaveCount(0);
}
async function report(page: Page, description: string) {
  await page.locator('textarea[name="work_description"]').fill(description);
  const codes = page.locator('select[name="fault_code_id"]');
  await expect.poll(() => codes.locator('option').count()).toBeGreaterThan(1);
  await codes.selectOption(await codes.locator('option').nth(1).getAttribute('value') as string);
  await page.getByLabel('Материалы не потребовались', { exact: true }).check();
  await page.getByRole('button', { name: 'Передать на проверку', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Предыдущий отчёт', exact: true })).toContainText(description);
}

test('no-key review permits explained rework and explicit manual acceptance with conflict and lost-response replay', async ({ page, browser }) => {
  test.setTimeout(120_000);
  const description = `T07 ручная приёмка ${crypto.randomUUID().slice(0, 8)}`;
  await login(page, true);
  await page.locator('.worker-card').filter({ hasText: `Исполнитель ${scenario}` }).getByRole('link', { name: 'Выдать', exact: true }).click();
  await page.getByRole('button', { name: 'Демо насос Т04', exact: true }).click();
  await page.getByLabel('Описание работ', { exact: true }).fill(description);
  await page.getByRole('button', { name: 'Выдать наряд', exact: true }).click();
  await expect(page).toHaveURL(/\/orders\/[0-9a-f-]+$/);
  const id = new URL(page.url()).pathname.split('/').at(-1)!;
  const context = await browser.newContext({ baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173' });
  const worker = await context.newPage();
  try {
    await login(worker, false); await worker.goto(`/orders/${id}/execute`);
    await action(worker, 'Принять'); await action(worker, 'Начать работу');
    await report(worker, 'Выполнен осмотр насоса, соединения подтянуты');
    const panel = page.getByRole('region', { name: 'Результат проверки', exact: true });
    await expect(panel).toContainText('Проверка недоступна', { timeout: 20_000 });
    expect((await (await page.request.get(`/api/v1/work-orders/${id}`)).json()).ai_review).toBeNull();
    const form = page.getByRole('form', { name: 'Приёмка мастером', exact: true });
    await form.locator('select[name="decision"]').selectOption('rework');
    await expect(form.getByRole('button', { name: 'Сохранить решение', exact: true })).toBeDisabled();
    await form.locator('textarea[name="decision_reason"]').fill('Повторно проверить соединение после пробного запуска');
    await form.getByRole('button', { name: 'Сохранить решение', exact: true }).click();
    await expect(worker.getByRole('region', { name: 'Результат проверки', exact: true })).toContainText('Повторно проверить соединение после пробного запуска');
    await expect(worker.getByRole('form', { name: 'Приёмка мастером', exact: true })).toHaveCount(0);
    await action(worker, 'Начать доработку'); await report(worker, 'Соединение проверено после пробного запуска, течи нет');
    await expect(page.getByRole('region', { name: 'Предыдущий отчёт', exact: true })).toContainText('Соединение проверено после пробного запуска, течи нет');
    await expect(form).toBeVisible({ timeout: 20_000 });
    await form.locator('select[name="decision"]').selectOption('accept');
    await expect(form.getByRole('button', { name: 'Сохранить решение', exact: true })).toBeDisabled();
    await form.locator('textarea[name="decision_reason"]').fill('Лично проверено мастером на месте');
    const requests: { body: string; key: string }[] = [];
    await page.route(`**/api/v1/work-orders/${id}/decision`, async route => {
      requests.push({ body: route.request().postData()!, key: route.request().headers()['idempotency-key'] });
      if (requests.length === 1) {
        const auth = await (await page.request.get('/api/v1/auth/me')).json();
        const current = await (await page.request.get(`/api/v1/work-orders/${id}`)).json();
        const changed = await page.request.post(`/api/v1/work-orders/${id}/actions`, { headers: { Origin: new URL(page.url()).origin, 'X-CSRF-Token': auth.csrf_token, 'Idempotency-Key': crypto.randomUUID() }, data: { action: 'reprioritize', expected_version: current.version, priority: 'high' } });
        expect(changed.status()).toBe(200);
        const response = await route.fetch(); expect(response.status()).toBe(409); await route.fulfill({ response });
      } else if (requests.length === 2) {
        const response = await route.fetch(); expect(response.status()).toBe(200); await route.abort('failed');
      } else await route.continue();
    });
    await form.getByRole('button', { name: 'Сохранить решение', exact: true }).click();
    await expect(form.getByRole('alert')).toContainText('Выберите решение заново');
    await expect(form.locator('select[name="decision"]')).toBeEnabled();
    await expect(form.locator('select[name="decision"]')).toHaveValue('');
    await form.locator('select[name="decision"]').selectOption('accept');
    await form.locator('textarea[name="decision_reason"]').fill('Лично проверено мастером на месте');
    await form.getByRole('button', { name: 'Сохранить решение', exact: true }).click();
    await expect(form.getByRole('button', { name: 'Повторить решение', exact: true })).toBeVisible();
    await form.getByRole('button', { name: 'Повторить решение', exact: true }).click();
    await expect(page.getByText('Закрыты', { exact: true })).toBeVisible();
    expect(requests).toHaveLength(3); expect(requests[2]).toEqual(requests[1]); expect(requests[1].key).not.toBe(requests[0].key);
    const current = await (await page.request.get(`/api/v1/work-orders/${id}`)).json();
    expect(current.ai_review).toBeNull(); expect(current.master_decision).toMatchObject({ decision: 'accept', reason: 'Лично проверено мастером на месте' });
  } finally { await context.close(); }
});
