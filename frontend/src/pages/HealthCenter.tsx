// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FiActivity, FiAlertTriangle, FiDownload, FiRefreshCw } from 'react-icons/fi';
import apiClient from '../services/api';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  PageHeader,
  SkeletonPanel,
} from '../components/ui';
import './HealthCenter.css';
import './UpdateNotice.css';

/**
 * HealthCenter — operational health dashboard.
 *
 * Reads GET /api/health/overview which returns
 *   { checks: [{ id, status: 'ok'|'warn'|'error', summary, hint }], details }
 * and paints one card per check: a fill-token status dot, the plain-language
 * summary, and the remediation hint whenever the check is not ok.
 *
 * Refresh keeps the previous results on screen (only the button enters its
 * busy state) so a slow or failing re-check never blanks a page that was
 * already telling the operator something useful.
 */

const STATUS_META = {
  ok: { tone: 'success', key: 'healthStatusOk', fallback: 'OK' },
  warn: { tone: 'warning', key: 'healthStatusWarn', fallback: 'Warning' },
  error: { tone: 'danger', key: 'healthStatusError', fallback: 'Error' },
};
const UNKNOWN_META = { tone: 'neutral', key: 'healthStatusUnknown', fallback: 'Unknown' };

const statusMeta = (status) => STATUS_META[status] || UNKNOWN_META;

const errorText = (err) => {
  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((d) => d?.msg || '').filter(Boolean).join(', ');
  if (detail && typeof detail === 'object') return JSON.stringify(detail);
  return err?.message || '';
};

const sleep = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });

const HealthCenter = () => {
  const { t } = useTranslation();
  const { userRole } = useAuth();
  const { addToast } = useToast();
  const isOwner = userRole === 'owner';
  const [checks, setChecks] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [checkedAt, setCheckedAt] = useState(null);
  const [updateInfo, setUpdateInfo] = useState(null);
  const [updateRunning, setUpdateRunning] = useState(false);
  const [updateNote, setUpdateNote] = useState('');

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await apiClient.get('/health/overview');
      const payload = res.data?.data ?? res.data ?? {};
      setChecks(Array.isArray(payload.checks) ? payload.checks : []);
      setCheckedAt(new Date());
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Owner-only endpoint: admins would just get a 403, so never ask for them.
  useEffect(() => {
    if (!isOwner) {
      setUpdateInfo(null);
      return undefined;
    }
    let cancelled = false;
    apiClient.get('/updater/status')
      .then((res) => { if (!cancelled) setUpdateInfo(res.data?.data ?? null); })
      .catch(() => { if (!cancelled) setUpdateInfo(null); });
    return () => { cancelled = true; };
  }, [isOwner]);

  const refresh = () => {
    setRefreshing(true);
    load();
  };

  // The installer restarts the panel: wait for it to go down and come back.
  const pollUntilOnline = async () => {
    const deadline = Date.now() + 5 * 60 * 1000;
    await sleep(5000);
    while (Date.now() < deadline) {
      try {
        await apiClient.get('/health/overview', { timeout: 5000 });
        return true;
      } catch {
        await sleep(3000);
      }
    }
    return false;
  };

  const runUpdate = async () => {
    if (updateRunning) return;
    if (!window.confirm(t('updateConfirm', 'The panel will restart briefly and may be unavailable for up to a minute. Continue?'))) return;
    setUpdateRunning(true);
    setUpdateNote('');
    try {
      const res = await apiClient.post('/updater/run');
      const body = res.data || {};
      if (!body.success) {
        // Refusals (Docker, no installer) carry the host-side command in msg.
        setUpdateNote(body.msg || t('updateRefused', 'The panel cannot start the update automatically.'));
        return;
      }
      setUpdateNote(body.msg || t('updateStarted', 'Update started. The panel will restart shortly.'));
      const backOnline = await pollUntilOnline();
      if (backOnline) {
        setUpdateNote(t('updateFinished', 'The panel is back online.'));
        addToast(t('updateFinished', 'The panel is back online.'), 'success');
        await load();
        setUpdateInfo(null);
      } else {
        setUpdateNote(t('updateTimeout', 'The panel did not answer in time. Check the server logs.'));
      }
    } catch (err) {
      setUpdateNote(errorText(err) || t('updateRunFailed', 'Could not start the update.'));
    } finally {
      setUpdateRunning(false);
    }
  };

  const counts = (checks || []).reduce(
    (acc, check) => {
      const status = check?.status;
      if (status === 'ok') acc.ok += 1;
      else if (status === 'warn') acc.warn += 1;
      else if (status === 'error') acc.error += 1;
      else acc.unknown += 1;
      return acc;
    },
    { ok: 0, warn: 0, error: 0, unknown: 0 },
  );

  const overall = counts.error > 0 ? 'error' : counts.warn > 0 ? 'warn' : counts.ok > 0 ? 'ok' : 'unknown';
  const overallMeta = statusMeta(overall);

  const lastChecked = checkedAt
    ? t('healthLastChecked', 'Last checked {{time}}', { time: checkedAt.toLocaleTimeString() })
    : null;

  return (
    <div className="health-page">
      <PageHeader
        title={t('healthTitle', 'System Health')}
        subtitle={t('healthSubtitle', 'Live checks across the panel, database, nodes and integrations.')}
        icon={<FiActivity />}
        meta={checks && (
          <>
            <Badge tone={overallMeta.tone} dot>
              {t(overallMeta.key, overallMeta.fallback)}
            </Badge>
            {lastChecked && <span>{lastChecked}</span>}
          </>
        )}
        actions={
          <Button
            variant="secondary"
            onClick={refresh}
            loading={refreshing}
            disabled={loading}
            icon={<FiRefreshCw aria-hidden="true" />}
          >
            {t('healthRefresh', 'Refresh')}
          </Button>
        }
      />

      {updateInfo?.update_available && (
        <Card tone="warning" className="health-update">
          <div className="update-notice">
            <span className="update-notice-icon" aria-hidden="true"><FiDownload /></span>
            <div className="update-notice-body">
              <h3 className="update-notice-title">{t('updateAvailableTitle', 'Update available')}</h3>
              <p className="update-notice-line">
                {t('updateVersionLine', 'Panel {{current}} → {{latest}}', {
                  current: updateInfo.current,
                  latest: updateInfo.latest,
                })}
              </p>
              <p className="update-notice-note">
                {updateNote || t('updateWarning', 'The panel will restart briefly while it updates.')}
              </p>
            </div>
            {isOwner && (
              <Button
                variant="primary"
                onClick={runUpdate}
                loading={updateRunning}
                disabled={updateRunning}
              >
                {updateRunning ? t('updateRunning', 'Updating…') : t('updateNow', 'Update now')}
              </Button>
            )}
          </div>
        </Card>
      )}

      {error && checks && (
        <p className="health-refresh-error" role="status">
          <FiAlertTriangle aria-hidden="true" />
          {t('healthRefreshFailed', 'Refresh failed — showing the previous results.')}
        </p>
      )}

      {loading && !checks && (
        <div className="health-grid" role="status" aria-live="polite" aria-label={t('loading', 'Loading...')}>
          <SkeletonPanel lines={3} />
          <SkeletonPanel lines={3} />
          <SkeletonPanel lines={3} />
          <SkeletonPanel lines={3} />
        </div>
      )}

      {!loading && !checks && error && (
        <ErrorState
          title={t('healthErrorTitle', "Couldn't load health checks")}
          message={errorText(error) || t('healthErrorBody', 'The health endpoint did not respond.')}
          onRetry={refresh}
          retryLabel={t('retry', 'Retry')}
        />
      )}

      {checks && checks.length === 0 && (
        <EmptyState title={t('healthEmpty', 'No checks reported yet')} />
      )}

      {checks && checks.length > 0 && (
        <>
          {counts.error + counts.warn > 0 && (
            <p className="health-alert">
              {t('healthIssuesSummary', '{{count}} check(s) need attention', { count: counts.error + counts.warn })}
            </p>
          )}
          <div className="health-grid" aria-live="polite">
            {checks.map((check, index) => {
              const meta = statusMeta(check?.status);
              const summary = check?.summary || check?.id || `#${index + 1}`;
              const showHint = check?.status !== 'ok' && check?.hint;
              return (
                <Card key={check?.id || index} tone={meta.tone} className="health-check">
                  <div className="health-check-head">
                    <span className={`health-dot health-dot--${check?.status || 'unknown'}`} aria-hidden="true" />
                    <h3 className="health-check-summary">{summary}</h3>
                    <Badge tone={meta.tone}>{t(meta.key, meta.fallback)}</Badge>
                  </div>
                  {showHint && (
                    <p className={`health-check-hint health-check-hint--${check.status}`}>{check.hint}</p>
                  )}
                </Card>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
};

export default HealthCenter;
