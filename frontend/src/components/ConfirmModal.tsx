import Modal from './Modal';

/**
 * A portal-based confirmation dialog that reuses Modal for proper focus trap,
 * Escape-key handling, ARIA attributes, and backdrop click-to-cancel.
 */
const ConfirmModal = ({
  open,
  onClose,
  onConfirm,
  title = 'Are you sure?',
  message,
  confirmLabel = 'Delete',
  cancelLabel = 'Cancel',
  danger = true,
}) => (
  <Modal isOpen={open} onClose={onClose} title={title} size="small">
    {message && <p style={{ margin: '0 0 20px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>{message}</p>}
    <div className="confirm-modal-actions">
      <button type="button" className="btn btn-secondary" onClick={onClose}>
        {cancelLabel}
      </button>
      <button
        type="button"
        className={`btn${danger ? ' btn-danger' : ''}`}
        onClick={() => { onConfirm(); onClose(); }}
        autoFocus
      >
        {confirmLabel}
      </button>
    </div>
  </Modal>
);

export default ConfirmModal;
