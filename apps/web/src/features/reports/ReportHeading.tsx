import { Link } from 'react-router';
import type { UserView } from '../../lib/api';
import { Icon } from '../../components/Icon';

export function ReportHeading({ user, title, description }: { user: UserView; title: string; description: string }) {
  return <div className="page-heading report-heading"><div><h2>{title}</h2><p className="muted">{description}</p></div>{user.role === 'master' && <Link className="button primary" to="/orders/new" aria-label="Создать наряд"><Icon name="plus" /><span className="report-create-label">Создать наряд</span></Link>}</div>;
}
