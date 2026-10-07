import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it } from 'vitest';
import { ApiClient, type UserView } from '../../lib/api';
import { TelegramPage } from './TelegramPage';
import { NotificationDeliveryPanel } from './NotificationDeliveryPanel';

const user: UserView = { id: 'worker', display_name: 'Исполнитель', role: 'worker', brigade_id: null, shift_id: null, specialty: null, grade: null };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
let root: Root, container: HTMLDivElement;
beforeEach(() => { (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement('div'); document.body.append(container); root = createRoot(container); });
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });

it('links, checks and unlinks the current user without displaying private IDs or token text', async () => {
  let linked = false;
  const commands: string[] = [];
  const api = new ApiClient(async (input, init) => {
    const path = String(input);
    if (path.endsWith('/csrf')) return json({ csrf_token: 'csrf' });
    if (path.endsWith('/link-token')) { commands.push('link'); return json({ token: 'secret-link', url: 'https://t.me/demo_bot?start=secret-link', expires_at: new Date(Date.now() + 600000).toISOString() }, 201); }
    if (path.endsWith('/unlink')) { commands.push('unlink'); linked = false; }
    return json({ linked });
  });
  await act(async () => root.render(<TelegramPage api={api} />));
  expect(container.textContent).toContain('Не привязан');
  await act(async () => [...container.querySelectorAll('button')].find(button => button.textContent === 'Привязать Telegram')!.click());
  expect(container.querySelector('a')!.href).toBe('https://t.me/demo_bot?start=secret-link');
  expect(container.textContent).not.toContain('secret-link');
  linked = true;
  await act(async () => [...container.querySelectorAll('button')].find(button => button.textContent === 'Проверить привязку')!.click());
  expect(container.textContent).toContain('Привязан');
  expect(container.querySelector('a')).toBeNull();
  await act(async () => [...container.querySelectorAll('button')].find(button => button.textContent === 'Отвязать Telegram')!.click());
  expect(container.textContent).toContain('Не привязан');
  expect(commands).toEqual(['link', 'unlink']);
});

it('shows a safe unavailable message without reflecting server diagnostic secrets', async () => {
  const api = new ApiClient(async () => json({ error: { code: 'telegram_not_configured', message: 'chat_id=123 token=private', details: [] } }, 503));
  await act(async () => root.render(<TelegramPage api={api} />));
  expect(container.textContent).toContain('Telegram пока не настроен');
  expect(container.textContent).not.toMatch(/chat_id|private/);
});

it('worker delivery panel includes only own safe statuses and no raw diagnostic fields', async () => {
  const api = new ApiClient(async () => json([
    { id: 'own', recipient_id: user.id, kind: 'new', status: 'BLOCKED', attempts: 0, last_error: 'chat_id=secret' },
    { id: 'other', recipient_id: 'another', kind: 'overdue', status: 'SENT', attempts: 1 },
  ]));
  await act(async () => root.render(<NotificationDeliveryPanel api={api} user={user} orderId="order" />));
  expect(container.textContent).toContain('Доставка заблокирована');
  expect(container.textContent).not.toMatch(/secret|another|Отправлено/);
});
