import { afterEach, expect, it, vi } from 'vitest';
import { compressPhoto } from './compressPhoto';
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it('decodes images, targets at most 500 KiB and releases the decoded bitmap', async () => {
  const close = vi.fn(); const drawImage = vi.fn();
  vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 4000, height: 3000, close }));
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(callback => callback(new Blob([new Uint8Array(400 * 1024)], { type: 'image/jpeg' })));
  const file = await compressPhoto(new File(['raw'], 'camera.png', { type: 'image/png' }));
  expect(file.type).toBe('image/jpeg'); expect(file.size).toBeLessThanOrEqual(500 * 1024); expect(drawImage).toHaveBeenCalled(); expect(close).toHaveBeenCalledOnce();
});
it('rejects decoding failures instead of uploading the raw file', async () => {
  vi.stubGlobal('createImageBitmap', vi.fn().mockRejectedValue(new Error('decode')));
  await expect(compressPhoto(new File(['invalid'], 'bad.jpg', { type: 'image/jpeg' }))).rejects.toThrow('Не удалось прочитать');
});
it('rejects an oversized compression result rather than falling back to the original', async () => {
  vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 1, height: 1, close: vi.fn() }));
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: vi.fn() } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(callback => callback(new Blob([new Uint8Array(6 * 1024 * 1024)], { type: 'image/jpeg' })));
  await expect(compressPhoto(new File(['raw'], 'large.jpg', { type: 'image/jpeg' }))).rejects.toThrow('5 МБ');
});
