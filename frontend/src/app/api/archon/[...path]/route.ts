import { NextRequest, NextResponse } from 'next/server';

const ARCHON_TARGETS = [
  process.env.INTERNAL_ARCHON_URL,
  process.env.NEXT_PUBLIC_ARCHON_API_URL,
  'http://archon-os:8501',
  'http://host.docker.internal:8501',
  'http://127.0.0.1:8501',
].filter((u): u is string => Boolean(u && u.trim()));

const TRACE_ID_RE = /^[0-9a-f]{32}$/i;
const FLAGS_RE = /^[0-9a-f]{2}$/i;

// W3C child span: neue 64-Bit-Span-ID, trace-id und Sampled-Flag bleiben erhalten.
function childTraceparent(incoming: string | null | undefined): string | null {
  const parts = (incoming || '').trim().split('-');
  if (parts.length !== 4) return null;
  const [version, traceId, , flags] = parts;
  if (version !== '00' || !TRACE_ID_RE.test(traceId) || /^0{32}$/i.test(traceId) || !FLAGS_RE.test(flags)) {
    return null;
  }
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  const spanId = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  if (/^0{16}$/i.test(spanId)) return null;
  return `${version}-${traceId.toLowerCase()}-${spanId}-${flags.toLowerCase()}`;
}

// W3C tracestate: gueltige Vendor-Eintraege, max. 32 Eintraege / 512 Zeichen.
function validTracestate(value: string | null | undefined): string | null {
  const raw = (value || '').trim();
  if (!raw) return null;
  const entries = raw.split(',').map((e) => e.trim()).filter((e) =>
    /^[a-z0-9_*/\-]{1,256}=[\x20-\x2b\x2d-\x3c\x3e-\x7e]{0,256}$/.test(e)
  ).slice(0, 32);
  while (entries.length > 0 && entries.join(',').length > 512) entries.pop();
  return entries.length > 0 ? entries.join(',') : null;
}

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
  // D16: Trace-Kontext über die Grenze Browser/Next.js → FastAPI (Child-Span).
  const childTp = childTraceparent(request.headers.get('traceparent'));
  if (childTp) forwardHeaders['traceparent'] = childTp;
  const inboundTracestate = validTracestate(request.headers.get('tracestate'));
  if (inboundTracestate) forwardHeaders['tracestate'] = inboundTracestate;

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
      // D16: Korrelations-ID und forkbarer W3C-Kontext zurück an den Browser.
      const upstreamTraceId = upstream.headers.get('X-Trace-Id');
      const fallbackTraceId = childTp ? childTp.split('-')[1] : null;
      if (upstreamTraceId || fallbackTraceId) {
        respHeaders['X-Trace-Id'] = upstreamTraceId || fallbackTraceId || '';
      }
      if (childTp) respHeaders['traceparent'] = childTp;
      if (inboundTracestate) respHeaders['tracestate'] = inboundTracestate;
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
