// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useToast } from '../../context/ToastContext';
import apiClient from '../../services/api';
import LoadingButton from '../../components/LoadingButton';
import { PanelSkeleton } from '../../components/ui';
import ErrorState from '../../components/ui/ErrorState';
import { FiLink, FiEdit2, FiCheck, FiX, FiCopy, FiExternalLink, FiInfo } from 'react-icons/fi';
import { Card, Field } from './shared';
import useInlineEditFocus from './useInlineEditFocus';

/* ═══════════════════════════════════════════════════════
   GENERAL (advanced) — Panel URL path + subscription prefix
═══════════════════════════════════════════════════════ */
type SharedState = {
  loading?: boolean;
  error?: boolean;
  reload?: () => void;
  data?: any;
};

type GeneralApiError = { response?: { data?: { msg?: string } } };

const GeneralSection = ({ shared }: { shared?: SharedState }) => {
  const { t } = useTranslation();
  const { addToast } = useToast();
  const [urlPath, setUrlPath] = useState('');
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState('');
  const [confirmSaved, setConfirmSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [subPrefix, setSubPrefix] = useState('');
  const [subPrefixEditing, setSubPrefixEditing] = useState(false);
  const [subPrefixValue, setSubPrefixValue] = useState('');
  const [subPrefixSaving, setSubPrefixSaving] = useState(false);
  const [profile, setProfile] = useState({ title: '', support: '', announce: '', interval: '12' });
  const [profileSaving, setProfileSaving] = useState(false);
  const loading = shared?.loading ?? true;
  const loadError = shared?.error ?? false;
  const load = shared?.reload ?? (() => {});
  const synced = useRef(false);
  const urlInputRef = useRef(null);
  const urlTriggerRef = useRef(null);
  const subInputRef = useRef(null);
  const subTriggerRef = useRef(null);
  useInlineEditFocus(editing, urlInputRef, urlTriggerRef);
  useInlineEditFocus(subPrefixEditing, subInputRef, subTriggerRef);

  useEffect(() => {
    const s = shared?.data;
    if (!s || synced.current) return;
    synced.current = true;
    setUrlPath(s.urlpath || '');
    setSubPrefix(s.subscription_url_prefix || '');
    setProfile({
      title: s.sub_profile_title ?? '',
      support: s.sub_support_url ?? '',
      announce: s.sub_announce ?? '',
      interval: String(s.sub_update_interval_hours ?? 12),
    });
  }, [shared]);

  const saveUrlPath = async () => {
    setSaving(true); setError('');
    try {
      const v = editValue.trim().replace(/^\/+|\/+$/g, '');
      if (v && !/^[A-Za-z0-9_-]+$/.test(v)) { setError(t('urlInvalid', 'Only letters, numbers, dashes and underscores.')); return; }
      if (v.length > 64) { setError(t('urlInvalid', 'Max 64 characters.')); return; }
      const res = await apiClient.put('/server/settings/urlpath', { urlpath: v });
      setUrlPath(v); setEditing(false);
      addToast(t('saved', 'Saved.'), 'success');
      const newBase = v ? `/${v}` : '';
      setTimeout(() => { window.location.assign(`${window.location.origin}${newBase}/settings`); }, 600);
      void res;
    } catch (e) { setError((e as GeneralApiError).response?.data?.msg || t('error', 'Error')); }
    finally { setSaving(false); }
  };

  const saveSubPrefix = async () => {
    setSubPrefixSaving(true);
    try {
      await apiClient.put('/server/settings/subscription', { subscription_url_prefix: subPrefixValue.trim() });
      setSubPrefix(subPrefixValue.trim()); setSubPrefixEditing(false);
      addToast(t('saved', 'Saved.'), 'success');
    } catch (e) { addToast((e as GeneralApiError).response?.data?.msg || t('error', 'Error'), 'error'); }
    finally { setSubPrefixSaving(false); }
  };

  const saveProfile = async () => {
    const hours = Number(profile.interval);
    if (!Number.isInteger(hours) || hours < 1 || hours > 168) {
      addToast(t('subIntervalInvalid', 'Update interval must be between 1 and 168 hours.'), 'error');
      return;
    }
    setProfileSaving(true);
    try {
      const res = await apiClient.put('/server/settings/subscription', {
        sub_profile_title: profile.title.trim(),
        sub_support_url: profile.support.trim(),
        sub_announce: profile.announce.trim(),
        sub_update_interval_hours: hours,
      });
      if (res?.data?.success === false) throw new Error(res.data.msg || 'save failed');
      addToast(t('saved', 'Saved.'), 'success');
    } catch (e) { addToast((e as GeneralApiError).response?.data?.msg || (e as Error).message || t('error', 'Error'), 'error'); }
    finally { setProfileSaving(false); }
  };

  const panelUrl = urlPath ? `${window.location.origin}/${urlPath}/` : `${window.location.origin}/`;

  const editValueClean = editValue.trim().replace(/^\/+|\/+$/g, '');
  const pathChanged = editValueClean !== urlPath;
  const newPanelUrl = editValueClean ? `${window.location.origin}/${editValueClean}/` : `${window.location.origin}/`;

  if (loading) return <PanelSkeleton lines={4} label="Loading…" />;
  if (loadError) return <ErrorState title={t('settingsLoadError', 'Failed to load settings')} message={t('settingsLoadErrorDetail', 'Could not reach the server.')} onRetry={load} retryLabel={t('retry', 'Retry')} />;

  return (
    <div className="sp-cards">
      <Card title={t('panelUrl', 'Panel URL Path')} icon={FiLink}>
        <div className="sp-url-row">
          <code className="sp-code">{urlPath ? `/${urlPath}/` : '/'}</code>
          {!editing && (
            <button ref={urlTriggerRef} className="sp-icon-btn" onClick={() => { setEditValue(urlPath); setEditing(true); setError(''); setConfirmSaved(false); }} aria-label={t('changePanelPath', 'Change panel URL path')}>
              <FiEdit2 size={14} aria-hidden="true" />
            </button>
          )}
        </div>
        {editing && (
          <div className="sp-inline-edit">
            <label className="sr-only" htmlFor="general-urlpath">{t('panelUrl', 'Panel URL Path')}</label>
            <input
              id="general-urlpath" ref={urlInputRef}
              type="text" value={editValue}
              placeholder={t('enterPath', 'e.g. dashboard')}
              onChange={e => setEditValue(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && (!pathChanged || confirmSaved)) saveUrlPath(); if (e.key === 'Escape') setEditing(false); }}
              className="sp-input"
            />
            {error && <p className="sp-error" role="alert">{error}</p>}
            {pathChanged && (
              <div className="sp-urlpath-confirm">
                <div className="sp-url-preview">
                  <span className="sp-label-xs">{t('urlpathNewUrl', 'Panel will move to')}</span>
                  <code className="sp-code">{newPanelUrl}</code>
                  <button
                    type="button" className="sp-icon-btn" aria-label={t('copy', 'Copy')}
                    onClick={() => { navigator.clipboard?.writeText(newPanelUrl).catch(() => {}); addToast(t('copied', 'Copied.'), 'success'); }}
                  >
                    <FiCopy size={12} aria-hidden="true" />
                  </button>
                </div>
                <label className="sp-check">
                  <input type="checkbox" checked={confirmSaved} onChange={e => setConfirmSaved(e.target.checked)} />
                  <span>{t('urlpathConfirmSaved', 'I saved the new URL — the old one stops working immediately.')}</span>
                </label>
              </div>
            )}
            <div className="sp-row-btns">
              <LoadingButton className="btn btn-sm" isLoading={saving} onClick={saveUrlPath} disabled={pathChanged && !confirmSaved}><FiCheck size={12} /> {t('save', 'Save')}</LoadingButton>
              <button className="btn btn-sm btn-secondary" onClick={() => setEditing(false)}><FiX size={12} /> {t('cancel', 'Cancel')}</button>
            </div>
          </div>
        )}
        <div className="sp-url-preview">
          <span className="sp-label-xs">{t('panelUrl', 'Full URL')}</span>
          <a href={panelUrl} target="_blank" rel="noopener noreferrer" className="sp-link">
            {panelUrl} <FiExternalLink size={11} />
          </a>
        </div>
        <p className="sp-hint">{urlPath ? t('urlpathActive', 'Panel served at /{path}/. Clear to serve at root.', { path: urlPath }) : t('urlpathRoot', 'Panel served at root (/).')}</p>
      </Card>

      <Card title={t('subscriptionLinkCard', 'Subscription URL Prefix')} icon={FiLink}>
        <div className="sp-url-row">
          <code className="sp-code sp-code--muted">{subPrefix || t('notSet', '(uses panel origin)')}</code>
          {!subPrefixEditing && (
            <button ref={subTriggerRef} className="sp-icon-btn" onClick={() => { setSubPrefixValue(subPrefix); setSubPrefixEditing(true); }} aria-label={t('changeSubPrefix', 'Change subscription URL prefix')}>
              <FiEdit2 size={14} aria-hidden="true" />
            </button>
          )}
        </div>
        {subPrefixEditing && (
          <div className="sp-inline-edit">
            <label className="sr-only" htmlFor="general-subprefix">{t('subscriptionLinkCard', 'Subscription URL Prefix')}</label>
            <input id="general-subprefix" ref={subInputRef} type="text" value={subPrefixValue} placeholder="https://panel.example.com" onChange={e => setSubPrefixValue(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') saveSubPrefix(); if (e.key === 'Escape') setSubPrefixEditing(false); }} className="sp-input" />
            <div className="sp-row-btns">
              <LoadingButton className="btn btn-sm" isLoading={subPrefixSaving} onClick={saveSubPrefix}><FiCheck size={12} /> {t('save', 'Save')}</LoadingButton>
              <button className="btn btn-sm btn-secondary" onClick={() => setSubPrefixEditing(false)}><FiX size={12} /> {t('cancel', 'Cancel')}</button>
            </div>
          </div>
        )}
        <p className="sp-hint">{t('subscriptionLinkDesc', 'Override the base URL used in user subscription links. Leave empty to use the panel origin.')}</p>
      </Card>

      <Card title={t('subProfileCard', 'Subscription Page')} icon={FiInfo}>
        <p className="sp-hint sp-mb-14">{t('subProfileDesc', 'Title, support link, announcement and refresh interval shown on the client subscription page.')}</p>
        <div className="sp-two-col">
          <Field label={t('subProfileTitle', 'Page title')} inputId="sub-profile-title">
            <input id="sub-profile-title" className="sp-input" type="text" maxLength={64} value={profile.title} placeholder="OVManager VPN" onChange={e => setProfile({ ...profile, title: e.target.value })} />
          </Field>
          <Field label={t('subUpdateInterval', 'Update interval (hours)')} hint={t('subUpdateIntervalHint', 'Shown to clients as the refresh cadence (1–168).')} inputId="sub-profile-interval">
            <input id="sub-profile-interval" className="sp-input" type="number" min={1} max={168} value={profile.interval} onChange={e => setProfile({ ...profile, interval: e.target.value })} />
          </Field>
        </div>
        <Field label={t('subSupportUrl', 'Support link')} hint={t('subSupportUrlHint', 'Shown on the subscription page. Must start with http:// or https://. Leave empty to hide.')} inputId="sub-profile-support">
          <input id="sub-profile-support" className="sp-input" type="url" value={profile.support} placeholder="https://t.me/your_support" onChange={e => setProfile({ ...profile, support: e.target.value })} />
        </Field>
        <Field label={t('subAnnounce', 'Announcement')} hint={t('subAnnounceHint', 'Banner shown above the account details. Leave empty to hide.')} inputId="sub-profile-announce">
          <textarea id="sub-profile-announce" className="sp-input" rows={3} maxLength={500} value={profile.announce} onChange={e => setProfile({ ...profile, announce: e.target.value })} />
        </Field>
        <div className="sp-btn-group sp-mt-18">
          <LoadingButton className="btn btn-sm" isLoading={profileSaving} onClick={saveProfile}>
            <FiCheck size={13} /> {t('save', 'Save')}
          </LoadingButton>
        </div>
      </Card>
    </div>
  );
};

export default GeneralSection;
