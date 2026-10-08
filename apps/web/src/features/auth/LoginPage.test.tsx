import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import { LoginPage } from './LoginPage';
import { LocaleProvider } from '../../ui/locale';

it('offers three fixed profiles in RU/KZ and submits only the selected profile code', async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement('div'); const root = createRoot(container);
  const login = vi.fn().mockResolvedValue(undefined);
  try {
    for (const locale of ['ru', 'kk']) {
      localStorage.setItem('naryadai.locale', locale);
      await act(async () => root.render(<LocaleProvider key={locale}><LoginPage busy={false} error={null} onLogin={vi.fn()} onJudgeLogin={login} profiles={[
        { code: 'master', display_name: 'internal', role: 'master' },
        { code: 'worker-1', display_name: 'internal', role: 'worker' },
        { code: 'worker-2', display_name: 'internal', role: 'worker' },
      ]} /></LocaleProvider>));
      const buttons = container.querySelectorAll<HTMLButtonElement>('.judge-profiles button');
      expect(Array.from(buttons, button => button.textContent)).toEqual(locale === 'ru' ? ['Мастер', 'Рабочий 1', 'Рабочий 2'] : ['Шебер', 'Жұмысшы 1', 'Жұмысшы 2']);
      await act(async () => buttons[2].click());
      expect(login).toHaveBeenLastCalledWith('worker-2');
    }
  } finally { await act(async () => root.unmount()); localStorage.removeItem('naryadai.locale'); }
});
