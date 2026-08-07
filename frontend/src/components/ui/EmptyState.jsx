import { FiInbox } from 'react-icons/fi';

const EmptyState = ({ title, description, icon: Icon = FiInbox, actionLabel, onAction }) => ( // eslint-disable-line no-unused-vars
  <div className="empty-state">
    <span className="empty-state-icon" aria-hidden="true"><Icon size={40} /></span>
    <h3>{title}</h3>
    {description && <p>{description}</p>}
    {actionLabel && onAction && (
      <button type="button" className="btn btn-secondary empty-state-action" onClick={onAction}>
        {actionLabel}
      </button>
    )}
  </div>
);

export default EmptyState;