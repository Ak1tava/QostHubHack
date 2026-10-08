import { useEffect, useState } from 'react';

export type Locale = 'ru' | 'kk';
export type Theme = 'light' | 'dark';
const ru = {
  close: 'Закрыть', pending: 'Подождите…', why: 'Почему?', offline: 'Нет связи',
  offlineDetail: 'Действия доступны после восстановления связи. Изменения не отправлены.',
  deadlineUnknown: 'Срок не указан', remaining: 'До срока', overdue: 'Просрочен', minutes: 'мин',
  empty: 'Пока нет нарядов', emptyDetail: 'Новые назначения появятся здесь.', loading: 'Загрузка…',
  title: 'Один язык интерфейса. В каждом наряде.', eyebrow: 'НарядAI / Дизайн-система',
  subtitle: 'Чёткие статусы. Крупные действия. Всё важное — с первого взгляда.',
  demo: 'Витрина компонентов · демонстрационные данные', back: 'В приложение',
  light: 'Светлая', dark: 'Тёмная', theme: 'Тема', language: 'Язык',
  palette: 'Цвет и смысл', paletteDetail: 'Оранжевый ведёт к действию. Цвет статуса всегда сопровождается текстом.',
  background: 'Фон', surface: 'Поверхность', primary: 'Навигация', accent: 'Главное действие',
  states: 'Статусы без догадок', orders: 'Наряды', people: 'Исполнители', priorities: 'Приоритеты', verdicts: 'Вывод ИИ',
  type: 'Читается в цеху', typeDetail: 'Ә Ғ Қ Ң Ө Ұ Ү Һ І · 0123456789',
  typeSample: 'Наряд выдан — ИИ на контроле', numberLabel: 'Номер наряда', dueLabel: 'До срока',
  actions: 'Действие на первом месте', issue: 'Выдать наряд', continue: 'Продолжить', cancel: 'Отменить',
  pendingExample: 'Отправка', disabledExample: 'Недоступно', reason: 'Причина приостановки',
  parts: 'Ждём детали', access: 'Нет доступа', help: 'Нужна помощь',
  deadlines: 'Срок виден сразу', comfortable: 'Есть время', near: 'Срок приближается', urgent: 'Осталось мало времени',
  aiTitle: 'Проверка отчёта', aiExample: 'На демонстрационном фото нет общего плана оборудования.',
  aiWhy: 'Для сравнения нужны сопоставимые ракурсы до и после ремонта.',
  aiLimit: 'Пример вывода. Решение о приёмке принимает мастер.',
  details: 'Посмотреть детали', overlays: 'Подробности рядом', drawer: 'Открыть панель', sheet: 'Открыть нижнюю панель',
  drawerTitle: 'Детали наряда', sheetTitle: 'Укажите причину', sampleOrder: 'Демонстрационный наряд №147',
  sampleDescription: 'Замена уплотнения насоса. Все данные на этой странице — примеры.',
  feedback: 'Обратная связь', toast: 'Показать уведомление', toastMessage: 'Пример уведомления',
  emptyHeading: 'Пустое состояние', skeletonHeading: 'Ожидание данных', offlineHeading: 'Потеря связи',
  kpis: 'Смена в цифрах', issued: 'Выдано', active: 'В работе', closed: 'Закрыто', overdueLabel: 'Просрочено',
  realtime: 'Обновление статуса', highlight: 'Показать подсветку', statusUpdated: 'Статус обновлён',
  footer: 'Основа мобильной PWA и панели мастера', localizationNote: 'Перевод экранов подключается поэтапно.',
};
const kk: Record<keyof typeof ru, string> = {
  close: 'Жабу', pending: 'Күтіңіз…', why: 'Неліктен?', offline: 'Байланыс жоқ',
  offlineDetail: 'Байланыс қалпына келгенде әрекеттер қолжетімді болады. Өзгерістер жіберілмеді.',
  deadlineUnknown: 'Мерзім көрсетілмеген', remaining: 'Мерзімге дейін', overdue: 'Мерзімі өткен', minutes: 'мин',
  empty: 'Әзірге наряд жоқ', emptyDetail: 'Жаңа тапсырмалар осында пайда болады.', loading: 'Жүктелуде…',
  title: 'Әр нарядта — бірізді интерфейс.', eyebrow: 'НарядAI / Дизайн жүйесі',
  subtitle: 'Түсінікті күйлер. Ірі батырмалар. Маңыздысы бірден көрінеді.',
  demo: 'Компоненттер көрмесі · демонстрациялық деректер', back: 'Қолданбаға',
  light: 'Ашық', dark: 'Қараңғы', theme: 'Тақырып', language: 'Тіл',
  palette: 'Түс пен мағына', paletteDetail: 'Қызғылт сары түс әрекетке бағыттайды. Күй түсімен бірге мәтін көрсетіледі.',
  background: 'Фон', surface: 'Бет', primary: 'Навигация', accent: 'Негізгі әрекет',
  states: 'Түсінікті күйлер', orders: 'Нарядтар', people: 'Орындаушылар', priorities: 'Басымдықтар', verdicts: 'ЖИ қорытындысы',
  type: 'Цехта да анық оқылады', typeDetail: 'Ә Ғ Қ Ң Ө Ұ Ү Һ І · 0123456789',
  typeSample: 'Наряд берілді — ЖИ бақылауда', numberLabel: 'Наряд нөмірі', dueLabel: 'Мерзімге дейін',
  actions: 'Әрекет бірінші орында', issue: 'Наряд беру', continue: 'Жалғастыру', cancel: 'Болдырмау',
  pendingExample: 'Жіберілуде', disabledExample: 'Қолжетімсіз', reason: 'Кідірту себебі',
  parts: 'Бөлшектерді күтудеміз', access: 'Кіру мүмкін емес', help: 'Көмек қажет',
  deadlines: 'Мерзім бірден көрінеді', comfortable: 'Уақыт бар', near: 'Мерзім жақындады', urgent: 'Уақыт аз қалды',
  aiTitle: 'Есепті тексеру', aiExample: 'Демонстрациялық фотода жабдықтың жалпы көрінісі жоқ.',
  aiWhy: 'Салыстыру үшін жөндеуге дейінгі және кейінгі ұқсас ракурстар қажет.',
  aiLimit: 'Қорытынды үлгісі. Қабылдау туралы шешімді шебер қабылдайды.',
  details: 'Толығырақ', overlays: 'Мәліметтер жақын жерде', drawer: 'Панельді ашу', sheet: 'Төменгі панельді ашу',
  drawerTitle: 'Наряд мәліметтері', sheetTitle: 'Себебін көрсетіңіз', sampleOrder: 'Демонстрациялық наряд №147',
  sampleDescription: 'Сорғы тығыздағышын ауыстыру. Бұл беттегі барлық деректер — үлгілер.',
  feedback: 'Кері байланыс', toast: 'Хабарламаны көрсету', toastMessage: 'Хабарлама үлгісі',
  emptyHeading: 'Бос күй', skeletonHeading: 'Деректерді күту', offlineHeading: 'Байланыс үзілуі',
  kpis: 'Ауысым сандармен', issued: 'Берілген', active: 'Орындалуда', closed: 'Жабылған', overdueLabel: 'Мерзімі өткен',
  realtime: 'Күйді жаңарту', highlight: 'Бөлектеуді көрсету', statusUpdated: 'Күй жаңартылды',
  footer: 'Мобильді PWA мен шебер панелінің негізі', localizationNote: 'Экран аудармалары кезең-кезеңімен қосылады.',
};
export type MessageKey = keyof typeof ru;
export function translate(locale: Locale, key: MessageKey) { return (locale === 'kk' ? kk : ru)[key]; }

// Preferences belong to the preview until the existing screens adopt the dictionary in T17.
function readPreference<T extends string>(key: string, options: readonly T[], fallback: T): T {
  try { const value = localStorage.getItem(key); return options.includes(value as T) ? value as T : fallback; }
  catch { return fallback; }
}
export function useUiPreferences() {
  const [locale, setLocale] = useState<Locale>(() => readPreference('naryadai.ui-kit.locale', ['ru', 'kk'], 'ru'));
  const [theme, setTheme] = useState<Theme>(() => readPreference('naryadai.ui-kit.theme', ['light', 'dark'], 'light'));
  useEffect(() => {
    try { localStorage.setItem('naryadai.ui-kit.locale', locale); localStorage.setItem('naryadai.ui-kit.theme', theme); }
    catch { /* The preview also works with storage disabled. */ }
  }, [locale, theme]);
  return { locale, setLocale, theme, setTheme, t: (key: MessageKey) => translate(locale, key) };
}
