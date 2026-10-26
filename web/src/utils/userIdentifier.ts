// Prefer the compact numeric route for authenticated panel operations when
// the server supplies a safe live-row ID. UUIDs remain the fallback for older
// payloads and for durable/public links such as subscriptions and restore.
export const userIdentifierSegment = (user: { id?: unknown; uuid?: unknown }) => {
  const value = user?.id;
  if (typeof value === 'number' && Number.isSafeInteger(value) && value > 0) {
    return `id/${value}`;
  }
  if (typeof value === 'string' && /^[1-9]\d*$/.test(value)
    && (value.length < 19 || (value.length === 19 && value <= '9223372036854775807'))) {
    return `id/${value}`;
  }
  return encodeURIComponent(typeof user?.uuid === 'string' ? user.uuid : '');
};

export const userApiPath = (user: { id?: unknown; uuid?: unknown }) =>
  `/users/${userIdentifierSegment(user)}`;
