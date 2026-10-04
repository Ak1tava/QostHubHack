import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it } from 'vitest';
import { useQuery } from './useQuery';

it('never lets an older filter response replace the current data', async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  let first!: (value: string) => void, second!: (value: string) => void;
  const oldLoad = () => new Promise<string>(resolve => { first = resolve; });
  const newLoad = () => new Promise<string>(resolve => { second = resolve; });
  function View({ load }: { load: (signal: AbortSignal) => Promise<string> }) { const state = useQuery(load, false); return <p>{state.data}</p>; }
  const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
  try {
    await act(async () => root.render(<View load={oldLoad} />));
    await act(async () => root.render(<View load={newLoad} />));
    await act(async () => second('новый участок'));
    await act(async () => first('старый участок'));
    expect(container.textContent).toBe('новый участок');
  } finally { await act(async () => root.unmount()); container.remove(); }
});
