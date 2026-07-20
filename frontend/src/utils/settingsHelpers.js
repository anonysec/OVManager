// Pure, framework-free helpers shared by Settings.jsx and the test suite.

export const SUB_URL_SCHEME_RE = /^https?:$/;
export const SUB_PATH_RE = /^[a-zA-Z0-9_-]+(\/[a-zA-Z0-9_-]+)*$/;

/**
 * Validate the subscription URL prefix + path.
 * Returns an i18n key (string) on failure, or '' when valid.
 * The caller maps the key through useTranslation().
 */
export function validateSubscription(prefix, path, t) {
  const p = (prefix || '').trim();
  const pa = (path || '').trim();
  if (p) {
    try {
      const u = new URL(p);
      if (!SUB_URL_SCHEME_RE.test(u.protocol)) return t('urlSchemeHttp');
    } catch {
      return t('urlInvalid');
    }
  }
  if (pa && !SUB_PATH_RE.test(pa.replace(/^\/+|\/+$/g, ''))) {
    return t('pathInvalid');
  }
  return '';
}

const ICON_MAP = { dark: 'moon', light: 'sun' };

export function themeIcon(theme) {
  return ICON_MAP[theme] || 'moon';
}

export function buildSubUrl(prefix, path) {
  return `${prefix}${path ? path.replace(/^\/+|\/+$/g, '') + '/' : ''}{user_uuid}`;
}
