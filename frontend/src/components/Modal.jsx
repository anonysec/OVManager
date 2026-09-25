import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { createPortal } from 'react-dom';
import { FiX } from 'react-icons/fi';

// Ensure the portal mount point exists once.
function getModalRoot() {
  let root = document.getElementById('modal-root');
  if (!root) {
    root = document.createElement('div');
    root.id = 'modal-root';
    document.body.appendChild(root);
  }
  return root;
}

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

const Modal = ({ isOpen, onClose, title, children, size = 'medium' }) => {
  const { t } = useTranslation();
  const dialogRef = useRef(null);
  // Store what had focus before the modal opened so we can restore it on close.
  const previousFocusRef = useRef(null);
  // Keep the latest close handler without re-running the focus effect below:
  // a fresh closure every render must not steal focus back to the header's
  // close button while the user is typing.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  // Escape key + focus management — runs once per open, never per re-render.
  useEffect(() => {
    if (!isOpen) return undefined;

    // Save current focus target and move focus into the dialog. Prefer the
    // first input field (a form should open ready to type); fall back to the
    // first focusable element or the dialog itself.
    previousFocusRef.current = document.activeElement;
    const dialog = dialogRef.current;
    if (dialog) {
      const firstInput = dialog.querySelector('input:not([disabled]), textarea:not([disabled]), select:not([disabled])');
      if (firstInput) firstInput.focus();
      else if (dialog.querySelectorAll(FOCUSABLE)[0]) dialog.querySelectorAll(FOCUSABLE)[0].focus();
      else dialog.focus();
    }

    const onKeyDown = (e) => {
      if (e.key === 'Escape') {
        onCloseRef.current();
        return;
      }

      // Tab / Shift+Tab focus trap
      if (e.key !== 'Tab' || !dialog) return;
      const focusable = Array.from(dialog.querySelectorAll(FOCUSABLE)).filter(
        (el) => !el.closest('[aria-hidden="true"]')
      );
      if (!focusable.length) { e.preventDefault(); return; }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      // Restore focus to the element that opened the modal
      if (previousFocusRef.current && typeof previousFocusRef.current.focus === 'function') {
        previousFocusRef.current.focus();
      }
    };
  }, [isOpen]);

  // Prevent body scroll while modal is open
  useEffect(() => {
    if (!isOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, [isOpen]);

  if (!isOpen) return null;

  const handleBackdropClick = (e) => {
    if (e.target === e.currentTarget) onClose();
  };

  return createPortal(
    <div className="modal-backdrop" onClick={handleBackdropClick}>
      <div
        ref={dialogRef}
        className={`modal-window modal-${size}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? 'modal-title' : undefined}
        tabIndex={-1}
      >
        {title && (
          <div className="modal-header">
            <h2 id="modal-title">{title}</h2>
            <button
              type="button"
              onClick={onClose}
              className="modal-close"
              aria-label={t('closeModal', 'Close modal')}
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
    getModalRoot()
  );
};

export default Modal;
