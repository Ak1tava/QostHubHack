import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiClient } from '../../lib/api';
import { SpeechInput } from './SpeechInput';

let root: Root, container: HTMLDivElement;
let uploads: FormData[], signals: AbortSignal[];
let response: () => Promise<Response>;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const transcript = (text = 'Распознано', mock = false) => json({ text, language: 'ru', model: 'large-v3-turbo', duration_seconds: 1, is_mock: mock });
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
  uploads = []; signals = []; response = async () => transcript();
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.unstubAllGlobals(); vi.useRealTimers(); });
function Harness({ maxLength = 10000, disabled = false }: { maxLength?: number; disabled?: boolean }) {
  const [value, setValue] = useState('Введено вручную');
  const api = new ApiClient(async (url, init) => {
    if (String(url).endsWith('/csrf')) return json({ csrf_token: 'csrf' });
    uploads.push(init!.body as FormData); signals.push(init!.signal!); return response();
  });
  return <form onSubmit={event => { event.preventDefault(); throw new Error('Unexpected submit'); }}>
    <textarea aria-label="Описание" value={value} onChange={event => setValue(event.target.value)} />
    <SpeechInput api={api} value={value} onChange={setValue} maxLength={maxLength} disabled={disabled} />
  </form>;
}
async function render(props: { maxLength?: number; disabled?: boolean } = {}) { await act(async () => root.render(<Harness {...props} />)); }
function button(label: string) { return [...container.querySelectorAll<HTMLButtonElement>('button')].find(item => item.textContent === label)!; }
async function click(label: string) { expect(button(label)).toBeDefined(); await act(async () => button(label).click()); }
async function edit(label: string, value: string) {
  await act(async () => {
    const field = container.querySelector<HTMLTextAreaElement>(`textarea[aria-label="${label}"]`)!;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(field, value);
    field.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
async function upload(file = new File(['audio'], 'voice.webm', { type: 'audio/webm' })) {
  await act(async () => {
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    expect(input).not.toBeNull(); Object.defineProperty(input, 'files', { configurable: true, value: [file] });
    input.dispatchEvent(new Event('change', { bubbles: true }));
  });
}
const description = () => container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Описание"]')!.value;

it('keeps the form untouched until edited draft is explicitly appended and never submits', async () => {
  await render(); await upload();
  expect(description()).toBe('Введено вручную');
  await edit('Черновик расшифровки', 'Проверено и исправлено');
  await edit('Описание', 'Новый ручной текст');
  await click('Вставить'); expect(description()).toBe('Новый ручной текст\n\nПроверено и исправлено');
  expect(container.querySelector('textarea[aria-label="Черновик расшифровки"]')).toBeNull();
});
it('sends Russian multipart audio without a language selector and with abort signal', async () => {
  await render();
  expect(container.querySelector('select')).toBeNull();
  await upload(); expect(uploads[0].get('language')).toBe('ru'); expect(uploads[0].get('file')).toBeInstanceOf(File); expect(signals[0].aborted).toBe(false);
});
it('rejects oversized file before uploading and preserves manual input', async () => {
  await render(); const file = new File(['x'], 'large.webm', { type: 'audio/webm' }); Object.defineProperty(file, 'size', { value: 10 * 1024 * 1024 + 1 });
  await upload(file); expect(uploads).toHaveLength(0); expect(container.querySelector('[role="alert"]')).not.toBeNull(); expect(description()).toBe('Введено вручную');
});
it.each([
  ['mobile.M4A', 'audio/mp4'], ['voice.mp3', 'audio/mpeg'], ['record.wav', 'audio/wav'],
  ['record.webm', 'audio/webm'], ['record.mp4', 'audio/mp4'], ['record.ogg', 'audio/ogg'],
])('uploads %s with supported MIME when browser omitted File.type', async (name, mimeType) => {
  await render(); await upload(new File(['synthetic-audio'], name));
  expect(uploads[0].get('file')).toMatchObject({ name, type: mimeType, size: 15 });
  await click('Вставить'); expect(description()).toBe('Введено вручную\n\nРаспознано');
});
it('rejects unsupported extension when File.type is empty without sending arbitrary data', async () => {
  await render(); await upload(new File(['synthetic-audio'], 'document.pdf'));
  expect(uploads).toHaveLength(0); expect(container.querySelector('[role="alert"]')).not.toBeNull();
  expect(description()).toBe('Введено вручную');
});
it('does not override an explicitly unsupported MIME based on a supported extension', async () => {
  await render(); await upload(new File(['synthetic-audio'], 'document.wav', { type: 'application/pdf' }));
  expect(uploads).toHaveLength(0); expect(container.querySelector('[role="alert"]')).not.toBeNull();
});
it('aborts canceled upload and ignores stale response after another upload', async () => {
  let done!: (value: Response) => void; response = () => new Promise(resolve => { done = resolve; });
  await render(); await upload(); await click('Отмена'); expect(signals[0].aborted).toBe(true);
  response = async () => transcript('Свежая запись'); await upload(); await act(async () => done(transcript('Старый ответ')));
  expect(container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Черновик расшифровки"]')!.value).toBe('Свежая запись');
});
it('shows safe errors, allows retry, and explicitly marks mock transcripts', async () => {
  response = async () => json({ error: { code: 'unavailable', message: 'internal http://asr:8016 model large-v3-turbo', details: [] } }, 503);
  await render(); await upload(); expect(container.textContent).not.toContain('http://asr'); expect(container.textContent).not.toContain('large-v3');
  response = async () => transcript('Тестовая речь', true); await click('Повторить распознавание');
  expect(container.textContent).toContain('Тестовая расшифровка'); await click('Отмена'); expect(description()).toBe('Введено вручную');
});
it('offers file and manual input without MediaRecorder', async () => {
  vi.stubGlobal('MediaRecorder', undefined); await render(); expect(button('Записать голос').disabled).toBe(true);
  await upload(); await click('Вставить'); expect(description()).toContain('Распознано');
});
it('refuses insertion exceeding target limit without truncating text', async () => {
  await render({ maxLength: 20 }); await upload(); await click('Вставить'); expect(description()).toBe('Введено вручную'); expect(container.querySelector('[role="alert"]')).not.toBeNull();
});
it('aborts upload when the parent form becomes locked', async () => {
  let done!: (value: Response) => void; response = () => new Promise(resolve => { done = resolve; });
  await render(); await upload(); await render({ disabled: true }); expect(signals[0].aborted).toBe(true);
  await act(async () => done(transcript('После блокировки')));
  expect(container.querySelector('textarea[aria-label="Черновик расшифровки"]')).toBeNull(); expect(description()).toBe('Введено вручную');
});
it('rejects empty speech without inserting fabricated text', async () => {
  response = async () => transcript('  '); await render(); await upload();
  expect(container.querySelector('[role="alert"]')).not.toBeNull(); expect(button('Вставить')).toBeUndefined(); expect(description()).toBe('Введено вручную');
});

class Recorder {
  static instances: Recorder[] = [];
  static isTypeSupported = (type: string) => type === 'audio/mp4';
  state = 'inactive'; mimeType: string; ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null; onerror: (() => void) | null = null;
  constructor(_stream: MediaStream, options?: MediaRecorderOptions) { this.mimeType = options?.mimeType ?? ''; Recorder.instances.push(this); }
  start() { this.state = 'recording'; }
  stop() { if (this.state !== 'recording') throw new DOMException('Inactive recorder', 'InvalidStateError'); this.state = 'inactive'; queueMicrotask(() => { this.ondataavailable?.({ data: new Blob(['voice'], { type: this.mimeType }) }); this.onstop?.(); }); }
}
function microphone(getUserMedia?: () => Promise<unknown>) {
  const stop = vi.fn(); Recorder.instances = []; vi.stubGlobal('MediaRecorder', Recorder);
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia: getUserMedia ?? (async () => ({ getTracks: () => [{ stop }] })) } });
  return stop;
}
it('records supported mp4 and releases the microphone on stop before draft insertion', async () => {
  const stop = microphone(); await render(); await click('Записать голос'); expect(Recorder.instances[0].mimeType).toBe('audio/mp4');
  await click('Остановить запись'); expect(stop).toHaveBeenCalled(); expect(uploads[0].get('file')).toMatchObject({ type: 'audio/mp4' }); expect(description()).toBe('Введено вручную');
});
it('handles repeated stop clicks while final recorder data is still pending', async () => {
  const failures: unknown[] = [];
  const capture = (event: ErrorEvent) => { event.preventDefault(); failures.push(event.error); };
  window.addEventListener('error', capture);
  try {
    microphone(); await render(); await click('Записать голос');
    await act(async () => { button('Остановить запись').click(); button('Остановить запись').click(); });
    expect(failures).toEqual([]); expect(uploads).toHaveLength(1);
  } finally { window.removeEventListener('error', capture); }
});
it('stops at fifty-nine seconds and uploads final data within the server duration limit', async () => {
  vi.useFakeTimers(); const stop = microphone(); await render(); await click('Записать голос');
  await act(async () => vi.advanceTimersByTime(58_999)); expect(uploads).toHaveLength(0); expect(stop).not.toHaveBeenCalled();
  await act(async () => vi.advanceTimersByTime(1)); expect(uploads).toHaveLength(1); expect(stop).toHaveBeenCalled();
  expect(uploads[0].get('file')).toMatchObject({ type: 'audio/mp4', size: 5 });
  await click('Отмена'); await click('Записать голос'); await act(async () => root.unmount()); expect(stop).toHaveBeenCalledTimes(2);
});
it('handles denied microphone and permits file fallback', async () => {
  microphone(async () => { throw new DOMException('Denied', 'NotAllowedError'); }); await render(); await click('Записать голос');
  expect(container.querySelector('[role="alert"]')?.textContent).toContain('микрофон'); await upload(); await click('Вставить'); expect(description()).toContain('Распознано');
});
it('cleans a late microphone permission result after cancellation', async () => {
  let allow!: (value: unknown) => void; const stop = vi.fn(); microphone(() => new Promise(resolve => { allow = resolve; }));
  await render(); await click('Записать голос'); await click('Отмена');
  await act(async () => allow({ getTracks: () => [{ stop }] })); expect(stop).toHaveBeenCalled(); expect(Recorder.instances).toHaveLength(0); expect(uploads).toHaveLength(0);
});
