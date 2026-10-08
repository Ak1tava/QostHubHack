import { leakTemplate } from './templateFixture.test-helper';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it } from 'vitest';
import { ApiClient } from '../../lib/api';
import { SavedSubmission } from './SavedSubmission';
import type { Submission } from './data';

it('shows immutable report with catalog names, units, protected photos and Russian evidence labels', async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const submission: Submission = { id: 'revision', worker_id: 'worker', work_order_id: 'order', revision: 2, assignment_version: 1, work_description: 'Заменено масло', fault_code_id: 'code-id', materials: [{ material_id: 'material-id', quantity: '1.2500' }], no_materials_used: false, after_photo_ids: ['photo-id'], comment: 'Проверено', submitted_at: '2026-10-04T10:00:00Z', missing_evidence: ['after_photo'] };
  const api = new ApiClient(async input => new Response(JSON.stringify({ items: String(input).includes('work-codes') ? [{ id: 'code-id', code: '01', name: 'Течь' }] : [{ id: 'material-id', name: 'Масло', unit: 'л' }], total: 1 }), { headers: { 'Content-Type': 'application/json' } }));
  const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
  try {
    await act(async () => root.render(<SavedSubmission api={api} submission={submission} />));
    expect(container.textContent).toContain('01 · Течь'); expect(container.textContent).toContain('Масло: 1.2500 л');
    expect(container.textContent).toContain('Фото после работы'); expect(container.textContent).not.toContain('material-id');
    expect(container.querySelector('img')!.getAttribute('src')).toBe('/api/v1/photos/photo-id'); expect(container.querySelector('input, textarea, select')).toBeNull();
  } finally { await act(async () => root.unmount()); container.remove(); }
});

it('renders persisted answers with labels from the issued snapshot', async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const api = new ApiClient(async () => new Response(JSON.stringify({ items: [], total: 0 }), { headers: { 'Content-Type': 'application/json' } }));
  const submission: Submission = { id: 'report', work_order_id: 'order', worker_id: 'worker', revision: 1, assignment_version: 1, work_description: 'Устранено', fault_code_id: 'code', comment: null, no_materials_used: true, submitted_at: '2026-10-08T10:00:00Z', template_answers: [{ id: 'identify_leak', checked: true }] };
  const container = document.createElement('div'); const root = createRoot(container);
  try {
    await act(async () => root.render(<SavedSubmission api={api} submission={submission} template={leakTemplate} />));
    expect(container.textContent).toContain('Место течи указано: Выполнено');
    expect(container.textContent).toContain('Работы описаны: Не подтверждено');
    expect(container.querySelector('input')).toBeNull();
  } finally { await act(async () => root.unmount()); }
});
