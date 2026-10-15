export class ApiError extends Error { constructor(message: string, public status: number) { super(message); } }
function describe(value: unknown): string {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(describe).join(' ');
  if (value && typeof value === 'object') return Object.entries(value).map(([key, val]) => `${['detail', 'non_field_errors'].includes(key) ? '' : `${key}: `}${describe(val)}`).join(' ');
  return 'Something went wrong. Please try again.';
}
export async function api<T = Record<string, unknown>>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  if (options.method && !['GET', 'HEAD'].includes(options.method)) {
    const tokenResponse = await fetch('/api/auth/csrf/', {credentials: 'include', cache: 'no-store'});
    if (!tokenResponse.ok) throw new ApiError('Could not establish a secure connection to the API.', tokenResponse.status);
    const {csrfToken} = await tokenResponse.json();
    headers.set('X-CSRFToken', csrfToken);
  }
  const response = await fetch(`/api/${path.replace(/^\//, '')}`, {...options, headers, credentials: 'include', cache: 'no-store'});
  const data = await response.json().catch(() => ({detail: 'The server returned an unexpected response.'}));
  if (!response.ok) throw new ApiError(describe(data), response.status);
  return data as T;
}
export const send = <T = Record<string, unknown>>(path: string, data: unknown, method = 'POST') => api<T>(path, {method, body: JSON.stringify(data)});
export type Page<T> = {count: number; next: string | boolean | null; previous: string | boolean | null; results: T[]};
export type RecordData = Record<string, any>;
export type Session = {user: {id: number; first_name: string; email: string; mobile: string; is_superuser: boolean}; business: RecordData | null; role: string; billing_enabled: boolean};
