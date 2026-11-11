// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

// System & Audit logs — unified hub with tabs for journalctl tails and audit events.
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
import { FiActivity, FiFileText, FiPause, FiPlay, FiRefreshCw } from 'react-icons/fi';
import apiClient from '../services/api';
import { errorMessageOf } from '../utils/errorMessage';
import { Button, PageHeader, Tabs } from '../components/ui';
import { useAuth } from '../context/AuthContext';
import AuditLog from './AuditLog';
import './Logs.css';

const LINES_KEY = 'ovmanager-logs-lines';
const LINE_OPTIONS = [100, 200, 500];

const Logs = () => {
  const { t } = useTranslation();
  const { userRole } = useAuth();
  const isOwner = userRole === 'owner';

  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get('tab');
  const activeTab = tabParam === 'audit' && isOwner ? 'audit' : 'system';

  const handleTabChange = (nextTab: string) => {
    setSearchParams(nextTab === 'system' ? {} : { tab: nextTab });
  };

  const [lines, setLines] = useState(() => { try { const n = Number(localStorage.getItem(LINES_KEY)); return LINE_OPTIONS.includes(n) ? n : 200; } catch { return 200; } });
  const [output, setOutput] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [follow, setFollow] = useState(true);

  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => { try { localStorage.setItem(LINES_KEY, String(lines)); } catch { /* blocked storage */ } }, [lines]);

  const fetchLogs = useCallback(async (opts: { background?: boolean } = {}) => {
    if (!opts.background) { setError(''); setLoading(true); }
    try {
      const res = await apiClient.get('/logs', { params: { lines } });
      setOutput(res.data || '');
      setError('');
    } catch (e) {
      if (!opts.background) {
        setOutput('');
        setError(errorMessageOf(e, t('logsError', 'Failed to load logs.')));
      }
    } finally {
      if (!opts.background) setLoading(false);
    }
  }, [lines, t]);

  useEffect(() => {
    if (activeTab === 'system') {
      fetchLogs();
    }
  }, [fetchLogs, activeTab]);

  // tail -f: poll only while the tab is visible and follow is on.
  useEffect(() => {
    if (!follow || activeTab !== 'system') return;
    const id = setInterval(() => {
      if (!document.hidden) fetchLogs({ background: true });
    }, 5000);
    const onVisible = () => { if (!document.hidden) fetchLogs({ background: true }); };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [follow, fetchLogs, activeTab]);

  // Keep the tail in view.
  useEffect(() => {
    if (follow && activeTab === 'system' && bottomRef.current) bottomRef.current.scrollIntoView({ block: 'end' });
  }, [output, follow, activeTab]);

  const tabs = [
    { id: 'system', label: t('logsTitle', 'System logs'), icon: <FiFileText /> },
    { id: 'audit', label: t('audit', 'Audit'), icon: <FiActivity /> },
  ];

  return (
    <div className="logs-page">
      <PageHeader
        title={t('navLogs', 'Logs')}
        subtitle={
          activeTab === 'system'
            ? t('logsSubtitle', 'Last journal lines for the panel and its nodes')
            : t('auditSubtitle', 'Who changed what, and when. Entries are scoped to the admins you can see.')
        }
        icon={activeTab === 'system' ? <FiFileText /> : <FiActivity />}
        actions={
          activeTab === 'system' ? (
            <>
              <Button
                variant="secondary"
                icon={follow ? <FiPause /> : <FiPlay />}
                aria-pressed={follow}
                onClick={() => setFollow((f) => !f)}
              >
                {t('logsFollow', 'Follow')}
              </Button>
              <Button variant="secondary" icon={<FiRefreshCw />} onClick={() => fetchLogs()}>
                {t('logsRefresh', 'Refresh')}
              </Button>
            </>
          ) : undefined
        }
      />

      {isOwner && (
        <div style={{ marginBottom: 'var(--space-4)' }}>
          <Tabs
            tabs={tabs}
            value={activeTab}
            onChange={handleTabChange}
            ariaLabel={t('navLogs', 'Logs')}
          />
        </div>
      )}

      {activeTab === 'system' ? (
        <>
          <div className="logs-controls">
            <label>
              <span>{t('logsLines', 'Lines')}</span>
              <select value={lines} onChange={(e) => setLines(Number(e.target.value))}>
                {LINE_OPTIONS.map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
            </label>
          </div>

          <div className={`logs-view${error ? ' logs-view--error' : ''}`}>
            {error ? (
              <div className="logs-error" role="alert">{error}</div>
            ) : loading ? (
              <div className="log-rows-empty" aria-live="polite" aria-busy="true">{t('loading', 'Loading…')}</div>
            ) : output ? (
              <pre className="log-rows">{output}</pre>
            ) : (
              <div className="log-rows-empty" aria-live="polite">{t('logsEmpty', 'No log output')}</div>
            )}
            <div ref={bottomRef} />
          </div>
        </>
      ) : (
        <AuditLog hideHeader />
      )}
    </div>
  );
};

export default Logs;
