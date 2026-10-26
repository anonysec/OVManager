// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useToast } from '../context/ToastContext';
import { useLive } from '../context/LiveContext';
import apiClient from '../services/api';
import { asList } from '../utils/apiData';
import { Card, Stat } from './settings/shared';
import { Button } from '../components/ui';
import { FiShield, FiUser, FiLock, FiSettings } from 'react-icons/fi';
import './Admins.css';

const Admins = () => {
  const { t } = useTranslation();
  const { addToast } = useToast();
  const { addToast } = useToast();
  const { subscribe } = useLive();
  const [admins, setAdmins] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const fetchAdmins = useCallback(async () => {
    try {
      const res = await apiClient.get('/admins/');
      if (res.data?.success) {
        setAdmins(asList(res.data, 'admins'));
      } else {
        setLoadError(true);
      }
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAdmins();
    const sub = subscribe('admins.changed', fetchAdmins);
    return () => sub();
  }, [subscribe, fetchAdmins]);

  const soleOwner = admins.find((a: any) => a.is_owner);
  const adminCount = admins.length;

  const changePassword = async () => {
    const newPass = window.prompt(t('enterNewPassword', 'Enter a new password for the owner account:'));
    if (!newPass) return;
    if (newPass.length < 8) {
      addToast(t('passwordTooShort', 'Password must be at least 8 characters.'), 'error');
      return;
    }
    try {
      const res = await apiClient.post(`/admins/${soleOwner?.id}/password`, { password: newPass });
      if (res.data?.success) {
        addToast(t('passwordChanged', 'Owner password changed successfully.'), 'success');
      } else {
        addToast(res.data?.msg || t('changeFailed', 'Could not change password.'), 'error');
      }
    } catch {
      addToast(t('changeFailed', 'Could not change password.'), 'error');
    }
  };

  if (loading) return (
    <div className="admins-page">
      <div className="admins-skeleton" />
    </div>
  );

  if (loadError) return (
    <div className="admins-page">
      <Card title={t('loadError', 'Could not load administrators')} icon={FiShield}>
        <p className="admins-error">{t('loadErrorDetail', 'Try refreshing the page.')}</p>
        <Button type="button" variant="primary" onClick={fetchAdmins}>{t('retry', 'Retry')}</Button>
      </Card>
    </div>
  );

  return (
    <div className="admins-page">
      <header className="admins-header">
        <div className="admins-hero">
          <div className="admins-crown">👑</div>
          <div>
            <h1 className="admins-title">{t('soleAdministrator', 'Sole Administrator')}</h1>
            <p className="admins-subtitle">
              {t('soleAdministratorSub', 'This panel has a single owner account with full control. You are the sole administrator — there are no other admin accounts, and only one can ever exist.')}
            </p>
          </div>
        </div>
        <div className="admins-stats">
          <Stat label={t('totalAdministrators', 'Total administrators')} value={adminCount} tone="info" />
          <Stat label={t('ownerAccount', 'Owner account')} value={soleOwner ? soleOwner.name : '—'} />
        </div>
      </header>

      <Card title={t('ownerAccountCard', 'Owner Account')} icon={FiUser} className="admins-owner-card">
        <div className="admins-owner-profile">
          <div className="admins-owner-avatar">
            <span className="avatar-md" aria-hidden="true">
              {soleOwner?.name?.slice(0, 1).toUpperCase() || '?'}
            </span>
            <span className="sidebar-profile-pulse is-owner" aria-hidden="true" />
            <span className="admins-owner-crown" aria-label={t('soleOwner', 'Sole owner')}>👑</span>
          </div>
          <div className="admins-owner-details">
            <div className="admins-owner-name">{soleOwner?.name || '—'}</div>
            <div className="admins-owner-role">
              <span className="admins-owner-badge">Sole Owner</span>
              <span className="admins-owner-since">
                {t('accountCreated', 'Account created')}: {soleOwner?.created_at ? new Date(soleOwner.created_at).toLocaleDateString() : '—'}
              </span>
            </div>
          </div>
        </div>

        <div className="admins-owner-actions">
          <Button type="button" variant="primary" onClick={changePassword} icon={<FiLock aria-hidden="true" />}>
            {t('changeOwnerPassword', 'Change owner password')}
          </Button>
          <Button type="button" variant="secondary" onClick={() => { window.location.href = '/settings'; }} icon={<FiSettings aria-hidden="true" />}>
            {t('manageAccount', 'Manage account settings')}
          </Button>
        </div>
      </Card>

      <Card title={t('adminSecurityCard', 'Administrator Security')} icon={FiShield} className="admins-security-card">
        <div className="admins-security-list">
          <div className="admins-security-item">
            <div className="admins-security-check" aria-hidden="true">✓</div>
            <div>
              <strong>{t('singlePointOfControl', 'Single point of control')}</strong>
              <p className="admins-security-note">{t('singlePointOfControlNote', 'One owner account controls all panel settings, nodes, users, and billing. Only one administrator can ever exist on this panel.')}</p>
            </div>
          </div>
          <div className="admins-security-item">
            <div className="admins-security-check" aria-hidden="true">✓</div>
            <div>
              <strong>{t('ownerApprovalRequired', 'Owner approval required')}</strong>
              <p className="admins-security-note">{t('ownerApprovalRequiredNote', 'No additional administrator accounts can be created — the owner is the only admin, by design.')}</p>
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
};

export default Admins;
