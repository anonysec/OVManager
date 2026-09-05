// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useLive } from '../../context/LiveContext';
import apiClient from '../../services/api';
import PanelSkeleton from '../../components/ui/PanelSkeleton';
import ErrorState from '../../components/ui/ErrorState';
import EmptyState from '../../components/ui/EmptyState';
import { FiActivity } from 'react-icons/fi';
import { Card } from './shared';
import { fmtDateTime } from '../../utils/time';

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

export default ActivitySection;
