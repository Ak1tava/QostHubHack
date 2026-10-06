import { useCallback } from 'react';
import type { components } from '../../../../../packages/contracts/api.generated';
import { ApiClient } from '../../lib/api';
import { useQuery } from '../../lib/useQuery';

export type WorkOrder = components['schemas']['WorkOrderView'];
export type WorkOrderDetail = components['schemas']['WorkOrderDetail'];
export type WorkOrderList = components['schemas']['WorkOrderList'];
export type CreateOrder = components['schemas']['WorkOrderCreate'];
export type OrderAction = components['schemas']['ActionCommand'];
export type Shift = components['schemas']['ShiftResponse'];
export type ShiftMember = components['schemas']['ShiftMemberView'];
export type Equipment = components['schemas']['EquipmentView'];
export type Named = components['schemas']['NamedView'];
export type Material = components['schemas']['MaterialView'];
export type WorkCode = components['schemas']['WorkCodeView'];
export type SubmissionCreate = components['schemas']['SubmissionCreate'];
export type Submission = components['schemas']['SubmissionView'];
export type Photo = components['schemas']['PhotoView'];
type Catalog = components['schemas']['CatalogResponse'];
type Kinds = { areas: Named; equipment: Equipment; brigades: Named; materials: Material; 'work-codes': WorkCode };

export const statuses: Record<WorkOrder['status'], string> = {
  ISSUED: 'Выданы', ACCEPTED: 'Приняты', QUEUED: 'Очередь', REJECTED: 'Отказ', IN_PROGRESS: 'В работе', PAUSED: 'Пауза',
  SUBMITTED: 'На приёмке', AI_REVIEW: 'Проверка', REWORK: 'Доработка', CLOSED: 'Закрыты', CANCELLED: 'Отменены',
};
export const priorities: Record<WorkOrder['priority'], string> = { emergency: 'Аварийный', high: 'Высокий', normal: 'Обычный', planned: 'Плановый' };
export const availability: Record<ShiftMember['availability'], string> = { free: 'Свободен', busy: 'Занят', queued: 'В очереди', off_shift: 'Вне смены' };

async function catalog<K extends keyof Kinds>(api: ApiClient, kind: K, signal: AbortSignal): Promise<Kinds[K][]> {
  const all: Kinds[K][] = [];
  let offset = 0;
  while (true) {
    const page = await api.request<Catalog>('/api/v1/catalog/{kind}', { params: { kind }, query: { offset, limit: 200 }, signal });
    all.push(...page.items as Kinds[K][]);
    offset += page.items.length;
    if (offset >= page.total || !page.items.length) return all;
  }
}

export function useCatalogs(api: ApiClient) {
  return useQuery(useCallback(async (signal: AbortSignal) => {
    const [areas, equipment, brigades] = await Promise.all([catalog(api, 'areas', signal), catalog(api, 'equipment', signal), catalog(api, 'brigades', signal)]);
    return { areas, equipment, brigades };
  }, [api]), 'refresh');
}

export function useShift(api: ApiClient, areaId = '') {
  return useQuery(useCallback((signal: AbortSignal) => api.request<Shift>('/api/v1/shift', { query: { area_id: areaId || undefined }, signal }), [api, areaId]));
}

export function useExecutionCatalogs(api: ApiClient) {
  return useQuery(useCallback(async (signal: AbortSignal) => {
    const [materials, codes] = await Promise.all([catalog(api, 'materials', signal), catalog(api, 'work-codes', signal)]);
    return { materials, codes };
  }, [api]), 'refresh');
}

export function submitOrder(api: ApiClient, id: string, body: SubmissionCreate, key: string) {
  return api.request<Submission>('/api/v1/work-orders/{order_id}/submissions', { params: { order_id: id }, method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify(body) });
}

export function uploadPhoto(api: ApiClient, id: string, file: File, type: 'before' | 'after') {
  const body = new FormData(); body.append('file', file); body.append('type', type);
  return api.request<Photo>('/api/v1/work-orders/{order_id}/photos', { params: { order_id: id }, method: 'POST', body });
}

export function createOrder(api: ApiClient, body: CreateOrder, key: string) {
  return api.request<WorkOrder>('/api/v1/work-orders', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify(body) });
}

export function orderAction(api: ApiClient, id: string, body: OrderAction, key: string) {
  return api.request<WorkOrder>('/api/v1/work-orders/{order_id}/actions', { params: { order_id: id }, method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify(body) });
}
