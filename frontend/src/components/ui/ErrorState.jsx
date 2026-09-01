import { FiAlertTriangle, FiArrowLeft, FiRefreshCw } from 'react-icons/fi';

/**
 * ErrorState — error placeholder.
 *
 * Pair with EmptyState visually: same badge geometry, different hue. The badge
 * uses the danger soft fill + danger-text foreground so it reads at AA in both
 * themes without falling back to a vivid red on a white card.
 *
 * Actions sit on their own row so the headline and message can stay centered
 * even when both retry and back are present.
 */
const ErrorState = ({ title, message, icon: Icon = FiAlertTriangle, onRetry, onBack, retryLabel = 'Retry' }) => (
  <div className="error-state" role="alert" aria-live="assertive">
    <span className="error-state-badge" aria-hidden="true">
      <Icon size={28} />
    </span>
    <div className="error-state-body">
      <h3>{title}</h3>
      {message && <p>{message}</p>}
    </div>
    {(onRetry || onBack) && (
      <div className="error-state-actions">
        {onRetry && (
          <button type="button" className="btn btn-retry" onClick={onRetry}>
            <FiRefreshCw aria-hidden="true" /> {retryLabel}
          </button>
        )}
        {onBack && (
          <button type="button" className="btn btn-secondary" onClick={onBack}>
            <FiArrowLeft aria-hidden="true" /> Go back
          </button>
        )}
      </div>
    )}
  </div>
);

export default ErrorState;
