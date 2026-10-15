import { NextRequest } from 'next/server';
let firstRequest = true;
const publicSegments = new Set(['auth','csrf','login','register','logout','me','forgot-password','reset-password','dashboard','products','customers','invoices','payments','settings','profile','reports','lookup','preview','filters','widgets','health','plans','memberships','printing','devices','jobs','agent','pair','poll','ack','admin','businesses','flags','audit','overview','pay','cancel','pdf','share','ledger','catalog-preview','catalog-import','catalog-file','import-csv','revoke-links','quick']);

// Same-origin server proxy keeps session cookies first-party. Secrets never reach the browser.
async function proxy(request: NextRequest, context: {params: Promise<{path: string[]}>}) {
  const started = performance.now(); const cold = firstRequest; firstRequest = false;
  const requestId = crypto.randomUUID();
  const {path} = await context.params;
  const backend = process.env.BACKEND_URL || 'http://127.0.0.1:8000';
  const target = new URL(`/api/${path.map(encodeURIComponent).join('/')}/${request.nextUrl.search}`, backend);
  const headers = new Headers();
  headers.set('X-Request-ID', requestId);
  const route = `/api/${path.map(segment => publicSegments.has(segment) ? segment : ':value').join('/')}/`;
  const recordTiming = (status: number) => console.info(JSON.stringify({event:'api_proxy', request_id:requestId, route, method:request.method, status, total_ms:Math.round((performance.now()-started)*100)/100, worker_state:cold?'cold':'warm'}));
  if (path[0] === 'printing' && path[1] === 'agent') {
    const authorization = request.headers.get('authorization');
    if (authorization) headers.set('authorization', authorization);
  }
  for (const key of ['content-type', 'cookie', 'x-csrftoken', 'origin', 'accept']) {
    const value = request.headers.get(key); if (value) headers.set(key, value);
  }
  // Render sets the backend's forwarded scheme from its HTTPS connection.
  // Overriding it with Next's internal HTTP URL can cause redirect loops.
  try {
    const response = await fetch(target, {method: request.method, headers,
      body: ['GET', 'HEAD'].includes(request.method) ? undefined : await request.arrayBuffer(),
      redirect: 'manual', cache: 'no-store', signal: AbortSignal.timeout(90000)});
    const outgoing = new Headers();
    for (const key of ['content-type', 'content-disposition', 'location', 'retry-after', 'x-robots-tag', 'x-content-type-options', 'server-timing', 'x-worker-state']) {
      const value = response.headers.get(key); if (value) outgoing.set(key, value);
    }
    for (const cookie of response.headers.getSetCookie()) outgoing.append('set-cookie', cookie);
    outgoing.set('Cache-Control', 'private, no-store');
    outgoing.set('X-Request-ID', requestId);
    outgoing.set('X-Proxy-Worker-State', cold ? 'cold' : 'warm');
    outgoing.append('Server-Timing', `proxy;dur=${(performance.now()-started).toFixed(2)}`);
    recordTiming(response.status);
    return new Response(response.body, {status: response.status, headers: outgoing});
  } catch(error) {
    const timeout = error instanceof Error && ['TimeoutError','AbortError'].includes(error.name);
    const status = timeout ? 504 : 503; recordTiming(status);
    return Response.json({detail: timeout ? 'The server did not respond in time. It may be waking up. For a saved invoice or payment, check your records before retrying.' : 'The API is unavailable. Please try again shortly.', request_id:requestId}, {status, headers:{'Cache-Control':'private, no-store','X-Request-ID':requestId}});
  }
}
export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const PUT = proxy;
export const DELETE = proxy;
