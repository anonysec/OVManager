import { useState, useRef, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useTheme } from '../context/ThemeContext';
import { loadLanguage, SUPPORTED_LANGS, LANG_LABELS } from '../i18n';
import { LangFlag } from '../components/LangFlag';
import { FiAlertCircle, FiSun, FiMoon, FiMonitor } from 'react-icons/fi';
import apiClient from '../services/api';
import { errorMessageOf } from '../utils/errorMessage';
import Logo from '../components/Logo';
import { Button, Field } from '../components/ui';
import PasswordInput from '../components/PasswordInput';
import '../components/TopBar.css';
import './AuthPage.css';

const AuthPage = () => {
  const [view, setView] = useState<'login' | 'setup'>('login');
  const [step, setStep] = useState<'verify' | 'create'>('verify');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [setupKey, setSetupKey] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [langOpen, setLangOpen] = useState(false);
  const langRef = useRef<HTMLDivElement>(null);

  const { theme, cycleTheme } = useTheme() as any;
  const { t, i18n } = useTranslation();
  const { login, claim, claimable, recoverable } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (!langOpen) return;
    const onDoc = (e: MouseEvent) => { if (langRef.current && !langRef.current.contains(e.target as Node)) setLangOpen(false); };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [langOpen]);

  useEffect(() => {
    let alive = true;
    apiClient.get('/owner-claim')
      .then((res) => { if (alive && res.data?.claimable) setView('setup'); })
      .catch(() => { /* stay on login */ });
    return () => { alive = false; };
  }, []);

  const clearError = () => { if (error) setError(''); };

  const handleLogin = async (e: any) => {
    e.preventDefault();
    if (loading) return;
    setError('');
    setLoading(true);
    try {
      await login(username, password);
      navigate('/');
    } catch {
      setError(t('loginError', 'Incorrect username or password.'));
    } finally {
      setLoading(false);
    }
  };

  const handleVerify = async (e: any) => {
    e.preventDefault();
    if (loading) return;
    setError('');
    setLoading(true);
    try {
      await apiClient.post('/owner-claim/verify', { claim_key: setupKey.trim() });
      setStep('create');
    } catch (err: any) {
      setError(errorMessageOf(err, t('claimError', 'The claim failed. Check the key and try again.')));
    } finally {
      setLoading(false);
    }
  };

  const handleClaim = async (e: any) => {
    e.preventDefault();
    if (loading) return;
    if (password !== confirmPassword) {
      setError(t('passwordsDoNotMatch', 'Passwords do not match.'));
      return;
    }
    setError('');
    setLoading(true);
    try {
      await claim(setupKey.trim(), password, username.trim());
      navigate('/');
    } catch (err: any) {
      setError(errorMessageOf(err, t('claimError', 'The claim failed. Check the key and try again.')));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-topbar">
        <button type="button" className="icon-btn" onClick={cycleTheme} aria-label={t('toggleTheme', 'Toggle theme')} title={theme}>
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
          <span className="login-brand-mark" aria-hidden="true"><Logo size={64} /></span>
          <h1 className="login-brand">OV<span>Manager</span></h1>
          <p className="login-card-subtitle">
            {view === 'login' ? t('loginSubtitle', 'Sign in to manage your VPN fleet.') : t('claimSubtitle', 'Paste the setup key from the installer, then choose the owner account details.')}
          </p>
        </header>

        {error && (
          <div className="login-error" role="alert" aria-live="assertive">
            <FiAlertCircle aria-hidden="true" />
            <span>{error}</span>
          </div>
        )}

        {view === 'login' ? (
          <form className="login-form" onSubmit={handleLogin}>
            <Field label={t('username')}>
              <input type="text" value={username} onChange={(e) => { setUsername(e.target.value); clearError(); }} autoComplete="username" placeholder={t('usernamePlaceholder', 'admin')} required autoFocus />
            </Field>
            <PasswordInput label={t('password')} value={password} onChange={(e: any) => { setPassword(e.target.value); clearError(); }} autoComplete="current-password" placeholder={t('passwordPlaceholder', '••••••••')} required />
            <Button type="submit" variant="primary" size="lg" block loading={loading}>{t('loginButton', 'Login')}</Button>
            {(claimable || recoverable) && <button type="button" className="login-claim-link" onClick={() => setView('setup')}>{t('ownerAccess', 'Owner access')}</button>}
          </form>
        ) : step === 'verify' ? (
          <form className="login-form" onSubmit={handleVerify}>
            <Field label={t('claimKey', 'Setup key')} hint={t('claimKeyHint', 'Printed at the end of the install; regenerate it with: ovm owner-claim')}>
              <input type="text" value={setupKey} onChange={(e) => { setSetupKey(e.target.value); clearError(); }} autoComplete="off" spellCheck={false} required autoFocus />
            </Field>
            <Button type="submit" variant="primary" size="lg" block loading={loading}>{t('verifyButton', 'Verify')}</Button>
            <button type="button" className="login-claim-link" onClick={() => setView('login')}>{t('backToLogin', 'Back to login')}</button>
          </form>
        ) : (
          <form className="login-form" onSubmit={handleClaim}>
            <Field label={t('username')}>
              <input type="text" value={username} onChange={(e) => { setUsername(e.target.value); clearError(); }} autoComplete="username" placeholder={t('usernamePlaceholder', 'admin')} required autoFocus />
            </Field>
            <PasswordInput label={t('claimPassword', 'Owner password')} value={password} onChange={(e: any) => { setPassword(e.target.value); clearError(); }} autoComplete="new-password" placeholder={t('passwordPlaceholder', '••••••••')} minLength={8} required />
            <PasswordInput label={t('confirmPassword', 'Confirm password')} value={confirmPassword} onChange={(e: any) => { setConfirmPassword(e.target.value); clearError(); }} autoComplete="new-password" placeholder={t('passwordPlaceholder', '••••••••')} minLength={8} required />
            {confirmPassword && password !== confirmPassword && (
              <p className="ui-field-hint" style={{ color: 'var(--danger-text)' }}>{t('passwordsDoNotMatch', 'Passwords do not match.')}</p>
            )}
            <Button type="submit" variant="primary" size="lg" block loading={loading}>{t('claimButton', 'Create owner account')}</Button>
            <button type="button" className="login-claim-link" onClick={() => { setStep('verify'); setView('login'); }}>{t('backToLogin', 'Back to login')}</button>
          </form>
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

export default AuthPage;
