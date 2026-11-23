import { NextResponse } from 'next/server';

/**
 * Theme-Live-Overrides: dünner Proxy auf den FastAPI-Endpunkt.
 * Leitet Auth-Header und Cookies weiter — der FastAPI-Endpunkt ist
 * admin-geschützt; ohne Spiegelung bekamen POST/DELETE 401.
 */
const ARCHON_TARGETS = [
  process.env.INTERNAL_ARCHON_URL,
  process.env.NEXT_PUBLIC_ARCHON_API_URL,
  'http://archon-os:8501',
  'http://host.docker.internal:8501',
  'http://127.0.0.1:8501',
].filter((u): u is string => Boolean(u && u.trim()));

const UPSTREAM = '/api/theme/live-overrides';

function forwardHeaders(request: Request, withBody: boolean): HeadersInit {
  const headers: Record<string, string> = {};
  const auth = request.headers.get('authorization');
  if (auth) headers['Authorization'] = auth;
  const cookie = request.headers.get('cookie');
  if (cookie) headers['Cookie'] = cookie;
  if (withBody) headers['Content-Type'] = 'application/json';
  return headers;
}

async function forward(request: Request, method: 'GET' | 'POST' | 'DELETE') {
  const body = method === 'POST' ? await request.text() : undefined;
  const headers = forwardHeaders(request, method === 'POST');
  let lastError = '';
  for (let i = 0; i < ARCHON_TARGETS.length; i += 1) {
    const base = ARCHON_TARGETS[i];
    try {
      const res = await fetch(`${base.replace(/\/+$/, '')}${UPSTREAM}`, {
        method,
        headers,
        body,
        cache: 'no-store',
      });
      if (res.ok || i === ARCHON_TARGETS.length - 1) {
        const text = await res.text();
        return new NextResponse(text || null, {
          status: res.status,
          headers: { 'Content-Type': res.headers.get('content-type') || 'application/json' },
        });
      }
    } catch (err) {
      lastError = err instanceof Error ? err.message : String(err);
    }
  }
  return NextResponse.json({ error: 'Archon-Theme-Endpoint nicht erreichbar', details: lastError }, { status: 502 });
}

export async function GET(request: Request) { return forward(request, 'GET'); }
export async function POST(request: Request) { return forward(request, 'POST'); }
export async function DELETE(request: Request) { return forward(request, 'DELETE'); }
