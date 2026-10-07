import type { ApiClient, UserView } from '../../lib/api';
import { number, useReport, useReportContext, type Rating } from './data';
import { Limitations, ReportFilters, ReportPeriodDetails, ReportStatus } from './ReportFilters';

const labels = { Q: 'Качество', T: 'Своевременность', R: 'Без подтверждённых возвратов', V: 'Нормативная загрузка' };

export function RatingPage({ api, user }: { api: ApiClient; user: UserView }) {
  const context = useReportContext(api, user);
  const report = useReport<Rating>(api, '/api/v1/reports/rating', context.query);
  const data = context.query ? report.data : null;
  const groups = new Map<string, Rating['items']>();
  for (const item of data?.items ?? []) {
    if (user.role === 'worker' && item.worker_id !== user.id) continue;
    const group = `${item.specialty || 'Специальность не указана'} · ${item.work_type === 'planned' ? 'Плановые работы' : 'Аварийные работы'}`;
    groups.set(group, [...(groups.get(group) ?? []), item]);
  }
  return <section className="page report-page"><h2>Рейтинг исполнителей</h2>
    <ReportFilters context={context} user={user} /><ReportStatus context={context} report={report} />
    <details className="action-form"><summary>Как считается рейтинг</summary>
      <p>100 × (0,50Q + 0,25T + 0,15R + 0,10V). Если часть компонентов недоступна, веса доступных компонентов нормируются: сумма их взвешенных значений делится на сумму доступных весов.</p>
      <p>Q — средняя окончательная оценка мастера / 5. T — доля своевременно принятых сдач. R — доля без подтверждённого возврата по качеству после полного окна 7 дней. V — нормативные часы / доступные часы, не больше 1. Без закрытых работ рейтинг не рассчитывается.</p>
      <p>Сравнивайте только одинаковую специальность и тип работ. Подтверждённые корректировки сроков и нормативные часы учитываются только при наличии данных; оценка ИИ не заменяет решение мастера.</p>
    </details>
    {data && <><ReportPeriodDetails period={data.period} />
      {groups.size === 0 && <p>Нет закрытых работ для рейтинга в выбранном периоде.</p>}
      {[...groups].map(([group, items]) => <section key={group}><h3>{group}</h3><div className="worker-grid">{items.map(item => <article className="worker-card rating-card" key={`${item.worker_id}:${item.work_type}`}>
        <h4>{item.display_name}</h4><strong aria-label="Итоговый рейтинг">{item.score === null ? 'Нет данных' : `${number(item.score)} / 100`}</strong><p>Закрыто работ: {number(item.closed_count)}</p>
        <dl>{(Object.keys(labels) as (keyof typeof labels)[]).map(key => { const component = item.components[key]; return <div key={key}><dt>{key} · {labels[key]}</dt><dd>{component.value === null ? 'Нет данных' : `${number(component.value * 100)}%`}<br />Выборка: {number(component.sample_size)}{component.reason && <p className="muted">{component.reason}</p>}</dd></div>; })}</dl>
      </article>)}</div></section>)}<Limitations items={data.limitations} />
    </>}
  </section>;
}
