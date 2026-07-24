import { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import logoSrc from '../assets/ovmanager-character.webp'; 

const LoginPage = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const { login } = useAuth();
  const navigate = useNavigate();
  const { t } = useTranslation();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    try {
      await login(username, password);
      navigate('/');
    } catch { 
      setError(t('loginError'));
    }
  };

  return (
    <div id="login-container">
      <div className="login-box">
        <div className="login-hero-card">
          <img src={logoSrc} alt="OVManager mascot" className="login-logo" />
          <div className="login-orbit login-orbit-one" />
          <div className="login-orbit login-orbit-two" />
        </div>
        <div className="product-kicker">OVNode Fleet Control</div>
        <h2>OVManager</h2>
        <p className="login-subtitle">Secure VPN operations, users, nodes and traffic in one control room.</p>
        <form onSubmit={handleSubmit}>
          <div className="input-group">
            <label htmlFor="username">{t('username')}</label>
            <input
              type="text"
              id="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>
          <div className="input-group">
            <label htmlFor="password">{t('password')}</label>
            <input
              type="password"
              id="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          <button type="submit" className="btn">{t('loginButton')}</button>
          {error && <p className="error-message">{error}</p>}
        </form>
      </div>
    </div>
  );
};

export default LoginPage;