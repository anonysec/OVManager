import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { FiEdit2, FiActivity, FiDownload, FiCopy, FiCheck, FiWifi, FiHardDrive, FiClock, FiUsers, FiUserX, FiUserCheck } from 'react-icons/fi';
import Modal from './Modal';
import { formatTraffic } from '../utils/format';
import { daysUntil, formatDate } from '../utils/time';
import { copyText } from '../utils/clipboard';

const statusOf = (user, t) => {
  const online = user.online || Number(user.active_connections || 0) > 0;
  if (online) return { label: t('statusOnline'), cls: 'online' };
  const d = daysUntil(user.expiry_date);
  if (d < 0) return { label: t('expired'), cls: 'expired' };
  if (user.is_active === false) return { label: t('disabled'), cls: 'offline' };
  return { label: t('statusOffline'), cls: 'idle' };
};

const UserDetailModal = ({ user, isOpen, onClose, subscriptionLink, onEdit, onSessions, onDownload, onToggleStatus, onDelete, onExtend, onResetUsage }) => {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const [qr, setQr] = useState('');

  // Generate QR code via a plain dynamic import — lazy() is for React components,
  // not for calling library functions directly.
  useEffect(() => {
    if (!subscriptionLink || !isOpen) return;
    let cancelled = false;
    import('qrcode').then(({ default: QRLib }) => {
      QRLib.toDataURL(subscriptionLink, { margin: 1, width: 240, color: { dark: '#0f1115', light: '#ffffff' } })
        .then((dataUrl) => { if (!cancelled) setQr(dataUrl); })
        .catch(() => { if (!cancelled) setQr(''); });
    }).catch(() => { if (!cancelled) setQr(''); });
    return () => { cancelled = true; };
  }, [subscriptionLink, isOpen]);

  // Reset QR when modal closes so it regenerates fresh on next open
  useEffect(() => {
    if (!isOpen) setQr('');
  }, [isOpen]);

  if (!user) return null;

  const st = statusOf(user, t);
  const d = daysUntil(user.expiry_date);

  const copyLink = async () => {
    if (!subscriptionLink) return;
    try {
      const ok = await copyText(subscriptionLink);
      setCopied(ok);
      setTimeout(() => setCopied(false), 1600);
    } catch { /* ignore */ }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={`${t('user')}: ${user.name}`} size="medium">
      <div className="udetail">
        <div className="udetail-head">
          <span className="udetail-avatar">{user.name.slice(0, 1).toUpperCase()}</span>
          <div>
            <div className="udetail-name">{user.name}</div>
            <span className={`status-pill ${st.cls}`}>{st.label}</span>
          </div>
          <code className="udetail-uuid" title={user.uuid}>{user.uuid.slice(0, 8)}…</code>
        </div>

        <div className="udetail-grid">
          <div className="udetail-cell">
            <span className="ud-ico"><FiWifi /></span>
            <div><span className="ud-k">{t('activeConnections')}</span><strong>{user.active_connections ?? 0}/{user.max_logins ?? 0}</strong></div>
          </div>
          <div className="udetail-cell">
            <span className="ud-ico"><FiHardDrive /></span>
            <div><span className="ud-k">{t('totalTraffic')}</span><strong>{formatTraffic(user.used)} / {Number(user.total) > 0 ? formatTraffic(user.total) : '∞'}</strong></div>
          </div>
          <div className="udetail-cell">
            <span className="ud-ico"><FiClock /></span>
            <div><span className="ud-k">{t('th_expiryDate')}</span><strong className={d >= 0 && d <= 7 ? 'expiry-soon' : ''}>{formatDate(user.expiry_date)}</strong></div>
          </div>
          <div className="udetail-cell">
            <span className="ud-ico"><FiUsers /></span>
            <div><span className="ud-k">{t('th_owner')}</span><strong>{user.owner || '—'}</strong></div>
          </div>
        </div>

        <div className="udetail-sub">
          <span className="ud-k">{t('subscriptionLink')}</span>
          <div className="udetail-linkrow">
            <code className="udetail-link">{subscriptionLink || '—'}</code>
            <button type="button" className="code-copy" onClick={copyLink} aria-label={t('copyLink')} disabled={!subscriptionLink}>
              {copied ? <FiCheck /> : <FiCopy />}
            </button>
          </div>
          {qr && (
            <div className="udetail-qr" aria-label={t('qrAlt', 'Subscription link QR code')}>
              <img src={qr} alt="" />
            </div>
          )}
          <p className="udetail-note">{t('subIsOpenvpn')}</p>
        </div>

        <div className="udetail-actions">
          <button type="button" className="btn btn-sm" onClick={() => { onEdit?.(user); }}><FiEdit2 /> {t('rowEdit')}</button>
          <button type="button" className="btn btn-sm" onClick={() => { onSessions?.(user); }}><FiActivity /> {t('rowSessions')}</button>
          <button type="button" className="btn btn-sm btn-success" onClick={() => { onDownload?.(user); }}><FiDownload /> {t('downloadConfig')}</button>
          {onExtend && (
            <button type="button" className="btn btn-sm btn-secondary" onClick={() => { onExtend?.(user); }}><FiClock /> {t('extend', 'Extend')}</button>
          )}
          {onToggleStatus && (
            <button type="button" className={`btn btn-sm ${user.is_active ? 'btn-secondary' : 'btn-success'}`} onClick={() => onToggleStatus(user)}>
              {user.is_active ? <FiUserX /> : <FiUserCheck />} {user.is_active ? t('disableUser') : t('enableUser')}
            </button>
          )}
          {onResetUsage && (
            <button type="button" className="btn btn-sm btn-secondary" onClick={() => { onResetUsage?.(user); }}>{t('resetUsageButton', 'Reset usage')}</button>
          )}
          {onDelete && (
            <button type="button" className="btn btn-sm btn-danger" onClick={() => { onDelete?.(user); }}>{t('rowDelete', 'Delete')}</button>
          )}
        </div>
      </div>
    </Modal>
  );
};

export default UserDetailModal;
