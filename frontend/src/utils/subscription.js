// Subscription link builder — single source for the public /sub/{uuid} URL.
//
// Backend contract (routers/sub.py + routers/setting.py):
//   GET /server/settings -> { subscription_url_prefix, subscription_path }
//   subscription_url_prefix already ends with "/" (DB > env > request base)
//   subscription_path defaults to "sub"
//   Public page:  {prefix}{path}/{uuid}
//   Per-node dl:  {prefix}{path}/download/{uuid}/{nodeName}  (server-side route,
//   kept here for completeness; panel downloads use /api/nodes/ovpn/* instead)
//
// Previous UserManagement.getSubscriptionLink built
//   `${proto}://${domain}:${port}/${prefix}/${user.name}`
// which was always '' (settings never loaded) and used name instead of uuid.

export function buildSubscriptionLink(settings, uuid) {
  if (!settings || !uuid) return '';
  const rawPrefix = settings.subscription_url_prefix || '';
  const rawPath = (settings.subscription_path || 'sub').replace(/^\/+|\/+$/g, '') || 'sub';
  if (!rawPrefix) return '';
  const prefix = rawPrefix.endsWith('/') ? rawPrefix : `${rawPrefix}/`;
  return `${prefix}${rawPath}/${uuid}`;
}

export function buildSubscriptionDownloadLink(settings, uuid, nodeName) {
  const base = buildSubscriptionLink(settings, uuid);
  if (!base || !nodeName) return base;
  return `${base.replace(/\/$/, '')}/download/${uuid}/${encodeURIComponent(nodeName)}`;
}
