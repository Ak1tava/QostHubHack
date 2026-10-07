import { Link, useLocation } from 'react-router';
import type { UserView } from '../lib/api';
import { Icon } from './Icon';

export const roleNames: Record<UserView['role'], string> = { master: 'Мастер', worker: 'Исполнитель', manager: 'Руководитель', admin: 'Администратор' };

export function Brand() {
  return <Link className="app-brand" to="/" aria-label="НарядAI — главная"><span className="brand-mark"><Icon name="tool" /></span><div><h1>НарядAI</h1><small>Ремонтные работы</small></div></Link>;
}

export function AppNavigation({ user }: { user: UserView }) {
  const { pathname, search } = useLocation();
  const reports = pathname.startsWith('/reports/') || pathname === '/analytics/anomalies';
  const links = [
    { to: user.role === 'worker' ? '/my-orders' : '/shift', label: user.role === 'worker' ? 'Мои наряды' : 'Панель смены', icon: 'shift', active: pathname === '/shift' || pathname === '/my-orders' || pathname.startsWith('/orders/') },
    { to: reports ? `${pathname}${search}` : '/reports/shift', label: user.role === 'worker' ? 'Мои показатели' : 'Отчёты', icon: 'report', active: reports },
    { to: '/telegram', label: 'Telegram', icon: 'telegram', active: pathname === '/telegram' },
  ] as const;
  return <aside className="app-sidebar"><Brand /><p className="nav-caption">Рабочее пространство</p>
    <nav className="app-nav" aria-label="Разделы приложения">{links.map(link => <Link key={link.icon} to={link.to} aria-current={link.active ? 'page' : undefined}><Icon name={link.icon} /><span>{link.label}</span></Link>)}</nav>
    <div className="sidebar-role"><span>Ваша роль</span><strong>{roleNames[user.role]}</strong></div>
  </aside>;
}
