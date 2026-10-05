// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT


import { useTranslation } from 'react-i18next';
import { FiAlertTriangle, FiRefreshCw } from 'react-icons/fi';
import { EmptyState, PanelSkeleton } from '../ui';

function Panel({ title, icon: Icon, action, flush = false, className = '', children }: { title?: any; icon?: any; action?: any; flush?: boolean; className?: string; children?: any }) {
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


export function PanelState({ loading, error, isEmpty, onRetry, skeleton, children }: { loading?: any; error?: any; isEmpty?: any; onRetry?: any; skeleton?: any; children?: any }) {
  const { t } = useTranslation();
  if (loading) return skeleton ?? <PanelSkeleton lines={3} label={t('loading', 'Loading…')} />;
  if (error) {
    return (
      <div className="ds-inline-error" role="alert">
        <FiAlertTriangle aria-hidden="true" />
        <div>
          <strong>{t('panelLoadFailed', 'Could not load this panel')}</strong>
          <span>{t('panelLoadFailedHint', 'Other sections are unaffected.')}</span>
        </div>
        {onRetry && (
          <button type="button" className="btn btn-sm btn-secondary" onClick={onRetry} aria-label={t('retry', 'Retry')}>
            <FiRefreshCw size={12} aria-hidden="true" /> {t('retry', 'Retry')}
          </button>
        )}
      </div>
    );
  }
  if (isEmpty) return <EmptyState title={t('noData')} description={t('noDataDesc')} />;
  return typeof children === 'function' ? children() : children;
}

export { Panel };
export default Panel;