import { FiInbox } from 'react-icons/fi';

// The soft accent-tinted badge disc makes an empty region read as
// "intentional" rather than "broken", and leads the eye to the headline.

const EmptyState = ({ title, description, actionLabel, onAction }: { title?: any; description?: any; actionLabel?: any; onAction?: any }) => (
  <div className="empty-state">
    <span className="empty-state-badge" aria-hidden="true">
      <FiInbox size={28} />
    </span>
    <div className="empty-state-body">
      <h3>{title}</h3>
      {description && <p>{description}</p>}
    </div>
    {actionLabel && onAction && (
      <button type="button" className="btn btn-secondary empty-state-action" onClick={onAction}>
        {actionLabel}
      </button>
    )}
  </div>
);

export default EmptyState;
