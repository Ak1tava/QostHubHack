import { execFileSync } from 'node:child_process';
import { expect, test, type Page } from '@playwright/test';

// Auth traces contain cookies and request bodies; never upload them as diagnostics.
test.use({ trace: 'off' });

const account = (scenario: string) => `${process.env.E2E_LOGIN!}-${scenario}`;
const password = () => process.env.E2E_PASSWORD!;

async function fill(page: Page, login: string, pin = password()) {
  await page.getByLabel('Логин', { exact: true }).fill(login);
  await page.getByLabel('Пароль или ПИН', { exact: true }).fill(pin);
}

async function signIn(page: Page, scenario: string) {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Вход', exact: true })).toBeVisible();
  await fill(page, account(scenario));
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Вы вошли', exact: true })).toBeVisible();
}

test('real PIN login, HttpOnly cookie, reload, logout and server 401', async ({ page, context }) => {
  expect(password().startsWith('00')).toBe(true);
  await signIn(page, 'session');
  const cookie = (await context.cookies()).find(cookie => cookie.name === 'qosthub_session');
  expect(cookie).toMatchObject({ httpOnly: true, sameSite: 'Lax', path: '/' });
  expect(await page.evaluate(() => document.cookie)).not.toContain('qosthub_session');
  const me = await page.request.get('/api/v1/auth/me');
  expect(me.status()).toBe(200);
  expect(me.headers()['cache-control']).toBe('no-store');
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Вы вошли', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Выйти', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Вход', exact: true })).toBeVisible();
  const loggedOut = await page.request.get('/api/v1/auth/me');
  expect(loggedOut.status()).toBe(401);
  expect((await loggedOut.json()).error.code).toBe('unauthenticated');
});

test('invalid credentials and CSRF error allow a fresh successful login; server rejects extra role', async ({ page }) => {
  await page.goto('/');
  await fill(page, account('credentials'), 'incorrect-password');
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Неверный логин или пароль');
  await page.route('**/api/v1/auth/login', route => route.continue({ headers: { ...route.request().headers(), 'x-csrf-token': 'tampered' } }));
  await fill(page, account('credentials'));
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Проверка безопасности запроса не пройдена');
  await page.unroute('**/api/v1/auth/login');
  const invalid = await page.evaluate(async () => {
    const { csrf_token } = await (await fetch('/api/v1/auth/csrf', { cache: 'no-store' })).json();
    const response = await fetch('/api/v1/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf_token },
      body: JSON.stringify({ login: 'test', password: 'secret-value', role: 'admin' }),
    });
    return { status: response.status, body: await response.text() };
  });
  expect(invalid.status).toBe(422);
  expect(invalid.body).toContain('validation_error');
  expect(invalid.body).not.toContain('secret-value');
  await fill(page, account('credentials'));
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Вы вошли', exact: true })).toBeVisible();
});

test('expired server session clears auth and permits login again', async ({ page }) => {
  const native = !!(process.env.E2E_DATABASE_URL && process.env.E2E_PYTHON_PATH);
  test.skip(!process.env.CI && !native, 'Session expiry mutation requires the disposable CI or local T04 stack');
  await signIn(page, 'expiry');
  const expire = `
import sys
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.db import get_engine
from app.modules.auth.demo import validate_demo_target
from app.modules.auth.models import AuthSession, User
validate_demo_target(settings.database_url.get_secret_value())
assert make_url(settings.database_url.get_secret_value()).database in {'qosthub_demo', 'qosthub_demo_t04'}
assert sys.argv[1].startswith('e2e-worker-')
with Session(get_engine()) as db:
    db.execute(update(AuthSession).where(AuthSession.user_id.in_(select(User.id).where(User.login == sys.argv[1]))).values(expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)))
    db.commit()
`;
  if (native) execFileSync(process.env.E2E_PYTHON_PATH!, ['-c', expire, account('expiry')], { cwd: '../../services/api', timeout: 30_000, env: { ...process.env, DATABASE_URL: process.env.E2E_DATABASE_URL! } });
  else execFileSync('docker', ['compose', 'exec', '-T', 'api', '/workspace/services/api/.venv/bin/python', '-c', expire, account('expiry')], { cwd: '../..', timeout: 30_000 });
  await expect(page.getByRole('heading', { name: 'Вход', exact: true })).toBeVisible();
  await fill(page, account('expiry'));
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Вы вошли', exact: true })).toBeVisible();
});

test('429 observes Retry-After before another attempt', async ({ page }) => {
  await page.route('**/api/v1/auth/login', route => route.fulfill({
    status: 429, contentType: 'application/json', headers: { 'Retry-After': '2' },
    body: JSON.stringify({ error: { code: 'rate_limited', message: 'Слишком много попыток', details: [] } }),
  }));
  await page.goto('/');
  await fill(page, account('credentials'));
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Слишком много попыток');
  await expect(page.getByRole('button', { name: 'Войти', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Войти', exact: true })).toBeEnabled({ timeout: 5_000 });
});

test('422 shows field errors and unavailable server has a readable message', async ({ page }) => {
  await page.route('**/api/v1/auth/login', route => route.fulfill({
    status: 422, contentType: 'application/json',
    body: JSON.stringify({ error: { code: 'validation_error', message: 'Проверьте введённые данные', details: [{ field: 'login', message: 'Некорректное значение' }] } }),
  }));
  await page.goto('/');
  await fill(page, account('credentials'));
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('login: Некорректное значение');
  await page.unroute('**/api/v1/auth/login');
  await page.route('**/api/v1/auth/login', route => route.abort('failed'));
  await fill(page, account('credentials'));
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Сервер недоступен');
});

test('offline shell never restores cached private auth or serves HTML for API', async ({ page, context }) => {
  await signIn(page, 'offline');
  await page.evaluate(() => navigator.serviceWorker.ready.then(() => true));
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Вы вошли', exact: true })).toBeVisible();
  const paths = await page.evaluate(async () => {
    const paths: string[] = [];
    for (const name of await caches.keys()) {
      for (const request of await (await caches.open(name)).keys()) paths.push(new URL(request.url).pathname);
    }
    return paths;
  });
  expect(paths.some(path => /^\/(api|health|docs|redoc)(\/|$)/.test(path) || path === '/openapi.json')).toBe(false);
  await context.setOffline(true);
  await page.reload();
  await expect(page.getByRole('heading', { name: 'НарядAI', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Вход', exact: true })).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('Сервер недоступен');
  expect(await page.evaluate(() => fetch('/api/v1/auth/me').then(() => 'response').catch(() => 'network-error'))).toBe('network-error');
  const excluded = await context.newPage();
  await expect(excluded.goto('/api/v1/auth/me')).rejects.toThrow();
  await excluded.close();
});
