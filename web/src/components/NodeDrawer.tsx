import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  FiActivity, FiShield, FiCheck, FiCpu, FiDownload, FiGlobe, FiPower, FiRefreshCw,
  FiSave, FiTrash2, FiX, FiZap,
} from 'react-icons/fi';
import apiClient from '../services/api';
import { formatBytes } from '../utils/format';
import { CODES } from '../utils/geo';
import { Button, Field, Tabs } from './ui';
import './NodeDrawer.css';

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

const apiError = (e: any, fallback: any) => {
  const detail = e?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((d: any) => d?.msg || '').filter(Boolean).join(', ');
  if (typeof e?.response?.data?.msg === 'string') return e.response.data.msg;
  return fallback;
};

const NodeDrawer = ({
  node,
  initialTab = 'overview',
  onClose,
  onDelete,
  onDownloadAll,
  onChanged,
}: { node?: any; initialTab?: any; onClose?: any; onDelete?: any; onDownloadAll?: any; onChanged?: any }) => {
  const { t } = useTranslation();
  const drawerRef = useRef<any>(null);
  const previousFocusRef = useRef<any>(null);
  const onCloseRef = useRef<any>(onClose);
  useEffect(() => { onCloseRef.current = onClose; }, [onClose]);

  const [tab, setTab] = useState(initialTab);
  const [status, setStatus] = useState<any>(null);
  const [statusState, setStatusState] = useState('loading');
  const [enabled, setEnabled] = useState(Boolean(node?.status));
  const [busy, setBusy] = useState('');
  const [results, setResults] = useState<any>({});

  // Node endpoint edit state
  const [formData, setFormData] = useState({
    name: node?.name || '',
    address: node?.address || '',
    port: node?.port || 2083,
    ovpn_port: node?.ovpn_port || 1194,
    protocol: node?.protocol || 'udp',
    tunnel_address: node?.tunnel_address || '',
    country_code: node?.country_code || '',
    key: '',
    cert: '',
  });

  // Settings state (DNS, IPv6, Extra Ports)
  const [dns1, setDns1] = useState('');
  const [dns2, setDns2] = useState('');
  const [ipv6On, setIpv6On] = useState(false);
  const [ipv6Prefix, setIpv6Prefix] = useState('');
  const [extraPorts, setExtraPorts] = useState(node?.extra_ports || '');

  useEffect(() => {
    if (node) {
      setFormData({
        name: node.name || '',
        address: node.address || '',
        port: node.port || 2083,
        ovpn_port: node.ovpn_port || 1194,
        protocol: node.protocol || 'udp',
        tunnel_address: node.tunnel_address || '',
        country_code: node.country_code || '',
        key: '',
        cert: '',
      });
      setExtraPorts(node.extra_ports || '');
      setEnabled(Boolean(node.status));
    }
  }, [node]);

  const setResult = (key: any, ok: any, text: any) => setResults((prev: any) => ({ ...prev, [key]: { ok, text } }));

  const loadStatus = useCallback(async () => {
    if (!node) return;
    setStatusState('loading');
    try {
      const res = await apiClient.get(`/nodes/${node.id}/status`);
      const data = res.data?.data || null;
      setStatus(data);
      if (data?.node?.extra_ports !== undefined) {
        setExtraPorts(data.node.extra_ports);
      }
      setStatusState('ready');
    } catch {
      setStatusState('error');
    }
  }, [node]);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  useEffect(() => {
    if (!node) return undefined;
    previousFocusRef.current = document.activeElement;
    const dialog = drawerRef.current;
    if (dialog) {
      const firstInput = dialog.querySelector('input:not([disabled]), textarea:not([disabled]), select:not([disabled])');
      if (firstInput) firstInput.focus();
      else if (dialog.querySelectorAll(FOCUSABLE)[0]) dialog.querySelectorAll(FOCUSABLE)[0].focus();
      else dialog.focus();
    }

    const onKeyDown = (e: any) => {
      if (e.key === 'Escape') { onCloseRef.current?.(); return; }
      if (e.key !== 'Tab' || !dialog) return;
      const focusable: any[] = Array.from(dialog.querySelectorAll(FOCUSABLE)).filter(
        (el: any) => !el.closest('[aria-hidden="true"]')
      );
      if (!focusable.length) { e.preventDefault(); return; }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      if (previousFocusRef.current && typeof previousFocusRef.current.focus === 'function') {
        previousFocusRef.current.focus();
      }
    };
  }, [node]);

  const run = async (key: any, fn: any) => {
    setBusy(key);
    setResult(key, null, '');
    try {
      await fn();
    } catch (e: any) {
      setResult(key, false, apiError(e, t('nodeRequestFailed', 'The panel could not reach the node.')));
    } finally {
      setBusy('');
    }
  };

  const handleFormChange = (e: any) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const applyNodeEdit = () => run('edit', async () => {
    const payload: any = {
      name: formData.name.trim(),
      address: formData.address.trim(),
      port: Number(formData.port),
      ovpn_port: Number(formData.ovpn_port),
      protocol: formData.protocol || 'udp',
      tunnel_address: formData.tunnel_address.trim() || null,
      country_code: formData.country_code || null,
      status: enabled,
    };
    if (formData.key.trim()) payload.key = formData.key.trim();
    if (formData.cert.trim()) payload.cert = formData.cert.trim();

    const res = await apiClient.put(`/nodes/${node.id}`, payload);
    const ok = Boolean(res.data?.success);
    setResult('edit', ok, res.data?.msg || (ok ? t('saved', 'Saved.') : t('nodeUpdateFailed', 'Could not update the node.')));
    if (ok) onChanged?.();
  });

  const applyDns = () => run('dns', async () => {
    const body: any = {};
    if (dns1.trim()) body.dns1 = dns1.trim();
    if (dns2.trim()) body.dns2 = dns2.trim();
    const res = await apiClient.put(`/nodes/${node.id}/dns`, body);
    setResult('dns', Boolean(res.data?.success), res.data?.msg || '');
    if (res.data?.success) { setDns1(''); setDns2(''); }
  });

  const applyIpv6 = () => run('ipv6', async () => {
    const body: any = { enable_ipv6: ipv6On };
    if (ipv6Prefix.trim()) body.ipv6_prefix = ipv6Prefix.trim();
    const res = await apiClient.put(`/nodes/${node.id}/ipv6`, body);
    setResult('ipv6', Boolean(res.data?.success), res.data?.msg || '');
    if (res.data?.success) setIpv6Prefix('');
  });

  const applyPorts = () => run('ports', async () => {
    const res = await apiClient.put(`/nodes/${node.id}/ports`, { extra_ports: extraPorts.trim() });
    const ok = Boolean(res.data?.success);
    setResult('ports', ok, res.data?.msg || (ok ? t('saved', 'Saved.') : 'Failed to save extra ports'));
    if (ok) onChanged?.();
  });

  const checkNow = () => run('check', async () => {
    const res = await apiClient.get(`/nodes/${node.id}/status`);
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

  const repinCert = () => run('repin', async () => {
    const res = await apiClient.post(`/nodes/${node.id}/repin`);
    const data = res.data || {};
    setResult('repin', Boolean(data.success), data.msg || t('nodeRequestFailed', 'The panel could not reach the node.'));
    if (data.success) { loadStatus(); onChanged?.(); }
  });

  const updateSoftware = () => run('update', async () => {
    const res = await apiClient.post(`/nodes/${node.id}/update`);
    const data = res.data || {};
    setResult('update', Boolean(data.success), data.msg || t('nodeRequestFailed', 'The panel could not reach the node.'));
  });

  const downloadAll = async () => {
    if (onDownloadAll) {
      await onDownloadAll(node);
      setResult('download', true, t('nodeDownloadStarted', 'Download started.'));
      return;
    }
    const r = await apiClient.get(`/nodes/ovpn-all/${node.id}`, { responseType: 'blob' });
    const blob = new Blob([r.data], { type: 'application/zip' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${node.name}-all-configs.zip`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
    setResult('download', true, t('nodeDownloadStarted', 'Download started.'));
  };

  const toggleStatus = () => run('toggle', async () => {
    const next = !enabled;
    const res = await apiClient.put(`/nodes/${node.id}`, {
      name: node.name,
      address: node.address,
      status: next,
    });
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

  const info = status?.node_info;
  const sessions = status?.session_diagnostics;
  const reachable = status?.reachable;
  const latency = status?.latency_ms;
  const cpu = info?.cpu_usage;
  const mem = info?.memory_usage;
  const certExpiry = info?.cert_expiry;
  const live = sessions?.live_count ?? (Array.isArray(sessions?.live_sessions) ? sessions.live_sessions.length : 0);
  const liveList = Array.isArray(sessions?.live_sessions) ? sessions.live_sessions : [];

  return (
    <div className="node-drawer-backdrop" onClick={onClose} role="presentation" onKeyDown={(e) => { if (e.key === 'Escape') onClose(); }}>
      <aside
        ref={drawerRef}
        className="node-drawer"
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        aria-label={`${node.name} — ${t('nodeDetails', 'Node details')}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="node-drawer-head">
          <div className="nd-identity">
            <span className="avatar-xs">{String(node.name || '?').slice(0, 2).toUpperCase()}</span>
            <div>
              <strong>{node.name}</strong>
              <small>{node.address} · Port {node.port}</small>
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
              <CertPinSection pin={status?.cert_pin} onRepin={repinCert} busy={busy} result={results.repin} />
              {certExpiry && <CertExpiryChip expiry={certExpiry} />}
              {statusState === 'error' && <p className="nd-note">{t('nodeNoStatus', 'No live status yet — check the node.')}</p>}

              {liveList.length > 0 && (
                <div className="nd-list">
                  {liveList.map((s: any, i: number) => (
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
              </div>
              <ResultLine result={results.check} />
            </div>
          )}

          {tab === 'settings' && (
            <div className="nd-stack">
              {/* 1. Connection & Endpoint Editing */}
              <section className="nd-section">
                <h3 className="nd-section-title">{t('nodeSectionConnection', 'Connection')}</h3>
                <div className="nd-grid-2">
                  <Field label={t('nodeName')}>
                    <input type="text" name="name" value={formData.name} onChange={handleFormChange} />
                  </Field>
                  <Field label={t('th_address')}>
                    <input type="text" name="address" value={formData.address} onChange={handleFormChange} />
                  </Field>
                  <Field label={t('nodePort')}>
                    <input type="number" name="port" value={formData.port} onChange={handleFormChange} min="1" max="65535" />
                  </Field>
                  <Field label={t('tunnelAddress', 'Tunnel address')}>
                    <input type="text" name="tunnel_address" value={formData.tunnel_address} onChange={handleFormChange} placeholder="e.g. 10.8.0.1" />
                  </Field>
                </div>

                <div className="nd-grid-2" style={{ marginTop: '8px' }}>
                  <Field label={t('th_protocol', 'Protocol')}>
                    <select name="protocol" value={formData.protocol} onChange={handleFormChange}>
                      <option value="udp">UDP</option>
                      <option value="tcp">TCP</option>
                    </select>
                  </Field>
                  <Field label={t('ovpnPort', 'OpenVPN port')}>
                    <input type="number" name="ovpn_port" value={formData.ovpn_port} onChange={handleFormChange} min="1" max="65535" />
                  </Field>
                </div>

                <div style={{ marginTop: '8px' }}>
                  <Field label={t('nodeCountry', 'Country')}>
                    <select name="country_code" value={formData.country_code} onChange={handleFormChange}>
                      <option value="">{t('nodeCountryAuto', 'Auto-detect from IP')}</option>
                      {Object.entries(CODES).map(([code, entry]) => (
                        <option key={code} value={code}>{entry.name}</option>
                      ))}
                    </select>
                  </Field>
                </div>

                <div style={{ marginTop: '8px' }}>
                  <Field label={t('key', 'API key')} hint={t('certFieldHint', 'Paste the full PEM from node install. Used for TLS verification.')}>
                    <input type="text" name="key" value={formData.key} onChange={handleFormChange} placeholder={t('keyKeepExistingHint', 'Leave blank to keep the current key')} autoComplete="off" />
                  </Field>
                </div>

                <div style={{ marginTop: '8px' }}>
                  <Field label={t('certFieldLabel', 'Certificate (PEM)')} hint={t('certFieldHint', 'Paste the full PEM from node install. Used for TLS verification.')}>
                    <textarea name="cert" value={formData.cert} onChange={handleFormChange} rows={3} placeholder={t('certFieldPlaceholder', '-----BEGIN CERTIFICATE-----')} />
                  </Field>
                </div>

                <div className="nd-section-foot">
                  <Button size="sm" variant="primary" loading={busy === 'edit'} disabled={Boolean(busy) && busy !== 'edit'} icon={<FiSave size={12} />} onClick={applyNodeEdit}>
                    {busy === 'edit' ? t('nodeApplying', 'Applying...') : t('updateNodeButton', 'Save changes')}
                  </Button>
                </div>
                <ResultLine result={results.edit} />
              </section>

              {/* 2. Extra Ports with Persistent Save */}
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

              {/* 3. DNS Servers */}
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

              {/* 4. IPv6 */}
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
                  {t('nodeRestartButton', 'Restart VPN')}
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
                  icon={<FiRefreshCw size={12} aria-hidden="true" />} onClick={renewCert}
                >
                  {t('nodeRenewCertButton', 'Renew certificate')}
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
                  {t('nodeUpdateButton', 'Update node')}
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

const ResultLine = ({ result }: { result?: any }) => {
  if (!result?.text) return null;
  return (
    <p className={`nd-result${result.ok ? ' is-ok' : ' is-error'}`} role={result.ok ? 'status' : 'alert'}>
      {result.ok && <FiCheck size={12} aria-hidden="true" />}
      {result.text}
    </p>
  );
};

const NodeLogsTab = ({ nodeId }: { nodeId?: any }) => {
  const { t } = useTranslation();
  const [level, setLevel] = useState('WARNING');
  const [logs, setLogs] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (lv: any) => {
    setLoading(true);
    try {
      const r = await apiClient.get(`/nodes/${nodeId}/logs`, { params: { level: lv, limit: 100 } });
      const data = r.data?.data || {};
      setLogs({
        records: Array.isArray(data.records) ? data.records : [],
        lastError: data.last_error || null,
        errors1h: data.errors_1h || 0,
      });
    } catch {
      setLogs({ records: [], lastError: null, failed: true });
    } finally {
      setLoading(false);
    }
  }, [nodeId]);

  useEffect(() => { load(level); }, [load, level]);

  return (
    <div className="nd-stack">
      <div className="nd-logbar">
        <label className="nd-loglevel">
          <span>{t('logLevel', 'Level')}</span>
          <select value={level} onChange={(e) => setLevel(e.target.value)}>
            <option value="DEBUG">DEBUG</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
          </select>
        </label>
        <Button size="sm" variant="secondary" icon={<FiRefreshCw size={12} aria-hidden="true" />} onClick={() => load(level)}>
          {t('refreshLogs', 'Refresh')}
        </Button>
      </div>

      {logs?.lastError && (
        <div className="nd-logerror" role="alert">{logs.lastError}</div>
      )}

      {loading && logs === null ? (
        <div className="nd-empty">{t('loading', 'Loading…')}</div>
      ) : logs?.failed ? (
        <div className="nd-empty">{t('nodeLogsFailed', 'Could not load node logs.')}</div>
      ) : logs?.records?.length ? (
        <>
        <div className="nd-loglist" tabIndex={0} role="region" aria-label={t('nodeTabLogs', 'Logs')}>
          {logs.records.slice().reverse().map((r: any, i: number) => (
            <div key={i} className={`nd-log nd-log--${(r.level || '').toLowerCase()}`}>
              <span className="nd-log-time">{r.time?.slice(11, 19) || '—'}</span>
              <span className="nd-log-msg">[{r.level}] {r.message}{r.where ? ` (${r.where})` : ''}</span>
            </div>
          ))}
        </div>
        </>
      ) : (
        <div className="nd-empty">{t('nodeLogsEmpty', 'No log records at this level.')}</div>
      )}
    </div>
  );
};

const TlsChip = ({ status, t }: { status?: any; t?: any }) => {
  const pin = status?.cert_pin;
  const verified = status?.tls_verified;
  const mode = status?.tls_mode;
  if (!status) return null;

  let label = t('tlsVerified', 'Encrypted');
  let tone = 'is-ok';
  if (mode === 'plain') {
    label = t('tlsPlain', 'Plain HTTP');
    tone = 'is-critical';
  } else if (!verified || mode === 'unverified-self-signed') {
    label = t('tlsSelfSigned', 'Self-signed');
    tone = 'is-soon';
  } else if (pin?.pinned && !pin.match) {
    label = t('nodeTlsPinMismatch', 'Pin does NOT match the live certificate');
    tone = 'is-critical';
  }

  return (
    <div className={`nd-cert ${tone}`}>
      <FiShield size={13} aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
};

const CertPinSection = ({ pin, onRepin, busy, result }: { pin?: any; onRepin?: any; busy?: any; result?: any }) => {
  const { t } = useTranslation();
  if (!pin?.pinned) return null;

  const expiry = pin.expiry ? new Date(pin.expiry).toLocaleDateString() : '—';
  const match = pin.match;

  return (
    <section className="nd-pin">
      <div className="nd-pin-head">
        <span className="nd-pin-title">{t('nodeTlsPinTitle', 'TLS certificate pin')}</span>
        <span className={`nd-pin-chip ${match ? 'is-ok' : 'is-mismatch'}`}>
          {match ? t('nodeTlsPinMatch', 'Pin matches the live certificate') : t('nodeTlsPinMismatch', 'Pin does NOT match the live certificate')}
        </span>
      </div>
      <dl className="nd-pin-meta">
        <div><dt>{t('nodeTlsPinIssuer', 'Issuer')}</dt><dd>{pin.issuer || '—'}</dd></div>
        <div><dt>{t('nodeTlsPinExpiry', 'Expires')}</dt><dd>{expiry}</dd></div>
      </dl>
      <div className="nd-pin-foot">
        <Button size="sm" variant="secondary" loading={busy === 'repin'} disabled={Boolean(busy) && busy !== 'repin'} icon={<FiRefreshCw size={12} aria-hidden="true" />} onClick={onRepin}>
          {t('nodeRepinButton', 'Re-pin from current cert')}
        </Button>
      </div>
      <ResultLine result={result} />
    </section>
  );
};

const CertExpiryChip = ({ expiry }: { expiry?: any }) => {
  const { t } = useTranslation();
  if (!expiry) return null;
  const now = new Date();
  const exp = new Date(expiry);
  const diffDays = Math.ceil((exp.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));

  if (diffDays <= 0) {
    return <div className="nd-cert is-expired">{t('certExpired', 'TLS certificate expired')}</div>;
  }
  if (diffDays <= 30) {
    return <div className="nd-cert is-soon">{t('certDaysLeft', 'TLS certificate expires in {{days}} days', { days: diffDays })}</div>;
  }
  return <div className="nd-cert is-ok">{t('certValidDays', 'TLS certificate valid — {{days}} days left', { days: diffDays })}</div>;
};

export default NodeDrawer;