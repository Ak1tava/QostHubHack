import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { LocaleProvider, useLocale, localizedTemplate } from './locale';
import { ApiClient, ApiError } from '../lib/api';
import { SpeechInput } from '../features/speech/SpeechInput';
import { LoginPage } from '../features/auth/LoginPage';
import { leakTemplate } from '../features/work-orders/templateFixture.test-helper';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const container = document.createElement('div');
document.body.append(container);
const root = createRoot(container);
afterEach(async () => { await act(async () => root.render(null)); localStorage.clear(); vi.restoreAllMocks(); });
function Switch() {
  const { locale, setLocale } = useLocale();
  return <button onClick={() => setLocale(locale === 'ru' ? 'kk' : 'ru')}>switch</button>;
}
async function toggle() { await act(async () => container.querySelector('button')!.click()); }

it('defaults to Russian and preserves entered login while switching and after remount', async () => {
  const render = () => <LocaleProvider><Switch /><LoginPage busy={false} error={null} onLogin={async () => {}} /></LocaleProvider>;
  await act(async () => root.render(render()));
  expect(container.textContent).toContain('Вход');
  const login = container.querySelector<HTMLInputElement>('#login')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(login, 'Мастер-123');
    login.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await toggle();
  expect(container.textContent).toContain('Кіру');
  expect(container.querySelector<HTMLInputElement>('#login')!.value).toBe('Мастер-123');
  expect(document.documentElement.lang).toBe('kk');
  await act(async () => root.render(null));
  await act(async () => root.render(render()));
  expect(container.textContent).toContain('Кіру');
});

it('works when localStorage is denied and ignores unsupported persisted locales', async () => {
  localStorage.setItem('naryadai.locale', 'en');
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('denied'); });
  await act(async () => root.render(<LocaleProvider><Switch /><LoginPage busy={false} error={null} onLogin={async () => {}} /></LocaleProvider>));
  expect(container.textContent).toContain('Вход');
  await toggle();
  expect(container.textContent).toContain('Кіру');
});

it('uses UI locale as speech default while preserving an explicit speech language edit', async () => {
  localStorage.setItem('naryadai.locale', 'kk');
  await act(async () => root.render(<LocaleProvider><Switch /><SpeechInput api={new ApiClient()} value="" onChange={() => {}} maxLength={4000} /></LocaleProvider>));
  const select = container.querySelector('select')!;
  expect(select.value).toBe('kk');
  await act(async () => { select.value = 'ru'; select.dispatchEvent(new Event('change', { bubbles: true })); });
  await toggle(); await toggle();
  expect(select.value).toBe('ru');
});

it('localizes known error codes while preserving unknown server error text', async () => {
  localStorage.setItem('naryadai.locale', 'kk');
  await act(async () => root.render(<LocaleProvider><LoginPage busy={false} error={new ApiError(401, 'invalid_credentials', 'server text')} onLogin={async () => {}} /></LocaleProvider>));
  expect(container.textContent).toContain('Логин немесе құпиясөз қате');
  await act(async () => root.render(<LocaleProvider><LoginPage busy={false} error={new ApiError(400, 'unknown_custom_error', 'Текст из документа')} onLogin={async () => {}} /></LocaleProvider>));
  expect(container.textContent).toContain('Текст из документа');
});

it('translates shipped template ID/version/checklist IDs only and preserves descriptions', () => {
  const known = localizedTemplate(leakTemplate, 'kk');
  expect(known.title).toBe('Көрінетін ағуды жою');
  expect(known.checklist[0].label.toLowerCase()).toContain('ағу');
  expect(known.initial_description).toBe(leakTemplate.initial_description);
  expect(localizedTemplate({ ...leakTemplate, version: 2 }, 'kk')).toEqual({ ...leakTemplate, version: 2 });
  expect(localizedTemplate({ ...leakTemplate, id: 'custom' } as unknown as typeof leakTemplate, 'kk')).toEqual({ ...leakTemplate, id: 'custom' });
  const custom = { ...leakTemplate, checklist: [{ id: 'custom', label: 'Непереводимый текст', required: true }] };
  expect(localizedTemplate(custom, 'kk').checklist[0].label).toBe('Непереводимый текст');
});
