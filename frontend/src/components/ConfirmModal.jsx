import Modal from './Modal';

const ConfirmModal = ({ open, onClose, onConfirm, title, message, confirmLabel = 'Delete', danger = true }) => {
  if (!open) return null;

  return (
    <div className="confirm-modal-overlay" onClick={onClose}>
      <div className="confirm-modal" onClick={(e) => e.stopPropagation()}>
        <button className="close-modal-btn" onClick={onClose} aria-label="Close">×</button>
        <h3>{title}</h3>
        <p>{message}</p>
        <div className="confirm-modal-actions">
          <button className="btn btn-secondary" onClick={onClose}>{cancelLabel}</button>
          <button className={`btn ${danger ? 'btn-danger' : ''}`} onClick={onConfirm}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
};

export default ConfirmModal;