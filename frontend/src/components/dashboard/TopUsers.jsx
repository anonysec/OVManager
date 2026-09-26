// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * TopUsers — highest-billed users over the last N days
 * (GET /users/traffic/top, tenancy-aware: admins get their own users).
 */
import { useTranslation } from 'react-i18next';
import { EmptyState, Panel, PanelSkeleton, PanelState } from '../ui';
import { formatBytes } from '../../utils/format';

export default function TopUsers({ items, error, loading, onRetry, t: tProp }) {
  const { t } = useTranslation();
  const rows = (items || []).slice(0, 5);
  const max = Math.max(1, ...rows.map((r) => r.bytes || 0));

  return (
    <Panel title={t('topUsersCard', 'Top traffic — last 7 days')} icon={null} flush>
      <PanelState
        t={tProp || t}
        loading={loading}
        error={error}
        onRetry={onRetry}
        skeleton={<PanelSkeleton lines={5} label={t('loading', 'Loading…')} />}
      >
        {rows.length > 0 ? (
          <div className="ds-topusers">
            {rows.map((r) => (
              <div key={r.name} className="ds-topusers-row">
                <span className="ds-topusers-name" title={r.name}>{r.name}</span>
                <span className="ds-topusers-bar" aria-hidden="true">
                  <span
                    className="ds-topusers-fill"
                    style={{ width: `${Math.round(((r.bytes || 0) / max) * 100)}%` }}
                  />
                </span>
                <span className="ds-topusers-bytes">{formatBytes(r.bytes || 0)}</span>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ padding: 20 }}>
            <EmptyState
              title={t('topUsersEmpty', 'No traffic recorded yet')}
              description={t('topUsersEmptyDesc', 'Once users start connecting, the heaviest will show up here.')}
            />
          </div>
        )}
      </PanelState>
    </Panel>
  );
}
