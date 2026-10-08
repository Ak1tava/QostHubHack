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
    expect(container.textContent).toContain('Требуется проверка мастера'); expect(container.textContent).toContain('MOCK');
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
      const review = { is_mock: true, model: 't18-prepared-demo-provider-v2', prompt_version: 't18-prepared-v2',
        result: { verdict, score: null, findings: [{ code: 'comparison', severity: 'info', message: 'Рисунки', evidence_refs: ['photo:before', 'photo:after'] }], missing_evidence: [], limitations: [] } };
      await act(async () => root.render(<ReviewPanel order={{ ...base, ai_review: review } as unknown as WorkOrderDetail} />));
      expect(container.textContent).toContain('Подготовленный демонстрационный результат');
      expect(container.querySelector('a[href="/api/v1/photos/before"]')?.textContent).toBe('Фото до работы');
      expect(container.querySelector('a[href="/api/v1/photos/after"]')?.textContent).toBe('Фото после работы');
      await act(async () => root.render(<ReviewPanel order={{ ...base, ai_review: { ...review, is_mock: false, model: 'live' } } as unknown as WorkOrderDetail} />));
      expect(container.textContent).not.toContain('Подготовленный демонстрационный результат');
    }
  } finally { await act(async () => root.unmount()); container.remove(); }
});
