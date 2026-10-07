import { expect, test } from '@playwright/test';

test.use({ trace: 'off' });

test('T14 preserves API period between reports and fits mobile navigation', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Логин', { exact: true }).fill(`${process.env.E2E_LOGIN!}-master-t08-report`);
  await page.getByLabel('Пароль или ПИН').fill(process.env.E2E_PASSWORD!);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Панель смены', exact: true })).toBeVisible();
  const response = page.waitForResponse(item => item.url().includes('/api/v1/reports/shift?') && item.status() === 200);
  await page.goto('/reports/shift');
  const report = await (await response).json();
  const values = page.locator('dl[aria-label="Показатели отчёта"] dd strong');
  for (const [index, key] of ['issued', 'performed', 'closed', 'overdue', 'rejected'].entries()) await expect(values.nth(index)).toHaveText(new Intl.NumberFormat('ru-RU').format(report.counts[key]));
  const ratingResponse = page.waitForResponse(item => item.url().includes('/api/v1/reports/rating?') && item.status() === 200);
  await page.getByRole('navigation', { name: 'Отчёты', exact: true }).getByRole('link', { name: 'Рейтинг', exact: true }).click();
  const rating = await (await ratingResponse).json();
  expect(rating.period.start_at).toBe(report.period.start_at); expect(rating.period.end_at).toBe(report.period.end_at);
  for (const width of [320, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 844 });
    await expect(page.getByRole('navigation', { name: 'Разделы приложения' })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
});
