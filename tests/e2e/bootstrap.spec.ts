import { expect, test, type Page } from '@playwright/test';

async function controlledPage(page: Page) {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'НарядAI', exact: true })).toBeVisible();
  await page.evaluate(() => navigator.serviceWorker.ready.then(() => true));
  await page.reload();
  await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller))).toBe(true);
}

test('production web proxies health, OpenAPI and unknown API routes', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'НарядAI', exact: true })).toBeVisible();
  const live = await page.request.get('/health/live');
  expect(live.status()).toBe(200);
  expect(await live.json()).toEqual({ status: 'ok' });
  const ready = await page.request.get('/health/ready');
  expect([200, 503]).toContain(ready.status());
  expect(await ready.json()).toEqual({ status: ready.status() === 200 ? 'ready' : 'not_ready' });
  const schema = await page.request.get('/openapi.json');
  expect(schema.status()).toBe(200);
  expect((await schema.json()).paths['/health/ready'].get.responses).toHaveProperty('503');
  const missing = await page.request.get('/api/v1/t01-does-not-exist');
  expect(missing.status()).toBe(404);
  expect(missing.headers()['content-type']).toContain('application/json');
  expect(await missing.json()).toEqual({ detail: 'Not Found' });
  const docs = await page.request.get('/docs');
  expect(docs.status()).toBe(200);
  expect(await docs.text()).toContain('swagger-ui');
});

test('PWA publishes a standalone manifest and valid installation icons', async ({ page }) => {
  await page.goto('/');
  const href = await page.locator('link[rel="manifest"]').getAttribute('href');
  expect(href).toBeTruthy();
  const response = await page.request.get(href!);
  expect(response.status()).toBe(200);
  const manifest = await response.json();
  expect(manifest.display).toBe('standalone');
  expect(manifest.lang).toBe('ru');
  for (const size of [192, 512]) {
    const icon = manifest.icons.find((entry: { sizes: string }) => entry.sizes === `${size}x${size}`);
    expect(icon).toBeTruthy();
    const image = await page.request.get(icon.src);
    expect(image.status()).toBe(200);
    const bytes = await image.body();
    expect(bytes.subarray(0, 8)).toEqual(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
    expect(bytes.readUInt32BE(16)).toBe(size);
    expect(bytes.readUInt32BE(20)).toBe(size);
  }
});

test('offline shell works while API, health and documentation stay network-only', async ({ page, context }) => {
  await controlledPage(page);
  await page.evaluate(async () => {
    await fetch('/health/live');
    await fetch('/api/v1/t01-does-not-exist');
  });
  const cachedPaths = await page.evaluate(async () => {
    const paths: string[] = [];
    for (const name of await caches.keys()) {
      for (const request of await (await caches.open(name)).keys()) paths.push(new URL(request.url).pathname);
    }
    return paths;
  });
  expect(cachedPaths.some(path => /^\/(api|health|docs)(\/|$)/.test(path) || path === '/openapi.json')).toBe(false);
  await context.setOffline(true);
  await page.reload();
  await expect(page.getByRole('heading', { name: 'НарядAI', exact: true })).toBeVisible();
  const offlineHealth = await page.evaluate(() => fetch('/health/live').then(() => 'response').catch(() => 'network-error'));
  expect(offlineHealth).toBe('network-error');
  for (const path of ['/api/v1/t01-does-not-exist', '/health/live', '/docs', '/openapi.json']) {
    const excluded = await context.newPage();
    await expect(excluded.goto(path)).rejects.toThrow();
    await excluded.close();
  }
});
