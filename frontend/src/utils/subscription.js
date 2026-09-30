// Single source for the public /sub/{uuid} URL. Backend contract
// (routers/sub.py + routers/setting.py): GET /server/settings returns
// subscription_url_prefix (already trailing-slashed) and subscription_path
// (default "sub"); the public page is {prefix}{path}/{uuid}.
//
// The previous UserManagement.getSubscriptionLink built
// `${proto}://${domain}:${port}/${prefix}/${user.name}` — always '' because
// settings were never loaded, and keyed by name instead of uuid.

export function buildSubscriptionLink(settings, uuid) {
  if (!settings || !uuid) return '';
  const rawPrefix = settings.subscription_url_prefix || '';
  const rawPath = (settings.subscription_path || 'sub').replace(/^\/+|\/+$/g, '') || 'sub';
  if (!rawPrefix) return '';
  const prefix = rawPrefix.endsWith('/') ? rawPrefix : `${rawPrefix}/`;
  return `${prefix}${rawPath}/${uuid}`;
}
