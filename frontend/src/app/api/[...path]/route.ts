import { NextRequest } from 'next/server';

// Same-origin server proxy keeps session cookies first-party. Secrets never reach the browser.
async function proxy(request: NextRequest, context: {params: Promise<{path: string[]}>}) {
  const {path} = await context.params;
  const backend = process.env.BACKEND_URL || 'http://127.0.0.1:8000';
  const target = new URL(`/api/${path.map(encodeURIComponent).join('/')}/${request.nextUrl.search}`, backend);
  const headers = new Headers();
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
    for (const key of ['content-type', 'content-disposition', 'location', 'retry-after', 'x-robots-tag', 'x-content-type-options']) {
      const value = response.headers.get(key); if (value) outgoing.set(key, value);
    }
    for (const cookie of response.headers.getSetCookie()) outgoing.append('set-cookie', cookie);
    outgoing.set('Cache-Control', 'private, no-store');
    return new Response(response.body, {status: response.status, headers: outgoing});
  } catch(error) {
    console.error('Billora API proxy failed:', error instanceof Error ? error.name : 'Unknown error');
    return Response.json({detail: 'The API is unavailable. Please try again shortly.'}, {status: 503});
  }
}
export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const PUT = proxy;
export const DELETE = proxy;
