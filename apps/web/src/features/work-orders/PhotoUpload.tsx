import { useEffect, useRef, useState } from 'react';
import type { ApiClient } from '../../lib/api';
import { compressPhoto } from '../../lib/compressPhoto';
import { uploadPhoto, type Photo } from './data';

export function PhotoUpload({ api, orderId, type, disabled, onUploaded, onPendingChange }: { api: ApiClient; orderId: string; type: 'before' | 'after'; disabled: boolean; onUploaded: (photo: Photo) => void; onPendingChange?: (pending: boolean) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [preview, setPreview] = useState('');
  const running = useRef(false);
  const active = useRef(true);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  useEffect(() => { onPendingChange?.(busy || !!file); }, [busy, file, onPendingChange]);
  useEffect(() => {
    if (!file) { setPreview(''); return; }
    const url = URL.createObjectURL(file); setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  async function choose(selected: File | undefined) {
    if (!selected || running.current || disabled) return;
    running.current = true; setBusy(true); setError(''); setFile(null);
    try { const compressed = await compressPhoto(selected); if (active.current) setFile(compressed); }
    catch (error) { if (active.current) setError(error instanceof Error ? error.message : 'Не удалось подготовить фото.'); }
    finally { running.current = false; if (active.current) setBusy(false); }
  }
  async function upload() {
    if (!file || running.current || disabled) return;
    running.current = true; setBusy(true); setError('');
    try {
      const photo = await uploadPhoto(api, orderId, file, type);
      if (active.current) { setPhotos(previous => [...previous, photo]); setFile(null); onUploaded(photo); }
    } catch (error) { if (active.current) setError(error instanceof Error ? error.message : 'Не удалось загрузить фото.'); }
    finally { running.current = false; if (active.current) setBusy(false); }
  }
  return <section className="photo-upload" aria-label={`Фото ${type === 'before' ? 'до' : 'после'}`}>
    <label>Фото {type === 'before' ? 'до работы' : 'после работы'}<input type="file" accept="image/*" capture="environment" disabled={disabled || busy} onChange={event => { const selected = event.target.files?.[0]; event.target.value = ''; void choose(selected); }} /></label>
    {preview && file && <figure><img src={preview} alt="Предпросмотр выбранного фото" /><figcaption>{Math.ceil(file.size / 1024)} КБ · подготовлено к загрузке</figcaption></figure>}
    {file && <button type="button" disabled={disabled || busy} onClick={() => void upload()}>{busy ? 'Загружаем…' : error ? 'Повторить загрузку фото' : 'Загрузить фото'}</button>}
    {busy && <p role="status">Подготавливаем и загружаем фотографию…</p>}
    {error && <p role="alert">{error}</p>}
    {photos.map(photo => <figure key={photo.id}><img src={photo.read_url} alt={`Загруженное фото ${type === 'before' ? 'до' : 'после'}`} /><figcaption>Загружено</figcaption></figure>)}
  </section>;
}
