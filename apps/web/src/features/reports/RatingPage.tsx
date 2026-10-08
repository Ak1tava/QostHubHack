import { useLocale } from '../../ui/locale';
import type { ApiClient, UserView } from '../../lib/api';
import { number, useReport, useReportContext, type Rating } from './data';
import { Limitations, ReportFilters, ReportPeriodDetails, ReportStatus } from './ReportFilters';
import { ReportHeading } from './ReportHeading';
import { ratingReason } from './analyticsCopy';

const labels = { Q: 'Качество', T: 'Своевременность', R: 'Без подтверждённых возвратов', V: 'Нормативная загрузка' };
const weights = { Q: .50, T: .25, R: .15, V: .10 };
const componentKeys = Object.keys(labels) as (keyof typeof labels)[];

export function RatingPage({ api, user }: { api: ApiClient; user: UserView }) {
  const { tx, locale } = useLocale();
  const context = useReportContext(api, user);
  const report = useReport<Rating>(api, '/api/v1/reports/rating', context.query);
  const data = context.query ? report.data : null;
  const groups = new Map<string, Rating['items']>();
  for (const item of data?.items ?? []) {
    if (user.role === 'worker' && item.worker_id !== user.id) continue;
    const group = ((item.specialty || 'Специальность не указана') + " · " + (item.work_type === 'planned' ? tx('Плановые работы') : tx('Аварийные работы')));
    groups.set(group, [...(groups.get(group) ?? []), item]);
  }
  return <section className="page report-page">
    <ReportHeading user={user} title={tx("Рейтинг исполнителей")} description={tx("Сопоставимые работы, окончательные оценки и размер выборки")} />
    <ReportFilters context={context} user={user} period={data?.period} /><ReportStatus context={context} report={report} />
    <details className="report-panel rating-formula"><summary>{tx("Как считается рейтинг")}</summary>
      <p>{tx("100 × (0,50Q + 0,25T + 0,15R + 0,10V). Если часть компонентов недоступна, веса доступных компонентов нормируются: сумма их взвешенных значений делится на сумму доступных весов.")}</p>
      <p>{tx("Q — средняя окончательная оценка мастера / 5. T — доля своевременно принятых сдач. R — доля без подтверждённого возврата по качеству после полного окна 7 дней. V — нормативные часы / доступные часы, не больше 1. Без закрытых работ рейтинг не рассчитывается.")}</p>
      <p>{tx("Сравнивайте только одинаковую специальность и тип работ. Подтверждённые корректировки сроков и нормативные часы учитываются только при наличии данных; оценка ИИ не заменяет решение мастера.")}</p>
    </details>
    {data && <><ReportPeriodDetails period={data.period} />
      {groups.size === 0 && <p className="report-empty">{tx("Нет закрытых работ для рейтинга в выбранном периоде.")}</p>}
      {[...groups].map(([group, items]) => <section className="rating-group" key={group}><h3>{group}</h3><p className="muted">{tx("Сравнение внутри одной специальности и типа работ.")}</p><div className="rating-list">{items.map(item => {
        const available = componentKeys.filter(key => item.components[key].value !== null);
        const totalWeight = available.reduce((total, key) => total + weights[key], 0);
        return <article className="report-panel rating-card" key={`${item.worker_id}:${item.work_type}`}>
          <div className="rating-person"><div><h4>{item.display_name}</h4><p>{tx("Закрыто работ: ")}{number(item.closed_count)}</p></div><div className="rating-score"><strong aria-label={tx("Итоговый рейтинг")}>{item.score === null ? tx("Нет данных") : `${number(item.score)} / 100`}</strong>{item.score !== null && <meter min={0} max={100} value={item.score} aria-label={(tx("Рейтинг: ") + (item.display_name))} />}</div></div>
          <dl className="rating-components">{componentKeys.map(key => { const component = item.components[key]; return <div key={key}><dt>{key} · {tx(labels[key])}</dt><dd><strong>{component.value === null ? tx("Нет данных") : `${number(component.value * 100)}%`}</strong>{component.value !== null && <meter min={0} max={1} value={component.value} aria-label={`${tx(labels[key])}: ${item.display_name}`} />}<small>{tx("Выборка: ")}{number(component.sample_size)}</small>{component.reason && <p className="muted">{ratingReason(locale, component.reason)}</p>}</dd></div>; })}</dl>
          <p className="rating-weights">{totalWeight ? (tx("Веса доступных компонентов: ") + (available.map(key => `${key} ${number(weights[key] / totalWeight * 100)}%`).join(' · ')) + tx(". Компоненты без данных не участвуют в оценке.")) : tx("Доступных компонентов нет.")}</p>
        </article>;
      })}</div></section>)}<Limitations items={data.limitations} />
    </>}
  </section>;
}
