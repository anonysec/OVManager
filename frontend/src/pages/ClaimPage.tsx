import { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { FiAlertCircle, FiEye, FiEyeOff } from 'react-icons/fi';
import apiClient from '../services/api';
import Logo from '../components/Logo';
import { Button, Field } from '../components/ui';
import './LoginPage.css';

const ClaimPage = () => {
  const [step, setStep] = useState<'verify' | 'create'>('verify');
  const [setupKey, setSetupKey] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { claim } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { t } = useTranslation();
  const recover = searchParams.get('mode') === 'recover';

  const clearError = () => { if (error) setError(''); };

  const claimErrorOf = (err: any) =>
    err?.response?.data?.detail || t('claimError', 'The claim failed. Check the key and try again.');

  // Step 1 — prove the holder of the setup key before asking for credentials.
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

  // Step 2 — the key checked out, now create the owner account.
  const handleCreate = async (e: any) => {
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
      setError(claimErrorOf(err));
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
          <form className="login-form" onSubmit={handleCreate}>
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

            <div className="ui-field">
              <label className="ui-field-label" htmlFor="claim-confirm">{t('confirmPassword', 'Confirm password')}</label>
              <div className="ui-field-control login-password-wrap">
                <input
                  type={showPassword ? 'text' : 'password'}
                  id="claim-confirm"
                  className="ui-input login-password-input"
                  value={confirmPassword}
                  onChange={(e) => { setConfirmPassword(e.target.value); clearError(); }}
                  autoComplete="new-password"
                  placeholder={t('passwordPlaceholder', '••••••••')}
                  minLength={8}
                  required
                />
              </div>
            </div>

            <Button type="submit" variant="primary" size="lg" block loading={loading}>
              {t('claimButton', 'Create owner account')}
            </Button>
          </form>
        )}
      </main>
    </div>
  );
};

export default ClaimPage;
