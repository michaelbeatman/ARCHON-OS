import { NextRequest, NextResponse } from 'next/server';

const MEDIA_PB_URL = process.env.INTERNAL_POCKETBASE_MEDIA_URL || 'http://pocketbase-media:8090';
const HOST_DOCKER_URL = 'http://host.docker.internal:8092';
const LOCALHOST_URL = 'http://127.0.0.1:8092';
const ALLOWED_ORIGIN = process.env.NEXT_PUBLIC_APP_ORIGIN || 'http://localhost:3000';

function getCorsHeaders(req: NextRequest): Record<string, string> {
  const origin = req.headers.get('origin');
  const allowed = origin && (origin === ALLOWED_ORIGIN || origin.startsWith('http://localhost:') || origin.startsWith('http://127.0.0.1:'))
    ? origin
    : ALLOWED_ORIGIN;
  return {
    'Access-Control-Allow-Origin': allowed,
    'Vary': 'Origin',
  };
}

// D16: Auch der Media-Proxy muss einen gueltigen W3C-Kontext weitergeben.
// Kommt keiner vom Browser (PocketBase beforeSend), erzeugt er selbst einen Root.
const TRACE_ID_RE = /^[0-9a-f]{32}$/i;
const FLAGS_RE = /^[0-9a-f]{2}$/i;

function randomHex(byteLength: number): string {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

function childTraceparent(incoming: string | null | undefined): string | null {
  const parts = (incoming || '').trim().split('-');
  if (parts.length !== 4) return null;
  const [version, traceId, , flags] = parts;
  if (version !== '00' || !TRACE_ID_RE.test(traceId) || /^0{32}$/i.test(traceId) || !FLAGS_RE.test(flags)) {
    return null;
  }
  const spanId = randomHex(8);
  if (/^0{16}$/i.test(spanId)) return null;
  return `${version}-${traceId.toLowerCase()}-${spanId}-${flags.toLowerCase()}`;
}

function rootTraceparent(): string {
  let traceId = randomHex(16);
  while (/^0{32}$/i.test(traceId)) traceId = randomHex(16);
  let spanId = randomHex(8);
  while (/^0{16}$/i.test(spanId)) spanId = randomHex(8);
  return `00-${traceId}-${spanId}-01`;
}

function validTracestate(value: string | null | undefined): string | null {
  const raw = (value || '').trim();
  if (!raw) return null;
  const entries = raw.split(',').map((e) => e.trim()).filter((e) =>
    /^[a-z0-9_*/\-]{1,256}=[\x20-\x2b\x2d-\x3c\x3e-\x7e]{0,256}$/.test(e)
  ).slice(0, 32);
  while (entries.length > 0 && entries.join(',').length > 512) entries.pop();
  return entries.length > 0 ? entries.join(',') : null;
}

function traceHeaders(req: NextRequest): Record<string, string> {
  const incoming = req.headers.get('traceparent');
  const forked = childTraceparent(incoming);
  if (incoming && !forked) {
    console.warn('[media-proxy] Ungueltiger traceparent verworfen — neuer Root erzeugt');
  }
  const headers: Record<string, string> = { traceparent: forked || rootTraceparent() };
  const tracestate = validTracestate(req.headers.get('tracestate'));
  if (tracestate) headers['tracestate'] = tracestate;
  return headers;
}

async function hasAuthorizedSession(req: NextRequest): Promise<boolean> {
  const trace = traceHeaders(req);
  // Vorher genügte ein beliebiger nicht-leerer Authorization-Header oder
  // blosses Vorhandensein eines Cookies/sec-fetch-site -> wirkungsloses Gate.
  // Jetzt echte Verifikation gegen den Archon-Backend (verify_session).
  const token = (req.headers.get('authorization') || '').replace(/^Bearer\s+/i, '').trim()
    || req.cookies.get('archon_session')?.value
    || '';
  if (!token) return false;
  const pbToken = req.cookies.get('pb_auth')?.value;
  if (pbToken) {
    try {
      const pbRes = await fetch(`${MEDIA_PB_URL}/api/auth/refresh`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...trace }, body: '{}',
        cache: 'no-store', signal: AbortSignal.timeout(3000),
      });
      if (pbRes.ok) return true;
    } catch { /* dann Archon-Session versuchen */ }
  }
  try {
    const targets = [process.env.INTERNAL_ARCHON_URL, 'http://archon-os:8501', 'http://127.0.0.1:8501']
      .filter((u): u is string => Boolean(u && u.trim()));
    for (const base of targets) {
      const res = await fetch(`${base.replace(/\/+$/, '')}/api/auth/me`, {
        headers: { Authorization: `Bearer ${token}`, ...trace },
        cache: 'no-store', signal: AbortSignal.timeout(3000),
      });
      if (res.ok) return true;
    }
  } catch { /* fail-closed */ }
  return false;
}

function sanitizePathSegments(segments: string[]): string | null {
  for (const seg of segments) {
    if (!seg || seg === '.' || seg === '..' || seg.includes('..') || seg.includes('\\')) {
      return null;
    }
  }
  return segments.join('/');
}

async function forwardRequest(method: string, url: string, req: NextRequest, bodyBuffer?: ArrayBuffer) {
  const headers: Record<string, string> = {};
  const authHeader = req.headers.get('authorization');
  if (authHeader) headers['Authorization'] = authHeader;

  // Content-Type inklusive multipart/form-data boundary zwingend beibehalten
  const contentType = req.headers.get('content-type');
  if (contentType) {
    headers['Content-Type'] = contentType;
  }

  const rangeHeader = req.headers.get('range');
  if (rangeHeader) {
    headers['Range'] = rangeHeader;
  }

  Object.assign(headers, traceHeaders(req));

  return fetch(url, {
    method,
    headers,
    body: method !== 'GET' && method !== 'HEAD' ? bodyBuffer : undefined,
    cache: 'no-store',
  });
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  if (!(await hasAuthorizedSession(request))) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  const { path } = await params;
  const pathStr = sanitizePathSegments(path);
  if (!pathStr) {
    return NextResponse.json({ error: 'Invalid media path' }, { status: 400 });
  }
  const search = request.nextUrl.search;

  const targetUrls = [
    `${MEDIA_PB_URL}/api/${pathStr}${search}`,
    `${HOST_DOCKER_URL}/api/${pathStr}${search}`,
    `${LOCALHOST_URL}/api/${pathStr}${search}`,
  ];

  let lastError: any = null;

  const fetchHeaders: Record<string, string> = { ...traceHeaders(request) };
  const rangeHeader = request.headers.get('range');
  if (rangeHeader) {
    fetchHeaders['Range'] = rangeHeader;
  }
  const authHeader = request.headers.get('authorization');
  if (authHeader) {
    fetchHeaders['Authorization'] = authHeader;
  }

  for (const url of targetUrls) {
    try {
      const response = await fetch(url, {
        headers: fetchHeaders,
        cache: 'no-store'
      });

      const responseHeaders: Record<string, string> = {
        ...getCorsHeaders(request),
      };

      const contentType = response.headers.get('content-type');
      if (contentType) responseHeaders['Content-Type'] = contentType;

      const contentRange = response.headers.get('content-range');
      if (contentRange) responseHeaders['Content-Range'] = contentRange;

      const acceptRanges = response.headers.get('accept-ranges');
      if (acceptRanges) responseHeaders['Accept-Ranges'] = acceptRanges;

      const contentLength = response.headers.get('content-length');
      if (contentLength) responseHeaders['Content-Length'] = contentLength;

      // Stream response body directly instead of buffering full video/audio files into RAM
      return new NextResponse(response.body, {
        status: response.status,
        headers: responseHeaders,
      });
    } catch (err: any) {
      lastError = err;
    }
  }

  return NextResponse.json(
    { error: 'Failed to proxy request to Media PocketBase', details: lastError?.message || 'Unknown network error' },
    { status: 502 }
  );
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  if (!(await hasAuthorizedSession(request))) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  const { path } = await params;
  const pathStr = sanitizePathSegments(path);
  if (!pathStr) {
    return NextResponse.json({ error: 'Invalid media path' }, { status: 400 });
  }
  const search = request.nextUrl.search;
  const bodyBuffer = await request.arrayBuffer();

  const targetUrls = [
    `${MEDIA_PB_URL}/api/${pathStr}${search}`,
    `${HOST_DOCKER_URL}/api/${pathStr}${search}`,
    `${LOCALHOST_URL}/api/${pathStr}${search}`,
  ];

  let lastError: any = null;

  for (const url of targetUrls) {
    try {
      const response = await forwardRequest('POST', url, request, bodyBuffer);
      const contentType = response.headers.get('content-type') || 'application/json';

      return new NextResponse(response.body, {
        status: response.status,
        headers: {
          'Content-Type': contentType,
          ...getCorsHeaders(request),
        },
      });
    } catch (err: any) {
      lastError = err;
    }
  }

  return NextResponse.json(
    { error: 'Failed to proxy POST request to Media PocketBase', details: lastError?.message || 'Unknown network error' },
    { status: 502 }
  );
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  if (!(await hasAuthorizedSession(request))) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  const { path } = await params;
  const pathStr = sanitizePathSegments(path);
  if (!pathStr) {
    return NextResponse.json({ error: 'Invalid media path' }, { status: 400 });
  }
  const search = request.nextUrl.search;
  const bodyBuffer = await request.arrayBuffer();

  const targetUrls = [
    `${MEDIA_PB_URL}/api/${pathStr}${search}`,
    `${HOST_DOCKER_URL}/api/${pathStr}${search}`,
    `${LOCALHOST_URL}/api/${pathStr}${search}`,
  ];

  let lastError: any = null;

  for (const url of targetUrls) {
    try {
      const response = await forwardRequest('PATCH', url, request, bodyBuffer);
      const contentType = response.headers.get('content-type') || 'application/json';

      return new NextResponse(response.body, {
        status: response.status,
        headers: {
          'Content-Type': contentType,
          ...getCorsHeaders(request),
        },
      });
    } catch (err: any) {
      lastError = err;
    }
  }

  return NextResponse.json(
    { error: 'Failed to proxy PATCH request to Media PocketBase', details: lastError?.message || 'Unknown network error' },
    { status: 502 }
  );
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  if (!(await hasAuthorizedSession(request))) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  const { path } = await params;
  const pathStr = sanitizePathSegments(path);
  if (!pathStr) {
    return NextResponse.json({ error: 'Invalid media path' }, { status: 400 });
  }
  const search = request.nextUrl.search;

  const targetUrls = [
    `${MEDIA_PB_URL}/api/${pathStr}${search}`,
    `${HOST_DOCKER_URL}/api/${pathStr}${search}`,
    `${LOCALHOST_URL}/api/${pathStr}${search}`,
  ];

  let lastError: any = null;

  for (const url of targetUrls) {
    try {
      const response = await forwardRequest('DELETE', url, request);
      const contentType = response.headers.get('content-type') || 'application/json';

      return new NextResponse(response.body, {
        status: response.status,
        headers: {
          'Content-Type': contentType,
          ...getCorsHeaders(request),
        },
      });
    } catch (err: any) {
      lastError = err;
    }
  }

  return NextResponse.json(
    { error: 'Failed to proxy DELETE request to Media PocketBase', details: lastError?.message || 'Unknown network error' },
    { status: 502 }
  );
}
