// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import apiClient from '../../services/api';
import ConfirmModal from '../../components/ConfirmModal';
import PanelSkeleton from '../../components/ui/PanelSkeleton';
import ErrorState from '../../components/ui/ErrorState';
import { Badge, Button, Card, Field } from '../../components/ui';
import {
  FiAlertCircle, FiCheckCircle, FiExternalLink, FiGlobe, FiInfo,
  FiLock, FiRefreshCw, FiShield, FiUpload, FiZap,
} from 'react-icons/fi';
import './TlsSection.css';

/* ═══════════════════════════════════════════════════════
   TLS (advanced) — the panel's own HTTPS certificate.

   GET  /tls/status       what certificate the panel will use
   POST /tls/upload       install a key + certificate pair (multipart)
   POST /tls/self-signed  regenerate a self-signed certificate
   POST /tls/renew        request a Let's Encrypt certificate via acme.sh
   POST /tls/restart      best-effort panel restart so changes apply

   Every endpoint is owner-only. File-based changes only take effect after a
   panel restart, so each successful install surfaces the same restart action.
   ═══════════════════════════════════════════════════════ */

const MAX_FILE_BYTES = 1024 * 1024;
const PEM_ACCEPT = '.pem,.key,.crt,.cer';
const PEM_RE = /\.(pem|key|crt|cer)$/i;
// acme.sh issue (180s) + install (60s) can outlive the client's default timeout.
const RENEW_TIMEOUT_MS = 250000;
const RESTART_POLL_MS = 2500;
const RESTART_POLL_ATTEMPTS = 20;
const REQUEST_FAILED = 'The request failed. Please try again.';

const MODE_TONE = { managed: 'success', files: 'info', disabled: 'neutral', misconfigured: 'danger' };
const MODE_LABEL = {
  managed: ['settingsTlsMode_managed', 'Managed by the panel'],
  files: ['settingsTlsMode_files', 'Files from the environment'],
  disabled: ['settingsTlsMode_disabled', 'Disabled (HTTP only)'],
  misconfigured: ['settingsTlsMode_misconfigured', 'Misconfigured'],
};
const SOURCE_LABEL = {
  'panel-managed': ['settingsTlsSource_panelManaged', 'Panel-managed'],
  environment: ['settingsTlsSource_environment', 'Environment'],
};
const ISSUER_LABEL = {
  'self-signed': ['settingsTlsIssuer_selfSigned', 'Self-signed'],
  custom: ['settingsTlsIssuer_custom', 'Custom / uploaded'],
};

const expiryTone = (days) => {
  if (days == null) return 'neutral';
  if (days <= 7) return 'danger';
  if (days <= 30) return 'warning';
  return 'success';
};

const Notice = ({ tone = 'info', children }) => {
  const Icon = tone === 'error' ? FiAlertCircle : tone === 'success' ? FiCheckCircle : FiInfo;
  return (
    <div className={`ts-notice ts-notice--${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      <Icon size={14} aria-hidden="true" />
      <span>{children}</span>
    </div>
  );
};

const RestartPrompt = ({ onRestart, busy, restarting }) => {
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
  const navigate = useNavigate();

  const [status, setStatus] = useState(null);
  const [summary, setSummary] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState('');
  const [restarting, setRestarting] = useState(false);
  const [pendingRestart, setPendingRestart] = useState(false);
  const [feedback, setFeedback] = useState({});

  const [keyFile, setKeyFile] = useState(null);
  const [certFile, setCertFile] = useState(null);
  const [fileError, setFileError] = useState({ key: '', cert: '' });
  const keyInputRef = useRef(null);
  const certInputRef = useRef(null);

  const [domain, setDomain] = useState('');
  const [email, setEmail] = useState('');
  const [useIp, setUseIp] = useState(false);

  const [confirm, setConfirm] = useState({ open: false, title: '', message: '', confirmLabel: '', onConfirm: null });
  const pollRef = useRef({ attempts: 0, timer: null });

  const setArea = useCallback((area, value) => {
    setFeedback((f) => ({ ...f, [area]: value }));
  }, []);

  const closeConfirm = () => setConfirm((c) => ({ ...c, open: false }));
  const askConfirm = (title, message, confirmLabel, onConfirm) =>
    setConfirm({ open: true, title, message, confirmLabel, onConfirm });

  const refreshStatus = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setLoading(true);
    try {
      const res = await apiClient.get('/tls/status');
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

  const clearPoll = useCallback(() => {
    if (pollRef.current.timer) clearTimeout(pollRef.current.timer);
    pollRef.current = { attempts: 0, timer: null };
  }, []);
  useEffect(() => clearPoll, [clearPoll]);

  // After a restart the panel disconnects for a moment; poll the status
  // endpoint until it answers again instead of asking the operator to reload.
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
      const res = await apiClient.post('/tls/restart', {}, { timeout: 20000 });
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
      // The restart can cut the response off mid-flight; treat that as started.
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

  const onPickFile = (slot) => (event) => {
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
      const res = await apiClient.post('/tls/upload', form, { timeout: 60000 });
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

  const doSelfSigned = async () => {
    setBusy('selfSigned');
    setArea('selfSigned', null);
    setArea('restart', null);
    try {
      const res = await apiClient.post('/tls/self-signed', {}, { timeout: 60000 });
      const env = res.data || {};
      if (env.success === false) {
        setArea('selfSigned', { tone: 'error', text: env.msg || t('settingsTlsRequestFailed', REQUEST_FAILED) });
      } else {
        setArea('selfSigned', { tone: 'success', text: env.msg || t('saved', 'Saved.') });
        setPendingRestart(true);
        refreshStatus({ silent: true });
      }
    } catch {
      setArea('selfSigned', { tone: 'error', text: t('settingsTlsRequestFailed', REQUEST_FAILED) });
    } finally {
      setBusy('');
    }
  };

  const askSelfSigned = () => askConfirm(
    t('settingsTlsSelfSignedConfirmTitle', 'Replace the current certificate?'),
    t('settingsTlsSelfSignedConfirm', 'A new self-signed certificate will replace the current one. Browsers will warn that the connection is not trusted until you accept it manually. Continue?'),
    t('settingsTlsSelfSignedButton', 'Generate self-signed certificate'),
    doSelfSigned,
  );

  const doRenew = async () => {
    setBusy('renew');
    setArea('renew', null);
    setArea('restart', null);
    try {
      const payload = useIp ? { use_ip: true } : { domain: domain.trim(), email: email.trim() };
      const res = await apiClient.post('/tls/renew', payload, { timeout: RENEW_TIMEOUT_MS });
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
        message={t('settingsTlsLoadError', 'Could not read the TLS status.')}
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
      <Card title={t('settingsTlsCard', 'Panel Certificate (TLS)')} icon={<FiLock aria-hidden="true" />}>
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
          <Button
            variant="ghost"
            size="sm"
            iconRight={<FiExternalLink size={13} aria-hidden="true" />}
            onClick={() => navigate('/health')}
          >
            {t('settingsTlsOpenHealth', 'Open Health Center')}
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

      <Card title={t('settingsTlsUploadTitle', 'Upload Certificate')} icon={<FiUpload aria-hidden="true" />}>
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

      <Card title={t('settingsTlsSelfSignedTitle', 'Self-signed Certificate')} icon={<FiShield aria-hidden="true" />}>
        <p className="ts-hint">
          {t('settingsTlsSelfSignedHint', "Creates a new certificate valid for 10 years for this server's primary IP. Because no public authority signs it, browsers show a security warning until you accept it.")}
        </p>
        <div className="ts-actions">
          <Button
            variant="secondary"
            size="sm"
            icon={<FiShield size={13} aria-hidden="true" />}
            loading={busy === 'selfSigned'}
            disabled={restarting || (busy !== '' && busy !== 'selfSigned')}
            onClick={askSelfSigned}
          >
            {t('settingsTlsSelfSignedButton', 'Generate self-signed certificate')}
          </Button>
        </div>
        {feedback.selfSigned && <Notice tone={feedback.selfSigned.tone}>{feedback.selfSigned.text}</Notice>}
        {feedback.selfSigned?.tone === 'success' && restartNeeded && !restartDone && restartPrompt}
      </Card>

      <Card title={t('settingsTlsLetsEncryptTitle', "Let's Encrypt Certificate")} icon={<FiGlobe aria-hidden="true" />}>
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
