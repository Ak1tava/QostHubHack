import { useLocale } from '../../ui/locale';
import { useEffect, useRef, useState } from 'react';
import type { components } from '../../../../../packages/contracts/api.generated';
import { ApiError, type ApiClient } from '../../lib/api';

type Phase = 'idle' | 'permission' | 'recording' | 'transcribing' | 'draft';
const MAX_BYTES = 10 * 1024 * 1024;
const AUDIO_TYPES = ['audio/webm', 'audio/mp4', 'audio/x-m4a', 'audio/mpeg', 'audio/wav', 'audio/x-wav', 'audio/ogg'];
const AUDIO_EXTENSIONS: Record<string, string> = {
  '.webm': 'audio/webm', '.mp4': 'audio/mp4', '.m4a': 'audio/mp4',
  '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.ogg': 'audio/ogg',
};

function speechError(error: unknown): string {
  if (!(error instanceof ApiError)) return 'Не удалось распознать речь. Повторите попытку или введите текст вручную.';
  switch (error.status) {
    case 401: return 'Сессия истекла. Войдите снова.';
    case 403: return 'Распознавание недоступно для вашей учётной записи. Введите текст вручную.';
    case 413: return 'Аудио должно быть не больше 10 МБ.';
    case 415: return 'Выберите аудиофайл WebM, MP4, M4A, MP3, WAV или OGG.';
    case 422: return 'Не удалось прочитать речь. Проверьте язык и запись: не более 60 секунд.';
    case 429: return 'Распознавание занято. Повторите попытку позже или введите текст вручную.';
    case 503: return 'Распознавание временно недоступно. Повторите позже или введите текст вручную.';
    default: return 'Не удалось распознать речь. Проверьте соединение и повторите попытку.';
  }
}

export function SpeechInput({ api, value, onChange, maxLength, disabled = false }: {
  api: ApiClient; value: string; onChange: (value: string) => void; maxLength: number; disabled?: boolean;
}) {
  const { tx } = useLocale();
  const [phase, setPhase] = useState<Phase>('idle');
  const [draft, setDraft] = useState('');
  const [mock, setMock] = useState(false);
  const [error, setError] = useState<string | { limit: number }>('');
  const [audio, setAudio] = useState<File | null>(null);
  const generation = useRef(0);
  const request = useRef<AbortController | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const canRecord = typeof MediaRecorder !== 'undefined' && !!navigator.mediaDevices?.getUserMedia;
  const busy = phase === 'permission' || phase === 'recording' || phase === 'transcribing';

  function releaseMicrophone() {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
    stream.current?.getTracks().forEach(track => track.stop());
    stream.current = null;
  }
  function stopWork() {
    generation.current++;
    request.current?.abort(); request.current = null;
    const active = recorder.current; recorder.current = null;
    if (active) {
      active.onstop = null; active.ondataavailable = null; active.onerror = null;
      if (active.state !== 'inactive') active.stop();
    }
    releaseMicrophone();
  }
  function cancel() {
    stopWork(); setAudio(null); setDraft(''); setMock(false); setError(''); setPhase('idle');
  }
  useEffect(() => () => stopWork(), []);
  useEffect(() => { if (disabled) cancel(); }, [disabled]);

  async function transcribe(file: File) {
    stopWork(); setDraft(''); setMock(false); setError(''); setPhase('idle'); setAudio(null);
    if (!file.size || file.size > MAX_BYTES) { setError("Выберите непустое аудио не больше 10 МБ и не длиннее 60 секунд."); return; }
    if (!file.type) {
      const type = AUDIO_EXTENSIONS[file.name.slice(file.name.lastIndexOf('.')).toLowerCase()];
      if (type) file = new File([file], file.name, { type, lastModified: file.lastModified });
    }
    if (!AUDIO_TYPES.includes(file.type.split(';')[0].toLowerCase())) { setError("Выберите аудиофайл WebM, MP4, M4A, MP3, WAV или OGG."); return; }
    setAudio(file); setPhase('transcribing');
    const token = generation.current;
    const controller = new AbortController(); request.current = controller;
    const body = new FormData(); body.set('file', file); body.set('language', 'ru');
    try {
      const result = await api.request<components['schemas']['SpeechTranscription']>('/api/v1/speech/transcriptions', {
        method: 'POST', body, signal: controller.signal,
      });
      if (token !== generation.current || controller.signal.aborted) return;
      if (!result.text.trim()) { setError("Речь не обнаружена. Запишите ещё раз или введите текст вручную."); setPhase('idle'); return; }
      setDraft(result.text); setMock(result.is_mock); setPhase('draft');
    } catch (failure) {
      if (token !== generation.current || controller.signal.aborted) return;
      setError(speechError(failure)); setPhase('idle');
    } finally { if (request.current === controller) request.current = null; }
  }

  async function record() {
    if (!canRecord || disabled) return;
    cancel(); setPhase('permission'); const token = generation.current;
    try {
      const microphone = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (token !== generation.current) { microphone.getTracks().forEach(track => track.stop()); return; }
      stream.current = microphone;
      const mimeType = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'].find(type => MediaRecorder.isTypeSupported(type));
      if (!mimeType) throw new Error('unsupported');
      const active = new MediaRecorder(microphone, { mimeType }); recorder.current = active;
      const chunks: Blob[] = []; let bytes = 0;
      active.ondataavailable = event => {
        if (token !== generation.current) return;
        bytes += event.data.size;
        if (bytes > MAX_BYTES) { stopWork(); setPhase('idle'); setError("Запись превысила 10 МБ. Запишите более короткое сообщение."); return; }
        chunks.push(event.data);
      };
      active.onerror = () => {
        if (token !== generation.current) return;
        stopWork(); setPhase('idle'); setError("Запись прервалась. Повторите или выберите аудиофайл.");
      };
      active.onstop = () => {
        if (token !== generation.current) return;
        releaseMicrophone();
        const type = active.mimeType || mimeType;
        const file = new File(chunks, type.startsWith('audio/mp4') ? 'speech.mp4' : 'speech.webm', { type });
        void transcribe(file);
      };
      active.start(1000); setPhase('recording');
      // Reserve one second for encoder padding and delivery of the final chunk.
      timer.current = setTimeout(() => { if (active.state === 'recording') active.stop(); }, 59_000);
    } catch (failure) {
      if (token !== generation.current) return;
      stopWork(); setPhase('idle');
      setError(failure instanceof DOMException && failure.name === 'NotAllowedError'
        ? "Доступ к микрофону запрещён. Разрешите его в браузере или выберите аудиофайл."
        : "Микрофон или запись недоступны. Используйте HTTPS, выберите аудиофайл или введите текст вручную.");
    }
  }

  function insert() {
    const text = draft.trim();
    if (!text || disabled) return;
    const appended = value ? `${value}\n\n${text}` : text;
    if (appended.length > maxLength) { setError({ limit: maxLength }); return; }
    onChange(appended); cancel();
  }

  return <section aria-label={tx("Голосовой ввод")} className="speech-input">
    <p className="muted">{tx("Голосовой ввод · до 60 секунд и 10 МБ. Проверьте текст перед вставкой; можно писать вручную.")}</p>
    <p className="muted">{tx("Распознавание речи доступно только на русском языке.")}</p>
    <div className="form-row">
      {phase === 'recording' ? <button type="button" disabled={disabled} onClick={() => { const active = recorder.current; if (active?.state === 'recording') active.stop(); }}>{tx("Остановить запись")}</button>
        : <button type="button" disabled={disabled || busy || !canRecord} onClick={() => void record()}>{tx("Записать голос")}</button>}
      <label>{tx("Выбрать аудио")}<input type="file" aria-label={tx("Аудиофайл")} accept="audio/webm,audio/mp4,audio/x-m4a,audio/mpeg,audio/wav,audio/x-wav,audio/ogg,.webm,.mp4,.m4a,.mp3,.wav,.ogg" disabled={disabled || busy} onChange={event => {
        const file = event.target.files?.[0]; event.target.value = ''; if (file) void transcribe(file);
      }} /></label>
    </div>
    {!canRecord && <p className="muted">{tx("Запись в этом браузере недоступна. Выберите аудиофайл или введите текст вручную.")}</p>}
    {phase === 'permission' && <p role="status">{tx("Ожидаем разрешение микрофона…")}</p>}
    {phase === 'recording' && <p role="status">{tx("Идёт запись. Она остановится автоматически.")}</p>}
    {phase === 'transcribing' && <p role="status">{tx("Распознаём речь…")}</p>}
    {phase === 'draft' && <>
      {mock && <p role="status">{tx("Тестовая расшифровка — проверьте и исправьте текст.")}</p>}
      <label>{tx("Черновик расшифровки")}<textarea aria-label={tx("Черновик расшифровки")} value={draft} disabled={disabled} onChange={event => { setDraft(event.target.value); setError(''); }} rows={4} /></label>
      <button type="button" disabled={disabled || !draft.trim()} onClick={insert}>{tx("Вставить")}</button>
    </>}
    {error && <p role="alert">{typeof error === 'string' ? tx(error) : tx("Текст превышает лимит ") + error.limit + tx(" символов. Сократите черновик перед вставкой.")}</p>}
    {error && audio && <button type="button" disabled={disabled || busy} onClick={() => void transcribe(audio)}>{tx("Повторить распознавание")}</button>}
    {(busy || phase === 'draft' || error) && <button type="button" disabled={disabled} onClick={cancel}>{tx("Отмена")}</button>}
  </section>;
}
