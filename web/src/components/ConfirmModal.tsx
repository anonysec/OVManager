// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState } from 'react';
import Modal from './Modal';

type ConfirmModalProps = {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void | Promise<void>;
  title?: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
};

const ConfirmModal = ({
  open,
  onClose,
  onConfirm,
  title = 'Are you sure?',
  message,
  confirmLabel = 'Delete',
  cancelLabel = 'Cancel',
  danger = true,
}: ConfirmModalProps) => {
  const [busy, setBusy] = useState(false);
  const handleConfirm = async () => {
    setBusy(true);
    try {
      await onConfirm();
      onClose();
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal isOpen={open} onClose={onClose} title={title} size="small">
      {message && <p style={{ margin: '0 0 20px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>{message}</p>}
      <div className="confirm-modal-actions">
        <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
          {cancelLabel}
        </button>
        <button
          type="button"
          className={`btn${danger ? ' btn-danger' : ''}`}
          onClick={handleConfirm}
          disabled={busy}
          aria-busy={busy || undefined}
          autoFocus
        >
          {busy && <span className="button-spinner" aria-hidden="true" />}
          {confirmLabel}
        </button>
      </div>
    </Modal>
  );
};

export default ConfirmModal;
