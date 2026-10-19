import { useState, useRef, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useTheme } from '../context/ThemeContext';
import { loadLanguage, SUPPORTED_LANGS, LANG_LABELS } from '../i18n';
import { LangFlag } from '../components/LangFlag';
import { FiAlertCircle, FiSun, FiMoon, FiMonitor } from 'react-icons/fi';
import apiClient from '../services/api';
import Logo from '../components/Logo';
import { Button, Field } from '../components/ui';
import PasswordInput from '../components/PasswordInput';
import { errorMessageOf } from '../utils/errorMessage';
import './LoginPage.css';

const ClaimPage = () => {
  const [step, setStep] = useState<'verify' | 'create'>('verify');
  const [mode, setMode] = useState<'create' | 'reset'>('create');
  const [setupKey, setSetupKey] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [langOpen, setLangOpen] = useState(false);
  const langRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!langOpen) return;
    const onDoc = (e: MouseEvent) => { if (langRef.current && !langRef.current.contains(e.target as Node)) setLangOpen(false); };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [langOpen]);
  const { theme, cycleTheme } = useTheme() as any;
  const { t, i18n } = useTranslation();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { claim } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const recover = searchParams.get('mode') === 'recover';

  useEffect(() => {
    const token = localStorage.getItem('authToken');
    if (!token) return;
    apiClient.get('/server/settings').then(() => { window.location.replace('/'); }).catch(() => {});
  }, []);
  const clearError = () => { if (error) setError(''); };

  const claimErrorOf = (err: any) =>
    errorMessageOf(err, t('claimError', 'The claim failed. Check the key and try again.'));

  const handleVerify = async (e: any) => {
    e.preventDefault();
    if (loading) return;
    setError('');
    setLoading(true);
    try {
      await apiClient.post('/owner-claim/verify', { claim_key: setupKey.trim() });
      setStep('create');
    } catch (err: any) {
      setError(claimErrorOf(err));
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async (e: any) => {
    e.preventDefault();
    if (loading) return;
    if (mode === 'create' && password !== confirmPassword) {
      setError(t('passwordsDoNotMatch', 'Passwords do not match.'));
      return;
    }
    setError('');
    setLoading(true);
    try {
      await claim(setupKey.trim(), password, mode === 'create' ? username.trim() : '');
      navigate('/');
    } catch (err: any) {
      setError(claimErrorOf(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-topbar">
        <button type="button" className="icon-btn" onClick={cycleTheme} aria-label="Toggle theme" title={theme}>
          {theme === 'light' ? <FiSun aria-hidden="true" /> : theme === 'dark' ? <FiMoon aria-hidden="true" /> : <FiMonitor aria-hidden="true" />}
        </button>
        <div className="lang-picker-wrap" ref={langRef}>
          <button type="button" className={`icon-btn${langOpen ? ' active' : ''}`} onClick={() => setLangOpen((o) => !o)} title={t('language', 'Language')} aria-label={t('changeLanguage', 'Change language')}>
            <LangIcon size={18} />
          </button>
          <div className={`lang-dropdown${langOpen ? ' open' : ''}`}>
            {SUPPORTED_LANGS.map((code) => (
              <button key={code} className={`lang-option${i18n.language === code ? ' active' : ''}`} onClick={() => { void loadLanguage(code); setLangOpen(false); }}>
                <LangFlag code={code} />
                <span>{LANG_LABELS[code]}</span>
                {i18n.language === code && <span className="lang-check">✓</span>}
              </button>
            ))}
          </div>
        </div>
      </div>
      <main className="login-card">
        <header className="login-card-header">
          <span className="login-brand-mark" aria-hidden="true"><Logo size={40} /></span>
          <h1 className="login-brand">
            OV<span>Manager</span>
          </h1>
          <p className="login-card-subtitle">
            {recover
              ? t('claimRecoverHint', 'Each setup key works once. Lost it or already used? Run: sudo ovm auth reset for a fresh key.')
              : t('claimSubtitle', 'Paste the setup key from the installer, then choose the owner account details.')}
          </p>
        </header>

        {error && (
          <div className="login-error" role="alert" aria-live="assertive">
            <FiAlertCircle aria-hidden="true" />
            <span>{error}</span>
          </div>
        )}

        {step === 'verify' ? (
          <form className="login-form" onSubmit={handleVerify}>
            <Field label={t('claimKey', 'Setup key')} hint={t('claimKeyHint', 'Printed at the end of the install; regenerate it with: ovm owner-claim')}>
              <input
                type="text"
                id="claim-key"
                value={setupKey}
                onChange={(e) => { setSetupKey(e.target.value); clearError(); }}
                autoComplete="off"
                spellCheck={false}
                required
                autoFocus
              />
            </Field>

            <Button type="submit" variant="primary" size="lg" block loading={loading}>
              {t('verifyButton', 'Verify')}
            </Button>
          </form>
        ) : (
          <>
            <div className="login-tabs">
              <button type="button" className={`login-tab${mode === 'create' ? ' active' : ''}`} onClick={() => setMode('create')}>{t('claimCreate', 'Create')}</button>
              <button type="button" className={`login-tab${mode === 'reset' ? ' active' : ''}`} onClick={() => setMode('reset')}>{t('claimReset', 'Reset password')}</button>
            </div>
            <form className="login-form" onSubmit={handleCreate}>
              {mode === 'create' && (
                <Field label={t('username')}>
                  <input
                    type="text"
                    id="claim-username"
                    value={username}
                    onChange={(e) => { setUsername(e.target.value); clearError(); }}
                    autoComplete="username"
                    placeholder={t('usernamePlaceholder', 'admin')}
                    required
                    autoFocus
                  />
                </Field>
              )}

              <PasswordInput label={t('claimPassword', 'Owner password')} value={password} onChange={(e: any) => { setPassword(e.target.value); clearError(); }} autoComplete="new-password" placeholder={t('passwordPlaceholder', '••••••••')} minLength={8} required />

              {mode === 'create' && (
                <PasswordInput label={t('confirmPassword', 'Confirm password')} value={confirmPassword} onChange={(e: any) => { setConfirmPassword(e.target.value); clearError(); }} autoComplete="new-password" placeholder={t('passwordPlaceholder', '••••••••')} minLength={8} required />
              )}

              {confirmPassword && password !== confirmPassword && (
                <p className="ui-field-hint" style={{ color: 'var(--danger-text)' }}>{t('passwordsDoNotMatch', 'Passwords do not match.')}</p>
              )}

              <Button type="submit" variant="primary" size="lg" block loading={loading}>
                {mode === 'create' ? t('claimButton', 'Create owner account') : t('resetPassword', 'Reset password')}
              </Button>
            </form>
          </>
        )}
      </main>
    </div>
  );
};

const LangIcon = ({ size = 16 }: { size?: number }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 21a9 9 0 100-18 9 9 0 000 18z" />
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M2 12h20" />
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" />
  </svg>
);

export default ClaimPage;
