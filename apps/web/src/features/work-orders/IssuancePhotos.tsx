import { useLocale } from '../../ui/locale';
import type { Photo } from './data';

export function IssuancePhotos({ photos = [] }: { photos?: Photo[] }) {
  const { tx } = useLocale();
  if (!photos.length) return null;
  return <section aria-label={tx("Фото при выдаче")}><h3>{tx("Фото при выдаче")}</h3>
    {photos.map(photo => <figure key={photo.id}><img src={photo.read_url} alt={tx("Фото мастера при выдаче")} /><figcaption>{tx("Исходное состояние")}</figcaption></figure>)}
  </section>;
}
