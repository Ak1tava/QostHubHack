import { useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { ApiError } from '../lib/api';
import type { WorkOrderTemplate } from '../features/work-orders/TemplateRequirements';
import { LocaleContext, readPreference, translate, type Locale, type MessageKey } from './i18n';
import { appMessages } from './appMessages';
import { statusCatalog } from './status';

const messages = { ...appMessages, ...Object.fromEntries(Object.values(statusCatalog).flatMap(group => Object.values(group).flatMap(entry =>
  [[entry.ru, entry.kk], ...('column' in entry ? [[entry.column, entry.kk]] : [])]))),
};
export function translateText(locale: Locale, text: string): string {
  const key = text.trim();
  const translated = locale === 'kk' && Object.hasOwn(messages, key) ? messages[key] : undefined;
  return translated ? text.replace(key, translated) : text;
}
const errors: Record<string, [string, string]> = {
  invalid_credentials: ['Неверный логин или пароль.', 'Логин немесе құпиясөз қате.'],
  unauthenticated: ['Сессия истекла. Войдите снова.', 'Сессия аяқталды. Қайта кіріңіз.'],
  forbidden: ['Недостаточно прав для этого действия.', 'Бұл әрекетке құқық жеткіліксіз.'],
  csrf_failed: ['Сессия обновлена. Повторите действие.', 'Сессия жаңартылды. Әрекетті қайталаңыз.'],
  unavailable: ['Сервер недоступен. Проверьте соединение и повторите попытку.', 'Сервер қолжетімсіз. Байланысты тексеріп, қайталаңыз.'],
  rate_limited: ['Слишком частые попытки. Повторите позже.', 'Әрекеттер тым жиі. Кейін қайталаңыз.'],
  not_found: ['Объект не найден или недоступен.', 'Нысан табылмады немесе қолжетімсіз.'],
  version_conflict: ['Данные изменились. Обновите страницу и проверьте действие.', 'Деректер өзгерді. Бетті жаңартып, әрекетті тексеріңіз.'],
  validation_error: ['Проверьте поля формы.', 'Пішін өрістерін тексеріңіз.'],
  worker_busy: ['У исполнителя уже есть активный наряд.', 'Орындаушыда белсенді наряд бар.'],
  invalid_assignment: ['Недопустимое назначение исполнителя.', 'Орындаушыны тағайындау жарамсыз.'],
  invalid_equipment: ['Оборудование не относится к участку.', 'Жабдық бұл учаскеге жатпайды.'],
  idempotency_conflict: ['Ключ уже использован для другого запроса.', 'Кілт басқа сұрау үшін қолданылған.'],
};
export function localizeError(locale: Locale, error: Error): string {
  // Unknown codes and details may contain arbitrary server input; preserve them verbatim.
  if (locale === 'kk' && error instanceof ApiError && Object.hasOwn(errors, error.code)) return errors[error.code][1];
  return error.message;
}
export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>(() => readPreference('naryadai.locale', ['ru', 'kk'], 'ru'));
  useEffect(() => {
    document.documentElement.lang = locale;
    try { localStorage.setItem('naryadai.locale', locale); } catch { /* Storage may be denied in private browsing. */ }
  }, [locale]);
  const value = useMemo(() => ({ locale, setLocale }), [locale]);
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}
export function useLocale() {
  const context = useContext(LocaleContext);
  const locale = context?.locale ?? 'ru';
  return { locale, setLocale: context?.setLocale ?? (() => {}),
    t: (key: MessageKey) => translate(locale, key),
    tx: (text: string) => translateText(locale, text),
    errorText: (error: Error) => localizeError(locale, error),
  };
}
export function LanguageSelector() {
  const { locale, setLocale, t } = useLocale();
  return <div className="language-selector" role="group" aria-label={t('language')}>
    <button type="button" lang="ru" aria-pressed={locale === 'ru'} onClick={() => setLocale('ru')}>RU</button>
    <button type="button" lang="kk" aria-pressed={locale === 'kk'} onClick={() => setLocale('kk')}>Қазақша</button>
  </div>;
}
const templates: Record<string, { title: string; instructions: string[]; checklist: Record<string, string> }> = {
  visible_leak: {
    title: 'Көрінетін ағуды жою',
    instructions: ['Жұмысқа дейін ағудың көрінетін жерін фотоға түсіріңіз.', 'Орындалған жұмысты сипаттап, жұмыстан кейін сол жерді фотоға түсіріңіз.', 'Тек тексерілген көрінетін белгілерді белгілеңіз; фото жасырын күйді немесе пайдалану қауіпсіздігін растамайды.'],
    checklist: { identify_leak: 'Ағудың көрінетін жері көрсетіліп, тіркелген.', describe_repair: 'Ағуды жою бойынша орындалған жұмыс сипатталған.', inspect_result: 'Нәтиже көзбен тексеріліп, тіркелген.' },
  },
  visible_element: {
    title: 'Көрінетін элементті қалпына келтіру',
    instructions: ['Жұмысқа дейін көрінетін элемент пен зақымды фотоға түсіріңіз.', 'Қалпына келтіруді сипаттап, жұмыстан кейін сол элементті фотоға түсіріңіз.', 'Тек тексерілген көрінетін белгілерді белгілеңіз; фото жасырын күйді немесе пайдалану қауіпсіздігін растамайды.'],
    checklist: { identify_element: 'Көрінетін элемент пен зақым көрсетіліп, тіркелген.', describe_restoration: 'Қалпына келтіру бойынша орындалған жұмыс сипатталған.', inspect_result: 'Нәтиже көзбен тексеріліп, тіркелген.' },
  },
};
export function localizedTemplate(template: WorkOrderTemplate, locale: Locale): WorkOrderTemplate {
  if (locale !== 'kk' || template.version !== 1 || !Object.hasOwn(templates, template.id)) return template;
  const translated = templates[template.id];
  return { ...template, title: translated.title, instructions: translated.instructions,
    checklist: template.checklist.map(item => ({ ...item, label: Object.hasOwn(translated.checklist, item.id) ? translated.checklist[item.id] : item.label })),
  };
}
