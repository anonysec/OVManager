import { useTranslation } from 'react-i18next';

const UserSessionsModal = ({ user, data, loading, error, onClose, onRefresh, onDisconnect }) => {
  const { t } = useTranslation();
  const totals = data?.totals || {};
  const nodes = data?.nodes || [];

  const fmt = (value) => Number(value || 0).toLocaleString();

  return (
    <div className="modal-overlay">
      <div className="modal-content" style={{ maxWidth: 920 }}>
        <div className="modal-header">
          <h3>{t('sessionsTitle', 'Sessions / Auth Errors')} - {user?.name}</h3>
          <button className="close-button" onClick={onClose}>×</button>
        </div>

        {error && <div className="error-message">{error}</div>}
        {loading ? (
          <p>{t('loading', 'Loading...')}</p>
        ) : (
          <>
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
              <span className="status-active" style={{ padding: '6px 10px', borderRadius: 8 }}>
                {t('liveSessions', 'Live')}: {fmt(totals.live_count)}
              </span>
              <span style={{ padding: '6px 10px', borderRadius: 8, background: 'rgba(255,152,0,.12)', color: '#ffb74d' }}>
                {t('authErrors', 'Auth errors')}: {fmt(totals.auth_errors)}
              </span>
              <span style={{ padding: '6px 10px', borderRadius: 8, background: 'rgba(244,67,54,.12)', color: '#ef9a9a' }}>
                {t('staleMarkers', 'Stale markers')}: {fmt(totals.stale_marker_count)}
              </span>
            </div>

            <div className="table-container" style={{ maxHeight: 420, overflow: 'auto' }}>
              <table>
                <thead>
                  <tr>
                    <th>{t('node', 'Node')}</th>
                    <th>{t('commonName', 'Common name')}</th>
                    <th>{t('liveSessions', 'Live')}</th>
                    <th>{t('authErrors', 'Auth errors')}</th>
                    <th>{t('staleMarkers', 'Stale')}</th>
                    <th>{t('management', 'Mgmt')}</th>
                    <th>{t('lastError', 'Last error')}</th>
                  </tr>
                </thead>
                <tbody>
                  {nodes.map((node) => (
                    <tr key={node.node_name || node.common_name}>
                      <td>{node.node_name}</td>
                      <td>{node.common_name}</td>
                      <td>{fmt(node.live_count)}</td>
                      <td>{fmt(node.auth_errors)}</td>
                      <td>{fmt(node.stale_marker_count)}</td>
                      <td>{node.management_available ? t('yes', 'Yes') : t('no', 'No')}</td>
                      <td style={{ maxWidth: 320, whiteSpace: 'normal', fontSize: 12 }}>
                        {node.last_error || '-'}
                      </td>
                    </tr>
                  ))}
                  {nodes.length === 0 && (
                    <tr><td colSpan="7" style={{ textAlign: 'center' }}>{t('noData', 'No data')}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}

        <div className="modal-actions" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 18 }}>
          <button type="button" className="btn-secondary" onClick={onRefresh} disabled={loading}>
            {t('refreshButton', 'Refresh')}
          </button>
          <button type="button" className="btn danger" onClick={onDisconnect} disabled={loading}>
            {t('disconnectButton', 'Disconnect')}
          </button>
        </div>
        <p style={{ fontSize: 12, color: '#9e9e9e', marginTop: 12 }}>
          {t('disconnectHint', 'Disconnect removes stale login markers immediately. Live-session kill requires OpenVPN management to be enabled on the node.')}
        </p>
      </div>
    </div>
  );
};

export default UserSessionsModal;
