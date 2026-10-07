import { useEffect, useSyncExternalStore } from 'react';
import { Link, Navigate, Route, Routes, useParams } from 'react-router';
import { authStore } from './features/auth/session';
import { LoginPage } from './features/auth/LoginPage';
import { PwaUpdatePrompt } from './PwaUpdatePrompt';
import { events } from './lib/events';
import { ShiftPage } from './features/shift/ShiftPage';
import { CreateOrderPage } from './features/work-orders/CreateOrderPage';
import { OrderDetailsPage } from './features/work-orders/OrderDetailsPage';
import { ExecutionPage } from './features/work-orders/ExecutionPage';
import { MyOrdersPage } from './features/work-orders/MyOrdersPage';
import { ShiftReportPage } from './features/reports/ShiftReportPage';
import { RatingPage } from './features/reports/RatingPage';
import { AnomaliesPage } from './features/reports/AnomaliesPage';
import { TelegramPage } from './features/telegram/TelegramPage';
import type { UserView } from './lib/api';
import { AppNavigation, Brand, roleNames } from './components/AppNavigation';

function OrderRoute({ user }: { user: UserView }) {
  const { id } = useParams();
  if (user.role === 'worker') return <ExecutionPage key={`${user.id}:${id}`} api={authStore.api} user={user} orderId={id!} />;
  return <OrderDetailsPage key={`${user.id}:${id}`} api={authStore.api} user={user} orderId={id!} />;
}

function ExecutionRoute({ user }: { user: UserView }) {
  const { id } = useParams();
  return user.role === 'worker' ? <ExecutionPage key={`${user.id}:${id}`} api={authStore.api} user={user} orderId={id!} /> : <Navigate to={`/orders/${id}`} replace />;
}

export function App() {
  const { user, loading, busy, error } = useSyncExternalStore(authStore.subscribe, authStore.getSnapshot);
  useEffect(() => { void authStore.restore(); }, []);
  useEffect(() => {
    if (!user) return;
    events.start(() => { void authStore.restore(); });
    return () => events.stop();
  }, [user?.id]);
  return <div className={user ? 'app-shell' : 'login-shell'}>
    <a className="skip-link" href="#content">Перейти к содержимому</a>
    {user && <AppNavigation user={user} />}
    <div className="app-body"><header className="app-header"><div className="header-brand"><Brand /></div><span className="header-caption">Рабочее пространство</span>{user && <div className="account"><div className="account-person"><strong>{user.display_name}</strong><small>{roleNames[user.role]}</small></div><button onClick={() => void authStore.logout()} disabled={busy}>{busy ? 'Выходим…' : 'Выйти'}</button></div>}</header>
    <main className="app-content" id="content">
    {error && user && <p role="alert">{error.message}</p>}
    {loading ? <p role="status">Проверяем вход…</p> : user ? <Routes>
      <Route path="/" element={<Navigate to={user.role === 'worker' ? '/my-orders' : '/shift'} replace />} />
      <Route path="/my-orders" element={<MyOrdersPage key={user.id} api={authStore.api} user={user} />} />
      <Route path="/shift" element={user.role !== 'worker' ? <ShiftPage api={authStore.api} user={user} /> : <p role="alert">Панель доступна мастеру.</p>} />
      <Route path="/orders/new" element={<CreateOrderPage api={authStore.api} user={user} />} />
      <Route path="/orders/:id" element={<OrderRoute user={user} />} />
      <Route path="/orders/:id/execute" element={<ExecutionRoute user={user} />} />
      <Route path="/reports/shift" element={<ShiftReportPage key={user.id} api={authStore.api} user={user} />} />
      <Route path="/reports/rating" element={<RatingPage key={user.id} api={authStore.api} user={user} />} />
      <Route path="/analytics/anomalies" element={<AnomaliesPage key={user.id} api={authStore.api} user={user} />} />
      <Route path="/telegram" element={<TelegramPage key={user.id} api={authStore.api} />} />
      <Route path="*" element={<p>Страница не найдена. <Link to="/">На главную</Link></p>} />
    </Routes> : <LoginPage busy={busy} error={error} onLogin={payload => authStore.login(payload)} />}
    </main><PwaUpdatePrompt /></div>
  </div>;
}
