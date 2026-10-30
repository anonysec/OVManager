import { useTranslation } from 'react-i18next';
import Modal from './Modal';

type UserSessionsModalProps = {
  isOpen: boolean;
  user: any;
  data: any;
  loading: boolean;
  disconnecting?: boolean;
  error: string | null;
  onClose: () => void;
  onRefresh: () => void;
  onDisconnect: () => void;
};

const UserSessionsModal = ({ isOpen, user, data, loading, disconnecting = false, error, onClose, onRefresh, onDisconnect }: UserSessionsModalProps) => {
  const { t } = useTranslation();
  const nodes = Array.isArray(data?.nodes) ? data.nodes : [];
  const unavailableNodeCount = Math.max(
    0,
    Number(data?.unavailable_nodes) || 0,
    nodes.filter((node: any) => node?.reachable === false).length,
  );
  const totalNodeCount = Math.max(unavailableNodeCount, Number(data?.total_nodes) || 0, nodes.length);
  const hasPartialDiagnostics = Boolean(data?.partial) || unavailableNodeCount > 0;
  const hasRegistryPayload = Array.isArray(data?.global_registry);
  const registry = hasRegistryPayload ? data.global_registry : [];
  const registryUnavailable = Boolean(data?.global_registry_error) || !hasRegistryPayload;
  const nodeRows = nodes.map((node: any) => {
    const commonNames = [...new Set((Array.isArray(node.live_sessions) ? node.live_sessions : [])
      .map((session: any) => String(session?.common_name ?? '').trim())
      .filter(Boolean))];
    const unavailable = node.reachable === false;
    return {
      ...node,
      common_name: commonNames.join(', ') || (unavailable ? t('unavailable', 'Unavailable') : '—'),
      live_count: unavailable ? null : node.live_count ?? 0,
      auth_events: unavailable ? null : node.auth_events ?? node.auth_errors ?? 0,
    };
  });
  const fmt = (value: any) => value == null ? '—' : Number(value || 0).toLocaleString();

  const policy = (data?.policy || []).join(', ');
  const active = data?.active_connections ?? data?.totals?.live_count ?? 0;
  const max = data?.max_logins === 0 ? '∞' : (data?.max_logins ?? '—');

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={`${t('sessionsTitle', 'Login Diagnostics')} — ${user?.name || ''}`} size="large">
      {error && <div className="error-message" role="alert">{error}</div>}
      {loading ? <p>{t('loading', 'Loading...')}</p> : (
        <>
          <div className="diagnostic-summary">
            <span className="status-active">{t('activeMax', 'Active / Max')}: {active}/{max}</span>
            <span>{t('mode', 'Mode')}: {data?.mode || '-'}</span>
            <span>{t('policy', 'Policy')}: {policy || '-'}</span>
            <span>{t('registry', 'Registry')}: {registryUnavailable ? t('unavailable', 'Unavailable') : fmt(registry.length)}</span>
          </div>
          {hasPartialDiagnostics && (
            <p className="diagnostic-partial" role="status">
              {unavailableNodeCount > 0
                ? t('nodeDiagnosticsPartial', '{{unavailable}} of {{total}} nodes could not provide diagnostics; counts include reachable nodes only.', {
                  unavailable: unavailableNodeCount,
                  total: totalNodeCount,
                })
                : t('nodeDiagnosticsIncomplete', 'Node diagnostics are incomplete; counts may be partial.')}
            </p>
          )}
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
                {nodeRows.length ? nodeRows.map((n: any, i: number) => (
                  <tr key={`${n.node}-${i}`}>
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
          {registryUnavailable ? (
            <p style={{ textAlign: 'center', color: 'var(--muted)' }}>
              {t('registryUnavailable', 'The panel does not currently collect global registry data.')}
            </p>
          ) : (
            <div className="table-container" style={{ maxHeight: 280, overflow: 'auto' }}>
              <table className="list-table">
                <thead>
                  <tr>
                    <th>{t('commonName', 'Common name')}</th>
                    <th>{t('lastSeen', 'Last seen')}</th>
                    <th>{t('node', 'Node')}</th>
                  </tr>
                </thead>
                <tbody>
                  {registry.length ? registry.map((r: any, i: number) => (
                    <tr key={`${r.common_name}-${r.updated_at || r.created_at_utc}-${i}`}>
                      <td>{r.common_name}</td>
                      <td>{r.updated_at ? new Date(r.updated_at * 1000).toLocaleString() : (r.created_at_utc ? new Date(r.created_at_utc).toLocaleString() : '—')}</td>
                      <td>{r.node_name || r.node || '-'}</td>
                    </tr>
                  )) : <tr><td colSpan={3} style={{ textAlign: 'center', color: 'var(--muted)' }}>{t('noRegistryEntries', 'No registry entries.')}</td></tr>}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
      <div className="modal-footer">
        <button type="button" className="btn btn-secondary" onClick={onRefresh} disabled={loading || disconnecting}>{t('refresh', 'Refresh')}</button>
        <button type="button" className="btn btn-danger" onClick={onDisconnect} disabled={loading || disconnecting || active === 0}>{t('disconnect', 'Disconnect sessions')}</button>
      </div>
    </Modal>
  );
};

export default UserSessionsModal;