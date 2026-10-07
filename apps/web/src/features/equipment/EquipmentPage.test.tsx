import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, expect, it } from 'vitest';
import { ApiClient, type UserView } from '../../lib/api';
import { EquipmentPage } from './EquipmentPage';

let root: Root, container: HTMLDivElement;
const id = '11111111-1111-4111-8111-111111111111';
const areaId = '22222222-2222-4222-8222-222222222222';
const user: UserView = { id: 'master', display_name: 'Мастер', role: 'master', specialty: null, grade: null, brigade_id: null, shift_id: null };
const card = { id, name: 'Насос <script>alert(1)</script>', area_id: areaId, area: {id: areaId, name: 'Участок'}, timezone: 'Asia/Qostanay', public_url: `https://plant.example/equipment/${id}`, recent_work_orders: [{id: 'order', number: 'N-001', description: 'Замена уплотнения', status:'CLOSED', created_at:'2026-10-08T00:00:00Z', detail_url:'/orders/order'}] };
beforeEach(() => {
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.append(container); root=createRoot(container);
});
afterEach(async () => {await act(async () => root.unmount()); container.remove();});
async function render(body: unknown=card, role: UserView['role']='master', status=200) {
  const api=new ApiClient(async()=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}}));
  await act(async()=>root.render(<MemoryRouter><EquipmentPage api={api} user={{...user,role}} equipmentId={id}/></MemoryRouter>));
}
it('shows existing data and authorized history, provides downloadable QR and a safely escaped label', async()=>{
  await render();
  expect(container.textContent).toContain(card.name);
  expect(container.textContent).toContain('Замена уплотнения');
  expect(container.querySelector('a[href="/orders/order"]')).not.toBeNull();
  expect([...container.querySelectorAll('a')].map(a => a.getAttribute('href'))).toContain(`/orders/new?equipment_id=${id}&area_id=${areaId}`);
  expect(container.querySelector('img')?.getAttribute('src')).toContain('data:image/svg+xml');
  const downloads=[...container.querySelectorAll<HTMLAnchorElement>('a[download]')];
  expect(downloads).toHaveLength(2);
  const label=decodeURIComponent(downloads[1].href.split(',')[1]);
  expect(label).toContain('&lt;script&gt;');
  expect(label).not.toContain('<script>');
  expect(label).toContain(id);
});
it('does not offer creation to a worker and explains an empty history',async()=>{
  await render({...card,recent_work_orders:[]},'worker');
  expect(container.textContent).not.toContain('Создать наряд');
  expect(container.textContent).toContain('Доступных нарядов пока нет');
});
it('does not print HTTP dev links as QR',async()=>{
  await render({...card,public_url:null});
  expect(container.querySelector('a[download]')).toBeNull();
  expect(container.textContent).toContain('QR доступен на HTTPS-стенде');
});
it('does not reveal equipment on a server access denial',async()=>{
  await render({error:{code:'not_found',message:'Оборудование не найдено',details:[]}},'worker',404);
  expect(container.textContent).toContain('Оборудование не найдено');
  expect(container.textContent).not.toContain(card.name);
  expect(container.querySelector('a[download]')).toBeNull();
});
