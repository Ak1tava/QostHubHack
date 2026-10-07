import { expect, test, type Page } from '@playwright/test';

test.use({ trace: 'off' });
async function login(page: Page, role: 'master' | 'worker', scenario: string) {
  await page.goto('/');
  await page.getByLabel('Логин', { exact: true }).fill(`${process.env.E2E_LOGIN!}-${role === 'master' ? 'master-' : ''}${scenario}`);
  await page.getByLabel('Пароль или ПИН').fill(process.env.E2E_PASSWORD!);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('heading', { name: role === 'master' ? 'Панель смены' : 'Вы вошли', exact: true })).toBeVisible();
}

test('real API rejects brigade peer ratings, foreign photos and equipment analytics', async ({ page, browser }) => {
  await login(page, 'master', 't10-permissions');
  const current = await (await page.request.get('/api/v1/auth/me')).json();
  const [areas, equipment, shift] = await Promise.all(['/catalog/areas', '/catalog/equipment', '/shift'].map(async route => (await page.request.get(`/api/v1${route}`)).json()));
  const worker = shift.items.find((member: { user: { display_name: string } }) => member.user.display_name === 'Исполнитель t10-permissions').user;
  const eq = equipment.items.find((item: { area_id: string }) => item.area_id === areas.items[0].id);
  const origin = new URL(page.url()).origin;
  const created = await page.request.post('/api/v1/work-orders', { headers: { Origin: origin, 'X-CSRF-Token': current.csrf_token, 'Idempotency-Key': crypto.randomUUID() }, data: {
    work_type: 'planned', description: 'T10 protected order', area_id: eq.area_id, equipment_id: eq.id,
    assignee_id: worker.id, brigade_id: null, priority: 'normal', due_at: new Date(Date.now() + 3600_000).toISOString(),
  } });
  expect(created.status()).toBe(201); const order = await created.json();
  expect((await page.request.get(`/api/v1/work-orders/${order.id}/notifications`)).status()).toBe(200);
  const peerContext = await browser.newContext({ baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173' });
  const peer = await peerContext.newPage();
  try {
    await login(peer, 'worker', 't08-report');
    const own = (await (await peer.request.get('/api/v1/auth/me')).json()).user;
    const period = `start_at=${encodeURIComponent(new Date(Date.now() - 86400_000).toISOString())}&end_at=${encodeURIComponent(new Date(Date.now() + 86400_000).toISOString())}`;
    expect((await peer.request.get(`/api/v1/reports/rating?${period}&assignee_id=${worker.id}`)).status()).toBe(404);
    expect((await peer.request.get(`/api/v1/analytics/anomalies?${period}`)).status()).toBe(403);
    const ownRating = await peer.request.get(`/api/v1/reports/rating?${period}`);
    expect(ownRating.status()).toBe(200);
    expect((await ownRating.json()).items.every((item: { worker_id: string }) => item.worker_id === own.id)).toBe(true);
    await peer.goto('/analytics/anomalies');
    await expect(peer.getByRole('alert')).toContainText('Анализ оборудования недоступен исполнителю');
    expect((await peer.request.get(`/api/v1/photos/${crypto.randomUUID()}`)).status()).toBe(404);
    const link = await peer.request.get(`/api/v1/work-orders/${order.id}`);
    // Direct assignment does not grant peers in the same brigade order access.
    expect(link.status()).toBe(404);
    expect((await peer.request.get(`/api/v1/work-orders/${order.id}/notifications`)).status()).toBe(404);
  } finally { await peerContext.close(); }
});
