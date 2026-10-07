// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import apiClient from '../../services/api';
import ConfirmModal from '../../components/ConfirmModal';
import { PanelSkeleton } from '../../components/ui';
import ErrorState from '../../components/ui/ErrorState';
import { Badge, Button, Card, Field } from '../../components/ui';
import {
  FiAlertCircle, FiCheckCircle, FiGlobe, FiInfo,
  FiLock, FiRefreshCw, FiUpload, FiZap,
} from 'react-icons/fi';
import './TlsSection.css';

/* ═══════════════════════════════════════════════════════
   TLS (advanced) — the panel's own HTTPS certificate.

   Every endpoint is owner-only. File-based changes only take effect after a
   panel restart, so each successful install surfaces the same restart action.
   ═══════════════════════════════════════════════════════ */

const MAX_FILE_BYTES = 1024 * 1024;
const PEM_ACCEPT = '.pem,.key,.crt,.cer';
const PEM_RE = /\.(pem|key|crt|cer)$/i;
const RENEW_TIMEOUT_MS = 250000;
const RESTART_POLL_MS = 2500;
const RESTART_POLL_ATTEMPTS = 20;
const REQUEST_FAILED = 'The request failed. Please try again.';

const MODE_TONE: Record<string, string> = { managed: 'success', files: 'info', disabled: 'neutral', misconfigured: 'danger' };
const MODE_LABEL: Record<string, [string, string]> = {
  managed: ['settingsTlsMode_managed', 'Managed by the panel'],
  files: ['settingsTlsMode_files', 'Files from the environment'],
  disabled: ['settingsTlsMode_disabled', 'Disabled (HTTP only)'],
  misconfigured: ['settingsTlsMode_misconfigured', 'Misconfigured'],
};
const SOURCE_LABEL: Record<string, [string, string]> = {
  'panel-managed': ['settingsTlsSource_panelManaged', 'Panel-managed'],
  environment: ['settingsTlsSource_environment', 'Environment'],
};
const ISSUER_LABEL: Record<string, [string, string]> = {
  'self-signed': ['settingsTlsIssuer_selfSigned', 'Self-signed'],
  custom: ['settingsTlsIssuer_custom', 'Custom / uploaded'],
};

interface TlsStatus {
  mode?: string;
  source?: string;
  issued_by?: string;
  expires_days?: number | null;
  restart_required?: boolean;
  subject?: string;
  cert_path?: string;
}

interface TlsField {
  db?: string | null;
  env?: string | null;
  effective?: string | null;
  overridden?: boolean;
}

interface TlsSettingsData {
  fields?: Record<string, TlsField>;
  methods?: string[];
  restart_required?: boolean;
}

type FeedbackValue = { tone: string; text: string } | null;

const expiryTone = (days: number | null | undefined) => {
  if (days == null) return 'neutral';
  if (days <= 7) return 'danger';
  if (days <= 30) return 'warning';
  return 'success';
};

const Notice = ({ tone = 'info', children }: any) => {
  const Icon = tone === 'error' ? FiAlertCircle : tone === 'success' ? FiCheckCircle : FiInfo;
  return (
    <div className={`ts-notice ts-notice--${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      <Icon size={14} aria-hidden="true" />
      <span>{children}</span>
    </div>
  );
};

const RestartPrompt = ({ onRestart, busy, restarting }: any) => {
  const { t } = useTranslation();
  return (
    <div className="ts-restart">
      <p className="ts-restart-text">
        {t('settingsTlsRestartToApply', 'Restart the panel to activate the new certificate.')}
      </p>
      <Button
        variant="primary"
        size="sm"
        icon={<FiZap size={13} aria-hidden="true" />}
        loading={busy === 'restart'}
        disabled={restarting || (busy !== '' && busy !== 'restart')}
        onClick={onRestart}
      >
        {t('settingsTlsRestartNow', 'Restart panel now')}
      </Button>
    </div>
  );
};

const TlsSection = () => {
  const { t } = useTranslation();

  const [status, setStatus] = useState<TlsStatus | null>(null);
  const [summary, setSummary] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState('');
  const [restarting, setRestarting] = useState(false);
  const [pendingRestart, setPendingRestart] = useState(false);
  const [feedback, setFeedback] = useState<any>({});

  const [keyFile, setKeyFile] = useState<File | null>(null);
  const [certFile, setCertFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<Record<string, string>>({ key: '', cert: '' });
  const keyInputRef = useRef<HTMLInputElement>(null);
  const certInputRef = useRef<HTMLInputElement>(null);

  const [domain, setDomain] = useState('');
  const [email, setEmail] = useState('');
  const [useIp, setUseIp] = useState(false);

  const [tlsSettings, setTlsSettings] = useState<TlsSettingsData | null>(null);
  const [tlsForm, setTlsForm] = useState({
    cert_method: 'selfsigned',
    cert_file: '',
    key_file: '',
    acme_domain: '',
    acme_email: '',
  });
  const [tlsBusy, setTlsBusy] = useState('');
  const [tlsFeedback, setTlsFeedback] = useState<FeedbackValue>(null);

  const [confirm, setConfirm] = useState<{ open: boolean; title: string; message: string; confirmLabel: string; onConfirm: (() => void) | null }>({ open: false, title: '', message: '', confirmLabel: '', onConfirm: null });
  const pollRef = useRef<{ attempts: number; timer: ReturnType<typeof setTimeout> | null }>({ attempts: 0, timer: null });

  const setArea = useCallback((area: string, value: FeedbackValue) => {
    setFeedback((f: any) => ({ ...f, [area]: value }));
  }, []);

  const closeConfirm = () => setConfirm((c) => ({ ...c, open: false }));
  const askConfirm = (title: string, message: string, confirmLabel: string, onConfirm: () => void) =>
    setConfirm({ open: true, title, message, confirmLabel, onConfirm });

  const refreshStatus = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setLoading(true);
    try {
      const res = await apiClient.get('/https/status');
      const env = res.data || {};
      setStatus(env.data || null);
      setSummary(env.msg || '');
      if (env.data?.restart_required === true) setPendingRestart(true);
      else if (env.data?.restart_required === false) setPendingRestart(false);
      setError(false);
      return true;
    } catch {
      if (!silent) setError(true);
      return false;
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => { refreshStatus(); }, [refreshStatus]);

  const refreshTlsSettings = useCallback(async () => {
    try {
      const res = await apiClient.get('/tls/settings');
      const data: TlsSettingsData | null = res.data?.data || null;
      setTlsSettings(data);
      const fields = data?.fields || {};
      setTlsForm({
        cert_method: fields.cert_method?.effective || 'selfsigned',
        cert_file: fields.cert_file?.effective || '',
        key_file: fields.key_file?.effective || '',
        acme_domain: fields.acme_domain?.effective || '',
        acme_email: fields.acme_email?.effective || '',
      });
    } catch {
      setTlsSettings(null);
    }
  }, []);

  useEffect(() => { refreshTlsSettings(); }, [refreshTlsSettings]);

  const tlsField = (name: string) => tlsSettings?.fields?.[name];

  const saveTlsSettings = async () => {
    setTlsBusy('save');
    setTlsFeedback(null);
    try {
      const res = await apiClient.put('/tls/settings', tlsForm);
      const env = res.data || {};
      if (env.success === false) {
        setTlsFeedback({ tone: 'error', text: env.msg || t('settingsTlsRequestFailed', REQUEST_FAILED) });
      } else {
        setTlsFeedback({
          tone: 'success',
          text: t('settingsTlsSavedRestart', 'Saved. Run `ovm restart` to apply.'),
        });
        setPendingRestart(true);
        refreshTlsSettings();
      }
    } catch {
      setTlsFeedback({ tone: 'error', text: t('settingsTlsRequestFailed', REQUEST_FAILED) });
    } finally {
      setTlsBusy('');
    }
  };

  const renewFromSettings = async () => {
    setTlsBusy('renewNow');
    setTlsFeedback(null);
    try {
      const res = await apiClient.post(
        '/tls/renew',
        { domain: tlsForm.acme_domain, email: tlsForm.acme_email },
        { timeout: RENEW_TIMEOUT_MS },
      );
      const env = res.data || {};
      if (env.success === false) {
        setTlsFeedback({ tone: 'error', text: env.msg || t('settingsTlsRequestFailed', REQUEST_FAILED) });
      } else {
        setTlsFeedback({ tone: 'success', text: env.msg || t('saved', 'Saved.') });
        setPendingRestart(true);
        refreshStatus({ silent: true });
      }
    } catch {
      setTlsFeedback({ tone: 'error', text: t('settingsTlsRenewLost', 'No answer from the server. Refresh the status above before retrying.') });
    } finally {
      setTlsBusy('');
    }
  };

  const clearPoll = useCallback(() => {
    if (pollRef.current.timer) clearTimeout(pollRef.current.timer);
    pollRef.current = { attempts: 0, timer: null };
  }, []);
  useEffect(() => clearPoll, [clearPoll]);

  const pollForComeback = useCallback(function poll() {
    pollRef.current.attempts += 1;
    if (pollRef.current.attempts > RESTART_POLL_ATTEMPTS) {
      clearPoll();
      setRestarting(false);
      setBusy('');
      setArea('restart', {
        tone: 'info',
        text: t('settingsTlsRestartUnknown', 'The panel did not answer yet. Wait a few seconds, then refresh this page.'),
      });
      return;
    }
    pollRef.current.timer = setTimeout(async () => {
      const ok = await refreshStatus({ silent: true });
      if (ok) {
        clearPoll();
        setRestarting(false);
        setBusy('');
        setPendingRestart(false);
        setArea('restart', { tone: 'success', text: t('settingsTlsRestartDone', 'The panel is back online.') });
      } else {
        poll();
      }
    }, RESTART_POLL_MS);
  }, [clearPoll, refreshStatus, setArea, t]);

  const startRestart = useCallback(async () => {
    setBusy('restart');
    setArea('restart', null);
    setRestarting(true);
    try {
      const res = await apiClient.post('/https/restart', {}, { timeout: 20000 });
      const env = res.data || {};
      if (env.success === false) {
        setRestarting(false);
        setBusy('');
        setArea('restart', {
          tone: 'error',
          text: env.msg || t('settingsTlsRestartFailed', 'Could not restart the panel automatically. Restart it from the server console.'),
        });
        return;
      }
      setArea('restart', {
        tone: 'info',
        text: env.msg || t('settingsTlsRestarting', 'Restarting the panel… this page will reconnect automatically in a few seconds.'),
      });
    } catch {
      setArea('restart', {
        tone: 'info',
        text: t('settingsTlsRestarting', 'Restarting the panel… this page will reconnect automatically in a few seconds.'),
      });
    }
    pollForComeback();
  }, [pollForComeback, setArea, t]);

  const askRestart = () => askConfirm(
    t('settingsTlsRestartConfirmTitle', 'Restart the panel?'),
    t('settingsTlsRestartConfirm', 'The panel will disconnect for a few seconds while it restarts, then come back automatically. Continue?'),
    t('settingsTlsRestartNow', 'Restart panel now'),
    startRestart,
  );

  const onPickFile = (slot: string) => (event: any) => {
    const file = event.target.files?.[0] || null;
    if (slot === 'key') setKeyFile(file);
    else setCertFile(file);
    if (!file) {
      setFileError((e) => ({ ...e, [slot]: '' }));
      return;
    }
    if (!PEM_RE.test(file.name)) {
      setFileError((e) => ({ ...e, [slot]: t('settingsTlsPemOnly', 'PEM files only (.pem, .key, .crt, .cer).') }));
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setFileError((e) => ({ ...e, [slot]: t('settingsTlsFileTooLarge', 'Each file must be smaller than 1 MB.') }));
      return;
    }
    setFileError((e) => ({ ...e, [slot]: '' }));
  };

  const doUpload = async () => {
    if (fileError.key || fileError.cert) return;
    if (!keyFile || !certFile) {
      setArea('upload', { tone: 'error', text: t('settingsTlsBothFiles', 'Choose both the private key and the certificate files first.') });
      return;
    }
    setBusy('upload');
    setArea('upload', null);
    setArea('restart', null);
    try {
      const form = new FormData();
      form.append('key', keyFile);
      form.append('cert', certFile);
      const res = await apiClient.post('/https/existing', form, { timeout: 60000 });
      const env = res.data || {};
      if (env.success === false) {
        setArea('upload', { tone: 'error', text: env.msg || t('settingsTlsRequestFailed', REQUEST_FAILED) });
      } else {
        setArea('upload', { tone: 'success', text: env.msg || t('saved', 'Saved.') });
        setKeyFile(null);
        setCertFile(null);
        if (keyInputRef.current) keyInputRef.current.value = '';
        if (certInputRef.current) certInputRef.current.value = '';
        setPendingRestart(true);
        refreshStatus({ silent: true });
      }
    } catch {
      setArea('upload', { tone: 'error', text: t('settingsTlsRequestFailed', REQUEST_FAILED) });
    } finally {
      setBusy('');
    }
  };

  const doRenew = async () => {
    setBusy('renew');
    setArea('renew', null);
    setArea('restart', null);
    try {
      const payload = useIp ? { use_ip: true } : { domain: domain.trim(), email: email.trim() };
      const res = await apiClient.post('/https/automatic', payload, { timeout: RENEW_TIMEOUT_MS });
      const env = res.data || {};
      if (env.success === false) {
        setArea('renew', { tone: 'error', text: env.msg || t('settingsTlsRequestFailed', REQUEST_FAILED) });
      } else {
        setArea('renew', { tone: 'success', text: env.msg || t('saved', 'Saved.') });
        setPendingRestart(true);
        refreshStatus({ silent: true });
      }
    } catch {
      setArea('renew', {
        tone: 'error',
        text: t('settingsTlsRenewLost', 'No answer from the server. The request can take up to two minutes — refresh the status above before retrying.'),
      });
    } finally {
      setBusy('');
    }
  };

  if (loading && !status) return <PanelSkeleton lines={3} label="Loading…" />;
  if (error && !status) {
    return (
      <ErrorState
        title={t('settingsLoadError', 'Failed to load settings')}
        message={t('settingsTlsLoadError', 'Could not read the HTTPS certificate status.')}
        onRetry={() => refreshStatus()}
        retryLabel={t('retry', 'Retry')}
      />
    );
  }

  const mode = status?.mode || null;
  const modeLabel = mode && MODE_LABEL[mode]
    ? t(MODE_LABEL[mode][0], MODE_LABEL[mode][1])
    : (mode || '—');
  const sourceLabel = status?.source
    ? (SOURCE_LABEL[status.source] ? t(SOURCE_LABEL[status.source][0], SOURCE_LABEL[status.source][1]) : status.source)
    : null;
  const issuerLabel = status?.issued_by
    ? (ISSUER_LABEL[status.issued_by] ? t(ISSUER_LABEL[status.issued_by][0], ISSUER_LABEL[status.issued_by][1]) : status.issued_by)
    : null;
  const days = status?.expires_days;
  const restartDone = feedback.restart?.tone === 'success';
  const restartNeeded = pendingRestart || status?.restart_required === true;

  const restartPrompt = <RestartPrompt onRestart={askRestart} busy={busy} restarting={restarting} />;

  return (
    <div className="sp-cards">
      <Card title={t('settingsTlsCard', 'HTTPS Certificate')} icon={<FiLock aria-hidden="true" />}>
        <div className="ts-status-row">
          <p className="ts-summary">
            {summary || t('settingsTlsStatusUnknown', 'Certificate status is not available.')}
          </p>
          {mode && <Badge tone={MODE_TONE[mode] || 'neutral'} dot>{modeLabel}</Badge>}
        </div>

        <dl className="ts-meta">
          <div>
            <dt>{t('settingsTlsMode', 'Mode')}</dt>
            <dd>{modeLabel}</dd>
          </div>
          {sourceLabel && (
            <div>
              <dt>{t('settingsTlsSource', 'Source')}</dt>
              <dd>{sourceLabel}</dd>
            </div>
          )}
          {issuerLabel && (
            <div>
              <dt>{t('settingsTlsIssuedBy', 'Issued by')}</dt>
              <dd>{issuerLabel}</dd>
            </div>
          )}
          <div>
            <dt>{t('settingsTlsExpiresIn', 'Expires in')}</dt>
            <dd>
              {days == null ? (
                <span className="ts-muted">{t('settingsTlsNotAvailable', 'Not available')}</span>
              ) : days <= 0 ? (
                <Badge tone="danger">{t('settingsTlsExpired', 'Expired')}</Badge>
              ) : (
                <Badge tone={expiryTone(days)}>
                  {t('settingsTlsExpiresInDays', 'Expires in {{count}} days', { count: days })}
                </Badge>
              )}
            </dd>
          </div>
          {status?.subject && (
            <div>
              <dt>{t('settingsTlsSubject', 'Subject')}</dt>
              <dd className="ts-mono">{status.subject}</dd>
            </div>
          )}
          {status?.cert_path && (
            <div>
              <dt>{t('settingsTlsCertFile', 'Certificate file')}</dt>
              <dd className="ts-mono">{status.cert_path}</dd>
            </div>
          )}
        </dl>

        <div className="ts-actions">
          <Button
            variant="secondary"
            size="sm"
            icon={<FiRefreshCw size={13} aria-hidden="true" />}
            loading={loading}
            disabled={busy !== ''}
            onClick={() => refreshStatus()}
          >
            {t('refresh', 'Refresh')}
          </Button>
        </div>

        {restarting ? (
          <Notice tone="info">
            {feedback.restart?.text || t('settingsTlsRestarting', 'Restarting the panel… this page will reconnect automatically in a few seconds.')}
          </Notice>
        ) : (
          <>
            {feedback.restart && <Notice tone={feedback.restart.tone}>{feedback.restart.text}</Notice>}
            {restartNeeded && !restartDone && feedback.restart?.tone !== 'error' && (
              <>
                <Notice tone="warning">
                  {t('settingsTlsRestartRequired', 'A new certificate is waiting. Restart the panel to activate it.')}
                </Notice>
                {restartPrompt}
              </>
            )}
          </>
        )}
      </Card>

      <Card title={t('settingsTlsUploadTitle', 'Use Existing Certificate')} icon={<FiUpload aria-hidden="true" />}>
        <p className="ts-hint">
          {t('settingsTlsUploadHint', 'Upload the private key and its certificate as PEM files (.pem, .key, .crt or .cer, each under 1 MB). The key must match the certificate, and the certificate must not be expired.')}
        </p>
        <div className="ts-files">
          <Field label={t('settingsTlsKeyLabel', 'Private key file (PEM)')} error={fileError.key || undefined}>
            <input
              ref={keyInputRef}
              type="file"
              accept={PEM_ACCEPT}
              disabled={busy !== ''}
              onChange={onPickFile('key')}
            />
          </Field>
          <Field label={t('settingsTlsCertLabel', 'Certificate file (PEM)')} error={fileError.cert || undefined}>
            <input
              ref={certInputRef}
              type="file"
              accept={PEM_ACCEPT}
              disabled={busy !== ''}
              onChange={onPickFile('cert')}
            />
          </Field>
        </div>
        <div className="ts-actions">
          <Button
            variant="primary"
            size="sm"
            icon={<FiUpload size={13} aria-hidden="true" />}
            loading={busy === 'upload'}
            disabled={restarting || (busy !== '' && busy !== 'upload')}
            onClick={doUpload}
          >
            {t('settingsTlsUploadButton', 'Upload certificate')}
          </Button>
        </div>
        {feedback.upload && <Notice tone={feedback.upload.tone}>{feedback.upload.text}</Notice>}
        {feedback.upload?.tone === 'success' && restartNeeded && !restartDone && restartPrompt}
      </Card>

      <Card title={t('settingsTlsMethodTitle', 'Certificate Method')} icon={<FiLock aria-hidden="true" />}>
        <p className="ts-hint">
          {t('settingsTlsMethodHint', 'Saved to the panel database. Run `ovm restart` to apply. A field set in .env overrides the saved value.')}
        </p>
        <div className="ts-renew-grid">
          <Field label={t('settingsTlsMethodLabel', 'Method')}>
            <select
              value={tlsForm.cert_method}
              disabled={tlsBusy !== ''}
              onChange={(e) => setTlsForm((f) => ({ ...f, cert_method: e.target.value }))}
            >
              {['selfsigned', 'letsencrypt', 'none'].map((m) => (
                <option key={m} value={m}>{t(`settingsTlsMethod_${m}`, m)}</option>
              ))}
            </select>
          </Field>
        </div>
        <div className="ts-renew-grid">
          <Field
            label={t('settingsTlsFieldCertFile', 'Certificate file')}
            hint={tlsField('cert_file')?.overridden ? <Badge tone="warning">{t('settingsTlsOverrideBadge', 'Override via .env')}</Badge> : undefined}
          >
            <input
              type="text"
              value={tlsForm.cert_file}
              autoComplete="off"
              spellCheck={false}
              disabled={tlsField('cert_file')?.overridden || tlsBusy !== ''}
              onChange={(e) => setTlsForm((f) => ({ ...f, cert_file: e.target.value }))}
            />
          </Field>
          <Field
            label={t('settingsTlsFieldKeyFile', 'Private key file')}
            hint={tlsField('key_file')?.overridden ? <Badge tone="warning">{t('settingsTlsOverrideBadge', 'Override via .env')}</Badge> : undefined}
          >
            <input
              type="text"
              value={tlsForm.key_file}
              autoComplete="off"
              spellCheck={false}
              disabled={tlsField('key_file')?.overridden || tlsBusy !== ''}
              onChange={(e) => setTlsForm((f) => ({ ...f, key_file: e.target.value }))}
            />
          </Field>
        </div>
        <div className="ts-renew-grid">
          <Field
            label={t('settingsTlsFieldAcmeDomain', 'ACME domain')}
            hint={tlsField('acme_domain')?.overridden ? <Badge tone="warning">{t('settingsTlsOverrideBadge', 'Override via .env')}</Badge> : undefined}
          >
            <input
              type="text"
              value={tlsForm.acme_domain}
              placeholder={t('settingsTlsDomainPlaceholder', 'panel.example.com')}
              autoComplete="off"
              spellCheck={false}
              disabled={tlsField('acme_domain')?.overridden || tlsBusy !== ''}
              onChange={(e) => setTlsForm((f) => ({ ...f, acme_domain: e.target.value }))}
            />
          </Field>
          <Field
            label={t('settingsTlsFieldAcmeEmail', 'ACME email')}
            hint={tlsField('acme_email')?.overridden ? <Badge tone="warning">{t('settingsTlsOverrideBadge', 'Override via .env')}</Badge> : undefined}
          >
            <input
              type="email"
              value={tlsForm.acme_email}
              placeholder={t('settingsTlsEmailPlaceholder', 'you@example.com')}
              autoComplete="off"
              spellCheck={false}
              disabled={tlsField('acme_email')?.overridden || tlsBusy !== ''}
              onChange={(e) => setTlsForm((f) => ({ ...f, acme_email: e.target.value }))}
            />
          </Field>
        </div>
        <div className="ts-actions">
          <Button
            variant="primary"
            size="sm"
            icon={<FiLock size={13} aria-hidden="true" />}
            loading={tlsBusy === 'save'}
            disabled={restarting || (tlsBusy !== '' && tlsBusy !== 'save')}
            onClick={saveTlsSettings}
          >
            {t('settingsTlsSaveButton', 'Save')}
          </Button>
          {tlsForm.cert_method === 'letsencrypt' && (
            <Button
              variant="secondary"
              size="sm"
              icon={<FiGlobe size={13} aria-hidden="true" />}
              loading={tlsBusy === 'renewNow'}
              disabled={restarting || (tlsBusy !== '' && tlsBusy !== 'renewNow')}
              onClick={renewFromSettings}
            >
              {t('settingsTlsRenewNow', 'Renew now')}
            </Button>
          )}
        </div>
        {tlsFeedback && <Notice tone={tlsFeedback.tone}>{tlsFeedback.text}</Notice>}
      </Card>

      <Card title={t('settingsTlsLetsEncryptTitle', "Automatic Certificate")} icon={<FiGlobe aria-hidden="true" />}>
        <p className="ts-hint">
          {t('settingsTlsLetsEncryptHint', 'Requests a free, trusted certificate. The domain must already point to this server, and port 80 must be reachable from the internet. This can take up to two minutes.')}
        </p>
        <div className="ts-renew-grid">
          <Field label={t('settingsTlsDomain', 'Domain')}>
            <input
              type="text"
              value={domain}
              placeholder={t('settingsTlsDomainPlaceholder', 'panel.example.com')}
              autoComplete="off"
              spellCheck={false}
              disabled={useIp || busy !== ''}
              onChange={(e) => setDomain(e.target.value)}
            />
          </Field>
          <Field
            label={t('settingsTlsEmail', 'Email')}
            hint={t('settingsTlsEmailHint', "Optional. Let's Encrypt uses it for expiry notices; a temporary address is used when it is empty.")}
          >
            <input
              type="email"
              value={email}
              placeholder={t('settingsTlsEmailPlaceholder', 'you@example.com')}
              autoComplete="off"
              spellCheck={false}
              disabled={useIp || busy !== ''}
              onChange={(e) => setEmail(e.target.value)}
            />
          </Field>
        </div>
        <label className="ts-check">
          <input
            type="checkbox"
            checked={useIp}
            disabled={busy !== ''}
            onChange={(e) => setUseIp(e.target.checked)}
          />
          <span>{t('settingsTlsUseIp', "Request a certificate for this server's IP address")}</span>
        </label>
        {useIp && (
          <p className="ts-hint">{t('settingsTlsUseIpHint', "Uses the server's primary IP and issues a short-lived certificate.")}</p>
        )}
        <div className="ts-actions">
          <Button
            variant="primary"
            size="sm"
            icon={<FiGlobe size={13} aria-hidden="true" />}
            loading={busy === 'renew'}
            disabled={restarting || (busy !== '' && busy !== 'renew') || (!useIp && !domain.trim())}
            onClick={doRenew}
          >
            {t('settingsTlsRenewButton', 'Request certificate')}
          </Button>
        </div>
        {busy === 'renew' && (
          <p className="ts-hint">{t('settingsTlsRenewing', 'Requesting… this can take up to two minutes. Keep this tab open.')}</p>
        )}
        {feedback.renew && <Notice tone={feedback.renew.tone}>{feedback.renew.text}</Notice>}
        {feedback.renew?.tone === 'success' && restartNeeded && !restartDone && restartPrompt}
      </Card>

      <ConfirmModal
        open={confirm.open}
        onClose={closeConfirm}
        onConfirm={confirm.onConfirm || (() => {})}
        title={confirm.title}
        message={confirm.message}
        confirmLabel={confirm.confirmLabel}
        cancelLabel={t('cancelButton', 'Cancel')}
        danger={false}
      />
    </div>
  );
};

export default TlsSection;
