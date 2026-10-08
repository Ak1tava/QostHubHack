import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it } from 'vitest';
import { TemplateRequirements } from './TemplateRequirements';
import { leakTemplate } from './templateFixture.test-helper';

it('keeps template version in collapsed details and leaves safety instructions visible', async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement('div'); const root = createRoot(container);
  try {
    await act(async () => root.render(<TemplateRequirements template={leakTemplate} />));
    expect(container.querySelector('h3')?.textContent).toBe('Устранение видимой течи');
    expect(container.querySelector('details')?.textContent).toContain('версия 1');
    expect(container.querySelector('details')?.open).toBe(false);
    const visible = container.cloneNode(true) as HTMLElement; visible.querySelector('details')?.remove();
    expect(visible.textContent).toContain('Зафиксировать видимый участок течи');
    expect(visible.textContent).toContain('Требуются перед отправкой отчёта');
  } finally { await act(async () => root.unmount()); }
});
