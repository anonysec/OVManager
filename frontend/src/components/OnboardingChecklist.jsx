import { useEffect, useState, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { FiCheck, FiArrowRight, FiX, FiServer, FiUserPlus, FiLink, FiDownload, FiChevronRight, FiChevronLeft, FiStar, FiShield, FiZap, FiMonitor, FiWifi, FiKey, FiAward, FiHelpCircle } from 'react-icons/fi';
import apiClient from '../services/api';
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
    key: 'link', 
    icon: FiLink, 
    path: '/users', 
    illustration: 'link',
    title: 'onboardStepLinkTitle',
    desc: 'onboardStepLinkDesc',
    actionLabel: 'onboardStepLinkAction',
    done: (s) => s.users > 0,
    feature: 'link'
  },
  { 
    key: 'config', 
    icon: FiDownload, 
    path: '/users', 
    illustration: 'config',
    title: 'onboardStepConfigTitle',
    desc: 'onboardStepConfigDesc',
    actionLabel: 'onboardStepConfigAction',
    done: (s) => s.users > 0 && s.nodes > 0,
    feature: 'config'
  },
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
  link: (
    <svg viewBox="0 0 120 120" className="onboard-illustration" aria-hidden="true">
      <defs>
        <linearGradient id="linkGrad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#14b8a6" stopOpacity="0.3"/>
          <stop offset="100%" stopColor="#3b82f6" stopOpacity="0.1"/>
        </linearGradient>
      </defs>
      <circle cx="60" cy="60" r="50" fill="url(#linkGrad)" stroke="#14b8a6" strokeWidth="2" strokeDasharray="8 4" className="pulse-ring"/>
      <path d="M35 60 Q45 40 60 40 Q75 40 85 60" stroke="#14b8a6" strokeWidth="3" fill="none" strokeLinecap="round" className="arc-link"/>
      <path d="M35 60 Q45 80 60 80 Q75 80 85 60" stroke="#3b82f6" strokeWidth="3" fill="none" strokeLinecap="round" className="arc-link reverse"/>
      <circle cx="60" cy="60" r="8" fill="#14b8a6" opacity="0.3" className="pulse-center"/>
      <circle cx="60" cy="60" r="4" fill="#22c55e" className="status-dot"/>
    </svg>
  ),
  config: (
    <svg viewBox="0 0 120 120" className="onboard-illustration" aria-hidden="true">
      <defs>
        <linearGradient id="configGrad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#f59e0b" stopOpacity="0.3"/>
          <stop offset="100%" stopColor="#ef4444" stopOpacity="0.1"/>
        </linearGradient>
      </defs>
      <circle cx="60" cy="60" r="50" fill="url(#configGrad)" stroke="#f59e0b" strokeWidth="2" strokeDasharray="8 4" className="pulse-ring"/>
      <rect x="30" y="35" width="60" height="50" rx="6" fill="#f59e0b" opacity="0.2" stroke="#f59e0b" strokeWidth="2"/>
      <line x1="45" y1="50" x2="75" y2="50" stroke="#f59e0b" strokeWidth="2" strokeLinecap="round"/>
      <line x1="45" y1="62" x2="75" y2="62" stroke="#f59e0b" strokeWidth="2" strokeLinecap="round"/>
      <line x1="45" y1="74" x2="65" y2="74" stroke="#f59e0b" strokeWidth="2" strokeLinecap="round"/>
      <circle cx="82" cy="42" r="6" fill="#22c55e" className="status-dot"/>
    </svg>
  ),
};

const OnboardingChecklist = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { refreshTick } = useLive();
  const [state, setState] = useState({ nodes: 0, users: 0 });
  const [dismissed, setDismissed] = useState(() => localStorage.getItem('ovmanager-onboard-dismissed') === '1');
  const [currentStep, setCurrentStep] = useState(0);
  const [celebrate, setCelebrate] = useState(false);
  const [showCoaching, setShowCoaching] = useState(false);
  const containerRef = useRef(null);

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

  // Auto-advance to first incomplete step
  useEffect(() => {
    const firstIncomplete = STEPS.findIndex((s) => !s.done(state));
    if (firstIncomplete !== -1 && firstIncomplete !== currentStep) {
      setCurrentStep(firstIncomplete);
    }
  }, [state, doneCount]);

  // Celebration trigger
  useEffect(() => {
    if (allDone && !dismissed) {
      setCelebrate(true);
      setTimeout(() => setCelebrate(false), 3000);
    }
  }, [allDone, dismissed]);

  if (dismissed || allDone) return null;

  const dismiss = () => {
    localStorage.setItem('ovmanager-onboard-dismissed', '1');
    setDismissed(true);
  };

  const nextStep = () => {
    if (currentStep < STEPS.length - 1) setCurrentStep(c => c + 1);
  };
  const prevStep = () => {
    if (currentStep > 0) setCurrentStep(c => c - 1);
  };

  const current = STEPS[currentStep];
  const isCurrentDone = current.done(state);

  return (
    <>
      {/* Main onboarding panel */}
      <aside 
        ref={containerRef}
        className="onboarding-panel" 
        role="complementary" 
        aria-label={t('onboardTitle', 'Getting started')}
      >
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
            <span className="progress-label">{t('onboardProgress', '{done}/{total} steps done', { done: doneCount, total: STEPS.length })}</span>
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
                      ) : index === currentStep ? (
                        <button 
                          type="button" 
                          className="step-btn primary"
                          onClick={() => navigate(step.path)}
                        >
                          {t(step.actionLabel)}
                          <FiArrowRight />
                        </button>
                      ) : (
                        <button 
                          type="button" 
                          className="step-btn ghost"
                          onClick={() => { setCurrentStep(index); navigate(step.path); }}
                        >
                          {t(step.actionLabel)}
                        </button>
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

      {/* Celebration confetti */}
      {celebrate && (
        <div className="celebration-overlay" aria-hidden="true">
          <FiAward className="confetti-burst" />
          <div className="celebration-text">
            <FiAward className="award-icon" />
            <h3>{t('onboardCelebrateTitle', 'All set! 🎉')}</h3>
            <p>{t('onboardCelebrateDesc', 'Your VPN is ready to go.')}</p>
          </div>
        </div>
      )}

      {/* Coaching marks for first-time features */}
      {showCoaching && (
        <div className="coaching-overlay" onClick={() => setShowCoaching(false)} aria-hidden="true">
          <div className="coaching-spotlight" style={{ '--spotlight-left': 'var(--coach-left)', '--spotlight-top': 'var(--coach-top)', '--spotlight-width': 'var(--coach-width)', '--spotlight-height': 'var(--coach-height)' }} />
          <div className="coaching-tooltip" style={{ '--tooltip-left': 'var(--tip-left)', '--tooltip-top': 'var(--tip-top)' }}>
            <FiStar />
            <p>{t('onboardCoachTip', 'Click here to get started')}</p>
            <button onClick={() => setShowCoaching(false)}>{t('onboardGotIt', 'Got it')}</button>
          </div>
        </div>
      )}
    </>
  );
};

export default OnboardingChecklist;