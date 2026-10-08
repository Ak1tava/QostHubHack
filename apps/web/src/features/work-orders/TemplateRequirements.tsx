import type { components } from '../../../../../packages/contracts/api.generated';

export type WorkOrderTemplate = components['schemas']['WorkOrderTemplate'];

export function TemplateRequirements({ template }: { template: WorkOrderTemplate }) {
  return <section aria-label="Требования шаблона">
    <h3>{template.title} · версия {template.version}</h3>
    <ul>{template.instructions.map((instruction, index) => <li key={index}>{instruction}</li>)}</ul>
    <ul>{template.checklist.map(item => <li key={item.id}>{item.label}{item.required ? ' · обязательно' : ''}</li>)}</ul>
    <p>Фото до: {template.photo_requirements.before}; после: {template.photo_requirements.after}. Требуются перед отправкой отчёта.</p>
  </section>;
}
