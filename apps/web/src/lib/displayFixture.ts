// Exact fixture markers are formatted only for display; stored reports and evidence are unchanged.
export function displayFixtureName(value: string): string {
  if (value === '[T18 СИНТЕТИКА] Исполнитель судей') return 'Рабочий 1';
  return value.replace(/^\[T18 СИНТЕТИКА\] (Участок|Бригада) судей jury-2026(?:-prepared-v2)?$/u, '$1')
    .replace(/^\[T18 СИНТЕТИКА\] (Участок|Бригада|Мастер|Исполнитель) судей(?= |$)/u, '$1')
    .replace(/^\[ДЕМО\] ((?:Мастер|Исполнитель|Насос|Компрессор|Электродвигатель|Вентилятор|Подшипник|Масло|Уплотнение|Крепёж|Фильтр) \d{2})$/u, '$1')
    .replace(/^\[ДЕМО\] (Насосная|Компрессорная|Электроцех|Вентиляция|Бригада [1-3])(?: \/ \d+-\d{4}-\d{2}-\d{2})?$/u, '$1');
}
export function displayOrderNumber(value: string): string {
  return value.replace(/^T18-[a-z0-9_-]+-(\d{2})$/i, '$1')
    .replace(/^T09-\d+-\d{4}-\d{2}-\d{2}-(\d{4})$/, '$1');
}
export function displayOrderDescription(value: string): string {
  return value.replace(/^\[T18 СИНТЕТИКА\] /u, '');
}
export function displayFaultCode(value: string): string {
  return value.replace(/^T18-[a-z0-9_-]+-([A-Z]\d+)$/, '$1')
    .replace(/^T09-\d+-\d{4}-\d{2}-\d{2}-([A-Z]\d+)$/, '$1');
}
