import type { Photo } from './data';

export function IssuancePhotos({ photos = [] }: { photos?: Photo[] }) {
  if (!photos.length) return null;
  return <section aria-label="Фото при выдаче"><h3>Фото при выдаче</h3>
    {photos.map(photo => <figure key={photo.id}><img src={photo.read_url} alt="Фото мастера при выдаче" /><figcaption>Исходное состояние</figcaption></figure>)}
  </section>;
}
