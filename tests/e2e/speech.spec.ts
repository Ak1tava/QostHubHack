import { Buffer } from 'node:buffer';
import { expect, test, type Page } from '@playwright/test';

test.use({ trace: 'off' });
const scenario = 't16-speech';
const speechPath = '/api/v1/speech/transcriptions';

// One second of synthetic PCM tone; no voice, personal data or external recording.
function wav(silent = false): Buffer {
  const samples = 16_000, buffer = Buffer.alloc(44 + samples * 2);
  buffer.write('RIFF', 0); buffer.writeUInt32LE(buffer.length - 8, 4); buffer.write('WAVE', 8);
  buffer.write('fmt ', 12); buffer.writeUInt32LE(16, 16); buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(1, 22); buffer.writeUInt32LE(16_000, 24); buffer.writeUInt32LE(32_000, 28);
  buffer.writeUInt16LE(2, 32); buffer.writeUInt16LE(16, 34); buffer.write('data', 36); buffer.writeUInt32LE(samples * 2, 40);
  for (let i = 0; i < samples; i++) buffer.writeInt16LE(silent ? 0 : Math.round(10_000 * Math.sin(2 * Math.PI * 440 * i / 16_000)), 44 + i * 2);
  return buffer;
}
async function login(page: Page, master: boolean) {
  await page.goto('/');
  await page.getByRole('textbox', { name: 'Логин', exact: true }).fill(`${process.env.E2E_LOGIN!}-${master ? 'master-' : ''}${scenario}`);
  await page.getByLabel('Пароль или ПИН').fill(process.env.E2E_PASSWORD!);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('heading', { name: master ? 'Панель смены' : 'Мои наряды', exact: true })).toBeVisible();
}
async function action(page: Page, label: string) {
  await page.getByRole('button', { name: label, exact: true }).click();
  await page.getByRole('button', { name: 'Применить', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Применить', exact: true })).toHaveCount(0);
}
async function recognize(page: Page, locale: 'ru' | 'kk', expected: string) {
  const speech = page.getByRole('region', { name: locale === 'kk' ? 'Дауыспен енгізу' : 'Голосовой ввод', exact: true });
  await expect(speech.getByRole('combobox')).toHaveCount(0);
  await expect(speech).toContainText(locale === 'kk' ? 'Сөйлеуді тану тек орыс тілінде қолжетімді.' : 'Распознавание речи доступно только на русском языке.');
  const pending = page.waitForResponse(response => new URL(response.url()).pathname === speechPath && response.request().method() === 'POST');
  await speech.getByLabel('Аудиофайл', { exact: true }).setInputFiles({ name: 'synthetic-tone.wav', mimeType: 'audio/wav', buffer: wav() });
  const response = await pending;
  expect(response.status()).toBe(200); expect(response.headers()['cache-control']).toBe('no-store');
  expect(await response.json()).toMatchObject({ text: expected, language: 'ru', is_mock: true });
  await expect(speech.getByRole('textbox', { name: locale === 'kk' ? 'Танылған мәтіннің нобайы' : 'Черновик расшифровки', exact: true })).toHaveValue(expected);
  await expect(speech.getByRole('status')).toContainText(locale === 'kk' ? 'Сынақ мәтіні' : 'Тестовая расшифровка');
  return speech;
}

test('Russian ASR in RU/KZ UI keeps reviewed drafts separate until explicit creation and submission', async ({ page, browser }) => {
  test.setTimeout(90_000);
  await login(page, true);
  await page.getByRole('article').filter({ hasText: `Исполнитель ${scenario}` }).getByRole('link', { name: 'Выдать', exact: true }).click();
  await page.getByRole('button', { name: 'Демо насос Т04', exact: true }).click();
  const manual = `T16 ручное описание ${crypto.randomUUID().slice(0, 8)}`;
  const field = page.getByRole('textbox', { name: 'Описание работ', exact: true });
  await field.fill(manual);
  const assigneeId = new URL(page.url()).searchParams.get('assignee_id');
  if (!assigneeId) throw new Error('Worker issuance link must preselect an assignee');
  await expect(page.getByRole('combobox', { name: 'Исполнитель', exact: true })).toHaveValue(assigneeId);
  const listUrl = `/api/v1/work-orders?assignee_id=${encodeURIComponent(assigneeId)}&limit=200`;
  const before = await (await page.request.get(listUrl)).json();
  const mutations: string[] = [];
  page.on('request', request => { if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/v1/work-orders') mutations.push(request.url()); });
  const speech = await recognize(page, 'ru', 'Заменён подшипник');
  await expect(field).toHaveValue(manual);
  await speech.getByRole('textbox', { name: 'Черновик расшифровки', exact: true }).fill('Заменить подшипник и проверить вал');
  await speech.getByRole('button', { name: 'Вставить', exact: true }).click();
  const description = `${manual}\n\nЗаменить подшипник и проверить вал`;
  await expect(field).toHaveValue(description);
  expect(mutations).toEqual([]);
  expect((await (await page.request.get(listUrl)).json()).total).toBe(before.total);
  const created = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/work-orders' && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Выдать наряд', exact: true }).click();
  expect((await created).status()).toBe(201);
  await expect(page).toHaveURL(/\/orders\/[0-9a-f-]+$/);
  const id = new URL(page.url()).pathname.split('/').at(-1)!;
  expect((await (await page.request.get(`/api/v1/work-orders/${id}`)).json()).description).toBe(description);

  const context = await browser.newContext({ baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173' });
  const worker = await context.newPage();
  try {
    await login(worker, false); await worker.goto(`/orders/${id}/execute`);
    await action(worker, 'Принять'); await action(worker, 'Начать работу');
    const work = worker.getByRole('textbox', { name: 'Выполненные работы', exact: true });
    await work.fill('Осмотр выполнен вручную');
    const original = await (await worker.request.get(`/api/v1/work-orders/${id}`)).json();
    expect(original.status).toBe('IN_PROGRESS'); expect(original.submission).toBeNull();
    const commands: string[] = [];
    worker.on('request', request => { if (request.method() === 'POST' && new URL(request.url()).pathname.startsWith(`/api/v1/work-orders/${id}/`)) commands.push(request.url()); });
    await worker.getByRole('button', { name: 'KZ', exact: true }).click();
    await recognize(worker, 'kk', 'Заменён подшипник');
    await worker.getByRole('button', { name: 'RU', exact: true }).click();
    const kk = worker.getByRole('region', { name: 'Голосовой ввод', exact: true });
    await expect(work).toHaveValue('Осмотр выполнен вручную');
    await expect(kk.getByRole('textbox', { name: 'Черновик расшифровки', exact: true })).toHaveValue('Заменён подшипник');
    await kk.getByRole('textbox', { name: 'Черновик расшифровки', exact: true }).fill('Подшипник заменён, вал проверен');
    await kk.getByRole('button', { name: 'Вставить', exact: true }).click();
    const completed = 'Осмотр выполнен вручную\n\nПодшипник заменён, вал проверен';
    await expect(work).toHaveValue(completed); expect(commands).toEqual([]);
    const unchanged = await (await worker.request.get(`/api/v1/work-orders/${id}`)).json();
    expect(unchanged.status).toBe('IN_PROGRESS'); expect(unchanged.version).toBe(original.version); expect(unchanged.submission).toBeNull();

    // Silence traverses the real public endpoint and controlled HTTP ASR failure path.
    const failed = worker.waitForResponse(response => new URL(response.url()).pathname === speechPath && response.request().method() === 'POST');
    await kk.getByLabel('Аудиофайл', { exact: true }).setInputFiles({ name: 'synthetic-silence.wav', mimeType: 'audio/wav', buffer: wav(true) });
    expect((await failed).status()).toBe(422);
    await expect(kk.getByRole('alert')).toBeVisible(); await expect(work).toHaveValue(completed);
    expect(commands).toEqual([]);

    const codes = worker.getByRole('combobox', { name: 'Шифр неисправности', exact: true });
    await expect.poll(() => codes.locator('option').count()).toBeGreaterThan(1);
    await codes.selectOption((await codes.locator('option').nth(1).getAttribute('value'))!);
    await worker.getByRole('checkbox', { name: 'Материалы не потребовались', exact: true }).check();
    const submitted = worker.waitForResponse(response => new URL(response.url()).pathname === `/api/v1/work-orders/${id}/submissions` && response.request().method() === 'POST');
    await worker.getByRole('button', { name: 'Передать на проверку', exact: true }).click();
    expect((await submitted).status()).toBe(201);
    const saved = await (await worker.request.get(`/api/v1/work-orders/${id}`)).json();
    expect(saved.submission.work_description).toBe(completed);
    expect(saved.status).not.toBe('IN_PROGRESS'); expect(saved.status).not.toBe('CLOSED');
  } finally { await context.close(); }
});
