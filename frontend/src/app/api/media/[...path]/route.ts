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

function hasAuthorizedSession(req: NextRequest): boolean {
  const auth = req.headers.get('authorization');
  if (auth && auth.trim().length > 0) return true;
  if (req.cookies.get('archon_session')?.value || req.cookies.get('pb_auth')?.value) return true;
  // Allow same-origin browser requests when running in local dev without explicit token
  const secFetchSite = req.headers.get('sec-fetch-site');
  if (secFetchSite === 'same-origin') return true;
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
  if (!hasAuthorizedSession(request)) {
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

  const fetchHeaders: Record<string, string> = {};
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
  if (!hasAuthorizedSession(request)) {
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
  if (!hasAuthorizedSession(request)) {
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
  if (!hasAuthorizedSession(request)) {
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
