import { useLocale } from '../../ui/locale';
import type { ApiClient, UserView } from '../../lib/api';
import { duration, number, useReport, useReportContext, type ShiftReport } from './data';
import { Limitations, ReportFilters, ReportPeriodDetails, ReportStatus } from './ReportFilters';
import { ReportHeading } from './ReportHeading';
import { MetricBars } from './MetricBars';
import { Icon } from '../../components/Icon';

const counts = [
  { key: 'issued', label: 'Выдано', hint: 'Созданы в периоде', color: '' },
  { key: 'performed', label: 'Исполнено', hint: 'Работы сданы', color: 'mint' },
  { key: 'closed', label: 'Закрыто', hint: 'Приняты мастером', color: 'green' },
  { key: 'overdue', label: 'Просрочено', hint: 'Срок нарушен в периоде', color: 'amber' },
  { key: 'rejected', label: 'Отклонено', hint: 'Отказы исполнителей', color: 'red' },
] as const;

export function ShiftReportPage({ api, user }: { api: ApiClient; user: UserView }) {
  const { tx } = useLocale();
  const context = useReportContext(api, user, true);
  const report = useReport<ShiftReport>(api, '/api/v1/reports/shift', context.query);
  const data = context.query ? report.data : null;
  return <section className="page report-page">
    <ReportHeading user={user} title={user.role === 'worker' ? tx("Мои показатели") : tx("Отчёты и статистика")} description={tx("Результаты работ, время и закономерности ремонтов")} />
    <ReportFilters context={context} user={user} allowShift period={data?.period} /><ReportStatus context={context} report={report} />
    {data && <><ReportPeriodDetails period={data.period} />
      <dl className="report-kpis" aria-label={tx("Показатели отчёта")}>{counts.map(item => <div className="report-kpi" key={item.key}><dt><span className={`metric-dot ${item.color}`} />{tx(item.label)}</dt><dd><strong>{number(data.counts[item.key])}</strong><small>{tx(item.hint)}</small></dd></div>)}</dl>
      {Object.values(data.counts).every(value => value === 0) && <p className="report-empty">{tx("В выбранном периоде нарядов нет.")}</p>}
      <div className="report-chart-grid">
        <MetricBars title={tx("Наряды за период")} unit={tx("Наряды, шт.")} items={counts.map(item => ({ ...item, label: tx(item.label), value: data.counts[item.key] }))} caption={tx("Показатели пересекаются. Их сумма не равна общему числу нарядов.")} />
        <div className="report-panel workload-panel"><MetricBars title={tx("Длительности")} unit={tx("Время")} items={[
          { label: tx("Работа"), value: data.workload.active_seconds, text: duration(data.workload.active_seconds), color: 'green' },
          { label: tx("Паузы"), value: data.workload.pause_seconds, text: duration(data.workload.pause_seconds), color: 'amber' },
          { label: tx("Приёмка"), value: data.workload.review_seconds, text: duration(data.workload.review_seconds) },
        ]} /><dl className="downtime-stat"><div><dt>{tx("Простой оборудования")}</dt><dd>{data.downtime.has_data ? duration(data.downtime.seconds) : tx("Нет данных о простое")}</dd></div></dl><p className="chart-caption">{tx("Пересекающиеся интервалы одного оборудования объединены. Простой учитывается отдельно от времени работ.")}</p></div>
      </div>
      <article className="report-panel report-summary"><Icon name="list" /><div><h3>{tx("Сводка")}</h3><p className="full-description">{data.summary}</p></div></article><Limitations items={data.limitations} />
    </>}
  </section>;
}
