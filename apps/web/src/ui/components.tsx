import { useEffect, useId, useRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { describeStatus, type StatusDomain, type Tone } from './status';
import { translate, type Locale } from './i18n';

type Localized = { locale?: Locale };
export function StatusDot({ tone, label }: { tone: Tone; label: string }) {
  return <span className="ui-status-dot-label"><span className="ui-status-dot" data-tone={tone} aria-hidden="true" />{label}</span>;
}
export function StatusBadge({ domain, status, overdue = false, locale = 'ru' }: Localized & { domain: StatusDomain; status: string; overdue?: boolean }) {
  const { label, tone } = describeStatus(domain, status, locale);
  return <span className="ui-badges"><span className="ui-badge" data-tone={tone}>{label}</span>
    {overdue && <span className="ui-badge" data-tone="danger">{translate(locale, 'overdue')}</span>}</span>;
}
export function PriorityChip({ priority, locale = 'ru' }: Localized & { priority: keyof typeof import('./status').statusCatalog.priority }) {
  return <span className={priority === 'emergency' ? 'ui-emergency' : undefined}><StatusBadge domain="priority" status={priority} locale={locale} /></span>;
}
export function KpiTile({ label, value, delta, tone }: { label: string; value: ReactNode; delta?: string; tone?: Tone }) {
  return <div className="ui-kpi" data-tone={tone}><span>{label}</span><strong>{value}</strong>{delta && <small>{delta}</small>}</div>;
}
export function BigActionButton({ variant = 'primary', pending = false, locale = 'ru', children, disabled, className = '', ...props }:
  Localized & ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'danger'; pending?: boolean }) {
  return <button type="button" {...props} className={`ui-action ui-action-${variant} ${className}`} disabled={disabled || pending} aria-busy={pending || undefined}>
    {pending ? translate(locale, 'pending') : children}
  </button>;
}
export function ReasonChips({ label, options, value, onChange, disabled = false }: {
  label: string; options: { value: string; label: string }[]; value: string; onChange: (value: string) => void; disabled?: boolean;
}) {
  return <fieldset className="ui-reasons" disabled={disabled}><legend>{label}</legend><div className="ui-chip-row">
    {options.map(option => <button key={option.value} type="button" aria-pressed={value === option.value}
      onClick={() => onChange(option.value)}>{option.label}</button>)}
  </div></fieldset>;
}
export function DeadlineBar({ remainingSeconds, totalSeconds, overdue, locale = 'ru' }:
  Localized & { remainingSeconds: number; totalSeconds: number; overdue: boolean }) {
  if (!Number.isFinite(remainingSeconds) || !Number.isFinite(totalSeconds) || totalSeconds <= 0) {
    return <p className="ui-caption">{translate(locale, 'deadlineUnknown')}</p>;
  }
  const ratio = Math.max(0, Math.min(1, remainingSeconds / totalSeconds));
  const tone: Tone = overdue || ratio < .2 ? 'danger' : ratio <= .5 ? 'busy' : 'ok';
  const label = `${translate(locale, overdue ? 'overdue' : 'remaining')} ${Math.ceil(Math.abs(remainingSeconds) / 60)} ${translate(locale, 'minutes')}`;
  return <div className="ui-deadline" data-tone={tone} data-overdue={overdue}>
    <span>{label}</span><div className="ui-deadline-track" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100}
      aria-valuenow={Math.round(ratio * 100)} aria-valuetext={label}><span style={{ width: `${overdue ? 100 : ratio * 100}%` }} /></div>
  </div>;
}

type OverlayProps = Localized & { open: boolean; onClose: () => void; title: string; children: ReactNode };
function Overlay({ open, onClose, title, children, locale = 'ru', variant }: OverlayProps & { variant: 'drawer' | 'sheet' }) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  useEffect(() => {
    const dialog = ref.current!;
    if (!open) { if (dialog.open) dialog.close(); return; }
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    dialog.showModal();
    document.body.style.overflow = 'hidden';
    return () => {
      dialog.close();
      document.body.style.overflow = previousOverflow;
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, [open]);
  return <dialog ref={ref} className={`ui-overlay ui-${variant}`} aria-labelledby={id} tabIndex={-1}
    onCancel={event => { event.preventDefault(); onClose(); }}
    onKeyDown={event => {
      if (event.key !== 'Tab') return;
      const dialog = event.currentTarget;
      const controls = Array.from(dialog.querySelectorAll<HTMLElement>('button, a[href], input, select, textarea, summary, [tabindex]'))
        .filter(element => element.tabIndex >= 0 && !element.matches(':disabled, [hidden]') && element.getClientRects().length > 0);
      const first = controls[0], last = controls.at(-1);
      if (!first) { event.preventDefault(); dialog.focus(); return; }
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog)) {
        event.preventDefault(); last!.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    }}
    onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="ui-overlay-content"><header><h2 id={id}>{title}</h2>
      <button type="button" onClick={onClose} aria-label={translate(locale, 'close')}>×</button></header>{children}</div>
  </dialog>;
}
export function Drawer(props: OverlayProps) { return <Overlay {...props} variant="drawer" />; }
export function BottomSheet(props: OverlayProps) { return <Overlay {...props} variant="sheet" />; }
export function Toast({ message, onDismiss, locale = 'ru', tone = 'off' }: Localized & { message: string; onDismiss?: () => void; tone?: Tone }) {
  return <div className="ui-toast" data-tone={tone}><span role="status">{message}</span>
    {onDismiss && <button type="button" onClick={onDismiss} aria-label={translate(locale, 'close')}>×</button>}</div>;
}
export function EmptyState({ title, description, action, locale = 'ru' }: Localized & { title?: string; description?: string; action?: ReactNode }) {
  return <div className="ui-empty"><span aria-hidden="true">—</span><h3>{title ?? translate(locale, 'empty')}</h3>
    <p>{description ?? translate(locale, 'emptyDetail')}</p>{action}</div>;
}
export function Skeleton({ lines = 3, locale = 'ru' }: Localized & { lines?: number }) {
  return <div className="ui-skeleton" role="status" aria-label={translate(locale, 'loading')}>
    {Array.from({ length: Math.max(1, Math.min(10, Math.floor(lines) || 3)) }, (_, i) => <span key={i} aria-hidden="true" />)}
  </div>;
}
export function OfflineBanner({ offline, locale = 'ru' }: Localized & { offline: boolean }) {
  if (!offline) return null;
  return <div className="ui-offline" role="status"><strong>{translate(locale, 'offline')}</strong><span>{translate(locale, 'offlineDetail')}</span></div>;
}
export function AiCard({ title, children, explanation, actions, locale = 'ru' }:
  Localized & { title: string; children: ReactNode; explanation?: ReactNode; actions?: ReactNode }) {
  return <section className="ui-ai-card"><header><span aria-hidden="true">✦</span><h3>{title}</h3></header>
    <div>{children}</div>{explanation && <details><summary>{translate(locale, 'why')}</summary>{explanation}</details>}
    {actions && <div className="ui-ai-actions">{actions}</div>}
  </section>;
}
