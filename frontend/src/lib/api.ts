export class ApiError extends Error { constructor(message: string, public status: number) { super(message); } }
function describe(value: unknown): string {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(describe).join(' ');
  if (value && typeof value === 'object') return Object.entries(value).filter(([key]) => !['code','request_id'].includes(key)).map(([key, val]) => `${['detail', 'non_field_errors'].includes(key) ? '' : `${key}: `}${describe(val)}`).join(' ');
  return 'Something went wrong. Please try again.';
}
let cachedToken: string | null = null;
let tokenRequest: Promise<string> | null = null;
export function clearCsrfToken() { cachedToken = null; tokenRequest = null; }
function cookieToken() {
  if (typeof document === 'undefined') return null;
  const value = document.cookie.split('; ').find(row => row.startsWith('csrftoken='))?.slice(10);
  return value && /^[a-zA-Z0-9]{32,64}$/.test(value) ? value : null;
}
export async function csrfToken(refresh = false): Promise<string> {
  // The CSRF cookie is readable by design; the session cookie remains HTTP-only.
  // Read it on every mutation so rotation in another browser tab is observed.
  const existing = cookieToken() || cachedToken;
  if (!refresh && existing) return existing;
  if (!tokenRequest) {
    tokenRequest = fetch('/api/auth/csrf/', {credentials: 'include', cache: 'no-store'})
      .then(async response => {
        if (!response.ok) throw new ApiError('Could not establish a secure connection to the API.', response.status);
        const data = await response.json();
        if (typeof data.csrfToken !== 'string') throw new ApiError('The server returned an invalid security token.', 503);
        cachedToken = data.csrfToken;
        return data.csrfToken as string;
      }).finally(() => { tokenRequest = null; });
  }
  return tokenRequest;
}
export async function api<T = Record<string, unknown>>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const mutation = !['GET', 'HEAD', 'OPTIONS'].includes((options.method || 'GET').toUpperCase());
  const route = path.replace(/^\//, '');
  for (let attempt = 0; attempt < 2; attempt++) {
    if (mutation) headers.set('X-CSRFToken', await csrfToken(attempt > 0));
    const response = await fetch(`/api/${route}`, {...options, headers, credentials: 'include', cache: 'no-store'});
    const data = await response.json().catch(() => ({detail: 'The server returned an unexpected response.'}));
    // Retry only a definitive CSRF rejection, before Django has run the action.
    // Never replay a mutation after a timeout, network error or permission denial.
    if (mutation && attempt === 0 && response.status === 403 && data.code === 'csrf_failed') {
      clearCsrfToken(); continue;
    }
    if (!response.ok) throw new ApiError(describe(data), response.status);
    if (mutation && /^auth\/(login|register|logout)\/$/.test(route)) {
      clearCsrfToken(); cachedToken = data.csrfToken || null;
    }
    return data as T;
  }
  throw new ApiError('Your security token expired. Refresh the page and try again.', 403);
}
export const send = <T = Record<string, unknown>>(path: string, data: unknown, method = 'POST') => api<T>(path, {method, body: JSON.stringify(data)});
export type Page<T> = {count: number; next: string | boolean | null; previous: string | boolean | null; results: T[]};
export type RecordData = Record<string, any>;
export type Session = {user: {id: number; first_name: string; email: string | null; mobile: string; login_mobile: string | null; must_change_password: boolean; is_superuser: boolean}; business: RecordData | null; role: string; billing_enabled: boolean};
