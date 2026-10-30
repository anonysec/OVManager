// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT


import { useEffect, useRef, useState, useCallback, useId, useLayoutEffect, useMemo } from 'react';
import type { MouseEvent as ChartMouseEvent } from 'react';
import { useTranslation } from 'react-i18next';
import apiClient from '../../services/api';
import { DATA_REFRESH_SEC } from '../../utils/notifPrefs';
import { formatBytes } from '../../utils/format';
import { fmtDateTime } from '../../utils/time';

/**
 * Dashboard traffic chart.
 *
 * The API reports `total_used` as a cumulative counter, so the chart plots
 * per-bucket transfers (sum of positive counter deltas — counter resets from
 * user deletions simply contribute 0 for that bucket) and, for sessions, the
 * peak concurrent count per bucket. Buckets are built client-side so the
 * whole requested window is always shown: 48 half-hour buckets for 24h,
 * 56 three-hour buckets for 7d.
 */
type RawPoint = { ts?: number | string | null; total_used?: number | null; active_connections?: number | null };
type Bucket = { ts: number; traffic: number; conns: number };

const N_BUCKETS = { '24h': 48, '7d': 56 } as const;
const WINDOW_MS = { '24h': 24 * 3600e3, '7d': 7 * 24 * 3600e3 } as const;

const tsMs = (ts: number | string | null | undefined) => {
  const n = Number(ts);
  return Number.isFinite(n) && n > 0 ? n * 1000 : null;
};

const buildBuckets = (raw: RawPoint[], period: '24h' | '7d'): Bucket[] => {
  const points = raw
    .map((p) => ({ ts: tsMs(p.ts), used: Number(p.total_used || 0), conns: Number(p.active_connections || 0) }))
    .filter((p) => p.ts != null)
    .sort((a, b) => (a.ts as number) - (b.ts as number));
  if (points.length < 2) return [];
  const n = N_BUCKETS[period];
  const end = points[points.length - 1].ts as number;
  const start = end - WINDOW_MS[period];
  const width = WINDOW_MS[period] / n;
  const buckets: Bucket[] = Array.from({ length: n }, (_, i) => ({ ts: start + i * width, traffic: 0, conns: 0 }));
  const idxAt = (ts: number) => Math.min(n - 1, Math.max(0, Math.floor((ts - start) / width)));
  for (let i = 0; i < points.length; i++) {
    const cur = points[i];
    const idx = idxAt(cur.ts as number);
    if (i > 0) {
      // Transfer in this bucket: positive counter deltas only.
      const d = cur.used - points[i - 1].used;
      if (d > 0) buckets[idx].traffic += d;
    }
    // Sessions: peak concurrent within the bucket.
    if (cur.conns > buckets[idx].conns) buckets[idx].conns = cur.conns;
  }
  return buckets;
};

const smoothPath = (pts: Array<{ x: number; y: number }>) => {
  if (pts.length < 2) return '';
  const clamp = (v: number) => Math.min(100, Math.max(0, v));
  let d = `M${pts[0].x.toFixed(2)},${pts[0].y.toFixed(2)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[Math.min(pts.length - 1, i + 2)];
    const c1x = p1.x + (p2.x - p0.x) / 6;
    const c1y = clamp(p1.y + (p2.y - p0.y) / 6);
    const c2x = p2.x - (p3.x - p1.x) / 6;
    const c2y = clamp(p2.y - (p3.y - p1.y) / 6);
    d += ` C${c1x.toFixed(2)},${c1y.toFixed(2)} ${c2x.toFixed(2)},${c2y.toFixed(2)} ${p2.x.toFixed(2)},${p2.y.toFixed(2)}`;
  }
  return d;
};

export default function StreamChart({ period: initialPeriod = '24h' }: { period?: '24h' | '7d' }) {
  const { t } = useTranslation();
  const [period, setPeriod] = useState<'24h' | '7d'>(initialPeriod);
  const [metric, setMetric] = useState<'traffic' | 'conns'>('traffic');
  const [series, setSeries] = useState<RawPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const [tipW, setTipW] = useState(0);
  const tipRef = useRef<HTMLDivElement | null>(null);
  const gradId = useId().replace(/:/g, '');

  const load = useCallback((quiet = false, isStale: () => boolean = () => false) => {
    if (!quiet) setLoading(true);
    setLoadError(false);
    return apiClient.get(`/metrics/history?hours=${period === '7d' ? 168 : 24}`)
      .then((r) => {
        if (isStale()) return;
        const data: RawPoint[] = r.data?.data?.traffic || [];
        if (isStale()) return;
        setSeries(data);
      })
      .catch(() => { if (!isStale()) { setLoadError(true); setSeries([]); } })
      .finally(() => { if (!quiet && !isStale()) setLoading(false); });
  }, [period]);

  useEffect(() => {
    let cancelled = false;
    setSeries([]);
    load(false, () => cancelled).catch(() => {});
    return () => { cancelled = true; };
  }, [load]);

  useEffect(() => {
    const id = setInterval(() => { load(true).catch(() => {}); }, DATA_REFRESH_SEC * 1000);
    return () => clearInterval(id);
  }, [load]);

  const buckets = useMemo(() => buildBuckets(series, period), [series, period]);
  const isTraffic = metric === 'traffic';
  const vals = buckets.map((b) => (isTraffic ? b.traffic : b.conns));
  const peak = vals.length ? Math.max(...vals) : 0;
  const total = vals.reduce((a, b) => a + b, 0);
  const avg = vals.length ? total / vals.length : 0;
  const latest = vals.length ? vals[vals.length - 1] : 0;
  const peakIdx = vals.length ? vals.indexOf(peak) : -1;

  const fmt = useCallback((v: number) => (isTraffic ? formatBytes(v) : Math.round(Number(v || 0)).toLocaleString()), [isTraffic]);
  const fmtAxis = useCallback(
    (v: number) => (isTraffic ? formatBytes(v) : `${Math.round(Number(v || 0)).toLocaleString()} ${t('chartUnitSessions', 'sessions')}`),
    [isTraffic, t],
  );

  const connsVals = useMemo(() => {
    // Sessions buckets with no samples carry the previous peak — a gauge must
    // not drop to zero just because the collector skipped a window.
    let carried = 0;
    const out: number[] = [];
    for (const b of buckets) {
      if (b.conns) carried = b.conns;
      out.push(carried);
    }
    return out;
  }, [buckets]);
  const plotVals = isTraffic ? vals : connsVals;
  const plotPeak = plotVals.length ? Math.max(...plotVals, 1) : 1;

  const points = plotVals.map((v, i) => ({
    x: buckets.length > 1 ? (i / (buckets.length - 1)) * 100 : 0,
    y: 100 - (v / plotPeak) * 94 - 3,
    v,
  }));
  const lastPt = points[points.length - 1];
  const hasSeries = points.length > 1 && peak > 0;

  const hovered = hoverIdx != null && buckets[hoverIdx] ? hoverIdx : null;
  const hoverPct = hovered != null && buckets.length > 1 ? (hovered / (buckets.length - 1)) * 100 : 0;

  useLayoutEffect(() => {
    if (hovered != null && tipRef.current) setTipW(tipRef.current.offsetWidth);
  }, [hovered]);

  const onMove = (e: ChartMouseEvent<HTMLDivElement>) => {
    const host = e.currentTarget;
    if (!buckets.length) return;
    const rect = host.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    setHoverIdx(Math.min(buckets.length - 1, Math.floor(ratio * buckets.length)));
  };

  const linePath = smoothPath(points);
  const areaPath = hasSeries
    ? `${linePath} L${lastPt.x.toFixed(2)},100 L${points[0].x.toFixed(2)},100 Z`
    : '';

  const tickIdx = useMemo(() => {
    if (buckets.length < 2) return [];
    return [...new Set([0, Math.floor(buckets.length / 3), Math.floor((2 * buckets.length) / 3), buckets.length - 1])];
  }, [buckets.length]);

  const tickFmt = (ts: number) =>
    isTraffic
      ? fmtDateTime(new Date(ts).toISOString(), { year: undefined, month: undefined, day: undefined })
      : fmtDateTime(new Date(ts).toISOString(), { hour: undefined, minute: undefined });

  const windowLabel = period === '7d'
    ? t('chartWindow7d', 'Last 7 days')
    : t('chartWindow24h', 'Last 24 hours');
  const isEmpty = loading || loadError || buckets.length < 2 || peak === 0;

  return (
    <div className="ds-chart-embed">
      <div className="ds-chart-head">
        <div className="ds-chart-title">
          <span className="ds-chart-title-icon" aria-hidden="true">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="3 17 9 11 13 15 21 7" />
              <polyline points="15 7 21 7 21 13" />
            </svg>
          </span>
          <div>
            <h2 className="ds-chart-title-text">{isTraffic ? t('chartMetricTraffic', 'Traffic') : t('chartMetricConns', 'Sessions')}</h2>
            <p className="ds-chart-title-sub">{windowLabel}</p>
          </div>
        </div>
        <div className="ds-chart-controls">
          <div className="ds-segmented" role="group" aria-label={t('trafficChartMetric', 'Metric')}>
            <button type="button" className={isTraffic ? 'active' : ''} aria-pressed={isTraffic} onClick={() => setMetric('traffic')}>
              {t('chartMetricTraffic', 'Traffic')}
            </button>
            <button type="button" className={`ds-hide-mobile${metric === 'conns' ? ' active' : ''}`} aria-pressed={!isTraffic} onClick={() => setMetric('conns')}>
              {t('chartMetricConns', 'Sessions')}
            </button>
          </div>
          <div className="ds-segmented" role="group" aria-label={t('trafficChartPeriod', 'Period')}>
            <button type="button" className={period === '24h' ? 'active' : ''} aria-pressed={period === '24h'} onClick={() => setPeriod('24h')}>{t('chartPeriod24h', '24h')}</button>
            <button type="button" className={`ds-hide-mobile${period === '7d' ? ' active' : ''}`} aria-pressed={period === '7d'} onClick={() => setPeriod('7d')}>{t('chartPeriod7d', '7d')}</button>
          </div>
        </div>
      </div>

      <div className="ds-chart-inline-stats">
        <span className="ds-chart-stat">
          <span>{isTraffic ? t('chartTotal', 'Total') : t('trafficPeak', 'Peak')}</span>
          <b>{fmt(isTraffic ? total : peak)}</b>
        </span>
        <span className="ds-chart-stat">
          <span>{isTraffic ? t('trafficPeak', 'Peak') : t('chartAvg', 'Average')}</span>
          <b title={peakIdx >= 0 ? fmtDateTime(new Date(buckets[peakIdx].ts).toISOString()) : undefined}>
            {fmt(isTraffic ? peak : avg)}
          </b>
        </span>
        <span className="ds-chart-stat">
          <span>{t('trafficNow', 'Current')}</span>
          <b>{fmt(latest)}</b>
        </span>
        <span className={`ds-chart-badge ${loadError ? 'ds-chart-badge--offline' : 'ds-chart-badge--live'}`} aria-live="polite">
          <span className="ds-chart-badge-dot" aria-hidden="true" />
          {loadError ? t('chartOffline', 'Offline') : t('chartLive', 'Live')}
        </span>
      </div>

      <figure className="ds-chart-figure">
        <div className={`ds-chart-wrap${isEmpty ? ' is-empty' : ''}`}>
          {/* Plot box reserves the axis gutters; bars, svg, live dot and
              tooltip share its coordinate space so % positions stay in sync. */}
                  <div className="ds-chart-plot" role="img" tabIndex={0} aria-label={t('trafficChart', 'Traffic chart')} onMouseMove={onMove} onMouseLeave={() => setHoverIdx(null)} onKeyDown={(e) => { if (!buckets.length) return; if (e.key === 'ArrowRight') { e.preventDefault(); setHoverIdx((i) => Math.min(buckets.length - 1, (i ?? -1) + 1)); } else if (e.key === 'ArrowLeft') { e.preventDefault(); setHoverIdx((i) => Math.max(0, (i ?? 1) - 1)); } else if (e.key === 'Escape') { setHoverIdx(null); } }}>
            <svg className="ds-chart-svg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              <defs>
                <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--accent-color, var(--info))" stopOpacity="0.26" />
                  <stop offset="70%" stopColor="var(--accent-color, var(--info))" stopOpacity="0.05" />
                  <stop offset="100%" stopColor="var(--accent-color, var(--info))" stopOpacity="0" />
                </linearGradient>
              </defs>
              {[0, 25, 50, 75, 100].map((y) => (
                <line key={y} className="ds-chart-grid-line" x1="0" y1={y} x2="100" y2={y} />
              ))}
              {!isTraffic && areaPath && <path className="ds-chart-area" d={areaPath} fill={`url(#${gradId})`} />}
              {!isTraffic && hasSeries && <path className="ds-chart-line" d={linePath} vectorEffect="non-scaling-stroke" />}
            </svg>

            {isTraffic && (
              <div className="ds-chart-bars" aria-hidden="true">
                {plotVals.map((v, i) => (
                  <span
                    key={i}
                    className={`ds-chart-bar${hovered === i ? ' is-hover' : ''}${hasSeries && i === plotVals.length - 1 ? ' is-live' : ''}`}
                    style={{ height: v > 0 ? `${Math.max(2, (v / plotPeak) * 100)}%` : '0%' }}
                  />
                ))}
              </div>
            )}

            {!isTraffic && hasSeries && lastPt && (
              <span className="ds-chart-live-dot" style={{ left: `${lastPt.x}%`, top: `${lastPt.y}%` }} aria-hidden="true" />
            )}

            {hovered != null && (
              <span className="ds-chart-hover-line" style={{ left: `${hoverPct}%` }} aria-hidden="true" />
            )}

            {hovered != null && (
              <div
                ref={tipRef}
                className="ds-chart-tooltip"
                style={{ left: `clamp(${tipW / 2}px, ${hoverPct}%, calc(100% - ${tipW / 2}px))` }}
              >
                <strong><i className="ds-chart-tip-dot" aria-hidden="true" />{fmt(plotVals[hovered] || 0)}</strong>
                <span>{fmtDateTime(new Date(buckets[hovered].ts).toISOString())}</span>
              </div>
            )}
          </div>

          <div className="ds-chart-ylabels" aria-hidden="true">
            <span>{fmtAxis(plotPeak)}</span>
            <span>{fmtAxis(plotPeak / 2)}</span>
            <span>{fmtAxis(0)}</span>
          </div>
          <div className="ds-chart-xlabels" aria-hidden="true">
            {tickIdx.map((i) => (
              <span key={i}>{tickFmt(buckets[i].ts)}</span>
            ))}
          </div>

          {isEmpty && (
            <div className="ds-chart-empty">
              {loading
                ? t('loading', 'Loading…')
                : loadError
                  ? t('panelLoadFailed', 'Could not load this panel')
                  : t('noTrafficYet', 'No traffic yet — the graph fills in as clients connect')}
            </div>
          )}
        </div>
      </figure>
    </div>
  );
}
