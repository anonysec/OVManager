// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useToast } from '../../context/ToastContext';
import apiClient from '../../services/api';
import LoadingButton from '../../components/LoadingButton';
import PanelSkeleton from '../../components/ui/PanelSkeleton';
import ErrorState from '../../components/ui/ErrorState';
import { FiClock, FiEdit2, FiCheck, FiX } from 'react-icons/fi';
import { Card } from './shared';
import useInlineEditFocus from './useInlineEditFocus';

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

export default DisplaySection;
