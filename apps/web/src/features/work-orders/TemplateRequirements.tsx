import { localizedTemplate, useLocale } from '../../ui/locale';
import type { components } from '../../../../../packages/contracts/api.generated';

export type WorkOrderTemplate = components['schemas']['WorkOrderTemplate'];

export function TemplateRequirements({ template: source }: { template: WorkOrderTemplate }) {
  const { tx, locale } = useLocale();
  const template = localizedTemplate(source, locale);
  return <section aria-label={tx("Требования шаблона")}>
    <h3>{template.title}</h3>
    <ul>{template.instructions.map((instruction, index) => <li key={index}>{instruction}</li>)}</ul>
    <ul>{template.checklist.map(item => <li key={item.id}>{item.label}{item.required ? tx(" · обязательно") : ''}</li>)}</ul>
    <p>{tx("Фото до: ")}{template.photo_requirements.before}{tx("; после: ")}{template.photo_requirements.after}{tx(". Требуются перед отправкой отчёта.")}</p>
    <details><summary>{tx('Подробности шаблона')}</summary><p>{template.title}{tx(" · версия ")}{template.version}</p></details>
  </section>;
}
