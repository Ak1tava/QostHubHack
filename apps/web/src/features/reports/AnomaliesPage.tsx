import type { ApiClient, UserView } from '../../lib/api';
import { Fragment } from 'react';
import { Link } from 'react-router';
import { number, useReport, useReportContext, type Anomalies } from './data';
import { Limitations, ReportFilters, ReportPeriodDetails, ReportStatus } from './ReportFilters';
import { ReportHeading } from './ReportHeading';

const metricNames: Record<string, string> = { order_count: 'Количество нарядов', hours_between: 'Интервал, ч', hours_after_acceptance: 'После приёмки плановой работы, ч', actual: 'Фактический расход', norm: 'Норма расхода', ratio: 'Отношение к норме' };
const types = { repeat_fault: 'Повтор неисправности', after_planned: 'После плановой работы', material_overuse: 'Расход выше нормы' };

export function AnomaliesPage({ api, user }: { api: ApiClient; user: UserView }) {
  if (user.role === 'worker') return <p role="alert">Анализ оборудования недоступен исполнителю.</p>;
  return <EquipmentAnomalies api={api} user={user} />;
}

function EquipmentAnomalies({ api, user }: { api: ApiClient; user: UserView }) {
  const context = useReportContext(api, user);
  const report = useReport<Anomalies>(api, '/api/v1/analytics/anomalies', context.query);
  const data = context.query ? report.data : null;
  return <section className="page report-page">
    <ReportHeading user={user} title="Закономерности ремонтов" description="Сигналы для проверки с подтверждающими нарядами" />
    <ReportFilters context={context} user={user} period={data?.period} /><ReportStatus context={context} report={report} />
    <p className="muted">Сигналы требуют проверки причины. Связь с исполнителем или сменой сама по себе не доказывает причину.</p>
    {data && <><ReportPeriodDetails period={data.period} />{data.items.length === 0 && <p className="report-empty">Закономерностей по доступным данным за выбранный период не найдено.</p>}
      <div className="insights-grid">{data.items.map(item => <article className="report-panel insight-card" key={item.id}><span className={`insight-type ${item.type}`}>{types[item.type]}</span><h3>{item.title}</h3><p className="muted">Оборудование: {context.catalogs.data?.equipment.find(equipment => equipment.id === item.equipment_id)?.name ?? 'Оборудование из выбранной области доступа'}</p><p className="full-description">{item.description}</p>
        <dl className="order-info">{Object.entries(item.metrics).map(([key, value]) => <Fragment key={key}><dt>{metricNames[key] ?? key.replaceAll('_', ' ')}</dt><dd>{number(value)}</dd></Fragment>)}</dl>
        <details className="insight-evidence"><summary>Наряды, подтверждающие сигнал: {item.evidence_order_ids.length}</summary><ul>{item.evidence_order_ids.map((id, index) => <li key={id}><Link to={`/orders/${encodeURIComponent(id)}`}>Открыть подтверждающий наряд {index + 1}</Link></li>)}</ul></details><Limitations items={item.limitations} />
      </article>)}</div><Limitations items={data.limitations} /></>}
  </section>;
}
