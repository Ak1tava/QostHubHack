import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { ApiClient, type UserView } from '../../lib/api';
import { useCommand } from '../../lib/useCommand';
import { localDateTime, utcDateTime } from '../../lib/time';
import { compressPhoto } from '../../lib/compressPhoto';
import { availability, createOrder, priorities, uploadPhoto, useCatalogs, useShift, type CreateOrder, type Photo, type WorkOrder } from './data';

export function CreateOrderPage({ api, user }: { api: ApiClient; user: UserView }) {
  const [query] = useSearchParams();
  const navigate = useNavigate();
  const catalogs = useCatalogs(api);
  const [areaId, setAreaId] = useState(query.get('area_id') ?? '');
  const [equipmentId, setEquipmentId] = useState('');
  const [assigneeId, setAssigneeId] = useState(query.get('assignee_id') ?? '');
  const [mode, setMode] = useState<'worker' | 'brigade'>('worker');
  const [brigadeId, setBrigadeId] = useState('');
  const [responsibleId, setResponsibleId] = useState('');
  const [description, setDescription] = useState('');
  const [workType, setWorkType] = useState<CreateOrder['work_type']>('planned');
  const [priority, setPriority] = useState<NonNullable<CreateOrder['priority']>>('normal');
  const [deadline, setDeadline] = useState('');
  const deadlineInitialized = useRef(false);
  const [validation, setValidation] = useState('');
  const [beforePhotos, setBeforePhotos] = useState<File[]>([]);
  const [uploadedPhotos, setUploadedPhotos] = useState<Photo[]>([]);
  const [createdOrder, setCreatedOrder] = useState<WorkOrder | null>(null);
  const createdRef = useRef<WorkOrder | null>(null);
  const uploadedCount = useRef(0);
  const photoRunning = useRef(false);
  const [photoBusy, setPhotoBusy] = useState(false);
  const baseShift = useShift(api);
  const shift = useShift(api, areaId);
  const timezone = baseShift.data?.timezone ?? shift.data?.timezone;
  const workers = shift.data?.items.filter(member => member.user.role === 'worker') ?? [];
  const eligible = workers.filter(member => member.user.brigade_id === brigadeId);
  const brigades = catalogs.data?.brigades.filter(brigade => workers.some(member => member.user.brigade_id === brigade.id)) ?? [];
  const selected = workers.find(member => member.user.id === (mode === 'worker' ? assigneeId : responsibleId));
  const command = useCommand(useCallback((body: CreateOrder, key: string) => createOrder(api, body, key), [api]));

  useEffect(() => {
    if (!areaId && catalogs.data?.areas.length === 1) setAreaId(catalogs.data.areas[0].id);
  }, [areaId, catalogs.data]);
  useEffect(() => {
    if (!baseShift.data || deadlineInitialized.current) return;
    const now = new Date(baseShift.data.as_of).getTime();
    const master = baseShift.data.items.find(member => member.user.id === user.id);
    const onShift = master?.start_at && master.end_at && Date.parse(master.start_at) <= now && Date.parse(master.end_at) > now;
    const initial = onShift ? master!.end_at! : new Date(now + 3_600_000).toISOString();
    deadlineInitialized.current = true;
    setDeadline(localDateTime(initial, baseShift.data.timezone));
  }, [baseShift.data, user.id]);
  useEffect(() => {
    if (!shift.data || command.pending || command.busy || createdRef.current) return;
    const available = shift.data.items.filter(member => member.user.role === 'worker');
    if (assigneeId && !available.some(member => member.user.id === assigneeId)) setAssigneeId('');
    if (responsibleId && !available.some(member => member.user.id === responsibleId && member.user.brigade_id === brigadeId)) setResponsibleId('');
    if (brigadeId && !available.some(member => member.user.brigade_id === brigadeId)) setBrigadeId('');
  }, [shift.data, assigneeId, responsibleId, brigadeId, command.pending, command.busy]);

  function changeArea(id: string) {
    setAreaId(id);
    if (!catalogs.data?.equipment.some(item => item.id === equipmentId && item.area_id === id)) setEquipmentId('');
  }

  const assigned = mode === 'worker' ? workers.some(member => member.user.id === assigneeId) : brigadeId && eligible.some(member => member.user.id === responsibleId);
  const valid = !!(user.role === 'master' && catalogs.data && timezone && areaId && equipmentId && description.trim() && deadline && assigned);
  async function preparePhotos(files: File[]) {
    if (!files.length || photoRunning.current || createdRef.current) return;
    if (beforePhotos.length + files.length > 5) { setValidation('При выдаче можно добавить не более пяти фото.'); return; }
    photoRunning.current = true; setPhotoBusy(true); setValidation('');
    try { const prepared = await Promise.all(files.map(compressPhoto)); setBeforePhotos(previous => [...previous, ...prepared]); }
    catch (error) { setValidation(error instanceof Error ? error.message : 'Не удалось подготовить фото.'); }
    finally { photoRunning.current = false; setPhotoBusy(false); }
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); setValidation('');
    if (photoRunning.current) return;
    photoRunning.current = true; setPhotoBusy(true);
    try {
      let body: CreateOrder | undefined;
      if (!createdRef.current && !command.pending) {
        if (!valid || !timezone) return;
        body = { work_type: workType, description: description.trim(), area_id: areaId, equipment_id: equipmentId, priority,
          due_at: utcDateTime(deadline, timezone), assignee_id: mode === 'worker' ? assigneeId : null,
          brigade_id: mode === 'brigade' ? brigadeId : null, responsible_id: mode === 'brigade' ? responsibleId : null };
      }
      const created = createdRef.current ?? await command.run(body);
      if (created) {
        createdRef.current = created; setCreatedOrder(created);
        for (let index = uploadedCount.current; index < beforePhotos.length; index++) {
          const photo = await uploadPhoto(api, created.id, beforePhotos[index], 'before',
            { expected_version: created.version, assignment_version: created.assignment_version });
          uploadedCount.current = index + 1;
          setUploadedPhotos(previous => previous.some(saved => saved.id === photo.id) ? previous : [...previous, photo]);
        }
        navigate(`/orders/${created.id}`, { replace: true });
      }
    } catch (error) { setValidation(error instanceof Error ? error.message : 'Проверьте поля'); }
    finally { photoRunning.current = false; setPhotoBusy(false); }
  }

  if (user.role !== 'master') return <p role="alert">Выдавать наряды может только мастер.</p>;
  return <section className="page form-page">
    <Link to={areaId ? `/shift?area_id=${encodeURIComponent(areaId)}` : '/shift'}>← Панель смены</Link>
    <h2>Новый наряд</h2>
    <p className="muted">Мастер: {user.display_name}</p>
    {[catalogs.error, shift.error, baseShift.error].filter(Boolean).map((error, index) => <p role="alert" key={index}>{error!.message} <button type="button" onClick={() => { catalogs.reload(); shift.reload(); baseShift.reload(); }}>Обновить</button></p>)}
    <form onSubmit={submit}>
      <fieldset disabled={command.busy || command.pending || photoBusy || !!createdOrder || !catalogs.data} className="form-fields">
        <fieldset className="choice-group"><legend>Участок</legend><div className="choices">
          {catalogs.data?.areas.map(area => <button type="button" key={area.id} aria-pressed={areaId === area.id} onClick={() => changeArea(area.id)}>{area.name}</button>)}
        </div></fieldset>
        <fieldset className="choice-group"><legend>Оборудование</legend><div className="choices equipment-choices">
          {catalogs.data?.equipment.filter(item => item.area_id === areaId).map(item => <button type="button" key={item.id} aria-pressed={equipmentId === item.id} onClick={() => setEquipmentId(item.id)}>{item.name}</button>)}
          {!areaId && <p className="muted">Сначала выберите участок.</p>}
        </div></fieldset>
        <fieldset className="choice-group"><legend>Назначение</legend><div className="choices">
          <button type="button" aria-pressed={mode === 'worker'} onClick={() => setMode('worker')}>Исполнитель</button>
          <button type="button" aria-pressed={mode === 'brigade'} onClick={() => { setMode('brigade'); setResponsibleId(''); }}>Бригада</button>
        </div></fieldset>
        {mode === 'worker' ? <label>Исполнитель<select name="assignee_id" value={assigneeId} onChange={event => setAssigneeId(event.target.value)} disabled={!areaId || !shift.data} required>
          <option value="">Выберите исполнителя</option>{workers.map(member => <option key={member.user.id} value={member.user.id}>{member.user.display_name} · {availability[member.availability]} · очередь {member.queue_count}</option>)}
        </select></label> : <>
          <label>Бригада<select name="brigade_id" value={brigadeId} onChange={event => { setBrigadeId(event.target.value); setResponsibleId(''); }} required>
            <option value="">Выберите бригаду</option>{brigades.map(brigade => <option key={brigade.id} value={brigade.id}>{brigade.name}</option>)}
          </select></label>
          <label>Ответственный<select name="responsible_id" value={responsibleId} onChange={event => setResponsibleId(event.target.value)} required>
            <option value="">Выберите ответственного</option>{eligible.map(member => <option key={member.user.id} value={member.user.id}>{member.user.display_name} · {availability[member.availability]}</option>)}
          </select></label>
        </>}
        {selected && <p role="status" className={`notice availability-${selected.availability}`}>{availability[selected.availability]} · в очереди: {selected.queue_count}{selected.availability !== 'free' ? '. Проверьте назначение и срок.' : ''}</p>}
        <label>Описание работ<textarea name="description" value={description} onChange={event => setDescription(event.target.value)} required maxLength={10000} rows={3} /></label>
        <div className="form-row">
          <label>Тип<select value={workType} onChange={event => { const type = event.target.value as CreateOrder['work_type']; setWorkType(type); if (type === 'emergency') setPriority('emergency'); else if (priority === 'emergency') setPriority('normal'); }}>
            <option value="planned">Плановый</option><option value="emergency">Аварийный</option>
          </select></label>
          <label>Приоритет<select value={priority} onChange={event => setPriority(event.target.value as typeof priority)}>{Object.entries(priorities).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        </div>
        {priority === 'emergency' && <p className="badge priority-emergency">Аварийный приоритет</p>}
        <label>Срок {timezone && <small>({timezone})</small>}<input type="datetime-local" value={deadline} onChange={event => setDeadline(event.target.value)} required /></label>
        <label>Фото при выдаче · до 5<input type="file" accept="image/*" multiple capture="environment" onChange={event => { const files = Array.from(event.target.files ?? []); event.target.value = ''; void preparePhotos(files); }} /></label>
        {beforePhotos.length > 0 && <ul>{beforePhotos.map((file, index) => <li key={index}>{file.name} · {Math.ceil(file.size / 1024)} КБ</li>)}</ul>}
      </fieldset>
      {createdOrder && <p role="status">Наряд уже выдан. Загружено фото: {uploadedCount.current} из {beforePhotos.length}. <Link to={`/orders/${createdOrder.id}`}>Открыть наряд</Link></p>}
      {uploadedPhotos.map(photo => <figure key={photo.id}><img src={photo.read_url} alt="Загруженное фото при выдаче" /><figcaption>Загружено</figcaption></figure>)}
      {(validation || command.error) && <p role="alert">{validation || command.error!.message}</p>}
      {command.pending && <p role="status">Результат выдачи неизвестен. Повтор подтвердит ту же выдачу.</p>}
      <div className="form-submit"><button className="primary" type="submit" disabled={photoBusy || command.busy || (!createdOrder && !command.pending && !valid)}>{command.busy ? 'Выдаём…' : photoBusy ? 'Подготавливаем и загружаем фото…' : createdOrder ? 'Повторить загрузку фото' : command.pending ? 'Повторить выдачу' : 'Выдать наряд'}</button></div>
    </form>
  </section>;
}
