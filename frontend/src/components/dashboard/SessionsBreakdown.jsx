// Copyright (c) 2025 anonysec. All rights reserved.
// Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

/**
 * SessionsBreakdown — per-node live session visualization.
 * Each row: name + status dot + proportional bar + count.
 * Total at the bottom. Sorted by live count, then name.
 */
import { useTranslation } from 'react-i18next';
import { Panel, PanelState, EmptyState, PanelSkeleton } from '../ui';
import { nodeMeta } from '../../utils/geo';

const dotClass = (reachable, dbActive) => {
  if (!dbActive) return 'ds-session-dot ds-session-dot--off';
  if (reachable === false) return 'ds-session-dot ds-session-dot--down';
  return 'ds-session-dot';
};

export default function SessionsBreakdown({ nodes, nodeStatus, error, loading, onRetry, t: tProp }) {
  const { t } = useTranslation();
  const rows = (nodes || []).map((n) => {
    const st = nodeStatus?.[n.id] || {};
    const reachable = n.status && (st.reachable === true || (st.reachable === undefined && st.node_info !== undefined));
    return {
      id: n.id,
      name: n.name,
      active: n.status,
      reachable,
      live: Number(st.session_diagnostics?.live_count || 0),
      meta: nodeMeta(n),
    };
  });
  const sortedRows = rows.sort((a, b) => b.live - a.live || a.name.localeCompare(b.name));
  const total = sortedRows.reduce((sum, r) => sum + (r.reachable ? r.live : 0), 0);
  const peak = Math.max(1, ...sortedRows.map((r) => r.live));

  return (
    <Panel title={t('liveSessions', 'Live sessions')} icon={null}>
      <PanelState
        t={tProp || t}
        loading={loading}
        error={error}
        isEmpty={!nodes}
        onRetry={onRetry}
        skeleton={<PanelSkeleton lines={5} label={t('loading', 'Loading…')} />}
      >
        {sortedRows.length > 0 ? (
          <>
            <div className="ds-sessions-list">
              {sortedRows.map((r) => (
                <div key={r.id} className="ds-session-row">
                  <div className="ds-session-name">
                    <span className={dotClass(r.reachable, r.active)} aria-hidden="true" />
                    <strong title={r.meta?.name || r.name}>
                      {r.name}
                      {r.meta?.approximate && <span className="ds-muted"> · {t('approximate', 'approx.')}</span>}
                    </strong>
                  </div>
                  <div className="ds-session-bar" role="meter" aria-valuenow={r.live} aria-valuemin={0} aria-valuemax={peak} aria-label={`${r.name}: ${r.live} ${t('sessions', 'sessions')}`}>
                    <div className="ds-session-bar-fill" style={{ width: `${(r.live / peak) * 100}%` }} />
                  </div>
                  <span className="ds-session-count">{r.live}</span>
                </div>
              ))}
            </div>
            <div className="ds-sessions-total">
              <span>{t('totalConnections', 'Total connections')}</span>
              <strong>{total.toLocaleString()}</strong>
            </div>
          </>
        ) : (
          <EmptyState title={t('noNodes', 'No nodes')} description={t('noNodesDesc')} />
        )}
      </PanelState>
    </Panel>
  );
}
