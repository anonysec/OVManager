import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { FiCheck, FiX, FiServer, FiUserPlus, FiDownload, FiWifi, FiChevronRight, FiChevronLeft, FiStar, FiShield, FiHelpCircle } from 'react-icons/fi';
import apiClient from '../services/api';
import { asList } from '../utils/apiData';
import { settle } from '../hooks/useAsyncData';
import { useLive } from '../context/LiveContext';
import './OnboardingChecklist.css';

const STEPS = [
  { 
    key: 'node', 
    icon: FiServer, 
    path: '/nodes', 
    illustration: 'node',
    title: 'onboardStepNodeTitle',
    desc: 'onboardStepNodeDesc',
    actionLabel: 'onboardStepNodeAction',
    done: (s) => s.nodes > 0,
    feature: 'nodes'
  },
  { 
    key: 'user', 
    icon: FiUserPlus, 
    path: '/users', 
    illustration: 'user',
    title: 'onboardStepUserTitle',
    desc: 'onboardStepUserDesc',
    actionLabel: 'onboardStepUserAction',
    done: (s) => s.users > 0,
    feature: 'users'
  },
  {
    key: 'download',
    icon: FiDownload,
    path: '/users',
    illustration: 'download',
    title: 'onboardStepDownloadTitle',
    desc: 'onboardStepDownloadDesc',
    actionLabel: 'onboardStepDownloadAction',
    markLabel: 'onboardStepDownloadMark',
    manual: true,
    flag: 'downloaded',
    done: (s) => s.downloaded,
    feature: 'users'
  },
  {
    key: 'connect',
    icon: FiWifi,
    path: null,
    illustration: 'connect',
    title: 'onboardStepConnectTitle',
    desc: 'onboardStepConnectDesc',
    actionLabel: 'onboardStepConnectAction',
    manual: true,
    flag: 'connected',
    done: (s) => s.connected,
    feature: 'users'
  }
];

const ILLUSTRATIONS = {
  node: (
    <svg viewBox="0 0 120 120" className="onboard-illustration" aria-hidden="true">
      <defs>
        <linearGradient id="nodeGrad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.3"/>
          <stop offset="100%" stopColor="#06b6d4" stopOpacity="0.1"/>
        </linearGradient>
      </defs>
      <circle cx="60" cy="60" r="50" fill="url(#nodeGrad)" stroke="#3b82f6" strokeWidth="2" strokeDasharray="8 4" className="pulse-ring"/>
      <g className="server-stack">
        <rect x="40" y="30" width="40" height="14" rx="3" fill="#3b82f6" opacity="0.8"/>
        <rect x="40" y="48" width="40" height="14" rx="3" fill="#06b6d4" opacity="0.8"/>
        <rect x="40" y="66" width="40" height="14" rx="3" fill="#3b82f6" opacity="0.6"/>
      </g>
      <circle cx="60" cy="90" r="4" fill="#22c55e" className="status-dot"/>
    </svg>
  ),
  user: (
    <svg viewBox="0 0 120 120" className="onboard-illustration" aria-hidden="true">
      <defs>
        <linearGradient id="userGrad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#8b5cf6" stopOpacity="0.3"/>
          <stop offset="100%" stopColor="#ec4899" stopOpacity="0.1"/>
        </linearGradient>
      </defs>
      <circle cx="60" cy="60" r="50" fill="url(#userGrad)" stroke="#8b5cf6" strokeWidth="2" strokeDasharray="8 4" className="pulse-ring"/>
      <circle cx="60" cy="40" r="18" fill="#8b5cf6" opacity="0.8"/>
      <ellipse cx="60" cy="95" rx="28" ry="18" fill="#ec4899" opacity="0.6"/>
      <circle cx="60" cy="40" r="6" fill="#fde047" className="status-dot"/>
    </svg>
  ),
  download: (
    <svg viewBox="0 0 120 120" className="onboard-illustration" aria-hidden="true">
      <defs>
        <linearGradient id="dlGrad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#22c55e" stopOpacity="0.3"/>
          <stop offset="100%" stopColor="#06b6d4" stopOpacity="0.1"/>
        </linearGradient>
      </defs>
      <circle cx="60" cy="60" r="50" fill="url(#dlGrad)" stroke="#22c55e" strokeWidth="2" strokeDasharray="8 4" className="pulse-ring"/>
      <path d="M60 30 v36 m0 0 l-14 -14 m14 14 l14 -14" stroke="#22c55e" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
      <path d="M36 78 h48 v12 h-48 z" fill="#06b6d4" opacity="0.8"/>
    </svg>
  ),
  connect: (
    <svg viewBox="0 0 120 120" className="onboard-illustration" aria-hidden="true">
      <defs>
        <linearGradient id="connGrad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#f59e0b" stopOpacity="0.3"/>
          <stop offset="100%" stopColor="#22c55e" stopOpacity="0.1"/>
        </linearGradient>
      </defs>
      <circle cx="60" cy="60" r="50" fill="url(#connGrad)" stroke="#f59e0b" strokeWidth="2" strokeDasharray="8 4" className="pulse-ring"/>
      <path d="M66 28 L42 66 h16 L54 92 L78 54 h-16 z" fill="#22c55e" opacity="0.9"/>
    </svg>
  ),
};

const OnboardingChecklist = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { refreshTick } = useLive();
  const [state, setState] = useState(() => ({
    nodes: 0,
    users: 0,
    downloaded: localStorage.getItem('ovmanager-onboard-downloaded') === '1',
    connected: localStorage.getItem('ovmanager-onboard-connected') === '1',
  }));
  const [dismissed, setDismissed] = useState(() => localStorage.getItem('ovmanager-onboard-dismissed') === '1');
  const [currentStep, setCurrentStep] = useState(0);

  const load = useCallback(async () => {
    try {
      // Independent counts: a failing /users/ shouldn't reset the node step
      // back to "not done" and re-open a checklist the user already finished.
      const res = await settle({
        nodes: apiClient.get('/nodes/'),
        users: apiClient.get('/users/'),
      });
      const nodeList = asList(res.nodes.ok ? res.nodes.data : null, 'nodes');
      const userList = asList(res.users.ok ? res.users.data : null, 'users');
      setState((prev) => ({
        nodes: res.nodes.ok ? nodeList.length : prev.nodes,
        users: res.users.ok ? userList.length : prev.users,
      }));
    } catch { /* keep last known state */ }
  }, []);

  useEffect(() => { load(); }, [load, refreshTick]);

  const doneCount = STEPS.filter((s) => s.done(state)).length;
  const allDone = doneCount === STEPS.length;
  const pct = Math.round((doneCount / STEPS.length) * 100);

  // Auto-advance to first incomplete step
  useEffect(() => {
    const firstIncomplete = STEPS.findIndex((s) => !s.done(state));
    if (firstIncomplete !== -1 && firstIncomplete !== currentStep) {
      setCurrentStep(firstIncomplete);
    }
  }, [state, doneCount, currentStep]);

  if (dismissed || allDone) return null;

  const dismiss = () => {
    localStorage.setItem('ovmanager-onboard-dismissed', '1');
    setDismissed(true);
  };

  const markStep = (flag) => {
    localStorage.setItem(`ovmanager-onboard-${flag}`, '1');
    setState((prev) => ({ ...prev, [flag]: true }));
  };

  const nextStep = () => {
    if (currentStep < STEPS.length - 1) setCurrentStep(c => c + 1);
  };
  const prevStep = () => {
    if (currentStep > 0) setCurrentStep(c => c - 1);
  };

  return (
    <div className="onboarding-modal" role="dialog" aria-modal="true" aria-label={t('onboardTitle', 'Getting started')}>
      <aside className="onboarding-panel">
        <div className="onboarding-header">
          <div className="onboarding-brand">
            <FiShield className="brand-icon" />
            <span className="brand-text">{t('onboardTitle', 'Welcome to OVManager')}</span>
          </div>
          <button
            type="button"
            className="onboarding-close"
            onClick={dismiss}
            aria-label={t('onboardDismiss', 'Dismiss setup guide')}
          >
            <FiX />
          </button>
        </div>

        {/* Progress ring */}
        <div className="onboarding-progress-ring" role="progressbar" aria-valuenow={doneCount} aria-valuemin={0} aria-valuemax={STEPS.length}>
          <svg width="120" height="120" className="progress-svg">
            <circle
              className="progress-bg"
              cx="60" cy="60" r="52"
              fill="none" stroke="var(--border-color)" strokeWidth="8"
            />
            <circle
              className="progress-fill"
              cx="60" cy="60" r="52"
              fill="none" stroke="var(--accent-color)" strokeWidth="8"
              strokeDasharray={`${(Math.PI * 104 * pct) / 100} ${Math.PI * 104}`}
              strokeLinecap="round"
              style={{ transform: 'rotate(-90deg)', transformOrigin: '60px 60px' }}
            />
          </svg>
          <div className="progress-center">
            <span className="progress-pct">{pct}%</span>
            <span className="progress-label">{t('onboardProgress', '{{done}}/{{total}} steps complete', { done: doneCount, total: STEPS.length })}</span>
          </div>
        </div>

        {/* Step carousel */}
        <div className="onboarding-carousel">
          <button
            type="button"
            className={`carousel-nav prev ${currentStep === 0 ? 'hidden' : ''}`}
            onClick={prevStep}
            aria-label={t('onboardPrev', 'Previous step')}
          >
            <FiChevronLeft />
          </button>

          <div className="carousel-viewport">
            <div className="carousel-track" style={{ transform: `translateX(-${currentStep * 100}%)` }}>
              {STEPS.map((step, index) => (
                <div key={step.key} className="carousel-slide" data-step={index}>
                  {/* Illustration */}
                  <div className={`step-illustration ${step.done(state) ? 'completed' : ''} ${index === currentStep ? 'active' : ''}`}>
                    {ILLUSTRATIONS[step.illustration]}
                    {step.done(state) && (
                      <FiCheck className="completion-badge" />
                    )}
                    {!step.done(state) && index === currentStep && (
                      <FiStar className="active-sparkle" />
                    )}
                  </div>

                  {/* Step content */}
                  <div className="step-content">
                    <h3 className="step-title">{t(step.title)}</h3>
                    <p className="step-desc">{t(step.desc)}</p>

                    {/* Feature preview / coaching */}
                    <div className="step-preview">
                      <FiHelpCircle className="preview-icon" />
                      <span>{t(`onboardStep${step.key}Preview`, 'Click to explore this feature')}</span>
                    </div>

                    {/* Action */}
                    <div className="step-actions">
                      {step.done(state) ? (
                        <button
                          type="button"
                          className="step-btn completed"
                          disabled
                        >
                          <FiCheck /> {t('onboardComplete', 'Done')}
                        </button>
                      ) : step.manual && !step.path ? (
                        <button
                          type="button"
                          className="step-btn primary"
                          onClick={() => markStep(step.flag)}
                        >
                          <FiCheck /> {t(step.actionLabel)}
                        </button>
                      ) : (
                        <>
                          <button
                            type="button"
                            className="step-btn primary"
                            onClick={() => navigate(step.path)}
                          >
                            {t(step.actionLabel)}
                            <FiChevronRight />
                          </button>
                          {step.manual && (
                            <button
                              type="button"
                              className="step-btn ghost"
                              onClick={() => markStep(step.flag)}
                            >
                              <FiCheck /> {t(step.markLabel || 'onboardStepMarkDone', 'I did this')}
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <button
            type="button"
            className={`carousel-nav next ${currentStep === STEPS.length - 1 ? 'hidden' : ''}`}
            onClick={nextStep}
            aria-label={t('onboardNext', 'Next step')}
          >
            <FiChevronRight />
          </button>
        </div>

        {/* Step indicators */}
        <div className="step-indicators" role="tablist" aria-label="Setup steps">
          {STEPS.map((step, index) => (
            <button
              key={step.key}
              type="button"
              role="tab"
              aria-selected={index === currentStep}
              aria-label={t(step.title)}
              className={`step-indicator ${index === currentStep ? 'active' : ''} ${step.done(state) ? 'done' : ''}`}
              onClick={() => { setCurrentStep(index); navigate(step.path); }}
            >
              <span className="indicator-dot">
                {step.done(state) && <FiCheck size={10} />}
              </span>
              <span className="indicator-label">{t(step.title)}</span>
            </button>
          ))}
        </div>

        <button
          type="button"
          className="onboarding-dismiss-link"
          onClick={dismiss}
        >
          {t('onboardSkip', 'Skip for now')}
        </button>
      </aside>
    </div>
  );
};

export default OnboardingChecklist;