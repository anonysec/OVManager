import { FiAlertTriangle, FiRefreshCw } from 'react-icons/fi';

// Pairs with EmptyState: same badge geometry, different hue. Uses the danger

const ErrorState = ({ title, message, onRetry, retryLabel = 'Retry' }: { title?: any; message?: any; onRetry?: any; retryLabel?: any }) => (
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
