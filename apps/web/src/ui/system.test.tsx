import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it } from 'vitest';
import { describeStatus } from './status';
import { BigActionButton, DeadlineBar, ReasonChips, StatusBadge } from './components';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const container = document.createElement('div');
document.body.append(container);
const root = createRoot(container);
afterEach(async () => { await act(async () => root.render(null)); });

it('keeps submission, AI review and human closure distinct in both languages', () => {
  for (const locale of ['ru', 'kk'] as const) {
    const labels = ['SUBMITTED', 'AI_REVIEW', 'CLOSED'].map(status => describeStatus('order', status, locale).label);
    expect(new Set(labels).size).toBe(3);
    expect(describeStatus('verdict', 'accepted', locale).label).not.toBe(labels[2]);
  }
  expect(describeStatus('verdict', 'accepted').label).toBe('Замечаний не найдено');
  expect(describeStatus('order', 'FUTURE_STATUS')).toEqual({ label: 'FUTURE_STATUS', tone: 'off' });
});

it('shows overdue as an additional label without losing the current state', async () => {
  await act(async () => root.render(<StatusBadge domain="order" status="PAUSED" overdue />));
  expect(container.textContent).toContain('Приостановлен');
  expect(container.textContent).toContain('Просрочен');
});

it('does not submit a surrounding form when choosing a reason or clicking a default action', async () => {
  let submissions = 0;
  let selected = '';
  await act(async () => root.render(<form onSubmit={event => { event.preventDefault(); submissions++; }}>
    <ReasonChips label="Причина" options={[{ value: 'parts', label: 'Ждём детали' }]} value="" onChange={value => { selected = value; }} />
    <BigActionButton>Продолжить</BigActionButton>
  </form>));
  await act(async () => { container.querySelectorAll('button').forEach(button => button.click()); });
  expect(selected).toBe('parts');
  expect(submissions).toBe(0);
});

it('keeps pending actions disabled and reports invalid deadline data honestly', async () => {
  let actions = 0;
  await act(async () => root.render(<><BigActionButton pending onClick={() => actions++}>Выдать</BigActionButton>
    <DeadlineBar remainingSeconds={NaN} totalSeconds={0} overdue={false} /></>));
  await act(async () => container.querySelector('button')!.click());
  expect(actions).toBe(0);
  expect(container.querySelector('button')!.disabled).toBe(true);
  expect(container.textContent).toContain('Срок не указан');
  expect(container.querySelector('[role="progressbar"]')).toBeNull();
});
