export class SessionExpired extends Error {}
export function apiBase() {
  const value = (process.env.EXPO_PUBLIC_API_BASE_URL || '').replace(/\/$/, '');
  if (!value) throw new Error('Set EXPO_PUBLIC_API_BASE_URL before building this app.');
  const url = new URL(value);
  if (url.username || url.password || url.search || url.hash || url.pathname !== '/') throw new Error('Use the API origin only, without credentials or a path.');
  if (url.protocol !== 'https:' && !(typeof __DEV__ !== 'undefined' && __DEV__ && url.protocol === 'http:')) throw new Error('The release app requires an HTTPS API URL.');
  return value;
}
export async function request<T = any>(path: string, token?: string, body?: unknown): Promise<T> {
  const controller = new AbortController();
  // Cold starts are allowed 75 seconds. Offline saves never call this function.
  const timer = setTimeout(() => controller.abort(), 75000);
  try {
    const response = await fetch(`${apiBase()}/api/mobile/${path}/`, {
      method: body === undefined ? 'GET' : 'POST', signal: controller.signal, credentials: 'omit',
      headers: {'Content-Type': 'application/json', ...(token ? {Authorization: `Bearer ${token}`} : {})},
      ...(body === undefined ? {} : {body: JSON.stringify(body)})
    });
    let data: any;
    try {data = await response.json();} catch {throw new Error('Server is starting or unavailable. Local bills are safe; retry later.');}
    if (response.status === 401) throw new SessionExpired(data.detail || 'Sign in online again.');
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Server rejected this request. Check your account and connection.');
    return data;
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw new Error('Server connection timed out. Local data is safe.');
    throw error;
  } finally {clearTimeout(timer);}
}
export async function pullRequest(cursor: string, token: string) {
  // Query parameters belong before the trailing API path slash.
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 75000);
  try {
    const r = await fetch(`${apiBase()}/api/mobile/pull/?cursor=${encodeURIComponent(cursor)}`, {signal: controller.signal, credentials: 'omit', headers: {Authorization: `Bearer ${token}`}});
    if (r.status === 401) throw new SessionExpired('Device session expired or revoked. Sign in online; pending bills remain safe.');
    if (!r.ok) throw new Error('Could not download updates. Retry when the server is available.');
    return await r.json();
  } finally {clearTimeout(timer);}
}
