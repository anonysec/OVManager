// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useToast } from '../../context/ToastContext';
import apiClient from '../../services/api';
import LoadingButton from '../../components/LoadingButton';
import PanelSkeleton from '../../components/ui/PanelSkeleton';
import ErrorState from '../../components/ui/ErrorState';
import { FiLink, FiEdit2, FiCheck, FiX, FiCopy, FiExternalLink } from 'react-icons/fi';
import { Card } from './shared';
import useInlineEditFocus from './useInlineEditFocus';

/* ═══════════════════════════════════════════════════════
   GENERAL (advanced) — Panel URL path + subscription prefix
═══════════════════════════════════════════════════════ */
const GeneralSection = () => {
  const { t } = useTranslation();
  const { addToast } = useToast();
  const [urlPath, setUrlPath] = useState('');
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState('');
  const [confirmSaved, setConfirmSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [subPrefix, setSubPrefix] = useState('');
  const [subPrefixEditing, setSubPrefixEditing] = useState(false);
  const [subPrefixValue, setSubPrefixValue] = useState('');
  const [subPrefixSaving, setSubPrefixSaving] = useState(false);
  const urlInputRef = useRef(null);
  const urlTriggerRef = useRef(null);
  const subInputRef = useRef(null);
  const subTriggerRef = useRef(null);
  useInlineEditFocus(editing, urlInputRef, urlTriggerRef);
  useInlineEditFocus(subPrefixEditing, subInputRef, subTriggerRef);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setLoadError(false);
      const res = await apiClient.get('/server/settings');
      const s = res.data?.data || {};
      setUrlPath(s.urlpath || '');
      setSubPrefix(s.subscription_url_prefix || '');
    } catch { setLoadError(true); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const saveUrlPath = async () => {
    setSaving(true); setError('');
    try {
      const v = editValue.trim().replace(/^\/+|\/+$/g, '');
      if (v && !/^[A-Za-z0-9_-]+$/.test(v)) { setError(t('urlInvalid', 'Only letters, numbers, dashes and underscores.')); return; }
      if (v.length > 64) { setError(t('urlInvalid', 'Max 64 characters.')); return; }
      const res = await apiClient.put('/server/settings/urlpath', { urlpath: v });
      setUrlPath(v); setEditing(false);
      addToast(t('saved', 'Saved.'), 'success');
      // The panel moves to the new prefix — the old URL stops serving the app
      // (URLPathMiddleware hides non-matching paths), so redirect there now.
      const newBase = v ? `/${v}` : '';
      setTimeout(() => { window.location.assign(`${window.location.origin}${newBase}/settings`); }, 600);
      void res;
    } catch (e) { setError(e.response?.data?.msg || t('error', 'Error')); }
    finally { setSaving(false); }
  };

  const saveSubPrefix = async () => {
    setSubPrefixSaving(true);
    try {
      await apiClient.put('/server/settings/subscription', { subscription_url_prefix: subPrefixValue.trim() });
      setSubPrefix(subPrefixValue.trim()); setSubPrefixEditing(false);
      addToast(t('saved', 'Saved.'), 'success');
    } catch (e) { addToast(e.response?.data?.msg || t('error', 'Error'), 'error'); }
    finally { setSubPrefixSaving(false); }
  };

  const panelUrl = urlPath ? `${window.location.origin}/${urlPath}/` : `${window.location.origin}/`;

  // Anti-lockout: while editing, show where the panel WILL live and require
  // an explicit acknowledgment that the operator saved the new URL. A typo
  // here otherwise means mystery until --reset-urlpath saves the day.
  const editValueClean = editValue.trim().replace(/^\/+|\/+$/g, '');
  const pathChanged = editValueClean !== urlPath;
  const newPanelUrl = editValueClean ? `${window.location.origin}/${editValueClean}/` : `${window.location.origin}/`;

  if (loading) return <PanelSkeleton lines={4} label="Loading…" />;
  if (loadError) return <ErrorState title={t('settingsLoadError', 'Failed to load settings')} message={t('settingsLoadErrorDetail', 'Could not reach the server.')} onRetry={load} retryLabel={t('retry', 'Retry')} />;

  return (
    <div className="sp-cards">
      {/* Panel URL */}
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

      {/* Subscription URL prefix */}
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
    </div>
  );
};

export default GeneralSection;
