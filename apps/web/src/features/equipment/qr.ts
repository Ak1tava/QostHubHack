import QRCode from 'qrcode';

const svgUrl = (svg: string) => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
const escape = (text: string) => text.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' })[char]!);

export async function equipmentQr(url: string, name: string, id: string) {
  const parsed = new URL(url);
  if (parsed.protocol !== 'https:' || parsed.username || parsed.password || parsed.search || parsed.hash) throw new Error('QR доступен на HTTPS-стенде.');
  const qr = svgUrl(await QRCode.toString(url, { type: 'svg', errorCorrectionLevel: 'M', margin: 4, width: 512 }));
  const lines = Array.from(name).reduce<string[]>((result, char, index) => {
    if (index % 32 === 0) result.push('');
    result[result.length - 1] += char;
    return result;
  }, []);
  const top = 40 + lines.length * 32;
  const label = svgUrl(`<svg xmlns="http://www.w3.org/2000/svg" width="800" height="${top + 620}" viewBox="0 0 800 ${top + 620}"><rect width="100%" height="100%" fill="white"/><g fill="black" font-family="Arial,sans-serif" text-anchor="middle">${lines.map((line, i) => `<text x="400" y="${40 + i * 32}" font-size="28">${escape(line)}</text>`).join('')}<image x="144" y="${top}" width="512" height="512" href="${qr}"/><text x="400" y="${top + 540}" font-size="20">${escape(id)}</text><text x="400" y="${top + 578}" font-size="24">Оборудование · НарядAI</text></g></svg>`);
  return { qr, label };
}
