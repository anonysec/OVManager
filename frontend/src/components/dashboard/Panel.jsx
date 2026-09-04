// Copyright (c) 2025 anonysec. All rights reserved.
// Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

/**
 * Panel — base card primitive used by all dashboard panels.
 * - `title` rendered next to `icon` (decorative)
 * - `action` is a React node placed in the header right (e.g. tabs, view-all)
 * - `flush` removes body padding so the consumer can render edge-to-edge
 *   (e.g. DataTable, ActivityFeed)
 */
import { useTranslation } from 'react-i18next';
import { FiAlertTriangle, FiRefreshCw } from 'react-icons/fi';
import { EmptyState, PanelSkeleton } from '../ui';

function Panel({ title, icon: Icon, action, flush = false, className = '', children }) {
  return (
    <section className={`ds-card ${className}`}>
      <div className="ds-card-head">
        <h3 className="ds-card-title">
          {Icon && <span className="ds-card-title-icon" aria-hidden="true"><Icon size={14} /></span>}
          {title}
        </h3>
        {action && <div className="ds-card-action">{action}</div>}
      </div>
      <div className={`ds-card-body${flush ? ' ds-card-body--flush' : ''}`}>{children}</div>
    </section>
  );
}

/**
 * PanelState — resolves to skeleton / inline-error / empty / content
 * in that order. The inline error keeps the rest of the dashboard
 * usable instead of swapping it for a wall of red.
 */
export function PanelState({ loading, error, isEmpty, onRetry, skeleton, children, t: tProp }) {
  const { t } = useTranslation();
  const ti = tProp || t;
  if (loading) return skeleton ?? <PanelSkeleton lines={3} label={ti('loading', 'Loading…')} />;
  if (error) {
    return (
      <div className="ds-inline-error" role="alert">
        <FiAlertTriangle aria-hidden="true" />
        <div>
          <strong>{ti('panelLoadFailed', 'Could not load this panel')}</strong>
          <span>{ti('panelLoadFailedHint', 'Other sections are unaffected.')}</span>
        </div>
        {onRetry && (
          <button type="button" className="btn btn-sm btn-secondary" onClick={onRetry} aria-label={ti('retry', 'Retry')}>
            <FiRefreshCw size={12} aria-hidden="true" /> {ti('retry', 'Retry')}
          </button>
        )}
      </div>
    );
  }
  if (isEmpty) return <EmptyState title={ti('noData')} description={ti('noDataDesc')} />;
  return typeof children === 'function' ? children() : children;
}

export { Panel };
export default Panel;