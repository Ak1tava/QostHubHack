import { Buffer } from 'node:buffer';
import { expect, test, type Page } from '@playwright/test';

test.use({ trace: 'off' });
const scenario = 't10-lifecycle';
async function login(page: Page, master: boolean, name = scenario) {
  await page.goto('/');
  await page.getByLabel('Логин', { exact: true }).fill(`${process.env.E2E_LOGIN!}-${master ? 'master-' : ''}${name}`);
  await page.getByLabel('Пароль или ПИН').fill(process.env.E2E_PASSWORD!);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('heading', { name: master ? 'Панель смены' : 'Мои наряды', exact: true })).toBeVisible();
}
async function action(page: Page, label: string, reason?: string) {
  await page.getByRole('button', { name: label, exact: true }).click();
  if (reason) await page.getByLabel('Причина', { exact: true }).fill(reason);
  await page.getByRole('button', { name: 'Применить', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Применить', exact: true })).toHaveCount(0);
}
async function syntheticPhoto(page: Page, salt: number) {
  const encoded = await page.evaluate(seed => {
    const canvas = document.createElement('canvas'); canvas.width = 640; canvas.height = 480;
    const context = canvas.getContext('2d')!;
    for (let y = 0; y < 480; y += 8) for (let x = 0; x < 640; x += 8) {
      context.fillStyle = `rgb(${(x * 13 + y + seed * 31) % 255},${(y * 7 + seed * 43) % 255},${(x + y * 11 + seed * 59) % 255})`;
      context.fillRect(x, y, 8, 8);
    }
    return canvas.toDataURL('image/png').split(',')[1];
  }, salt);
  return { name: `synthetic-${salt}.png`, mimeType: 'image/png', buffer: Buffer.from(encoded, 'base64') };
}
async function submit(page: Page, description: string) {
  await page.locator('textarea[name="work_description"]').fill(description);
  const codes = page.locator('select[name="fault_code_id"]');
  await expect.poll(() => codes.locator('option').count()).toBeGreaterThan(1);
  await codes.selectOption(await codes.locator('option').nth(1).getAttribute('value') as string);
  await page.getByLabel('Материалы не потребовались', { exact: true }).check();
  await page.getByRole('button', { name: 'Передать на проверку', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Предыдущий отчёт', exact: true })).toContainText(description);
}

test('real two-session lifecycle preserves master photos and produces authoritative reports and ratings', async ({ page, browser }) => {
  test.setTimeout(150_000);
  await login(page, true);
  await page.locator('.worker-card').filter({ hasText: `Исполнитель ${scenario}` }).getByRole('link', { name: 'Выдать', exact: true }).click();
  const assigneeId = new URL(page.url()).searchParams.get('assignee_id')!;
  const periodQuery = `start_at=2000-01-01T00%3A00%3A00Z&end_at=${encodeURIComponent(new Date(Date.now() + 86400_000).toISOString())}`;
  const baseline = await (await page.request.get(`/api/v1/reports/shift?${periodQuery}&assignee_id=${assigneeId}`)).json();
  await page.getByRole('button', { name: 'Демо насос Т04', exact: true }).click();
  const description = `T10 полный цикл ${crypto.randomUUID().slice(0, 8)}`;
  await page.getByLabel('Описание работ', { exact: true }).fill(description);
  const input = page.getByLabel('Фото при выдаче · до 5', { exact: true });
  await expect(input).toBeVisible();
  await input.setInputFiles(await syntheticPhoto(page, 1));
  await page.getByRole('button', { name: 'Выдать наряд', exact: true }).click();
  await expect(page).toHaveURL(/\/orders\/[0-9a-f-]+$/);
  const id = new URL(page.url()).pathname.split('/').at(-1)!;
  await expect(page.getByRole('region', { name: 'Фото при выдаче', exact: true }).getByRole('img')).toHaveCount(1);
  const detail = await (await page.request.get(`/api/v1/work-orders/${id}`)).json();
  expect(detail.issuance_photos).toHaveLength(1);
  const workerContext = await browser.newContext({ baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173' });
  const worker = await workerContext.newPage();
  try {
    await login(worker, false); await worker.goto(`/orders/${id}/execute`);
    await expect(worker.getByRole('region', { name: 'Фото при выдаче', exact: true }).getByRole('img')).toHaveCount(1);
    expect((await worker.request.get(detail.issuance_photos[0].read_url)).status()).toBe(200);
    await action(worker, 'В очередь'); await action(worker, 'Принять'); await action(worker, 'Начать работу');
    await action(worker, 'Приостановить', 'Ожидание согласования'); await action(worker, 'Продолжить');
    await submit(worker, 'Выполнен осмотр, соединения насоса подтянуты');
    const decision = page.getByRole('form', { name: 'Приёмка мастером', exact: true });
    await expect(decision).toBeVisible();
    await decision.locator('select[name="decision"]').selectOption('rework');
    await decision.locator('textarea[name="decision_reason"]').fill('Повторить осмотр после пробного запуска');
    await decision.getByRole('button', { name: 'Сохранить решение', exact: true }).click();
    await expect(worker.getByRole('region', { name: 'Результат проверки', exact: true })).toContainText('Повторить осмотр');
    await action(worker, 'Начать доработку');
    await submit(worker, 'Пробный запуск выполнен, соединения проверены повторно');
    await expect(page.getByRole('region', { name: 'Предыдущий отчёт', exact: true })).toContainText('Пробный запуск выполнен, соединения проверены повторно');
    await expect(decision).toBeVisible();
    await decision.locator('select[name="decision"]').selectOption('accept');
    await decision.locator('select[name="score"]').selectOption('5');
    await decision.locator('textarea[name="decision_reason"]').fill('Лично проверено мастером на месте');
    await decision.getByRole('button', { name: 'Сохранить решение', exact: true }).click();
    await expect(page.getByText('Закрыты', { exact: true })).toBeVisible();
    const closed = await (await page.request.get(`/api/v1/work-orders/${id}`)).json();
    expect(closed.status).toBe('CLOSED'); expect(closed.submission.revision).toBe(2);
    expect(closed.ai_review).toBeNull();
    const own = (await (await worker.request.get('/api/v1/auth/me')).json()).user.id;
    const response = page.waitForResponse(res => res.url().includes('/api/v1/reports/shift?') && res.status() === 200);
    await page.goto(`/reports/shift?assignee_id=${own}`);
    const report = await (await response).json();
    expect(report.counts).toMatchObject({ issued: baseline.counts.issued + 1, performed: baseline.counts.performed + 1, closed: baseline.counts.closed + 1 });
    const shown = page.locator('dl[aria-label="Показатели отчёта"] dd strong');
    await expect(shown).toHaveCount(5);
    for (const [index, key] of ['issued', 'performed', 'closed', 'overdue', 'rejected'].entries()) {
      await expect(shown.nth(index)).toHaveText(new Intl.NumberFormat('ru-RU').format(report.counts[key]));
    }
    const ratingResponse = page.waitForResponse(res => res.url().includes('/api/v1/reports/rating?') && res.status() === 200);
    await page.goto(`/reports/rating?assignee_id=${own}`);
    const ratings = await (await ratingResponse).json();
    const rating = ratings.items.find((item: { worker_id: string; work_type: string }) => item.worker_id === own && item.work_type === closed.work_type);
    expect(rating).toMatchObject({ closed_count: baseline.counts.closed + 1, score: 100, components: { Q: { value: 1 }, T: { value: 1 }, R: { value: null }, V: { value: null } } });
    await expect(page.getByRole('heading', { name: 'Рейтинг исполнителей', exact: true })).toBeVisible();
    await expect(page.getByText('Нет данных', { exact: true }).first()).toBeVisible();
  } finally { await workerContext.close(); }
});
