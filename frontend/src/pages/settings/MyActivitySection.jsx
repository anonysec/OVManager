// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FiActivity, FiRefreshCw } from 'react-icons/fi';
import apiClient from '../../services/api';
import { fmtRelative } from '../../utils/time';
import { Card } from './shared';
import './MyActivitySection.css';

/* ═══════════════════════════════════════════════════════
   MY ACTIVITY (simple) — the caller's own audit trail.

   GET /activity/?limit=20 is already scoped by the backend:
   the owner sees every event, an admin only their own.
   ═══════════════════════════════════════════════════════ */

const LIMIT = 20;

// Friendlier words for common action segments ("node.tls_unverified" becomes
// "Node · TLS unverified"). Unknown segments are only title-cased.
const ACTION_WORDS = {
  tls: 'TLS',
  tls_unverified: 'TLS unverified',
  ovpn: 'OVPN',
  urlpath: 'URL path',
  api: 'API',
};

const readableAction = (action) => {
  const raw = String(action || '').trim();
  if (!raw) return '—';
  return raw
    .split('.')
    .map((part) => ACTION_WORDS[part] || part.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()))
    .join(' · ');
};

const MyActivitySection = () => {
  const { t, i18n } = useTranslation();
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  // Wall-clock seconds in state, so relative times never call Date.now()
  // during render (same pattern as the AuditLog page).
  const [nowTs, setNowTs] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const res = await apiClient.get('/activity/', { params: { limit: LIMIT } });
      if (res.data?.success) {
        setEvents(res.data.data || []);
      } else {
        setError(true);
      }
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const tick = () => setNowTs(Math.floor(Date.now() / 1000));
    tick();
    const id = setInterval(tick, 30000);
    return () => clearInterval(id);
  }, []);

  const rtf = useMemo(() => {
    try {
      return new Intl.RelativeTimeFormat(i18n.language || 'en', { numeric: 'auto' });
    } catch {
      return null;
    }
  }, [i18n.language]);

  // Localized "5m ago"; falls back to the shared English helper before the
  // first clock tick or on engines without RelativeTimeFormat.
  const timeAgo = (ts) => {
    if (!ts) return '—';
    const asIso = new Date(Number(ts) * 1000).toISOString();
    if (!rtf || !nowTs) return fmtRelative(asIso);
    const diff = Math.round(Number(ts) - nowTs);
    const abs = Math.abs(diff);
    if (abs < 60) return rtf.format(diff, 'second');
    if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute');
    if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour');
    if (abs < 604800) return rtf.format(Math.round(diff / 86400), 'day');
    if (abs < 2592000) return rtf.format(Math.round(diff / 604800), 'week');
    if (abs < 31536000) return rtf.format(Math.round(diff / 2592000), 'month');
    return rtf.format(Math.round(diff / 31536000), 'year');
  };

  const empty = events.length === 0;

  return (
    <Card title={t('activityCard', 'My activity')} icon={FiActivity}>
      <div className="ma-head">
        <p className="ma-desc">{t('activityDesc', 'Your latest actions on this panel.')}</p>
        <button type="button" className="btn btn-sm" onClick={load} disabled={loading}>
          <FiRefreshCw size={12} aria-hidden="true" className={loading ? 'ma-spin' : undefined} />
          {t('activityRefresh', 'Refresh')}
        </button>
      </div>

      {loading && empty ? (
        <p className="ma-state">{t('activityLoading', 'Loading…')}</p>
      ) : error && empty ? (
        <p className="ma-state ma-state--error" role="alert">{t('activityError', 'Could not load activity.')}</p>
      ) : empty ? (
        <p className="ma-state">{t('activityEmpty', 'No activity yet.')}</p>
      ) : (
        <ul className="ma-list">
          {events.map((e, index) => (
            <li className="ma-row" key={e.id ?? `${e.ts}-${index}`}>
              <span className="ma-time">{timeAgo(e.ts)}</span>
              <span className="ma-action">{readableAction(e.action)}</span>
              <span className="ma-target">{e.target || '—'}</span>
            </li>
          ))}
        </ul>
      )}

      {error && !empty && (
        <p className="ma-state ma-state--error" role="alert">{t('activityError', 'Could not load activity.')}</p>
      )}
    </Card>
  );
};

export default MyActivitySection;
