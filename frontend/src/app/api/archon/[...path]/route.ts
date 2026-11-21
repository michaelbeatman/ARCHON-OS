import { NextRequest, NextResponse } from 'next/server';

const ARCHON_TARGETS = [
  process.env.INTERNAL_ARCHON_URL,
  process.env.NEXT_PUBLIC_ARCHON_API_URL,
  'http://archon-os:8420',
  'http://host.docker.internal:8420',
  'http://127.0.0.1:8420',
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
  for (const base of ARCHON_TARGETS) {
    const targetUrl = `${base.replace(/\/+$/, '')}/${pathStr}${search}`;
    try {
      const upstream = await fetch(targetUrl, {
        method,
        headers: forwardHeaders,
        body: bodyBuffer && bodyBuffer.byteLength > 0 ? bodyBuffer : undefined,
        cache: 'no-store',
      });
      const respHeaders: Record<string, string> = {};
      const respCt = upstream.headers.get('content-type');
      if (respCt) respHeaders['Content-Type'] = respCt;
      return new NextResponse(upstream.body, {
        status: upstream.status,
        headers: respHeaders,
      });
    } catch (err: unknown) {
      lastError = err instanceof Error ? err.message : String(err);
    }
  }

  return NextResponse.json(
    { error: 'Archon FastAPI nicht erreichbar', details: lastError },
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

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyToArchon(request, 'DELETE', path);
}
