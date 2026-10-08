// Only errors created by local UI helpers carry these IDs. Arbitrary Error/API text has no ID.
export const uiErrorMessages = {
  photo_decode: 'Не удалось прочитать фотографию. Выберите другое изображение.',
  photo_source_size: 'Исходное фото слишком большое или пустое. Выберите фото до 40 МБ.',
  photo_dimensions: 'Не удалось прочитать размеры фотографии.',
  photo_canvas: 'Сжатие фото недоступно в этом браузере.',
  photo_compress: 'Не удалось сжать фото.',
  photo_result_size: 'Не удалось уменьшить фотографию до 5 МБ. Выберите другое фото.',
  photo_prepare: 'Не удалось подготовить фото.',
  photo_upload: 'Не удалось загрузить фото.',
  issuance_photo_limit: 'При выдаче можно добавить не более пяти фото.',
  check_fields: 'Проверьте поля',
  period_bounds: 'Проверьте границы периода',
  period_order: 'Начало периода должно быть раньше окончания',
  period_invalid: 'Проверьте период',
  deadline_required: 'Укажите срок',
  deadline_nonexistent: 'Это время не существует в часовом поясе предприятия',
} as const;
export class UiError extends Error {
  constructor(public readonly uiCode: keyof typeof uiErrorMessages) {
    super(uiErrorMessages[uiCode]);
    this.name = 'UiError';
  }
}
