import { FiInbox } from 'react-icons/fi';

/**
 * EmptyState — friendly, on-brand empty placeholder.
 *
 * The old version dropped a 40px outline icon on the panel with 0.6 opacity.
 * It felt weak — like a missing image rather than a designed state. The badge
 * treatment below puts the icon in a soft accent-tinted disc so it reads as
 * "intentional" instead of "broken", and so the eye is led to the headline.
 *
 * Pass an icon override for context (FiUsers, FiServer, FiActivity…). The badge
 * auto-fits the icon; you do not have to pick a size.
 */
const EmptyState = ({ title, description, icon: Icon = FiInbox, actionLabel, onAction, children }) => (
  <div className="empty-state">
    <span className="empty-state-badge" aria-hidden="true">
      <Icon size={28} />
    </span>
    <div className="empty-state-body">
      <h3>{title}</h3>
      {description && <p>{description}</p>}
      {children}
    </div>
    {actionLabel && onAction && (
      <button type="button" className="btn btn-secondary empty-state-action" onClick={onAction}>
        {actionLabel}
      </button>
    )}
  </div>
);

export default EmptyState;
