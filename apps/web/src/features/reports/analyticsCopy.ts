import type { Locale } from '../../ui/i18n';
import type { Anomalies, ShiftReport } from './data';

// Exact authored analytics copy only. Free text, AI output and unknown future copy stay verbatim.
const limitations: Record<string, string> = {
  'У части нарядов отсутствует журнал: прошлые сроки и назначения восстановлены неполно.': 'Кейбір нарядтардың журналы жоқ: бұрынғы мерзімдер мен тағайындаулар толық қалпына келтірілмеген.',
  'Нет зарегистрированных интервалов простоя за период; это не подтверждает отсутствие простоя.': 'Кезеңде тоқтап тұру аралықтары тіркелмеген; бұл тоқтап тұру болмағанын растамайды.',
  'Уважительность отказов и внешние задержки не структурированы; скрытые штрафы не применяются.': 'Бас тартудың негізділігі мен сыртқы кідірістер құрылымдалмаған; жасырын айыптар қолданылмайды.',
  'Доступные веса нормированы: Q 0.50, T 0.25; R/V неизвестны.': 'Қолжетімді салмақтар нормаланған: Q 0.50, T 0.25; R/V белгісіз.',
  'T использует исторический срок: подтверждённые внешние задержки не структурированы.': 'T тарихи мерзімді пайдаланады: расталған сыртқы кідірістер құрылымдалмаған.',
  'Оценки ИИ и свободный текст причин не подтверждают качество или вину исполнителя.': 'ЖИ бағалары мен себептердің еркін мәтіні сапаны немесе орындаушының кінәсін растамайды.',
  'Повтор шифра и расход анализируются только по окончательно принятым отчётам.': 'Кодтың қайталануы мен шығын тек түпкілікті қабылданған есептер бойынша талданады.',
  'Без сопоставимой нормы превышение расхода не определяется.': 'Салыстыруға болатын норма болмаса, артық шығын анықталмайды.',
  'Совпадение во времени — сигнал для проверки причины, а не доказательство вины исполнителя.': 'Уақыт бойынша сәйкес келу — себепті тексеру сигналы, орындаушы кінәсінің дәлелі емес.',
};
const repeatReason = 'Нет структурированного подтверждения возврата или повтора по причине качества.';
const reasons: Record<string, string> = {
  'Нет окончательных оценок мастера.': 'Шебердің қорытынды бағалары жоқ.',
  'Нет принятых сдач с известным сроком.': 'Мерзімі белгілі қабылданған жұмыстар жоқ.',
  [repeatReason]: 'Сапа себебінен қайтару немесе қайталау туралы құрылымдалған растау жоқ.',
  'Нет нормативных часов работ и исторических доступных часов смен.': 'Жұмыстардың нормативтік сағаттары мен ауысымдардың тарихи қолжетімді сағаттары жоқ.',
};
function exactCopy(locale: Locale, text: string, translations: Record<string, string>) {
  return locale === 'kk' && Object.hasOwn(translations, text) ? translations[text] : text;
}
export function analyticsLimitation(locale: Locale, text: string) {
  return exactCopy(locale, text, limitations);
}
export function ratingReason(locale: Locale, text: string) {
  if (locale !== 'kk') return text;
  const match = /^Окно наблюдения 7 дней не завершено для ([1-9]\d*) работ\. Нет структурированного подтверждения возврата или повтора по причине качества\.$/.exec(text);
  return match?.[0] === text ? `${match[1]} жұмыс үшін 7 күндік бақылау кезеңі аяқталмаған. ${reasons[repeatReason]}` : exactCopy(locale, text, reasons);
}
export function shiftSummary(locale: Locale, report: ShiftReport) {
  if (locale !== 'kk') return report.summary;
  const { counts, downtime } = report;
  const prefix = `Выдано ${counts.issued}, исполнено ${counts.performed}, закрыто ${counts.closed}. Просроченных за период: ${counts.overdue}; отклонённых: ${counts.rejected}. `;
  // Do not reinterpret an unknown summary or one inconsistent with its structured counts.
  if (!report.summary.startsWith(prefix)) return report.summary;
  const suffix = report.summary.slice(prefix.length);
  let hours = '';
  if (downtime.has_data) {
    const match = /^Простой оборудования: (\d+\.\d{2}) ч\.$/.exec(suffix);
    if (!match || match[0] !== suffix) return report.summary;
    const expected = downtime.seconds / 3600;
    const rounded = Number(match[1]);
    // Python and JS round exact half ties differently. Check the rounding interval and retain server digits.
    const tolerance = 0.005 + Number.EPSILON * Math.max(1, Math.abs(expected)) * 4;
    if (!Number.isFinite(expected) || !Number.isFinite(rounded) || Math.abs(expected - rounded) > tolerance) return report.summary;
    hours = match[1];
  } else if (suffix !== 'Нет данных о простое оборудования.') return report.summary;
  return `Берілген ${counts.issued}, орындалған ${counts.performed}, жабылған ${counts.closed}. Кезеңде мерзімі өткен: ${counts.overdue}; қабылданбаған: ${counts.rejected}. `
    + (downtime.has_data ? `Жабдықтың тоқтап тұруы: ${hours} сағ.` : 'Жабдықтың тоқтап тұруы туралы деректер жоқ.');
}
const anomalyCopy = {
  repeat_fault: {
    title: ['Повтор одного шифра на оборудовании', 'Жабдықта бір кодтың қайталануы'],
    description: ['Два принятых ремонта одного оборудования с одинаковым окончательным шифром за 7 дней.', '7 күн ішінде бір жабдықтың бірдей қорытынды кодпен қабылданған екі жөндеуі.'],
  },
  after_planned: {
    title: ['Аварийный ремонт вскоре после плановой работы', 'Жоспарлы жұмыстан кейін көп ұзамай болған апаттық жөндеу'],
    description: ['Ближайшая аварийная работа началась в пределах 48 часов после приёмки плановой.', 'Ең жақын апаттық жұмыс жоспарлы жұмыс қабылданғаннан кейін 48 сағат ішінде басталған.'],
  },
  material_overuse: {
    title: ['Расход материала выше сопоставимой нормы', 'Материал шығыны салыстырмалы нормадан жоғары'],
    description: ['Расход окончательного принятого отчёта превышает норму оборудования, шифра и материала.', 'Түпкілікті қабылданған есептегі шығын жабдық, код және материал нормасынан жоғары.'],
  },
} as const;
export function anomalyText(locale: Locale, item: Anomalies['items'][number], field: 'title' | 'description') {
  if (locale !== 'kk' || !Object.hasOwn(anomalyCopy, item.type)) return item[field];
  const [source, translated] = anomalyCopy[item.type][field];
  return item[field] === source ? translated : item[field];
}
