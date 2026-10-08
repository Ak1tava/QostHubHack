import { UiError } from './uiError';
const formatter = (timezone: string) => new Intl.DateTimeFormat('en-CA', {
  timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});

export function localDateTime(value: string, timezone: string): string {
  const parts = Object.fromEntries(formatter(timezone).formatToParts(new Date(value)).map(part => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

export function utcDateTime(value: string, timezone: string): string {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) throw new UiError('deadline_required');
  const target = Date.parse(`${value}:00Z`);
  let instant = target;
  for (let attempt = 0; attempt < 3; attempt++) {
    const displayed = localDateTime(new Date(instant).toISOString(), timezone);
    if (displayed === value) return new Date(instant).toISOString();
    instant += target - Date.parse(`${displayed}:00Z`);
  }
  throw new UiError('deadline_nonexistent');
}

export function displayTime(value: string, timezone: string): string {
  return new Intl.DateTimeFormat('ru-RU', { timeZone: timezone, day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(value));
}
