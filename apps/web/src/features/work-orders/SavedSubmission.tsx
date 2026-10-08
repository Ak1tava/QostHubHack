import type { WorkOrderTemplate } from './TemplateRequirements';
import type { ApiClient } from '../../lib/api';
import { useExecutionCatalogs, type Submission } from './data';

const evidenceLabels: Record<string, string> = { after_photo: 'Фото после работы', work_description: 'Описание выполненных работ', fault_code_id: 'Шифр неисправности', materials: 'Сведения о материалах', materials_conflict: 'Согласованность списка материалов и отметки об их отсутствии', invalid_photos: 'Допустимые фото этого наряда' };

export function SavedSubmission({ api, submission, template }: { api: ApiClient; submission: Submission; template?: WorkOrderTemplate | null }) {
  const catalogs = useExecutionCatalogs(api);
  const code = catalogs.data?.codes.find(item => item.id === submission.fault_code_id);
  return <section aria-label="Предыдущий отчёт"><h3>Передано на приёмку · отчёт {submission.revision}</h3>
    <p className="full-description">{submission.work_description}</p>
    <p>Шифр: {code ? `${code.code} · ${code.name}` : catalogs.loading ? 'Загружаем…' : 'Недоступен в справочнике'}</p>
    {submission.no_materials_used ? <p>Материалы не потребовались</p> : <ul>{submission.materials?.map(item => {
      const material = catalogs.data?.materials.find(material => material.id === item.material_id);
      return <li key={item.material_id}>{material?.name ?? 'Материал недоступен'}: {item.quantity}{material ? ` ${material.unit}` : ''}</li>;
    })}</ul>}
    {submission.after_photo_ids?.map(id => <figure className="saved-photo" key={id}><img src={`/api/v1/photos/${encodeURIComponent(id)}`} alt="Фото после работы из сохранённого отчёта" /></figure>)}
    {template && <section aria-label="Сохранённый чек-лист"><h4>Чек-лист · {template.title}</h4><ul>{template.checklist.map(item => {
      const answer = submission.template_answers?.find(answer => answer.id === item.id);
      return <li key={item.id}>{item.label}: {answer?.checked ? 'Выполнено' : 'Не подтверждено'}</li>;
    })}</ul></section>}
    {submission.comment && <p>{submission.comment}</p>}
    {!!submission.missing_evidence?.length && <p>Недостающие доказательства: {submission.missing_evidence.map(item => evidenceLabels[item] ?? 'Дополнительное подтверждение').join(', ')}</p>}
    {catalogs.error && <p role="alert">Справочники отчёта недоступны. <button type="button" onClick={catalogs.reload}>Обновить справочники</button></p>}
    <p className="muted">Отчёт сохранён и не редактируется.</p>
  </section>;
}
