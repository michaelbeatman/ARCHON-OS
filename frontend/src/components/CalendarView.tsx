"use client";

import React, { useState, useEffect, useCallback } from 'react';
import {
  ChevronLeft, ChevronRight, Calendar, Plus, X, Clock,
  Video, MapPin, Users, Loader2, RefreshCw, ExternalLink,
  Trash2, Search, Image as ImageIcon, AlignLeft
} from 'lucide-react';
import { pb } from '@/lib/pocketbase';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface CalendarEvent {
  id: string;
  title: string;
  start: string;       // ISO 8601
  end: string;         // ISO 8601
  source: 'google' | 'outlook' | 'crm';
  location?: string;
  attendees?: string[];
  description?: string;
  color?: string;
  kontaktId?: string;      // verknüpfter CRM-Kontakt
  kontaktName?: string;    // Anzeige-Name des Kontakts
  kontaktBild?: string | null;  // Profilbild-URL des verknüpften Kontakts
}

type CalView = 'twoweeks' | 'week' | 'month';
type SourceFilter = 'all' | 'google' | 'outlook' | 'crm';

interface CalendarViewProps {
  themeMode?: 'light' | 'dark';
}

interface Kontakt {
  id: string;
  name?: string;
  profilbild?: string;
  unternehmen?: string;
  email?: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const DAYS_DE = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
const MONTHS_DE = [
  'Januar', 'Februar', 'März', 'April', 'Mai', 'Juni',
  'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember'
];

function startOfWeek(date: Date): Date {
  const d = new Date(date);
  const day = d.getDay(); // 0 = Sun
  const diff = day === 0 ? -6 : 1 - day; // Monday-based week
  d.setDate(d.getDate() + diff);
  d.setHours(0, 0, 0, 0);
  return d;
}

function addDays(date: Date, n: number): Date {
  const d = new Date(date);
  d.setDate(d.getDate() + n);
  return d;
}

function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate();
}

const DAYS_FULL_DE = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag'];

function getISOWeek(d: Date): number {
  const date = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const dayNum = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
  const weekNo = Math.ceil((((date.getTime() - yearStart.getTime()) / 86400000) + 1) / 7);
  return weekNo;
}

function eventColor(source: CalendarEvent['source']): string {
  switch (source) {
    case 'google':  return 'event-google';
    case 'outlook': return 'event-outlook';
    case 'crm':     return 'event-crm';
    default:        return 'bg-zinc-600 border-zinc-700 text-white';
  }
}

function eventDot(source: CalendarEvent['source']): string {
  switch (source) {
    case 'google':  return 'event-google';
    case 'outlook': return 'event-outlook';
    case 'crm':     return 'event-crm';
    default:        return 'bg-zinc-500';
  }
}

function formatTime(iso: string): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
  } catch { return ''; }
}

function formatDateDE(iso: string): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
  } catch { return iso; }
}

/** Kontakt-Profilbild-URL bauen (Fallback: null → Initialen-Avatar) */
function kontaktBildUrl(k: Kontakt | null | undefined): string | null {
  if (!k) return null;
  try {
    if (k.profilbild) return pb.files.getURL(k as any, 'profilbild', { thumb: '100x100' });
  } catch { /* ignore */ }
  return null;
}

/** Initialen aus Name */
function initials(name?: string): string {
  if (!name) return '?';
  const parts = name.trim().split(/\s+/);
  const a = parts[0]?.[0] || '';
  const b = parts.length > 1 ? parts[parts.length - 1][0] : '';
  return (a + b).toUpperCase();
}

// ─── New Event Modal (mit Kontakt-Auswahl + Bild) ─────────────────────────────

interface NewEventModalProps {
  onClose: () => void;
  onSave: (ev: Omit<CalendarEvent, 'id'>) => Promise<void>;
  isLight: boolean;
  kontakte: Kontakt[];
}

function NewEventModal({ onClose, onSave, isLight, kontakte }: NewEventModalProps) {
  const today = new Date();
  const todayLocal = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}T${String(today.getHours()).padStart(2, '0')}:00`;
  const [title, setTitle] = useState('');
  const [start, setStart] = useState(todayLocal);
  const [end, setEnd] = useState(todayLocal);
  const [location, setLocation] = useState('');
  const [description, setDescription] = useState('');
  const [kontaktId, setKontaktId] = useState('');
  const [kontaktSearch, setKontaktSearch] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const filteredKontakte = kontakte
    .filter(k => {
      const q = kontaktSearch.toLowerCase();
      if (!q) return true;
      return (k.name || '').toLowerCase().includes(q) || (k.unternehmen || '').toLowerCase().includes(q);
    })
    .slice(0, 30);

  const selectedKontakt = kontakte.find(k => k.id === kontaktId);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    setSaving(true);
    setError('');
    try {
      await onSave({
        title: title.trim(),
        start: new Date(start).toISOString(),
        end: new Date(end).toISOString(),
        source: 'crm',
        location: location.trim() || undefined,
        description: description.trim() || undefined,
        kontaktId: kontaktId || undefined,
        kontaktName: selectedKontakt?.name || undefined,
      });
      onClose();
    } catch (err: any) {
      setError(`Speichern fehlgeschlagen: ${err?.message || 'Fehler'}`);
    } finally {
      setSaving(false);
    }
  };

  const inputCls = `w-full p-2.5 rounded-xl border text-xs font-sans transition focus:outline-none focus:ring-2 focus:ring-emerald-500 ${
    isLight
      ? 'bg-zinc-50 border-zinc-300 text-zinc-900 placeholder:text-zinc-400'
      : 'bg-zinc-950 border-zinc-700 text-zinc-100 placeholder:text-zinc-600'
  }`;
  const labelCls = `block text-[11px] font-bold mb-1 ${isLight ? 'text-zinc-600' : 'text-zinc-400'}`;

  return (
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-xs flex items-center justify-center p-4">
      <div className={`w-full max-w-lg rounded-2xl border p-6 shadow-2xl space-y-4 animate-in zoom-in-95 duration-150 max-h-[90vh] overflow-y-auto ${
        isLight ? 'bg-white border-zinc-200 text-zinc-900' : 'bg-zinc-900 border-zinc-800 text-zinc-100'
      }`}>
        <div className="flex items-center justify-between pb-3 border-b border-zinc-200 dark:border-zinc-800">
          <div className="flex items-center gap-2">
            <Calendar className="w-5 h-5 text-emerald-600" />
            <h3 className="font-bold text-sm">Termin eintragen</h3>
          </div>
          <button type="button" onClick={onClose} className="p-1 rounded-lg text-zinc-400 hover:text-zinc-600 transition cursor-pointer">
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className={labelCls}>Titel *</label>
            <input
              required
              type="text"
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder="z. B. Erstgespräch – Max Mustermann"
              className={inputCls}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>Start</label>
              <input type="datetime-local" value={start} onChange={e => setStart(e.target.value)} className={inputCls} />
            </div>
            <div>
              <label className={labelCls}>Ende</label>
              <input type="datetime-local" value={end} onChange={e => setEnd(e.target.value)} className={inputCls} />
            </div>
          </div>

          {/* Kontakt-Auswahl mit Bild */}
          <div>
            <label className={labelCls}>Kontakt (optional)</label>
            {selectedKontakt ? (
              <div className={`flex items-center gap-2.5 p-2 rounded-xl border ${
                isLight ? 'bg-emerald-50 border-emerald-200' : 'bg-emerald-950/30 border-emerald-800/40'
              }`}>
                {kontaktBildUrl(selectedKontakt) ? (
                  <img src={kontaktBildUrl(selectedKontakt)!} alt="" className="w-8 h-8 rounded-full object-cover" />
                ) : (
                  <div className="w-8 h-8 rounded-full bg-emerald-600 text-white text-[10px] font-black flex items-center justify-center">
                    {initials(selectedKontakt.name)}
                  </div>
                )}
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-bold truncate">{selectedKontakt.name}</div>
                  <div className="text-[10px] text-zinc-400 truncate">{selectedKontakt.unternehmen || selectedKontakt.email || '—'}</div>
                </div>
                <button
                  type="button"
                  onClick={() => { setKontaktId(''); setKontaktSearch(''); }}
                  className="p-1 rounded-md text-zinc-400 hover:text-zinc-600 transition cursor-pointer"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ) : (
              <div>
                <div className={`flex items-center gap-2 px-3 py-2 rounded-xl border ${inputCls.split(' ').slice(0, 2).join(' ')}`}>
                  <Search className="w-3.5 h-3.5 text-zinc-400 shrink-0" />
                  <input
                    type="text"
                    value={kontaktSearch}
                    onChange={e => setKontaktSearch(e.target.value)}
                    placeholder="Kontakt suchen (Name, Firma)..."
                    className="w-full bg-transparent text-xs focus:outline-none"
                  />
                </div>
                {filteredKontakte.length > 0 && (
                  <div className={`mt-1 max-h-36 overflow-y-auto rounded-xl border ${
                    isLight ? 'border-zinc-200 bg-white' : 'border-zinc-700 bg-zinc-950'
                  }`}>
                    {filteredKontakte.map(k => (
                      <button
                        key={k.id}
                        type="button"
                        onClick={() => setKontaktId(k.id)}
                        className={`w-full flex items-center gap-2.5 px-3 py-1.5 text-left transition cursor-pointer hover:bg-emerald-500/10 ${
                          isLight ? 'hover:bg-zinc-100' : 'hover:bg-zinc-800'
                        }`}
                      >
                        {kontaktBildUrl(k) ? (
                          <img src={kontaktBildUrl(k)!} alt="" className="w-6 h-6 rounded-full object-cover" />
                        ) : (
                          <div className="w-6 h-6 rounded-full bg-emerald-600 text-white text-[9px] font-black flex items-center justify-center shrink-0">
                            {initials(k.name)}
                          </div>
                        )}
                        <div className="min-w-0">
                          <div className="text-[11px] font-bold truncate">{k.name}</div>
                          <div className="text-[9px] text-zinc-400 truncate">{k.unternehmen || '—'}</div>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          <div>
            <label className={labelCls}>Ort / Link</label>
            <input
              type="text"
              value={location}
              onChange={e => setLocation(e.target.value)}
              placeholder="z. B. Zoom Link, Büro München"
              className={inputCls}
            />
          </div>

          <div>
            <label className={labelCls}>Notiz</label>
            <textarea
              rows={3}
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Agenda, Ansprechpartner, etc."
              className={`${inputCls} resize-none`}
            />
          </div>

          {error && <div className="text-[11px] font-bold text-rose-500">{error}</div>}

          <div className="flex justify-end gap-2 pt-2 border-t border-zinc-200 dark:border-zinc-800">
            <button
              type="button"
              onClick={onClose}
              className={`px-4 py-2 rounded-xl text-xs font-semibold transition cursor-pointer ${
                isLight ? 'bg-zinc-100 text-zinc-700 hover:bg-zinc-200' : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'
              }`}
            >
              Abbrechen
            </button>
            <button
              type="submit"
              disabled={saving}
              className="px-5 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-xs transition shadow-sm cursor-pointer disabled:opacity-50"
            >
              {saving ? 'Speichert...' : 'Termin speichern'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ─── Event Detail Popover (mit Kontakt-Bild) ──────────────────────────────────

function parseCalendarDescription(html: string): string {
  if (!html) return '';
  let text = html
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");

  text = text
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p>/gi, '\n')
    .replace(/<p[^>]*>/gi, '')
    .replace(/<h[1-6][^>]*>/gi, '\n')
    .replace(/<\/h[1-6]>/gi, '\n');

  text = text.replace(/<a\s+[^>]*href=["']([^"']*)["'][^>]*>([\s\S]*?)<\/a>/gi, '$2 ($1)');
  text = text.replace(/<[^>]+>/g, '');
  text = text.replace(/\n{3,}/g, '\n\n');

  return text.trim();
}

function renderDescriptionWithLinks(text: string) {
  if (!text) return "";
  const urlRegex = /(https?:\/\/[^\s]+)/g;
  const parts = text.split(urlRegex);
  return parts.map((part, index) => {
    if (part.match(urlRegex)) {
      return (
        <a
          key={index}
          href={part}
          target="_blank"
          rel="noopener noreferrer"
          className="text-sky-500 hover:underline break-all"
        >
          {part}
        </a>
      );
    }
    return part;
  });
}

interface EventDetailProps {
  event: CalendarEvent;
  onClose: () => void;
  isLight: boolean;
  onDelete?: (ev: CalendarEvent) => Promise<void>;
}

function EventDetail({ event, onClose, isLight, onDelete }: EventDetailProps) {
  const sourceLabel: Record<string, string> = { google: 'Google Kalender', outlook: 'Outlook', crm: 'CRM Termin' };
  const [deleting, setDeleting] = useState(false);

  const handleDelete = async () => {
    if (!onDelete) return;
    if (!confirm('Termin wirklich löschen?')) return;
    setDeleting(true);
    try { await onDelete(event); onClose(); } finally { setDeleting(false); }
  };

  const meetingLink = (() => {
    const descMatch = (event.description || '').match(/https:\/\/(teams\.microsoft\.com|meet\.google\.com|zoom\.us|teams\.live\.com)\/[^\s"'>]+/);
    if (descMatch) return descMatch[0];
    if ((event.location || '').startsWith('https://')) return event.location;
    return null;
  })();

  const weekdayStr = (() => {
    try {
      const days = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'];
      const d = new Date(event.start);
      return days[d.getDay()];
    } catch { return ''; }
  })();

  return (
    <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4" onClick={onClose}>
      <div
        className={`w-full max-w-sm rounded-2xl border p-5 shadow-2xl space-y-4 animate-in zoom-in-95 duration-150 ${
          isLight ? 'bg-white border-zinc-200 text-zinc-800' : 'bg-zinc-900 border-zinc-800 text-zinc-100'
        }`}
        onClick={e => e.stopPropagation()}
      >
        {/* Top Header */}
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-bold uppercase tracking-wider text-zinc-400">
            {sourceLabel[event.source] || event.source}
          </span>
          <button type="button" onClick={onClose} className="text-zinc-400 hover:text-zinc-600 transition cursor-pointer">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Title */}
        <h3 className="font-extrabold text-base tracking-tight leading-snug">
          {event.title}
        </h3>

        {/* Prominent Join Button */}
        {meetingLink && (
          <a
            href={meetingLink}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center justify-center gap-2 w-full py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-xs shadow-xs transition cursor-pointer text-center"
          >
            <Video className="w-4 h-4 shrink-0" />
            <span>Beitreten</span>
          </a>
        )}

        {/* Info Rows */}
        <div className="space-y-3 text-xs">
          {/* Time */}
          <div className="flex items-start gap-2.5">
            <Clock className="w-4 h-4 shrink-0 text-zinc-400 mt-0.5" />
            <div className="flex-1">
              <span className="font-semibold text-zinc-700 dark:text-zinc-250">
                {weekdayStr ? `${weekdayStr}, ` : ''}{formatDateDE(event.start)}
              </span>
              <span className="text-zinc-400 mx-1.5">•</span>
              <span className="text-zinc-650 dark:text-zinc-350 font-mono">
                {formatTime(event.start)} – {formatTime(event.end)}
              </span>
            </div>
          </div>

          {/* Location */}
          {event.location && (
            <div className="flex items-start gap-2.5">
              <MapPin className="w-4 h-4 shrink-0 text-zinc-400 mt-0.5" />
              <span className="text-zinc-650 dark:text-zinc-300 flex-1">{event.location}</span>
            </div>
          )}

          {/* Linked Contact */}
          {event.kontaktName && (
            <div className="flex items-center gap-2.5 pt-1.5 border-t border-zinc-100 dark:border-zinc-800/60">
              <div className="w-6 h-6 rounded-full bg-emerald-600 text-white text-[9px] font-black flex items-center justify-center shrink-0 overflow-hidden shadow-inner">
                {event.kontaktBild ? (
                  <img src={event.kontaktBild} alt="" className="w-full h-full object-cover" />
                ) : (
                  initials(event.kontaktName)
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-xs font-semibold truncate leading-none text-zinc-800 dark:text-zinc-200">{event.kontaktName}</div>
                <div className="text-[9px] text-zinc-400 mt-0.5">Verknüpfter CRM-Kontakt</div>
              </div>
            </div>
          )}

          {/* Attendees */}
          {event.attendees && event.attendees.length > 0 && (
            <div className="flex items-start gap-2.5 pt-1.5 border-t border-zinc-100 dark:border-zinc-800/60">
              <Users className="w-4 h-4 shrink-0 text-zinc-400 mt-0.5" />
              <div className="flex-1 min-w-0 text-[11px] text-zinc-650 dark:text-zinc-300">
                <span className="font-bold">Teilnehmer: </span>
                {event.attendees.join(', ')}
              </div>
            </div>
          )}

          {/* Description */}
          {event.description && (
            <div className="flex items-start gap-2.5 pt-2 border-t border-zinc-100 dark:border-zinc-800/60">
              <AlignLeft className="w-4 h-4 shrink-0 text-zinc-400 mt-0.5" />
              <div className="flex-1 min-w-0">
                <div className="text-[11px] leading-relaxed text-zinc-650 dark:text-zinc-300 whitespace-pre-wrap break-words max-h-40 overflow-y-auto pr-1">
                  {renderDescriptionWithLinks(parseCalendarDescription(event.description))}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Delete */}
        {onDelete && event.source === 'crm' && (
          <div className="pt-2 border-t border-zinc-100 dark:border-zinc-800/60">
            <button
              type="button"
              onClick={handleDelete}
              disabled={deleting}
              className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl text-[11px] font-bold text-rose-500 hover:bg-rose-500/10 transition cursor-pointer disabled:opacity-50"
            >
              <Trash2 className="w-3.5 h-3.5" />
              {deleting ? 'Löscht...' : 'Termin löschen'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Two-Weeks View (14 Tage, Kontakt-Bilder) ─────────────────────────────────

interface TwoWeeksViewProps {
  currentDate: Date;
  events: CalendarEvent[];
  isLight: boolean;
  onEventClick: (ev: CalendarEvent) => void;
  onDayClick: (day: Date) => void;
}

// Helper: Tageszeit-Label für visuelle Einordnung
function getTimeOfDayLabel(iso: string): { label: string; color: string; textColor: string } {
  try {
    const h = new Date(iso).getHours();
    if (h < 6) return { label: '🌙 Nacht', color: 'bg-zinc-700', textColor: 'text-white' };
    if (h < 12) return { label: '☀️ Vormittag', color: 'bg-amber-600', textColor: 'text-white' };
    if (h < 18) return { label: '🌤️ Nachmittag', color: 'bg-sky-600', textColor: 'text-white' };
    return { label: '🌆 Abend', color: 'bg-purple-600', textColor: 'text-white' };
  } catch { return { label: '', color: 'bg-zinc-600', textColor: 'text-white' }; }
}

function TwoWeeksView({ currentDate, events, isLight, onEventClick, onDayClick }: TwoWeeksViewProps) {
  const start = startOfWeek(currentDate);
  const today = new Date();
  const days: Date[] = Array.from({ length: 14 }, (_, i) => addDays(start, i));
  const week1 = days.slice(0, 7);
  const week2 = days.slice(7, 14);

  const eventsOnDay = (day: Date) =>
    events.filter(ev => isSameDay(new Date(ev.start), day))
      .sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime());

  const renderDayCol = (day: Date) => {
    const dayEvents = eventsOnDay(day);
    const isToday = isSameDay(day, today);
    const isWeekend = day.getDay() === 0 || day.getDay() === 6;
    return (
      <div
        key={day.toISOString()}
        className={`min-w-0 flex-1 border-l border-zinc-200 dark:border-zinc-800 flex flex-col ${
          isToday ? 'bg-emerald-500/[0.06]' : ''
        }`}
      >
        {/* Tages-Kopf */}
        <button
          type="button"
          onClick={() => onDayClick(day)}
          className={`w-full flex items-center justify-center gap-1.5 py-2 cursor-pointer hover:bg-emerald-500/10 transition border-b shrink-0 ${
            isLight ? 'bg-zinc-50 border-zinc-200' : 'bg-zinc-900/60 border-zinc-800'
          }`}
        >
          <span className={`text-[10px] font-bold ${isLight ? 'text-zinc-600' : 'text-zinc-350'}`}>
            {DAYS_FULL_DE[(day.getDay() + 6) % 7]}
          </span>
          <span className={`text-xs font-black px-1.5 py-0.5 rounded ${
            isToday ? 'bg-emerald-500 text-white' : isLight ? 'text-zinc-800 bg-zinc-200/50' : 'text-zinc-200 bg-zinc-800/50'
          }`}>
            {String(day.getDate()).padStart(2, '0')}.{String(day.getMonth() + 1).padStart(2, '0')}.
          </span>
        </button>

        {/* Events - scrollbarer Bereich, nimmt restliche Höhe ein */}
        <div className="flex-1 min-h-0 overflow-y-auto p-1.5 space-y-1.5">
          {dayEvents.map((ev, idx) => {
            return (
              <button
                key={ev.id}
                type="button"
                onClick={() => onEventClick(ev)}
                className={`w-full text-left rounded-lg border px-2 py-1.5 cursor-pointer hover:opacity-90 transition ${eventColor(ev.source)} relative`}
                title={ev.title}
                style={{ borderLeftWidth: '4px' }}
              >
                {/* Tageszeit-Indikator (kleiner farbiger Balken links) */}
                <div className="absolute left-0 top-0 bottom-0 w-1 rounded-l-lg bg-current opacity-30" />
                
                <div className="flex flex-col ml-1 min-w-0">
                  {/* Top Row: Title + Contact Picture (top right) */}
                  <div className="flex items-start justify-between gap-1.5 min-w-0 w-full">
                    <span className="text-[11px] font-bold leading-snug truncate flex-1">{ev.title}</span>
                    {(ev.kontaktBild || ev.kontaktName) && (
                      <div className="shrink-0 -mt-0.5">
                        {ev.kontaktBild ? (
                          <img src={ev.kontaktBild} alt="" className="w-5 h-5 rounded-full object-cover border border-white/20" />
                        ) : (
                          <div className="w-5 h-5 rounded-full bg-white/25 text-white text-[7px] font-black flex items-center justify-center border border-white/20">
                            {initials(ev.kontaktName!)}
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Bottom Row: Time (from-to) */}
                  {formatTime(ev.start) && (
                    <div className="flex items-center gap-1 mt-1 text-[9px] font-semibold opacity-90">
                      <Clock className="w-2.5 h-2.5 shrink-0" />
                      <span>{formatTime(ev.start)} – {formatTime(ev.end)}</span>
                    </div>
                  )}

                  {/* Location (if present) */}
                  {ev.location && (
                    <div className="flex items-center gap-1 mt-0.5 text-[9px] opacity-75 truncate">
                      <MapPin className="w-2.5 h-2.5 shrink-0" />
                      <span className="truncate">{ev.location}</span>
                    </div>
                  )}
                </div>
              </button>
            );
          })}
          
          {dayEvents.length === 0 && (
            <div className={`h-full flex items-center justify-center ${isLight ? 'text-zinc-300' : 'text-zinc-600'}`}>
              <span className="text-[10px] font-mono">— keine Termine —</span>
            </div>
          )}
        </div>
      </div>
    );
  };

  const renderWeekRow = (week: Date[], label: string) => (
    <div className="flex flex-col min-h-0 flex-1">
      <div className={`px-3 py-1.5 text-[10px] font-mono font-bold uppercase tracking-widest shrink-0 ${
        isLight ? 'text-zinc-400 bg-zinc-50 border-b border-zinc-200' : 'text-zinc-500 bg-zinc-900/60 border-b border-zinc-800'
      }`}>
        {label}
      </div>
      <div className="flex flex-1 min-h-0">
        {week.map(renderDayCol)}
      </div>
    </div>
  );

  const w1 = startOfWeek(currentDate);
  const w1e = addDays(w1, 6);
  const w2s = addDays(w1, 7);
  const w2e = addDays(w1, 13);

  return (
    <div className="flex-1 min-h-0 overflow-hidden">
      {/* Wochen-Überschriften - flex col, zwei Wochen übereinander */}
      <div className="flex flex-col h-full">
        {renderWeekRow(week1, `KW ${getISOWeek(w1)} · ${w1.getDate()}. – ${w1e.getDate()}. ${MONTHS_DE[w1.getMonth()]} ${w1.getFullYear()}`)}
        <div className={`border-t-2 ${isLight ? 'border-zinc-200' : 'border-zinc-700'} shrink-0`} />
        {renderWeekRow(week2, `KW ${getISOWeek(w2s)} · ${w2s.getDate()}. – ${w2e.getDate()}. ${MONTHS_DE[w2s.getMonth()]} ${w2s.getFullYear()}`)}
      </div>
    </div>
  );
}

// ─── Month View ────────────────────────────────────────────────────────────────

interface MonthViewProps {
  currentDate: Date;
  events: CalendarEvent[];
  isLight: boolean;
  onEventClick: (ev: CalendarEvent) => void;
}

function MonthView({ currentDate, events, isLight, onEventClick }: MonthViewProps) {
  const year = currentDate.getFullYear();
  const month = currentDate.getMonth();
  const today = new Date();

  const firstOfMonth = new Date(year, month, 1);
  const gridStart = startOfWeek(firstOfMonth);

  const cells: Date[] = [];
  for (let i = 0; i < 42; i++) {
    cells.push(addDays(gridStart, i));
  }

  const eventsOnDay = (day: Date) =>
    events.filter(ev => isSameDay(new Date(ev.start), day));

  return (
    <div className="flex-1 min-h-0 overflow-auto">
      <div className="grid grid-cols-7 border-b border-zinc-200 dark:border-zinc-800 shrink-0">
        {DAYS_DE.map(d => (
          <div key={d} className={`py-2 text-center text-[11px] font-bold font-mono uppercase tracking-widest ${
            isLight ? 'text-zinc-500 bg-zinc-50' : 'text-zinc-500 bg-zinc-900/50'
          }`}>
            {d}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-7 flex-1">
        {cells.map((day, i) => {
          const dayEvents = eventsOnDay(day);
          const isCurrentMonth = day.getMonth() === month;
          const isToday = isSameDay(day, today);
          const isWeekend = day.getDay() === 0 || day.getDay() === 6;

          return (
            <div
              key={i}
              className={`min-h-[90px] border-b border-r p-1.5 ${
                isLight
                  ? `border-zinc-200 ${!isCurrentMonth ? 'bg-zinc-50/70' : ''} ${isWeekend && isCurrentMonth ? 'bg-zinc-50/40' : ''}`
                  : `border-zinc-800/60 ${!isCurrentMonth ? 'bg-zinc-950/50' : ''}`
              }`}
            >
              <div className={`text-[11px] font-mono font-bold w-6 h-6 flex items-center justify-center rounded-full mb-1 ${
                isToday
                  ? 'bg-emerald-500 text-white'
                  : isCurrentMonth
                  ? isLight ? 'text-zinc-700' : 'text-zinc-300'
                  : isLight ? 'text-zinc-300' : 'text-zinc-700'
              }`}>
                {day.getDate()}
              </div>

              <div className="space-y-0.5">
                {dayEvents.slice(0, 3).map(ev => (
                  <button
                    key={ev.id}
                    type="button"
                    onClick={() => onEventClick(ev)}
                    className={`w-full text-left text-[10px] font-semibold px-1.5 py-0.5 rounded truncate border cursor-pointer hover:opacity-90 transition ${eventColor(ev.source)}`}
                    title={ev.title}
                  >
                    {ev.kontaktBild && (
                      <img src={ev.kontaktBild} alt="" className="w-3.5 h-3.5 rounded-full inline-block mr-1 -mt-0.5 object-cover" />
                    )}
                    {formatTime(ev.start) && <span className="opacity-75 mr-1">{formatTime(ev.start)}</span>}
                    {ev.title}
                  </button>
                ))}
                {dayEvents.length > 3 && (
                  <div className={`text-[10px] font-mono font-bold pl-1 ${isLight ? 'text-zinc-400' : 'text-zinc-600'}`}>
                    +{dayEvents.length - 3} weitere
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Week View ─────────────────────────────────────────────────────────────────

interface WeekViewProps {
  currentDate: Date;
  events: CalendarEvent[];
  isLight: boolean;
  onEventClick: (ev: CalendarEvent) => void;
}

function WeekView({ currentDate, events, isLight, onEventClick }: WeekViewProps) {
  const weekStart = startOfWeek(currentDate);
  const today = new Date();
  const days: Date[] = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i));
  const hours = Array.from({ length: 14 }, (_, i) => i + 7); // 07:00 – 20:00

  const eventPos = (ev: CalendarEvent) => {
    const s = new Date(ev.start);
    const e = new Date(ev.end);
    const startH = s.getHours() + s.getMinutes() / 60;
    const endH   = e.getHours() + e.getMinutes() / 60;
    const top    = Math.max(0, (startH - 7) / 14) * 100;
    const height = Math.max(2, (endH - startH) / 14) * 100;
    return { top: `${top}%`, height: `${height}%` };
  };

  return (
    <div className="flex-1 min-h-0 overflow-auto">
      <div className="grid grid-cols-8 border-b border-zinc-200 dark:border-zinc-800 sticky top-0 z-10">
        <div className={`py-2 text-center text-[10px] font-mono ${isLight ? 'bg-zinc-50' : 'bg-zinc-900'}`} />
        {days.map((day, i) => {
          const isToday = isSameDay(day, today);
          return (
            <div key={i} className={`py-2 text-center ${isLight ? 'bg-zinc-50 border-l border-zinc-200' : 'bg-zinc-900 border-l border-zinc-800'}`}>
              <div className={`text-[10px] font-mono uppercase tracking-wider ${isLight ? 'text-zinc-500' : 'text-zinc-500'}`}>
                {DAYS_DE[i]}
              </div>
              <div className={`text-sm font-black mx-auto mt-0.5 w-7 h-7 flex items-center justify-center rounded-full ${
                isToday ? 'bg-emerald-500 text-white' : isLight ? 'text-zinc-700' : 'text-zinc-300'
              }`}>
                {day.getDate()}
              </div>
            </div>
          );
        })}
      </div>

      <div className="grid grid-cols-8 relative" style={{ height: '700px' }}>
        <div className="relative">
          {hours.map(h => (
            <div
              key={h}
              className={`absolute left-0 right-0 text-[10px] font-mono text-right pr-2 ${isLight ? 'text-zinc-400' : 'text-zinc-600'}`}
              style={{ top: `${(h - 7) / 14 * 100}%` }}
            >
              {String(h).padStart(2, '0')}:00
            </div>
          ))}
        </div>

        {days.map((day, di) => {
          const dayEvents = events.filter(ev => isSameDay(new Date(ev.start), day));
          return (
            <div
              key={di}
              className={`relative border-l ${isLight ? 'border-zinc-200' : 'border-zinc-800'}`}
            >
              {hours.map(h => (
                <div
                  key={h}
                  className={`absolute left-0 right-0 border-t ${isLight ? 'border-zinc-100' : 'border-zinc-800/40'}`}
                  style={{ top: `${(h - 7) / 14 * 100}%` }}
                />
              ))}

              {dayEvents.map(ev => {
                const pos = eventPos(ev);
                return (
                  <button
                    key={ev.id}
                    type="button"
                    onClick={() => onEventClick(ev)}
                    className={`absolute left-0.5 right-0.5 rounded-lg border text-left px-1.5 py-1 text-[10px] font-semibold cursor-pointer hover:opacity-90 transition shadow-sm overflow-hidden ${eventColor(ev.source)}`}
                    style={{ top: pos.top, height: pos.height }}
                    title={ev.title}
                  >
                    <div className="flex items-center gap-1">
                      {ev.kontaktBild && (
                        <img src={ev.kontaktBild} alt="" className="w-3.5 h-3.5 rounded-full object-cover shrink-0" />
                      )}
                      <div className="font-bold truncate leading-tight">{ev.title}</div>
                    </div>
                    {formatTime(ev.start) && (
                      <div className="opacity-75 truncate">{formatTime(ev.start)} – {formatTime(ev.end)}</div>
                    )}
                  </button>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Main CalendarView ─────────────────────────────────────────────────────────

export function CalendarView({ themeMode = 'light' }: CalendarViewProps) {
  const isLight = themeMode === 'light';
  const [view, setView] = useState<CalView>('twoweeks');
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all');
  const [currentDate, setCurrentDate] = useState(new Date());
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [kontakte, setKontakte] = useState<Kontakt[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedEvent, setSelectedEvent] = useState<CalendarEvent | null>(null);
  const [showNewModal, setShowNewModal] = useState(false);
  const [statusMsg, setStatusMsg] = useState<{ type: 'info' | 'warn' | 'ok'; text: string } | null>(null);

  // ── Kontakte laden (für Bilder + Auswahl) ──────────────────────────────────
  const loadKontakte = useCallback(async () => {
    try {
      const list = await pb.collection('Kontakte').getFullList<Kontakt>({
        sort: 'name',
        fields: 'id,name,profilbild,unternehmen,email',
        requestKey: null,
      });
      setKontakte(list);
    } catch (err: any) {
      console.warn('Kontakte laden fehlgeschlagen:', err?.message || err);
    }
  }, []);

  // ── CRM-Termine aus PocketBase laden (echte Speicherung) ──────────────────
  const loadCrmEvents = useCallback(async (): Promise<CalendarEvent[]> => {
    try {
      const list = await pb.collection('termine').getFullList<any>({
        sort: 'start',
        requestKey: null,
      });
      return list.map((rec: any): CalendarEvent => ({
        id: `crm-${rec.id}`,
        title: rec.titel || 'Ohne Titel',
        start: rec.start,
        end: rec.ende || rec.start,
        source: 'crm',
        location: rec.ort || undefined,
        description: rec.notiz || undefined,
        kontaktId: rec.kontakt || undefined,
        kontaktName: undefined, // wird unten aufgelöst
      }));
    } catch (err: any) {
      console.warn('termine laden fehlgeschlagen:', err?.message || err);
      return [];
    }
  }, []);

  // Events laden: CRM (echt) + ICS (Outlook) + Aggregator (Google)
  const loadEvents = useCallback(async () => {
    setLoading(true);
    setStatusMsg(null);

    let calSettings: any = {};
    try {
      const raw = localStorage.getItem('archon_crm_calendar_settings_v1');
      if (raw) calSettings = JSON.parse(raw);
    } catch {}

    const icsUrl        = calSettings.outlookIcsUrl   || '';
    const aggregatorUrl = (calSettings.aggregatorUrl  || 'http://localhost:8421').replace(/\/$/, '');
    const lookAhead     = calSettings.lookAheadDays   || '60';
    const lookBack      = calSettings.lookBackDays    || '14';

    const collected: CalendarEvent[] = [];
    const sources: string[] = [];
    const errors: string[] = [];

    // ── 1. Echte CRM-Termine aus PocketBase ──────────────────────────────
    const crmEvents = await loadCrmEvents();
    if (crmEvents.length > 0) {
      collected.push(...crmEvents);
      sources.push(`CRM-Termine (${crmEvents.length})`);
    }

    // ── 2. ICS feed (Outlook) ─────────────────────────────────────────────
    if (icsUrl.trim()) {
      try {
        const params = new URLSearchParams({ url: icsUrl.trim(), lookAhead, lookBack });
        const res = await fetch(`/api/calendar/ics?${params}`, { cache: 'no-store' });
        const data = await res.json();
        if (res.ok && Array.isArray(data.events)) {
          collected.push(...data.events);
          sources.push(`Outlook ICS (${data.events.length} Termine)`);
        } else {
          errors.push(`ICS: ${data.error || 'Unbekannter Fehler'}`);
        }
      } catch (e: any) {
        errors.push(`ICS: ${e?.message || 'Netzwerkfehler'}`);
      }
    }

    // ── 3. Python aggregator (Google) ─────────────────────────────────────
    try {
      const res = await fetch(`${aggregatorUrl}/events`, {
        signal: AbortSignal.timeout(3000),
        cache: 'no-store',
      });
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data.events) && data.events.length > 0) {
          collected.push(...data.events);
          sources.push(`Aggregator (${data.events.length} Termine)`);
        }
      }
    } catch {}

    // ── 4. Kontakt-Bilder an Termine anhängen ─────────────────────────────
    for (const ev of collected) {
      if (ev.kontaktId) {
        const k = kontakte.find(c => c.id === ev.kontaktId);
        if (k) {
          ev.kontaktName = k.name;
          (ev as any).kontaktBild = kontaktBildUrl(k);
        }
      } else {
        // Ansonsten per E-Mail-Abgleich mit Teilnehmern / Beschreibung / Titel suchen
        const attendeesEmails = (ev.attendees || []).map(a => a.toLowerCase().trim());
        const descText = (ev.description || '').toLowerCase();
        const titleText = (ev.title || '').toLowerCase();

        const matchedKontakt = kontakte.find(k => {
          if (!k.email && !k.name) return false;
          if (k.email) {
            const kEmail = k.email.toLowerCase().trim();
            if (attendeesEmails.includes(kEmail)) return true;
            if (descText.includes(kEmail)) return true;
          }
          if (k.name) {
            const kName = k.name.toLowerCase().trim();
            if (titleText.includes(kName)) return true;
          }
          return false;
        });

        if (matchedKontakt) {
          ev.kontaktId = matchedKontakt.id;
          ev.kontaktName = matchedKontakt.name;
          (ev as any).kontaktBild = kontaktBildUrl(matchedKontakt);
        }
      }
    }

    // ── Result ────────────────────────────────────────────────────────────
    if (collected.length > 0) {
      // Sortieren nach Quell-Priorität: crm vor google vor outlook
      collected.sort((a, b) => {
        const priority = { crm: 0, google: 1, outlook: 2 };
        return (priority[a.source] || 3) - (priority[b.source] || 3);
      });

      const seenKeys = new Set<string>();
      const unique = collected.filter(ev => {
        // Eindeutiger Schlüssel basierend auf Name, Startzeitpunkt und Endzeitpunkt
        const titleKey = (ev.title || '').trim().toLowerCase();
        const startKey = new Date(ev.start).getTime();
        const endKey = new Date(ev.end).getTime();
        const compositeKey = `${titleKey}_${startKey}_${endKey}`;

        if (seenKeys.has(compositeKey)) return false;
        seenKeys.add(compositeKey);
        return true;
      });
      unique.sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime());
      setEvents(unique);

      setStatusMsg(null);
    } else {
      setStatusMsg({ type: 'warn', text: 'Keine Termine gefunden. Einstellungen → Kalender-APIs → ICS-URL eintragen oder "+ Termin eintragen" nutzen.' });
    }

    setLoading(false);
  }, [loadCrmEvents, kontakte]);

  useEffect(() => { loadKontakte(); }, [loadKontakte]);
  useEffect(() => { loadEvents(); }, [loadEvents]);

  // Neue Termine laden, wenn Kontakte fertig geladen sind (für Bilder)
  useEffect(() => {
    if (kontakte.length > 0) loadEvents();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kontakte.length]);

  const filteredEvents = events.filter(ev => {
    if (sourceFilter === 'all') return true;
    return ev.source === sourceFilter;
  });

  const navigate = (dir: -1 | 1) => {
    setCurrentDate(prev => {
      const d = new Date(prev);
      if (view === 'month') d.setMonth(d.getMonth() + dir);
      else if (view === 'week') d.setDate(d.getDate() + dir * 7);
      else d.setDate(d.getDate() + dir * 14); // twoweeks
      return d;
    });
  };

  const goToday = () => setCurrentDate(new Date());

  // Echten Termin in PocketBase speichern
  const handleSaveNewEvent = async (ev: Omit<CalendarEvent, 'id'>) => {
    const rec = await pb.collection('termine').create({
      titel: ev.title,
      start: ev.start,
      ende: ev.end,
      ort: ev.location || '',
      notiz: ev.description || '',
      kontakt: ev.kontaktId || '',
    });
    // Lokal hinzufügen
    const newEv: CalendarEvent = { ...ev, id: `crm-${rec.id}`, kontaktName: ev.kontaktName };
    const k = kontakte.find(c => c.id === ev.kontaktId);
    if (k) (newEv as any).kontaktBild = kontaktBildUrl(k);
    setEvents(prev => [...prev, newEv]);
    setStatusMsg({ type: 'ok', text: `Termin "${ev.title}" gespeichert.` });
  };

  // Echten Termin löschen
  const handleDeleteEvent = async (ev: CalendarEvent) => {
    if (!ev.id.startsWith('crm-')) return;
    const recId = ev.id.replace('crm-', '');
    try {
      await pb.collection('termine').delete(recId);
      setEvents(prev => prev.filter(e => e.id !== ev.id));
      setStatusMsg({ type: 'ok', text: 'Termin gelöscht.' });
    } catch (err: any) {
      setStatusMsg({ type: 'warn', text: `Löschen fehlgeschlagen: ${err?.message || 'Fehler'}` });
    }
  };

  // Neuen Termin im Modal vorbelegen (Tag-Klick)
  const handleDayClick = (day: Date) => {
    const local = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}T09:00`;
    setShowNewModal(true);
    // Modal liest nur initial — wir setzen einen Default-Zeitpunkt über einen Key
    (window as any).__archonPrefillDay = local;
  };

  // Header title
  const headerTitle = (() => {
    if (view === 'month') {
      return `${MONTHS_DE[currentDate.getMonth()]} ${currentDate.getFullYear()}`;
    }
    if (view === 'week') {
      const ws = startOfWeek(currentDate);
      const we = addDays(ws, 6);
      return `${ws.getDate()}. – ${we.getDate()}. ${MONTHS_DE[ws.getMonth()]} ${ws.getFullYear()}`;
    }
    // twoweeks
    const ws = startOfWeek(currentDate);
    const we = addDays(ws, 13);
    return `${ws.getDate()}. ${MONTHS_DE[ws.getMonth()]} – ${we.getDate()}. ${MONTHS_DE[we.getMonth()]} ${we.getFullYear()}`;
  })();

  const btnBase = `px-3 py-1.5 rounded-lg text-[11px] font-semibold transition cursor-pointer`;
  const btnActive = `bg-emerald-600 text-white shadow-sm`;
  const btnInactive = isLight
    ? `bg-zinc-100 text-zinc-700 hover:bg-zinc-200 border border-zinc-200`
    : `bg-zinc-800 text-zinc-300 hover:bg-zinc-700 border border-zinc-700`;

  const getFilterBtnClass = (src: SourceFilter) => {
    const active = sourceFilter === src;
    const base = `px-3 py-1.5 rounded-lg text-[11px] font-bold transition cursor-pointer border shadow-xs`;
    if (src === 'all') {
      return active
        ? `${base} bg-zinc-700 text-white border-zinc-600`
        : `${base} ${btnInactive} opacity-70`;
    }
    const colorClass = src === 'google' ? 'event-google' : src === 'outlook' ? 'event-outlook' : 'event-crm';
    return active
      ? `${base} ${colorClass} opacity-100`
      : `${base} ${colorClass} opacity-40 hover:opacity-75`;
  };

  return (
    <div className={`flex flex-col h-full min-h-0 calendar-view-root ${isLight ? 'bg-white' : 'bg-zinc-900'}`}>

      {/* ── Toolbar ── */}
      <div className={`shrink-0 px-5 py-3 border-b flex items-center gap-3 flex-wrap ${
        isLight ? 'border-zinc-200 bg-white' : 'border-zinc-800 bg-zinc-900'
      }`}>

        <div className="flex items-center gap-1.5">
          <button type="button" onClick={() => navigate(-1)} className={`p-1.5 rounded-lg ${btnInactive} cursor-pointer`}>
            <ChevronLeft className="w-3.5 h-3.5" />
          </button>
          <button type="button" onClick={() => navigate(1)} className={`p-1.5 rounded-lg ${btnInactive} cursor-pointer`}>
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
          <button type="button" onClick={goToday} className={`${btnBase} ${btnInactive}`}>Heute</button>
          <span className={`font-bold text-sm font-mono ml-2 ${isLight ? 'text-zinc-800' : 'text-zinc-200'}`}>
            {headerTitle}
          </span>
        </div>

        {/* View toggle */}
        <div className="flex items-center gap-1 ml-auto">
          <button type="button" onClick={() => setView('twoweeks')} className={`${btnBase} ${view === 'twoweeks' ? btnActive : btnInactive}`}>
            2 Wochen
          </button>
          <button type="button" onClick={() => setView('week')} className={`${btnBase} ${view === 'week' ? btnActive : btnInactive}`}>
            Woche
          </button>
          <button type="button" onClick={() => setView('month')} className={`${btnBase} ${view === 'month' ? btnActive : btnInactive}`}>
            Monat
          </button>
        </div>

        {/* Source filters */}
        <div className="flex items-center gap-1">
          {(['all', 'google', 'outlook', 'crm'] as SourceFilter[]).map(src => (
            <button
              key={src}
              type="button"
              onClick={() => setSourceFilter(src)}
              className={getFilterBtnClass(src)}
            >
              {src === 'all' ? 'Alle' : src === 'google' ? 'Google' : src === 'outlook' ? 'Outlook' : 'CRM'}
            </button>
          ))}
        </div>

        <button type="button" onClick={loadEvents} className={`p-1.5 rounded-lg ${btnInactive} cursor-pointer`} title="Kalender aktualisieren">
          <RefreshCw className="w-3.5 h-3.5" />
        </button>

        <span className={`text-[10px] font-mono font-bold px-2 py-1 rounded bg-zinc-100 dark:bg-zinc-800/80 text-zinc-500 dark:text-zinc-400`}>
          {filteredEvents.length} Termine
        </span>

        <button
          type="button"
          onClick={() => setShowNewModal(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-[11px] font-bold transition shadow-sm cursor-pointer"
        >
          <Plus className="w-3.5 h-3.5" />
          Termin eintragen
        </button>
      </div>

      {/* ── Status banner ── */}
      {statusMsg && (
        <div className={`shrink-0 px-5 py-2 text-[11px] font-mono flex items-center gap-2 ${
          statusMsg.type === 'ok'
            ? isLight ? 'bg-emerald-50 border-b border-emerald-200 text-emerald-700' : 'bg-emerald-950/30 border-b border-emerald-900 text-emerald-400'
            : isLight ? 'bg-amber-50 border-b border-amber-200 text-amber-700' : 'bg-amber-950/30 border-b border-amber-900 text-amber-400'
        }`}>
          <span>{statusMsg.type === 'ok' ? '✓' : '⚠️'} {statusMsg.text}</span>
        </div>
      )}

      {/* ── Calendar body ── */}
      {loading ? (
        <div className="flex-1 flex items-center justify-center gap-2 text-zinc-400">
          <Loader2 className="w-5 h-5 animate-spin" />
          <span className="text-sm font-mono">Kalender lädt...</span>
        </div>
      ) : view === 'twoweeks' ? (
        <TwoWeeksView
          currentDate={currentDate}
          events={filteredEvents}
          isLight={isLight}
          onEventClick={setSelectedEvent}
          onDayClick={handleDayClick}
        />
      ) : view === 'week' ? (
        <WeekView
          currentDate={currentDate}
          events={filteredEvents}
          isLight={isLight}
          onEventClick={setSelectedEvent}
        />
      ) : (
        <MonthView
          currentDate={currentDate}
          events={filteredEvents}
          isLight={isLight}
          onEventClick={setSelectedEvent}
        />
      )}

      {/* ── Modals ── */}
      {selectedEvent && (
        <EventDetail
          event={selectedEvent}
          onClose={() => setSelectedEvent(null)}
          isLight={isLight}
          onDelete={handleDeleteEvent}
        />
      )}
      {showNewModal && (
        <NewEventModal
          onClose={() => setShowNewModal(false)}
          onSave={handleSaveNewEvent}
          isLight={isLight}
          kontakte={kontakte}
        />
      )}
    </div>
  );
}
