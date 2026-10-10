"use client";

import React, { useState, useEffect, useMemo, useRef } from 'react';
import { pb } from '@/lib/pocketbase';
import {
  Image as ImageIcon, Plus, X, Link2, StickyNote, Upload, Trash2,
  RefreshCw, ExternalLink, Calendar, Search, LayoutGrid, Loader2,
  Mic, Square, Printer
} from 'lucide-react';
import { transcribeAudioOnly } from '@/utils/aiAudio';

interface MediaRecord {
  id: string;
  bild?: string;
  url?: string;
  notiz?: string;
  titel?: string;
  created: string;
  updated: string;
}

const COLLECTION = 'MediaBoard';

function getBildUrl(rec: MediaRecord): string | null {
  if (!rec || !rec.bild) return null;
  const val = rec.bild.trim();
  if (!val) return null;
  if (val.startsWith('http://') || val.startsWith('https://') || val.startsWith('data:')) {
    return val;
  }
  if (rec.id) {
    return pb.files.getURL(rec as any, val);
  }
  return val;
}

function formatDate(ts?: string): string {
  if (!ts) return '';
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts;
  return d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

interface MediaBoardViewProps {
  themeMode?: 'light' | 'dark';
}

export function MediaBoardView({ themeMode = 'light' }: MediaBoardViewProps) {
  const isLight = themeMode === 'light';

  const [records, setRecords] = useState<MediaRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Formular-State
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [formTitel, setFormTitel] = useState('');
  const [formUrl, setFormUrl] = useState('');
  const [formNotiz, setFormNotiz] = useState('');
  const [formImageFile, setFormImageFile] = useState<File | null>(null);
  const [formImagePreview, setFormImagePreview] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Diktat (Notiz per Mikrofon - wie bei den Kontakten)
  const [isDikting, setIsDikting] = useState(false);
  const [isDiktProcessing, setIsDiktProcessing] = useState(false);
  const diktterRecorderRef = useRef<MediaRecorder | null>(null);
  const diktterChunksRef = useRef<Blob[]>([]);
  const diktterStreamRef = useRef<MediaStream | null>(null);
  const [diktTime, setDiktTime] = useState(0);
  const dikttimerRef = useRef<any>(null);
  const SEGMENT_DURATION_SEC = 600;

  // Lightbox-Notiz (Post-it): Bearbeiten + Diktat + Speichern
  const [lightboxNotizText, setLightboxNotizText] = useState('');
  const [isEditingNotiz, setIsEditingNotiz] = useState(false);
  const [isSavingNotiz, setIsSavingNotiz] = useState(false);
  const [isLightboxDikting, setIsLightboxDikting] = useState(false);
  const [isLightboxDiktProcessing, setIsLightboxDiktProcessing] = useState(false);
  const lbDiktRecorderRef = useRef<MediaRecorder | null>(null);
  const lbDiktChunksRef = useRef<Blob[]>([]);
  const lbDiktStreamRef = useRef<MediaStream | null>(null);

  // Lightbox (große Ansicht)
  const [lightbox, setLightbox] = useState<MediaRecord | null>(null);

  // Suche
  const [searchTerm, setSearchTerm] = useState('');

  const fetchRecords = async () => {
    try {
      setLoading(true);
      setError('');
      const items = await pb.collection(COLLECTION).getList<MediaRecord>(1, 200, {
        sort: '-created',
      });
      setRecords(items.items);
    } catch (err: any) {
      setError(`Media Board konnte nicht geladen werden: ${err?.message || 'Unbekannter Fehler'}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRecords();
    // Echtzeit-Sync wie bei Kontakten
    let unsub: (() => void) | undefined;
    pb.collection(COLLECTION).subscribe<MediaRecord>('*', (e) => {
      if (e.action === 'create') {
        setRecords(prev => [e.record, ...prev]);
      } else if (e.action === 'update') {
        setRecords(prev => prev.map(r => (r.id === e.record.id ? e.record : r)));
      } else if (e.action === 'delete') {
        setRecords(prev => prev.filter(r => r.id !== e.record.id));
      }
    }).then((fn) => { unsub = fn; }).catch(() => {});
    return () => { if (unsub) unsub(); };
  }, []);

  const handleImageSelect = (file: File) => {
    setFormImageFile(file);
    setFormImagePreview(URL.createObjectURL(file));
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    if (e.clipboardData?.files && e.clipboardData.files.length > 0) {
      for (let i = 0; i < e.clipboardData.files.length; i++) {
        const f = e.clipboardData.files[i];
        if (f.type.startsWith('image/')) {
          e.preventDefault();
          handleImageSelect(f);
          return;
        }
      }
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formImageFile) {
      setError('Bitte ein Bild auswählen oder einfügen (Strg+V).');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const formData = new FormData();
      formData.append('bild', formImageFile);
      if (formTitel.trim()) formData.append('titel', formTitel.trim());
      if (formUrl.trim()) formData.append('url', formUrl.trim());
      if (formNotiz.trim()) formData.append('notiz', formNotiz.trim());

      await pb.collection(COLLECTION).create(formData);
      // Formular zurücksetzen
      setFormTitel(''); setFormUrl(''); setFormNotiz('');
      setFormImageFile(null); setFormImagePreview(null);
      setIsFormOpen(false);
      await fetchRecords();
    } catch (err: any) {
      setError(`Speichern fehlgeschlagen: ${err?.message || 'Unbekannter Fehler'}`);
    } finally {
      setSaving(false);
    }
  };

  const formatDiktTime = (s: number) => {
    const mins = Math.floor(s / 60);
    const secs = s % 60;
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  };

  // Diktat starten: Mikrofon -> Groq Whisper -> Text in die Notiz
  const startDiktat = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      diktterStreamRef.current = stream;
      diktterChunksRef.current = [];
      const rec = new MediaRecorder(stream);
      diktterRecorderRef.current = rec;
      rec.ondataavailable = (e) => { if (e.data.size > 0) diktterChunksRef.current.push(e.data); };
      rec.onstop = async () => {
        const blob = new Blob(diktterChunksRef.current, { type: 'audio/webm' });
        setIsDiktProcessing(true);
        try {
          const apiKey = process.env.NEXT_PUBLIC_GROQ_API_KEY || localStorage.getItem('groq_api_key') || '';
          const transcript = await transcribeAudioOnly(blob, apiKey);
          if (transcript && transcript.trim()) {
            setFormNotiz(prev => prev ? `${prev}\n${transcript.trim()}` : transcript.trim());
          }
        } catch (err: any) {
          setError(`Diktat-Transkription fehlgeschlagen: ${err?.message || 'Fehler'}`);
        } finally {
          setIsDiktProcessing(false);
        }
        diktterStreamRef.current?.getTracks().forEach(t => t.stop());
        diktterStreamRef.current = null;
      };
      rec.start();
      setIsDikting(true);
      setDiktTime(0);
      dikttimerRef.current = setInterval(() => {
        setDiktTime(prev => {
          const next = prev + 1;
          if (next >= SEGMENT_DURATION_SEC && diktterRecorderRef.current?.state === 'recording') {
            diktterRecorderRef.current.stop();
            return 0;
          }
          return next;
        });
      }, 1000);
    } catch (err: any) {
      setError(`Mikrofon nicht verfügbar: ${err?.message || 'Fehler'}`);
    }
  };

  const stopDiktat = () => {
    if (dikttimerRef.current) { clearInterval(dikttimerRef.current); dikttimerRef.current = null; }
    if (diktterRecorderRef.current && diktterRecorderRef.current.state !== 'inactive') {
      diktterRecorderRef.current.stop();
    }
    setIsDikting(false);
  };

  // Drucken: Grafik in ein Popup-Fenster laden und Druckdialog öffnen
  const escHtml = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  const handlePrint = (rec: MediaRecord) => {
    const imgUrl = getBildUrl(rec);
    if (!imgUrl) return;
    const win = window.open('', '_blank', 'width=900,height=700');
    if (!win) { setError('Popup-Blocker verhindert den Druckdialog.'); return; }
    const titel = escHtml(rec.titel || '');
    const notiz = escHtml(rec.notiz || '').replace(/\n/g, '<br/>');
    const datum = new Date(rec.created).toLocaleDateString('de-DE');
    win.document.write(
      '<!DOCTYPE html><html><head><title>Media Board</title>' +
      '<style>body{font-family:system-ui;margin:20px;text-align:center}' +
      'img{max-width:100%;max-height:85vh} h2{font-size:16px} p{color:#555;font-size:12px}' +
      '@media print{body{margin:0}}</style></head><body>' +
      '<h2>' + titel + '</h2>' +
      '<img src="' + imgUrl + '" onload="setTimeout(function(){window.print()},300)" />' +
      '<p>' + notiz + '</p>' +
      '<p style="color:#999;font-size:10px">' + datum + '</p>' +
      '</body></html>'
    );
    win.document.close();
  };

  // Lightbox-Notiz: Bearbeiten starten (Notiz-Text laden)
  const openNotizEdit = (rec: MediaRecord) => {
    setLightboxNotizText(rec.notiz || '');
    setIsEditingNotiz(true);
  };

  // Diktat direkt in der Lightbox-Notiz
  const startLightboxDiktat = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      lbDiktStreamRef.current = stream;
      lbDiktChunksRef.current = [];
      const rec = new MediaRecorder(stream);
      lbDiktRecorderRef.current = rec;
      rec.ondataavailable = (e) => { if (e.data.size > 0) lbDiktChunksRef.current.push(e.data); };
      rec.onstop = async () => {
        const blob = new Blob(lbDiktChunksRef.current, { type: 'audio/webm' });
        setIsLightboxDiktProcessing(true);
        try {
          const apiKey = process.env.NEXT_PUBLIC_GROQ_API_KEY || localStorage.getItem('groq_api_key') || '';
          const transcript = await transcribeAudioOnly(blob, apiKey);
          if (transcript && transcript.trim()) {
            setLightboxNotizText(prev => prev ? `${prev}\n${transcript.trim()}` : transcript.trim());
          }
        } catch (err: any) {
          setError(`Diktat fehlgeschlagen: ${err?.message || 'Fehler'}`);
        } finally {
          setIsLightboxDiktProcessing(false);
        }
        lbDiktStreamRef.current?.getTracks().forEach(t => t.stop());
        lbDiktStreamRef.current = null;
      };
      rec.start();
      setIsLightboxDikting(true);
    } catch (err: any) {
      setError(`Mikrofon nicht verfügbar: ${err?.message || 'Fehler'}`);
    }
  };

  const stopLightboxDiktat = () => {
    if (lbDiktRecorderRef.current && lbDiktRecorderRef.current.state !== 'inactive') {
      lbDiktRecorderRef.current.stop();
    }
    setIsLightboxDikting(false);
  };

  // Notiz speichern (PATCH auf den Datensatz)
  const saveLightboxNotiz = async () => {
    if (!lightbox) return;
    setIsSavingNotiz(true);
    setError('');
    try {
      const updated = await pb.collection(COLLECTION).update<MediaRecord>(lightbox.id, {
        notiz: lightboxNotizText.trim(),
      });
      setRecords(prev => prev.map(r => (r.id === updated.id ? updated : r)));
      setLightbox(updated);
      setIsEditingNotiz(false);
    } catch (err: any) {
      setError(`Notiz speichern fehlgeschlagen: ${err?.message || 'Fehler'}`);
    } finally {
      setIsSavingNotiz(false);
    }
  };

  const handleDelete = async (rec: MediaRecord) => {
    if (!confirm('Dieses Bild wirklich löschen?')) return;
    try {
      await pb.collection(COLLECTION).delete(rec.id);
      setRecords(prev => prev.filter(r => r.id !== rec.id));
      setLightbox(null);
    } catch (err: any) {
      setError(`Löschen fehlgeschlagen: ${err?.message || 'Fehler'}`);
    }
  };

  const filtered = useMemo(() => {
    if (!searchTerm) return records;
    const s = searchTerm.toLowerCase();
    return records.filter(r =>
      (r.titel || '').toLowerCase().includes(s) ||
      (r.notiz || '').toLowerCase().includes(s) ||
      (r.url || '').toLowerCase().includes(s)
    );
  }, [records, searchTerm]);

  return (
    <div className="h-full flex flex-col min-h-0 mediaboard-view-root">
      {/* KOPFZEILE: Titel + Suche + Neues Bild */}
      <div className="flex flex-wrap items-center gap-2 pb-4 shrink-0">
        <div className="flex items-center gap-2">
          <ImageIcon className="w-5 h-5 text-accent-main" />
          <h3 className="font-black text-lg tracking-tight font-mono">Media Board</h3>
          <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded font-bold ${
            isLight ? 'bg-zinc-200 text-zinc-600' : 'bg-zinc-800 text-zinc-300'
          }`}>
            {filtered.length} Bilder
          </span>
        </div>

        <div className={`flex items-center gap-2 px-3 py-2 rounded-xl border flex-1 min-w-[200px] ${
          isLight ? 'bg-white border-zinc-200' : 'bg-zinc-900 border-zinc-800'
        }`}>
          <Search className="w-4 h-4 text-zinc-400 shrink-0" />
          <input
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Titel, Notiz oder Link durchsuchen..."
            className="bg-transparent text-xs font-semibold focus:outline-none w-full placeholder:text-zinc-400"
          />
        </div>

        <button
          type="button"
          onClick={() => setIsFormOpen(true)}
          className="px-4 py-2 rounded-xl bg-accent-main hover:bg-accent-main-hover text-white font-bold text-xs transition shadow-md flex items-center gap-1.5 cursor-pointer"
        >
          <Plus className="w-4 h-4" />
          Bild hinzufügen
        </button>
      </div>

      {/* Fehler-Anzeige */}
      {error && (
        <div className={`mb-3 p-3 rounded-lg border text-xs font-semibold ${
          isLight ? 'bg-rose-50 border-rose-200 text-rose-700' : 'bg-rose-950/40 border-rose-900 text-rose-300'
        }`}>
          {error}
        </div>
      )}

      {/* PINWAND (Masonry-artig via CSS columns) */}
      {loading ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 text-zinc-400">
          <RefreshCw className="w-6 h-6 animate-spin text-accent-main" />
          <p className="text-xs font-mono font-semibold">Lade Media Board...</p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 text-zinc-400">
          <ImageIcon className="w-10 h-10" />
          <p className="text-xs font-semibold">
            {records.length === 0 ? 'Noch keine Bilder im Media Board.' : 'Keine Treffer für die Suche.'}
          </p>
          <p className="text-[11px] text-zinc-400">
            {records.length === 0 ? 'Klicke auf "Bild hinzufügen", um interessante Grafiken zu sammeln.' : ''}
          </p>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto pr-1">
          <div className="columns-2 md:columns-3 lg:columns-4 xl:columns-5 gap-3">
            {filtered.map((rec) => {
              const imgUrl = getBildUrl(rec);
              return (
                <div
                  key={rec.id}
                  className={`mb-3 break-inside-avoid rounded-xl border overflow-hidden transition cursor-pointer group ${
                    isLight
                      ? 'bg-white border-zinc-200 hover:border-zinc-300 hover:shadow-md'
                      : 'bg-zinc-900 border-zinc-800 hover:border-zinc-700 hover:shadow-lg'
                  }`}
                  onClick={() => setLightbox(rec)}
                >
                  {/* Bild 100x100-Vorschau (bei kleinen Bildern zentriert) */}
                  <div className="w-full h-28 overflow-hidden bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center">
                    {imgUrl ? (
                      <img
                        src={imgUrl}
                        alt={rec.titel || 'Media Board Bild'}
                        className="w-full h-full object-cover transition group-hover:scale-105"
                        loading="lazy"
                      />
                    ) : (
                      <ImageIcon className="w-8 h-8 text-zinc-300" />
                    )}
                  </div>
                  <div className="p-2">
                    {rec.titel && (
                      <p className="text-[11px] font-bold truncate">{rec.titel}</p>
                    )}
                    <div className="flex items-center justify-between mt-1">
                      <span className={`text-[10px] font-mono flex items-center gap-1 ${isLight ? 'text-zinc-400' : 'text-zinc-500'}`}>
                        <Calendar className="w-3 h-3" />
                        {formatDate(rec.created)}
                      </span>
                      {rec.url && (
                        <span className={`text-[10px] flex items-center gap-0.5 ${isLight ? 'text-zinc-400' : 'text-zinc-500'}`}>
                          <Link2 className="w-3 h-3" />
                          Link
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* HINZUFÜGEN-FORMULAR */}
      {isFormOpen && (
        <div className="fixed inset-0 z-[1050] bg-black/70 backdrop-blur-md flex items-center justify-center p-4">
          <div className={`w-full max-w-lg rounded-2xl border p-5 shadow-2xl space-y-4 flex flex-col max-h-[90vh] overflow-y-auto ${
            isLight ? 'bg-white border-zinc-200 text-zinc-900' : 'bg-zinc-900 border-zinc-800 text-zinc-100'
          }`}>
            <div className="flex items-center justify-between pb-3 border-b border-zinc-200 dark:border-zinc-800">
              <div className="flex items-center gap-2">
                <ImageIcon className="w-5 h-5 text-accent-main" />
                <h3 className="font-bold text-sm">Bild zum Media Board hinzufügen</h3>
              </div>
              <button
                type="button"
                onClick={() => setIsFormOpen(false)}
                className="p-1 rounded-lg hover:bg-zinc-200 dark:hover:bg-zinc-800 text-zinc-400 transition cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="space-y-3 text-xs" onPaste={handlePaste}>
              {/* Bild-Upload */}
              <div className={`p-3 rounded-xl border-2 border-dashed space-y-2 ${
                isLight ? 'border-zinc-300 bg-zinc-50' : 'border-zinc-700 bg-zinc-950/40'
              }`}>
                {formImagePreview ? (
                  <div className="flex items-center gap-3">
                    <img
                      src={formImagePreview}
                      alt="Vorschau"
                      className="w-20 h-20 rounded-lg object-cover border border-zinc-200 dark:border-zinc-700"
                    />
                    <div className="flex-1 min-w-0">
                      <p className="font-bold truncate">{formImageFile?.name}</p>
                      <p className="text-[10px] text-zinc-400">
                        {((formImageFile?.size || 0) / 1024).toFixed(0)} KB
                      </p>
                      <button
                        type="button"
                        onClick={() => { setFormImageFile(null); setFormImagePreview(null); }}
                        className="mt-1 text-[10px] text-rose-500 font-bold hover:underline cursor-pointer"
                      >
                        Bild entfernen
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-col items-center gap-2 py-4">
                    <Upload className="w-8 h-8 text-zinc-400" />
                    <p className="text-xs font-semibold text-zinc-400">
                      Klicken zum Auswählen oder <span className="font-mono">Strg+V</span> zum Einfügen
                    </p>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) handleImageSelect(f);
                      }}
                    />
                    <button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                      className="px-4 py-1.5 rounded-lg bg-accent-main hover:bg-accent-main-hover text-white font-bold text-xs transition cursor-pointer"
                    >
                      Datei auswählen
                    </button>
                  </div>
                )}
              </div>

              {/* Titel */}
              <div>
                <label className="block font-bold uppercase text-[10px] tracking-wider text-zinc-500 mb-1">
                  Titel <span className="font-normal">(optional)</span>
                </label>
                <input
                  value={formTitel}
                  onChange={(e) => setFormTitel(e.target.value)}
                  placeholder="z.B. Die 5 größten Vermittlungsagenturen der Welt"
                  className={`w-full px-3 py-2 rounded-lg border text-xs font-semibold focus:outline-none ${
                    isLight ? 'bg-white border-zinc-300 focus:border-accent-main' : 'bg-zinc-950 border-zinc-700 focus:border-accent-main'
                  }`}
                />
              </div>

              {/* Link */}
              <div>
                <label className="block font-bold uppercase text-[10px] tracking-wider text-zinc-500 mb-1">
                  Link <span className="font-normal">(optional)</span>
                </label>
                <div className={`flex items-center gap-2 px-3 py-2 rounded-lg border ${
                  isLight ? 'bg-white border-zinc-300' : 'bg-zinc-950 border-zinc-700'
                }`}>
                  <Link2 className="w-3.5 h-3.5 text-zinc-400 shrink-0" />
                  <input
                    value={formUrl}
                    onChange={(e) => setFormUrl(e.target.value)}
                    placeholder="https://www.linkedin.com/..."
                    className="bg-transparent text-xs font-semibold focus:outline-none w-full"
                  />
                </div>
              </div>

              {/* Notiz mit Diktierfunktion */}
              <div>
                <label className="block font-bold uppercase text-[10px] tracking-wider text-zinc-500 mb-1 flex items-center justify-between">
                  <span>Notiz <span className="font-normal">(optional)</span></span>
                  {isDikting ? (
                    <button
                      type="button"
                      onClick={stopDiktat}
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-rose-600 text-white text-[10px] font-bold animate-pulse cursor-pointer"
                    >
                      <Square className="w-2.5 h-2.5 fill-white" />
                      Stopp {formatDiktTime(diktTime)}
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={startDiktat}
                      disabled={isDiktProcessing}
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-bold transition cursor-pointer ${
                        isLight ? 'bg-zinc-100 text-zinc-600 hover:bg-zinc-200' : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'
                      } disabled:opacity-50`}
                      title="Notiz diktieren (Sprache -> Text)"
                    >
                      {isDiktProcessing ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <Mic className="w-2.5 h-2.5" />}
                      {isDiktProcessing ? 'Transkribiert...' : 'Diktieren'}
                    </button>
                  )}
                </label>
                <textarea
                  value={formNotiz}
                  onChange={(e) => setFormNotiz(e.target.value)}
                  placeholder="Warum ist diese Grafik interessant? Idee für später..."
                  rows={3}
                  className={`w-full px-3 py-2 rounded-lg border text-xs font-semibold focus:outline-none resize-none ${
                    isLight ? 'bg-white border-zinc-300 focus:border-accent-main' : 'bg-zinc-950 border-zinc-700 focus:border-accent-main'
                  }`}
                />
              </div>

              <p className={`text-[10px] flex items-center gap-1 ${isLight ? 'text-zinc-400' : 'text-zinc-500'}`}>
                <Calendar className="w-3 h-3" />
                Datum wird automatisch gesetzt (heute)
              </p>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsFormOpen(false)}
                  className={`px-4 py-2 rounded-lg font-semibold text-xs transition ${
                    isLight ? 'bg-zinc-200 text-zinc-800 hover:bg-zinc-300' : 'bg-zinc-800 text-zinc-200 hover:bg-zinc-700'
                  }`}
                >
                  Abbrechen
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="px-5 py-2 rounded-lg bg-accent-main hover:bg-accent-main-hover text-white font-bold text-xs transition shadow-md flex items-center gap-2 disabled:opacity-50 cursor-pointer"
                >
                  {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                  {saving ? 'Speichert...' : 'Hinzufügen'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* LIGHTBOX (große Ansicht) - hell/dunkel passend zum Theme */}
      {lightbox && (
        <div
          className="fixed inset-0 z-[1060] bg-black/85 backdrop-blur-md flex items-center justify-center p-6"
          onClick={() => setLightbox(null)}
        >
          <div
            className={`max-w-5xl w-full max-h-[90vh] flex flex-col overflow-hidden rounded-2xl border shadow-2xl ${
              isLight ? 'bg-white border-zinc-200' : 'bg-zinc-900 border-zinc-700'
            }`}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Kopfzeile */}
            <div className={`flex items-center justify-between p-3 border-b ${isLight ? 'border-zinc-200' : 'border-zinc-800'}`}>
              <div className="flex items-center gap-2 min-w-0">
                <ImageIcon className="w-4 h-4 text-accent-main shrink-0" />
                <h3 className="text-sm font-bold truncate">{lightbox.titel || 'Media Board Bild'}</h3>
                <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded font-bold shrink-0 ${
                  isLight ? 'bg-zinc-100 text-zinc-500' : 'bg-zinc-800 text-zinc-300'
                }`}>
                  {formatDate(lightbox.created)}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                {lightbox.url && (
                  <a
                    href={lightbox.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={`p-1.5 rounded-lg transition ${
                      isLight ? 'text-zinc-500 hover:bg-zinc-100' : 'text-zinc-300 hover:bg-zinc-800'
                    }`}
                    title="Link öffnen"
                  >
                    <ExternalLink className="w-4 h-4" />
                  </a>
                )}
                {/* DRUCKEN */}
                <button
                  type="button"
                  onClick={() => handlePrint(lightbox)}
                  className={`p-1.5 rounded-lg transition cursor-pointer ${
                    isLight
                      ? 'text-zinc-500 hover:bg-zinc-100 hover:text-zinc-700'
                      : 'text-zinc-300 hover:bg-zinc-800'
                  }`}
                  title="Drucken (Windows-Druckdialog)"
                >
                  <Printer className="w-4 h-4" />
                </button>
                {/* NOTIZ HINZUFÜGEN (grün, breit - nur wenn keine Notiz vorhanden) */}
                {!lightbox.notiz && !isEditingNotiz && (
                  <button
                    type="button"
                    onClick={() => openNotizEdit(lightbox)}
                    className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-[11px] font-bold transition shadow-sm cursor-pointer"
                    title="Notiz hinzufügen oder diktieren"
                  >
                    <StickyNote className="w-3.5 h-3.5" />
                    Notiz hinzufügen
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => handleDelete(lightbox)}
                  className="p-1.5 rounded-lg hover:bg-rose-500/10 text-rose-500 transition cursor-pointer"
                  title="Löschen"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  onClick={() => setLightbox(null)}
                  className={`p-1.5 rounded-lg transition cursor-pointer ${
                    isLight ? 'text-zinc-500 hover:bg-zinc-100' : 'text-zinc-300 hover:bg-zinc-800'
                  }`}
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Inhalt: Bild frei & groß in der Mitte + Notiz rechts NUR wenn vorhanden */}
            <div className="flex-1 overflow-auto flex flex-col md:flex-row min-h-0">
              {/* Bild-Bereich: nimmt den ganzen Platz ein (frei in der Mitte) */}
              <div className="flex-1 min-w-0 flex items-center justify-center p-6 bg-zinc-950/40">
                {getBildUrl(lightbox) ? (
                  <img
                    src={getBildUrl(lightbox)!}
                    alt={lightbox.titel || 'Media Board Bild'}
                    className="max-w-full max-h-full object-contain rounded-lg shadow-xl"
                  />
                ) : (
                  <ImageIcon className={`w-16 h-16 ${isLight ? 'text-zinc-300' : 'text-zinc-600'}`} />
                )}
              </div>

              {/* NOTIZ-PANEL rechts - NUR wenn Notiz vorhanden oder beim Bearbeiten */}
              {(lightbox.notiz || isEditingNotiz) && (
                <div className={`md:w-80 shrink-0 p-4 border-t md:border-t-0 md:border-l overflow-y-auto ${
                  isLight ? 'border-zinc-200' : 'border-zinc-800'
                }`}>
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-1.5">
                      <StickyNote className="w-3.5 h-3.5 text-amber-600" />
                      <span className={`text-[10px] font-bold uppercase tracking-wider ${isLight ? 'text-zinc-500' : 'text-zinc-400'}`}>
                        Notiz
                      </span>
                    </div>
                    {!isEditingNotiz && (
                      <button
                        type="button"
                        onClick={() => openNotizEdit(lightbox)}
                        className={`text-[10px] font-bold px-2 py-0.5 rounded-md transition cursor-pointer ${
                          isLight ? 'bg-zinc-100 text-zinc-600 hover:bg-zinc-200' : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'
                        }`}
                      >
                        Bearbeiten
                      </button>
                    )}
                  </div>

                  {isEditingNotiz ? (
                    <div className="space-y-2">
                      <textarea
                        value={lightboxNotizText}
                        onChange={(e) => setLightboxNotizText(e.target.value)}
                        placeholder="Notiz eingeben oder diktieren..."
                        rows={8}
                        autoFocus
                        className={`w-full px-3 py-2 rounded-lg border text-xs font-medium focus:outline-none resize-none ${
                          isLight
                            ? 'bg-amber-50 border-amber-200 text-amber-950 placeholder:text-amber-800/40'
                            : 'bg-amber-950/30 border-amber-800/40 text-amber-100 placeholder:text-amber-300/40'
                        }`}
                        style={{ lineHeight: '1.5' }}
                      />
                      {/* Diktat */}
                      <div className="flex items-center justify-between">
                        {isLightboxDikting ? (
                          <button
                            type="button"
                            onClick={stopLightboxDiktat}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-rose-600 text-white text-[10px] font-bold animate-pulse cursor-pointer"
                          >
                            <Square className="w-2.5 h-2.5 fill-white" />
                            Stopp
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={startLightboxDiktat}
                            disabled={isLightboxDiktProcessing}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-amber-600/20 text-amber-900 text-[10px] font-bold hover:bg-amber-600/30 transition cursor-pointer disabled:opacity-50"
                          >
                            {isLightboxDiktProcessing ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <Mic className="w-2.5 h-2.5" />}
                            {isLightboxDiktProcessing ? 'Transkribiert...' : 'Diktieren'}
                          </button>
                        )}
                        <div className="flex gap-1.5">
                          <button
                            type="button"
                            onClick={() => { setIsEditingNotiz(false); setLightboxNotizText(lightbox?.notiz || ''); }}
                            className="px-2 py-1 rounded-md text-[10px] font-bold text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition cursor-pointer"
                          >
                            Abbrechen
                          </button>
                          <button
                            type="button"
                            onClick={saveLightboxNotiz}
                            disabled={isSavingNotiz}
                            className="px-2.5 py-1 rounded-md bg-emerald-600 text-white text-[10px] font-bold hover:bg-emerald-700 transition cursor-pointer disabled:opacity-50"
                          >
                            {isSavingNotiz ? 'Speichert...' : 'Speichern'}
                          </button>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <p className={`text-xs leading-relaxed whitespace-pre-wrap ${
                      isLight ? 'text-amber-950' : 'text-amber-100'
                    }`} style={{ lineHeight: '1.5' }}>
                      {lightbox.notiz}
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
