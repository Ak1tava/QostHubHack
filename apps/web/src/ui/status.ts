import type { components } from '../../../../packages/contracts/api.generated';
import type { Locale } from './i18n';

export type Tone = 'ok' | 'busy' | 'queue' | 'off' | 'danger' | 'high';
type Entry = { ru: string; kk: string; tone: Tone; column?: string };
type OrderStatus = components['schemas']['WorkOrderView']['status'];
type Priority = components['schemas']['WorkOrderView']['priority'];
type Availability = components['schemas']['ShiftMemberView']['availability'];
type Verdict = components['schemas']['ReviewResult']['verdict'];

export const statusCatalog = {
  order: {
    ISSUED: { ru: 'Выдан', kk: 'Берілген', tone: 'queue', column: 'Выданы' },
    ACCEPTED: { ru: 'Принят', kk: 'Қабылданған', tone: 'queue', column: 'Приняты' },
    QUEUED: { ru: 'В очереди', kk: 'Кезекте', tone: 'queue', column: 'Очередь' },
    REJECTED: { ru: 'Отклонён', kk: 'Бас тартылған', tone: 'off', column: 'Отказ' },
    IN_PROGRESS: { ru: 'В работе', kk: 'Орындалуда', tone: 'busy' },
    PAUSED: { ru: 'Приостановлен', kk: 'Кідіртілген', tone: 'busy', column: 'Пауза' },
    SUBMITTED: { ru: 'Отчёт отправлен', kk: 'Есеп жіберілді', tone: 'queue', column: 'На приёмке' },
    AI_REVIEW: { ru: 'Проверка ИИ', kk: 'ЖИ тексеруі', tone: 'queue', column: 'Проверка' },
    REWORK: { ru: 'На доработке', kk: 'Түзетілуде', tone: 'danger', column: 'Доработка' },
    CLOSED: { ru: 'Закрыт', kk: 'Жабылған', tone: 'ok', column: 'Закрыты' },
    CANCELLED: { ru: 'Отменён', kk: 'Күші жойылған', tone: 'off', column: 'Отменены' },
  } satisfies Record<OrderStatus, Entry>,
  priority: {
    emergency: { ru: 'Аварийный', kk: 'Апаттық', tone: 'danger' },
    high: { ru: 'Высокий', kk: 'Жоғары', tone: 'high' },
    normal: { ru: 'Обычный', kk: 'Қалыпты', tone: 'off' },
    planned: { ru: 'Плановый', kk: 'Жоспарлы', tone: 'queue' },
  } satisfies Record<Priority, Entry>,
  availability: {
    free: { ru: 'Свободен', kk: 'Бос', tone: 'ok' },
    busy: { ru: 'Занят', kk: 'Бос емес', tone: 'busy' },
    queued: { ru: 'В очереди', kk: 'Кезекте', tone: 'queue' },
    off_shift: { ru: 'Вне смены', kk: 'Ауысымда емес', tone: 'off' },
  } satisfies Record<Availability, Entry>,
  verdict: {
    accepted: { ru: 'Замечаний не найдено', kk: 'Ескертулер табылмады', tone: 'ok' },
    accepted_with_notes: { ru: 'Есть замечания', kk: 'Ескертулер бар', tone: 'busy' },
    requires_rework: { ru: 'Требуется доработка', kk: 'Түзету қажет', tone: 'danger' },
    human_review: { ru: 'Требуется проверка мастера', kk: 'Шебердің тексеруі қажет', tone: 'queue' },
  } satisfies Record<Verdict, Entry>,
};
export type StatusDomain = keyof typeof statusCatalog;
export function describeStatus(domain: StatusDomain, status: string, locale: Locale = 'ru'): { label: string; tone: Tone } {
  const group: Record<string, Entry> = statusCatalog[domain];
  if (!Object.hasOwn(group, status)) return { label: status, tone: 'off' };
  const entry = group[status];
  return { label: entry[locale], tone: entry.tone };
}
export function statusLabels<D extends StatusDomain>(domain: D, locale: Locale = 'ru', columns = false) {
  return Object.fromEntries(Object.entries(statusCatalog[domain]).map(([key, value]) =>
    [key, columns && locale === 'ru' && 'column' in value ? value.column : value[locale]]
  )) as Record<keyof typeof statusCatalog[D], string>;
}
