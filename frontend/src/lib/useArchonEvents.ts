'use client';

/**
 * Ein gemeinsamer SSE-Bus für die gesamte Next.js-App.
 *
 * Vorher hatte frontend/src KEINEN EventSource — alle drei Cockpits luden
 * genau einmal und mussten manuell aktualisiert werden. HITL-Gates, DAG-
 * Knoten und Asset-Status blieben daher unbemerkt. Der FastAPI-Bus
 * `/api/v1/events/stream` wird über den Archon-Proxy erreicht.
 */
import { useEffect, useRef, useState } from 'react';
import {
  createTraceparent,
  forkActiveTraceparent,
  getArchonTracestate,
  setArchonTraceparent,
  setArchonTracestate,
} from './archon-api';

export type ArchonEvent = {
  type: string;
  timestamp?: number;
  data?: Record<string, unknown>;
};

type Listener = (event: ArchonEvent) => void;

const listeners = new Set<Listener>();
let source: EventSource | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let attempts = 0;
let generation = 0;

const EVENTS_URL = '/api/archon/api/v1/events/stream';

/**
 * D16: EventSource kann keine custom Header senden. Der W3C-Root wird daher
 * als Query-Param übergeben und vom Archon-Proxy validiert/geforkt (echo).
 */
function tracedEventsUrl(): string {
  const url = new URL(EVENTS_URL, window.location.origin);
  // SSE-Reconnects forken den letzten empfangenen Kontext statt einen
  // zweiten Root zu erzeugen (S-16.5: ein Root pro Systemeintritt).
  const forked = forkActiveTraceparent();
  if (forked) url.searchParams.set('traceparent', forked);
  else url.searchParams.set('traceparent', createTraceparent());
  const tracestate = getArchonTracestate();
  if (tracestate) url.searchParams.set('tracestate', tracestate);
  return `${url.pathname}${url.search}`;
}

function connect(gen: number) {
  if (typeof window === 'undefined' || source) return;
  try {
    source = new EventSource(tracedEventsUrl());
    source.onopen = () => {
      attempts = 0;
    };
    source.onmessage = (msg) => {
      if (!msg.data || msg.data.startsWith(':')) return;
      try {
        const parsed = JSON.parse(msg.data) as ArchonEvent;
        if (!parsed?.type) return;
        // D16/HIGH: SSE-Frames tragen traceparent/tracestate (archon/core/runtime.py).
        // Der Browser uebernimmt ihn als aktiven Kontext; alle Folge-Requests
        // forken daraus statt einen neuen Root zu starten.
        const data = parsed.data || {};
        const frameTp =
          (typeof data.traceparent === 'string' ? data.traceparent : null) ||
          (typeof (parsed as Record<string, unknown>).traceparent === 'string'
            ? (parsed as Record<string, unknown>).traceparent as string
            : null);
        if (frameTp) setArchonTraceparent(frameTp);
        const frameTs =
          (typeof data.tracestate === 'string' ? data.tracestate : null) ||
          (typeof (parsed as Record<string, unknown>).tracestate === 'string'
            ? (parsed as Record<string, unknown>).tracestate as string
            : null);
        if (frameTs) setArchonTracestate(frameTs);
        for (const fn of listeners) {
          try { fn(parsed); } catch { /* listener failure must not kill the bus */ }
        }
        // Globales CustomEvent für Komponenten ohne Hook (z. B. Legacy-Code)
        window.dispatchEvent(new CustomEvent('archon:sse', { detail: parsed }));
      } catch { /* ignore malformed frames */ }
    };
    source.onerror = () => {
      source?.close();
      source = null;
      // KRITISCH (Audit 23.11.2026): ein Generationswechsel (zweiter Mount /
      // React-StrictMode) darf die Rekonektion NIEMALS dauerhaft beenden.
      // Immer die aktuelle Generation verwenden.
      attempts += 1;
      const delay = Math.min(30_000, 1_000 * 2 ** Math.min(attempts, 5));
      if (reconnectTimer) clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(() => connect(generation), delay);
    };
  } catch {
    source = null;
  }
}

/** Registered a single shared EventSource for the whole app. */
export function useArchonEvents(listener?: Listener) {
  const listenerRef = useRef(listener);
  listenerRef.current = listener;
  const [, force] = useState(0);

  useEffect(() => {
    generation += 1;
    if (listenerRef.current) {
      const wrapped: Listener = (e) => listenerRef.current?.(e);
      listeners.add(wrapped);
      connect(generation);
      // Auch mit Listener muss ein versteckter/abgebrochener Stream beim
      // Sichtbarwerden wiederhergestellt werden.
      const onVisible = () => {
        if (document.visibilityState === 'visible' && !source) connect(generation);
      };
      document.addEventListener('visibilitychange', onVisible);
      return () => {
        listeners.delete(wrapped);
        document.removeEventListener('visibilitychange', onVisible);
      };
    }
    connect(generation);
    // Reconnect-Pruefung beim Sichtbarwerden des Tabs
    const onVisible = () => {
      if (document.visibilityState === 'visible' && !source) connect(generation);
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, []);

  return {
    /** Letztes Update-Zeichen (zum expliziten Re-Render). */
    touch: () => force((n) => n + 1),
  };
}
