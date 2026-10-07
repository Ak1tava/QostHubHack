import { Link } from 'react-router';
import type { UserView } from '../../lib/api';
import { localDateTime } from '../../lib/time';
import type { ShiftReport, useReportContext } from './data';

type Context = ReturnType<typeof useReportContext>;

export function ReportFilters({ context, user, allowShift = false }: { context: Context; user: UserView; allowShift?: boolean }) {
  const { params, catalogs, shift, timezone, start, end, shiftId, shifts, filter, areaId } = context;
  function destination(path: string) {
    const next = new URLSearchParams(params);
    if (path !== '/reports/shift') next.delete('shift_id');
    if (user.role === 'worker') { next.delete('assignee_id'); next.delete('brigade_id'); }
    return next.size ? `${path}?${next}` : path;
  }
  return <>
    <nav className="choices" aria-label="Отчёты"><Link className="button" to={destination('/reports/shift')}>Отчёт</Link><Link className="button" to={destination('/reports/rating')}>Рейтинг</Link>{user.role !== 'worker' && <Link className="button" to={destination('/analytics/anomalies')}>Закономерности</Link>}</nav>
    {user.role === 'worker' && <p className="muted">Показаны только ваши работы и оценки.</p>}
    {timezone && <p className="muted">Часовой пояс предприятия: {timezone}. По умолчанию — последние три календарных месяца.</p>}
    {catalogs.error && <p role="alert">{catalogs.error.message} <button onClick={catalogs.reload}>Обновить справочники</button></p>}
    {shift.error && <p role="alert">{shift.error.message} <button onClick={shift.reload}>Обновить параметры периода</button></p>}
    <fieldset className="form-fields filters" disabled={!timezone}>
      {allowShift && <label>Период или смена<select name="shift_id" value={shiftId} onChange={event => filter('shift_id', event.target.value)}>
        <option value="">Период по датам</option>{shifts.map((id, index) => <option key={id} value={id}>Смена из текущего состава {index + 1}</option>)}
      </select></label>}
      <label>Начало периода<input name="start" type="datetime-local" value={start} disabled={Boolean(shiftId)} onChange={event => filter('start', event.target.value)} /></label>
      <label>Окончание периода<input name="end" type="datetime-local" value={end} disabled={Boolean(shiftId)} onChange={event => filter('end', event.target.value)} /></label>
      <label>Участок<select name="area_id" value={areaId} onChange={event => filter('area_id', event.target.value)}><option value="">Все разрешённые участки</option>{catalogs.data?.areas.map(area => <option key={area.id} value={area.id}>{area.name}</option>)}</select></label>
      <label>Оборудование<select name="equipment_id" value={params.get('equipment_id') ?? ''} onChange={event => filter('equipment_id', event.target.value)}><option value="">Всё оборудование</option>{catalogs.data?.equipment.filter(item => !areaId || item.area_id === areaId).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      {user.role !== 'worker' && <>
        <label>Исполнитель<select name="assignee_id" value={params.get('assignee_id') ?? ''} onChange={event => filter('assignee_id', event.target.value)}><option value="">Все исполнители</option>{shift.data?.items.filter(member => member.user.role === 'worker').map(member => <option key={member.user.id} value={member.user.id}>{member.user.display_name}</option>)}</select></label>
        <label>Бригада<select name="brigade_id" value={params.get('brigade_id') ?? ''} onChange={event => filter('brigade_id', event.target.value)}><option value="">Все бригады</option>{catalogs.data?.brigades.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      </>}
    </fieldset>
    {context.validationError && <p role="alert">{context.validationError}</p>}
  </>;
}

export function ReportStatus({ context, report }: { context: Context; report: { loading: boolean; error: Error | null; reload: () => void } }) {
  return <>{(context.shift.loading || report.loading) && <p role="status">Загружаем отчёт…</p>}{report.error && <p role="alert">{report.error.message} <button onClick={report.reload}>Повторить запрос</button></p>}</>;
}

export function ReportPeriodDetails({ period }: { period: ShiftReport['period'] }) {
  return <p className="muted">Период: <time dateTime={period.start_at}>{localDateTime(period.start_at, period.timezone).replace('T', ' ')}</time> — <time dateTime={period.end_at}>{localDateTime(period.end_at, period.timezone).replace('T', ' ')}</time> ({period.timezone}). Данные на <time dateTime={period.as_of}>{localDateTime(period.as_of, period.timezone).replace('T', ' ')}</time>.</p>;
}

export function Limitations({ items }: { items: string[] }) {
  return items.length > 0 ? <aside className="notice"><h3>Ограничения данных</h3><ul>{items.map((item, index) => <li key={`${index}:${item}`}>{item}</li>)}</ul></aside> : null;
}
