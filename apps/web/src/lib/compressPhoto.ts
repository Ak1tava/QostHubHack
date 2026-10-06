const target = 500 * 1024;
const maximum = 5 * 1024 * 1024;

async function decode(file: File): Promise<{ source: CanvasImageSource; width: number; height: number; close: () => void }> {
  try {
    if (typeof createImageBitmap === 'function') {
      const bitmap = await createImageBitmap(file);
      return { source: bitmap, width: bitmap.width, height: bitmap.height, close: () => bitmap.close() };
    }
    const url = URL.createObjectURL(file);
    try {
      const image = new Image(); image.src = url; await image.decode();
      return { source: image, width: image.naturalWidth, height: image.naturalHeight, close: () => URL.revokeObjectURL(url) };
    } catch (error) { URL.revokeObjectURL(url); throw error; }
  } catch { throw new Error('Не удалось прочитать фотографию. Выберите другое изображение.'); }
}

export async function compressPhoto(file: File): Promise<File> {
  if (!file.size || file.size > 40 * 1024 * 1024) throw new Error('Исходное фото слишком большое или пустое. Выберите фото до 40 МБ.');
  const decoded = await decode(file);
  try {
    if (!decoded.width || !decoded.height) throw new Error('Не удалось прочитать размеры фотографии.');
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Сжатие фото недоступно в этом браузере.');
    let scale = Math.min(1, 2400 / Math.max(decoded.width, decoded.height));
    let result: Blob | null = null;
    for (let pass = 0; pass < 8; pass++) {
      canvas.width = Math.max(1, Math.round(decoded.width * scale)); canvas.height = Math.max(1, Math.round(decoded.height * scale));
      context.drawImage(decoded.source, 0, 0, canvas.width, canvas.height);
      result = await new Promise<Blob>((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Не удалось сжать фото.')), 'image/jpeg', pass === 0 ? 0.85 : 0.72));
      if (result.size <= target) break;
      scale *= Math.max(0.5, Math.min(0.85, Math.sqrt(target / result.size)));
    }
    if (!result || result.size > maximum) throw new Error('Не удалось уменьшить фотографию до 5 МБ. Выберите другое фото.');
    return new File([result], 'photo.jpg', { type: 'image/jpeg' });
  } finally { decoded.close(); }
}
