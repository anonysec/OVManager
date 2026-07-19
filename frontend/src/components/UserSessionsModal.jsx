import { useTranslation } from 'react-i18next';
import Modal from './Modal';

const UserSessionsModal = ({ isOpen, user, data, loading, error, onClose, onRefresh, onDisconnect }) => {
  const { t } = useTranslation();
  const nodes = data?.nodes || [];
  const registry = data?.global_registry || [];
  const fmt = (value) => Number(value || 0).toLocaleString();

  const policy = (data?.policy || []).join(', ');
  const active = data?.active_connections ?? data?.totals?.live_count ?? 0;
  const max = data?.max_logins === 0 ? '∞' : data?.max_logins;

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={`${t('sessionsTitle', 'Login Diagnostics')} — ${user?.name || ''}`} size="large">
      {error && <div className="error-message">{error}</div>}
      {loading ? <p>{t('loading', 'Loading...')}</p> : (
        <>
          <div className="diagnostic-summary">
            <span className="status-active">Active/Max: {active}/{max}</span>
            <span>Mode: {data?.mode || '-'}</span>
            <span>Policy: {policy || '-'}</span>
            <span>Registry: {registry.length}</span>
          </div>
          <p className="diagnostic-recommendation">{data?.recommendation || t('noRecommendation', 'No recommendation available.')}</p>

          <h4>{t('node', 'Node')} sessions</h4>
          <div className="table-container" style={{ maxHeight: 340, overflow: 'auto' }}>
            <table className="list-table">
              <thead>
                <tr>
                  <th>{t('node', 'Node')}</th>
                  <th>{t('commonName', 'Common name')}</th>
                  <th>{t('liveSessions', 'Live')}</th>
                  <th>{t('authErrors', 'Auth events')}</th>
                </tr>
              </thead>
              <tbody>
                {nodes.length ? nodes.map((n, i) => (
                  <tr key={i}>
                    <td>{n.node}</td>
                    <td>{n.common_name}</td>
                    <td>{fmt(n.live_count)}</td>
                    <td>{fmt(n.auth_events)}</td>
                  </tr>
                )) : <tr><td colSpan={4} style={{ textAlign: 'center', color: 'var(--muted)' }}>{t('noNodeSessions', 'No node sessions.')}</td></tr>}
              </tbody>
            </table>
          </div>

          <h4>{t('registry', 'Global registry')}</h4>
          <div className="table-container" style={{ maxHeight: 280, overflow: 'auto' }}>
            <table className="list-table">
              <thead>
                <tr>
                  <th>{t('commonName', 'Common name')}</th>
                  <th>{t('lastSeen', 'Last seen')}</th>
                  <th>{t('node', 'Node')}</th>
                  <th>{t('stale', 'Stale')}</th>
                </tr>
              </thead>
              <tbody>
                {registry.length ? registry.map((r, i) => (
                  <tr key={i}>
                    <td>{r.common_name}</td>
                    <td>{r.last_seen}</td>
                    <td>{r.node || '-'}</td>
                    <td>{r.stale ? '⚠' : '—'}</td>
                  </tr>
                )) : <tr><td colSpan={4} style={{ textAlign: 'center', color: 'var(--muted)' }}>{t('noRegistryEntries', 'No registry entries.')}</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}
      <div className="modal-footer">
        <button type="button" className="btn btn-secondary" onClick={onRefresh}>{t('refresh', 'Refresh')}</button>
        <button type="button" className="btn btn-danger" onClick={onDisconnect}>{t('disconnect', 'Disconnect sessions')}</button>
      </div>
    </Modal>
  );
};

export default UserSessionsModal;