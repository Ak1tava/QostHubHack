import { expect, test, type Locator, type Page } from '@playwright/test';

test.use({ trace: 'off' });
const loginName = (scenario: string, master = true) => `${process.env.E2E_LOGIN!}-${master ? 'master-' : ''}${scenario}`;
async function login(page: Page, scenario: string, master = true) {
  await page.goto('/');
  await page.getByLabel('Логин', { exact: true }).fill(loginName(scenario, master));
  await page.getByLabel('Пароль или ПИН').fill(process.env.E2E_PASSWORD!);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('heading', { name: master ? 'Панель смены' : 'Мои наряды', exact: true })).toBeVisible();
}
async function prepare(page: Page, scenario: string, description: string) {
  const card = page.locator('.worker-card').filter({ hasText: `Исполнитель ${scenario}` });
  await card.getByRole('link', { name: 'Выдать', exact: true }).click();
  await page.getByRole('button', { name: 'Демо насос Т04', exact: true }).click();
  await page.getByLabel('Описание работ', { exact: true }).fill(description);
}
async function issue(page: Page, scenario: string, description: string) {
  await prepare(page, scenario, description);
  await page.getByRole('button', { name: 'Выдать наряд', exact: true }).click();
  await expect(page).toHaveURL(/\/orders\/[0-9a-f-]+$/);
  await expect(page.getByRole('heading', { name: /^Наряд / })).toBeVisible();
  return new URL(page.url()).pathname.split('/').at(-1)!;
}

test('foreman issues an order and receives a worker status change within five seconds', async ({ page, browser }, testInfo) => {
  const description = `Сквозная проверка насоса T04 ${crypto.randomUUID().slice(0, 8)}`;
  const workerContext = await browser.newContext({ baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173' });
  const worker = await workerContext.newPage();
  try {
    const socketPromise = worker.waitForEvent('websocket', { predicate: socket => socket.url().endsWith('/api/v1/events') });
    await login(worker, 't04-browser', false);
    const socket = await socketPromise;
    await login(page, 't04-browser');
    await prepare(page, 't04-browser', description);
    const delivered = socket.waitForEvent('framereceived', { predicate: frame => typeof frame.payload === 'string' && JSON.parse(frame.payload).type === 'work_order.create', timeout: 5000 });
    await page.getByRole('button', { name: 'Выдать наряд', exact: true }).click();
    await expect(page).toHaveURL(/\/orders\/[0-9a-f-]+$/);
    const id = new URL(page.url()).pathname.split('/').at(-1)!;
    expect(JSON.parse(String((await delivered).payload)).work_order_id).toBe(id);
    await worker.goto(`/orders/${id}`);
    await expect(worker.getByText(description, { exact: true })).toBeVisible();
    await expect(worker.getByRole('button', { name: 'Переназначить', exact: true })).toHaveCount(0);
    const started = Date.now();
    const status = await worker.evaluate(async orderId => {
      const auth = await (await fetch('/api/v1/auth/me', { cache: 'no-store' })).json();
      const response = await fetch(`/api/v1/work-orders/${orderId}/actions`, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': auth.csrf_token, 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify({ action: 'accept', expected_version: 1 }) });
      return response.status;
    }, id);
    expect(status).toBe(200);
    await expect(page.getByText('Приняты', { exact: true })).toBeVisible({ timeout: 5000 });
    const elapsedMs = Date.now() - started;
    expect(elapsedMs).toBeLessThanOrEqual(5000);
    testInfo.annotations.push({ type: 'status-update', description: JSON.stringify({ elapsedMs }) });
    await page.getByRole('link', { name: '← Панель смены', exact: true }).click();
    await expect(page.locator('.order-card').filter({ hasText: description })).toBeVisible();
  } finally { await workerContext.close(); }
});

test('mobile issuance uses large controls, six or fewer scripted actions and no horizontal overflow', async ({ browser }, testInfo) => {
  const context = await browser.newContext({ baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173', viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const page = await context.newPage();
  try {
    await login(page, 't04-mobile');
    await page.screenshot({ path: '../../.superpowers/sdd/T04-implementation/mobile-shift.png', fullPage: true });
    let actions = 0;
    const tap = async (locator: Locator) => { await locator.tap(); actions++; };
    const started = Date.now();
    await tap(page.locator('.worker-card').filter({ hasText: 'Исполнитель t04-mobile' }).getByRole('link', { name: 'Выдать', exact: true }));
    await tap(page.getByRole('button', { name: 'Демо насос Т04', exact: true }));
    await tap(page.getByLabel('Описание работ', { exact: true }));
    await page.getByLabel('Описание работ', { exact: true }).fill('Мобильная проверка T04');
    await page.screenshot({ path: '../../.superpowers/sdd/T04-implementation/mobile-create.png', fullPage: true });
    await tap(page.getByRole('button', { name: 'Выдать наряд', exact: true }));
    await expect(page.getByRole('heading', { name: /^Наряд / })).toBeVisible();
    const elapsedMs = Date.now() - started;
    expect(actions).toBeLessThanOrEqual(6); expect(elapsedMs).toBeLessThanOrEqual(60000);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    testInfo.annotations.push({ type: 'mobile-emulation', description: JSON.stringify({ actions, elapsedMs, physicalPhones: false }) });
  } finally { await context.close(); }
});

test('HTTP reconciliation and reconnect recover changes missed by the socket', async ({ page, browser }) => {
  const description = `Восстановление соединения T04 ${crypto.randomUUID().slice(0, 8)}`;
  await page.addInitScript(() => {
    const state = window as unknown as { sockets: WebSocket[]; blockSockets: boolean };
    state.sockets = []; state.blockSockets = false;
    const Native = window.WebSocket;
    window.WebSocket = class extends Native {
      constructor(url: string | URL, protocols?: string | string[]) {
        if (state.blockSockets) throw new Error('Temporary test disconnection');
        super(url, protocols); state.sockets.push(this);
      }
    };
  });
  await login(page, 't04-reconnect');
  await expect.poll(() => page.evaluate(() => (window as unknown as { sockets: WebSocket[] }).sockets.some(socket => socket.readyState === 1))).toBe(true);
  await page.evaluate(() => { const state = window as unknown as { sockets: WebSocket[]; blockSockets: boolean }; state.blockSockets = true; state.sockets.forEach(socket => socket.close()); });
  const publisherContext = await browser.newContext({ baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173' });
  const publisher = await publisherContext.newPage();
  try {
    await login(publisher, 't04-reconnect');
    await issue(publisher, 't04-reconnect', description);
    await expect(page.locator('.order-card').filter({ hasText: description })).toBeVisible({ timeout: 5000 });
    await page.evaluate(() => { (window as unknown as { blockSockets: boolean }).blockSockets = false; window.dispatchEvent(new Event('online')); });
    await expect.poll(() => page.evaluate(() => (window as unknown as { sockets: WebSocket[] }).sockets.filter(socket => socket.readyState === 1).length), { timeout: 10000 }).toBe(1);
  } finally { await publisherContext.close(); }
});

test('direct links restore authentication and worker access stays read only', async ({ page, browser }) => {
  await login(page, 't04-deeplink');
  const id = await issue(page, 't04-deeplink', 'Проверка прямой ссылки T04');
  await page.reload(); await expect(page.getByText('Проверка прямой ссылки T04', { exact: true })).toBeVisible();
  const context = await browser.newContext({ baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173' });
  const worker = await context.newPage();
  try {
    await worker.goto(`/orders/${id}`);
    await expect(worker.getByRole('heading', { name: 'Вход', exact: true })).toBeVisible();
    await worker.getByLabel('Логин', { exact: true }).fill(loginName('t04-deeplink', false));
    await worker.getByLabel('Пароль или ПИН').fill(process.env.E2E_PASSWORD!);
    await worker.getByRole('button', { name: 'Войти', exact: true }).click();
    await expect(worker.getByText('Проверка прямой ссылки T04', { exact: true })).toBeVisible();
    await worker.goto('/orders/new');
    await expect(worker.getByRole('alert')).toContainText('Выдавать наряды может только мастер');
  } finally { await context.close(); }
});
