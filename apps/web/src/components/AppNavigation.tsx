import { useLocale } from '../ui/locale';
import { Link, useLocation } from 'react-router';
import type { UserView } from '../lib/api';
import { Icon } from './Icon';

export const roleNames: Record<UserView['role'], string> = { master: 'Мастер', worker: 'Исполнитель', manager: 'Руководитель', admin: 'Администратор' };

export function Brand() {
  const { tx } = useLocale();
  return <Link className="app-brand" to="/" aria-label={tx("НарядAI — главная")}><span className="brand-mark"><Icon name="tool" /></span><div><h1>{tx("НарядAI")}</h1><small>{tx("Ремонтные работы")}</small></div></Link>;
}

export function AppNavigation({ user }: { user: UserView }) {
  const { tx } = useLocale();
  const { pathname, search } = useLocation();
  const reports = pathname.startsWith('/reports/') || pathname === '/analytics/anomalies';
  const links = [
    { to: user.role === 'worker' ? '/my-orders' : '/shift', label: user.role === 'worker' ? tx("Мои наряды") : tx("Панель смены"), icon: 'shift', active: pathname === '/shift' || pathname === '/my-orders' || pathname.startsWith('/orders/') },
    { to: reports ? `${pathname}${search}` : '/reports/shift', label: user.role === 'worker' ? tx("Мои показатели") : tx("Отчёты"), icon: 'report', active: reports },
    { to: '/telegram', label: 'Telegram', icon: 'telegram', active: pathname === '/telegram' },
  ] as const;
  return <aside className="app-sidebar"><Brand /><p className="nav-caption">{tx("Рабочее пространство")}</p>
    <nav className="app-nav" aria-label={tx("Разделы приложения")}>{links.map(link => <Link key={link.icon} to={link.to} aria-current={link.active ? 'page' : undefined}><Icon name={link.icon} /><span>{link.label}</span></Link>)}</nav>
    <div className="sidebar-role"><span>{tx("Ваша роль")}</span><strong>{tx(roleNames[user.role])}</strong></div>
  </aside>;
}
