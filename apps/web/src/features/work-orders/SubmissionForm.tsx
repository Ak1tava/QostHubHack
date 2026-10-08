import { displayFixtureName, displayFaultCode } from '../../lib/displayFixture';
import { localizedTemplate, useLocale } from '../../ui/locale';
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { ApiClient, ApiError } from '../../lib/api';
import { useCommand } from '../../lib/useCommand';
import { PhotoUpload } from './PhotoUpload';
import { SpeechInput } from '../speech/SpeechInput';
import { submitOrder, useExecutionCatalogs, type SubmissionCreate, type WorkOrderDetail } from './data';

export function SubmissionForm({ api, order, disabled, reload, onSubmitted, onLockChange }: { api: ApiClient; order: WorkOrderDetail; disabled: boolean; reload: () => void; onSubmitted: () => void; onLockChange?: (locked: boolean) => void }) {
  const { tx, locale, errorText } = useLocale();
  const catalogs = useExecutionCatalogs(api);
  const template = order.template_snapshot ? localizedTemplate(order.template_snapshot, locale) : null;
  const [answers, setAnswers] = useState<Record<string, boolean>>({});
  const [description, setDescription] = useState('');
  const [code, setCode] = useState('');
  const [noMaterials, setNoMaterials] = useState(false);
  const [materials, setMaterials] = useState<{ material_id: string; quantity: string }[]>([]);
  const [photoIds, setPhotoIds] = useState<string[]>([]);
  const [comment, setComment] = useState('');
  const [photoPending, setPhotoPending] = useState(false);
  const command = useCommand(useCallback((body: SubmissionCreate, key: string) => submitOrder(api, order.id, body, key), [api, order.id]));
  useEffect(() => { onLockChange?.(command.busy || command.pending || photoPending); }, [command.busy, command.pending, photoPending, onLockChange]);
  useEffect(() => { if (command.error instanceof ApiError && command.error.status === 409) reload(); }, [command.error, reload]);
  const allowed = order.allowed_actions?.includes('submit') ?? false;
  const validMaterials = noMaterials || (materials.length > 0 && new Set(materials.map(material => material.material_id)).size === materials.length && materials.every(material =>
    catalogs.data?.materials.some(item => item.id === material.material_id) && /^\d{1,10}(\.\d{1,4})?$/.test(material.quantity) && Number(material.quantity) > 0));
  const validEvidence = !template || ((order.before_photo_count ?? 0) >= template.photo_requirements.before && photoIds.length >= template.photo_requirements.after && template.checklist.every(item => !item.required || answers[item.id] === true));
  const valid = validEvidence && allowed && !disabled && !photoPending && !!description.trim() && !!catalogs.data?.codes.some(item => item.id === code) && validMaterials;
  const locked = disabled || command.busy || command.pending || !allowed;
  async function submit(event: FormEvent) {
    event.preventDefault(); if (disabled || (!command.pending && !valid)) return;
    const body: SubmissionCreate | undefined = command.pending ? undefined : { ...(template ? { template_answers: template.checklist.map(item => ({ id: item.id, checked: answers[item.id] === true })) } : {}), expected_version: order.version, assignment_version: order.assignment_version, work_description: description.trim(), fault_code_id: code, materials: noMaterials ? [] : materials, no_materials_used: noMaterials, after_photo_ids: photoIds, comment: comment.trim() || null };
    const result = await command.run(body);
    if (result) { setAnswers({}); setDescription(''); setCode(''); setMaterials([]); setNoMaterials(false); setPhotoIds([]); setComment(''); onSubmitted(); }
  }
  return <form className="action-form" onSubmit={submit}>
    <h3>{tx("Отчёт о выполнении")}</h3>
    <p>{tx('После отправки отчёта ИИ сравнит заявку, описание работы и фото. Окончательное решение принимает мастер.')}</p>
    <fieldset className="form-fields" disabled={locked}>
      {template && <fieldset><legend>{tx("Чек-лист шаблона")}</legend>{template.checklist.map(item => <label className="checkbox-label" key={item.id}>
        <input type="checkbox" name={`template-${item.id}`} checked={answers[item.id] === true} onChange={event => setAnswers(previous => ({ ...previous, [item.id]: event.target.checked }))} />{item.label}{item.required ? tx(" · обязательно") : ''}
      </label>)}<p>{tx("Фото до: ")}{order.before_photo_count ?? 0} / {template.photo_requirements.before}{tx("; после: ")}{photoIds.length} / {template.photo_requirements.after}</p></fieldset>}
      <label>{tx("Выполненные работы")}<textarea name="work_description" value={description} onChange={event => setDescription(event.target.value)} required maxLength={8000} rows={4} /></label>
      <SpeechInput api={api} value={description} onChange={setDescription} maxLength={8000} disabled={locked} />
      <label>{tx("Шифр неисправности")}<select name="fault_code_id" value={code} onChange={event => setCode(event.target.value)} required><option value="">{tx("Выберите")}</option>{catalogs.data?.codes.map(item => <option value={item.id} key={item.id}>{displayFaultCode(item.code)} · {displayFixtureName(item.name)}</option>)}</select></label>
      <label className="checkbox-label"><input type="checkbox" name="no_materials_used" checked={noMaterials} onChange={event => setNoMaterials(event.target.checked)} />{tx("Материалы не потребовались")}</label>
      {!noMaterials && <section aria-label={tx("Материалы")}>{materials.map((material, index) => <div className="material-row" key={index}>
        <label>{tx("Материал")}<select name={`material_id-${index}`} value={material.material_id} onChange={event => setMaterials(previous => previous.map((item, position) => position === index ? { ...item, material_id: event.target.value } : item))}><option value="">{tx("Выберите")}</option>{catalogs.data?.materials.map(item => <option key={item.id} value={item.id}>{displayFixtureName(item.name)} · {item.unit}</option>)}</select></label>
        <label>{tx("Количество")}<input name={`quantity-${index}`} inputMode="decimal" value={material.quantity} onChange={event => setMaterials(previous => previous.map((item, position) => position === index ? { ...item, quantity: event.target.value.replace(',', '.') } : item))} required /></label>
        <button type="button" onClick={() => setMaterials(previous => previous.filter((_, position) => position !== index))}>{tx("Удалить материал")}</button>
      </div>)}<button type="button" onClick={() => setMaterials(previous => [...previous, { material_id: '', quantity: '' }])}>{tx("Добавить материал")}</button></section>}
      <PhotoUpload api={api} orderId={order.id} type="after" disabled={locked} onUploaded={photo => setPhotoIds(previous => [...previous, photo.id])} onPendingChange={setPhotoPending} />
      {!template && !photoIds.length && <p className="muted">{tx("Без фото отчёт можно отправить на проверку; отсутствие доказательств будет отмечено.")}</p>}
      <label>{tx("Комментарий")}<textarea name="comment" value={comment} onChange={event => setComment(event.target.value)} maxLength={4000} rows={2} /></label>
    </fieldset>
    {catalogs.error && <p role="alert">{errorText(catalogs.error)} <button type="button" onClick={catalogs.reload}>{tx("Обновить справочники")}</button></p>}
    {command.error && <p role="alert">{errorText(command.error)}{command.error instanceof ApiError && command.error.status === 409 ? tx(". Наряд перечитан; проверьте данные и отправьте снова.") : ''}</p>}
    {command.pending && <p role="status">{tx("Результат неизвестен. Повтор отправит тот же отчёт.")}</p>}
    <button className="primary" type="submit" disabled={disabled || command.busy || (!command.pending && !valid)}>{command.busy ? tx("Отправляем…") : command.pending ? tx("Повторить отправку") : tx("Передать на проверку")}</button>
  </form>;
}
