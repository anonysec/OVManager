/**
 * Unwrap a panel API payload into a list.
 *
 * GET /users/ and GET /nodes/ return `{ users|nodes, total, … }` inside the
 * standard `{ success, data }` envelope. Callers may hand us:
 *   - the axios response (`res` from settle(), whose `.data` is the body)
 *   - the API body (`response.data` from apiClient.get)
 *   - the inner `{ users, total }` object
 *   - a bare array (legacy / other endpoints)
 * Walking `.data` a few times keeps every consumer in sync.
 */
export function asList(payload, key) {
  let data = payload;
  for (let i = 0; i < 4 && data != null && !Array.isArray(data); i += 1) {
    if (key && Array.isArray(data[key])) return data[key];
    if (Array.isArray(data.users)) return data.users;
    if (Array.isArray(data.nodes)) return data.nodes;
    if (data.data !== undefined) {
      data = data.data;
      continue;
    }
    break;
  }
  return Array.isArray(data) ? data : [];
}
