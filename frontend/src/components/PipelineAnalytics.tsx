"use client";

import React from 'react';
import { AlertCircle, Clock } from 'lucide-react';
import { KontaktRecord } from '@/lib/pocketbase';

/**
 * Berechnet die Tage seit der letzten Aktivität / Nachricht eines Kontakts.
 */
export function getInactiveDays(kontakt: Partial<KontaktRecord>): number {
  const now = new Date().getTime();
  let latestTimestamp = 0;

  // 1. Nachrichtenverlauf prüfen
  if (kontakt.nachrichtenverlauf) {
    try {
      const messages = Array.isArray(kontakt.nachrichtenverlauf)
        ? kontakt.nachrichtenverlauf
        : typeof kontakt.nachrichtenverlauf === 'string'
        ? JSON.parse(kontakt.nachrichtenverlauf)
        : [];

      if (Array.isArray(messages)) {
        for (const msg of messages) {
          const t = msg.timestamp || msg.date || msg.created || msg.gesendet_am;
          if (t) {
            const parsed = new Date(t).getTime();
            if (!isNaN(parsed) && parsed > latestTimestamp) {
              latestTimestamp = parsed;
            }
          }
        }
      }
    } catch {}
  }

  // 2. Updated-Datum als Fallback
  if (!latestTimestamp && kontakt.updated) {
    const parsed = new Date(kontakt.updated).getTime();
    if (!isNaN(parsed) && parsed > latestTimestamp) {
      latestTimestamp = parsed;
    }
  }

  // 3. Vernetzt_am als weiterer Fallback
  if (!latestTimestamp && kontakt.vernetzt_am) {
    const parsed = new Date(kontakt.vernetzt_am).getTime();
    if (!isNaN(parsed) && parsed > latestTimestamp) {
      latestTimestamp = parsed;
    }
  }

  // 4. Created als finaler Fallback
  if (!latestTimestamp && kontakt.created) {
    const parsed = new Date(kontakt.created).getTime();
    if (!isNaN(parsed) && parsed > latestTimestamp) {
      latestTimestamp = parsed;
    }
  }

  if (!latestTimestamp) return 0;

  const diffMs = now - latestTimestamp;
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  return Math.max(0, diffDays);
}

/**
 * Prüft ob ein Kontakt in der aktiven Pipeline stagniert (> 14 Tage inaktiv).
 */
export function isContactStagnated(kontakt: Partial<KontaktRecord>, thresholdDays = 14): boolean {
  // Nicht prüfen bei abgeschlossenen oder archivierten Status
  const nonStagnatingStatuses = ['Unvernetzt', 'Parkposition', 'Pool', 'Gesperrt_1Jahr', 'Kein_Interesse'];
  if (!kontakt.status || nonStagnatingStatuses.includes(kontakt.status)) {
    return false;
  }

  return getInactiveDays(kontakt) >= thresholdDays;
}

/**
 * Optischer Indikator für stagnierende Kontakte auf Kanban-Karten & Tabellen.
 */
export function StagnationBadge({ days, isLight = false }: { days: number; isLight?: boolean }) {
  if (days < 14) return null;

  return (
    <div
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold border tracking-tight animate-in fade-in select-none ${
        isLight
          ? 'bg-rose-50 border-rose-200 text-rose-700'
          : 'bg-rose-950/40 border-rose-800/60 text-rose-300'
      }`}
      title={`Letzte Interaktion vor ${days} Tagen. Handlungsbedarf empfohlen.`}
    >
      <Clock className="w-2.5 h-2.5 shrink-0 text-rose-500" />
      <span>Seit &gt;{days}T inaktiv</span>
    </div>
  );
}
