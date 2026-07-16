import { useTranslation } from 'react-i18next';

const UserSessionsModal = ({ user, data, loading, error, onClose, onRefresh, onDisconnect }) => {
  const { t } = useTranslation();
  const nodes = data?.nodes || [];
  const registry = data?.global_registry || [];
  const fmt = (value) => Number(value || 0).toLocaleString();

  const policy = (data?.policy || []).join(', ');
  const active = data?.active_connections ?? data?.totals?.live_count ?? 0;
  const max = data?.max_logins === 0 ? '∞' : data?.max_logins;

  return (
    <div className="modal-overlay">
      <div className="modal-content" style={{ maxWidth: 1040 }}>
        <div className="modal-header">
          <h3>{t('sessionsTitle', 'Login Diagnostics')} - {user?.name}</h3>
          <button className="close-button" onClick={onClose}>×</button>
        </div>

        {error && <div className="error-message">{error}</div>}
        {loading ? <p>{t('loading', 'Loading...')}</p> : (
          <>
            <div className="diagnostic-summary">
              <span className="status-active">Active/Max: {active}/{max}</span>
              <span>Mode: {data?.mode || '-'}</span>
              <span>Policy: {policy || '-'}</span>
              <span>Registry: {registry.length}</span>
            </div>
            <p className="diagnostic-recommendation">{data?.recommendation || 'No recommendation available.'}</p>

            <h4>Node sessions</h4>
            <div className="table-container" style={{ maxHeight: 340, overflow: 'auto' }}>
              <table>
                <thead>
                  <tr>
                    <th>{t('node', 'Node')}</th>
                    <th>{t('commonName', 'Common name')}</th>
                    <th>{t('liveSessions', 'Live')}</th>
                    <th>{t('authErrors', 'Auth events')}</th>
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
                      <td style={{ maxWidth: 380, whiteSpace: 'normal', fontSize: 12 }}>{node.last_error || '-'}</td>
                    </tr>
                  ))}
                  {nodes.length === 0 && <tr><td colSpan="7" style={{ textAlign: 'center' }}>{t('noData', 'No data')}</td></tr>}
                </tbody>
              </table>
            </div>

            <h4>Global registry</h4>
            <div className="settings-list small">
              {registry.length ? registry.map((r) => (
                <p key={r.session_key}>{r.node_name} · {r.common_name} · {r.trusted_ip}:{r.trusted_port} · {r.created_at_utc}</p>
              )) : <p>No global registry rows for this user.</p>}
            </div>
          </>
        )}

        <div className="modal-actions" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 18 }}>
          <button type="button" className="btn-secondary" onClick={onRefresh} disabled={loading}>{t('refreshButton', 'Refresh')}</button>
          <button type="button" className="btn danger" onClick={onDisconnect} disabled={loading}>{t('disconnectButton', 'Disconnect')}</button>
        </div>
      </div>
    </div>
  );
};

export default UserSessionsModal;
