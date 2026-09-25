// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * StreamChart — area chart fed by /metrics/history with polling refresh.
 *
 * Data model:
 *  - Initial load: GET /metrics/history?hours={24|168} populates the series
 *  - Updates: refresh-cadence polling (single live source is /live/stream
 *    invalidation bus in LiveContext; per-chart SSE was removed to avoid
 *    a second DB-polling stream).
 *
 * The chart keeps the latest 240 points (≈ 1h at 15s cadence) to avoid
 * DOM bloat on long sessions. Hover crosshair and tooltip are pure DOM
 * to keep the chart fast. The component renders bare (no card chrome):
 * the dashboard hero owns the surrounding card.
 */
import { useEffect, useRef, useState, useCallback, useId } from 'react';
import { useTranslation } from 'react-i18next';
import apiClient from '../../services/api';
import { DATA_REFRESH_SEC } from '../../utils/notifPrefs';
import { formatBytes } from '../../utils/format';
import { fmtDateTime } from '../../utils/time';

const MAX_POINTS = 240;

const tsToIso = (ts) => {
  if (!ts) return null;
  const n = Number(ts);
  if (!Number.isFinite(n)) return null;
  return new Date(n * 1000).toISOString();
};

// Catmull-Rom -> cubic Bezier smoothing so spiky traffic reads as a calm
// curve instead of a jagged polyline. Control points are clamped to the
// viewBox so overshoot can never poke above the frame or below zero.
const smoothPath = (pts) => {
  if (pts.length < 2) return '';
  const clamp = (v) => Math.min(100, Math.max(0, v));
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

export default function StreamChart({ period: initialPeriod = '24h', hours: initialHours = 24 }) {
  const { t } = useTranslation();
  const [period, setPeriod] = useState(initialPeriod);
  const [metric, setMetric] = useState('traffic');
  const [series, setSeries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [hoverIdx, setHoverIdx] = useState(null);
  const svgRef = useRef(null);
  const gradId = useId().replace(/:/g, '');

  const hours = period === '7d' ? 168 : initialHours;

  // Initial + period-switch load
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(false);
    setSeries([]);
    apiClient.get(`/metrics/history?hours=${hours}`)
      .then((r) => {
        if (cancelled) return;
        const data = r.data?.data?.traffic || [];
        setSeries(data.slice(-MAX_POINTS));
      })
      .catch(() => { if (!cancelled) setLoadError(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [hours]);

  // Refresh on the user's dashboard cadence so the chart stays current
  // without a second SSE stream.
  useEffect(() => {
    const id = setInterval(() => {
      apiClient.get(`/metrics/history?hours=${hours}`)
        .then((r) => {
          const data = r.data?.data?.traffic || [];
          if (data.length) setSeries(data.slice(-MAX_POINTS));
        })
        .catch(() => { /* keep existing */ });
    }, DATA_REFRESH_SEC * 1000);
    return () => clearInterval(id);
  }, [hours]);

  const valueAt = useCallback((p) => Number(metric === 'conns' ? p.active_connections || 0 : p.total_used || 0), [metric]);
  const fmt = useCallback((v) => (metric === 'conns' ? Math.round(Number(v || 0)).toLocaleString() : formatBytes(v)), [metric]);

  const points = (() => {
    if (series.length < 2) return [];
    const vals = series.map(valueAt);
    const max = Math.max(...vals, 1);
    return series.map((p, i) => {
      const x = 2 + (i / (series.length - 1)) * 96;
      const y = 100 - (vals[i] / max) * 88 - 6;
      return { x, y, v: vals[i], ts: p.ts };
    });
  })();

  const lastVal = series.length ? valueAt(series[series.length - 1]) : 0;
  const peak = points.length ? Math.max(...points.map((p) => p.v)) : 0;
  const hovered = hoverIdx != null ? points[hoverIdx] : null;

  const onMove = (e) => {
    if (!svgRef.current || points.length < 2) return;
    const rect = svgRef.current.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    setHoverIdx(Math.round(ratio * (points.length - 1)));
  };

  const linePath = smoothPath(points);
  // All-zero data draws no curve — the overlay message explains instead.
  const hasCurve = points.length > 1 && peak > 0;
  const areaPath = hasCurve ? `${linePath} L100,100 L0,100 Z` : '';
  const last = points[points.length - 1];
  const halfVal = peak / 2;
  const firstTs = series.length ? tsToIso(series[0].ts) : null;

  return (
    <div className="ds-chart-embed">
      <div className="ds-chart-head">
        <div className="ds-chart-controls">
          <div className="ds-segmented" role="group" aria-label={t('trafficChartMetric', 'Metric')}>
            <button type="button" className={metric === 'traffic' ? 'active' : ''} aria-pressed={metric === 'traffic'} onClick={() => setMetric('traffic')}>
              {t('chartMetricTraffic', 'Traffic')}
            </button>
            <button type="button" className={metric === 'conns' ? 'active' : ''} aria-pressed={metric === 'conns'} onClick={() => setMetric('conns')}>
              {t('chartMetricConns', 'Sessions')}
            </button>
          </div>
          <div className="ds-segmented" role="group" aria-label={t('trafficChartPeriod', 'Period')}>
            <button type="button" className={period === '24h' ? 'active' : ''} aria-pressed={period === '24h'} onClick={() => setPeriod('24h')}>24h</button>
            <button type="button" className={period === '7d' ? 'active' : ''} aria-pressed={period === '7d'} onClick={() => setPeriod('7d')}>7d</button>
          </div>
        </div>
        <span className="ds-chart-inline-stats">
          <span>{t('trafficNow', 'Now')} <b>{fmt(lastVal)}</b></span>
          <span>{t('trafficPeak', 'Peak')} <b>{fmt(peak)}</b></span>
          <span className={`ds-chart-status ${loadError ? 'ds-chart-status--error' : ''}`} aria-hidden="true" />
          <span aria-live="polite">{loadError ? t('chartOffline', 'Offline') : t('chartPolling', 'Polling')}</span>
        </span>
      </div>
      <figure className="ds-chart-figure">
        <div className="ds-chart-wrap">
          <svg
            ref={svgRef}
            className="ds-chart-svg"
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            aria-hidden="true"
            onMouseMove={onMove}
            onMouseLeave={() => setHoverIdx(null)}
          >
            <defs>
              <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--accent-color, var(--info))" stopOpacity="0.30" />
                <stop offset="60%" stopColor="var(--accent-color, var(--info))" stopOpacity="0.08" />
                <stop offset="100%" stopColor="var(--accent-color, var(--info))" stopOpacity="0" />
              </linearGradient>
            </defs>
            {[25, 50, 75].map((y) => (
              <line key={y} className="ds-chart-grid-line" x1="0" y1={y} x2="100" y2={y} />
            ))}
            {areaPath && <path className="ds-chart-area" d={areaPath} fill={`url(#${gradId})`} />}
            {hasCurve && <path className="ds-chart-line" d={linePath} vectorEffect="non-scaling-stroke" />}
            {hovered && (
              <line className="ds-chart-hover-line" x1={hovered.x} y1="0" x2={hovered.x} y2="100" />
            )}
          </svg>
          {/* The current point is a DOM dot — an SVG circle would stretch into
              an ellipse under preserveAspectRatio="none". */}
          {hasCurve && last && (
            <span className="ds-chart-live-dot" style={{ left: `${last.x}%`, top: `${last.y}%` }} aria-hidden="true" />
          )}
          {hovered && (
            <div
              className="ds-chart-tooltip"
              style={{ left: `clamp(48px, ${hovered.x}%, calc(100% - 48px))` }}
            >
              <strong><i className="ds-chart-tip-dot" aria-hidden="true" />{fmt(hovered.v)}</strong>
              <span>{fmtDateTime(tsToIso(hovered.ts) || new Date().toISOString())}</span>
            </div>
          )}
          <span className="ds-chart-axis ds-chart-axis--max">{fmt(peak)}</span>
          {points.length > 1 && <span className="ds-chart-axis ds-chart-axis--mid">{fmt(halfVal)}</span>}
          <span className="ds-chart-axis ds-chart-axis--min">0</span>
          {firstTs && <span className="ds-chart-axis ds-chart-axis--t0">{fmtDateTime(firstTs)}</span>}
          {(loading || loadError || points.length < 2 || (!loadError && peak === 0)) && (
            <div className="ds-chart-empty">
              {loading
                ? t('loading', 'Loading…')
                : loadError
                  ? t('panelLoadFailed', 'Could not load chart')
                  : t('noTrafficYet', 'No traffic yet — the graph fills in as clients connect')}
            </div>
          )}
        </div>
        <details>
          <summary className="ds-chart-data-toggle">{t('chartDataTable', 'Data table')}</summary>
          <div className="ds-chart-data" style={{ maxHeight: 240, overflow: 'auto', marginTop: 8 }}>
            <table className="dt-table">
              <thead>
                <tr>
                  <th scope="col">{t('th_lastOnline', 'Time')}</th>
                  <th scope="col">{metric === 'conns' ? t('th_sessions', 'Sessions') : t('totalTraffic', 'Traffic')}</th>
                </tr>
              </thead>
              <tbody>
                {series.slice(-48).map((p, i) => (
                  <tr key={p.ts ?? i}>
                    <td className="dt-num">{fmtDateTime(tsToIso(p.ts) || '')}</td>
                    <td className="dt-num">{fmt(valueAt(p))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </figure>
    </div>
  );
}
