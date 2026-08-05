import { useState, useEffect, useCallback } from 'react';
import { FiEye, FiEyeOff } from 'react-icons/fi';

const STORAGE_KEY = 'ovmanager-mask-ips';

const PrivacyContext = null;

/**
 * PrivacyEye — toggle button for masking IP addresses in tables.
 * Persists preference to localStorage so the user's choice survives reloads.
 */
const PrivacyEye = ({ className = '', size = 18, ...props }) => {
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    setVisible(saved === null ? true : saved === 'true');
  }, []);

  const toggle = useCallback(() => {
    const next = !visible;
    setVisible(next);
    localStorage.setItem(STORAGE_KEY, String(next));
    props.onToggle?.(next);
  }, [visible]);

  return (
    <button
      type="button"
      className={`privacy-toggle${visible ? ' active' : ''} ${className}`}
      onClick={toggle}
      aria-label={visible ? 'Show IPs' : 'Mask IPs'}
      aria-pressed={!visible}
      title={visible ? 'IPs visible — click to mask' : 'IPs masked — click to reveal'}
      {...props}
    >
      {visible ? <FiEye size={size} /> : <FiEyeOff size={size} />}
    </button>
  );
};

/**
 * usePrivacyMask — hook to read the current IP-mask preference.
 * Falls back to true (masked) if no value is stored yet.
 */
export const usePrivacyMask = () => {
  const [maskIps, setMaskIps] = useState(true);
  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    setMaskIps(saved === null ? true : saved === 'true');
  }, []);
  return maskIps;
};

export default PrivacyEye;