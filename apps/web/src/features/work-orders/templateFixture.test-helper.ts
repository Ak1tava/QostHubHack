import type { components } from '../../../../../packages/contracts/api.generated';

export const leakTemplate: components['schemas']['WorkOrderTemplate'] = {
  id: 'visible_leak', version: 1, title: 'Устранение видимой течи', initial_description: 'Устранить видимую течь',
  instructions: ['Зафиксировать видимый участок течи'],
  checklist: [
    { id: 'identify_leak', label: 'Место течи указано', required: true },
    { id: 'describe_repair', label: 'Работы описаны', required: true },
    { id: 'inspect_result', label: 'Результат осмотрен', required: true },
  ], photo_requirements: { before: 1, after: 1 },
};
