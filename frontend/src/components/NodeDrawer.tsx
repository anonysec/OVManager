import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  FiActivity, FiShield, FiCheck, FiCpu, FiDownload, FiGlobe, FiPower, FiRefreshCw,
  FiTrash2, FiX, FiZap,
} from 'react-icons/fi';
import apiClient from '../services/api';
import { formatBytes } from '../utils/format';
import { Button, Field, Tabs } from './ui';
import './NodeDrawer.css';

/**
 * NodeDrawer — slide-over detail panel for one node.
 *
 * Tabs: Overview (health/version/TLS/live users), Settings (DNS, IPv6,
 * extra ports), Actions (restart/update/download/enable/delete) and Logs.
 * Settings and Actions always print the backend's own message, because the
 * node's answer is the only reliable source of what actually happened.
 */

const apiError = (e, fallback) => {
  const detail = e?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((d) => d?.msg || '').filter(Boolean).join(', ');
  if (typeof e?.response?.data?.msg === 'string') return e.response.data.msg;
  return fallback;
};

const NodeDrawer = ({
  node,
  initialTab = 'overview',
  onClose,
  onEdit,
  onDelete,
  onDownloadAll,
  onChanged,
}) => {
  const { t } = useTranslation();
  const [tab, setTab] = useState(initialTab);
  const [status, setStatus] = useState(null);
  const [statusState, setStatusState] = useState('loading');
  const [enabled, setEnabled] = useState(Boolean(node?.status));
  const [busy, setBusy] = useState('');
  const [results, setResults] = useState({});
  const [dns1, setDns1] = useState('');
  const [dns2, setDns2] = useState('');
  const [ipv6On, setIpv6On] = useState(false);
  const [ipv6Prefix, setIpv6Prefix] = useState('');
  const [extraPorts, setExtraPorts] = useState('');

  const setResult = (key, ok, text) => setResults((prev) => ({ ...prev, [key]: { ok, text } }));

  const loadStatus = useCallback(async () => {
    if (!node) return;
    setStatusState('loading');
    try {
      const res = await apiClient.get(`/nodes/${node.id}/status/`);
      setStatus(res.data?.data || null);
      setStatusState('ready');
    } catch {
      setStatusState('error');
    }
  }, [node]);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const run = async (key, fn) => {
    setBusy(key);
    setResult(key, null, '');
    try {
      await fn();
    } catch (e) {
      setResult(key, false, apiError(e, t('nodeRequestFailed', 'The panel could not reach the node.')));
    } finally {
      setBusy('');
    }
  };

  const info = status?.node_info || {};
  const sessions = status?.session_diagnostics || {};
  const live = Number(sessions?.live_count ?? 0);
  const liveList = useMemo(() => {
    const raw = status?.session_diagnostics || {};
    if (Array.isArray(raw.live_sessions)) return raw.live_sessions;
    if (Array.isArray(raw.sessions)) return raw.sessions;
    return [];
  }, [status]);
  const reachable = status?.reachable === true || (status?.reachable === undefined && Boolean(status?.node_info) && statusState === 'ready');
  const latency = Number(status?.latency_ms || 0);
  const cpu = Number(info?.cpu_usage);
  const mem = Number(info?.memory_usage);
  const certExpiry = info?.cert_expiry;

  const applyDns = () => run('dns', async () => {
    const body = {};
    if (dns1.trim()) body.dns1 = dns1.trim();
    if (dns2.trim()) body.dns2 = dns2.trim();
    if (!body.dns1 && !body.dns2) {
      setResult('dns', false, t('nodeKeepCurrentHint', 'Leave empty to keep the current value.'));
      return;
    }
    const res = await apiClient.put(`/nodes/${node.id}/dns`, body);
    setResult('dns', Boolean(res.data?.success), res.data?.msg || '');
    if (res.data?.success) { setDns1(''); setDns2(''); }
  });

  const applyIpv6 = () => run('ipv6', async () => {
    const body = { enable_ipv6: ipv6On };
    if (ipv6Prefix.trim()) body.ipv6_prefix = ipv6Prefix.trim();
    const res = await apiClient.put(`/nodes/${node.id}/ipv6`, body);
    setResult('ipv6', Boolean(res.data?.success), res.data?.msg || '');
    if (res.data?.success) setIpv6Prefix('');
  });

  const applyPorts = () => run('ports', async () => {
    const res = await apiClient.put(`/nodes/${node.id}/ports`, { extra_ports: extraPorts.trim() });
    setResult('ports', Boolean(res.data?.success), res.data?.msg || '');
    if (res.data?.success) setExtraPorts('');
  });

  const checkNow = () => run('check', async () => {
    const res = await apiClient.get(`/nodes/${node.id}/status/`);
    if (res.data?.data) setStatus(res.data.data);
    setResult('check', Boolean(res.data?.success), res.data?.msg || t('nodeStatusCheckDone', 'Status check complete.'));
  });

  const restartVpn = () => run('restart', async () => {
    const res = await apiClient.post(`/nodes/${node.id}/restart`);
    const data = res.data || {};
    const msg = data.msg || t('nodeRequestFailed', 'The panel could not reach the node.');
    setResult('restart', Boolean(data.success), data.success && data.data?.openvpn_running === false
      ? `${msg} ${t('nodeOpenVpnStopped', 'The node reports OpenVPN is not running.')}`
      : msg);
    onChanged?.();
  });

  const renewCert = () => run('renewCert', async () => {
    const res = await apiClient.post(`/nodes/${node.id}/renew-cert`);
    const data = res.data || {};
    const msg = data.msg || t('nodeRequestFailed', 'The panel could not reach the node.');
    const expiry = data.data?.server_expiry;
    setResult('renewCert', Boolean(data.success), data.success && expiry
      ? `${msg} (${t('nodeRenewCertExpiry', 'new expiry')}: ${expiry})`
      : msg);
    onChanged?.();
  });

  const updateSoftware = () => run('update', async () => {
    const res = await apiClient.post(`/nodes/${node.id}/update`);
    const data = res.data || {};
    setResult('update', Boolean(data.success), data.msg || t('nodeRequestFailed', 'The panel could not reach the node.'));
    onChanged?.();
  });

  const downloadAll = () => run('download', async () => {
    if (onDownloadAll) {
      await onDownloadAll(node);
      setResult('download', true, t('nodeDownloadStarted', 'Download started.'));
      return;
    }
    const response = await apiClient.get(`/nodes/ovpn-all/${node.id}`, { responseType: 'blob', timeout: 300000 });
    const blob = new Blob([response.data], { type: 'application/zip' });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `ovpn-configs-${node.name}.zip`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
    setResult('download', true, t('nodeDownloadStarted', 'Download started.'));
  });

  const toggleStatus = () => run('toggle', async () => {
    const next = !enabled;
    const res = await apiClient.put(`/nodes/${node.id}`, {
      name: node.name,
      address: node.address,
      tunnel_address: node.tunnel_address || null,
      protocol: node.protocol || 'udp',
      ovpn_port: Number(node.ovpn_port || 1194),
      port: Number(node.port || 2083),
      status: next,
      set_new_setting: false,
      use_tls: Boolean(node.use_tls),
    });
    setResult('toggle', Boolean(res.data?.success), res.data?.msg || (next
      ? t('nodeEnabledToast', 'Node enabled.')
      : t('nodeDisabledToast', 'Node disabled.')));
    if (res.data?.success) {
      setEnabled(next);
      onChanged?.();
    }
  });

  if (!node) return null;

  const tabs = [
    { id: 'overview', label: t('nodeTabOverview', 'Overview') },
    { id: 'settings', label: t('nodeTabSettings', 'Settings') },
    { id: 'actions', label: t('nodeTabActions', 'Actions') },
    { id: 'logs', label: t('nodeTabLogs', 'Logs') },
  ];

  return (
    <div className="node-drawer-backdrop" onClick={onClose}>
      <aside
        className="node-drawer"
        role="dialog"
        aria-label={`${node.name} — ${t('nodeDetails', 'Node details')}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="node-drawer-head">
          <div className="nd-identity">
            <span className="avatar-xs">{String(node.name || '?').slice(0, 2).toUpperCase()}</span>
            <div>
              <strong>{node.name}</strong>
              <small>{node.address}:{node.port}</small>
            </div>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label={t('nodeClose', 'Close')}><FiX /></button>
        </div>

        <Tabs tabs={tabs} value={tab} onChange={setTab} ariaLabel={t('nodeDetails', 'Node details')} className="nd-tabs" />

        <div className="node-drawer-body" role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
          {tab === 'overview' && (
            <div className="nd-stack">
              <div className="nd-grid">
                <div className="nd-cell"><FiActivity /><span>{t('status', 'Status')}</span><b className={reachable ? 'ok' : 'bad'}>{reachable ? t('statusOnline', 'Online') : t('statusOffline', 'Offline')}</b></div>
                <div className="nd-cell"><FiZap /><span>{t('nodeVersion', 'Version')}</span><b>{info?.version || '—'}</b></div>
                <div className="nd-cell"><FiCpu /><span>{t('th_cpu', 'CPU%')}</span><b>{Number.isFinite(cpu) ? `${cpu.toFixed(0)}%` : '—'}</b></div>
                <div className="nd-cell"><FiActivity /><span>{t('kv_memory', 'Memory')}</span><b>{Number.isFinite(mem) ? `${mem.toFixed(0)}%` : '—'}</b></div>
                <div className="nd-cell"><FiActivity /><span>{t('avgLatency', 'Avg latency')}</span><b>{latency ? `${latency.toFixed(0)}ms` : '—'}</b></div>
                <div className="nd-cell"><FiGlobe /><span>{t('th_protocol', 'Protocol')}</span><b>{(node.protocol || 'udp').toUpperCase()} · {node.ovpn_port ?? '—'}</b></div>
              </div>

              <div className="nd-live">
                <span className="nd-live-count">{live}</span>
                <span className="nd-live-label">{t('liveSessions', 'Live sessions')}</span>
              </div>

              <TlsChip status={status} t={t} />
              {certExpiry && <CertExpiryChip expiry={certExpiry} />}
              {statusState === 'error' && <p className="nd-note">{t('nodeNoStatus', 'No live status yet — check the node.')}</p>}

              {liveList.length > 0 && (
                <div className="nd-list">
                  {liveList.map((s, i) => (
                    <div key={i} className="nd-row">
                      <span className="nd-row-dot" />
                      <span className="nd-row-main">{s.common_name}</span>
                      <span className="nd-row-sub">{s.trusted_ip || ''}</span>
                      <span className="nd-row-meta">{formatBytes((s.bytes_received || 0) + (s.bytes_sent || 0))}</span>
                    </div>
                  ))}
                </div>
              )}

              <div className="nd-actions">
                <Button size="sm" variant="secondary" loading={busy === 'check'} icon={<FiRefreshCw size={12} aria-hidden="true" />} onClick={checkNow}>
                  {t('checkStatus', 'Check Status')}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => onEdit?.(node)}>{t('editButton', 'Edit')}</Button>
              </div>
              <ResultLine result={results.check} />
            </div>
          )}

          {tab === 'settings' && (
            <div className="nd-stack">
              <p className="nd-note">{t('nodeSettingsNote', 'Saving any setting here reloads the VPN and briefly interrupts connected users.')}</p>

              <section className="nd-section">
                <h3 className="nd-section-title">{t('nodeDnsTitle', 'DNS servers')}</h3>
                <p className="nd-section-hint">{t('nodeDnsHint', 'DNS servers pushed to VPN clients. Leave a box empty to keep the current value.')}</p>
                <div className="nd-grid-2">
                  <Field label={t('nodeDns1', 'Primary DNS')}>
                    <input type="text" value={dns1} onChange={(e) => setDns1(e.target.value)} placeholder="1.1.1.1" disabled={busy === 'dns'} />
                  </Field>
                  <Field label={t('nodeDns2', 'Secondary DNS')}>
                    <input type="text" value={dns2} onChange={(e) => setDns2(e.target.value)} placeholder="1.0.0.1" disabled={busy === 'dns'} />
                  </Field>
                </div>
                <div className="nd-section-foot">
                  <Button size="sm" variant="primary" loading={busy === 'dns'} disabled={Boolean(busy) && busy !== 'dns'} onClick={applyDns}>
                    {busy === 'dns' ? t('nodeApplying', 'Applying...') : t('nodeApply', 'Apply')}
                  </Button>
                </div>
                <ResultLine result={results.dns} />
              </section>

              <section className="nd-section">
                <h3 className="nd-section-title">{t('nodeIpv6Title', 'IPv6')}</h3>
                <label className="nd-check">
                  <input type="checkbox" checked={ipv6On} onChange={(e) => setIpv6On(e.target.checked)} disabled={busy === 'ipv6'} />
                  <span>{t('nodeIpv6Enable', 'Enable IPv6 pool')}</span>
                </label>
                <Field label={t('nodeIpv6Prefix', 'IPv6 prefix')} hint={t('nodeIpv6PrefixHint', 'Example: fd42::/64')}>
                  <input type="text" value={ipv6Prefix} onChange={(e) => setIpv6Prefix(e.target.value)} placeholder="fd42::/64" disabled={busy === 'ipv6'} />
                </Field>
                <div className="nd-section-foot">
                  <Button size="sm" variant="primary" loading={busy === 'ipv6'} disabled={Boolean(busy) && busy !== 'ipv6'} onClick={applyIpv6}>
                    {busy === 'ipv6' ? t('nodeApplying', 'Applying...') : t('nodeApply', 'Apply')}
                  </Button>
                </div>
                <ResultLine result={results.ipv6} />
              </section>

              <section className="nd-section">
                <h3 className="nd-section-title">{t('nodePortsTitle', 'Extra ports')}</h3>
                <p className="nd-section-hint">{t('nodePortsHint', 'Extra ports the node opens for the VPN, like 443,8443. Leave empty to close them again.')}</p>
                <Field label={t('nodePortsTitle', 'Extra ports')}>
                  <input type="text" value={extraPorts} onChange={(e) => setExtraPorts(e.target.value)} placeholder="443,8443" disabled={busy === 'ports'} />
                </Field>
                <div className="nd-section-foot">
                  <Button size="sm" variant="primary" loading={busy === 'ports'} disabled={Boolean(busy) && busy !== 'ports'} onClick={applyPorts}>
                    {busy === 'ports' ? t('nodeApplying', 'Applying...') : t('nodeApply', 'Apply')}
                  </Button>
                </div>
                <ResultLine result={results.ports} />
              </section>
            </div>
          )}

          {tab === 'actions' && (
            <div className="nd-stack">
              <section className="nd-action">
                <div className="nd-action-text">
                  <h3>{t('nodeRestartTitle', 'Restart VPN')}</h3>
                  <p>{t('nodeRestartHint', 'Restarts OpenVPN on the node. Connected users drop and reconnect.')}</p>
                </div>
                <Button
                  size="sm" variant="secondary" loading={busy === 'restart'}
                  disabled={Boolean(busy) && busy !== 'restart'}
                  icon={<FiRefreshCw size={12} aria-hidden="true" />} onClick={restartVpn}
                >
                  {busy === 'restart' ? t('nodeRestarting', 'Restarting...') : t('nodeRestartButton', 'Restart VPN')}
                </Button>
                <ResultLine result={results.restart} />
              </section>

              <section className="nd-action">
                <div className="nd-action-text">
                  <h3>{t('nodeRenewCertTitle', 'Renew server certificate')}</h3>
                  <p>{t('nodeRenewCertHint', 'Issues a fresh OpenVPN server certificate and restarts OpenVPN. Clients reconnect automatically; use it when the certificate is near expiry.')}</p>
                </div>
                <Button
                  size="sm" variant="secondary" loading={busy === 'renewCert'}
                  disabled={Boolean(busy) && busy !== 'renewCert'}
                  icon={<FiShield size={12} aria-hidden="true" />} onClick={renewCert}
                >
                  {busy === 'renewCert' ? t('nodeRenewCerting', 'Renewing...') : t('nodeRenewCertButton', 'Renew certificate')}
                </Button>
                <ResultLine result={results.renewCert} />
              </section>

              <section className="nd-action">
                <div className="nd-action-text">
                  <h3>{t('nodeUpdateTitle', 'Update node software')}</h3>
                  <p>{t('nodeUpdateHint', 'Asks the node to update itself. Docker nodes must be updated from the host instead.')}</p>
                </div>
                <Button
                  size="sm" variant="secondary" loading={busy === 'update'}
                  disabled={Boolean(busy) && busy !== 'update'}
                  icon={<FiDownload size={12} aria-hidden="true" />} onClick={updateSoftware}
                >
                  {busy === 'update' ? t('nodeUpdating', 'Updating...') : t('nodeUpdateButton', 'Update node')}
                </Button>
                <ResultLine result={results.update} />
              </section>

              <section className="nd-action">
                <div className="nd-action-text">
                  <h3>{t('nodeDownloadTitle', 'Download all configs')}</h3>
                  <p>{t('nodeDownloadHint', 'Download every OpenVPN profile from this node as a ZIP file.')}</p>
                </div>
                <Button
                  size="sm" variant="secondary" loading={busy === 'download'}
                  disabled={Boolean(busy) && busy !== 'download'}
                  icon={<FiDownload size={12} aria-hidden="true" />} onClick={downloadAll}
                >
                  {t('downloadAll', 'Download all')}
                </Button>
                <ResultLine result={results.download} />
              </section>

              <section className="nd-action">
                <div className="nd-action-text">
                  <h3>{t('nodeToggleTitle', 'Enable or disable')}</h3>
                  <p>{t('nodeToggleHint', 'A disabled node stays in the panel but is no longer used for new users.')}</p>
                </div>
                <Button
                  size="sm" variant="secondary" loading={busy === 'toggle'}
                  disabled={Boolean(busy) && busy !== 'toggle'}
                  icon={<FiPower size={12} aria-hidden="true" />} onClick={toggleStatus}
                >
                  {enabled ? t('disableUser', 'Disable') : t('enableUser', 'Enable')}
                </Button>
                <ResultLine result={results.toggle} />
              </section>

              <section className="nd-action nd-action--danger">
                <div className="nd-action-text">
                  <h3>{t('deleteNode', 'Delete node')}</h3>
                  <p>{t('deleteNodeHint', 'Removes the node and its users from the panel. This cannot be undone.')}</p>
                </div>
                <Button
                  size="sm" variant="danger" icon={<FiTrash2 size={12} aria-hidden="true" />}
                  onClick={() => onDelete?.(node)}
                >
                  {t('deleteButton', 'Delete')}
                </Button>
              </section>
            </div>
          )}

          {tab === 'logs' && <NodeLogsTab nodeId={node.id} />}
        </div>
      </aside>
    </div>
  );
};

const ResultLine = ({ result }) => {
  if (!result?.text) return null;
  return (
    <p className={`nd-result${result.ok ? ' is-ok' : ' is-error'}`} role={result.ok ? 'status' : 'alert'}>
      {result.ok && <FiCheck size={12} aria-hidden="true" />}
      {result.text}
    </p>
  );
};

const NodeLogsTab = ({ nodeId }) => {
  const { t } = useTranslation();
  const [level, setLevel] = useState('WARNING');
  const [logs, setLogs] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (lv) => {
    setLoading(true);
    try {
      const r = await apiClient.get(`/nodes/${nodeId}/logs`, { params: { level: lv, limit: 100 } });
      const data = r.data?.data || {};
      setLogs({
        records: Array.isArray(data.records) ? data.records : [],
        lastError: data.last_error || null,
        errors: data.errors_1h || 0,
      });
    } catch {
      setLogs({ records: [], lastError: null, errors: 0, failed: true });
    } finally {
      setLoading(false);
    }
  }, [nodeId]);

  useEffect(() => { load(level); }, [load, level]);

  return (
    <div className="nd-stack">
      <div className="nd-logbar">
        <label className="nd-loglevel">
          {t('logLevel', 'Level')}
          <select value={level} onChange={(e) => setLevel(e.target.value)} aria-label={t('logLevel', 'Level')}>
            {['ERROR', 'WARNING', 'INFO'].map((lv) => (
              <option key={lv} value={lv}>{lv}</option>
            ))}
          </select>
        </label>
        <Button
          size="sm" variant="secondary" loading={loading}
          icon={<FiRefreshCw size={12} aria-hidden="true" />} onClick={() => load(level)}
        >
          {t('refreshLogs', 'Refresh')}
        </Button>
      </div>
      {logs?.lastError && (
        <div className="nd-logerror" role="alert">{logs.lastError}</div>
      )}
      {loading && logs === null ? (
        <div className="nd-empty">{t('loading', 'Loading...')}</div>
      ) : logs?.failed ? (
        <div className="nd-empty">{t('nodeLogsFailed', 'Could not load node logs.')}</div>
      ) : logs?.records?.length ? (
        <div className="nd-loglist">
          {logs.records.slice().reverse().map((r, i) => (
            <div key={i} className={`nd-log nd-log--${String(r.level || 'info').toLowerCase()}`}>
              <span className="nd-log-time">{r.time || ''}</span>
              <span className="nd-log-msg" title={r.where || ''}>{r.message || ''}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="nd-empty">{t('nodeLogsEmpty', 'No log records at this level.')}</div>
      )}
    </div>
  );
};

const TlsChip = ({ status, t }) => {
  const mode = status?.tls_mode;
  // 'unknown' = never connected (offline or legacy response): stay silent,
  // the Online/Offline cell already covers it.
  if (!mode || mode === 'verified' || mode === 'unknown') return null;
  if (mode === 'plain') {
    return (
      <div className="nd-cert is-critical" role="alert">
        <span aria-hidden="true">!</span>
        {t('tlsPlainDetail', 'Plain HTTP — API key crosses the network in cleartext. Enable TLS on the node.')}
      </div>
    );
  }
  return (
    <div className="nd-cert is-soon" role="alert">
      <span aria-hidden="true">!</span>
      {t('tlsUnverified', "Unverified TLS (self-signed) — no MITM protection. Switch the node to Let's Encrypt.")}
    </div>
  );
};

const CertExpiryChip = ({ expiry }) => {
  const { t } = useTranslation();
  const days = Math.ceil((new Date(expiry) - new Date()) / 86400000);
  const cls = days < 0 ? 'is-expired' : days <= 7 ? 'is-critical' : days <= 30 ? 'is-soon' : 'is-ok';
  return (
    <div className={`nd-cert ${cls}`}>
      <span aria-hidden="true">◆</span>
      {days < 0
        ? t('certExpired', 'TLS certificate expired')
        : days <= 30
          ? t('certDaysLeft', 'TLS certificate expires in {{days}} days', { days })
          : t('certValidDays', 'TLS certificate valid — {{days}} days left', { days })}
    </div>
  );
};

export default NodeDrawer;
