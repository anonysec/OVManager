import { FiInbox } from 'react-icons/fi';

/**
 * EmptyState — friendly, on-brand empty placeholder.
 *
 * The badge treatment puts the icon in a soft accent-tinted disc so it
 * reads as "intentional" instead of "broken", and so the eye is led to
 * the headline.
 */
const EmptyState = ({ title, description, actionLabel, onAction }) => (
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
