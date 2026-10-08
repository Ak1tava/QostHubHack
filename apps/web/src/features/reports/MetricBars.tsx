import { useLocale } from '../../ui/locale';
import { useId } from 'react';
import { number } from './data';

export type Metric = { label: string; value: number; text?: string; color?: string };

export function MetricBars({ title, unit, items, caption }: { title: string; unit: string; items: Metric[]; caption?: string }) {
  const { tx } = useLocale();
  const id = useId();
  const maximum = Math.max(0, ...items.map(item => item.value));
  return <figure className="report-panel metric-chart" aria-labelledby={id}>
    <figcaption className="chart-heading"><h3 id={id}>{title}</h3><span className="chart-unit">{unit}</span></figcaption>
    <dl className="metric-rows">{items.map(item => <div className="metric-row" key={item.label}>
      <dt>{item.label}</dt><dd><span className="metric-track" aria-hidden="true"><span className={`metric-fill ${item.color ?? ''}`} style={{ width: `${Math.max(0, item.value) / Math.max(1, maximum) * 100}%` }} /></span><span className="metric-value">{item.text ?? number(item.value)}</span></dd>
    </div>)}</dl><p className="chart-scale">{tx("Общая шкала: от 0 до ")}{items.find(item => item.value === maximum)?.text ?? number(maximum)}{items.some(item => item.text) ? '' : ` ${unit.toLowerCase()}`}</p>
    {caption && <p className="chart-caption">{caption}</p>}
  </figure>;
}
