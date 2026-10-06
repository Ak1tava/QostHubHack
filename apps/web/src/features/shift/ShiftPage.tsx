import { Link, useSearchParams } from 'react-router';
import { ApiClient, type UserView } from '../../lib/api';
import { useCatalogs, useShift } from '../work-orders/data';
import { OrderBoard } from '../work-orders/OrderBoard';
import { WorkerList } from './WorkerList';

export function ShiftPage({ api, user }: { api: ApiClient; user: UserView }) {
  const [query, setQuery] = useSearchParams();
  const areaId = query.get('area_id') ?? '';
  const catalogs = useCatalogs(api);
  const shift = useShift(api, areaId);
  function filter(name: string, value: string) {
    const next = new URLSearchParams(query);
    if (value) next.set(name, value); else next.delete(name);
    next.delete('offset');
    if (name === 'area_id') { next.delete('equipment_id'); next.delete('assignee_id'); }
    setQuery(next, { replace: true });
  }
  return <section className="page">
    <div className="page-heading"><h2>Панель смены</h2>{user.role === 'master' && <Link className="button primary" to={areaId ? `/orders/new?area_id=${encodeURIComponent(areaId)}` : '/orders/new'}>Новый наряд</Link>}</div>
    {catalogs.error && <p role="alert">{catalogs.error.message} <button onClick={catalogs.reload}>Обновить справочники</button></p>}
    {shift.error && <p role="alert">{shift.error.message} <button onClick={shift.reload}>Обновить смену</button></p>}
    <label className="area-filter">Участок<select value={areaId} onChange={event => filter('area_id', event.target.value)}>
      <option value="">Все разрешённые участки</option>{catalogs.data?.areas.map(area => <option key={area.id} value={area.id}>{area.name}</option>)}
    </select></label>
    {shift.loading && <p role="status">Загружаем смену…</p>}
    {shift.data && <WorkerList members={shift.data.items} areaId={areaId} canCreate={user.role === 'master'} />}
    {catalogs.data && <OrderBoard api={api} catalogs={catalogs.data} members={shift.data?.items ?? []} timezone={shift.data?.timezone ?? 'Asia/Qostanay'} query={query} filter={filter} setQuery={next => setQuery(next, { replace: true })} />}
  </section>;
}
