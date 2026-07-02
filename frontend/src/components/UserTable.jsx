import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FiCopy } from 'react-icons/fi';
import ActionsDropdown from './ActionsDropdown';
import './UserTable.css';

const UserTable = ({ users, onDelete, onDownload, onEdit, onToggleStatus, onResetUsage, onShowSessions, getSubscriptionLink }) => {
  const { t } = useTranslation();
  const [copyFeedback, setCopyFeedback] = useState({ id: null, status: null });

  const formatTrafficGB = (bytes) => {
    if (bytes === null || bytes === undefined) return '-';
    const gb = Number(bytes) / 1024 / 1024 / 1024;
    if (!Number.isFinite(gb)) return '-';

    if (gb < 1) {
      return gb.toFixed(1);
    }
    // For values >= 1 GB, remove trailing zeros
    return gb.toFixed(2).replace(/\.00$/, '').replace(/\.0$/, '');
  };

  const formatLoginUsage = (user) => {
    const active = Number(user.active_connections || 0);
    const max = Number(user.max_logins || 0);
    return `${active}/${max === 0 ? t('unlimited', '∞') : max}`;
  };

  const formatTrafficUsage = (used, total) => {
    const unlimited = t('unlimited', '∞');
    const usedText = formatTrafficGB(used);
    // total null/undefined means unlimited traffic.
    if (total === null || total === undefined) {
      return usedText === '-' ? `0 / ${unlimited}` : `${usedText} / ${unlimited}`;
    }
    const totalText = formatTrafficGB(total);
    if (usedText === '-' && totalText === '-') return '-';
    if (usedText === '-') return `- / ${totalText} GB`;
    if (totalText === '-') return `${usedText} / -`;
    return `${usedText} / ${totalText} GB`;
  };

  const showCopyFeedback = (user, status) => {
    const id = user?.uuid || user?.name;
    setCopyFeedback({ id, status });
    window.setTimeout(() => {
      setCopyFeedback((current) => (current.id === id ? { id: null, status: null } : current));
    }, 1600);
  };

  const copyLabelFor = (user) => {
    const id = user?.uuid || user?.name;
    if (copyFeedback.id !== id) return t('copySubscriptionLink', 'Copy');
    if (copyFeedback.status === 'copied') return t('copied_subscription_link', 'Copied');
    if (copyFeedback.status === 'empty') return t('copy_no_link', 'No link');
    if (copyFeedback.status === 'failed') return t('copy_failed', 'Failed');
    return t('copySubscriptionLink', 'Copy');
  };

  const copyColorFor = (user) => {
    const id = user?.uuid || user?.name;
    if (copyFeedback.id !== id) return '#90caf9';
    if (copyFeedback.status === 'copied') return '#4caf50';
    return '#ff9800';
  };

  const handleCopyLink = async (user) => {
    if (!getSubscriptionLink) {
      showCopyFeedback(user, 'empty');
      return;
    }
    const link = getSubscriptionLink(user) || '';
    if (!link) {
      showCopyFeedback(user, 'empty');
      return;
    }

    const copied = await copyTextToClipboard(link);
    showCopyFeedback(user, copied ? 'copied' : 'failed');
    if (!copied) {
      console.warn('Failed to copy subscription link:', link);
    }
  };

  // Works on both HTTPS and plain HTTP/IP panels.
  async function copyTextToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch {
        // Fall through to textarea fallback.
      }
    }

    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.setAttribute('readonly', '');
    textArea.style.position = 'fixed';
    textArea.style.top = '-1000px';
    textArea.style.left = '-1000px';
    textArea.style.opacity = '0';
    document.body.appendChild(textArea);

    const selection = document.getSelection();
    const selectedRange = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null;

    textArea.focus();
    textArea.select();
    textArea.setSelectionRange(0, text.length);

    let copied = false;
    try {
      copied = document.execCommand('copy');
    } catch {
      copied = false;
    }

    document.body.removeChild(textArea);
    if (selectedRange && selection) {
      selection.removeAllRanges();
      selection.addRange(selectedRange);
    }
    return copied;
  }

  return (
    <div className="table-container">
      <table>
        <thead>
          <tr>
            <th>{t('th_username')}</th>
            <th>{t('th_expiryDate')}</th>
            <th>{t('th_totalTraffic')}</th>
            <th>{t('th_maxLogins')}</th>
            <th>{t('th_status')}</th>
            <th>{t('th_owner')}</th>
            <th>{t('th_actions')}</th>
          </tr>
        </thead>
        <tbody>
          {users.length === 0 ? (
            <tr><td colSpan="7" style={{ textAlign: 'center' }}>{t('noUsersFound')}</td></tr>
          ) : (
            users.map((user) => (
              <tr key={user.name}>
                <td>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                    <span
                      title={user.online ? t('online', 'Online') : t('offline', 'Offline')}
                      style={{
                        width: 9,
                        height: 9,
                        borderRadius: '50%',
                        background: user.online ? '#4caf50' : '#777',
                        boxShadow: user.online ? '0 0 8px rgba(76,175,80,.7)' : 'none',
                        display: 'inline-block',
                      }}
                    />
                    <span>{user.name}</span>
                    <small style={{ color: user.online ? '#81c784' : '#9e9e9e' }}>
                      {user.online ? t('online', 'Online') : t('offline', 'Offline')}
                    </small>
                  </span>
                </td>
                <td>{new Date(user.expiry_date).toLocaleDateString('en-CA')}</td>
                <td>{formatTrafficUsage(user.used, user.total)}</td>
                <td>{formatLoginUsage(user)}</td>
                <td>
                  <span className={`status-${user.is_active ? 'active' : 'inactive'}`}>
                    {user.is_active ? t('status_active') : t('status_inactive')}
                  </span>
                </td>
                <td>{user.owner}</td>
                <td style={{ textAlign: 'right', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <ActionsDropdown
                    actions={[
                      { label: t('editButton'), onClick: () => onEdit(user) },
                      { label: t('downloadButton'), onClick: () => onDownload(user) },
                      {
                        label: t('resetUsageButton', 'Reset Usage'),
                        onClick: () => onResetUsage && onResetUsage(user),
                        className: 'secondary-action',
                      },
                      {
                        label: t('sessionsButton', 'Sessions / Auth Errors'),
                        onClick: () => onShowSessions && onShowSessions(user),
                        className: 'secondary-action',
                      },
                      {
                        label: user.is_active ? t('deactivateButton', 'Deactivate') : t('activateButton', 'Activate'),
                        onClick: () => onToggleStatus(user),
                        className: user.is_active ? 'warning-action' : 'success-action',
                      },
                      {
                        label: t('deleteButton'),
                        onClick: () => onDelete(user.uuid, user.name),
                        className: 'danger-action',
                      },
                    ]}
                  />
                  <button
                    className="icon-btn btn-copy"
                    title={copyLabelFor(user)}
                    type="button"
                    onClick={() => handleCopyLink(user)}
                    style={{
                      background: 'rgba(144, 202, 249, 0.08)',
                      border: '1px solid rgba(144, 202, 249, 0.35)',
                      borderRadius: 6,
                      padding: '4px 8px',
                      marginLeft: 6,
                      cursor: 'pointer',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 5,
                      color: copyColorFor(user),
                      fontSize: 12,
                      minWidth: 72,
                      justifyContent: 'center',
                    }}
                  >
                    <FiCopy style={{ fontSize: 16, color: copyColorFor(user) }} />
                    <span>{copyLabelFor(user)}</span>
                  </button>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
};

export default UserTable;