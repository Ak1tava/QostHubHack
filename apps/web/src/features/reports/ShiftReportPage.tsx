import type { ApiClient, UserView } from '../../lib/api';
import { duration, number, useReport, useReportContext, type ShiftReport } from './data';
import { Limitations, ReportFilters, ReportPeriodDetails, ReportStatus } from './ReportFilters';

export function ShiftReportPage({ api, user }: { api: ApiClient; user: UserView }) {
  const context = useReportContext(api, user, true);
  const report = useReport<ShiftReport>(api, '/api/v1/reports/shift', context.query);
  const data = context.query ? report.data : null;
  return <section className="page report-page"><h2>Отчёт смены и периода</h2>
    <ReportFilters context={context} user={user} allowShift /><ReportStatus context={context} report={report} />
    {data && <><ReportPeriodDetails period={data.period} />
      <dl className="order-info" aria-label="Показатели отчёта">
        <dt>Выдано</dt><dd>{number(data.counts.issued)}</dd><dt>Исполнено</dt><dd>{number(data.counts.performed)}</dd><dt>Закрыто</dt><dd>{number(data.counts.closed)}</dd><dt>Просрочено</dt><dd>{number(data.counts.overdue)}</dd><dt>Отклонено</dt><dd>{number(data.counts.rejected)}</dd>
      </dl>
      <h3>Длительности</h3><dl className="order-info"><dt>Работа</dt><dd>{duration(data.workload.active_seconds)}</dd><dt>Паузы</dt><dd>{duration(data.workload.pause_seconds)}</dd><dt>Приёмка</dt><dd>{duration(data.workload.review_seconds)}</dd><dt>Простой оборудования</dt><dd>{data.downtime.has_data ? duration(data.downtime.seconds) : 'Нет данных о простое'}</dd></dl>
      {Object.values(data.counts).every(value => value === 0) && <p>В выбранном периоде нарядов нет.</p>}
      <h3>Сводка</h3><p className="full-description">{data.summary}</p><Limitations items={data.limitations} />
    </>}
  </section>;
}
