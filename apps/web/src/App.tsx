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
import type { UserView } from './lib/api';

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
  return <main>
    <header className="app-header"><div><h1>НарядAI</h1><p>Система ремонтных нарядов</p></div>{user && <div className="account"><span>{user.display_name}</span><button onClick={() => void authStore.logout()} disabled={busy}>{busy ? 'Выходим…' : 'Выйти'}</button></div>}</header>
    {error && user && <p role="alert">{error.message}</p>}
    {loading ? <p role="status">Проверяем вход…</p> : user ? <Routes>
      <Route path="/" element={user.role === 'master' ? <Navigate to="/shift" replace /> : <section className="auth-card"><h2>Вы вошли</h2><p>{user.display_name}</p>{user.role === 'worker' ? <Link className="button primary" to="/my-orders">Мои наряды</Link> : <Link to="/shift">Панель смены</Link>}</section>} />
      <Route path="/my-orders" element={<MyOrdersPage key={user.id} api={authStore.api} user={user} />} />
      <Route path="/shift" element={user.role !== 'worker' ? <ShiftPage api={authStore.api} user={user} /> : <p role="alert">Панель доступна мастеру.</p>} />
      <Route path="/orders/new" element={<CreateOrderPage api={authStore.api} user={user} />} />
      <Route path="/orders/:id" element={<OrderRoute user={user} />} />
      <Route path="/orders/:id/execute" element={<ExecutionRoute user={user} />} />
      <Route path="*" element={<p>Страница не найдена. <Link to="/">На главную</Link></p>} />
    </Routes> : <LoginPage busy={busy} error={error} onLogin={payload => authStore.login(payload)} />}
    <PwaUpdatePrompt />
  </main>;
}
