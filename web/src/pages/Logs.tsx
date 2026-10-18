// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

// System logs — journalctl tails for the panel and its nodes (plan Task 2).
// The backend caps the read; follow is a 5s tail refetch, paused whenever the
// tab is hidden or the operator unfollows.
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FiFileText, FiPause, FiPlay, FiRefreshCw } from 'react-icons/fi';
import apiClient from '../services/api';
import { asList } from '../utils/apiData';
import { errorMessageOf } from '../utils/errorMessage';
import { Button, PageHeader } from '../components/ui';
import './Logs.css';

const LINES_KEY = 'ovmanager-logs-lines';
const LINE_OPTIONS = [100, 200, 500];

const Logs = () => {
  const { t } = useTranslation();
  const [unit, setUnit] = useState('ovmanager');
  const [lines, setLines] = useState(() => Number(localStorage.getItem(LINES_KEY)) || 200);
  const [nodes, setNodes] = useState<{ name: string }[]>([]);
  const [output, setOutput] = useState('');
  const [error, setError] = useState('');
  const [follow, setFollow] = useState(true);

  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => { localStorage.setItem(LINES_KEY, String(lines)); }, [lines]);

  // Nodes are owner-gated; admins just see the Panel until they pick one up
  // another way — the select degrades quietly.
  useEffect(() => {
    let cancelled = false;
    apiClient.get('/nodes/').then((res: any) => {
      if (cancelled) return;
      setNodes(asList(res?.data?.data?.nodes ?? res?.data, 'nodes').map((n: any) => ({ name: String(n.name) })));
    }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const fetchLogs = useCallback(async (opts: { background?: boolean } = {}) => {
    if (!opts.background) setError('');
    try {
      const res = await apiClient.get('/logs', { params: { unit, lines } });
      setOutput(res.data || '');
      setError('');
    } catch (e) {
      setOutput('');
      if (!opts.background) setError(errorMessageOf(e, t('logsError', 'Failed to load logs.')));
    }
  }, [unit, lines, t]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  // tail -f: poll only while the tab is visible and follow is on.
  useEffect(() => {
    if (!follow) return;
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') fetchLogs({ background: true });
    }, 5000);
    const onVisible = () => { if (document.visibilityState === 'visible') fetchLogs({ background: true }); };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [follow, fetchLogs]);

  // Keep the tail in view.
  useEffect(() => {
    if (follow && bottomRef.current) bottomRef.current.scrollIntoView({ block: 'end' });
  }, [output, follow]);

  return (
    <div className="logs-page">
      <PageHeader
        title={t('logsTitle', 'System logs')}
        subtitle={t('logsSubtitle', 'Last journal lines for the panel and its nodes')}
        icon={<FiFileText />}
        actions={
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
        }
      />

      <div className="logs-controls">
        <label>
          <span>{t('logsUnit', 'Unit')}</span>
          <select value={unit} onChange={(e) => setUnit(e.target.value)}>
            <option value="ovmanager">{t('logsUnitPanel', 'Panel')}</option>
            {nodes.map((n) => (
              <option key={n.name} value={`openvpn-${n.name}`}>{n.name}</option>
            ))}
          </select>
        </label>
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
        ) : output ? (
          <pre className="log-rows">{output}</pre>
        ) : (
          <div className="log-rows-empty" aria-live="polite">{t('logsEmpty', 'No log output')}</div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
};

export default Logs;
