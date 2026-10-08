import { displayFixtureName, displayOrderNumber, displayOrderDescription } from '../../lib/displayFixture';
import { useLocale } from '../../ui/locale';
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router';
import type { components } from '../../../../../packages/contracts/api.generated';
import { ApiClient, type UserView } from '../../lib/api';
import { useQuery } from '../../lib/useQuery';
import { displayTime } from '../../lib/time';
import { statuses } from '../work-orders/data';
import { equipmentQr } from './qr';
import './equipment.css';

type EquipmentDetail = components['schemas']['EquipmentDetail'];

function EquipmentQr({ card }: { card: EquipmentDetail }) {
  const { tx } = useLocale();
  const [images, setImages] = useState<{ qr: string; label: string } | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    setImages(null); setError('');
    if (card.public_url) void equipmentQr(card.public_url, card.name, card.id).then(result => {
      if (active) setImages(result);
    }).catch(() => { if (active) setError(tx("Не удалось подготовить QR. Обновите страницу.")); });
    return () => { active = false; };
  }, [card.public_url, card.name, card.id]);
  if (!card.public_url) return <p className="muted">{tx("QR доступен на HTTPS-стенде.")}</p>;
  return <section className="equipment-qr" aria-label={tx("QR оборудования")}>
    <div className="equipment-label"><h3>{displayFixtureName(card.name)}</h3><p className="equipment-id">{card.id}</p>
      {images && <img src={images.qr} width="256" height="256" alt={`QR: ${displayFixtureName(card.name)}`} />}
      <p className="equipment-url"><a href={card.public_url}>{card.public_url}</a></p>
    </div>
    <p>{tx("Откройте QR обычной камерой телефона. Для просмотра нужен вход.")}</p>
    {error && <p role="alert">{error}</p>}
    {!images && !error && <p role="status">{tx("Подготавливаем QR…")}</p>}
    {images && <div className="choices">
      <a className="button" href={images.qr} download={`equipment-${card.id}-qr.svg`}>{tx("Скачать QR")}</a>
      <a className="button" href={images.label} download={`equipment-${card.id}-label.svg`}>{tx("Скачать наклейку")}</a>
      <button onClick={() => window.print()}>{tx("Печатать наклейку")}</button>
    </div>}
  </section>;
}

export function EquipmentPage({ api, user, equipmentId }: { api: ApiClient; user: UserView; equipmentId: string }) {
  const { tx, errorText } = useLocale();
  const detail = useQuery(useCallback((signal: AbortSignal) => api.request<EquipmentDetail>('/api/v1/equipment/{equipment_id}', { params: { equipment_id: equipmentId }, signal }), [api, equipmentId]));
  const card = detail.data;
  return <section className="page equipment-page">
    <Link to={user.role === 'worker' ? '/my-orders' : '/shift'}>{tx("← К нарядам")}</Link>
    {detail.loading && <p role="status">{tx("Загружаем оборудование…")}</p>}
    {detail.error && <p role="alert">{errorText(detail.error)} <button onClick={detail.reload}>{tx("Обновить")}</button></p>}
    {card && <>
      <div className="page-heading"><div><p className="muted">{tx("Оборудование")}</p><h2>{displayFixtureName(card.name)}</h2><p>{displayFixtureName(card.area.name)}</p></div>
        {user.role === 'master' && <Link className="button primary" to={`/orders/new?equipment_id=${card.id}&area_id=${card.area_id}`}>{tx("Создать наряд")}</Link>}
      </div>
      <div className="equipment-layout"><EquipmentQr card={card} />
        <section className="equipment-history" aria-labelledby="equipment-history-title"><h3 id="equipment-history-title">{tx("Последние 10 нарядов")}</h3>
          {card.recent_work_orders.length === 0 ? <p className="muted">{tx("Доступных нарядов пока нет.")}</p> : <ol className="equipment-orders">{card.recent_work_orders.map(order => <li key={order.id}>
            <Link to={order.detail_url}><strong>{displayOrderNumber(order.number)}</strong><span className="badge">{tx(statuses[order.status])}</span><p>{displayOrderDescription(order.description)}</p><time dateTime={order.created_at}>{displayTime(order.created_at, card.timezone)}</time></Link>
          </li>)}</ol>}
        </section>
      </div>
    </>}
  </section>;
}
