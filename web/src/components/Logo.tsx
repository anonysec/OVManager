// Accent colour comes from `currentColor`, so callers recolour the logo via
// `color: var(--accent)`. The globe is deliberately minimal (ring + meridian +
// equator + hub): finer detail turned to mud at menu size.

import { useTranslation } from 'react-i18next';

const Logo = ({ size = 38, className = '' }) => {
  const { t } = useTranslation();
  return (
  <svg
    width={size}
    height={size}
    viewBox="0 0 48 48"
    className={`ops-logo-svg ${className}`}
    role="img"
    aria-label={t('appLogo', 'OVManager')}
    style={{ color: 'var(--accent-color, var(--accent, #ff7a1e))' }}
  >
    <rect x="2" y="2" width="44" height="44" rx="13" fill="currentColor" />
    <circle cx="24" cy="24" r="12.5" fill="none" stroke="var(--logo-ink, #15110a)" strokeWidth="3" />
    <ellipse cx="24" cy="24" rx="5.5" ry="12.5" fill="none" stroke="var(--logo-ink, #15110a)" strokeWidth="2.2" />
    <line x1="11.5" y1="24" x2="36.5" y2="24" stroke="var(--logo-ink, #15110a)" strokeWidth="2.2" />
    <circle cx="24" cy="24" r="3.6" fill="var(--logo-ink, #15110a)" />
  </svg>
  );
};

export default Logo;
