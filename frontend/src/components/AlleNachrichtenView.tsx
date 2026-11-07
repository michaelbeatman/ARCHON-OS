"use client";

import React, { useState, useEffect, useMemo } from 'react';
import { pb, KontaktRecord, getProfilbildUrl } from '@/lib/pocketbase';
import {
  MessageSquare, Mail, Mic, FileText, Link2, ChevronDown, ChevronUp,
  Search, Users, RefreshCw, Calendar, Inbox, Send, ArrowDownUp
} from 'lucide-react';

interface FlatMessage {
  id: string;
  kontaktId: string;
  kontaktName: string;
  kontaktUnternehmen?: string;
  profilbildUrl: string | null;
  sender: 'user' | 'kontakt' | string;
  channel: string;
  type: string;
  text: string;
  rawTranscript?: string;
  isStarred?: boolean;
  timestamp: string;
  date?: string;
  time?: string;
}

const CHANNEL_META: Record<string, { label: string; Icon: any; color: string; bg: string }> = {
  linkedin: { label: 'LinkedIn', Icon: Link2, color: 'text-[#0A66C2]', bg: 'bg-[#E0F2FE]' },
  email: { label: 'E-Mail', Icon: Mail, color: 'text-amber-600', bg: 'bg-amber-100' },
  meeting: { label: 'Meeting', Icon: Mic, color: 'text-rose-600', bg: 'bg-rose-100' },
  audio: { label: 'Audio-Diktat', Icon: Mic, color: 'text-rose-600', bg: 'bg-rose-100' },
  note: { label: 'Notiz', Icon: FileText, color: 'text-emerald-600', bg: 'bg-emerald-100' },
};

function normalizeChannel(channel?: string, type?: string, text?: string): string {
  const c = (channel || type || '').toLowerCase();
  if (c.includes('link')) return 'linkedin';
  if (c.includes('mail') || c.includes('email')) return 'email';
  if (c.includes('meet') || c.includes('audio')) return 'meeting';
  if (c.includes('note') || c.includes('notiz')) return 'note';
  if (text && (text.includes('NOTIZ') || text.includes('NACHTRAG'))) return 'note';
  return 'linkedin';
}

function senderLabel(sender: string, kontaktName: string): { name: string; isUser: boolean } {
  const s = (sender || '').toLowerCase();
  if (s === 'user' || s === 'ich' || s === 'me' || s === 'michael keller') {
    return { name: 'Michael Keller', isUser: true };
  }
  if (s === 'contact' || s === 'kontakt' || !s) {
    return { name: kontaktName, isUser: false };
  }
  return { name: sender, isUser: false };
}

function parseMessageTimestamp(m: any, fallback?: string): string {
  if (m.timestamp) {
    const rawTs = String(m.timestamp).trim();
    if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC$/.test(rawTs)) {
      return rawTs.replace(' UTC', 'Z').replace(' ', 'T');
    }
    if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(rawTs)) {
      return rawTs.replace(' ', 'T') + (rawTs.length === 16 ? ':00' : '');
    }
    return rawTs;
  }
  const raw = m.date ? (m.time ? `${m.date} ${m.time}` : m.date) : (m.time || '');
  if (raw) {
    const trimmed = String(raw).trim();
    if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC$/.test(trimmed)) {
      return trimmed.replace(' UTC', 'Z').replace(' ', 'T');
    }
    if (/^\d{4}-\d{2}-\d{2}/.test(trimmed)) {
      return trimmed.replace(' ', 'T') + (trimmed.length === 16 ? ':00' : '');
    }
    const dm = trimmed.match(/^(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2}))?/);
    if (dm) {
      return `${dm[3]}-${dm[2]}-${dm[1]}T${dm[4] || '00'}:${dm[5] || '00'}:00`;
    }
  }
  return fallback || '';
}

function parseDateObject(ts?: string, date?: string): Date | null {
  if (ts) {
    const rawTs = String(ts).trim();
    let d = new Date(rawTs);
    if (isNaN(d.getTime())) {
      if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC$/.test(rawTs)) {
        d = new Date(rawTs.replace(' UTC', 'Z').replace(' ', 'T'));
      } else if (/^\d{4}-\d{2}-\d{2}/.test(rawTs)) {
        d = new Date(rawTs.replace(' ', 'T'));
      }
    }
    if (!isNaN(d.getTime())) return d;
  }
  if (date) {
    const raw = String(date).trim();
    if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC$/.test(raw)) {
      const d = new Date(raw.replace(' UTC', 'Z').replace(' ', 'T'));
      if (!isNaN(d.getTime())) return d;
    }
    if (/^\d{4}-\d{2}-\d{2}/.test(raw)) {
      const iso = raw.replace(' ', 'T') + (raw.length === 16 ? ':00' : (raw.length === 10 ? 'T00:00:00' : ''));
      const d = new Date(iso);
      if (!isNaN(d.getTime())) return d;
    }
    const dm = raw.match(/^(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2}))?/);
    if (dm) {
      return new Date(Number(dm[3]), Number(dm[2]) - 1, Number(dm[1]), Number(dm[4] || 0), Number(dm[5] || 0));
    }
  }
  return null;
}

function formatDateTime(ts: string | undefined, date?: string, time?: string): string {
  if (date && time) {
    return `${date} ${time}`;
  }
  const d = parseDateObject(ts, date);
  if (!d) return date || ts || '';
  return d.toLocaleString('de-DE', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit'
  });
}

// Liefert den Datums-Schlüssel (YYYY-MM-DD) für die Tag-Gruppierung.
function dayKey(ts?: string, date?: string): string {
  const d = parseDateObject(ts, date);
  if (d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  }
  return '';
}

// Relative Zeitangabe: "Heute", "Gestern", "vor 1 Woche", "vor 2 Wochen"...
function relativeTime(ts?: string, date?: string): string {
  const d = parseDateObject(ts, date);
  if (!d || isNaN(d.getTime())) return '';

  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const day = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diffDays = Math.round((today.getTime() - day.getTime()) / 86400000);

  if (diffDays <= 0) return 'Heute';
  if (diffDays === 1) return 'Gestern';
  if (diffDays < 7) return `vor ${diffDays} Tagen`;
  const weeks = Math.floor(diffDays / 7);
  return weeks === 1 ? 'vor 1 Woche' : `vor ${weeks} Wochen`;
}

// Deutsches Datum für die Trennleiste: "Montag, 11. August 2026"
function formatDayHeader(ts?: string, date?: string): string {
  const d = parseDateObject(ts, date);
  if (!d || isNaN(d.getTime())) return date || (ts || '').substring(0, 10);
  return d.toLocaleDateString('de-DE', {
    weekday: 'long', day: '2-digit', month: 'long', year: 'numeric'
  });
}

interface AlleNachrichtenViewProps {
  themeMode?: 'light' | 'dark';
  kontakte: KontaktRecord[];
  loading?: boolean;
  onOpenKontakt?: (id: string) => void;
}

export function AlleNachrichtenView({
  themeMode = 'light',
  kontakte,
  loading = false,
  onOpenKontakt
}: AlleNachrichtenViewProps) {
  const isLight = themeMode === 'light';

  const [searchTerm, setSearchTerm] = useState('');
  const [channelFilter, setChannelFilter] = useState<string>('all');
  const [senderFilter, setSenderFilter] = useState<'all' | 'inbound' | 'outbound'>('all');
  const [direction, setDirection] = useState<'desc' | 'asc'>('desc');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Alle Nachrichten aus allen Kontakten flach sammeln
  const allMessages = useMemo<FlatMessage[]>(() => {
    const flat: FlatMessage[] = [];
    for (const k of kontakte) {
      const nv = k.nachrichtenverlauf;
      if (!nv) continue;
      let list: any[] = [];
      if (Array.isArray(nv)) list = nv;
      else if (typeof nv === 'string') {
        try { const p = JSON.parse(nv); if (Array.isArray(p)) list = p; } catch { /* ignore */ }
      }
      for (const m of list) {
        if (!m || typeof m !== 'object') continue;
        const text = (m.text || '').trim();
        if (!text) continue;
        const ts = parseMessageTimestamp(m, k.updated || k.created);
        flat.push({
          id: m.id || `${k.id}_${flat.length}_${ts}`,
          kontaktId: k.id,
          kontaktName: k.name || 'Unbekannt',
          kontaktUnternehmen: k.unternehmen,
          profilbildUrl: getProfilbildUrl(k),
          sender: m.sender || 'contact',
          channel: normalizeChannel(m.channel, m.type, text),
          type: m.type || m.channel || 'linkedin',
          text,
          rawTranscript: m.rawTranscript,
          isStarred: !!m.isStarred,
          timestamp: ts,
          date: m.date,
          time: m.time,
        });
      }
    }
    return flat;
  }, [kontakte]);

  // Sortieren: neueste zuerst (desc) oder älteste zuerst (asc)
  const sorted = useMemo(() => {
    const list = [...allMessages];
    list.sort((a, b) => {
      const ta = new Date(a.timestamp || 0).getTime();
      const tb = new Date(b.timestamp || 0).getTime();
      return direction === 'desc' ? tb - ta : ta - tb;
    });
    return list;
  }, [allMessages, direction]);

  // Filtern
  const filtered = useMemo(() => {
    return sorted.filter((m) => {
      const matchesSearch =
        !searchTerm ||
        m.kontaktName.toLowerCase().includes(searchTerm.toLowerCase()) ||
        m.text.toLowerCase().includes(searchTerm.toLowerCase()) ||
        (m.kontaktUnternehmen || '').toLowerCase().includes(searchTerm.toLowerCase());
      const matchesChannel = channelFilter === 'all' || m.channel === channelFilter;

      const senderInfo = senderLabel(m.sender, m.kontaktName);
      const matchesSender =
        senderFilter === 'all' ||
        (senderFilter === 'inbound' && !senderInfo.isUser) ||
        (senderFilter === 'outbound' && senderInfo.isUser);

      return matchesSearch && matchesChannel && matchesSender;
    });
  }, [sorted, searchTerm, channelFilter, senderFilter]);

  const senderCounts = useMemo(() => {
    let inbound = 0;
    let outbound = 0;
    for (const m of allMessages) {
      const isUser = senderLabel(m.sender, m.kontaktName).isUser;
      if (isUser) outbound++;
      else inbound++;
    }
    return { all: allMessages.length, inbound, outbound };
  }, [allMessages]);

  const channelCounts = useMemo(() => {
    const counts: Record<string, number> = { all: allMessages.length };
    for (const m of allMessages) {
      counts[m.channel] = (counts[m.channel] || 0) + 1;
    }
    return counts;
  }, [allMessages]);

  const getChannelMeta = (ch: string) => {
    return CHANNEL_META[ch] || { label: ch, Icon: MessageSquare, color: 'text-slate-500', bg: 'bg-slate-100' };
  };

  return (
    <div className="h-full flex flex-col min-h-0">
      {/* HEADER: Suche + Filter */}
      <div className="flex flex-wrap items-center gap-2 pb-4 shrink-0">
        <div className={`flex items-center gap-2 px-3 py-2 rounded-xl border flex-1 min-w-[220px] ${
          isLight ? 'bg-white border-slate-200' : 'bg-slate-900 border-slate-800'
        }`}>
          <Search className="w-4 h-4 text-slate-400 shrink-0" />
          <input
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Nachrichten durchsuchen (Name, Text, Firma)..."
            className="bg-transparent text-xs font-semibold focus:outline-none w-full placeholder:text-slate-400"
          />
        </div>

        <button
          type="button"
          onClick={() => setDirection(d => d === 'desc' ? 'asc' : 'desc')}
          className={`px-3 py-2 rounded-xl border text-xs font-bold flex items-center gap-1.5 transition cursor-pointer ${
            isLight ? 'bg-white border-slate-200 text-slate-600 hover:bg-slate-50' : 'bg-slate-900 border-slate-800 text-slate-300 hover:bg-slate-800'
          }`}
          title={direction === 'desc' ? 'Neueste zuerst (aktuell)' : 'Älteste zuerst (aktuell)'}
        >
          <ArrowDownUp className="w-3.5 h-3.5" />
          {direction === 'desc' ? 'Neueste zuerst' : 'Älteste zuerst'}
        </button>

        {/* Sender Filter: Alle / Erhalten (Inbound) / Gesendet (Outbound) */}
        <div className={`flex items-center gap-1 px-1.5 py-1 rounded-xl border ${isLight ? 'bg-white border-slate-200' : 'bg-slate-900 border-slate-800'}`}>
          <button
            type="button"
            onClick={() => setSenderFilter('all')}
            className={`px-2.5 py-1.5 rounded-lg text-[11px] font-bold transition cursor-pointer ${
              senderFilter === 'all'
                ? isLight ? 'bg-accent-soft text-accent-main' : 'bg-accent-light text-accent-main'
                : isLight ? 'text-slate-500 hover:bg-slate-100' : 'text-slate-400 hover:bg-slate-800'
            }`}
            title="Alle Nachrichten anzeigen"
          >
            Alle ({senderCounts.all || 0})
          </button>
          <button
            type="button"
            onClick={() => setSenderFilter('inbound')}
            className={`px-2.5 py-1.5 rounded-lg text-[11px] font-bold transition cursor-pointer flex items-center gap-1.5 ${
              senderFilter === 'inbound'
                ? isLight ? 'bg-emerald-100 text-emerald-800 font-black' : 'bg-emerald-950/80 text-emerald-300 border border-emerald-700/60 font-black'
                : isLight ? 'text-slate-600 hover:bg-slate-100' : 'text-slate-400 hover:bg-slate-800'
            }`}
            title="Nur erhaltene Nachrichten anzeigen (von Kontakten geschrieben oder geantwortet)"
          >
            <Inbox className="w-3.5 h-3.5 text-emerald-500" />
            <span>Erhalten ({senderCounts.inbound || 0})</span>
          </button>
          <button
            type="button"
            onClick={() => setSenderFilter('outbound')}
            className={`px-2.5 py-1.5 rounded-lg text-[11px] font-bold transition cursor-pointer flex items-center gap-1.5 ${
              senderFilter === 'outbound'
                ? isLight ? 'bg-accent-soft text-accent-main' : 'bg-accent-light text-accent-main'
                : isLight ? 'text-slate-500 hover:bg-slate-100' : 'text-slate-400 hover:bg-slate-800'
            }`}
            title="Nur gesendete Nachrichten anzeigen"
          >
            <Send className="w-3.5 h-3.5" />
            <span>Gesendet ({senderCounts.outbound || 0})</span>
          </button>
        </div>

        <div className={`flex items-center gap-1 px-1.5 py-1 rounded-xl border ${isLight ? 'bg-white border-slate-200' : 'bg-slate-900 border-slate-800'}`}>
          <button
            type="button"
            onClick={() => setChannelFilter('all')}
            className={`px-2.5 py-1.5 rounded-lg text-[11px] font-bold transition cursor-pointer ${
              channelFilter === 'all'
                ? isLight ? 'bg-accent-soft text-accent-main' : 'bg-accent-light text-accent-main'
                : isLight ? 'text-slate-500 hover:bg-slate-100' : 'text-slate-400 hover:bg-slate-800'
            }`}
          >
            Alle ({channelCounts.all || 0})
          </button>
          {Object.entries(CHANNEL_META).map(([ch, meta]) => (
            <button
              key={ch}
              type="button"
              onClick={() => setChannelFilter(ch)}
              className={`px-2.5 py-1.5 rounded-lg text-[11px] font-bold transition cursor-pointer flex items-center gap-1 ${
                channelFilter === ch
                  ? isLight ? 'bg-accent-soft text-accent-main' : 'bg-accent-light text-accent-main'
                  : isLight ? 'text-slate-500 hover:bg-slate-100' : 'text-slate-400 hover:bg-slate-800'
              }`}
            >
              <meta.Icon className="w-3 h-3" />
              {meta.label} ({channelCounts[ch] || 0})
            </button>
          ))}
        </div>
      </div>

      {/* NACHRICHTEN-LISTE */}
      {loading ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 text-slate-400">
          <RefreshCw className="w-6 h-6 animate-spin text-accent-main" />
          <p className="text-xs font-mono font-semibold">Sammle alle Nachrichten...</p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 text-slate-400">
          <Inbox className="w-10 h-10" />
          <p className="text-xs font-semibold">Keine Nachrichten gefunden.</p>
          <p className="text-[11px] text-slate-400">Passe Suche oder Filter an.</p>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto space-y-2 pr-1">
          {filtered.map((m, idx) => {
            const meta = getChannelMeta(m.channel);
            const sender = senderLabel(m.sender, m.kontaktName);
            const isExpanded = expandedId === m.id;

            // Tag-Gruppierung: vor jeder Nachricht eines NEUEN Tages eine
            // visuelle Trennleiste mit Datum (links) + relativer Zeit (rechts).
            const prev = idx > 0 ? filtered[idx - 1] : null;
            const currentDay = dayKey(m.timestamp, m.date);
            const prevDay = prev ? dayKey(prev.timestamp, prev.date) : null;
            const isNewDay = currentDay && currentDay !== prevDay;

            return (
              <React.Fragment key={m.id}>
              {isNewDay && (
                <div className="flex items-center gap-3 pt-2 pb-1 select-none">
                  <div className={`flex-1 h-px ${isLight ? 'bg-slate-300' : 'bg-slate-700'}`} />
                  <div className={`px-3 py-1 rounded-full border text-[11px] font-bold whitespace-nowrap ${
                    isLight
                      ? 'bg-white border-slate-300 text-slate-700'
                      : 'bg-slate-900 border-slate-700 text-slate-200'
                  }`}>
                    {formatDayHeader(m.timestamp, m.date)}
                  </div>
                  <div className={`px-2.5 py-1 rounded-full text-[10px] font-bold whitespace-nowrap ${
                    isLight ? 'bg-accent-soft text-accent-main' : 'bg-accent-light text-accent-main'
                  }`}>
                    {relativeTime(m.timestamp, m.date)}
                  </div>
                  <div className={`flex-1 h-px ${isLight ? 'bg-slate-300' : 'bg-slate-700'}`} />
                </div>
              )}
              <div
                className={`rounded-xl border p-3 transition ${
                  isLight ? 'bg-white border-slate-200 hover:border-slate-300' : 'bg-slate-900 border-slate-800 hover:border-slate-700'
                }`}
              >
                <div className="flex items-start gap-3">
                  {/* Avatar */}
                  <button
                    type="button"
                    onClick={() => onOpenKontakt && onOpenKontakt(m.kontaktId)}
                    className="w-10 h-10 rounded-full border border-slate-200 dark:border-slate-700 overflow-hidden shrink-0 cursor-pointer hover:ring-2 hover:ring-accent-main transition"
                    title={`Kontakt öffnen: ${m.kontaktName}`}
                  >
                    {m.profilbildUrl ? (
                      <img src={m.profilbildUrl} alt={m.kontaktName} className="w-full h-full object-cover" />
                    ) : (
                      <div className="w-full h-full bg-slate-200 dark:bg-slate-700 flex items-center justify-center text-xs font-bold text-slate-500">
                        {m.kontaktName.charAt(0).toUpperCase()}
                      </div>
                    )}
                  </button>

                  {/* Inhalt */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <button
                        type="button"
                        onClick={() => onOpenKontakt && onOpenKontakt(m.kontaktId)}
                        className="text-xs font-bold hover:underline cursor-pointer truncate max-w-[200px]"
                      >
                        {m.kontaktName}
                      </button>
                      {m.kontaktUnternehmen && (
                        <span className={`text-[10px] font-semibold ${isLight ? 'text-slate-400' : 'text-slate-500'} truncate max-w-[160px]`}>
                          {m.kontaktUnternehmen}
                        </span>
                      )}
                      <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-bold ${meta.bg} ${meta.color}`}>
                        <meta.Icon className="w-3 h-3" />
                        {meta.label}
                      </span>
                      <span className={`text-[10px] font-mono ${isLight ? 'text-slate-400' : 'text-slate-500'}`}>
                        {formatDateTime(m.timestamp, m.date, m.time)}
                      </span>
                      <span className={`text-[10px] font-bold ${sender.isUser ? 'text-accent-main' : isLight ? 'text-slate-500' : 'text-slate-400'}`}>
                        {sender.isUser ? '→ ' : '← '}{sender.name}
                      </span>
                    </div>

                    {/* Textvorschau / voller Text */}
                    <p className={`mt-1 text-xs leading-relaxed whitespace-pre-wrap break-words ${
                      isExpanded ? '' : 'line-clamp-2'
                    } ${isLight ? 'text-slate-700' : 'text-slate-300'}`}>
                      {m.text}
                    </p>

                    {(m.rawTranscript || (m.text && m.text.length > 160)) && (
                      <button
                        type="button"
                        onClick={() => setExpandedId(isExpanded ? null : m.id)}
                        className="mt-1.5 inline-flex items-center gap-1 text-[10px] font-bold text-accent-main hover:underline cursor-pointer"
                      >
                        {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                        {isExpanded ? 'Einklappen' : 'Vollständig anzeigen'}
                      </button>
                    )}
                  </div>
                </div>
              </div>
              </React.Fragment>
            );
          })}
        </div>
      )}
    </div>
  );
}
