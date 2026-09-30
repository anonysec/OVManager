import { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { FiAlertCircle, FiEye, FiEyeOff } from 'react-icons/fi';
import Logo from '../components/Logo';
import { Button, Field } from '../components/ui';
// The pre-auth card, shared with the login page: same shell, same classes.
import './LoginPage.css';

// First-run owner claim: the installer prints a one-time key and no password.
// Posting it with the chosen password creates the owner row; the key is spent
// by the attempt.
const ClaimPage = () => {
  const [claimKey, setClaimKey] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { claim } = useAuth();
  const navigate = useNavigate();
  const { t } = useTranslation();

  const clearError = () => { if (error) setError(''); };

  const handleSubmit = async (e: any) => {
    e.preventDefault();
    if (loading) return;
    setError('');
    setLoading(true);
    try {
      await claim(claimKey.trim(), password);
      navigate('/');
    } catch (err: any) {
      // The server explains exactly what is wrong (already claimed, no key,
      // key refused), and that message is more useful than a generic one.
      setError(err?.response?.data?.detail || t('claimError', 'The claim failed. Check the key and try again.'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <main className="login-card">
        <header className="login-card-header">
          <span className="login-brand-mark" aria-hidden="true"><Logo size={40} /></span>
          <h1 className="login-brand">
            OV<span>Manager</span>
          </h1>
          <p className="login-card-subtitle">
            {t('claimSubtitle', 'Paste the claim key from the installer and choose the owner password.')}
          </p>
        </header>

        {error && (
          <div className="login-error" role="alert" aria-live="assertive">
            <FiAlertCircle aria-hidden="true" />
            <span>{error}</span>
          </div>
        )}

        <form className="login-form" onSubmit={handleSubmit}>
          <Field label={t('claimKey', 'Claim key')} hint={t('claimKeyHint', 'Printed at the end of the install; regenerate it with: ovm owner-claim')}>
            <input
              type="text"
              id="claim-key"
              value={claimKey}
              onChange={(e) => { setClaimKey(e.target.value); clearError(); }}
              autoComplete="off"
              spellCheck={false}
              required
              autoFocus
            />
          </Field>

          <div className="ui-field">
            <label className="ui-field-label" htmlFor="claim-password">{t('claimPassword', 'Owner password')}</label>
            <div className="ui-field-control login-password-wrap">
              <input
                type={showPassword ? 'text' : 'password'}
                id="claim-password"
                className="ui-input login-password-input"
                value={password}
                onChange={(e) => { setPassword(e.target.value); clearError(); }}
                autoComplete="new-password"
                placeholder={t('passwordPlaceholder', '••••••••')}
                minLength={8}
                required
              />
              <button
                type="button"
                className="login-password-toggle"
                onClick={() => setShowPassword((visible) => !visible)}
                aria-label={showPassword ? t('hidePassword', 'Hide password') : t('showPassword', 'Show password')}
                title={showPassword ? t('hidePassword', 'Hide password') : t('showPassword', 'Show password')}
              >
                {showPassword ? <FiEyeOff aria-hidden="true" /> : <FiEye aria-hidden="true" />}
              </button>
            </div>
          </div>

          <Button type="submit" variant="primary" size="lg" block loading={loading}>
            {t('claimButton', 'Claim this panel')}
          </Button>
        </form>
      </main>
    </div>
  );
};

export default ClaimPage;
