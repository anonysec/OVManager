// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useToast } from '../../context/ToastContext';
import { useLive } from '../../context/LiveContext';
import apiClient from '../../services/api';
import LoadingButton from '../../components/LoadingButton';
import PanelSkeleton from '../../components/ui/PanelSkeleton';
import ErrorState from '../../components/ui/ErrorState';
import { FiUserPlus, FiCheck } from 'react-icons/fi';
import { Card, Field } from './shared';

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

export default DefaultsSection;
