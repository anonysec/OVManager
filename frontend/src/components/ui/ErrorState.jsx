import { FiAlertTriangle, FiArrowLeft, FiRefreshCw } from 'react-icons/fi';

const ErrorState = ({ title, message, icon: Icon = FiAlertTriangle, onRetry, onBack, retryLabel = 'Retry' }) => (
  <div className="error-state" role="alert" aria-live="assertive">
    <span className="error-state-icon" aria-hidden="true"><Icon size={40} /></span>
    <h3>{title}</h3>
    {message && <p>{message}</p>}
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
  </div>
);

export default ErrorState;