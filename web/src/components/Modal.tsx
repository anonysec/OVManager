import './Modal.css';
import { useEffect, useId, useRef, type MouseEvent } from 'react';
import type { ReactNode } from 'react';
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

let dialogCount = 0;

const Modal = ({ isOpen, onClose, title, children, size = 'medium' }: { isOpen?: boolean; onClose?: () => void; title?: string; children?: ReactNode; size?: 'small' | 'medium' | 'large' }) => {
  const { t } = useTranslation();
  const dialogRef = useRef<any>(null);
  const titleId = useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const previousFocusRef = useRef<any>(null);
  const onCloseRef = useRef<any>(onClose);
  const pointerDownRef = useRef<{ x: number; y: number } | null>(null);
  const dirtyRef = useRef(false);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  // Dialog semantics: inert the app root while open so background content is
  // not focusable/operable, and lock body scroll. Reference-count nested dialogs
  // so closing one does not un-inert the page while another stays open.
  useEffect(() => {
    if (!isOpen) return undefined;
    dialogCount += 1;
    const rootEl = document.getElementById('root');
    const ownsInert = dialogCount === 1;
    const inertPrev = ownsInert ? (rootEl ? rootEl.getAttribute('inert') : null) : null;
    if (ownsInert && rootEl) rootEl.setAttribute('inert', '');
    const ownsOverflow = dialogCount === 1;
    const prevOverflow = ownsOverflow ? document.body.style.overflow : '';
    if (ownsOverflow) document.body.style.overflow = 'hidden';
    return () => {
      dialogCount = Math.max(0, dialogCount - 1);
      if (ownsOverflow) document.body.style.overflow = prevOverflow;
      if (ownsInert && rootEl) {
        if (inertPrev !== null) rootEl.setAttribute('inert', inertPrev);
        else rootEl.removeAttribute('inert');
      }
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return undefined;

    previousFocusRef.current = document.activeElement;
    pointerDownRef.current = null;
    dirtyRef.current = false;
    const dialog = dialogRef.current;
    if (dialog) {
      const firstInput = dialog.querySelector('input:not([disabled]), textarea:not([disabled]), select:not([disabled])');
      if (firstInput) firstInput.focus();
      else if (dialog.querySelectorAll(FOCUSABLE)[0]) dialog.querySelectorAll(FOCUSABLE)[0].focus();
      else dialog.focus();
    }

    const onKeyDown = (e: any) => {
      if (e.key === 'Escape') {
        onCloseRef.current?.();
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

  if (!isOpen) return null;

  // Clicking the backdrop closes the dialog, but only on a real click. A
  // drag (text selection, a slipped pointer) or a form the user has edited
  // must not dismiss the draft; X, Cancel and Escape still do.
  const handleBackdropMouseDown = (e: MouseEvent<HTMLDivElement>) => {
    pointerDownRef.current = e.target === e.currentTarget ? { x: e.clientX, y: e.clientY } : null;
  };
  const handleBackdropClick = (e: MouseEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget) return;
    const start = pointerDownRef.current;
    pointerDownRef.current = null;
    if (!start) return;
    if (Math.hypot(e.clientX - start.x, e.clientY - start.y) > 4) return;
    if (dirtyRef.current) return;
    if (window.getSelection()?.toString()) return;
    onCloseRef.current?.();
  };
  const markDirty = () => { dirtyRef.current = true; };

  return createPortal(
    <div
      className="modal-backdrop"
      onMouseDown={handleBackdropMouseDown}
      onClick={handleBackdropClick}
      role="presentation"
    >
      <div
        ref={dialogRef}
        className={`modal-window modal-${size}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        tabIndex={-1}
        onInput={markDirty}
        onChange={markDirty}
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
            <h2 id={titleId}>{title}</h2>
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
