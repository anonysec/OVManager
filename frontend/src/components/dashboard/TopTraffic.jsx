// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * TopTraffic — top users by billed bytes over the last 7 days.
 * Self-contained (own fetch) so the dashboard page never waits on it.
 */
import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import apiClient from '../../services/api';
import { formatTraffic } from '../../utils/format';

export default function TopTraffic() {
  const { t } = useTranslation();
  const [rows, setRows] = useState(null);

  useEffect(() => {
    let cancelled = false;
    apiClient
      .get('/users/traffic/top', { params: { days: 7, limit: 5 } })
      .then((r) => {
        if (cancelled) return;
        const list = r.data?.data;
        setRows(Array.isArray(list) ? list : []);
      })
      .catch(() => {
        if (!cancelled) setRows([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!rows || rows.length === 0) return null;
  const max = Math.max(...rows.map((r) => Number(r.bytes || 0)), 1);

  return (
    <div className="ds-toptraffic" aria-label={t('topTraffic7d', 'Top traffic, 7 days')}>
      <span className="ds-toptraffic-title">{t('topTraffic7d', 'Top traffic, 7 days')}</span>
      <ul>
        {rows.map((r) => (
          <li key={r.name}>
            <span className="ds-toptraffic-name" title={r.name}>{r.name}</span>
            <span className="ds-toptraffic-bar" aria-hidden="true">
              <span style={{ width: `${Math.max(2, Math.round((Number(r.bytes || 0) / max) * 100))}%` }} />
            </span>
            <span className="ds-toptraffic-val">{formatTraffic(r.bytes)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
