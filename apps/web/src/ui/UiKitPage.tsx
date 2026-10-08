import { useState } from 'react';
import { Link } from 'react-router';
import { AiCard, BigActionButton, BottomSheet, DeadlineBar, Drawer, EmptyState, KpiTile, OfflineBanner, PriorityChip, ReasonChips, Skeleton, StatusBadge, StatusDot, Toast } from './components';
import { useUiPreferences, type MessageKey } from './i18n';
import { describeStatus, statusCatalog, type StatusDomain } from './status';
import './ui-kit.css';

export function UiKitPage() {
  const { locale, setLocale, theme, setTheme, t } = useUiPreferences();
  const [overlay, setOverlay] = useState<'drawer' | 'sheet' | null>(null);
  const [reason, setReason] = useState('');
  const [toast, setToast] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const options = [{ value: 'parts', label: t('parts') }, { value: 'access', label: t('access') }, { value: 'help', label: t('help') }];
  const domains: { domain: StatusDomain; title: MessageKey }[] = [
    { domain: 'order', title: 'orders' }, { domain: 'availability', title: 'people' },
    { domain: 'priority', title: 'priorities' }, { domain: 'verdict', title: 'verdicts' },
  ];
  function previewAction() { setToast(true); }
  return <div className="ui-kit" data-theme={theme} lang={locale}>
    <a className="skip-link" href="#ui-content">{t('title')}</a>
    <header className="kit-header"><Link to="/" className="kit-brand" aria-label={t('back')}><span className="kit-brand-mark" aria-hidden="true">Н</span><span>Наряд<span>AI</span></span></Link>
      <div className="kit-controls">
        <div className="kit-segmented" role="group" aria-label={t('language')}>
          <button type="button" lang="ru" aria-pressed={locale === 'ru'} onClick={() => setLocale('ru')}>RU</button>
          <button type="button" lang="kk" aria-pressed={locale === 'kk'} onClick={() => setLocale('kk')}>KZ</button>
        </div>
        <div className="kit-segmented" role="group" aria-label={t('theme')}>
          <button type="button" aria-pressed={theme === 'light'} onClick={() => setTheme('light')}>{t('light')}</button>
          <button type="button" aria-pressed={theme === 'dark'} onClick={() => setTheme('dark')}>{t('dark')}</button>
        </div>
      </div>
    </header>
    <main id="ui-content" className="kit-content">
      <section className="kit-hero"><div><p className="kit-eyebrow">{t('eyebrow')}</p><h1>{t('title')}</h1><p>{t('subtitle')}</p>
        <span className="kit-demo-label">{t('demo')}</span></div><div className="kit-hero-note"><span>01 / UI</span><strong>НарядAI</strong><p>{t('typeSample')}</p></div>
      </section>
      <section className="kit-kpis" aria-label={t('kpis')}>
        <KpiTile label={t('issued')} value="24" /><KpiTile label={t('active')} value="7" />
        <KpiTile label={t('closed')} value="15" /><KpiTile label={t('overdueLabel')} value="3" tone="danger" />
      </section>
      <div className="kit-grid">
        <section className="kit-panel kit-wide"><div className="kit-section-heading"><span>01</span><div><h2>{t('palette')}</h2><p>{t('paletteDetail')}</p></div></div>
          <div className="kit-swatches">{([
            ['background', 'bg'], ['surface', 'surface'], ['primary', 'primary'], ['accent', 'accent'],
          ] as const).map(([key, token]) => <div className="kit-swatch" key={token}><span style={{ background: `var(--${token})` }} /><strong>{t(key)}</strong><small>--{token}</small></div>)}</div>
        </section>
        <section className="kit-panel kit-wide"><div className="kit-section-heading"><span>02</span><h2>{t('states')}</h2></div>
          <div className="kit-status-groups">{domains.map(({ domain, title }) => <div className="kit-status-group" key={domain}><h3>{t(title)}</h3><div className="kit-badge-list">
            {Object.keys(statusCatalog[domain]).map(status => domain === 'priority'
              ? <PriorityChip key={status} priority={status as keyof typeof statusCatalog.priority} locale={locale} />
              : <StatusBadge key={status} domain={domain} status={status} locale={locale} />)}
          </div></div>)}</div>
          <div className="kit-status-extra"><StatusBadge domain="order" status="PAUSED" overdue locale={locale} />
            <StatusDot tone="ok" label={describeStatus('availability', 'free', locale).label} /></div>
        </section>
        <section className="kit-panel"><div className="kit-section-heading"><span>03</span><h2>{t('actions')}</h2></div>
          <div className="kit-actions"><BigActionButton onClick={previewAction}>{t('issue')}</BigActionButton>
            <BigActionButton variant="secondary" onClick={previewAction}>{t('continue')}</BigActionButton>
            <BigActionButton variant="danger" onClick={previewAction}>{t('cancel')}</BigActionButton>
            <BigActionButton pending locale={locale}>{t('pendingExample')}</BigActionButton>
            <BigActionButton disabled>{t('disabledExample')}</BigActionButton>
          </div><ReasonChips label={t('reason')} options={options} value={reason} onChange={setReason} />
        </section>
        <section className="kit-panel"><div className="kit-section-heading"><span>04</span><h2>{t('deadlines')}</h2></div>
          <div className="kit-deadlines">{([
            ['comfortable', 5400, false], ['near', 2400, false], ['urgent', 600, false], ['overdueLabel', -2700, true],
          ] as const).map(([label, seconds, overdue]) => <div key={label}><h3>{t(label)}</h3><DeadlineBar remainingSeconds={seconds} totalSeconds={7200} overdue={overdue} locale={locale} /></div>)}
            <DeadlineBar remainingSeconds={NaN} totalSeconds={0} overdue={false} locale={locale} />
          </div>
        </section>
        <section className="kit-panel"><div className="kit-section-heading"><span>05</span><h2>{t('type')}</h2></div>
          <p className="kit-type-sample">{t('typeSample')}</p><p className="kit-alphabet">{t('typeDetail')}</p>
          <div className="kit-number-samples"><div><span>{t('numberLabel')}</span><strong>№ 0147</strong></div><div><span>{t('dueLabel')}</span><strong>01:42:08</strong></div></div>
        </section>
        <div className="kit-ai"><AiCard title={t('aiTitle')} locale={locale} explanation={<p>{t('aiWhy')}</p>}
          actions={<BigActionButton variant="secondary" onClick={() => setOverlay('drawer')}>{t('details')}</BigActionButton>}>
          <StatusBadge domain="verdict" status="human_review" locale={locale} /><p>{t('aiExample')}</p><p className="ui-caption">{t('aiLimit')}</p>
        </AiCard></div>
        <section className="kit-panel"><div className="kit-section-heading"><span>06</span><h2>{t('overlays')}</h2></div>
          <div className="kit-actions"><BigActionButton variant="secondary" onClick={() => setOverlay('drawer')}>{t('drawer')}</BigActionButton>
            <BigActionButton variant="secondary" onClick={() => setOverlay('sheet')}>{t('sheet')}</BigActionButton></div>
        </section>
        <section className="kit-panel"><div className="kit-section-heading"><span>07</span><h2>{t('feedback')}</h2></div>
          <Toast message={t('toastMessage')} locale={locale} /><div className="kit-feedback-controls"><button type="button" onClick={() => setToast(true)}>{t('toast')}</button></div>
          <div key={highlight} className={highlight ? 'kit-update ui-updated' : 'kit-update'}><StatusDot tone="queue" label={t('statusUpdated')} /></div>
          <button type="button" onClick={() => setHighlight(value => value + 1)}>{t('highlight')}</button>
        </section>
        <section className="kit-panel"><div className="kit-section-heading"><span>08</span><h2>{t('emptyHeading')}</h2></div><EmptyState locale={locale} /></section>
        <section className="kit-panel"><div className="kit-section-heading"><span>09</span><h2>{t('skeletonHeading')}</h2></div><Skeleton locale={locale} />
          <h3>{t('offlineHeading')}</h3><OfflineBanner offline locale={locale} /></section>
      </div>
      <footer className="kit-footer"><span>{t('footer')}</span><span>{t('localizationNote')}</span><Link to="/">{t('back')} →</Link></footer>
    </main>
    <Drawer open={overlay === 'drawer'} onClose={() => setOverlay(null)} title={t('drawerTitle')} locale={locale}>
      <p className="kit-demo-label">{t('demo')}</p><h3>{t('sampleOrder')}</h3><StatusBadge domain="order" status="IN_PROGRESS" locale={locale} />
      <p>{t('sampleDescription')}</p><BigActionButton variant="secondary" onClick={() => setOverlay(null)}>{t('close')}</BigActionButton>
    </Drawer>
    <BottomSheet open={overlay === 'sheet'} onClose={() => setOverlay(null)} title={t('sheetTitle')} locale={locale}>
      <ReasonChips label={t('reason')} options={options} value={reason} onChange={setReason} />
      <div className="kit-sheet-action"><BigActionButton variant="secondary" onClick={() => setOverlay(null)}>{t('close')}</BigActionButton></div>
    </BottomSheet>
    {toast && <div className="kit-toast"><Toast message={t('toastMessage')} onDismiss={() => setToast(false)} locale={locale} /></div>}
  </div>;
}
