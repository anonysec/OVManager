import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  FiX, FiActivity, FiGlobe, FiCpu, FiTrash2, FiRefreshCw, FiPower,
} from 'react-icons/fi';
import apiClient from '../services/api';
import { formatBytes } from '../utils/format';

/**
 * NodeDrawer — slide-over detail panel for a node.
 * Tabs: Overview · Sessions · Config · Danger.
 */
const NodeDrawer = ({ node, onClose, onEdit, onDelete, onToggleStatus, onCheckStatus }) => {
  const { t } = useTranslation();
  const [tab, setTab] = useState('overview');
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!node) return;
    setTab('overview');
    setStatus(null);
    const load = async () => {
      setLoading(true);
      try {
        const r = await apiClient.get(`/nodes/${node.id}/status/`);
        setStatus(r.data?.data || null);
      } catch { /* keep empty */ }
      finally { setLoading(false); }
    };
    load();
  }, [node]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  if (!node) return null;

  const info = status?.node_info || {};
  const sessions = status?.session_diagnostics || {};
  const live = Number(sessions?.live_count || 0);
  const latency = Number(status?.latency_ms || 0);
  const reachable = status?.reachable !== false;
  const cpu = Number(info?.cpu_usage);
  const mem = Number(info?.memory_usage);
  const certExpiry = info?.cert_expiry;

  const tabs = [
    { id: 'overview', label: t('nodeTabOverview', 'Overview') },
    { id: 'sessions', label: t('nodeTabSessions', 'Sessions') },
    { id: 'config', label: t('nodeTabConfig', 'Config') },
    { id: 'danger', label: t('nodeTabDanger', 'Danger'), danger: true },
  ];

  return (
    <div className="node-drawer-backdrop" onClick={onClose}>
      <aside className="node-drawer" role="dialog" aria-label={`${node.name} — ${t('nodeDetails', 'Node details')}`} onClick={(e) => e.stopPropagation()}>
        <div className="node-drawer-head">
          <div className="nd-identity">
            <span className="avatar-xs">{node.name.slice(0, 2).toUpperCase()}</span>
            <div>
              <strong>{node.name}</strong>
              <small>{node.address}:{node.port}</small>
            </div>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label={t('close', 'Close')}><FiX /></button>
        </div>

        <div className="node-drawer-tabs" role="tablist">
          {tabs.map(tb => (
            <button
              key={tb.id}
              type="button"
              role="tab"
              className={`nd-tab${tab === tb.id ? ' active' : ''}${tb.danger ? ' nd-tab-danger' : ''}`}
              onClick={() => setTab(tb.id)}
            >
              {tb.label}
            </button>
          ))}
        </div>

        <div className="node-drawer-body">
          {tab === 'overview' && (
            <div className="nd-stack">
              <div className="nd-grid">
                <div className="nd-cell"><FiActivity /><span>{t('status', 'Status')}</span><b className={reachable ? 'ok' : 'bad'}>{reachable ? t('statusOnline', 'Online') : t('statusOffline', 'Offline')}</b></div>
                <div className="nd-cell"><FiCpu /><span>{t('th_cpu', 'CPU')}</span><b>{Number.isFinite(cpu) ? `${cpu.toFixed(0)}%` : '—'}</b></div>
                <div className="nd-cell"><FiActivity /><span>{t('kv_memory', 'Memory')}</span><b>{Number.isFinite(mem) ? `${mem.toFixed(0)}%` : '—'}</b></div>
                <div className="nd-cell"><FiActivity /><span>{t('avgLatency', 'Latency')}</span><b>{latency ? `${latency.toFixed(0)}ms` : '—'}</b></div>
                <div className="nd-cell"><FiActivity /><span>{t('liveSessions', 'Live sessions')}</span><b>{live}</b></div>
                <div className="nd-cell"><FiGlobe /><span>{t('th_protocol', 'Protocol')}</span><b>{node.protocol || 'tcp'}</b></div>
              </div>
              {certExpiry && <CertExpiryChip expiry={certExpiry} />}
              <div className="nd-actions">
                <button className="btn btn-sm" onClick={() => onCheckStatus?.(node.id)}><FiRefreshCw size={12} /> {t('check', 'Check')}</button>
                <button className="btn btn-sm btn-secondary" onClick={() => onEdit(node)}>{t('edit', 'Edit')}</button>
              </div>
            </div>
          )}

          {tab === 'sessions' && (
            <div className="nd-stack">
              {loading ? (
                <div className="nd-empty">{t('loading', 'Loading…')}</div>
              ) : live > 0 ? (
                <div className="nd-list">
                  {(sessions.sessions || []).map((s, i) => (
                    <div key={i} className="nd-row">
                      <span className="nd-row-dot" />
                      <span className="nd-row-main">{s.common_name}</span>
                      <span className="nd-row-sub">{s.trusted_ip || ''}</span>
                      <span className="nd-row-meta">{formatBytes((s.bytes_received || 0) + (s.bytes_sent || 0))}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="nd-empty">{t('noLiveSessions', 'No live sessions right now.')}</div>
              )}
            </div>
          )}

          {tab === 'config' && (
            <div className="nd-stack">
              {[
                [t('th_address', 'Address'), `${node.address}:${node.port}`],
                [t('tunnelAddress', 'Tunnel address'), node.tunnel_address || '—'],
                [t('th_protocol', 'Protocol'), node.protocol || 'tcp'],
                [t('ovpnPort', 'OpenVPN port'), String(node.ovpn_port ?? '—')],
                [t('th_tls', 'TLS'), node.use_tls ? t('enabled', 'Enabled') : t('disabled', 'Disabled')],
                [t('th_status', 'Status'), node.status ? t('active', 'Active') : t('inactive', 'Inactive')],
              ].map(([k, v]) => (
                <div key={k} className="nd-kv"><span>{k}</span><b>{v}</b></div>
              ))}
            </div>
          )}

          {tab === 'danger' && (
            <div className="nd-stack">
              <div className="nd-danger-block">
                <strong>{t('toggleStatus', 'Toggle node status')}</strong>
                <p>{t('toggleStatusHint', 'Disable without deleting the record — node stops being used.')}</p>
                <button className="btn btn-sm btn-secondary" onClick={() => onToggleStatus?.(node)}>
                  <FiPower size={12} /> {node.status ? t('disable', 'Disable') : t('enable', 'Enable')}
                </button>
              </div>
              <div className="nd-danger-block nd-danger-block--red">
                <strong>{t('deleteNode', 'Delete node')}</strong>
                <p>{t('deleteNodeHint', 'Removes the node and its users from the panel. This cannot be undone.')}</p>
                <button className="btn btn-sm btn-danger" onClick={() => onDelete?.(node.id, node.name)}>
                  <FiTrash2 size={12} /> {t('deleteButton', 'Delete')}
                </button>
              </div>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
};

const CertExpiryChip = ({ expiry }) => {
  const { t } = useTranslation();
  const days = Math.ceil((new Date(expiry) - new Date()) / 86400000);
  const cls = days < 0 ? 'is-expired' : days <= 7 ? 'is-critical' : days <= 30 ? 'is-soon' : 'is-ok';
  return (
    <div className={`nd-cert ${cls}`}>
      <span>◈</span>
      {days < 0
        ? t('certExpired', 'TLS certificate expired')
        : days <= 30
          ? t('certDaysLeft', 'TLS certificate expires in {{days}} days', { days })
          : t('certValidDays', 'TLS certificate valid — {{days}} days left', { days })}
    </div>
  );
};

export default NodeDrawer;
