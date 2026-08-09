/**
 * Settings — single scrollable page, no sub-tabs.
 * All sections load together; anchor links jump to each category.
 */
import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useToast } from '../context/ToastContext';
import { useLive } from '../context/LiveContext';
import apiClient from '../services/api';
import LoadingButton from '../components/LoadingButton';
import PanelSkeleton from '../components/ui/PanelSkeleton';
import ErrorState from '../components/ui/ErrorState';
import EmptyState from '../components/ui/EmptyState';
import {
  FiSliders, FiServer, FiShield, FiArchive, FiSend, FiActivity,
  FiLink, FiEdit2, FiCheck, FiX, FiExternalLink,
  FiZap, FiRefreshCw, FiDownload, FiUpload, FiDatabase,
  FiBarChart2,
} from 'react-icons/fi';
import { formatBytes } from '../utils/format';
import { formatUptime, fmtDateTime } from '../utils/time';
import './Settings.css';
import '../components/SettingsStyles.css';

/* ─────────────────────────────────────────────
   Section header with anchor
───────────────────────────────────────────── */
const SectionHeader = ({ id, icon: Icon, label, description }) => (
  <div className="sp-section-header" id={id}>
    <span className="sp-section-icon"><Icon aria-hidden="true" /></span>
    <div>
      <h2>{label}</h2>
      {description && <p>{description}</p>}
    </div>
  </div>
);

/* ─────────────────────────────────────────────
   Card wrapper
───────────────────────────────────────────── */
const Card = ({ title, icon: Icon, children, className = '' }) => (
  <div className={`sp-card ${className}`}>
    {title && (
      <div className="sp-card-head">
        {Icon && <Icon size={15} aria-hidden="true" />}
        <span>{title}</span>
      </div>
    )}
    <div className="sp-card-body">{children}</div>
  </div>
);

/* ─────────────────────────────────────────────
   Field helpers
───────────────────────────────────────────── */
const Field = ({ label, hint, children, horizontal }) => (
  <div className={`sp-field${horizontal ? ' sp-field--h' : ''}`}>
    <label className="sp-label">{label}</label>
    {children}
    {hint && <p className="sp-hint">{hint}</p>}
  </div>
);

const Stat = ({ label, value, tone }) => (
  <div className={`sp-stat${tone ? ` sp-stat--${tone}` : ''}`}>
    <span>{label}</span>
    <strong>{value}</strong>
  </div>
);

/* ═══════════════════════════════════════════════════════
   GENERAL — Panel URL path
═══════════════════════════════════════════════════════ */
const GeneralSection = () => {
  const { t } = useTranslation();
  const { refreshTick } = useLive();
  const { addToast } = useToast();
  const [urlPath, setUrlPath] = useState('');
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [timezone, setTimezone] = useState('UTC');
  const [tzEditing, setTzEditing] = useState(false);
  const [tzValue, setTzValue] = useState('UTC');
  const [tzSaving, setTzSaving] = useState(false);
  const [subPrefix, setSubPrefix] = useState('');
  const [subPrefixEditing, setSubPrefixEditing] = useState(false);
  const [subPrefixValue, setSubPrefixValue] = useState('');
  const [subPrefixSaving, setSubPrefixSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const res = await apiClient.get('/server/settings');
      const s = res.data?.data || {};
      setUrlPath(s.urlpath || '');
      setTimezone(s.timezone || 'UTC');
      setSubPrefix(s.subscription_url_prefix || '');
    } catch { /* noop */ } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load, refreshTick]);

  const saveUrlPath = async () => {
    setSaving(true); setError('');
    try {
      const v = editValue.trim().replace(/^\/+|\/+$/g, '');
      if (v && !/^[A-Za-z0-9_-]+$/.test(v)) { setError(t('urlInvalid', 'Only letters, numbers, dashes and underscores.')); return; }
      if (v.length > 64) { setError(t('urlInvalid', 'Max 64 characters.')); return; }
      await apiClient.put('/server/settings/urlpath', { urlpath: v });
      setUrlPath(v); setEditing(false);
      addToast(t('saved', 'Saved.'), 'success');
    } catch (e) { setError(e.response?.data?.msg || t('error', 'Error')); }
    finally { setSaving(false); }
  };

  const saveTz = async () => {
    setTzSaving(true);
    try {
      await apiClient.put('/server/settings/timezone', { timezone: tzValue });
      setTimezone(tzValue); setTzEditing(false);
      addToast(t('saved', 'Saved.'), 'success');
    } catch (e) { addToast(e.response?.data?.msg || t('error', 'Error'), 'error'); }
    finally { setTzSaving(false); }
  };

  const saveSubPrefix = async () => {
    setSubPrefixSaving(true);
    try {
      await apiClient.put('/server/settings/subscription', { subscription_url_prefix: subPrefixValue.trim() });
      setSubPrefix(subPrefixValue.trim()); setSubPrefixEditing(false);
      addToast(t('saved', 'Saved.'), 'success');
    } catch (e) { addToast(e.response?.data?.msg || t('error', 'Error'), 'error'); }
    finally { setSubPrefixSaving(false); }
  };

  const panelUrl = urlPath
    ? `${window.location.origin}/${urlPath}/`
    : `${window.location.origin}/`;

  if (loading) return <PanelSkeleton lines={4} label="Loading…" />;

  return (
    <div className="sp-cards">
      {/* Panel URL */}
      <Card title={t('panelUrl', 'Panel URL')} icon={FiLink}>
        <div className="sp-url-row">
          <code className="sp-code">{urlPath ? `/${urlPath}/` : '/'}</code>
          {!editing && (
            <button className="sp-icon-btn" onClick={() => { setEditValue(urlPath); setEditing(true); setError(''); }} aria-label={t('change', 'Change')}>
              <FiEdit2 size={14} />
            </button>
          )}
        </div>
        {editing && (
          <div className="sp-inline-edit">
            <input
              type="text" value={editValue} autoFocus
              placeholder={t('enterPath', 'e.g. dashboard')}
              onChange={e => setEditValue(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') saveUrlPath(); if (e.key === 'Escape') setEditing(false); }}
              className="sp-input"
            />
            {error && <p className="sp-error">{error}</p>}
            <div className="sp-row-btns">
              <LoadingButton className="btn btn-sm" isLoading={saving} onClick={saveUrlPath}><FiCheck size={12} /> {t('save', 'Save')}</LoadingButton>
              <button className="btn btn-sm btn-secondary" onClick={() => setEditing(false)}><FiX size={12} /> {t('cancel', 'Cancel')}</button>
            </div>
          </div>
        )}
        <div className="sp-url-preview">
          <span className="sp-label-xs">{t('panelUrl', 'Full URL')}</span>
          <a href={panelUrl} target="_blank" rel="noopener noreferrer" className="sp-link">
            {panelUrl} <FiExternalLink size={11} />
          </a>
        </div>
        <p className="sp-hint">{urlPath ? t('urlpathActive', 'Panel served at /{path}/. Clear to serve at root.', { path: urlPath }) : t('urlpathRoot', 'Panel served at root (/).')}</p>
      </Card>

      {/* Timezone */}
      <Card title={t('timezoneCard', 'Display Timezone')} icon={FiSliders}>
        <div className="sp-url-row">
          <code className="sp-code">{timezone}</code>
          {!tzEditing && (
            <button className="sp-icon-btn" onClick={() => { setTzValue(timezone); setTzEditing(true); }} aria-label={t('change', 'Change')}>
              <FiEdit2 size={14} />
            </button>
          )}
        </div>
        {tzEditing && (
          <div className="sp-inline-edit">
            <input type="text" value={tzValue} autoFocus placeholder="Asia/Tehran" onChange={e => setTzValue(e.target.value)} className="sp-input" />
            <div className="sp-row-btns">
              <LoadingButton className="btn btn-sm" isLoading={tzSaving} onClick={saveTz}><FiCheck size={12} /> {t('save', 'Save')}</LoadingButton>
              <button className="btn btn-sm btn-secondary" onClick={() => setTzEditing(false)}><FiX size={12} /> {t('cancel', 'Cancel')}</button>
            </div>
          </div>
        )}
        <p className="sp-hint">{t('timezoneDesc', 'IANA timezone name used for all date/time displays (e.g. UTC, Asia/Tehran, Europe/Amsterdam).')}</p>
      </Card>

      {/* Subscription URL prefix */}
      <Card title={t('subscriptionLinkCard', 'Subscription URL Prefix')} icon={FiLink}>
        <div className="sp-url-row">
          <code className="sp-code sp-code--muted">{subPrefix || t('notSet', '(uses panel origin)')}</code>
          {!subPrefixEditing && (
            <button className="sp-icon-btn" onClick={() => { setSubPrefixValue(subPrefix); setSubPrefixEditing(true); }} aria-label={t('change', 'Change')}>
              <FiEdit2 size={14} />
            </button>
          )}
        </div>
        {subPrefixEditing && (
          <div className="sp-inline-edit">
            <input type="text" value={subPrefixValue} autoFocus placeholder="https://panel.example.com" onChange={e => setSubPrefixValue(e.target.value)} className="sp-input" />
            <div className="sp-row-btns">
              <LoadingButton className="btn btn-sm" isLoading={subPrefixSaving} onClick={saveSubPrefix}><FiCheck size={12} /> {t('save', 'Save')}</LoadingButton>
              <button className="btn btn-sm btn-secondary" onClick={() => setSubPrefixEditing(false)}><FiX size={12} /> {t('cancel', 'Cancel')}</button>
            </div>
          </div>
        )}
        <p className="sp-hint">{t('subscriptionLinkDesc', 'Override the base URL used in user subscription links. Leave empty to use the panel origin.')}</p>
      </Card>
    </div>
  );
};

/* ═══════════════════════════════════════════════════════
   SYSTEM — Server info + maintenance actions
═══════════════════════════════════════════════════════ */
const SystemSection = () => {
  const { t } = useTranslation();
  const { refreshTick } = useLive();
  const { addToast } = useToast();
  const [sysInfo, setSysInfo] = useState(null);
  const [trafficTotal, setTrafficTotal] = useState(null);
  const [activeConns, setActiveConns] = useState(0);
  const [busy, setBusy] = useState('');
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const [infoRes, metricsRes] = await Promise.all([
        apiClient.get('/server/info'),
        apiClient.get('/metrics/history?hours=24'),
      ]);
      setSysInfo(infoRes.data?.data || null);
      const traffic = metricsRes.data?.data?.traffic || [];
      if (traffic.length) {
        setTrafficTotal(traffic.reduce((s, h) => s + Number(h.total_used || 0), 0));
        setActiveConns(traffic[traffic.length - 1]?.active_connections || 0);
      }
    } catch { /* noop */ } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load, refreshTick]);

  const run = async (url, label) => {
    setBusy(url);
    try {
      await apiClient.post(url);
      addToast(label + ' ' + t('saved', 'done.'), 'success');
    } catch { addToast(t('error', 'Failed'), 'error'); }
    finally { setBusy(''); }
  };

  if (loading) return <PanelSkeleton lines={4} label="Loading…" />;

  return (
    <div className="sp-cards">
      {sysInfo && (
        <Card title={t('serverInfo', 'Server Info')} icon={FiServer}>
          <div className="sp-stats-grid">
            <Stat label={t('kv_uptime', 'Uptime')} value={formatUptime(sysInfo.uptime)} />
            <Stat label={t('kv_cpu', 'CPU')} value={`${Number(sysInfo.cpu || 0).toFixed(0)}%`} tone={sysInfo.cpu > 85 ? 'danger' : sysInfo.cpu > 70 ? 'warn' : null} />
            <Stat label={t('kv_memory', 'Memory')} value={`${Number(sysInfo.memory_percent || 0).toFixed(0)}%`} tone={sysInfo.memory_percent > 85 ? 'danger' : sysInfo.memory_percent > 70 ? 'warn' : null} />
            <Stat label={t('kv_disk', 'Disk')} value={`${Number(sysInfo.disk_percent || 0).toFixed(0)}%`} tone={sysInfo.disk_percent > 85 ? 'danger' : null} />
            {trafficTotal != null && <Stat label={t('totalTraffic', 'Traffic 24h')} value={formatBytes(trafficTotal)} />}
            <Stat label={t('activeConnections', 'Active Conns')} value={activeConns} />
          </div>
        </Card>
      )}
      <Card title={t('maintenanceCard', 'Maintenance')} icon={FiZap}>
        <p className="sp-hint" style={{ marginBottom: 12 }}>{t('maintenanceDesc', 'Run background jobs on demand. These also run automatically on a schedule.')}</p>
        <div className="sp-btn-group">
          <button className="btn btn-sm" disabled={!!busy} onClick={() => run('/metrics/collect', t('collectNow', 'Metrics'))}>
            {busy === '/metrics/collect' ? '…' : <><FiZap size={13} /> {t('collectNow', 'Collect metrics')}</>}
          </button>
          <button className="btn btn-sm btn-secondary" disabled={!!busy} onClick={() => run('/maintenance/sync-limits', t('syncLimits', 'Limits'))}>
            {busy === '/maintenance/sync-limits' ? '…' : <><FiRefreshCw size={13} /> {t('syncLimits', 'Sync limits')}</>}
          </button>
          <button className="btn btn-sm btn-secondary" disabled={!!busy} onClick={() => run('/maintenance/clean-stale', t('cleanStale', 'Stale'))}>
            {busy === '/maintenance/clean-stale' ? '…' : <><FiRefreshCw size={13} /> {t('cleanStale', 'Clean stale sessions')}</>}
          </button>
          <button className="btn btn-sm btn-secondary" disabled={!!busy} onClick={() => run('/maintenance/clean-global-registry', t('cleanRegistry', 'Registry'))}>
            {busy === '/maintenance/clean-global-registry' ? '…' : <><FiBarChart2 size={13} /> {t('cleanRegistry', 'Clean registry')}</>}
          </button>
        </div>
      </Card>
    </div>
  );
};

/* ═══════════════════════════════════════════════════════
   SECURITY — Auth summary
═══════════════════════════════════════════════════════ */
const SecuritySection = () => {
  const { t } = useTranslation();
  const { refreshTick } = useLive();
  const [hours, setHours] = useState(8);
  const [sec, setSec] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try { setLoading(true); setError(null); const r = await apiClient.get(`/security/summary?hours=${hours}`); setSec(r.data?.data || null); }
    catch { setError(t('failedToLoad', 'Failed to load')); } finally { setLoading(false); }
  }, [hours, t]);

  useEffect(() => { load(); }, [load, refreshTick]);

  return (
    <div className="sp-cards">
      <Card title={t('securityCard', 'Authentication Summary')} icon={FiShield}>
        <div className="sp-hours-toggle">
          {[4, 8, 12, 24, 48].map(h => (
            <button key={h} type="button" className={`sp-hour-btn${hours === h ? ' active' : ''}`} onClick={() => setHours(h)}>{h}h</button>
          ))}
        </div>
        {error && <ErrorState title={t('error', 'Error')} message={error} onRetry={load} />}
        {loading && !error && <PanelSkeleton lines={3} label="Loading…" />}
        {!loading && !error && sec && (
          <div className="sp-stats-grid">
            <Stat label={t('authErrors', 'Auth Errors')} value={sec.auth_errors || 0} tone={sec.auth_errors > 0 ? 'danger' : null} />
            <Stat label={t('rejects', 'Rejects')} value={sec.rejects || 0} tone={sec.rejects > 0 ? 'warn' : null} />
            <Stat label={t('staleMarkers', 'Stale Markers')} value={sec.stale_markers || 0} tone={sec.stale_markers > 5 ? 'warn' : null} />
          </div>
        )}
        {sec?.per_node?.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <p className="sp-label-xs" style={{ marginBottom: 6 }}>{t('th_node', 'Per Node')}</p>
            <div className="sp-node-list">
              {sec.per_node.map(n => (
                <div key={n.node} className="sp-node-row">
                  <span className="sp-node-name">{n.node}</span>
                  <span className={`sp-badge${n.auth_errors > 0 ? ' danger' : ''}`}>{n.auth_errors} err</span>
                  <span className="sp-badge">{n.live} live</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </Card>
    </div>
  );
};

/* ═══════════════════════════════════════════════════════
   BACKUP — Create, download, restore
═══════════════════════════════════════════════════════ */
const BackupSection = () => {
  const { t } = useTranslation();
  const { refreshTick } = useLive();
  const { addToast } = useToast();
  const [backups, setBackups] = useState([]);
  const [busy, setBusy] = useState('');
  const [restoreFile, setRestoreFile] = useState(null);

  const load = useCallback(async () => {
    try { const r = await apiClient.get('/maintenance/backup/list'); if (Array.isArray(r.data?.data)) setBackups(r.data.data); }
    catch { /* noop */ }
  }, []);

  useEffect(() => { load(); }, [load, refreshTick]);

  const create = async () => {
    setBusy('create');
    try {
      const r = await apiClient.post('/maintenance/backup');
      addToast(r.data?.msg || t('createBackup', 'Backup created'), 'success');
      load();
    } catch (e) { addToast(e.response?.data?.detail || t('error', 'Failed'), 'error'); }
    finally { setBusy(''); }
  };

  const download = async () => {
    try {
      const r = await apiClient.get('/maintenance/backup/download', { responseType: 'blob' });
      const url = URL.createObjectURL(new Blob([r.data]));
      const a = document.createElement('a'); a.href = url; a.download = 'ovmanager-backup.db';
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    } catch { addToast(t('error', 'Download failed'), 'error'); }
  };

  const restore = async () => {
    if (!restoreFile) return;
    setBusy('restore');
    try {
      const fd = new FormData(); fd.append('file', restoreFile);
      await apiClient.post('/maintenance/backup/restore', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
      addToast(t('restoreButton', 'Restored successfully'), 'success');
      setRestoreFile(null);
    } catch (e) { addToast(e.response?.data?.detail || t('error', 'Restore failed'), 'error'); }
    finally { setBusy(''); }
  };

  return (
    <div className="sp-cards">
      <Card title={t('backupTitle', 'Database Backup')} icon={FiDatabase}>
        <div className="sp-btn-group" style={{ marginBottom: 16 }}>
          <button className="btn btn-sm" disabled={!!busy} onClick={create}>
            {busy === 'create' ? '…' : <><FiUpload size={13} /> {t('createBackup', 'Create backup')}</>}
          </button>
          {backups.length > 0 && (
            <button className="btn btn-sm btn-secondary" onClick={download}>
              <FiDownload size={13} /> {t('downloadLatest', 'Download latest')}
            </button>
          )}
        </div>
        {backups.length > 0 && (
          <div className="sp-backup-list">
            {backups.slice(0, 8).map(b => (
              <div key={b.name} className="sp-backup-row">
                <FiDatabase size={13} style={{ color: 'var(--muted)' }} />
                <span className="sp-backup-name">{b.name}</span>
                {b.size && <span className="sp-backup-size">{formatBytes(b.size)}</span>}
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title={t('restoreSection', 'Restore from File')} icon={FiArchive}>
        <p className="sp-hint" style={{ marginBottom: 12 }}>{t('restoreButton', 'Select a .db backup file to restore. This will overwrite current data.')}</p>
        <div className="sp-field">
          <input type="file" accept=".db" onChange={e => setRestoreFile(e.target.files?.[0] || null)} className="sp-file-input" />
        </div>
        <button className="btn btn-sm" disabled={!restoreFile || !!busy} onClick={restore}>
          {busy === 'restore' ? '…' : <><FiRefreshCw size={13} /> {t('restoreButton', 'Restore')}</>}
        </button>
      </Card>
    </div>
  );
};

/* ═══════════════════════════════════════════════════════
   BOT — Telegram bot configuration
═══════════════════════════════════════════════════════ */
const BotSection = () => {
  const { t } = useTranslation();
  const { addToast } = useToast();
  const [token, setToken] = useState('');
  const [enabled, setEnabled] = useState(false);
  const [ownerId, setOwnerId] = useState('');
  const [defaultDays, setDefaultDays] = useState(30);
  const [defaultGb, setDefaultGb] = useState(100);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [encryptKeyMissing, setEncryptKeyMissing] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const r = await apiClient.get('/server/settings');
      const d = r.data?.data || {};
      setEnabled(d.bot_enabled || false);
      setOwnerId(d.owner_telegram_id || '');
      setDefaultDays(d.default_days || 30);
      setDefaultGb(d.default_traffic_gb || 100);
      setEncryptKeyMissing(false);
    } catch { /* noop */ } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        bot_enabled: enabled,
        owner_telegram_id: ownerId ? Number(ownerId) : null,
        default_days: Number(defaultDays) || 30,
        default_traffic_gb: Number(defaultGb) || 100,
        ...(token ? { bot_token: token } : {}),
      };
      const r = await apiClient.put('/server/settings/bot', payload);
      if (r.data?.success === false) {
        const msg = r.data?.msg || '';
        if (msg.toLowerCase().includes('encrypt')) setEncryptKeyMissing(true);
        addToast(msg || t('error', 'Error'), 'error');
      } else {
        addToast(t('saved', 'Bot settings saved.'), 'success');
        setToken(''); // clear token field — it's write-only
      }
    } catch (e) {
      const msg = e.response?.data?.detail || e.response?.data?.msg || t('error', 'Error');
      if (msg.toLowerCase().includes('encrypt')) setEncryptKeyMissing(true);
      addToast(msg, 'error');
    } finally { setSaving(false); }
  };

  const clearToken = async () => {
    setSaving(true);
    try {
      await apiClient.put('/server/settings/bot', { bot_token: null, bot_enabled: false });
      setEnabled(false); setToken('');
      addToast(t('tokenCleared', 'Bot token cleared.'), 'success');
    } catch (e) { addToast(e.response?.data?.detail || t('error', 'Error'), 'error'); }
    finally { setSaving(false); }
  };

  if (loading) return <PanelSkeleton lines={4} label="Loading…" />;

  return (
    <div className="sp-cards">
      <Card title={t('telegramBot', 'Telegram Bot')} icon={FiSend}>
        {encryptKeyMissing && (
          <div className="settings-alert settings-alert--error" role="alert" style={{ marginBottom: 16 }}>
            <strong>{t('botEncryptKeyMissing', 'BOT_ENCRYPT_KEY not set')}</strong>
            <p>{t('botEncryptKeyMissingDesc', 'Set BOT_ENCRYPT_KEY in your .env before saving a token.')}</p>
          </div>
        )}

        <Field label={t('botToken', 'Bot Token')} hint={t('botDesc', 'Obtain from @BotFather. Write-only — leave blank to keep the existing token.')}>
          <input className="sp-input" type="text" value={token} onChange={e => setToken(e.target.value)}
            placeholder="123456789:ABC…" disabled={encryptKeyMissing} />
        </Field>

        <Field label={t('ownerTelegramId', 'Owner Telegram ID')} hint="Your personal Telegram user ID — receives alerts.">
          <input className="sp-input" type="number" value={ownerId} onChange={e => setOwnerId(e.target.value)} placeholder="123456789" />
        </Field>

        <div className="sp-two-col">
          <Field label={t('modal_expiryDate', 'Default Days')}>
            <input className="sp-input" type="number" min={1} max={3650} value={defaultDays} onChange={e => setDefaultDays(e.target.value)} />
          </Field>
          <Field label="Default Traffic (GB)">
            <input className="sp-input" type="number" min={1} value={defaultGb} onChange={e => setDefaultGb(e.target.value)} />
          </Field>
        </div>

        <Field label={t('botEnabled', 'Enable Bot')} horizontal>
          <label className="sp-toggle">
            <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} disabled={encryptKeyMissing} />
            <span className="sp-toggle-track"><span className="sp-toggle-thumb" /></span>
          </label>
        </Field>

        <div className="sp-btn-group" style={{ marginTop: 20 }}>
          <LoadingButton className="btn btn-sm" isLoading={saving} onClick={save} disabled={encryptKeyMissing}>
            {t('save', 'Save settings')}
          </LoadingButton>
          <button className="btn btn-sm btn-secondary" onClick={clearToken} disabled={saving}>
            {t('clearToken', 'Clear token')}
          </button>
        </div>
      </Card>
    </div>
  );
};

/* ═══════════════════════════════════════════════════════
   ACTIVITY — Recent audit events
═══════════════════════════════════════════════════════ */
const ActivitySection = () => {
  const { t } = useTranslation();
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try { setLoading(true); setError(null); const r = await apiClient.get('/activity/?limit=50'); setEvents(r.data?.data || []); }
    catch { setError(t('failedToLoad', 'Failed to load')); } finally { setLoading(false); }
  }, [t]);

  useEffect(() => { load(); }, [load]);

  const ACTION_TONE = { 'user.delete': 'danger', 'user.create': 'ok', 'node.delete': 'danger', 'node.create': 'ok', 'maintenance.restore': 'warn' };

  return (
    <div className="sp-cards">
      <Card title={t('activityLogCard', 'Recent Activity')} icon={FiActivity}>
        {loading && <PanelSkeleton lines={5} label="Loading…" />}
        {error && <ErrorState title={t('error', 'Error')} message={error} onRetry={load} />}
        {!loading && !error && events.length === 0 && (
          <EmptyState title={t('noActivity', 'No activity yet')} description={t('activityWillAppear', 'Actions will appear here.')} />
        )}
        {!loading && !error && events.length > 0 && (
          <div className="sp-feed">
            {events.map(e => (
              <div key={e.id} className="sp-feed-row">
                <span className={`sp-badge sp-badge--${ACTION_TONE[e.action] || 'muted'}`}>{e.action}</span>
                <div className="sp-feed-body">
                  <span className="sp-feed-actor">{e.actor || 'system'}</span>
                  {e.target && <><span className="sp-muted">→</span><span className="sp-feed-target">{e.target}</span></>}
                </div>
                {e.ts && <span className="sp-feed-time">{fmtDateTime(new Date(e.ts * 1000).toISOString())}</span>}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
};

/* ═══════════════════════════════════════════════════════
   ROOT SETTINGS PAGE
═══════════════════════════════════════════════════════ */
const SECTIONS = [
  { id: 'general',  icon: FiSliders,  labelKey: 'settingsGeneral',  label: 'General',  descKey: 'settingsGeneralDesc',  desc: 'Panel URL, timezone and subscription settings', Component: GeneralSection  },
  { id: 'system',   icon: FiServer,   labelKey: 'settingsSystem',   label: 'System',   descKey: 'settingsSystemDesc',   desc: 'Server info and maintenance actions',            Component: SystemSection   },
  { id: 'security', icon: FiShield,   labelKey: 'settingsSecurity', label: 'Security', descKey: 'settingsSecurityDesc', desc: 'Authentication errors and session signals',      Component: SecuritySection },
  { id: 'backup',   icon: FiArchive,  labelKey: 'settingsBackup',   label: 'Backup',   descKey: 'settingsBackupDesc',   desc: 'Create, download and restore the database',      Component: BackupSection   },
  { id: 'bot',      icon: FiSend,     labelKey: 'settingsBot',      label: 'Bot',      descKey: 'settingsBotDesc',      desc: 'Telegram bot token and defaults',                Component: BotSection      },
  { id: 'activity', icon: FiActivity, labelKey: 'settingsActivity', label: 'Activity', descKey: 'settingsActivityDesc', desc: 'Recent administrator actions',                   Component: ActivitySection },
];

const Settings = () => {
  const { t } = useTranslation();

  return (
    <div className="sp-page">
      {/* Sticky jump-nav */}
      <nav className="sp-jumpnav" aria-label="Jump to section">
        {SECTIONS.map(s => (
          <a key={s.id} href={`#${s.id}`} className="sp-jumpnav-link">
            <s.icon size={14} aria-hidden="true" />
            <span>{t(s.labelKey, s.label)}</span>
          </a>
        ))}
      </nav>

      {/* All sections */}
      <div className="sp-sections">
        {SECTIONS.map(({ id, icon, labelKey, label, descKey, desc, Component }) => (
          <section key={id} className="sp-section">
            <SectionHeader
              id={id}
              icon={icon}
              label={t(labelKey, label)}
              description={t(descKey, desc)}
            />
            <Component />
          </section>
        ))}
      </div>
    </div>
  );
};

export default Settings;
