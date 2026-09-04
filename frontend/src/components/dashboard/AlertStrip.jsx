// Copyright (c) 2025 anonysec. All rights reserved.
// Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

/**
 * AlertStrip — horizontal pill list of actionable alerts.
 * Each pill deep-links to its target. Past two items collapse into a
 * "+N more" overflow pill that opens the first overflow target.
 */
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { FiAlertTriangle, FiCheckCircle } from 'react-icons/fi';

export default function AlertStrip({ items, onClear }) {
  const navigate = useNavigate();
  const { t } = useTranslation();

  if (!items || items.length === 0) {
    return (
      <div className="ds-alerts ds-alerts--clear" role="status" aria-live="polite">
        <span className="ds-alerts-icon" aria-hidden="true"><FiCheckCircle /></span>
        <span className="ds-alerts-text">
          {t('allSystemsClear', 'All systems clear')}
        </span>
      </div>
    );
  }

  const visible = items.slice(0, 2);
  const overflow = items.length - visible.length;

  return (
    <div className="ds-alerts ds-alerts--has-items" role="status" aria-live="polite" aria-label={`${t('attentionRequired', 'Attention required')}: ${items.map((n) => n.title).join('. ')}`}>
      <span className="ds-alerts-icon" aria-hidden="true"><FiAlertTriangle /></span>
      <span className="ds-alerts-items">
        {visible.map((n) => (
          <button
            key={n.id}
            type="button"
            className={`ds-alert-pill ds-alert-pill--${n.level || 'warning'}`}
            onClick={() => n.link && navigate(n.link)}
            title={n.detail || n.title}
          >
            <span className="dot" aria-hidden="true" />
            {n.title}
          </button>
        ))}
        {overflow > 0 && (
          <button
            type="button"
            className="ds-alerts-more"
            onClick={() => items[2]?.link && navigate(items[2].link)}
          >
            +{overflow}
          </button>
        )}
      </span>
      {onClear && (
        <button type="button" className="ds-alerts-more" onClick={onClear}>
          {t('dismiss', 'Dismiss')}
        </button>
      )}
    </div>
  );
}
