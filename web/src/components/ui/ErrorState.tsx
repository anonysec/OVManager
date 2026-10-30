import './ErrorState.css';
import { FiAlertTriangle, FiRefreshCw } from 'react-icons/fi';
import { useTranslation } from 'react-i18next';

// Pairs with EmptyState: same badge geometry, different hue. Uses the danger

const ErrorState = ({ title, message, onRetry, retryLabel }: { title?: any; message?: any; onRetry?: any; retryLabel?: any }) => {
  const { t } = useTranslation();
  const label = retryLabel ?? t('retry', 'Retry');
  return (
  <div className="error-state" role="alert" aria-live="assertive">
    <span className="error-state-badge" aria-hidden="true">
      <FiAlertTriangle size={28} />
    </span>
    <div className="error-state-body">
      {title && <h3>{title}</h3>}
      {message && <p>{message}</p>}
    </div>
    {onRetry && (
      <div className="error-state-actions">
        <button type="button" className="btn btn-retry" onClick={onRetry}>
          <FiRefreshCw aria-hidden="true" /> {label}
        </button>
      </div>
    )}
  </div>
  );
};

export default ErrorState;
