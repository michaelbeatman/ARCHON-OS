import { NextRequest, NextResponse } from 'next/server';

const ARCHON_TARGETS = [
  process.env.INTERNAL_ARCHON_URL,
  process.env.NEXT_PUBLIC_ARCHON_API_URL,
  'http://archon-os:8501',
  'http://host.docker.internal:8501',
  'http://127.0.0.1:8501',
].filter((u): u is string => Boolean(u && u.trim()));

function sanitizePathSegments(segments: string[]): string | null {
  for (const seg of segments) {
    if (!seg || seg === '.' || seg === '..' || seg.includes('..') || seg.includes('\\')) {
      return null;
    }
  }
  return segments.join('/');
}

async function proxyToArchon(
  request: NextRequest,
  method: string,
  segments: string[]
): Promise<NextResponse> {
  const pathStr = sanitizePathSegments(segments);
  if (!pathStr) {
    return NextResponse.json({ error: 'Invalid API path' }, { status: 400 });
  }

  const search = request.nextUrl.search || '';
  const bodyBuffer = method !== 'GET' && method !== 'HEAD' ? await request.arrayBuffer() : undefined;

  const forwardHeaders: Record<string, string> = {};
  const auth = request.headers.get('authorization');
  if (auth) forwardHeaders['Authorization'] = auth;
  const cookie = request.headers.get('cookie');
  if (cookie) forwardHeaders['Cookie'] = cookie;
  const contentType = request.headers.get('content-type');
  if (contentType) forwardHeaders['Content-Type'] = contentType;
  const apiKey = request.headers.get('x-api-key');
  if (apiKey) forwardHeaders['X-API-Key'] = apiKey;

  let lastError: string = 'Archon Backend nicht erreichbar';
  let lastResponse: NextResponse | null = null;
  for (let i = 0; i < ARCHON_TARGETS.length; i += 1) {
    const base = ARCHON_TARGETS[i];
    const targetUrl = `${base.replace(/\/+$/, '')}/${pathStr}${search}`;
    try {
      // KRITISCH (Audit 23.11.2026): SSE-Streams dürfen NICHT nach 5 s
      // abgebrochen werden — der Backend-Bus sendet Keepalive alle 20 s.
      const isSseRequest = pathStr.includes('events/stream') || pathStr.includes('/stream');
      const upstream = await fetch(targetUrl, {
        method,
        headers: forwardHeaders,
        body: bodyBuffer && bodyBuffer.byteLength > 0 ? bodyBuffer : undefined,
        cache: 'no-store',
        signal: isSseRequest ? undefined : AbortSignal.timeout(5000),
      });
      const respHeaders: Record<string, string> = {};
      const respCt = upstream.headers.get('content-type');
      if (respCt) respHeaders['Content-Type'] = respCt;
      if (isSseRequest || respCt?.includes('text/event-stream')) {
        for (const h of ['Cache-Control', 'X-Accel-Buffering']) {
          const v = upstream.headers.get(h);
          if (v) respHeaders[h] = v;
        }
      }
      const response = new NextResponse(upstream.body, {
        status: upstream.status,
        headers: respHeaders,
      });
      // Früher wurde die ERSTE HTTP-Antwort sofort zurückgegeben — auch ein
      // 404/500 eines falsch konfigurierten Ziels. Dann wurden die korrekten
      // Fallbacks nie probiert und die komplette Content-Machine lieferte 404.
      if (upstream.ok || i === ARCHON_TARGETS.length - 1) {
        return response;
      }
      lastResponse = response;
      await upstream.body?.cancel().catch(() => undefined);
    } catch (err: unknown) {
      lastError = err instanceof Error ? err.message : String(err);
    }
  }

  if (lastResponse) return lastResponse;
  // Keine internen_HOST/Port/DNS-Details an den Client (OWASP ASVS 5.0).
  console.error('[archon-proxy] Backend nicht erreichbar:', lastError);
  return NextResponse.json(
    { error: 'Archon Backend nicht erreichbar', request_id: crypto.randomUUID() },
    { status: 502 }
  );
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyToArchon(request, 'GET', path);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyToArchon(request, 'POST', path);
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyToArchon(request, 'PATCH', path);
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyToArchon(request, 'PUT', path);
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyToArchon(request, 'DELETE', path);
}
