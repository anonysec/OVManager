import { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { FiActivity, FiEye, FiEyeOff, FiLock, FiServer, FiShield } from 'react-icons/fi';
import logoSrc from '../assets/ovmanager-character.webp';
import Logo from '../components/Logo';

const LoginPage = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();
  const { t } = useTranslation();

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (loading) return;
    setError('');
    setLoading(true);
    try {
      await login(username, password);
      navigate('/');
    } catch {
      setError(t('loginError'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div id="login-container">
      <div className="login-shell">
        <section className="login-showcase" aria-label="OVManager overview">
          <div className="login-showcase-brand">
            <Logo size={38} />
            <span>OV<span>Manager</span></span>
          </div>
          <div className="login-showcase-copy">
            <span className="login-showcase-kicker"><FiActivity aria-hidden="true" /> OVNode Fleet Control</span>
            <h1>One calm view of your VPN fleet.</h1>
            <p>Monitor nodes, manage access, and resolve connection issues before they become incidents.</p>
          </div>
          <div className="login-showcase-status">
            <div className="login-status-orbit" aria-hidden="true">
              <img src={logoSrc} alt="" />
              <span className="orbit-dot orbit-dot-one" />
              <span className="orbit-dot orbit-dot-two" />
            </div>
            <div className="login-status-copy">
              <span className="status-kicker"><i /> Built for operators</span>
              <strong>Secure access to the control room</strong>
              <span>Everything you need to keep OpenVPN users online.</span>
            </div>
          </div>
          <div className="login-feature-list">
            <span><FiServer aria-hidden="true" /> Node health at a glance</span>
            <span><FiShield aria-hidden="true" /> Session-aware security signals</span>
            <span><FiLock aria-hidden="true" /> Protected admin access</span>
          </div>
        </section>

        <section className="login-box" aria-labelledby="login-title">
          <div className="login-box-header">
            <div>
              <span className="login-box-kicker">{t('welcomeBack', 'Welcome back')}</span>
              <h2 id="login-title">{t('loginTitle', 'Admin Panel Login')}</h2>
              <p className="login-subtitle">{t('loginSubtitle', 'Sign in to continue to your operations dashboard.')}</p>
            </div>
            <span className="login-lock-badge" aria-hidden="true"><FiLock /></span>
          </div>
          <form onSubmit={handleSubmit}>
            <div className="input-group">
              <label htmlFor="username">{t('username')}</label>
              <input
                type="text"
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                placeholder={t('usernamePlaceholder', 'Enter your username')}
                required
              />
            </div>
            <div className="input-group">
              <label htmlFor="password">{t('password')}</label>
              <div className="password-field">
                <input
                  type={showPassword ? 'text' : 'password'}
                  id="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  placeholder={t('passwordPlaceholder', 'Enter your password')}
                  required
                />
                <button
                  type="button"
                  className="password-toggle"
                  onClick={() => setShowPassword((visible) => !visible)}
                  aria-label={showPassword ? t('hidePassword', 'Hide password') : t('showPassword', 'Show password')}
                  title={showPassword ? t('hidePassword', 'Hide password') : t('showPassword', 'Show password')}
                >
                  {showPassword ? <FiEyeOff aria-hidden="true" /> : <FiEye aria-hidden="true" />}
                </button>
              </div>
            </div>
            <button type="submit" className="btn login-submit" disabled={loading}>
              {loading && <span className="button-spinner" aria-hidden="true" />}
              <span>{loading ? `${t('loginButton')}…` : t('loginButton')}</span>
            </button>
            {error && <p className="error-message" role="alert" aria-live="assertive">{error}</p>}
          </form>
          <p className="login-footnote"><FiShield aria-hidden="true" /> Access is limited to authorized administrators.</p>
        </section>
      </div>
    </div>
  );
};

export default LoginPage;
