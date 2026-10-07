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
