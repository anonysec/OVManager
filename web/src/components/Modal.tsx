import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { createPortal } from 'react-dom';
import { FiX } from 'react-icons/fi';

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

const Modal = ({ isOpen, onClose, title, children, size = 'medium' }: { isOpen?: any; onClose?: any; title?: any; children?: any; size?: any }) => {
  const { t } = useTranslation();
  const dialogRef = useRef<any>(null);
  const previousFocusRef = useRef<any>(null);
  const onCloseRef = useRef<any>(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!isOpen) return undefined;

    previousFocusRef.current = document.activeElement;
    const dialog = dialogRef.current;
    if (dialog) {
      const firstInput = dialog.querySelector('input:not([disabled]), textarea:not([disabled]), select:not([disabled])');
      if (firstInput) firstInput.focus();
      else if (dialog.querySelectorAll(FOCUSABLE)[0]) dialog.querySelectorAll(FOCUSABLE)[0].focus();
      else dialog.focus();
    }

    const onKeyDown = (e: any) => {
      if (e.key === 'Escape') {
        onCloseRef.current();
        return;
      }

      if (e.key !== 'Tab' || !dialog) return;
      const focusable: any[] = Array.from(dialog.querySelectorAll(FOCUSABLE)).filter(
        (el: any) => !el.closest('[aria-hidden="true"]')
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
      if (previousFocusRef.current && typeof previousFocusRef.current.focus === 'function') {
        previousFocusRef.current.focus();
      }
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, [isOpen]);

  if (!isOpen) return null;

  const handleBackdropClick = (e: any) => {
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
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="modal-close modal-close--floating"
            aria-label={t('closeModal', 'Close modal')}
          >
            <FiX size={20} />
          </button>
        )}
        {title && (
          <div className="modal-header">
            <h2 id="modal-title">{title}</h2>
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
