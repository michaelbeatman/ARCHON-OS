"use client";

import React, { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { pb, KontaktRecord, STATUS_COLUMNS, getProfilbildUrl } from '@/lib/pocketbase';
import {
  X, ArrowUp, ArrowDown, ChevronsUpDown, SlidersHorizontal, ExternalLink,
  ChevronDown, Search, Settings2, Check, Pencil, Save, RotateCcw, Palette
} from 'lucide-react';

// ─── Constants ────────────────────────────────────────────────────────────────

const CFG_KEY = 'mc_table_columns_config';   // separate Persistenz für diese Tabelle
const STATUS_COLOR_KEY = 'mc_status_colors'; // benutzerdefinierte Status-Farben

type SortDir = 'asc' | 'desc';
type SortKey = keyof KontaktRecord | '';

interface ColDef {
  key: keyof KontaktRecord;
  label: string;
  defaultOn: boolean;
  width?: string;
  editable?: boolean;
  minW: number;
}

const ALL_COLUMNS: ColDef[] = [
  { key: 'name',            label: 'Name',            defaultOn: true,  editable: true,  minW: 180 },
  { key: 'unternehmen',     label: 'Unternehmen',     defaultOn: true,  editable: true,  minW: 170 },
  { key: 'rolle',           label: 'Rolle',           defaultOn: true,  editable: true,  minW: 190 },
  { key: 'status',          label: 'Status',          defaultOn: true,                   minW: 160 },
  { key: 'rating',          label: 'Rating',          defaultOn: false,                  minW: 90  },
  { key: 'region',          label: 'Region',          defaultOn: false, editable: true,  minW: 130 },
  { key: 'vernetzt_am',     label: 'Vernetzt am',     defaultOn: false,                  minW: 120 },
  { key: 'naechster_schritt', label: 'Nächster Schritt', defaultOn: false, editable: true, minW: 190 },
  { key: 'LinkedInheader',    label: 'LinkedIn Headline', defaultOn: false, editable: true, minW: 200 },
  { key: 'Linkedin_info',     label: 'LinkedIn Info',     defaultOn: false, editable: true, minW: 220 },
  { key: 'linkedin_url',    label: 'LinkedIn',        defaultOn: false,                  minW: 90  },
];

// Hochkontrast-Statuspalette (Standard)
const DEFAULT_STATUS_STYLES: Record<string, { bg: string; text: string; border: string; label: string }> = {
  'Unvernetzt':              { bg: '#f1f5f9', text: '#334155', border: '#cbd5e1', label: 'Unvernetzt' },
  'Vernetzt':                { bg: '#d1fae5', text: '#065f46', border: '#6ee7b7', label: 'Vernetzt' },
  'Erstnachricht':           { bg: '#e0f2fe', text: '#075985', border: '#7dd3fc', label: 'Erstnachricht' },
  'Im Dialog':               { bg: '#f3e8ff', text: '#5b21b6', border: '#d8b4fe', label: 'Im Dialog' },
  'Interview vereinbart':    { bg: '#d1fae5', text: '#065f46', border: '#6ee7b7', label: 'Interview vereinbart' },
  'Regelmäßiger Kontakt':    { bg: '#f0fdfa', text: '#134e4a', border: '#99f6e4', label: 'Regelmäßiger Kontakt' },
  'Parkposition':            { bg: '#fef3c7', text: '#92400e', border: '#fcd34d', label: 'Parkposition' },
  'Pool':                    { bg: '#ede9fe', text: '#5b21b6', border: '#c4b5fd', label: 'Pool' },
  'Irrelevant':              { bg: '#f1f5f9', text: '#475569', border: '#cbd5e1', label: 'Irrelevant' },
  'Gesperrt_1Jahr':          { bg: '#f1f5f9', text: '#475569', border: '#cbd5e1', label: 'Gesperrt (Archiv)' },
  'Kein_Interesse':          { bg: '#f8fafc', text: '#64748b', border: '#e2e8f0', label: 'Kein Interesse' },
};

function loadCfg(): { colVis: Record<string, boolean>; sortKey: SortKey; sortDir: SortDir; widths: Record<string, number> } | null {
  try {
    const raw = localStorage.getItem(CFG_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch { return null; }
}

function loadStatusColors(): Record<string, { bg: string; text: string; border: string }> {
  try {
    const raw = localStorage.getItem(STATUS_COLOR_KEY);
    if (!raw) return {};
    return JSON.parse(raw) || {};
  } catch { return {}; }
}

// ─── Props ────────────────────────────────────────────────────────────────────

interface Props {
  open: boolean;
  rollenLabel: string;
  kontakte: KontaktRecord[];
  themeMode: 'light' | 'dark' | 'system';
  onClose: () => void;
  onOpenKontakt: (k: KontaktRecord) => void;
  onOpenDesign?: () => void;   // Zahnrad -> voller Design/CSS-Editor
  onStatusChange?: (k: KontaktRecord, status: string) => void; // Live-Aktualisierung der Eltern
}

// ─── Cell edit helpers ────────────────────────────────────────────────────────

type EditableKey = 'name' | 'unternehmen' | 'rolle' | 'region' | 'naechster_schritt' | 'LinkedInheader' | 'Linkedin_info';

async function saveField(k: KontaktRecord, key: EditableKey, value: string) {
  await pb.collection('Kontakte').update(k.id, { [key]: value });
}
async function saveStatus(k: KontaktRecord, status: string) {
  await pb.collection('Kontakte').update(k.id, { status });
}

// ─── Component ────────────────────────────────────────────────────────────────

export function RollenListePanel({ open, rollenLabel, kontakte, themeMode, onClose, onOpenKontakt, onOpenDesign, onStatusChange }: Props) {
  const isLight = themeMode === 'light';

  const [search, setSearch] = useState('');
  const [showColPicker, setShowColPicker] = useState(false);

  // separate Tabellen-Konfiguration (nur diese Mission-Control-Tabelle)
  const [colVis, setColVis] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(ALL_COLUMNS.map(c => [c.key, c.defaultOn]))
  );
  const [sortKey, setSortKey] = useState<SortKey>('');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [widths, setWidths] = useState<Record<string, number>>(() =>
    Object.fromEntries(ALL_COLUMNS.map(c => [c.key, c.minW]))
  );

  // Status-Farb-Overrides
  const [statusColors, setStatusColors] = useState<Record<string, { bg: string; text: string; border: string }>>(() => loadStatusColors());
  const [colorEditorOpen, setColorEditorOpen] = useState(false);
  const [statusColorDrafts, setStatusColorDrafts] = useState<Record<string, { bg: string; text: string; border: string }>>({});

  // ── Laden aus localStorage ──────────────────────────────────────────────
  useEffect(() => {
    const cfg = loadCfg();
    if (cfg) {
      setColVis(cfg.colVis);
      setSortKey(cfg.sortKey);
      setSortDir(cfg.sortDir);
      if (cfg.widths && Object.keys(cfg.widths).length) setWidths(cfg.widths);
    }
  }, []);

  // ── Persistieren ────────────────────────────────────────────────────────
  const persist = (colVisN: Record<string, boolean>, sortKeyN: SortKey, sortDirN: SortDir, widthsN: Record<string, number>) => {
    try {
      localStorage.setItem(CFG_KEY, JSON.stringify({ colVis: colVisN, sortKey: sortKeyN, sortDir: sortDirN, widths: widthsN }));
    } catch {}
  };

  const setColumnVisibility = (key: string, on: boolean) => {
    setColVis(prev => { const n = { ...prev, [key]: on }; persist(n, sortKey, sortDir, widths); return n; });
  };
  const setSort = (key: SortKey) => {
    let nk = key, nd: SortDir = 'asc';
    if (sortKey === key) nd = sortDir === 'asc' ? 'desc' : 'asc';
    setSortKey(nk); setSortDir(nd); persist(colVis, nk, nd, widths);
  };
  const setColWidth = (key: string, w: number) => {
    setWidths(prev => { const n = { ...prev, [key]: w }; persist(colVis, sortKey, sortDir, n); return n; });
  };
  const resetColumns = () => {
    const vis = Object.fromEntries(ALL_COLUMNS.map(c => [c.key, c.defaultOn]));
    const w = Object.fromEntries(ALL_COLUMNS.map(c => [c.key, c.minW]));
    setColVis(vis); setWidths(w); setSortKey(''); setSortDir('asc'); persist(vis, '', 'asc', w);
  };

  // ── Drag-to-Resize ──────────────────────────────────────────────────────
  const [resizeCol, setResizeCol] = useState<string | null>(null);
  const [resizeStartX, setResizeStartX] = useState(0);
  const [resizeStartW, setResizeStartW] = useState(0);

  const onResizeStart = (e: React.MouseEvent, key: string) => {
    e.preventDefault(); e.stopPropagation();
    setResizeCol(key); setResizeStartX(e.clientX); setResizeStartW(widths[key] ?? 160);
  };
  useEffect(() => {
    if (!resizeCol) return;
    const move = (e: MouseEvent) => {
      const delta = e.clientX - resizeStartX;
      const w = Math.max(60, resizeStartW + delta);
      setColWidth(resizeCol, w);
    };
    const up = () => setResizeCol(null);
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
    return () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up); };
  }, [resizeCol, resizeStartX, resizeStartW]);

  // ── Inline editing state ────────────────────────────────────────────────
  const [editing, setEditing] = useState<{ id: string; key: EditableKey } | null>(null);
  const [draft, setDraft] = useState('');
  const [statusMenuId, setStatusMenuId] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const editRef = useRef<HTMLInputElement>(null);
  const showToast = (m: string) => { setToast(m); setTimeout(() => setToast(null), 2200); };

  useEffect(() => { if (editing && editRef.current) { editRef.current.focus(); editRef.current.select(); } }, [editing]);
  useEffect(() => { if (!open) { setShowColPicker(false); setEditing(null); setStatusMenuId(null); setColorEditorOpen(false); } }, [open]);

  const startEdit = (k: KontaktRecord, key: EditableKey, value: string) => {
    if (k.id === savingId) return;
    setEditing({ id: k.id, key }); setDraft(value ?? '');
  };
  const commitEdit = async () => {
    if (!editing) return;
    const k = kontakte.find(x => x.id === editing.id);
    if (!k) { setEditing(null); return; }
    const value = draft.trim();
    if (value === String(k[editing.key] ?? '')) { setEditing(null); return; }
    if (editing.key === 'name' && !value) { showToast('Name darf nicht leer sein'); return; }
    setSavingId(k.id);
    try { await saveField(k, editing.key, value); showToast('Gespeichert ✓'); }
    catch (err: any) { showToast('Fehler: ' + (err?.message || 'unbekannt')); }
    finally { setSavingId(null); setEditing(null); }
  };
  const commitStatus = async (k: KontaktRecord, status: string) => {
    setStatusMenuId(null); setSavingId(k.id);
    try { await saveStatus(k, status); onStatusChange?.(k, status); showToast('Status geändert ✓'); }
    catch (err: any) { showToast('Fehler: ' + (err?.message || 'unbekannt')); }
    finally { setSavingId(null); }
  };

  // ── Status-Farben Editor ────────────────────────────────────────────────
  const openColorEditor = () => {
    setStatusColorDrafts(Object.fromEntries(ALL_STATUS_KEYS().map(s => [s, { ...(statusColors[s] ?? DEFAULT_STATUS_STYLES[s]) }])));
    setColorEditorOpen(true);
  };
  const saveStatusColors = () => {
    // merge over defaults; prune keys identical to default
    const out: Record<string, { bg: string; text: string; border: string }> = {};
    for (const [s, v] of Object.entries(statusColorDrafts)) {
      const def = DEFAULT_STATUS_STYLES[s];
      if (!def || v.bg !== def.bg || v.text !== def.text || v.border !== def.border) out[s] = v;
    }
    try { localStorage.setItem(STATUS_COLOR_KEY, JSON.stringify(out)); } catch {}
    setStatusColors(out); setColorEditorOpen(false);
  };

  // ── Derived ─────────────────────────────────────────────────────────────
  function ALL_STATUS_KEYS(): string[] { return STATUS_COLUMNS.map(c => String(c.id)); }
  const getStatusStyle = (id: string) => {
    const def = DEFAULT_STATUS_STYLES[id] ?? { bg: '#f1f5f9', text: '#475569', border: '#cbd5e1', label: id };
    const ov = statusColors[id];
    return { ...def, ...(ov ?? {}) };
  };

  const visibleCols = ALL_COLUMNS.filter(c => colVis[c.key]);

  const sorted = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filtered = q ? kontakte.filter(k =>
      (k.name || '').toLowerCase().includes(q) ||
      (k.unternehmen || '').toLowerCase().includes(q) ||
      (k.rolle || '').toLowerCase().includes(q)
    ) : kontakte;
    if (!sortKey) return filtered;
    return [...filtered].sort((a, b) => {
      let av = (a[sortKey] ?? '') as string | number;
      let bv = (b[sortKey] ?? '') as string | number;
      if (Array.isArray(av)) av = (av as string[]).join(', ');
      if (Array.isArray(bv)) bv = (bv as string[]).join(', ');
      const cmp = String(av).localeCompare(String(bv), 'de', { sensitivity: 'base' });
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [kontakte, sortKey, sortDir, search]);

  const StatusBadge = ({ id }: { id: string }) => {
    const st = getStatusStyle(String(id));
    return (
      <span style={{ backgroundColor: st.bg, color: st.text, borderColor: st.border }}
        className="inline-flex items-center px-2 py-0.5 rounded-full border text-xs font-medium whitespace-nowrap">
        {st.label}
      </span>
    );
  };

  const renderEditableText = (k: KontaktRecord, col: ColDef) => {
    const key = col.key as EditableKey;
    const isMe = editing?.id === k.id && editing.key === key;
    const saving = savingId === k.id;
    const value = String(k[key] ?? '');
    if (isMe) {
      return (
        <div className="flex items-center gap-1">
          <input ref={editRef} value={draft} onChange={e => setDraft(e.target.value)}
            onBlur={commitEdit} onKeyDown={e => { if (e.key === 'Enter') commitEdit(); if (e.key === 'Escape') setEditing(null); }}
            className={`w-full min-w-[80px] px-1.5 py-0.5 rounded border text-xs outline-none ${isLight ? 'bg-white border-emerald-400' : 'bg-zinc-800 border-emerald-500'}`} />
          {saving ? <Save className="w-3 h-3 animate-pulse text-zinc-400" /> : <Check className="w-3 h-3 text-emerald-500" />}
        </div>
      );
    }
    return (
      <div className="group/cell flex items-center gap-1">
        <button onClick={e => { e.stopPropagation(); startEdit(k, key, value); }}
          className="truncate text-left w-full min-w-0 transition hover:bg-zinc-100/60 dark:hover:bg-zinc-800/40 rounded px-1 py-0.5 cursor-text"
          onDoubleClick={e => { e.stopPropagation(); startEdit(k, key, value); }}>
          {value || <span className="text-zinc-400 italic">—</span>}
        </button>
        <Pencil className={`w-3 h-3 shrink-0 opacity-0 group-hover/cell:opacity-60 ${isLight ? 'text-zinc-400' : 'text-zinc-500'}`} />
      </div>
    );
  };

  const renderCell = (k: KontaktRecord, col: ColDef) => {
    if (col.editable) return renderEditableText(k, col);
    const v = k[col.key];
    if (col.key === 'status') {
      const menuOpen = statusMenuId === k.id;
      return (
        <div className="relative" onClick={e => e.stopPropagation()}>
          <button onClick={() => setStatusMenuId(menuOpen ? null : k.id)}
            className={`flex items-center gap-1 rounded-md px-1 py-0.5 transition ${isLight ? 'hover:bg-zinc-100' : 'hover:bg-zinc-800'} ${savingId === k.id ? 'opacity-60' : ''}`}
            title="Status ändern">
            <StatusBadge id={k.status} />
            <ChevronDown className={`w-3 h-3 ${isLight ? 'text-zinc-400' : 'text-zinc-500'} transition ${menuOpen ? 'rotate-180' : ''}`} />
          </button>
          {menuOpen && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setStatusMenuId(null)} />
              <div className={`absolute left-0 top-full mt-1 z-50 w-52 rounded-xl border shadow-2xl py-1 max-h-64 overflow-auto ${isLight ? 'bg-white border-zinc-200' : 'bg-zinc-900 border-zinc-700'}`}>
                {STATUS_COLUMNS.map(s => (
                  <button key={String(s.id)} onClick={() => commitStatus(k, String(s.id))}
                    className={`w-full flex items-center gap-2 px-3 py-1.5 text-xs transition ${isLight ? 'hover:bg-zinc-50' : 'hover:bg-zinc-800'}`}>
                    <StatusBadge id={String(s.id)} />
                    <span className="ml-auto">{k.status === s.id ? <Check className="w-3 h-3 text-emerald-500" /> : null}</span>
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      );
    }
    if (col.key === 'rating') return <span>{typeof v === 'number' && v > 0 ? '★'.repeat(v) : '—'}</span>;
    if (col.key === 'linkedin_url' && v) {
      return <a href={String(v)} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}
        className="text-blue-500 hover:text-blue-400"><ExternalLink className="w-3.5 h-3.5" /></a>;
    }
    if (col.key === 'vernetzt_am' && v) return <span>{new Date(String(v)).toLocaleDateString('de-DE')}</span>;
    if (!v) return <span className="text-zinc-400">—</span>;
    return <span className="truncate">{String(v)}</span>;
  };

  const SortIcon = ({ col }: { col: ColDef }) => {
    if (sortKey !== col.key) return <ChevronsUpDown className="w-3 h-3 opacity-30" />;
    return sortDir === 'asc' ? <ArrowUp className="w-3 h-3 text-emerald-500" /> : <ArrowDown className="w-3 h-3 text-emerald-500" />;
  };

  return (
    <>
      <div className={`fixed inset-0 z-40 transition-opacity duration-300 ${open ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'} ${isLight ? 'bg-black/20' : 'bg-black/50'}`} onClick={onClose} />

      <div className={`fixed top-0 right-0 h-full z-50 flex flex-col transition-transform duration-300 ease-in-out
        ${open ? 'translate-x-0' : 'translate-x-full'}
        ${isLight ? 'bg-white border-l border-zinc-200 shadow-2xl' : 'bg-zinc-950 border-l border-zinc-800 shadow-2xl'}
        w-[min(92vw,1100px)]`}>

        {/* Header */}
        <div className={`flex items-center justify-between px-5 py-3.5 border-b shrink-0 ${isLight ? 'border-zinc-200' : 'border-zinc-800'}`}>
          <div>
            <h2 className={`text-base font-bold ${isLight ? 'text-zinc-900' : 'text-zinc-100'}`}>{rollenLabel}</h2>
            <p className={`text-xs mt-0.5 ${isLight ? 'text-zinc-500' : 'text-zinc-400'}`}>
              {sorted.length} Kontakte · Klick auf Text = Bearbeiten · auf Zeile = Details
            </p>
          </div>

          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className={`absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 pointer-events-none ${isLight ? 'text-zinc-400' : 'text-zinc-500'}`} />
              <input type="text" value={search} onChange={e => setSearch(e.target.value)} placeholder="Filtern…"
                className={`w-40 pl-8 pr-3 py-1.5 rounded-lg border text-xs outline-none transition ${isLight ? 'bg-zinc-50 border-zinc-200 text-zinc-900 placeholder-zinc-400 focus:border-emerald-400' : 'bg-zinc-800 border-zinc-700 text-zinc-100 placeholder-zinc-500 focus:border-emerald-500'}`} />
            </div>

            {/* Spalten anpassen */}
            <div className="relative">
              <button onClick={() => setShowColPicker(p => !p)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium transition ${isLight ? 'bg-zinc-50 border-zinc-200 text-zinc-700 hover:bg-zinc-100' : 'bg-zinc-800 border-zinc-700 text-zinc-300 hover:bg-zinc-700'}`}>
                <SlidersHorizontal className="w-3.5 h-3.5" /> Spalten <ChevronDown className={`w-3 h-3 transition-transform ${showColPicker ? 'rotate-180' : ''}`} />
              </button>
              {showColPicker && (
                <div className={`absolute right-0 top-full mt-1 w-56 rounded-xl border shadow-2xl z-10 p-2 ${isLight ? 'bg-white border-zinc-200' : 'bg-zinc-900 border-zinc-700'}`}>
                  <div className="flex items-center justify-between px-2 mb-1">
                    <span className="text-[10px] font-bold uppercase tracking-wide text-zinc-400">Spalten</span>
                    <button onClick={resetColumns} className="flex items-center gap-1 text-[10px] text-zinc-400 hover:text-emerald-500"><RotateCcw className="w-3 h-3" /> Reset</button>
                  </div>
                  {ALL_COLUMNS.map(col => (
                    <label key={col.key} className={`flex items-center gap-2 px-2 py-1.5 rounded-lg cursor-pointer select-none ${isLight ? 'hover:bg-zinc-50' : 'hover:bg-zinc-800'}`}>
                      <input type="checkbox" checked={colVis[col.key]} onChange={e => setColumnVisibility(col.key, e.target.checked)} className="accent-emerald-500" />
                      <span className={`text-xs ${isLight ? 'text-zinc-700' : 'text-zinc-300'}`}>{col.label}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>

            {/* Design / Status-Farben */}
            <div className="relative">
              <button onClick={() => setColorEditorOpen(p => !p)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium transition ${isLight ? 'bg-zinc-50 border-zinc-200 text-zinc-700 hover:bg-zinc-100' : 'bg-zinc-800 border-zinc-700 text-zinc-300 hover:bg-zinc-700'}`}>
                <Palette className="w-3.5 h-3.5" /> Status-Farben
              </button>
            </div>

            {/* Zahnrad -> voller CSS-Editor */}
            {onOpenDesign && (
              <button onClick={onOpenDesign} title="Voller Design/CSS-Editor"
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium transition ${isLight ? 'bg-zinc-50 border-zinc-200 text-zinc-700 hover:bg-zinc-100' : 'bg-zinc-800 border-zinc-700 text-zinc-300 hover:bg-zinc-700'}`}>
                <Settings2 className="w-3.5 h-3.5" /> Design
              </button>
            )}

            <button onClick={onClose} className={`p-1.5 rounded-lg transition ${isLight ? 'hover:bg-zinc-100 text-zinc-500' : 'hover:bg-zinc-800 text-zinc-400'}`}><X className="w-4 h-4" /></button>
          </div>
        </div>

        {/* Table (horizontales Scrollen) */}
        <div className="flex-1 overflow-auto min-h-0 w-full">
          <table className="w-full border-collapse text-xs">
            <thead className={`sticky top-0 z-20 ${isLight ? 'bg-zinc-50 border-b border-zinc-200' : 'bg-zinc-900 border-b border-zinc-800'}`}>
              <tr>
                {visibleCols.map(col => (
                  <th key={col.key}
                    onClick={() => setSort(col.key)}
                    style={{ minWidth: col.minW, width: widths[col.key] }}
                    className={`relative px-3 py-2.5 text-left font-semibold uppercase tracking-wide cursor-pointer select-none whitespace-nowrap ${isLight ? 'text-zinc-500 hover:text-zinc-700' : 'text-zinc-400 hover:text-zinc-200'}`}>
                    <span className="flex items-center gap-1">{col.label}<SortIcon col={col} /></span>
                    <div
                      onMouseDown={e => onResizeStart(e, col.key)}
                      onDoubleClick={e => { e.stopPropagation(); setColWidth(col.key, col.minW); }}
                      className={`absolute right-0 top-0 h-full w-1.5 cursor-col-resize transition ${resizeCol === col.key ? 'bg-emerald-400' : 'hover:bg-zinc-300 dark:hover:bg-zinc-600'}`} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.length === 0 && (
                <tr><td colSpan={visibleCols.length} className={`px-4 py-12 text-center text-sm ${isLight ? 'text-zinc-400' : 'text-zinc-500'}`}>Keine Kontakte gefunden.</td></tr>
              )}
              {sorted.map((k, i) => {
                const av = getProfilbildUrl(k);
                const rowEditable = editing?.id === k.id || statusMenuId === k.id;
                return (
                  <tr key={k.id}
                    onClick={() => { if (!rowEditable) { onOpenKontakt(k); onClose(); } }}
                    className={`border-b transition ${isLight ? `${i % 2 === 0 ? 'bg-white' : 'bg-zinc-50/60'} border-zinc-100 hover:bg-blue-50/60` : `${i % 2 === 0 ? 'bg-zinc-950' : 'bg-zinc-900/40'} border-zinc-800 hover:bg-zinc-800/60`} ${savingId === k.id ? 'opacity-60' : ''}`}>
                    {visibleCols.map(col => (
                      <td key={col.key} style={{ minWidth: col.minW }} className={`px-3 py-2.5 max-w-[300px] ${isLight ? 'text-zinc-800' : 'text-zinc-200'} ${col.key === 'name' ? 'font-medium' : ''}`}>
                        {col.key === 'name' && editing?.id === k.id && editing.key === 'name' ? (
                          renderEditableText(k, { key: 'name', label: 'Name', defaultOn: true, minW: 160 })
                        ) : col.key === 'name' ? (
                          <div className="flex items-center gap-2 min-w-0">
                            {av ? <img src={av} className="w-6 h-6 rounded-full object-cover shrink-0" alt="" />
                              : <span className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 ${isLight ? 'bg-zinc-200 text-zinc-600' : 'bg-zinc-700 text-zinc-300'}`}>{(k.name || '?')[0].toUpperCase()}</span>}
                            <button
                              onClick={e => { e.stopPropagation(); onOpenKontakt(k); onClose(); }}
                              title="Profil öffnen"
                              className="truncate text-left font-medium min-w-0 transition hover:underline underline-offset-2 cursor-pointer"
                            >
                              {k.name || '—'}
                            </button>
                            <button
                              onClick={e => { e.stopPropagation(); startEdit(k, 'name', k.name || ''); }}
                              title="Name bearbeiten"
                              className={`p-1 rounded opacity-0 group-hover:opacity-100 transition ${isLight ? 'hover:bg-zinc-100 text-zinc-400' : 'hover:bg-zinc-800 text-zinc-500'}`}
                            >
                              <Pencil className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        ) : renderCell(k, col)}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Footer */}
        <div className={`px-5 py-2.5 border-t text-[11px] shrink-0 flex items-center justify-between ${isLight ? 'border-zinc-200 text-zinc-400' : 'border-zinc-800 text-zinc-500'}`}>
          <span>{sorted.length} von {kontakte.length} Kontakten · Spalten-Höhe ziehen = Breite anpassen</span>
          {toast && <span className={`text-[11px] font-medium ${isLight ? 'text-emerald-600' : 'text-emerald-400'}`}>{toast}</span>}
        </div>
      </div>

      {/* Status-Farben Editor (Overlay) */}
      {colorEditorOpen && (
        <div className="fixed inset-0 z-[60] bg-black/50 flex items-center justify-center p-4" onClick={() => setColorEditorOpen(false)}>
          <div onClick={e => e.stopPropagation()} className={`rounded-2xl border p-5 w-full max-w-lg shadow-2xl max-h-[85vh] overflow-auto ${isLight ? 'bg-white border-zinc-200' : 'bg-zinc-900 border-zinc-800'}`}>
            <div className="flex items-center justify-between mb-3">
              <h3 className={`text-sm font-black flex items-center gap-2 ${isLight ? 'text-zinc-900' : 'text-zinc-100'}`}><Palette className="w-4 h-4 text-emerald-400" /> Status-Farben</h3>
              <button onClick={() => setColorEditorOpen(false)} className={`p-1.5 rounded-md cursor-pointer ${isLight ? 'hover:bg-zinc-100 text-zinc-500' : 'hover:bg-zinc-800 text-zinc-300'}`}><X className="w-4 h-4" /></button>
            </div>
            <div className="space-y-3">
              {ALL_STATUS_KEYS().map(s => {
                const d = statusColorDrafts[s] ?? DEFAULT_STATUS_STYLES[s];
                return (
                  <div key={s} className={`rounded-xl border p-3 ${isLight ? 'border-zinc-200' : 'border-zinc-800'}`}>
                    <div className="flex items-center justify-between mb-2">
                      <span className={`text-xs font-bold ${isLight ? 'text-zinc-700' : 'text-zinc-300'}`}>{DEFAULT_STATUS_STYLES[s]?.label ?? s}</span>
                      <span style={{ backgroundColor: d?.bg, color: d?.text, borderColor: d?.border }} className="px-2 py-0.5 rounded-full border text-xs">Vorschau</span>
                    </div>
                    <div className="flex items-center gap-2">
                      {([
                        ['Hintergrund', 'bg'], ['Text', 'text'], ['Rahmen', 'border'],
                      ] as const).map(([label, field]) => (
                        <label key={field as string} className={`flex items-center gap-1 text-[10px] ${isLight ? 'text-zinc-500' : 'text-zinc-400'}`}>
                          {label}
                          <input type="color" value={d?.[field as 'bg'] || '#000000'}
                            onChange={e => setStatusColorDrafts(prev => ({ ...prev, [s]: { ...(prev[s] ?? DEFAULT_STATUS_STYLES[s]), [field]: e.target.value } }))}
                            className="w-8 h-6 rounded border border-zinc-300 cursor-pointer" />
                        </label>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="flex gap-2 mt-4">
              <button onClick={saveStatusColors} className="flex-1 px-3 py-2 rounded-xl text-xs font-bold bg-emerald-500 text-white hover:opacity-90">Speichern</button>
              <button onClick={() => { try { localStorage.removeItem(STATUS_COLOR_KEY); } catch {} setStatusColors({}); setColorEditorOpen(false); }}
                className="px-3 py-2 rounded-xl text-xs font-bold bg-zinc-200 hover:bg-zinc-300">Zurücksetzen</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
