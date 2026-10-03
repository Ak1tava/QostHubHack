import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PwaUpdatePrompt } from './PwaUpdatePrompt';

const { updateServiceWorker } = vi.hoisted(() => ({ updateServiceWorker: vi.fn() }));

vi.mock('virtual:pwa-register/react', async () => {
  const { useState } = await import('react');
  return {
    useRegisterSW: () => ({
      needRefresh: useState(true),
      offlineReady: useState(false),
      updateServiceWorker,
    }),
  };
});

describe('подтверждение обновления PWA', () => {
  let root: Root;
  let container: HTMLDivElement;

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    updateServiceWorker.mockReset().mockResolvedValue(undefined);
    container = document.createElement('div');
    document.body.append(container);
    root = createRoot(container);
    act(() => root.render(<PwaUpdatePrompt />));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it('не применяет новую версию до нажатия пользователем', async () => {
    expect(container.querySelector('[role="status"]')).not.toBeNull();
    expect(updateServiceWorker).not.toHaveBeenCalled();
    await act(async () => container.querySelector<HTMLButtonElement>('button')!.click());
    expect(updateServiceWorker).toHaveBeenCalledExactlyOnceWith(true);
  });

  it('позволяет отложить обновление без перезагрузки', () => {
    act(() => container.querySelectorAll('button')[1].click());
    expect(container.querySelector('[role="status"]')).toBeNull();
    expect(updateServiceWorker).not.toHaveBeenCalled();
  });

  it('показывает ошибку и сохраняет возможность повторить обновление', async () => {
    updateServiceWorker.mockRejectedValueOnce(new Error('network unavailable'));
    await act(async () => container.querySelector<HTMLButtonElement>('button')!.click());
    expect(container.querySelector('[role="alert"]')).not.toBeNull();
    expect(container.querySelector<HTMLButtonElement>('button')!.disabled).toBe(false);
  });
});
