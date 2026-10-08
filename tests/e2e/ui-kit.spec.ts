import { expect, test } from '@playwright/test';

for (const width of [390, 1440]) {
  for (const locale of ['ru', 'kk'] as const) {
    for (const theme of ['light', 'dark'] as const) {
      test(`UI kit: ${width}px / ${locale} / ${theme}`, async ({ page }) => {
        const errors: string[] = [];
        const apiRequests: string[] = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('request', request => { if (new URL(request.url()).pathname.startsWith('/api/')) apiRequests.push(request.url()); });
        await page.setViewportSize({ width, height: 900 });
        await page.goto('/ui-kit');
        if (locale === 'kk') await page.getByRole('button', { name: 'KZ', exact: true }).click();
        if (theme === 'dark') await page.getByRole('button', { name: locale === 'ru' ? 'Тёмная' : 'Қараңғы', exact: true }).click();
        await expect(page.locator('.ui-kit')).toHaveAttribute('lang', locale);
        await expect(page.locator('.ui-kit')).toHaveAttribute('data-theme', theme);
        // Reload verifies saved preferences and measures the settled theme, outside hover/theme transitions.
        await page.reload();
        await expect(page.locator('.ui-kit')).toHaveAttribute('lang', locale);
        await expect(page.locator('.ui-kit')).toHaveAttribute('data-theme', theme);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        const contrasts = await page.evaluate(() => {
          type Rgba = [number, number, number, number];
          function color(value: string): Rgba {
            const numbers = value.match(/[\d.]+/g)!.map(Number);
            return [numbers[0], numbers[1], numbers[2], numbers[3] ?? 1];
          }
          function blend(top: Rgba, base: Rgba): Rgba {
            return [top[0] * top[3] + base[0] * (1 - top[3]), top[1] * top[3] + base[1] * (1 - top[3]),
              top[2] * top[3] + base[2] * (1 - top[3]), 1];
          }
          function luminance(rgb: Rgba) {
            const values = rgb.slice(0, 3).map(value => value / 255).map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
            return values[0] * .2126 + values[1] * .7152 + values[2] * .0722;
          }
          return Array.from(document.querySelectorAll<HTMLElement>('.ui-badge, .ui-kpi > span, .ui-kpi strong, .kit-demo-label, .ui-action-primary:not(:disabled), .kit-segmented button')).filter(element => element.getClientRects().length).map(element => {
            const parents: HTMLElement[] = [];
            for (let current: HTMLElement | null = element; current; current = current.parentElement) parents.unshift(current);
            const background = parents.reduce<Rgba>((base, parent) => blend(color(getComputedStyle(parent).backgroundColor), base), [255, 255, 255, 1]);
            const a = luminance(blend(color(getComputedStyle(element).color), background)), b = luminance(background);
            return { text: element.textContent, ratio: (Math.max(a, b) + .05) / (Math.min(a, b) + .05) };
          }).filter(result => result.ratio < 4.5);
        });
        expect(contrasts).toEqual([]);
        if (width === 390) {
          const sizes = await page.locator('button:visible').evaluateAll(buttons => buttons.map(button => ({ text: button.textContent, height: button.getBoundingClientRect().height })).filter(button => button.height < 56));
          expect(sizes).toEqual([]);
        }
        expect(await page.locator('.ui-kit').evaluate(element => {
          const css = getComputedStyle(element);
          return css.getPropertyValue('--free-fg').trim() === css.getPropertyValue('--ok-fg').trim()
            && css.getPropertyValue('--muted').trim() === css.getPropertyValue('--text-muted').trim();
        })).toBe(true);
        await page.screenshot({ path: test.info().outputPath(`ui-kit-${width}-${locale}-${theme}.png`), fullPage: true });
        expect(apiRequests).toEqual([]);
        expect(errors).toEqual([]);
      });
    }
  }
}

test('dialogs trap keyboard focus, close on Escape, and restore the invoking button', async ({ page }) => {
  await page.goto('/ui-kit');
  for (const name of ['Открыть панель', 'Открыть нижнюю панель']) {
    const trigger = page.getByRole('button', { name, exact: true });
    await trigger.click();
    const dialog = page.locator('dialog[open]');
    await expect(dialog).toBeVisible();
    for (let index = 0; index < 9; index++) {
      await page.keyboard.press('Tab');
      expect(await dialog.evaluate(element => element.contains(document.activeElement))).toBe(true);
    }
    for (let index = 0; index < 9; index++) {
      await page.keyboard.press('Shift+Tab');
      expect(await dialog.evaluate(element => element.contains(document.activeElement))).toBe(true);
    }
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(trigger).toBeFocused();
    expect(await page.evaluate(() => document.body.style.overflow)).toBe('');
  }
});

test('reduced motion and disabled storage remain usable', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.addInitScript(() => {
    Storage.prototype.getItem = () => { throw new DOMException('Disabled', 'SecurityError'); };
    Storage.prototype.setItem = () => { throw new DOMException('Disabled', 'SecurityError'); };
  });
  await page.goto('/ui-kit');
  await page.getByRole('button', { name: 'KZ', exact: true }).click();
  await expect(page.locator('.ui-kit')).toHaveAttribute('lang', 'kk');
  expect(await page.locator('.ui-emergency').first().evaluate(element => getComputedStyle(element).animationName)).toBe('none');
  await page.getByRole('button', { name: 'Хабарламаны көрсету', exact: true }).click();
  await expect(page.locator('.kit-toast')).toContainText('Хабарлама үлгісі');
  await page.locator('.kit-toast').getByRole('button', { name: 'Жабу', exact: true }).click();
  await expect(page.locator('.kit-toast')).toHaveCount(0);
});

test.describe('existing screens with the shared foundation', () => {
  test.use({ serviceWorkers: 'block' });
  for (const screen of ['login', 'shift', 'reports'] as const) {
    test(`${screen} fits 320/390/768/1440px without changing its data flow`, async ({ page }) => {
      const failures: string[] = [];
      const mutations: string[] = [];
      page.on('pageerror', error => failures.push(error.message));
      const user = { id: 'demo-master', display_name: 'Демо мастер', role: 'master', specialty: null, grade: null, brigade_id: null, shift_id: null };
      const period = { start_at: '2026-10-01T03:00:00Z', end_at: '2026-10-08T15:00:00Z', as_of: '2026-10-08T15:00:00Z', timezone: 'Asia/Qostanay' };
      await page.routeWebSocket('**/api/v1/events', () => {});
      await page.route('**/api/**', async route => {
        const request = route.request(), path = new URL(request.url()).pathname;
        if (request.method() !== 'GET') mutations.push(path);
        if (path === '/api/v1/auth/me') return route.fulfill({ status: screen === 'login' ? 401 : 200, json: screen === 'login'
          ? { error: { code: 'unauthenticated', message: 'Войдите' } } : { user, csrf_token: 'demo-csrf' } });
        if (path === '/api/v1/shift') return route.fulfill({ json: { as_of: period.as_of, timezone: period.timezone, items: [] } });
        if (path === '/api/v1/reports/shift') return route.fulfill({ json: {
          period, counts: { issued: 1234, performed: 900, closed: 856, overdue: 123, rejected: 12 },
          workload: { active_seconds: 123456, pause_seconds: 1200, review_seconds: 600 },
          downtime: { seconds: 0, has_data: false }, summary: 'Демонстрационный отчёт для проверки вёрстки.', limitations: [],
        } });
        return route.fulfill({ json: { items: [], total: 0, offset: 0, limit: 50 } });
      });
      await page.goto(screen === 'reports' ? '/reports/shift' : screen === 'shift' ? '/shift' : '/');
      await expect(page.getByRole('heading', { name: screen === 'login' ? 'Вход' : screen === 'shift' ? 'Панель смены' : 'Отчёты и статистика', exact: true })).toBeVisible();
      if (screen === 'reports') await expect(page.locator('.report-kpi')).toHaveCount(5);
      for (const width of [320, 390, 768, 1440]) {
        await page.setViewportSize({ width, height: 900 });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${screen} at ${width}px`).toBe(true);
        if (width === 390) await page.screenshot({ path: test.info().outputPath(`${screen}-390.png`), fullPage: true });
      }
      expect(failures).toEqual([]);
      expect(mutations).toEqual([]);
    });
  }
});
