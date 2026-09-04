// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * ServerHealth — row of four resource meters (CPU, Memory, Disk, Load)
 * with a footer for nodes online. Tones are derived from percentage
 * thresholds (CPU/mem 70/85, disk 85). Sparks are optional and shown
 * only if the caller supplies ≥2 points (skipped for load to avoid
 * noisy assumptions about data shape).
 */
import { useTranslation } from 'react-i18next';
import Meter from './Meter';
import Sparkline from './Sparkline';
import Panel, { PanelState } from './Panel';
import { SkeletonStats } from '../ui';

const tonify = (pct) => {
  if (pct > 85) return 'danger';
  if (pct > 70) return 'warn';
  return 'ok';
};

export default function ServerHealth({ stats, traffic, error, loading, onRetry, t: tProp, onlineNodes, totalNodes }) {
  const { t } = useTranslation();
  const cpu = Number(stats?.cpu ?? 0);
  const mem = Number(stats?.memory_percent ?? 0);
  const disk = Number(stats?.disk_percent ?? 0);
  const load = Number(stats?.load_1 ?? stats?.load ?? 0);
  const cpuSpark = (traffic?.conns || []).slice(-24);

  return (
    <Panel
      title={t('serverHealth', 'Server health')}
      icon={null}
    >
      <PanelState
        t={tProp || t}
        loading={loading}
        error={error}
        isEmpty={!stats}
        onRetry={onRetry}
        skeleton={<SkeletonStats count={4} label={t('loading', 'Loading…')} />}
      >
        {stats && (
          <>
            <div className="ds-health-grid">
              <Meter
                label={t('panelCPU', 'CPU')}
                value={`${cpu.toFixed(0)}%`}
                pct={cpu}
                tone={tonify(cpu)}
                spark={cpuSpark}
                ariaSuffix={t(TONE_LABEL(cpu), '')}
              />
              <Meter
                label={t('panelMemory', 'Memory')}
                value={`${mem.toFixed(0)}%`}
                pct={mem}
                tone={tonify(mem)}
                spark={cpuSpark}
              />
              <Meter
                label={t('disk', 'Disk')}
                value={`${disk.toFixed(0)}%`}
                pct={disk}
                tone={disk > 85 ? 'danger' : 'ok'}
                spark={cpuSpark}
              />
              <div className="ds-meter ds-meter--ok">
                <div className="ds-meter-label">
                  <span>{t('load', 'Load')}</span>
                  <span className="ds-meter-value">{load ? load.toFixed(2) : '—'}</span>
                </div>
                <Sparkline values={(traffic?.bytes || []).slice(-24)} tone="info" className="ds-meter-spark" />
              </div>
            </div>
            <div className="ds-health-foot">
              <span className="ds-health-foot-meta">
                {t('nodesOnline', 'Nodes online')}: {onlineNodes}/{totalNodes}
              </span>
            </div>
          </>
        )}
      </PanelState>
    </Panel>
  );
}

const TONE_LABEL = (p) => (p > 85 ? 'critical' : p > 70 ? 'warning' : 'normal');
