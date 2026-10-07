import type { ApiClient, UserView } from '../../lib/api';
import { Fragment } from 'react';
import { Link } from 'react-router';
import { number, useReport, useReportContext, type Anomalies } from './data';
import { Limitations, ReportFilters, ReportPeriodDetails, ReportStatus } from './ReportFilters';

const metricNames: Record<string, string> = { order_count: 'Количество нарядов', hours_between: 'Интервал, ч', hours_after_acceptance: 'После приёмки плановой работы, ч', actual: 'Фактический расход', norm: 'Норма расхода', ratio: 'Отношение к норме' };

export function AnomaliesPage({ api, user }: { api: ApiClient; user: UserView }) {
  if (user.role === 'worker') return <p role="alert">Анализ оборудования недоступен исполнителю.</p>;
  return <EquipmentAnomalies api={api} user={user} />;
}

function EquipmentAnomalies({ api, user }: { api: ApiClient; user: UserView }) {
  const context = useReportContext(api, user);
  const report = useReport<Anomalies>(api, '/api/v1/analytics/anomalies', context.query);
  const data = context.query ? report.data : null;
  return <section className="page report-page"><h2>Закономерности ремонтов</h2>
    <ReportFilters context={context} user={user} /><ReportStatus context={context} report={report} />
    <p className="muted">Сигналы требуют проверки причины. Связь с исполнителем или сменой сама по себе не доказывает причину.</p>
    {data && <><ReportPeriodDetails period={data.period} />{data.items.length === 0 && <p>Закономерностей по доступным данным за выбранный период не найдено.</p>}
      {data.items.map(item => <article className="action-form" key={item.id}><h3>{item.title}</h3><p>Оборудование: {context.catalogs.data?.equipment.find(equipment => equipment.id === item.equipment_id)?.name ?? item.equipment_id}</p><p className="full-description">{item.description}</p>
        <dl className="order-info">{Object.entries(item.metrics).map(([key, value]) => <Fragment key={key}><dt>{metricNames[key] ?? key.replaceAll('_', ' ')}</dt><dd>{number(value)}</dd></Fragment>)}</dl>
        <p>Наряды, подтверждающие сигнал:</p><ul>{item.evidence_order_ids.map(id => <li key={id}><Link to={`/orders/${encodeURIComponent(id)}`}>Наряд {id}</Link></li>)}</ul><Limitations items={item.limitations} />
      </article>)}<Limitations items={data.limitations} /></>}
  </section>;
}
