import { useEffect, useRef, useState } from 'react';
import { ApiError } from './api';

export function useCommand<T, R>(send: (body: T, key: string) => Promise<R>) {
  const snapshot = useRef<{ body: T; key: string } | null>(null);
  const running = useRef(false);
  const generation = useRef(0);
  const [state, setState] = useState<{ busy: boolean; pending: boolean; error: Error | null }>({ busy: false, pending: false, error: null });
  useEffect(() => () => { generation.current++; snapshot.current = null; }, []);

  async function run(body?: T): Promise<R | null> {
    if (running.current || (!snapshot.current && body === undefined)) return null;
    running.current = true;
    const current = generation.current;
    if (!snapshot.current) snapshot.current = { body: structuredClone(body!), key: crypto.randomUUID() };
    const command = snapshot.current;
    setState(previous => ({ ...previous, busy: true, error: null }));
    try {
      const result = await send(command.body, command.key);
      if (current !== generation.current) return null;
      snapshot.current = null; setState({ busy: false, pending: false, error: null });
      return result;
    } catch (error) {
      if (current !== generation.current) return null;
      const definitive = error instanceof ApiError && error.status >= 400 && error.status < 500;
      if (definitive) snapshot.current = null;
      setState({ busy: false, pending: !definitive, error: error instanceof Error ? error : new Error('Не удалось выполнить команду') });
      return null;
    } finally { running.current = false; }
  }
  return { ...state, run };
}
