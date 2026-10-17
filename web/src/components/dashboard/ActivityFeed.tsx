// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT


import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { EmptyState, PanelSkeleton } from '../ui';
import { Panel, PanelState } from './Panel';
import { fmtDateTime, fmtRelative } from '../../utils/time';

const actionTone = (action: any) => {
  if (!action) return '';
  if (action.startsWith('user.delete')) return 'danger';
  if (action.startsWith('user.disable') || action.startsWith('node.disable')) return 'warning';
  if (action.startsWith('user.create') || action.startsWith('user.enable') || action.startsWith('node.enable')) return 'ok';
  return '';
};

export default function ActivityFeed({ items, error, loading, onRetry }: { items?: any; error?: any; loading?: any; onRetry?: any; t?: any }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const rows: any[] = (items || []).slice(0, 8);

  return (
    <Panel
      title={t('activityLogCard', 'Recent activity')}
      icon={null}
      action={
        <button type="button" className="btn btn-sm btn-secondary" onClick={() => navigate('/audit')}>
          {t('viewAll', 'View all')}
        </button>
      }
      flush
    >
      <PanelState
        loading={loading}
        error={error}
        isEmpty={!items}
        onRetry={onRetry}
        skeleton={<PanelSkeleton lines={5} label={t('loading', 'Loading…')} />}
      >
        {rows.length > 0 ? (
          <div className="ds-feed">
            {rows.map((e: any) => {
              const actor = e.actor || e.username || 'system';
              const initial = String(actor).slice(0, 1).toUpperCase();
              const tsIso = e.ts ? new Date(e.ts * 1000).toISOString() : null;
              return (
                <div key={e.id || `${e.ts}-${e.action}-${e.target}`} className="ds-feed-item">
                  <span className="ds-feed-avatar" aria-hidden="true">{initial}</span>
                  <span className={`ds-feed-action ${actionTone(e.action) ? `ds-feed-action--${actionTone(e.action)}` : ''}`}>{e.action}</span>
                  <div className="ds-feed-body">
                    <span className="ds-feed-actor">{actor}</span>
                    {e.target && (
                      <>
                        <span className="ds-feed-arrow" aria-hidden="true">→</span>
                        <span className="ds-feed-target">{e.target}</span>
                      </>
                    )}
                  </div>
                  {tsIso && (
                    <time className="ds-feed-time" dateTime={tsIso} title={fmtDateTime(tsIso)}>
                      {fmtRelative(tsIso)}
                    </time>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <div style={{ padding: 20 }}>
            <EmptyState
              title={t('noActivity', 'No activity yet')}
              description={t('activityWillAppear', 'Actions will appear here.')}
            />
          </div>
        )}
      </PanelState>
    </Panel>
  );
}
