import { NextRequest, NextResponse } from 'next/server';

/**
 * GET /api/calendar/ics?url=<encoded-ics-url>
 *
 * Server-side ICS proxy + parser. Fetches the ICS file from the given URL
 * (bypasses browser CORS restrictions) and returns parsed events as JSON.
 *
 * No external dependencies — pure regex/string parsing.
 */

interface ParsedEvent {
  id: string;
  title: string;
  start: string;
  end: string;
  source: 'outlook' | 'google';
  location: string;
  description: string;
  attendees: string[];
}

// ─── ICS date parsing ─────────────────────────────────────────────────────────

function parseIcsDate(raw: string): string {
  if (!raw) return '';
  raw = raw.trim();

  // Already ISO-ish: YYYY-MM-DD
  if (/^\d{4}-\d{2}-\d{2}/.test(raw)) return new Date(raw).toISOString();

  // TZID=Europe/Berlin:20260806T085749 → strip TZID prefix
  const tzMatch = raw.match(/TZID=[^:]+:(.+)/);
  if (tzMatch) raw = tzMatch[1];

  // 20260806T085749Z or 20260806T085749
  const m = raw.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(Z?)$/);
  if (m) {
    const [, y, mo, d, h, min, s, z] = m;
    const iso = `${y}-${mo}-${d}T${h}:${min}:${s}${z || ''}`;
    return new Date(iso).toISOString();
  }

  // DATE only: 20260806
  const dateOnly = raw.match(/^(\d{4})(\d{2})(\d{2})$/);
  if (dateOnly) {
    const [, y, mo, d] = dateOnly;
    return new Date(`${y}-${mo}-${d}T00:00:00Z`).toISOString();
  }

  return '';
}

// ─── ICS parser ───────────────────────────────────────────────────────────────

function parseIcs(text: string, lookBackDays: number, lookAheadDays: number, source: 'google' | 'outlook'): ParsedEvent[] {
  const events: ParsedEvent[] = [];

  // Unfold lines (ICS allows folding with CRLF + whitespace)
  const unfolded = text.replace(/\r\n[ \t]/g, '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');

  const veventBlocks = unfolded.match(/BEGIN:VEVENT[\s\S]*?END:VEVENT/g) || [];

  const now = Date.now();
  const minTs = now - lookBackDays * 86400_000;
  const maxTs = now + lookAheadDays * 86400_000;

  for (const block of veventBlocks) {
    const get = (key: string): string => {
      // Handle multi-line values and TZID prefixes like DTSTART;TZID=...:value
      const re = new RegExp(`^${key}(?:;[^:]*)?:(.+)`, 'm');
      const m = block.match(re);
      return m ? m[1].trim() : '';
    };

    const uid      = get('UID');
    const summary  = get('SUMMARY');
    const dtstart  = get('DTSTART');
    const dtend    = get('DTEND') || get('DTEND;VALUE=DATE');
    const location = get('LOCATION');
    const desc     = get('DESCRIPTION').replace(/\\n/g, ' ').replace(/\\,/g, ',');

    const startIso = parseIcsDate(dtstart);
    const endIso   = parseIcsDate(dtend);

    if (!startIso) continue;

    const startTs = new Date(startIso).getTime();
    if (startTs < minTs || startTs > maxTs) continue;

    events.push({
      id: uid || `ics-${startIso}-${Math.random().toString(36).slice(2, 7)}`,
      title: summary || '(Kein Titel)',
      start: startIso,
      end: endIso || startIso,
      source,
      location: location.replace(/\\,/g, ','),
      description: desc,
      attendees: [],
    });
  }

  return events;
}

// ─── Route handler ────────────────────────────────────────────────────────────

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const icsUrl   = searchParams.get('url');
  const lookBack = parseInt(searchParams.get('lookBack') || '7',  10);
  const lookAhead= parseInt(searchParams.get('lookAhead') || '30', 10);

  if (!icsUrl) {
    return NextResponse.json({ events: [], error: 'Missing ?url= parameter' }, { status: 400 });
  }

  let decoded: string;
  try {
    decoded = decodeURIComponent(icsUrl);
  } catch {
    return NextResponse.json({ events: [], error: 'Invalid URL encoding' }, { status: 400 });
  }

  // Split multiple URLs separated by commas or semicolons
  const urls = decoded
    .split(/[;,]/)
    .map(url => url.trim())
    .filter(url => /^https?:\/\//i.test(url));

  if (urls.length === 0) {
    return NextResponse.json({ events: [], error: 'No valid HTTP/HTTPS URLs found' }, { status: 400 });
  }

  const allEvents: ParsedEvent[] = [];
  const errors: string[] = [];

  // Fetch all calendars in parallel
  await Promise.all(
    urls.map(async (url) => {
      try {
        const isGoogle = url.toLowerCase().includes('google.com');
        const source: 'google' | 'outlook' = isGoogle ? 'google' : 'outlook';

        const res = await fetch(url, {
          headers: {
            'User-Agent': 'ArchonCRM-CalendarSync/1.0',
            'Accept': 'text/calendar, */*',
          },
          signal: AbortSignal.timeout(8000),
          cache: 'no-store',
        });

        if (!res.ok) {
          errors.push(`${url}: HTTP ${res.status}`);
          return;
        }

        const text = await res.text();
        if (!text.includes('BEGIN:VCALENDAR')) {
          errors.push(`${url}: Invalid ICS file`);
          return;
        }

        const parsed = parseIcs(text, lookBack, lookAhead, source);
        allEvents.push(...parsed);
      } catch (err: any) {
        errors.push(`${url}: ${err?.message || String(err)}`);
      }
    })
  );

  // Sort events chronologically
  allEvents.sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime());

  // Return success even if only some URLs succeeded, but add errors list
  return NextResponse.json({
    events: allEvents,
    count: allEvents.length,
    source: 'ics-multiple',
    errors: errors.length > 0 ? errors : undefined
  });
}
