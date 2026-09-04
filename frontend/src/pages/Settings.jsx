/**
 * Settings — single friendly page. Every section is always visible (no
 * Simple/Advanced split): defaults → bot → display → appearance → alerts →
 * general → system → security → backup → activity. The page was a "user
 * friendly" wish-list item (2026-09): fewer clicks to reach any control, the
 * most-touched settings sit at the top.
 *
 * The page also responds to deep links: arriving at `/settings#defaults`
 * scrolls the matching <section> into view. Previously the hash was ignored
 * and the page reset to the top.
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useLocation, Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useToast } from '../context/ToastContext';
import { useLive } from '../context/LiveContext';
import apiClient from '../services/api';
import { useTheme } from '../context/ThemeContext';
import { readPrefs, writePref, REFRESH_OPTIONS } from '../utils/notifPrefs';
import { settle } from '../hooks/useAsyncData';
import { getUiPref, setUiPref, getUiStyle, setUiStyle } from '../utils/uiPrefs';
import LoadingButton from '../components/LoadingButton';
import ConfirmModal from '../components/ConfirmModal';
import PanelSkeleton from '../components/ui/PanelSkeleton';
import ErrorState from '../components/ui/ErrorState';
import EmptyState from '../components/ui/EmptyState';
import {
  FiSliders, FiServer, FiShield, FiArchive, FiSend, FiActivity,
  FiLink, FiEdit2, FiCheck, FiX, FiExternalLink, FiCopy,
  FiZap, FiRefreshCw, FiDownload, FiUpload, FiDatabase,
  FiBarChart2, FiUserPlus, FiClock, FiSun, FiMoon, FiMonitor,
  FiBell, FiGlobe, FiAlertTriangle, FiLayout, FiGrid, FiMinus,
} from 'react-icons/fi';
import { formatBytes } from '../utils/format';
import { formatUptime, fmtDateTime } from '../utils/time';
import './Settings.css';

/* ─────────────────────────────────────────────
   Section header with anchor
───────────────────────────────────────────── */
const SectionHeader = ({ headingId, icon: Icon, label, description }) => (
  <div className="sp-section-header">
    <span className="sp-section-icon">{Icon ? <Icon aria-hidden="true" /> : null}</span>
    <div>
      <h2 id={headingId}>{label}</h2>
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
const Field = ({ label, hint, children, horizontal, inputId }) => (
  <div className={`sp-field${horizontal ? ' sp-field--h' : ''}`}>
    <label className="sp-label" htmlFor={inputId}>{label}</label>
    {children}
    {hint && <p className="sp-hint">{hint}</p>}
  </div>
);

const TONE_SR_KEY = { danger: 'critical', warn: 'warning', ok: 'allSystemsClear', muted: 'noNotif' };

const Stat = ({ label, value, tone }) => {
  const { t } = useTranslation();
  return (
    <div className={`sp-stat${tone ? ` sp-stat--${tone}` : ''}`}>
      <span>{label}</span>
      <strong>
        {value}
        {tone && <span className="sr-only"> ({t(TONE_SR_KEY[tone] || 'warning', tone)})</span>}
      </strong>
    </div>
  );
};

/* Focus management for inline editors: move focus into the input on open
   and return it to the invoking edit button on close. */
const useInlineEditFocus = (editing, inputRef, triggerRef) => {
  const wasOpen = useRef(false);
  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      wasOpen.current = true;
    } else if (wasOpen.current) {
      triggerRef.current?.focus();
      wasOpen.current = false;
    }
  }, [editing, inputRef, triggerRef]);
};

/* ═══════════════════════════════════════════════════════
   DEFAULTS — new user defaults (used by the Telegram bot)
═══════════════════════════════════════════════════════ */
const DefaultsSection = () => {
  const { t } = useTranslation();
  const { refreshTick } = useLive();
  const { addToast } = useToast();
  const [days, setDays] = useState(30);
  const [trafficGb, setTrafficGb] = useState(100);
  const [devices, setDevices] = useState(1);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setLoadError(false);
      const res = await apiClient.get('/server/settings');
      const s = res.data?.data || {};
      setDays(Number(s.default_days) || 30);
      setTrafficGb(Number(s.default_traffic_gb) || 100);
      setDevices(Number(s.default_max_users) || 1);
    } catch { setLoadError(true); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load, refreshTick]);

  const save = async () => {
    setSaving(true);
    try {
      await apiClient.put('/server/settings/bot', {
        default_days: Math.max(1, Math.min(3650, Number(days) || 30)),
        default_traffic_gb: Math.max(1, Number(trafficGb) || 100),
        default_max_users: Math.max(1, Math.min(1000, Number(devices) || 1)),
      });
      addToast(t('saved', 'Defaults saved.'), 'success');
    } catch (e) {
      addToast(e.response?.data?.msg || e.response?.data?.detail || t('error', 'Error'), 'error');
    } finally { setSaving(false); }
  };

  if (loading) return <PanelSkeleton lines={3} label="Loading…" />;
  if (loadError) return <ErrorState title={t('settingsLoadError', 'Failed to load settings')} message={t('settingsLoadErrorDetail', 'Could not reach the server.')} onRetry={load} retryLabel={t('retry', 'Retry')} />;

  return (
    <div className="sp-cards">
      <Card title={t('newUserDefaults', 'New User Defaults')} icon={FiUserPlus}>
        <p className="sp-hint sp-mb-14">
          {t('defaultsDesc', 'Used as the Standard plan when an operator creates a user from the Telegram bot.')}
        </p>
        <div className="sp-two-col">
          <Field label={t('defaultDays', 'Default expiry (days)')} inputId="defaults-days">
            <input id="defaults-days" className="sp-input" type="number" min={1} max={3650} value={days} onChange={e => setDays(e.target.value)} />
          </Field>
          <Field label={t('defaultTrafficGb', 'Default traffic (GB)')} inputId="defaults-traffic">
            <input id="defaults-traffic" className="sp-input" type="number" min={1} value={trafficGb} onChange={e => setTrafficGb(e.target.value)} />
          </Field>
        </div>
        <Field label={t('defaultDevices', 'Default devices per user')} hint={t('defaultDevicesHint', 'Simultaneous logins allowed for each new user. 0 = unlimited.')} inputId="defaults-devices">
          <input id="defaults-devices" className="sp-input" type="number" min={0} max={1000} value={devices} onChange={e => setDevices(e.target.value)} />
        </Field>
        <div className="sp-btn-group sp-mt-18">
          <LoadingButton className="btn btn-sm" isLoading={saving} onClick={save}>
            <FiCheck size={13} /> {t('save', 'Save defaults')}
          </LoadingButton>
        </div>
      </Card>
    </div>
  );
};

/* ═══════════════════════════════════════════════════════
   BOT — Telegram bot configuration (compact)
═══════════════════════════════════════════════════════ */
const BotSection = () => {
  const { t } = useTranslation();
  const { addToast } = useToast();
  const [token, setToken] = useState('');
  const [enabled, setEnabled] = useState(false);
  const [ownerId, setOwnerId] = useState('');
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [encryptKeyMissing, setEncryptKeyMissing] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setLoadError(false);
      const r = await apiClient.get('/server/settings');
      const d = r.data?.data || {};
      setEnabled(d.bot_enabled || false);
      setOwnerId(d.owner_telegram_id || '');
      setEncryptKeyMissing(false);
    } catch { setLoadError(true); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        bot_enabled: enabled,
        owner_telegram_id: ownerId ? Number(ownerId) : null,
        ...(token ? { bot_token: token } : {}),
      };
      const r = await apiClient.put('/server/settings/bot', payload);
      if (r.data?.success === false) {
        const msg = r.data?.msg || '';
        if (msg.toLowerCase().includes('encrypt')) setEncryptKeyMissing(true);
        addToast(msg || t('error', 'Error'), 'error');
      } else {
        addToast(t('saved', 'Bot settings saved.'), 'success');
        setToken(''); // token is write-only
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

  if (loading) return <PanelSkeleton lines={3} label="Loading…" />;
  if (loadError) return <ErrorState title={t('settingsLoadError', 'Failed to load settings')} message={t('settingsLoadErrorDetail', 'Could not reach the server.')} onRetry={load} retryLabel={t('retry', 'Retry')} />;

  return (
    <div className="sp-cards">
      <Card title={t('telegramBot', 'Telegram Bot')} icon={FiSend}>
        {encryptKeyMissing && (
          <div className="settings-alert settings-alert--error sp-mb-16" role="alert">
            <strong>{t('botEncryptKeyMissing', 'BOT_ENCRYPT_KEY not set')}</strong>
            <p>{t('botEncryptKeyMissingDesc', 'Set BOT_ENCRYPT_KEY in your .env before saving a token.')}</p>
          </div>
        )}

        <Field label={t('botToken', 'Bot Token')} hint={t('botDesc', 'From @BotFather. Operators use the menu and typed search — /start is the only command. Leave blank to keep the current token.')} inputId="bot-token">
          <input id="bot-token" className="sp-input" type="text" value={token} onChange={e => setToken(e.target.value)}
            placeholder="123456789:ABC…" disabled={encryptKeyMissing} />
        </Field>

        <Field label={t('ownerTelegramId', 'Owner Telegram ID')} hint={t('ownerTelegramIdHint', 'Your numeric Telegram user ID. After saving, open the bot and tap Start.')} inputId="bot-owner-id">
          <input id="bot-owner-id" className="sp-input" type="number" value={ownerId} onChange={e => setOwnerId(e.target.value)} placeholder="123456789" />
        </Field>

        <Field label={t('botEnabled', 'Enable Bot')} horizontal>
          <label className="sp-toggle">
            <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} disabled={encryptKeyMissing} aria-label={t('botEnabled', 'Enable Bot')} />
            <span className="sp-toggle-track"><span className="sp-toggle-thumb" /></span>
          </label>
        </Field>

        <div className="sp-btn-group sp-mt-20">
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
   DISPLAY — timezone used everywhere in the UI
═══════════════════════════════════════════════════════ */
const DisplaySection = () => {
  const { t } = useTranslation();
  const { addToast } = useToast();
  const [timezone, setTimezone] = useState('UTC');
  const [editing, setEditing] = useState(false);
  const [tzValue, setTzValue] = useState('UTC');
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const inputRef = useRef(null);
  const triggerRef = useRef(null);
  useInlineEditFocus(editing, inputRef, triggerRef);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setLoadError(false);
      const res = await apiClient.get('/server/settings');
      setTimezone(res.data?.data?.timezone || 'UTC');
    } catch { setLoadError(true); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      await apiClient.put('/server/settings/timezone', { timezone: tzValue });
      setTimezone(tzValue); setEditing(false);
      addToast(t('saved', 'Saved.'), 'success');
    } catch (e) { addToast(e.response?.data?.msg || t('error', 'Error'), 'error'); }
    finally { setSaving(false); }
  };

  const cancel = () => setEditing(false);

  if (loading) return <PanelSkeleton lines={3} label="Loading…" />;
  if (loadError) return <ErrorState title={t('settingsLoadError', 'Failed to load settings')} message={t('settingsLoadErrorDetail', 'Could not reach the server.')} onRetry={load} retryLabel={t('retry', 'Retry')} />;

  return (
    <div className="sp-cards">
      <Card title={t('timezoneCard', 'Display Timezone')} icon={FiClock}>
        <div className="sp-url-row">
          <code className="sp-code">{timezone}</code>
          {!editing && (
            <button ref={triggerRef} className="sp-icon-btn" onClick={() => { setTzValue(timezone); setEditing(true); }} aria-label={t('changeTimezone', 'Change timezone')}>
              <FiEdit2 size={14} aria-hidden="true" />
            </button>
          )}
        </div>
        {editing && (
          <div className="sp-inline-edit">
            <label className="sr-only" htmlFor="display-tz">{t('displayTimezone', 'Display timezone')}</label>
            <input id="display-tz" ref={inputRef} type="text" value={tzValue} placeholder="Asia/Tehran" onChange={e => setTzValue(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') save(); if (e.key === 'Escape') cancel(); }} className="sp-input" />
            <div className="sp-row-btns">
              <LoadingButton className="btn btn-sm" isLoading={saving} onClick={save}><FiCheck size={12} /> {t('save', 'Save')}</LoadingButton>
              <button className="btn btn-sm btn-secondary" onClick={cancel}><FiX size={12} /> {t('cancel', 'Cancel')}</button>
            </div>
          </div>
        )}
        <p className="sp-hint">{t('timezoneDesc', 'IANA timezone name used for all date/time displays (e.g. UTC, Asia/Tehran, Europe/Amsterdam).')}</p>
      </Card>
    </div>
  );
};

/* ═══════════════════════════════════════════════════════
   GENERAL (advanced) — Panel URL path + subscription prefix
═══════════════════════════════════════════════════════ */
const GeneralSection = () => {
  const { t } = useTranslation();
  const { addToast } = useToast();
  const [urlPath, setUrlPath] = useState('');
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState('');
  const [confirmSaved, setConfirmSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [subPrefix, setSubPrefix] = useState('');
  const [subPrefixEditing, setSubPrefixEditing] = useState(false);
  const [subPrefixValue, setSubPrefixValue] = useState('');
  const [subPrefixSaving, setSubPrefixSaving] = useState(false);
  const urlInputRef = useRef(null);
  const urlTriggerRef = useRef(null);
  const subInputRef = useRef(null);
  const subTriggerRef = useRef(null);
  useInlineEditFocus(editing, urlInputRef, urlTriggerRef);
  useInlineEditFocus(subPrefixEditing, subInputRef, subTriggerRef);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setLoadError(false);
      const res = await apiClient.get('/server/settings');
      const s = res.data?.data || {};
      setUrlPath(s.urlpath || '');
      setSubPrefix(s.subscription_url_prefix || '');
    } catch { setLoadError(true); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const saveUrlPath = async () => {
    setSaving(true); setError('');
    try {
      const v = editValue.trim().replace(/^\/+|\/+$/g, '');
      if (v && !/^[A-Za-z0-9_-]+$/.test(v)) { setError(t('urlInvalid', 'Only letters, numbers, dashes and underscores.')); return; }
      if (v.length > 64) { setError(t('urlInvalid', 'Max 64 characters.')); return; }
      const res = await apiClient.put('/server/settings/urlpath', { urlpath: v });
      setUrlPath(v); setEditing(false);
      addToast(t('saved', 'Saved.'), 'success');
      // The panel moves to the new prefix — the old URL stops serving the app
      // (URLPathMiddleware hides non-matching paths), so redirect there now.
      const newBase = v ? `/${v}` : '';
      setTimeout(() => { window.location.assign(`${window.location.origin}${newBase}/settings`); }, 600);
      void res;
    } catch (e) { setError(e.response?.data?.msg || t('error', 'Error')); }
    finally { setSaving(false); }
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

  const panelUrl = urlPath ? `${window.location.origin}/${urlPath}/` : `${window.location.origin}/`;

  // Anti-lockout: while editing, show where the panel WILL live and require
  // an explicit acknowledgment that the operator saved the new URL. A typo
  // here otherwise means mystery until --reset-urlpath saves the day.
  const editValueClean = editValue.trim().replace(/^\/+|\/+$/g, '');
  const pathChanged = editValueClean !== urlPath;
  const newPanelUrl = editValueClean ? `${window.location.origin}/${editValueClean}/` : `${window.location.origin}/`;

  if (loading) return <PanelSkeleton lines={4} label="Loading…" />;
  if (loadError) return <ErrorState title={t('settingsLoadError', 'Failed to load settings')} message={t('settingsLoadErrorDetail', 'Could not reach the server.')} onRetry={load} retryLabel={t('retry', 'Retry')} />;

  return (
    <div className="sp-cards">
      {/* Panel URL */}
      <Card title={t('panelUrl', 'Panel URL Path')} icon={FiLink}>
        <div className="sp-url-row">
          <code className="sp-code">{urlPath ? `/${urlPath}/` : '/'}</code>
          {!editing && (
            <button ref={urlTriggerRef} className="sp-icon-btn" onClick={() => { setEditValue(urlPath); setEditing(true); setError(''); setConfirmSaved(false); }} aria-label={t('changePanelPath', 'Change panel URL path')}>
              <FiEdit2 size={14} aria-hidden="true" />
            </button>
          )}
        </div>
        {editing && (
          <div className="sp-inline-edit">
            <label className="sr-only" htmlFor="general-urlpath">{t('panelUrl', 'Panel URL Path')}</label>
            <input
              id="general-urlpath" ref={urlInputRef}
              type="text" value={editValue}
              placeholder={t('enterPath', 'e.g. dashboard')}
              onChange={e => setEditValue(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && (!pathChanged || confirmSaved)) saveUrlPath(); if (e.key === 'Escape') setEditing(false); }}
              className="sp-input"
            />
            {error && <p className="sp-error" role="alert">{error}</p>}
            {pathChanged && (
              <div className="sp-urlpath-confirm">
                <div className="sp-url-preview">
                  <span className="sp-label-xs">{t('urlpathNewUrl', 'Panel will move to')}</span>
                  <code className="sp-code">{newPanelUrl}</code>
                  <button
                    type="button" className="sp-icon-btn" aria-label={t('copy', 'Copy')}
                    onClick={() => { navigator.clipboard?.writeText(newPanelUrl).catch(() => {}); addToast(t('copied', 'Copied.'), 'success'); }}
                  >
                    <FiCopy size={12} aria-hidden="true" />
                  </button>
                </div>
                <label className="sp-check">
                  <input type="checkbox" checked={confirmSaved} onChange={e => setConfirmSaved(e.target.checked)} />
                  <span>{t('urlpathConfirmSaved', 'I saved the new URL — the old one stops working immediately.')}</span>
                </label>
              </div>
            )}
            <div className="sp-row-btns">
              <LoadingButton className="btn btn-sm" isLoading={saving} onClick={saveUrlPath} disabled={pathChanged && !confirmSaved}><FiCheck size={12} /> {t('save', 'Save')}</LoadingButton>
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

      {/* Subscription URL prefix */}
      <Card title={t('subscriptionLinkCard', 'Subscription URL Prefix')} icon={FiLink}>
        <div className="sp-url-row">
          <code className="sp-code sp-code--muted">{subPrefix || t('notSet', '(uses panel origin)')}</code>
          {!subPrefixEditing && (
            <button ref={subTriggerRef} className="sp-icon-btn" onClick={() => { setSubPrefixValue(subPrefix); setSubPrefixEditing(true); }} aria-label={t('changeSubPrefix', 'Change subscription URL prefix')}>
              <FiEdit2 size={14} aria-hidden="true" />
            </button>
          )}
        </div>
        {subPrefixEditing && (
          <div className="sp-inline-edit">
            <label className="sr-only" htmlFor="general-subprefix">{t('subscriptionLinkCard', 'Subscription URL Prefix')}</label>
            <input id="general-subprefix" ref={subInputRef} type="text" value={subPrefixValue} placeholder="https://panel.example.com" onChange={e => setSubPrefixValue(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') saveSubPrefix(); if (e.key === 'Escape') setSubPrefixEditing(false); }} className="sp-input" />
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
   SYSTEM (advanced) — Server info + maintenance actions
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
  const [loadError, setLoadError] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setLoadError(false);
      // Independent: missing traffic history should not blank out server info.
      const res = await settle({
        info: apiClient.get('/server/info'),
        metrics: apiClient.get('/metrics/history?hours=24'),
      });
      if (res.info.ok) setSysInfo(res.info.data.data?.data || null);
      else setLoadError(true);
      const traffic = res.metrics.ok ? (res.metrics.data.data?.data?.traffic || []) : [];
      if (traffic.length) {
        setTrafficTotal(traffic.reduce((s, h) => s + Number(h.total_used || 0), 0));
        setActiveConns(traffic[traffic.length - 1]?.active_connections || 0);
      }
    } catch { setLoadError(true); } finally { setLoading(false); }
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

  const spin = <span className="button-spinner" aria-hidden="true" />;

  if (loading) return <PanelSkeleton lines={4} label="Loading…" />;
  if (loadError && !sysInfo) return <ErrorState title={t('settingsLoadError', 'Failed to load settings')} message={t('settingsLoadErrorDetail', 'Could not reach the server.')} onRetry={load} retryLabel={t('retry', 'Retry')} />;

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
        <p className="sp-hint sp-mb-12">{t('maintenanceDesc', 'Run background jobs on demand. These also run automatically on a schedule.')}</p>
        <div className="sp-btn-group">
          <button className="btn btn-sm" disabled={!!busy} aria-busy={busy === '/metrics/collect'} onClick={() => run('/metrics/collect', t('collectNow', 'Metrics'))}>
            {busy === '/metrics/collect' ? spin : <><FiZap size={13} aria-hidden="true" /> {t('collectNow', 'Collect metrics')}</>}
          </button>
          <button className="btn btn-sm btn-secondary" disabled={!!busy} aria-busy={busy === '/maintenance/sync-limits'} onClick={() => run('/maintenance/sync-limits', t('syncLimits', 'Limits'))}>
            {busy === '/maintenance/sync-limits' ? spin : <><FiRefreshCw size={13} aria-hidden="true" /> {t('syncLimits', 'Sync limits')}</>}
          </button>
          <button className="btn btn-sm btn-secondary" disabled={!!busy} aria-busy={busy === '/maintenance/clean-stale'} onClick={() => run('/maintenance/clean-stale', t('cleanStale', 'Stale'))}>
            {busy === '/maintenance/clean-stale' ? spin : <><FiRefreshCw size={13} aria-hidden="true" /> {t('cleanStale', 'Clean stale sessions')}</>}
          </button>
          <button className="btn btn-sm btn-secondary" disabled={!!busy} aria-busy={busy === '/maintenance/clean-global-registry'} onClick={() => run('/maintenance/clean-global-registry', t('cleanRegistry', 'Registry'))}>
            {busy === '/maintenance/clean-global-registry' ? spin : <><FiBarChart2 size={13} aria-hidden="true" /> {t('cleanRegistry', 'Clean registry')}</>}
          </button>
        </div>
      </Card>
    </div>
  );
};

/* ═══════════════════════════════════════════════════════
   SECURITY (advanced) — Auth summary
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
        <div className="sp-hours-toggle" role="group" aria-label={t('securityWindow', 'Time window')}>
          {[4, 8, 12, 24, 48].map(h => (
            <button key={h} type="button" className={`sp-hour-btn${hours === h ? ' active' : ''}`} aria-pressed={hours === h} onClick={() => setHours(h)}>{h}h</button>
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
          <div className="sp-mt-16">
            <p className="sp-label-xs sp-mb-6">{t('th_node', 'Per Node')}</p>
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
        {(sec?.timezone || sec?.hours) && (
          <p className="sp-hint sp-mt-12">
            {t('securityWindow', 'Window: last {{hours}}h · {{timezone}}', { hours: sec.hours ?? hours, timezone: sec.timezone || 'UTC' })}
          </p>
        )}
        {Array.isArray(sec?.top_common_names) && sec.top_common_names.length > 0 && (
          <div className="sp-mt-12">
            <p className="sp-label-xs sp-mb-6">{t('topCommonNames', 'Most affected identities')}</p>
            <div className="sp-chip-row">
              {sec.top_common_names.slice(0, 10).map(([cn, count]) => (
                <span key={cn} className="sp-chip" title={`${count} events`}>{cn} · {count}</span>
              ))}
            </div>
          </div>
        )}
        {Array.isArray(sec?.last_errors) && sec.last_errors.length > 0 && (
          <div className="sp-mt-12">
            <p className="sp-label-xs sp-mb-6">{t('lastErrors', 'Latest auth events')}</p>
            <div className="sp-node-list">
              {sec.last_errors.slice(0, 5).map((e, i) => (
                <div key={`${e.ts}-${e.common_name}-${i}`} className="sp-node-row sp-err-row">
                  <span className="sp-node-name">{e.common_name || e.username || '—'}</span>
                  <span className="sp-cell-sub">{[e.node, e.time_local || (e.ts ? new Date(e.ts * 1000).toLocaleString() : '')].filter(Boolean).join(' · ')}</span>
                  <span className={`sp-badge${e.action === 'reject' ? ' danger' : ''}`}>{e.reason || e.action || 'event'}</span>
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
   BACKUP (advanced) — Create, download, restore
═══════════════════════════════════════════════════════ */
const BackupSection = () => {
  const { t } = useTranslation();
  const { refreshTick } = useLive();
  const { addToast } = useToast();
  const [backups, setBackups] = useState([]);
  const [busy, setBusy] = useState('');
  const [restoreFile, setRestoreFile] = useState(null);
  const [loadError, setLoadError] = useState(false);
  const [confirm, setConfirm] = useState({ open: false, title: '', message: '', onConfirm: null });
  const closeConfirm = () => setConfirm((c) => ({ ...c, open: false }));

  const load = useCallback(async () => {
    try {
      setLoadError(false);
      const r = await apiClient.get('/maintenance/backup/list');
      if (Array.isArray(r.data?.data)) setBackups(r.data.data);
    }
    catch { setLoadError(true); }
  }, []);

  useEffect(() => { load(); }, [load, refreshTick]);

  const create = async () => {
    setBusy('create');
    try {
      const r = await apiClient.post('/maintenance/backup');
      addToast(r.data?.msg || t('createBackup', 'Backup created'), 'success');
      load();
    } catch (e) { addToast(e.response?.data?.detail || e.response?.data?.msg || t('error', 'Failed'), 'error'); }
    finally { setBusy(''); }
  };

  const download = async () => {
    try {
      const r = await apiClient.get('/maintenance/backup/download', { responseType: 'blob' });
      const url = URL.createObjectURL(new Blob([r.data]));
      const a = document.createElement('a'); a.href = url; a.download = backups[0]?.name || 'ovmanager-backup.db';
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    } catch { addToast(t('error', 'Download failed'), 'error'); }
  };

  const doRestore = async () => {
    if (!restoreFile) return;
    if (!restoreFile.name.endsWith('.db')) {
      addToast(t('backupMustBeDb', 'Backup file must be a .db file.'), 'error');
      return;
    }
    setBusy('restore');
    try {
      const fd = new FormData(); fd.append('file', restoreFile);
      const r = await apiClient.post('/maintenance/backup/restore', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
      if (r.data?.success) {
        addToast(r.data.msg || t('restored', 'Restored successfully'), 'success');
        setRestoreFile(null);
      } else {
        addToast(r.data?.msg || t('error', 'Restore failed'), 'error');
      }
    } catch (e) { addToast(e.response?.data?.detail || e.response?.data?.msg || t('error', 'Restore failed'), 'error'); }
    finally { setBusy(''); }
  };

  const askRestore = () => {
    if (!restoreFile) return;
    setConfirm({
      open: true,
      title: t('restoreButton', 'Restore'),
      message: t('confirmRestoreFile', 'Restore from "{{name}}"? This will overwrite current data.', { name: restoreFile.name }),
      onConfirm: doRestore,
    });
  };

  return (
    <div className="sp-cards">
      <Card title={t('backupTitle', 'Database Backup')} icon={FiDatabase}>
        <div className="sp-btn-group sp-mb-16">
          <button className="btn btn-sm" disabled={!!busy} aria-busy={busy === 'create'} onClick={create}>
            {busy === 'create' ? <span className="button-spinner" aria-hidden="true" /> : <><FiUpload size={13} aria-hidden="true" /> {t('createBackup', 'Create backup')}</>}
          </button>
          {backups.length > 0 && (
            <button className="btn btn-sm btn-secondary" onClick={download}>
              <FiDownload size={13} /> {t('downloadLatest', 'Download latest')}
            </button>
          )}
          <Link to="/maintenance" className="btn btn-sm btn-secondary">{t('viewAll', 'View all')}</Link>
        </div>
        {loadError && backups.length === 0 ? (
          <ErrorState title={t('loadError', 'Could not load data')} message={t('loadErrorDetail', 'Could not reach backup list.')} onRetry={load} retryLabel={t('retry', 'Retry')} />
        ) : backups.length === 0 ? (
          <EmptyState title={t('noBackups', 'No backups yet')} description={t('noBackupsBody', 'Create your first backup to protect panel data.')} />
        ) : (
          <div className="sp-backup-list">
            {backups.slice(0, 8).map(b => (
              <div key={b.name} className="sp-backup-row">
                <FiDatabase size={13} aria-hidden="true" />
                <span className="sp-backup-name">{b.name}</span>
                {b.size && <span className="sp-backup-size">{formatBytes(b.size)}</span>}
              </div>
            ))}
            {backups.length > 8 && (
              <Link to="/maintenance" className="sp-viewall">{t('showingMore', 'Showing 8 of {{total}} — view all', { total: backups.length })}</Link>
            )}
          </div>
        )}
      </Card>

      <Card title={t('restoreSection', 'Restore from File')} icon={FiArchive}>
        <p className="sp-hint sp-mb-12">{t('restoreHint', 'Select a .db backup file to restore. This overwrites current data and asks for confirmation.')}</p>
        <div className="sp-field">
          <label className="sr-only" htmlFor="sp-restore-file">{t('selectBackupFile', 'Select backup file')}</label>
          <input id="sp-restore-file" type="file" accept=".db" onChange={e => setRestoreFile(e.target.files?.[0] || null)} className="sp-file-input" aria-label={t('selectBackupFile', 'Select backup file')} />
        </div>
        <button className="btn btn-sm" disabled={!restoreFile || !!busy} aria-busy={busy === 'restore'} onClick={askRestore}>
          {busy === 'restore' ? <span className="button-spinner" aria-hidden="true" /> : <><FiRefreshCw size={13} aria-hidden="true" /> {t('restoreButton', 'Restore')}</>}
        </button>
      </Card>
      <ConfirmModal open={confirm.open} onClose={closeConfirm} onConfirm={confirm.onConfirm || (() => {})} title={confirm.title} message={confirm.message} danger confirmLabel={t('restoreButton', 'Restore')} cancelLabel={t('cancelButton', 'Cancel')} />
    </div>
  );
};

/* ═══════════════════════════════════════════════════════
   ACTIVITY (advanced) — Recent audit events
═══════════════════════════════════════════════════════ */
const ActivitySection = () => {
  const { t } = useTranslation();
  const { refreshTick } = useLive();
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try { setLoading(true); setError(null); const r = await apiClient.get('/activity/?limit=50'); setEvents(r.data?.data || []); }
    catch { setError(t('failedToLoad', 'Failed to load')); } finally { setLoading(false); }
  }, [t]);

  useEffect(() => { load(); }, [load, refreshTick]);

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
          <>
            <div className="sp-feed">
              {events.map(e => (
                <div key={e.id} className="sp-feed-row">
                  <span className={`sp-badge sp-badge--${ACTION_TONE[e.action] || 'muted'}`}>{e.action}</span>
                  <div className="sp-feed-body">
                    <span className="sp-feed-actor">{e.actor || 'system'}</span>
                    {e.target && <><span className="sp-muted">→</span><span className="sp-feed-target">{e.target}</span></>}
                  </div>
                  {e.ts && <time className="sp-feed-time" dateTime={new Date(e.ts * 1000).toISOString()}>{fmtDateTime(new Date(e.ts * 1000).toISOString())}</time>}
                </div>
              ))}
            </div>
            <Link to="/audit" className="sp-viewall">{t('viewAllActivity', 'View full audit log')}</Link>
          </>
        )}
      </Card>
    </div>
  );
};

/* ═══════════════════════════════════════════════════════
   APPEARANCE — theme + language (front-end only)
═══════════════════════════════════════════════════════ */
const AppearanceSection = () => {
  const { t, i18n } = useTranslation();
  const { theme, setTheme } = useTheme();
  const [lang, setLang] = useState(i18n.language || 'en');

  const THEMES = [
    { id: 'light', label: t('lightTheme', 'Light'), icon: FiSun },
    { id: 'dark', label: t('darkTheme', 'Dark'), icon: FiMoon },
    { id: 'system', label: t('systemTheme', 'System'), icon: FiMonitor },
  ];

  const LANGS = [
    { id: 'fa', label: 'فارسی' },
    { id: 'en', label: 'English' },
    { id: 'ru', label: 'Русский' },
    { id: 'cn', label: '中文' },
  ];

  const changeLanguage = (id) => {
    i18n.changeLanguage(id);
    localStorage.setItem('ovmanager-lang', id);
    setLang(id);
    // No document.documentElement.dir write here: DashboardLayout owns that in
    // an effect keyed on i18n.language, and it sets html[lang] and body[dir]
    // too, which this duplicate did not. Mutating the DOM from a function
    // created during render is what the rule objects to.
  };

  const ACCENTS = [
    { hex: '#ff6a1a', name: 'Orange' },
    { hex: '#2fd276', name: 'Emerald' },
    { hex: '#6366f1', name: 'Indigo' },
    { hex: '#ec4899', name: 'Rose' },
    { hex: '#19d3e9', name: 'Cyan' },
    { hex: '#eab308', name: 'Amber' },
  ];
  const [accent, setAccent] = useState(() => getUiPref('accent', ''));
  const chooseAccent = (hex) => {
    setAccent(hex);
    setUiPref('accent', hex);
    document.documentElement.style.setProperty('--accent-color', hex);
  };

  const [uiStyle, setUiStyleState] = useState(() => getUiStyle());
  const chooseUiStyle = (style) => {
    setUiStyle(style);
    setUiStyleState(style);
  };

  const [corner, setCorner] = useState(() => {
    try { return localStorage.getItem('ovmanager-sidebar-corner') || 'inline-start'; }
    catch { return 'inline-start'; }
  });
  const chooseCorner = (id) => {
    try { localStorage.setItem('ovmanager-sidebar-corner', id); } catch { /* private mode */ }
    setCorner(id);
    // Applied live by the sidebar — no reload, no lost form state.
    window.dispatchEvent(new CustomEvent('sidebar-corner-change', { detail: { corner: id } }));
  };

  return (
    <div className="sp-cards">
      <Card title={t('accentCard', 'Accent color')} icon={FiSun}>
        <div className="accent-picker" role="group" aria-label={t('accentCard', 'Accent color')}>
          <button
            type="button"
            className={`accent-swatch${accent === '' ? ' active' : ''}`}
            style={{ background: 'var(--accent-color)' }}
            onClick={() => chooseAccent('')}
            title={t('accentDefault', 'Default')}
            aria-label={t('accentDefault', 'Default')}
            aria-pressed={accent === ''}
          />
          {ACCENTS.map((a) => (
            <button
              key={a.hex}
              type="button"
              className={`accent-swatch${accent === a.hex ? ' active' : ''}`}
              style={{ background: a.hex }}
              onClick={() => chooseAccent(a.hex)}
              title={a.name}
              aria-label={a.name}
              aria-pressed={accent === a.hex}
            />
          ))}
        </div>
        <p className="sp-hint">{t('accentDesc', 'Changes the brand color across the panel. Saved per browser.')}</p>
      </Card>

      <Card title={t('themeCard', 'Theme')} icon={FiMonitor}>
        <div className="sp-theme-pills" role="group" aria-label={t('themeCard', 'Theme')}>
          {THEMES.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`sp-theme-pill${theme === item.id ? ' active' : ''}`}
              onClick={() => setTheme(item.id)}
              aria-pressed={theme === item.id}
            >
              <item.icon size={15} aria-hidden="true" />
              <span>{item.label}</span>
            </button>
          ))}
        </div>
        <p className="sp-hint">{t('themeDesc', 'System follows your operating system preference.')}</p>
      </Card>

      <Card title={t('styleCard', 'Panel style')} icon={FiLayout}>
        <div className="sp-theme-pills sp-pills-2" role="group" aria-label={t('styleCard', 'Panel style')}>
          <button
            type="button"
            className={`sp-theme-pill${uiStyle === 'normal' ? ' active' : ''}`}
            onClick={() => chooseUiStyle('normal')}
            aria-pressed={uiStyle === 'normal'}
          >
            <FiGrid size={15} aria-hidden="true" />
            <span>{t('styleNormal', 'Normal')}</span>
          </button>
          <button
            type="button"
            className={`sp-theme-pill${uiStyle === 'minimal' ? ' active' : ''}`}
            onClick={() => chooseUiStyle('minimal')}
            aria-pressed={uiStyle === 'minimal'}
          >
            <FiMinus size={15} aria-hidden="true" />
            <span>{t('styleMinimal', 'Minimal')}</span>
          </button>
        </div>
        <p className="sp-hint">{t('styleDesc', 'Normal uses rich cards and soft shadows; Minimal is flat with hairline borders. Saved per browser.')}</p>
      </Card>

      <Card title={t('sidebarCornerCard', 'Sidebar position')} icon={FiLayout}>
        <div className="sp-theme-pills sp-pills-5" role="group" aria-label={t('sidebarCornerCard', 'Sidebar position')}>
          {[
            { id: 'inline-start', label: t('sidebarEdge', 'Edge') },
            { id: 'top-left',     label: t('sidebarTopLeft',     'Top L') },
            { id: 'top-right',    label: t('sidebarTopRight',    'Top R') },
            { id: 'bottom-left',  label: t('sidebarBottomLeft',  'Bot L') },
            { id: 'bottom-right', label: t('sidebarBottomRight', 'Bot R') },
          ].map((c) => (
            <button
              key={c.id}
              type="button"
              className={`sp-theme-pill${corner === c.id ? ' active' : ''}`}
              onClick={() => chooseCorner(c.id)}
              aria-pressed={corner === c.id}
            >
              <span>{c.label}</span>
            </button>
          ))}
        </div>
        <p className="sp-hint">{t('sidebarCornerDesc', 'Where the sidebar anchors. "Edge" is the default full-height rail; the four corners dock to the top or bottom. Saved per browser.')}</p>
      </Card>

      <Card title={t('languageCard', 'Language')} icon={FiGlobe}>
        <div className="sp-lang-row" role="group" aria-label={t('languageCard', 'Language')}>
          {LANGS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`sp-lang-btn${lang === item.id ? ' active' : ''}`}
              onClick={() => changeLanguage(item.id)}
              aria-pressed={lang === item.id}
            >
              {item.label}
            </button>
          ))}
        </div>
        <p className="sp-hint">{t('languageDesc', 'Interface language. Persian switches the panel to RTL.')}</p>
      </Card>
    </div>
  );
};

/* ═══════════════════════════════════════════════════════
   ALERTS & DASHBOARD — which alerts to surface + refresh
═══════════════════════════════════════════════════════ */
const AlertsSection = () => {
  const { t } = useTranslation();
  const [prefs, setPrefs] = useState(readPrefs);

  const toggle = (key, value) => {
    writePref(key, value);
    setPrefs(readPrefs());
  };

  const ALERTS = [
    { key: 'nodeDown', label: t('alertNodeDown', 'Node offline / unreachable'), icon: FiAlertTriangle },
    { key: 'maxLogins', label: t('alertMaxLogins', 'User at max logins'), icon: FiAlertTriangle },
    { key: 'authErrors', label: t('alertAuthErrors', 'Authentication errors'), icon: FiAlertTriangle },
    { key: 'rejects', label: t('alertRejects', 'Connection rejects'), icon: FiAlertTriangle },
    { key: 'stale', label: t('alertStale', 'Stale session markers'), icon: FiAlertTriangle },
  ];

  return (
    <div className="sp-cards">
      <Card title={t('alertsCard', 'Alert Types')} icon={FiBell}>
        <p className="sp-hint sp-mb-12">{t('alertsDesc', 'Choose which alerts appear in the topbar bell and the dashboard strip.')}</p>
        <div className="sp-alert-list">
          {ALERTS.map((item) => (
            <label key={item.key} className="sp-alert-row">
              <span className="sp-alert-label"><item.icon size={13} aria-hidden="true" /> {item.label}</span>
              <span className="sp-toggle">
                <input type="checkbox" checked={prefs[item.key] !== false} onChange={(e) => toggle(item.key, e.target.checked)} />
                <span className="sp-toggle-track"><span className="sp-toggle-thumb" /></span>
              </span>
            </label>
          ))}
        </div>
      </Card>

      <Card title={t('refreshCard', 'Refresh Interval')} icon={FiRefreshCw}>
        <Field label={t('refreshInterval', 'Dashboard refresh (seconds)')} hint={t('refreshDesc', 'How often the dashboard and notification bell poll for fresh data.')} inputId="alerts-refresh">
          <select id="alerts-refresh" className="sp-select" value={prefs.refreshSec} onChange={(e) => toggle('refreshSec', Number(e.target.value))}>
            {REFRESH_OPTIONS.map((sec) => (
              <option key={sec} value={sec}>{sec} {t('secondsUnit', 's')}</option>
            ))}
          </select>
        </Field>
      </Card>
    </div>
  );
};

/* ═══════════════════════════════════════════════════════
   ROOT SETTINGS PAGE
═══════════════════════════════════════════════════════ */
const SECTIONS = [
  { id: 'defaults',   icon: FiUserPlus,  labelKey: 'settingsDefaults',   label: 'Defaults',   descKey: 'settingsDefaultsDesc',   desc: 'New user defaults used by the Telegram bot', Component: DefaultsSection, simple: true },
  { id: 'bot',        icon: FiSend,      labelKey: 'settingsBot',        label: 'Bot',        descKey: 'settingsBotDesc',        desc: 'Telegram bot token, enable state and owner ID', Component: BotSection, simple: true },
  { id: 'display',    icon: FiClock,     labelKey: 'settingsDisplay',    label: 'Display',    descKey: 'settingsDisplayDesc',    desc: 'Timezone used for all date and time displays', Component: DisplaySection, simple: true },
  { id: 'appearance', icon: FiMonitor,   labelKey: 'settingsAppearance', label: 'Appearance', descKey: 'settingsAppearanceDesc', desc: 'Theme and interface language', Component: AppearanceSection, simple: true },
  { id: 'alerts',     icon: FiBell,      labelKey: 'settingsAlerts',     label: 'Alerts',     descKey: 'settingsAlertsDesc',     desc: 'Which alerts to show and how often to refresh', Component: AlertsSection, simple: true },
  { id: 'general',    icon: FiLink,      labelKey: 'settingsGeneral',    label: 'General',    descKey: 'settingsGeneralDesc',    desc: 'Panel URL path and subscription link prefix', Component: GeneralSection, simple: false },
  { id: 'system',     icon: FiServer,    labelKey: 'settingsSystem',     label: 'System',     descKey: 'settingsSystemDesc',     desc: 'Server info and maintenance actions', Component: SystemSection, simple: false },
  { id: 'security',   icon: FiShield,    labelKey: 'settingsSecurity',   label: 'Security',   descKey: 'settingsSecurityDesc',   desc: 'Authentication errors and session signals', Component: SecuritySection, simple: false },
  { id: 'backup',     icon: FiArchive,   labelKey: 'settingsBackup',     label: 'Backup',     descKey: 'settingsBackupDesc',     desc: 'Create, download and restore the database', Component: BackupSection, simple: false },
  { id: 'activity',   icon: FiActivity,  labelKey: 'settingsActivity',   label: 'Activity',   descKey: 'settingsActivityDesc',   desc: 'Recent administrator actions', Component: ActivitySection, simple: false },
];

const Settings = () => {
  const { t } = useTranslation();
  const location = useLocation();

  // All sections always visible — no Simple/Advanced split
  const visible = useMemo(() => SECTIONS, []);
  const activeHash = location.hash.replace(/^#/, '');

  // Deep-link scroll: when URL has #section-id, scroll that section into
  // view and move focus there so keyboard users land in the right place.
  useEffect(() => {
    const hash = location.hash.replace(/^#/, '');
    if (!hash) return;
    const el = document.getElementById(`sp-section-${hash}`);
    if (!el) return;
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    // Allow the page to paint first, then scroll.
    const id = setTimeout(() => {
      el.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
      el.focus({ preventScroll: true });
    }, 0);
    return () => clearTimeout(id);
  }, [location.hash]);

  return (
    <div className="sp-page">
      <nav className="sp-jumpnav" aria-label={t('settingsNavigation', 'Settings sections')}>
        {visible.map(s => (
          <Link
            key={s.id}
            to={`#${s.id}`}
            replace
            className="sp-jumpnav-link"
            aria-current={activeHash === s.id ? 'true' : undefined}
          >
            <s.icon size={14} aria-hidden="true" />
            <span>{t(s.labelKey, s.label)}</span>
          </Link>
        ))}
      </nav>

      {/* All sections */}
      <div className="sp-sections">
        {visible.map((sec) => {
          const Component = sec.Component;
          return (
            <section key={sec.id} className="sp-section" id={`sp-section-${sec.id}`} tabIndex={-1} aria-labelledby={`sp-heading-${sec.id}`}>
              <SectionHeader
                headingId={`sp-heading-${sec.id}`}
                icon={sec.icon}
                label={t(sec.labelKey, sec.label)}
                description={t(sec.descKey, sec.desc)}
              />
              <Component />
            </section>
          );
        })}
      </div>
    </div>
  );
};

export default Settings;
