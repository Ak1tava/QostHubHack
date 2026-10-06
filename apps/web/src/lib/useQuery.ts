import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from './api';
import { events } from './events';

export function useQuery<T>(load: (signal: AbortSignal) => Promise<T>, live: boolean | 'refresh' = true) {
  const [state, setState] = useState<{ data: T | null; error: Error | null; loading: boolean }>({ data: null, error: null, loading: true });
  const refreshRef = useRef<() => void>(() => {});
  useEffect(() => {
    let active = true, pending = false;
    let controller: AbortController | null = null;
    setState({ data: null, error: null, loading: true });
    const refresh = async () => {
      if (!active) return;
      if (controller) { pending = true; return; }
      controller = new AbortController();
      try {
        const data = await load(controller.signal);
        if (active) setState({ data, error: null, loading: false });
      } catch (error) {
        if (active) setState(previous => ({
          data: error instanceof ApiError && error.status >= 400 && error.status < 500 ? null : previous.data,
          error: error instanceof Error ? error : new Error('Не удалось обновить данные'), loading: false,
        }));
      } finally {
        controller = null;
        if (active && pending) { pending = false; void refresh(); }
      }
    };
    refreshRef.current = () => { void refresh(); };
    void refresh();
    const unsubscribe = live ? events.subscribe(refreshRef.current, live === 'refresh') : () => {};
    return () => { active = false; controller?.abort(); unsubscribe(); };
  }, [load, live]);
  const reload = useCallback(() => refreshRef.current(), []);
  return { ...state, reload };
}
