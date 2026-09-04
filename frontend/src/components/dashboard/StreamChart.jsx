// Copyright (c) 2025 anonysec. All rights reserved.
// Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

/**
 * StreamChart — real-time area chart fed by /metrics/history.
 *
 * Streaming model:
 *  - Initial load: GET /metrics/history?hours={24|168} populates the series
 *  - Updates: SSE from /metrics/stream appends new points to the series
 *  - If SSE fails / is disabled, polling every 30s provides the same data
 *
 * The chart keeps the latest 240 points (≈ 1h at 15s cadence) to avoid
 * DOM bloat on long sessions. Hover crosshair and tooltip are pure DOM
 * to keep the chart fast.
 */
import { useEffect, useRef, useState, useCallback, useId } from 'react';
import { useTranslation } from 'react-i18next';
import apiClient from '../../services/api';
import { formatBytes } from '../../utils/format';
import { fmtDateTime } from '../../utils/time';
import useEventSource from '../../hooks/useEventSource';
import { Panel } from './Panel';

const MAX_POINTS = 240;
const CHART_HEIGHT = 240;

const tsToIso = (ts) => {
  if (!ts) return null;
  const n = Number(ts);
  if (!Number.isFinite(n)) return null;
  return new Date(n * 1000).toISOString();
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

  // Real-time appends via SSE; ignored if unavailable.
  const { status } = useEventSource('/api/metrics/stream', {
    enabled: !loading && !loadError,
    onMessage: (msg) => {
      if (!msg || typeof msg !== 'object') return;
      setSeries((prev) => {
        const next = [...prev, { ts: msg.ts || Math.floor(Date.now() / 1000), total_used: msg.total_used, active_connections: msg.active_connections }];
        return next.length > MAX_POINTS ? next.slice(-MAX_POINTS) : next;
      });
    },
  });

  // Polling fallback: when SSE is closed or errored, refresh every 30s.
  useEffect(() => {
    if (status === 'open') return undefined;
    const id = setInterval(() => {
      apiClient.get(`/metrics/history?hours=${hours}`)
        .then((r) => {
          const data = r.data?.data?.traffic || [];
          if (data.length) setSeries(data.slice(-MAX_POINTS));
        })
        .catch(() => { /* keep existing */ });
    }, 30000);
    return () => clearInterval(id);
  }, [status, hours]);

  const valueAt = useCallback((p) => Number(metric === 'conns' ? p.active_connections || 0 : p.total_used || 0), [metric]);
  const fmt = useCallback((v) => (metric === 'conns' ? Math.round(Number(v || 0)).toLocaleString() : formatBytes(v)), [metric]);

  const points = (() => {
    if (series.length < 2) return [];
    const vals = series.map(valueAt);
    const max = Math.max(...vals, 1);
    return series.map((p, i) => {
      const x = (i / (series.length - 1)) * 100;
      const y = 100 - (vals[i] / max) * 88 - 6;
      return { x, y, v: vals[i], ts: p.ts };
    });
  })();

  const lastVal = series.length ? valueAt(series[series.length - 1]) : 0;
  const peak = points.length ? Math.max(...points.map((p) => p.v)) : 0;
  const hovered = hoverIdx != null ? points[hoverIdx] : null;
  const isLive = status === 'open';

  const onMove = (e) => {
    if (!svgRef.current || points.length < 2) return;
    const rect = svgRef.current.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    setHoverIdx(Math.round(ratio * (points.length - 1)));
  };

  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ');
  const areaPath = points.length ? `${linePath} L100,100 L0,100 Z` : '';
  const last = points[points.length - 1];

  return (
    <Panel
      title={t('trafficChartTitle', 'Traffic')}
      action={
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
          <span className="ds-chart-meta" aria-live="polite">
            <span className={`ds-chart-status ${isLive ? 'ds-chart-status--live' : loadError ? 'ds-chart-status--error' : ''}`} aria-hidden="true" />
            {isLive ? t('chartLive', 'Live') : loadError ? t('chartOffline', 'Offline') : t('chartPolling', 'Polling')}
          </span>
        </div>
      }
    >
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
                <stop offset="0%" stopColor="var(--info)" stopOpacity="0.32" />
                <stop offset="100%" stopColor="var(--info)" stopOpacity="0" />
              </linearGradient>
            </defs>
            {[20, 40, 60, 80].map((y) => (
              <line key={y} className="ds-chart-grid-line" x1="0" y1={y} x2="100" y2={y} />
            ))}
            {areaPath && <path className="ds-chart-area" d={areaPath} fill={`url(#${gradId})`} />}
            {linePath && <path className="ds-chart-line" d={linePath} vectorEffect="non-scaling-stroke" />}
            {last && <circle className="ds-chart-pulse" cx={last.x} cy={last.y} r="2" key={last.x + last.y} />}
            {hovered && (
              <>
                <line className="ds-chart-hover-line" x1={hovered.x} y1="0" x2={hovered.x} y2="100" />
                <circle className="ds-chart-hover-dot" cx={hovered.x} cy={hovered.y} r="1.5" />
              </>
            )}
          </svg>
          {hovered && (
            <div
              className="ds-chart-tooltip"
              style={{ left: `clamp(48px, ${hovered.x}%, calc(100% - 48px))` }}
            >
              <strong>{fmt(hovered.v)}</strong>
              <span>{fmtDateTime(tsToIso(hovered.ts) || new Date().toISOString())}</span>
            </div>
          )}
          <span className="ds-chart-axis ds-chart-axis--max">{fmt(peak)}</span>
          <span className="ds-chart-axis ds-chart-axis--min">0</span>
          {(loading || loadError || points.length < 2) && (
            <div className="ds-chart-empty">
              {loading ? t('loading', 'Loading…') : loadError ? t('panelLoadFailed', 'Could not load chart') : t('noMetrics', 'No metrics yet')}
            </div>
          )}
        </div>
        <figcaption className="ds-chart-summary">
          <div><b>{fmt(lastVal)}</b><span>{t('trafficNow', 'Current')}</span></div>
          <div><b>{fmt(peak)}</b><span>{t('trafficPeak', 'Peak')}</span></div>
          <div><b>{period === '7d' ? '7' : '24'}h</b><span>{t('trafficWindow', 'Window')}</span></div>
        </figcaption>
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
    </Panel>
  );
}
