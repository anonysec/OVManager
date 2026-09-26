import { FiAlertTriangle, FiRefreshCw } from 'react-icons/fi';

/**
 * ErrorState — error placeholder.
 *
 * Pair with EmptyState visually: same badge geometry, different hue. The badge
 * uses the danger soft fill + danger-text foreground so it reads at AA in both
 * themes without falling back to a vivid red on a white card.
 */
const ErrorState = ({ title, message, onRetry, retryLabel = 'Retry' }) => (
  <div className="error-state" role="alert" aria-live="assertive">
    <span className="error-state-badge" aria-hidden="true">
      <FiAlertTriangle size={28} />
    </span>
    <div className="error-state-body">
      <h3>{title}</h3>
      {message && <p>{message}</p>}
    </div>
    {onRetry && (
      <div className="error-state-actions">
        <button type="button" className="btn btn-retry" onClick={onRetry}>
          <FiRefreshCw aria-hidden="true" /> {retryLabel}
        </button>
      </div>
    )}
  </div>
);

export default ErrorState;
