// GET /users/ and /nodes/ return `{ users|nodes, total, … }` inside a
// `{ success, data }` envelope, but callers pass the payload at any of four
// depths (fetch response, apiClient body, inner object, bare array). Walking

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
