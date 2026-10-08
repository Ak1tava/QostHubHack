import { displayFixtureName } from '../../lib/displayFixture';
import { useLocale } from '../../ui/locale';
import { Link, useSearchParams } from 'react-router';
import { ApiClient, type UserView } from '../../lib/api';
import { useCatalogs, useShift } from '../work-orders/data';
import { OrderBoard } from '../work-orders/OrderBoard';
import { WorkerList } from './WorkerList';
import { StatusBadge } from '../../ui/components';

const exampleWorkers = [
  { initial: 'А.', score: 4.9, completed: 28, busy: true },
  { initial: 'Б.', score: 4.8, completed: 25, busy: true },
  { initial: 'В.', score: 4.6, completed: 22, busy: true },
  { initial: 'Г.', score: 4.5, completed: 19, busy: true },
  { initial: 'Д.', score: 4.2, completed: 16, busy: false },
];

function JudgeBrigadeExample() {
  const { locale } = useLocale();
  const kk = locale === 'kk';
  const label = kk ? 'Бригада мысалы' : 'Пример бригады';
  return <section className="action-form" aria-label={label}>
    <span className="badge">{label}</span>
    <h3>{kk ? 'Жөндеушілер рейтингі' : 'Рейтинг слесарей'}</h3>
    <p className="muted">{kk ? '4 жұмысшы бос емес · 1 жұмысшы бос' : '4 рабочих заняты · 1 свободен'}</p>
    <div className="worker-grid">{exampleWorkers.map((worker, index) => <article className="worker-card" key={worker.initial}>
      <strong>{index + 1}. {kk ? 'Жөндеуші' : 'Слесарь'} {worker.initial}</strong>
      <StatusBadge domain="availability" status={worker.busy ? 'busy' : 'free'} />
      <span>{kk ? 'Баға' : 'Оценка'}: {worker.score.toLocaleString(kk ? 'kk-KZ' : 'ru-RU')} / 5</span>
      <span>{kk ? 'Орындалған нарядтар' : 'Выполнено нарядов'}: {worker.completed}</span>
    </article>)}</div>
  </section>;
}

export function ShiftPage({ api, user, judgeMode = false }: { api: ApiClient; user: UserView; judgeMode?: boolean }) {
  const { tx, errorText } = useLocale();
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
    <div className="page-heading"><h2>{tx("Панель смены")}</h2>{user.role === 'master' && <Link className="button primary" to={areaId ? `/orders/new?area_id=${encodeURIComponent(areaId)}` : '/orders/new'}>{tx("Новый наряд")}</Link>}</div>
    {judgeMode && user.role === 'master' && <JudgeBrigadeExample />}
    {catalogs.error && <p role="alert">{errorText(catalogs.error)} <button onClick={catalogs.reload}>{tx("Обновить справочники")}</button></p>}
    {shift.error && <p role="alert">{errorText(shift.error)} <button onClick={shift.reload}>{tx("Обновить смену")}</button></p>}
    <label className="area-filter">{tx("Участок")}<select value={areaId} onChange={event => filter('area_id', event.target.value)}>
      <option value="">{tx("Все разрешённые участки")}</option>{catalogs.data?.areas.map(area => <option key={area.id} value={area.id}>{displayFixtureName(area.name)}</option>)}
    </select></label>
    {shift.loading && <p role="status">{tx("Загружаем смену…")}</p>}
    {shift.data && <WorkerList members={shift.data.items} areaId={areaId} canCreate={user.role === 'master'} />}
    {catalogs.data && <OrderBoard api={api} catalogs={catalogs.data} members={shift.data?.items ?? []} timezone={shift.data?.timezone ?? 'Asia/Qostanay'} query={query} filter={filter} setQuery={next => setQuery(next, { replace: true })} />}
  </section>;
}
