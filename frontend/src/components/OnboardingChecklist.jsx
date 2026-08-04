import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { FiCheck, FiArrowRight, FiX, FiServer, FiUserPlus, FiLink, FiDownload } from 'react-icons/fi';
import apiClient from '../services/api';
import { useLive } from '../context/LiveContext';

const STEPS = [
  { key: 'node', icon: FiServer, path: '/nodes', done: (s) => s.nodes > 0 },
  { key: 'user', icon: FiUserPlus, path: '/users', done: (s) => s.users > 0 },
  { key: 'link', icon: FiLink, path: '/users', done: (s) => s.users > 0 },
  { key: 'config', icon: FiDownload, path: '/users', done: (s) => s.users > 0 && s.nodes > 0 },
];

const OnboardingChecklist = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { refreshTick } = useLive();
  const [state, setState] = useState({ nodes: 0, users: 0 });
  const [dismissed, setDismissed] = useState(() => localStorage.getItem('ovmanager-onboard-dismissed') === '1');

  const load = useCallback(async () => {
    try {
      const [nodesRes, usersRes] = await Promise.all([
        apiClient.get('/nodes/'),
        apiClient.get('/users/'),
      ]);
      setState({
        nodes: (nodesRes.data?.data || []).length,
        users: (usersRes.data?.data || []).length,
      });
    } catch { /* keep last known state */ }
  }, []);

  useEffect(() => { load(); }, [load, refreshTick]);

  const doneCount = STEPS.filter((s) => s.done(state)).length;
  const allDone = doneCount === STEPS.length;
  const pct = Math.round((doneCount / STEPS.length) * 100);

  if (dismissed || allDone) return null;

  const dismiss = () => {
    localStorage.setItem('ovmanager-onboard-dismissed', '1');
    setDismissed(true);
  };

  return (
    <aside className="onboarding-card" role="complementary" aria-label={t('onboardTitle', 'Getting started')}>
      <button type="button" className="onboarding-close" onClick={dismiss} aria-label={t('onboardDismiss', 'Dismiss setup guide')}><FiX /></button>
      <h3>{t('onboardTitle', 'Getting started')}</h3>
      <p className="onboarding-sub">{t('onboardSub', 'A few quick steps to bring your VPN online.')}</p>

      <div className="onboarding-progress" role="progressbar" aria-valuenow={doneCount} aria-valuemin={0} aria-valuemax={STEPS.length}>
        <div className="onboarding-progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="onboarding-progress-label">{doneCount}/{STEPS.length} {t('onboardDone', 'done')}</span>

      <ol className="onboarding-steps">
        {STEPS.map((step) => {
          const Icon = step.icon;
          const done = step.done(state);
          return (
            <li key={step.key} className={done ? 'is-done' : 'is-next'}>
              <span className="onboarding-step-icon" aria-hidden="true">
                {done ? <FiCheck /> : <Icon />}
              </span>
              <span className="onboarding-step-label">{t(`onboardStep${step.key}`, step.key)}</span>
              {done ? (
                <span className="onboarding-step-check" aria-label={t('onboardComplete', 'Complete')}><FiCheck /></span>
              ) : (
                <button type="button" className="onboarding-step-go" onClick={() => navigate(step.path)} aria-label={t('onboardGo', 'Go to step')}>
                  <FiArrowRight />
                </button>
              )}
            </li>
          );
        })}
      </ol>
    </aside>
  );
};

export default OnboardingChecklist;
