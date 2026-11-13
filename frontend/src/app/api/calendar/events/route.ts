import { NextResponse } from 'next/server';

/**
 * GET /api/calendar/events
 *
 * Aggregates events from Google Calendar + Outlook (via the Python backend
 * at CALENDAR_AGGREGATOR_URL, default: http://localhost:8421/events).
 *
 * Falls back to empty array with status 503 when the Python aggregator
 * is not running, so the frontend can show its mock-data banner instead
 * of crashing.
 */
export async function GET() {
  const aggregatorUrl = process.env.CALENDAR_AGGREGATOR_URL || 'http://localhost:8421/events';

  try {
    const res = await fetch(aggregatorUrl, {
      next: { revalidate: 60 }, // cache 60 s
      signal: AbortSignal.timeout(5000), // 5 s timeout
    });

    if (!res.ok) {
      return NextResponse.json(
        { events: [], error: `Aggregator returned ${res.status}` },
        { status: 503 }
      );
    }

    const data = await res.json();
    return NextResponse.json({ events: data.events || [] });
  } catch (err: any) {
    // Aggregator not running — expected during initial setup
    return NextResponse.json(
      { events: [], error: 'Calendar aggregator not reachable' },
      { status: 503 }
    );
  }
}

export async function POST(req: Request) {
  const aggregatorUrl = (process.env.CALENDAR_AGGREGATOR_URL || 'http://localhost:8421/events')
    .replace('/events', '/create-google-event');

  try {
    const body = await req.json();
    const res = await fetch(aggregatorUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(10000),
    });

    const data = await res.json();
    if (!res.ok) {
      return NextResponse.json(
        { success: false, error: data.error || `Aggregator returned status ${res.status}` },
        { status: res.status }
      );
    }
    return NextResponse.json(data);
  } catch (err: any) {
    return NextResponse.json(
      { success: false, error: err?.message || 'Calendar aggregator not reachable' },
      { status: 503 }
    );
  }
}
