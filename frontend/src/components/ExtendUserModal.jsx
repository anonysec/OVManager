import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import Modal from './Modal';
import LoadingButton from './LoadingButton';

const ExtendUserModal = ({ user, isOpen, onClose, onExtend }) => {
  const { t } = useTranslation();
  const [days, setDays] = useState('30');
  const [extraGb, setExtraGb] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (isOpen) {
      setDays('30');
      setExtraGb('');
      setError('');
      setBusy(false);
    }
  }, [isOpen, user]);

  if (!user) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    const d = Number(days || 0);
    const gb = extraGb.trim() === '' ? 0 : Number(extraGb);
    if ((!Number.isFinite(d) || d < 0) || (!Number.isFinite(gb) || gb < 0)) {
      setError(t('invalidExtendInput', 'Enter valid non-negative numbers.'));
      return;
    }
    const bytes = Math.round(gb * 1024 * 1024 * 1024);
    if (d === 0 && bytes === 0) {
      setError(t('extendEmpty', 'Enter days or traffic to add.'));
      return;
    }
    setBusy(true);
    try {
      await onExtend?.(user, { days: Math.floor(d), bytes });
      onClose();
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || t('error'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={`${t('extend', 'Extend')} — ${user.name}`} size="small">
      <form onSubmit={handleSubmit} className="modal-form">
        <div className="input-group">
          <label htmlFor="extend-days">{t('extendDays', 'Add days')}</label>
          <input
            id="extend-days"
            type="number"
            min="0"
            max="3650"
            step="1"
            value={days}
            onChange={(e) => setDays(e.target.value)}
            autoFocus
          />
          <small className="input-hint">{t('extendDaysHint', 'Added to the current expiry date.')}</small>
        </div>
        <div className="input-group">
          <label htmlFor="extend-gb">{t('extendTrafficGb', 'Add traffic (GB)')}</label>
          <input
            id="extend-gb"
            type="number"
            min="0"
            step="0.1"
            value={extraGb}
            onChange={(e) => setExtraGb(e.target.value)}
            placeholder="0"
          />
          <small className="input-hint">{t('extendTrafficHint', 'Added to the current quota. Leave 0 to keep quota.')}</small>
        </div>
        <div className="modal-form-quickrow" role="group" aria-label={t('quickExtend', 'Quick extend')}>
          {[7, 30, 90].map((d) => (
            <button key={d} type="button" className={`date-chip${String(d) === String(days) ? ' active' : ''}`} onClick={() => setDays(String(d))}>
              +{d}d
            </button>
          ))}
        </div>
        {error && <p className="error-message" role="alert">{error}</p>}
        <div className="modal-footer">
          <button type="button" className="btn btn-secondary" onClick={onClose}>{t('cancelButton')}</button>
          <LoadingButton type="submit" className="btn" isLoading={busy}>{t('extend', 'Extend')}</LoadingButton>
        </div>
      </form>
    </Modal>
  );
};

export default ExtendUserModal;
