import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  FiEdit2, FiActivity, FiDownload, FiCopy, FiCheck, FiWifi, FiHardDrive,
  FiClock, FiUsers, FiUserX, FiUserCheck, FiRefreshCw, FiTrash2,
} from 'react-icons/fi';
import Modal from './Modal';
import { Badge, Button } from './ui';
import apiClient from '../services/api';
import { formatTraffic } from '../utils/format';
import { daysUntil, formatDate, fmtRelative } from '../utils/time';
import { copyText } from '../utils/clipboard';

const statusOf = (user, t) => {
  const online = user.online || Number(user.active_connections || 0) > 0;
  if (online) return { label: t('statusOnline'), tone: 'success' };
  const d = daysUntil(user.expiry_date);
  if (d < 0) return { label: t('expired'), tone: 'danger' };
  if (user.is_active === false) return { label: t('disabled'), tone: 'neutral' };
  return { label: t('statusOffline'), tone: 'neutral' };
};

const TrafficHistory = ({ days, t }) => {
  const max = Math.max(...days.map((d) => Number(d.bytes || 0)), 1);
  return (
    <div className="ud-hist" aria-label={t('trafficHistory14d', 'Traffic, last 14 days')}>
      <span className="ud-label">{t('trafficHistory14d', 'Traffic, last 14 days')}</span>
      <div className="ud-hist-bars">
        {days.map((d) => (
          <span
            key={d.day}
            className="ud-hist-bar"
            title={`${d.day}: ${formatTraffic(d.bytes)}`}
            style={{ height: `${Math.max(3, Math.round((Number(d.bytes || 0) / max) * 100))}%` }}
          />
        ))}
      </div>
    </div>
  );
};

const UserDetailModal = ({ user, isOpen, onClose, subscriptionLink, onEdit, onSessions, onDownload, onToggleStatus, onDelete, onExtend, onResetUsage }) => {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const [qr, setQr] = useState('');
  const [history, setHistory] = useState(null);

  // Per-day billed bytes (last 14 days) for the traffic graph.
  useEffect(() => {
    if (!isOpen || !user?.uuid) {
      setHistory(null);
      return;
    }
    let cancelled = false;
    apiClient
      .get(`/users/${user.uuid}/traffic`, { params: { days: 14 } })
      .then((r) => {
        if (cancelled) return;
        const list = r.data?.data?.days;
        setHistory(Array.isArray(list) ? list : []);
      })
      .catch(() => {
        if (!cancelled) setHistory([]);
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen, user?.uuid]);

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
  const used = Number(user.used || 0);
  const total = Number(user.total || 0);
  const unlimited = !total;
  const pct = unlimited ? 0 : Math.min(100, Math.round((used / total) * 100));
  const expirySoon = d >= 0 && d <= 7;

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
      <div className="ud-page">
        <header className="ud-header">
          <span className="ud-avatar" aria-hidden="true">{user.name.slice(0, 1).toUpperCase()}</span>
          <div className="ud-identity">
            <strong className="ud-name">{user.name}</strong>
            <code className="ud-uuid" title={user.uuid}>{user.uuid.slice(0, 8)}…</code>
          </div>
          <Badge tone={st.tone} dot>{st.label}</Badge>
        </header>

        <section className="ud-usage" aria-label={t('totalUsage', 'Total usage')}>
          <div className="ud-usage-head">
            <span className="ud-label">{t('quotaLabel', 'Quota')}</span>
            <span className="ud-usage-value">
              {formatTraffic(used)} / {unlimited ? t('unlimited') : formatTraffic(total)}
            </span>
          </div>
          <div
            className={`ud-progress${pct >= 85 ? ' ud-progress--warn' : ''}${pct >= 100 ? ' ud-progress--danger' : ''}`}
            role="progressbar"
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={t('quotaUsed', '{{pct}}% used', { pct })}
          >
            <span className="ud-progress-fill" style={{ width: unlimited ? '0%' : `${pct}%` }} />
          </div>
          <span className="ud-usage-note">
            {unlimited ? t('unlimited') : t('quotaUsed', '{{pct}}% used', { pct })}
          </span>
        </section>

        <dl className="ud-grid">
          <div className="ud-cell">
            <span className="ud-ico" aria-hidden="true"><FiWifi /></span>
            <div>
              <dt className="ud-label">{t('activeConnections')}</dt>
              <dd className="ud-value">{user.active_connections ?? 0}/{user.max_logins ?? 0}</dd>
            </div>
          </div>
          <div className="ud-cell">
            <span className="ud-ico" aria-hidden="true"><FiHardDrive /></span>
            <div>
              <dt className="ud-label">{t('th_dataUsed', 'Data Used')}</dt>
              <dd className="ud-value">{formatTraffic(used)}</dd>
            </div>
          </div>
          <div className="ud-cell">
            <span className="ud-ico" aria-hidden="true"><FiClock /></span>
            <div>
              <dt className="ud-label">{t('th_expiryDate')}</dt>
              <dd className={`ud-value${expirySoon ? ' is-soon' : ''}`}>
                {formatDate(user.expiry_date)}
                {d !== Infinity && (
                  <small className="ud-subline">
                    {d < 0
                      ? t('expiredAgo', 'Expired {{days}} days ago', { days: Math.abs(d) })
                      : t('expiresIn', 'Expires in {{days}} days', { days: d })}
                  </small>
                )}
              </dd>
            </div>
          </div>
          <div className="ud-cell">
            <span className="ud-ico" aria-hidden="true"><FiActivity /></span>
            <div>
              <dt className="ud-label">{t('th_lastOnline')}</dt>
              <dd className="ud-value">{user.last_online ? fmtRelative(user.last_online) : t('never', 'Never')}</dd>
            </div>
          </div>
          <div className="ud-cell">
            <span className="ud-ico" aria-hidden="true"><FiUsers /></span>
            <div>
              <dt className="ud-label">{t('th_owner')}</dt>
              <dd className="ud-value">{user.owner || '—'}</dd>
            </div>
          </div>
        </dl>

        {history && history.length > 0 && history.some((day) => Number(day.bytes) > 0) && (
          <TrafficHistory days={history} t={t} />
        )}

        <section className="ud-sub">
          <span className="ud-label">{t('subscriptionLink')}</span>
          <div className="ud-linkrow">
            <code className="ud-link">{subscriptionLink || '—'}</code>
            <Button
              size="sm"
              variant="secondary"
              onClick={copyLink}
              disabled={!subscriptionLink}
              icon={copied ? <FiCheck aria-hidden="true" /> : <FiCopy aria-hidden="true" />}
              aria-label={t('copyLink')}
            />
          </div>
          {qr && (
            <div className="ud-qr" aria-label={t('qrAlt', 'Subscription link QR code')}>
              <img src={qr} alt="" />
            </div>
          )}
          <p className="ud-note">{t('subIsOpenvpn')}</p>
        </section>

        <div className="ud-actions">
          <Button variant="primary" size="sm" icon={<FiDownload aria-hidden="true" />} onClick={() => onDownload?.(user)}>
            {t('downloadConfig')}
          </Button>
          <Button size="sm" icon={<FiEdit2 aria-hidden="true" />} onClick={() => onEdit?.(user)}>
            {t('rowEdit')}
          </Button>
          <Button size="sm" icon={<FiActivity aria-hidden="true" />} onClick={() => onSessions?.(user)}>
            {t('rowSessions')}
          </Button>
          {onExtend && (
            <Button size="sm" icon={<FiClock aria-hidden="true" />} onClick={() => onExtend?.(user)}>
              {t('extend', 'Extend')}
            </Button>
          )}
          {onToggleStatus && (
            <Button
              size="sm"
              variant={user.is_active ? 'secondary' : 'primary'}
              icon={user.is_active ? <FiUserX aria-hidden="true" /> : <FiUserCheck aria-hidden="true" />}
              onClick={() => onToggleStatus(user)}
            >
              {user.is_active ? t('disableUser') : t('enableUser')}
            </Button>
          )}
          {onResetUsage && (
            <Button size="sm" icon={<FiRefreshCw aria-hidden="true" />} onClick={() => onResetUsage?.(user)}>
              {t('resetUsageButton', 'Reset usage')}
            </Button>
          )}
          {onDelete && (
            <Button variant="danger" size="sm" icon={<FiTrash2 aria-hidden="true" />} onClick={() => onDelete?.(user)}>
              {t('rowDelete', 'Delete')}
            </Button>
          )}
        </div>

        <p className="ud-hint">{t('downloadConfigHint', "Download this user's OpenVPN profile (.ovpn).")}</p>
      </div>
    </Modal>
  );
};

export default UserDetailModal;
