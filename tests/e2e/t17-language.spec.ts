import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

test.use({ trace: 'off', serviceWorkers: 'block' });
const scenario = 't17-language';
const suppliedDescription = 'Войти\nМои наряды\nМенің жеке мәтінім';

async function login(page: Page, master: boolean) {
  await page.goto('/');
  await page.getByLabel('Логин', { exact: true }).fill(`${process.env.E2E_LOGIN!}-${master ? 'master-' : ''}${scenario}`);
  await page.getByLabel('Пароль или ПИН', { exact: true }).fill(process.env.E2E_PASSWORD!);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('heading', { name: master ? 'Панель смены' : 'Мои наряды', exact: true })).toBeVisible();
}

async function mobileFits(page: Page, screen: string) {
  const artifacts = resolve(test.info().config.rootDir, '../../.tooling/t17-t19/t17-browser');
  mkdirSync(artifacts, { recursive: true });
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${screen}: KK at ${width}px`).toBe(true);
    const path = resolve(artifacts, `${screen}-kk-${width}.png`);
    await page.screenshot({ path, fullPage: true });
    await test.info().attach(`${screen}-kk-${width}`, { path, contentType: 'image/png' });
  }
}

test('T17 RU is the default; KK persists and localizes authored login errors without rewriting typed fields', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('html')).toHaveAttribute('lang', 'ru');
  await expect(page.getByRole('heading', { name: 'Вход', exact: true })).toBeVisible();
  await page.getByLabel('Логин', { exact: true }).fill('Войти');
  await page.getByLabel('Пароль или ПИН', { exact: true }).fill('synthetic-not-a-real-password');
  await page.getByRole('button', { name: 'KZ', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'kk');
  await expect(page.getByLabel('Логин', { exact: true })).toHaveValue('Войти');
  await expect(page.getByLabel('Құпиясөз немесе ПИН', { exact: true })).toHaveValue('synthetic-not-a-real-password');
  // Exercise the error display without consuming the disposable server's login budget.
  await page.route('**/api/v1/auth/login', route => route.fulfill({ status: 401, json: { error: { code: 'invalid_credentials', message: 'Неверный логин или пароль.' } } }));
  await page.getByRole('button', { name: 'Кіру', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Логин немесе құпиясөз қате.');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('lang', 'kk');
  await expect(page.getByRole('button', { name: 'KZ', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('button', { name: 'Кіру', exact: true })).toBeVisible();
  await mobileFits(page, 'login');
});

test('T17 KK create and template report preserve user data, drafts, checks and Russian speech guidance across switches', async ({ page, browser }) => {
  test.setTimeout(90_000);
  await login(page, true);
  await page.getByRole('button', { name: 'KZ', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Ауысым панелі', exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Ауысым панелі', exact: true })).toBeVisible();
  await page.locator('.worker-card').filter({ hasText: `Исполнитель ${scenario}` }).getByRole('link', { name: 'Беру', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Демо насос Т04', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Демо насос Т04', exact: true }).click();
  await page.getByRole('combobox', { name: 'Үлгі', exact: true }).selectOption('visible_leak');
  await expect(page.getByRole('region', { name: 'Үлгі талаптары', exact: true })).toContainText('Көрінетін ағуды жою');
  await page.getByRole('textbox', { name: 'Жұмыс сипаттамасы', exact: true }).fill(suppliedDescription);
  await expect(page.getByRole('region', { name: 'Дауыспен енгізу', exact: true })).toContainText('Сөйлеуді тану тек орыс тілінде қолжетімді.');
  await expect(page.getByRole('region', { name: 'Дауыспен енгізу', exact: true }).getByRole('combobox')).toHaveCount(0);
  await page.getByRole('button', { name: 'RU', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Описание работ', exact: true })).toHaveValue(suppliedDescription);
  await expect(page.getByRole('combobox', { name: 'Шаблон', exact: true })).toHaveValue('visible_leak');
  await expect(page.getByRole('region', { name: 'Голосовой ввод', exact: true })).toContainText('Распознавание речи доступно только на русском языке.');
  await page.getByRole('button', { name: 'KZ', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Жұмыс сипаттамасы', exact: true })).toHaveValue(suppliedDescription);
  await expect(page.getByRole('region', { name: 'Дауыспен енгізу', exact: true })).toContainText('Сөйлеуді тану тек орыс тілінде қолжетімді.');
  await mobileFits(page, 'create-template');
  await page.getByRole('button', { name: 'Наряд беру', exact: true }).click();
  await expect(page).toHaveURL(/\/orders\/[0-9a-f-]+$/);
  const id = new URL(page.url()).pathname.split('/').at(-1)!;
  const context = await browser.newContext({ baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173', serviceWorkers: 'block' });
  const worker = await context.newPage();
  try {
    const created = await (await page.request.get(`/api/v1/work-orders/${id}`)).json();
    expect(created.description).toBe(suppliedDescription);
    await expect(page.locator('.full-description')).toHaveText(suppliedDescription);
    await expect(page.getByRole('button', { name: 'Болдырмау', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Қайта тағайындау', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Басымдықты өзгерту', exact: true })).toBeVisible();
    await expect(page.getByRole('region', { name: 'Наряд тарихы', exact: true }).locator('li').last().locator('strong')).toHaveText('Беру');
    await page.route('**/api/v1/telegram/status', route => route.fulfill({ status: 503, json: { error: { code: 'telegram_not_configured', message: 'Synthetic unavailable Telegram' } } }));
    await page.goto('/telegram');
    await expect(page.getByRole('alert')).toHaveText('Telegram әлі бапталмаған. Шеберге хабарласыңыз.');
    await page.getByRole('button', { name: 'RU', exact: true }).click();
    await expect(page.getByRole('alert')).toHaveText('Telegram пока не настроен. Обратитесь к мастеру.');
    await page.getByRole('button', { name: 'KZ', exact: true }).click();
    await expect(page.getByRole('alert')).toHaveText('Telegram әлі бапталмаған. Шеберге хабарласыңыз.');
    await page.goto(`/orders/${id}`);
    await login(worker, false);
    await worker.goto(`/orders/${id}/execute`);
    for (const action of ['Принять', 'Начать работу']) {
      await worker.getByRole('button', { name: action, exact: true }).click();
      const applied = worker.waitForResponse(response => response.url().endsWith('/actions') && response.request().method() === 'POST');
      await worker.getByRole('button', { name: 'Применить', exact: true }).click();
      expect((await applied).status()).toBe(200);
      await expect(worker.getByRole('button', { name: 'Применить', exact: true })).toHaveCount(0);
    }
    const manualReport = 'Отчёты\nҚолмен енгізілген жұмыс сипаттамасы';
    await worker.getByRole('textbox', { name: 'Выполненные работы', exact: true }).fill(manualReport);
    await worker.locator('input[name="template-identify_leak"]').check();
    await worker.getByRole('button', { name: 'KZ', exact: true }).click();
    await expect(worker.getByRole('heading', { name: 'Орындалу есебі', exact: true })).toBeVisible();
    await expect(worker.getByRole('textbox', { name: 'Орындалған жұмыстар', exact: true })).toHaveValue(manualReport);
    await expect(worker.getByRole('group', { name: 'Үлгінің тексеру тізімі', exact: true })).toContainText('Ағудың көрінетін жері көрсетіліп, тіркелген.');
    await expect(worker.locator('input[name="template-identify_leak"]')).toBeChecked();
    await expect(worker.locator('.full-description')).toHaveText(suppliedDescription);
    const voice = worker.getByRole('region', { name: 'Дауыспен енгізу', exact: true });
    await expect(voice.getByRole('combobox')).toHaveCount(0);
    await expect(voice).toContainText('Сөйлеуді тану тек орыс тілінде қолжетімді.');
    await worker.getByRole('button', { name: 'RU', exact: true }).click();
    await worker.getByRole('button', { name: 'KZ', exact: true }).click();
    await expect(voice).toContainText('Сөйлеуді тану тек орыс тілінде қолжетімді.');
    await expect(worker.getByRole('textbox', { name: 'Орындалған жұмыстар', exact: true })).toHaveValue(manualReport);
    await expect(worker.locator('input[name="template-identify_leak"]')).toBeChecked();
    const submissions: string[] = [];
    worker.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/submissions')) submissions.push(request.url()); });
    await mobileFits(worker, 'report-template');
    expect(submissions).toEqual([]);
    const unchanged = await (await worker.request.get(`/api/v1/work-orders/${id}`)).json();
    expect(unchanged.status).toBe('IN_PROGRESS');
    expect(unchanged.submission).toBeNull();
  } finally {
    await context.close();
    // Release only this synthetic worker, keeping the test repeatable in the full suite.
    const current = await (await page.request.get(`/api/v1/work-orders/${id}`)).json();
    if (current.allowed_actions.includes('cancel')) {
      const auth = await (await page.request.get('/api/v1/auth/me')).json();
      const cancelled = await page.request.post(`/api/v1/work-orders/${id}/actions`, {
        headers: { Origin: new URL(page.url()).origin, 'X-CSRF-Token': auth.csrf_token, 'Idempotency-Key': crypto.randomUUID() },
        data: { action: 'cancel', expected_version: current.version, reason: 'Синтетическая проверка языка завершена' },
      });
      expect(cancelled.status()).toBe(200);
    }
  }
});
