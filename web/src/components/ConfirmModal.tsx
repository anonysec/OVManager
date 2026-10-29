// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
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
  title,
  message,
  confirmLabel,
  cancelLabel,
  danger = true,
}: ConfirmModalProps) => {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const resolvedTitle = title ?? t('confirmTitle', 'Are you sure?');
  const resolvedConfirm = confirmLabel ?? t('confirmDelete', 'Delete');
  const resolvedCancel = cancelLabel ?? t('cancel', 'Cancel');
  const handleConfirm = async () => {
    setBusy(true);
    try {
      await onConfirm();
      onClose();
    } catch (e) {
      // Keep the dialog open so the caller can retry; surface via toast at caller.
      void e;
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal isOpen={open} onClose={busy ? undefined : onClose} title={resolvedTitle} size="small">
      {message && <p style={{ margin: '0 0 20px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>{message}</p>}
      <div className="confirm-modal-actions">
        <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
          {resolvedCancel}
        </button>
        <button
          type="button"
          className={`btn${danger ? ' btn-danger' : ''}`}
          onClick={handleConfirm}
          disabled={busy}
          aria-busy={busy || undefined}
         
        >
          {busy && <span className="button-spinner" aria-hidden="true" />}
          {resolvedConfirm}
        </button>
      </div>
    </Modal>
  );
};

export default ConfirmModal;
