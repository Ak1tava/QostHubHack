import { useLocale } from '../../ui/locale';
import { Link, useLocation } from 'react-router';
import type { UserView } from '../../lib/api';
import { displayTime, localDateTime, utcDateTime } from '../../lib/time';
import { defaultPeriod, type ShiftReport, type useReportContext } from './data';
import { Icon } from '../../components/Icon';

type Context = ReturnType<typeof useReportContext>;

export function ReportFilters({ context, user, allowShift = false, period }: { context: Context; user: UserView; allowShift?: boolean; period?: ShiftReport['period'] }) {
  const { tx, errorText } = useLocale();
  const { params, catalogs, shift, timezone, start, end, shiftId, shifts, filter, areaId } = context;
  const { pathname } = useLocation();
  function destination(path: string) {
    const next = new URLSearchParams(params);
    if (path !== '/reports/shift') {
      next.delete('shift_id');
      if (shiftId && period) {
        next.delete('start'); next.delete('end');
        next.set('start_at', period.start_at); next.set('end_at', period.end_at);
      }
    }
    if (!shiftId && context.query?.start_at && context.query.end_at) {
      if (!next.has('start') && !next.has('start_at')) next.set('start_at', context.query.start_at);
      if (!next.has('end') && !next.has('end_at')) next.set('end_at', context.query.end_at);
    }
    if (user.role === 'worker') { next.delete('assignee_id'); next.delete('brigade_id'); }
    return next.size ? `${path}?${next}` : path;
  }
  const selected = shiftId ? period : context.query?.start_at && context.query.end_at ? { start_at: context.query.start_at, end_at: context.query.end_at } : null;
  const tabs = [{ path: '/reports/shift', label: tx("Обзор") }, { path: '/reports/rating', label: tx("Рейтинг") }, ...(user.role === 'worker' ? [] : [{ path: '/analytics/anomalies', label: tx("Закономерности") }])];
  return <>
    <nav className="report-tabs" aria-label={tx("Отчёты")}>{tabs.map(tab => {
      const disabled = Boolean(shiftId && !period && tab.path !== '/reports/shift');
      return <Link key={tab.path} to={destination(tab.path)} aria-current={pathname === tab.path ? 'page' : undefined} aria-disabled={disabled || undefined} onClick={event => { if (disabled) event.preventDefault(); }}>{tab.label}</Link>;
    })}</nav>
    {user.role === 'worker' && <p className="muted">{tx("Показаны только ваши работы и оценки.")}</p>}
    <div className="report-filters">
      <div className="period-heading"><p><Icon name="calendar" />{selected && timezone ? `${displayTime(selected.start_at, timezone)} — ${displayTime(selected.end_at, timezone)}` : tx("Выберите период или смену")}</p>
        <div className="period-presets" aria-label={tx("Быстрый выбор периода")}>{([7, 30, 90] as const).map(days => {
          const active = Boolean(!shiftId && selected && timezone && (days === 90
            ? Date.parse(selected.start_at) === Date.parse(utcDateTime(defaultPeriod(selected.end_at, timezone).start, timezone))
            : Date.parse(selected.end_at) - Date.parse(selected.start_at) === days * 86400000));
          return <button key={days} type="button" disabled={!timezone} aria-pressed={active} onClick={() => context.preset(days)}>{days === 90 ? tx("3 месяца") : ((days) + tx(" дней"))}</button>;
        })}</div>
      </div>
      {timezone && <p className="period-timezone">{tx("Часовой пояс предприятия: ")}{timezone}{tx(". Конец периода не включается.")}</p>}
    {catalogs.error && <p role="alert">{errorText(catalogs.error)} <button onClick={catalogs.reload}>{tx("Обновить справочники")}</button></p>}
    {shift.error && <p role="alert">{errorText(shift.error)} <button onClick={shift.reload}>{tx("Обновить параметры периода")}</button></p>}
    <details className="filter-details"><summary>{tx("Настроить период и фильтры")}{areaId || params.get('equipment_id') || params.get('assignee_id') || params.get('brigade_id') || shiftId ? tx(" · выбраны фильтры") : ''}</summary>
    <fieldset className="form-fields filters" disabled={!timezone}>
      {allowShift && <label>{tx("Период или смена")}<select name="shift_id" value={shiftId} onChange={event => filter('shift_id', event.target.value)}>
        <option value="">{tx("Период по датам")}</option>{shifts.map((id, index) => {
          const member = shift.data?.items.find(item => item.user.shift_id === id);
          return <option key={id} value={id}>{member?.start_at && member.end_at && timezone ? (tx("Смена: ") + (displayTime(member.start_at, timezone)) + " — " + (displayTime(member.end_at, timezone))) : (tx("Смена из текущего состава ") + (index + 1))}</option>;
        })}
      </select></label>}
      <label>{tx("Начало периода")}<input name="start" type="datetime-local" value={shiftId && period ? localDateTime(period.start_at, period.timezone) : start} disabled={Boolean(shiftId)} onChange={event => filter('start', event.target.value)} /></label>
      <label>{tx("Окончание периода")}<input name="end" type="datetime-local" value={shiftId && period ? localDateTime(period.end_at, period.timezone) : end} disabled={Boolean(shiftId)} onChange={event => filter('end', event.target.value)} /></label>
      <label>{tx("Участок")}<select name="area_id" value={areaId} onChange={event => filter('area_id', event.target.value)}><option value="">{tx("Все разрешённые участки")}</option>{catalogs.data?.areas.map(area => <option key={area.id} value={area.id}>{area.name}</option>)}</select></label>
      <label>{tx("Оборудование")}<select name="equipment_id" value={params.get('equipment_id') ?? ''} onChange={event => filter('equipment_id', event.target.value)}><option value="">{tx("Всё оборудование")}</option>{catalogs.data?.equipment.filter(item => !areaId || item.area_id === areaId).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      {user.role !== 'worker' && <>
        <label>{tx("Исполнитель")}<select name="assignee_id" value={params.get('assignee_id') ?? ''} onChange={event => filter('assignee_id', event.target.value)}><option value="">{tx("Все исполнители")}</option>{shift.data?.items.filter(member => member.user.role === 'worker').map(member => <option key={member.user.id} value={member.user.id}>{member.user.display_name}</option>)}</select></label>
        <label>{tx("Бригада")}<select name="brigade_id" value={params.get('brigade_id') ?? ''} onChange={event => filter('brigade_id', event.target.value)}><option value="">{tx("Все бригады")}</option>{catalogs.data?.brigades.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      </>}
    </fieldset>
    </details></div>
    {context.validationError && <p role="alert">{errorText(context.validationError)}</p>}
  </>;
}

export function ReportStatus({ context, report }: { context: Context; report: { loading: boolean; error: Error | null; reload: () => void } }) {
  const { tx, errorText } = useLocale();
  return <>{(context.shift.loading || report.loading) && <p className="report-status" role="status">{tx("Загружаем отчёт…")}</p>}{report.error && <p className="report-status" role="alert">{errorText(report.error)} <button onClick={report.reload}>{tx("Повторить запрос")}</button></p>}</>;
}

export function ReportPeriodDetails({ period }: { period: ShiftReport['period'] }) {
  const { tx } = useLocale();
  return <p className="report-period muted">{tx("Период: ")}<time dateTime={period.start_at}>{localDateTime(period.start_at, period.timezone).replace('T', ' ')}</time> — <time dateTime={period.end_at}>{localDateTime(period.end_at, period.timezone).replace('T', ' ')}</time> ({period.timezone}{tx("). Данные на ")}<time dateTime={period.as_of}>{localDateTime(period.as_of, period.timezone).replace('T', ' ')}</time>.</p>;
}

export function Limitations({ items }: { items: string[] }) {
  const { tx } = useLocale();
  return items.length > 0 ? <aside className="notice"><h3>{tx("Ограничения данных")}</h3><ul>{items.map((item, index) => <li key={`${index}:${item}`}>{item}</li>)}</ul></aside> : null;
}
