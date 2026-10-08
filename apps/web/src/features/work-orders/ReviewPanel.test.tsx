import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it } from 'vitest';
import type { WorkOrderDetail } from './data';
import { ReviewPanel } from './ReviewPanel';

it('distinguishes waiting, blocked, human review and MOCK while rendering evidence text literally', async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
  const base = { id: 'order', submission: { id: 'submission', after_photo_ids: ['photo'], revision: 1 } };
  try {
    await act(async () => root.render(<ReviewPanel order={{ ...base, review_status: 'pending' } as unknown as WorkOrderDetail} />));
    expect(container.textContent).toContain('Ожидает проверки');
    await act(async () => root.render(<ReviewPanel order={{ ...base, review_status: 'blocked' } as unknown as WorkOrderDetail} />));
    expect(container.textContent).toContain('Проверка недоступна');
    await act(async () => root.render(<ReviewPanel order={{ ...base, review_status: 'completed', ai_review: { is_mock: true, model: 'test', prompt_version: 'v1', result: { verdict: 'human_review', score: null, findings: [{ code: 'visual', severity: 'warning', message: '<script>alert(1)</script>', evidence_refs: ['photo:photo', 'work_description', 'https://bad.test'] }], missing_evidence: [], limitations: ['Скрытые узлы не проверены'] } }, master_decision: { decision: 'rework', reason: 'Устранить течь', score: null } } as unknown as WorkOrderDetail} />));
    expect(container.textContent).toContain('Требуется проверка мастера'); expect(container.textContent).toContain('Тестовый результат');
    expect(container.textContent).toContain('<script>alert(1)</script>'); expect(container.querySelector('script')).toBeNull();
    expect(container.textContent).toContain('Устранить течь'); expect(container.querySelector('a[href="https://bad.test"]')).toBeNull();
    expect(container.querySelector('a[href="/api/v1/photos/photo"]')).not.toBeNull();
    expect(container.querySelector('a[href="#submission-submission"]')).not.toBeNull();
  } finally { await act(async () => root.unmount()); container.remove(); }
});

it('labels prepared scenarios and links both photo phases without marking live reviews as prepared', async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement('div'); const root = createRoot(container);
  const base = { id: 'order', issuance_photos: [{ id: 'before' }], submission: { id: 'submission', after_photo_ids: ['after'] } };
  try {
    for (const verdict of ['accepted', 'requires_rework', 'human_review']) {
      const review = { source: 'prepared', is_mock: true, model: 't18-prepared-demo-provider-v2', prompt_version: 't18-prepared-v2',
        result: { verdict, score: null, findings: [{ code: 'comparison', severity: 'info', message: 'Рисунки', evidence_refs: ['photo:before', 'photo:after'] }], missing_evidence: [], limitations: [] } };
      await act(async () => root.render(<ReviewPanel order={{ ...base, ai_review: review } as unknown as WorkOrderDetail} />));
      expect(container.querySelectorAll('.badge')).toHaveLength(1);
      expect(container.textContent).toContain('Подготовленный результат');
      expect(container.querySelector('a[href="/api/v1/photos/before"]')?.textContent).toBe('Фото до работы');
      expect(container.querySelector('a[href="/api/v1/photos/after"]')?.textContent).toBe('Фото после работы');
      await act(async () => root.render(<ReviewPanel order={{ ...base, ai_review: { ...review, source: 'provider', is_mock: false, model: 'live' } } as unknown as WorkOrderDetail} />));
      expect(container.textContent).not.toContain('Подготовленный результат');
    }
  } finally { await act(async () => root.unmount()); container.remove(); }
});

it('links worker before-photo evidence missing from issuance photos without guessing its phase', async () => {
  const container = document.createElement('div'); const root = createRoot(container);
  const id = 'd57ee760-77df-4946-a506-cf0d0b64e1a6';
  try {
    await act(async () => root.render(<ReviewPanel order={{ id: 'order', issuance_photos: [], ai_review: { source: 'provider', is_mock: false, model: 'live', prompt_version: 'v1', result: { verdict: 'human_review', score: null, findings: [{ message: 'Проверить фото', evidence_refs: [`photo:${id}`, 'photo:https://bad.test', 'photo:not-a-uuid'] }], missing_evidence: [], limitations: [] } } } as unknown as WorkOrderDetail} />));
    expect(container.querySelector(`a[href="/api/v1/photos/${id}"]`)?.textContent).toBe('Фото к проверке');
    expect(container.querySelectorAll('a')).toHaveLength(1);
    expect(container.textContent).toContain('photo:not-a-uuid');
  } finally { await act(async () => root.unmount()); }
});

it('explains when review begins before a report exists', async () => {
  const container = document.createElement('div'); const root = createRoot(container);
  try {
    await act(async () => root.render(<ReviewPanel order={{ id: 'order' } as WorkOrderDetail} />));
    expect(container.textContent).toContain('ИИ-проверка работы');
    expect(container.textContent).toContain('после отправки отчёта');
  } finally { await act(async () => root.unmount()); }
});

it.each([['rules', 'Проверка по правилам'], ['provider', 'Результат ИИ'], ['unknown', 'Источник не подтверждён']])('keeps %s provenance truthful and technical fields collapsed', async (source, label) => {
  const container = document.createElement('div'); const root = createRoot(container);
  try {
    await act(async () => root.render(<ReviewPanel order={{ id: 'order', ai_review: { source, is_mock: false, model: 'gpt-test', prompt_version: 'v1', result: { verdict: 'human_review', score: null, findings: [], missing_evidence: ['Нужен ракурс'], limitations: ['Скрытые узлы не проверены'] } } } as unknown as WorkOrderDetail} />));
    expect(container.textContent).toContain(label);
    expect(container.querySelector('details')?.open).toBe(false);
    expect(container.querySelector('details')?.textContent).toContain('gpt-test');
    expect(container.querySelector('details')?.textContent).not.toContain('Скрытые узлы');
    expect(container.textContent).toContain('Следующее действие');
  } finally { await act(async () => root.unmount()); }
});

it('keeps exact prepared photo provenance in details and neutral finding text without mutating results', async () => {
  const container = document.createElement('div'); const root = createRoot(container);
  const messages = [
    'Описание очистки соответствует заявке; синтетический рисунок после показывает очищенный кожух.',
    'По синтетическим рисункам нельзя подтвердить полноту очистки кожуха. Видимый результат должен проверить мастер.',
  ];
  const result = { verdict: 'human_review', score: null, findings: messages.map(message => ({ message, evidence_refs: [] })), missing_evidence: [], limitations: ['Скрытые узлы не проверены'] };
  const review = { source: 'prepared', is_mock: true, model: 'prepared', prompt_version: 'v2', result };
  try {
    await act(async () => root.render(<ReviewPanel order={{ id: 'order', ai_review: review } as unknown as WorkOrderDetail} />));
    const visible = container.cloneNode(true) as HTMLElement; visible.querySelector('details')?.remove();
    expect(visible.textContent).not.toContain('синтетическ');
    expect(visible.textContent).not.toContain('учебные изображения');
    expect(visible.textContent).toContain('Скрытые узлы не проверены');
    expect(visible.textContent).toContain('нельзя подтвердить полноту очистки');
    expect(container.querySelector('details')?.textContent).toContain('учебные изображения');
    expect(result.findings.map(finding => finding.message)).toEqual(messages);
    await act(async () => root.render(<ReviewPanel order={{ id: 'order', ai_review: { ...review, source: 'provider', is_mock: false } } as unknown as WorkOrderDetail} />));
    expect(container.textContent).toContain(messages[0]);
    expect(container.textContent).toContain(messages[1]);
  } finally { await act(async () => root.unmount()); }
});
