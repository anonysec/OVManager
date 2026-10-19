import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useTheme } from '../context/ThemeContext';
import { loadLanguage, SUPPORTED_LANGS, LANG_LABELS } from '../i18n';
import { FiAlertCircle, FiEye, FiEyeOff } from 'react-icons/fi';
import apiClient from '../services/api';
import Logo from '../components/Logo';
import { Button, Field } from '../components/ui';
import './LoginPage.css';

const LoginPage = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const { theme, cycleTheme } = useTheme() as any;
  const { i18n } = useTranslation();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();
  const { t } = useTranslation();

  // Fallback: AuthContext already probed /owner-claim at mount and the router
  // only shows this page when the answer was "not claimable". This re-check
  // stays for the case where that probe failed while the backend was still
  // starting. Any failure just leaves the login form alone.
  useEffect(() => {
    let alive = true;
    apiClient.get('/owner-claim')
      .then((res) => { if (alive && res.data?.claimable) navigate('/setup', { replace: true }); })
      .catch(() => { /* stay on login */ });
    return () => { alive = false; };
  }, [navigate]);

  const clearError = () => { if (error) setError(''); };

  const handleSubmit = async (e: any) => {
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

  return (
    <div className="login-page">
      <div className="login-topbar">
      <button type="button" className="icon-btn" onClick={cycleTheme} aria-label="Toggle theme">{theme}</button>
      <select className="ui-input" value={i18n.language} onChange={(e) => void loadLanguage(e.target.value)} aria-label="Language">
        {SUPPORTED_LANGS.map((l) => <option key={l} value={l}>{LANG_LABELS[l]}</option>)}
      </select>
    </div>
    <main className="login-card">
        <header className="login-card-header">
          <span className="login-brand-mark" aria-hidden="true"><Logo size={40} /></span>
          <h1 className="login-brand">
            OV<span>Manager</span>
          </h1>
          <p className="login-card-subtitle">
            {t('loginSubtitle', 'Sign in to manage your VPN fleet.')}
          </p>
        </header>

        {error && (
          <div className="login-error" role="alert" aria-live="assertive">
            <FiAlertCircle aria-hidden="true" />
            <span>{error}</span>
          </div>
        )}

        <form className="login-form" onSubmit={handleSubmit}>
          <Field label={t('username')}>
            <input
              type="text"
              id="username"
              value={username}
              onChange={(e) => { setUsername(e.target.value); clearError(); }}
              autoComplete="username"
              placeholder={t('usernamePlaceholder', 'admin')}
              required
              autoFocus
            />
          </Field>

          <div className="ui-field">
            <label className="ui-field-label" htmlFor="password">{t('password')}</label>
            <div className="ui-field-control login-password-wrap">
              <input
                type={showPassword ? 'text' : 'password'}
                id="password"
                className="ui-input login-password-input"
                value={password}
                onChange={(e) => { setPassword(e.target.value); clearError(); }}
                autoComplete="current-password"
                placeholder={t('passwordPlaceholder', '••••••••')}
                required
              />
              <button
                type="button"
                className="login-password-toggle"
                tabIndex={-1}
                onClick={() => setShowPassword((visible) => !visible)}
                aria-label={showPassword ? t('hidePassword', 'Hide password') : t('showPassword', 'Show password')}
                title={showPassword ? t('hidePassword', 'Hide password') : t('showPassword', 'Show password')}
              >
                {showPassword ? <FiEyeOff aria-hidden="true" /> : <FiEye aria-hidden="true" />}
              </button>
            </div>
          </div>

          <Button type="submit" variant="primary" size="lg" block loading={loading}>
            {t('loginButton', 'Login')}
          </Button>
        </form>

        <p className="login-claim-hint">
          <button
            type="button"
            className="login-claim-link"
            onClick={() => navigate('/setup?mode=recover')}
          >
            {t('forgotPassword', 'Forgot password?')}
          </button>
        </p>
      </main>
    </div>
  );
};

export default LoginPage;
