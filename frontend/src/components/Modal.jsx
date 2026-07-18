import { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { FiX } from 'react-icons/fi';

// Portal modal component for proper overlay behavior
const Modal = ({ isOpen, onClose, title, children, size = 'medium' }) => {
  const modalRef = useRef(null);
  const [modalRoot, setModalRoot] = useState(null);

  useEffect(() => {
    // Create portal root if it doesn't exist
    let root = document.getElementById('modal-root');
    if (!root) {
      root = document.createElement('div');
      root.id = 'modal-root';
      document.body.appendChild(root);
    }
    setModalRoot(root);

    // Handle escape key
    const handleEscape = (e) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [onClose]);

  // Handle click outside to close
  const handleBackdropClick = (e) => {
    if (e.target === modalRef.current?.parentElement) {
      onClose();
    }
  };

  if (!isOpen || !modalRoot) return null;

  return createPortal(
    <div className="modal-backdrop" onClick={handleBackdropClick}>
      <div 
        ref={modalRef}
        className={`modal-window modal-${size}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? "modal-title" : undefined}
      >
        {title && (
          <div className="modal-header">
            <h2 id="modal-title">{title}</h2>
            <button 
              onClick={onClose} 
              className="modal-close"
              aria-label="Close modal"
            >
              <FiX size={20} />
            </button>
          </div>
        )}
        <div className="modal-body">
          {children}
        </div>
      </div>
    </div>,
    modalRoot
  );
};

export default Modal;