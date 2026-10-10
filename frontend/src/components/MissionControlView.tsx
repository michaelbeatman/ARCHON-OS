"use client";

import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Users, Building2, UserRound, MessageSquare, Target, AlertCircle,
  Database, Calendar as CalendarIcon, ExternalLink, Copy, Check,
  Sparkles, Loader2, Clipboard, PenLine, X, User, Briefcase, DoorOpen,
  Search, ArrowRight, Info
} from 'lucide-react';
import { pb, KontaktRecord, getProfilbildUrl } from '@/lib/pocketbase';
import { isContactStagnated } from './PipelineAnalytics';
import { RollenListePanel } from './RollenListePanel';

interface Props {
  kontakte: KontaktRecord[];
  themeMode: 'light' | 'dark';
  onOpenKontakt?: (k: KontaktRecord) => void;
  onNavigateToKontakte?: () => void;
  onOpenDesign?: () => void;
  onKontaktUpdate?: (k: KontaktRecord) => void; // Live-Update eines Kontakts (z.B. Status) in die Elternstate
}

interface Termin {
  id: string;
  titel: string;
  start: string;
  ende?: string;
  ort?: string;
  kontaktId?: string;
}

const OMNI_BASE = 'http://localhost:20128/v1';

export function MissionControlView({ kontakte, themeMode, onOpenKontakt, onNavigateToKontakte, onOpenDesign, onKontaktUpdate }: Props) {
  const isLight = themeMode === 'light';

  // ── Kontakt-Suche ─────────────────────────────────────────────────────
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<KontaktRecord[]>([]);
  const [searchFocused, setSearchFocused] = useState(false);
  const [highlightIdx, setHighlightIdx] = useState(0);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) { setSearchResults([]); return; }
    const hits = kontakte.filter(k =>
      (k.name || '').toLowerCase().includes(q) ||
      (k.unternehmen || '').toLowerCase().includes(q) ||
      (k.rolle || '').toLowerCase().includes(q)
    ).slice(0, 8);
    setSearchResults(hits);
    setHighlightIdx(0);
  }, [searchQuery, kontakte]);

  const openContact = (k: KontaktRecord) => {
    setSearchQuery('');
    setSearchResults([]);
    onNavigateToKontakte?.();
    // small delay so nav switches before drawer opens
    setTimeout(() => onOpenKontakt?.(k), 50);
  };

  const handleSearchSubmit = () => {
    const target = searchResults[highlightIdx] ?? searchResults[0];
    if (target) openContact(target);
  };

  const handleSearchKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setHighlightIdx(i => Math.min(i + 1, searchResults.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHighlightIdx(i => Math.max(i - 1, 0)); }
    else if (e.key === 'Enter') { e.preventDefault(); handleSearchSubmit(); }
    else if (e.key === 'Escape') { setSearchQuery(''); setSearchResults([]); }
  };

  // ── Termine ───────────────────────────────────────────────────────────
  const [termine, setTermine] = useState<Termin[]>([]);
  const [termineLoaded, setTermineLoaded] = useState(false);

  const loadTermine = useCallback(async () => {
    try {
      const list = await pb.collection('termine').getFullList<any>({
        sort: 'start',
        requestKey: null,
      });
      setTermine((list as any[]).map((rec: any): Termin => ({
        id: rec.id,
        titel: rec.titel || 'Ohne Titel',
        start: rec.start,
        ende: rec.ende || undefined,
        ort: rec.ort || undefined,
        kontaktId: rec.kontakt || undefined,
      })));
    } catch (err: any) {
      console.warn('termine laden fehlgeschlagen:', err?.message || err);
    }
    setTermineLoaded(true);
  }, []);

  useEffect(() => { loadTermine(); }, [loadTermine]);

  const kontaktById = useCallback((id?: string) => kontakte.find(k => k.id === id), [kontakte]);

  const now = Date.now();
  const upcoming = termine
    .filter(t => new Date(t.start).getTime() >= now - 1000 * 60 * 60)
    .sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime())
    .slice(0, 5);

  const formatTerminBadge = (start: string) => {
    const d = new Date(start);
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const that = new Date(d); that.setHours(0, 0, 0, 0);
    const diff = Math.round((that.getTime() - today.getTime()) / 86400000);
    const time = d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
    if (diff === 0) return `Heute, ${time} Uhr`;
    if (diff === 1) return `Morgen, ${time} Uhr`;
    return `${d.toLocaleDateString('de-DE', { weekday: 'short', day: '2-digit', month: '2-digit' })}, ${time} Uhr`;
  };

  // ── Status & Conversion ───────────────────────────────────────────────
  // Gesperrte und Unvernetzte Kontakte komplett aus der aktiven Statistik ausschließen
  const aktiveKontakte = kontakte.filter(k =>
    k.status !== 'Gesperrt_1Jahr' &&
    k.status !== 'Kein_Interesse' &&
    k.status !== 'Unvernetzt' &&
    k.status !== 'Irrelevant'
  );
  const countStatus = (s: string) => aktiveKontakte.filter(k => k.status === s).length;
  const total = aktiveKontakte.length;
  const erstNachricht = countStatus('Erstnachricht');
  const imDialog = countStatus('Im Dialog');
  const interview = countStatus('Interview vereinbart');

  const replyRate = (erstNachricht + imDialog) > 0 ? Math.round((imDialog / (erstNachricht + imDialog)) * 100) : 0;
  const meetingRate = (imDialog + interview) > 0 ? Math.round((interview / (imDialog + interview)) * 100) : 0;

  // ── Rollen ────────────────────────────────────────────────────────────
  const re_GF = /(geschäftsführer|geschaeftsfuehrer|inhaber|eigentümer|eigentuemer|gründer|gruender|ceo|founder|co-founder|managing director|president|owner|partner)/i;
  const re_Exec = /(executive search|headhunter|personalberater|talent acquisition|recruiter|recruiting|talent partners)/i;
  const re_Decision = /(entscheider|decision|bereichsleiter|division|vorstand|board|leadership|leitung|director|vp[ .-]|vice president|chief)/i;
  const re_HR = /(human resources|personalleiter|hr manager|\\bhr\\b|personal|talent)/i;
  const re_Interim = /(interim|freiberuflich|freelance|selbstständig|selbststaendig|consultant|freelancer)/i;
  const re_Investor = /(private equity|\bpe\b|investor|investment|venture capital|beteiligungsgesellschaft|family office|angel investor|kapitalgeber|fonds|fund manager)/i;
  const re_Finance = /(\bcfo\b|chief financial|finanzleiter|finance director|controlling|treasury|\bbank\b|finanz)/i;
  const re_Consulting = /(consultant|consulting|berater|beratung|advisor|advisory|strategy|unternehmensberatung|business development|matchmaker)/i;
  const re_Quality = /(qualified person|quality|gmp|gdp|regulatory|zulassung|compliance|good manufacturing|sterile|quality manager|quality director|qm\b|regulatory affairs)/i;
  
  // ── Einheitliche Zuordnung: alle verfügbaren Textfelder als ein Pool prüfen ──
  // Reihenfolge = Priorität. Erster Treffer gewinnt.
  // WICHTIG: `exec` (Recruiter/Executive-Search) steht ganz oben, da "Executive Search",
  // "Headhunter", "Recruiter" eindeutige Marker sind und sonst durch generische Begriffe
  // wie "Partner"/"Director"/"Consultant" fälschlich als GF/Entscheider/Interim einsortiert würden.
  // Der new hinzugekommene LinkedIn-Header (LinkedInheader / Linkedin_info) wird MITGEPRÜFT,
  // damit die reichere Headline die Zuordnung verbessert; keine Feld hat Vorrang.
  const kontaktText = (k: KontaktRecord): string =>
    `${k.rolle || ''} ${k.RollenVerteilungzuordnung || ''} ${k.LinkedInheader || ''} ${k.Linkedin_info || ''}`;
  const ROLL_GROUP_DEFS = [
    { key: 'exec',    label: 'Recruiter / Exec-Search', match: (k: KontaktRecord) => re_Exec.test(kontaktText(k)) },
    { key: 'gf',      label: 'GF / Inhaber',            match: (k: KontaktRecord) => re_GF.test(kontaktText(k)) },
    { key: 'decision',label: 'Entscheider / Führung',   match: (k: KontaktRecord) => re_Decision.test(kontaktText(k)) },
    { key: 'investor',label: 'Investor / PE',           match: (k: KontaktRecord) => re_Investor.test(kontaktText(k)) },
    { key: 'hr',      label: 'HR / Personal',           match: (k: KontaktRecord) => re_HR.test(kontaktText(k)) },
    { key: 'finance', label: 'Finance / CFO',           match: (k: KontaktRecord) => re_Finance.test(kontaktText(k)) },
    { key: 'interim', label: 'Interim / Freiberuflich', match: (k: KontaktRecord) => re_Interim.test(kontaktText(k)) },
    { key: 'consult', label: 'Consulting',              match: (k: KontaktRecord) => re_Consulting.test(kontaktText(k)) },
    { key: 'quality', label: 'Quality / GMP',           match: (k: KontaktRecord) => re_Quality.test(kontaktText(k)) },
  ];

  // Ein Kontakt gehört zur ERSTEN passenden Gruppe (Prioritätsreihenfolge).
  const assignGroup = (k: KontaktRecord): string => {
    const g = ROLL_GROUP_DEFS.find(def => def.match(k));
    return g ? g.key : 'sonstig';
  };

  const groupKeyToLabel = (key: string): string => {
    const def = ROLL_GROUP_DEFS.find(d => d.key === key);
    return def ? def.label : 'Sonstige';
  };

  // ── Hilfetexte für die Info-Icons der Rollen-Gruppen ─────────────────────
  // Beschreibt, welche Personen/Gruppen eingeordnet werden und welche
  // Begriffe (Keywords) für die automatische Zuordnung zählen.
  const ROLL_INFO: Record<string, { was: string; begriffe: string }> = {
    gf: {
      was: 'Unternehmer, Gründer, Inhaber und Geschäftsführer (inkl. Managing Director, CEO, Präsident, Eigentümer, Owner, Partner). Entscheider, die das Unternehmen führen bzw. besitzen.',
      begriffe: 'Geschäftsführer, Inhaber, Eigentümer, Gründer, CEO, Founder, Co-Founder, Managing Director, President, Owner, Partner',
    },
    exec: {
      was: 'Recruiter und Executive-Search-Dienstleister, Headhunter, Personalberater, Talentsuchende.',
      begriffe: 'Executive Search, Headhunter, Personalberater, Talent Acquisition, Recruiter, Recruiting, Talent Partners',
    },
    decision: {
      was: 'Führungskräfte und Entscheider unterhalb der Geschäftsführung: Bereichsleiter, Vorstand, Director, VP, Division-Leiter, Chief-* (z. B. CCO, CTO).',
      begriffe: 'Entscheider, Decision, Bereichsleiter, Division, Vorstand, Board, Leadership, Leitung, Director, VP, Vice President, Chief',
    },
    investor: {
      was: 'Investoren, Private-Equity-, Venture-Capital- und Beteiligungsgesellschaften, Family Offices, Fonds- und Anlagegeber.',
      begriffe: 'Private Equity, PE, Investor, Investment, Venture Capital, Beteiligungsgesellschaft, Family Office, Angel Investor, Kapitalgeber, Fonds, Fund Manager',
    },
    hr: {
      was: 'Personalabteilungen und HR-Verantwortliche (Recruiting, Personalentwicklung, People & Culture).',
      begriffe: 'Human Resources, Personalleiter, HR Manager, HR, Personal, Talent',
    },
    finance: {
      was: 'Finanzverantwortliche: CFO, Finanzleiter, Controlling, Treasury, Banken und Finanzexperten.',
      begriffe: 'CFO, Chief Financial, Finanzleiter, Finance Director, Controlling, Treasury, Bank, Finanz',
    },
    interim: {
      was: 'Interim-Manager und Freiberufliche/Freelancer (zeitweise Projekt- und Führungsrollen).',
      begriffe: 'Interim, Freiberuflich, Freelance, Selbstständig, Consultant, Freelancer',
    },
    consult: {
      was: 'Beratung und Consulting: Unternehmensberater, Strategen, Advisor, Business Development und Matchmaker.',
      begriffe: 'Consultant, Consulting, Berater, Beratung, Advisor, Advisory, Strategy, Unternehmensberatung, Business Development, Matchmaker',
    },
    quality: {
      was: 'Qualitäts- und Regulatorik-Verantwortliche in Pharma/Medizin: Qualified Person, GMP/GDP, QM, Zulassung/Regulatory.',
      begriffe: 'Qualified Person, Quality, GMP, GDP, Regulatory, Zulassung, Compliance, Good Manufacturing, Sterile, Quality Manager, QM, Regulatory Affairs',
    },
    sonstig: {
      was: 'Alle übrigen Kontakte, die keiner der oben genannten Kategorien zugeordnet werden konnten.',
      begriffe: '–',
    },
  };

  // Welcher Info-Tooltip gerade offen ist
  const [openHelp, setOpenHelp] = useState<string | null>(null);

  // Gruppen-Zählung (einmalig, für alle Anzeigen konsistent)
  const groupMap = new Map<string, KontaktRecord[]>();
  for (const k of aktiveKontakte) {
    const g = assignGroup(k);
    if (!groupMap.has(g)) groupMap.set(g, []);
    groupMap.get(g)!.push(k);
  }
  const countOf = (key: string) => groupMap.get(key)?.length || 0;

  const gfCount       = countOf('gf');
  const decisionCount = countOf('decision');
  const investorCount = countOf('investor');
  const execCount     = countOf('exec');
  const hrCount       = countOf('hr');
  const financeCount  = countOf('finance');
  const interimCount  = countOf('interim');
  const consultingCount = countOf('consult');
  const qualityCount  = countOf('quality');
  const otherCount    = groupMap.get('sonstig')?.length || 0;

const hasMsg = (k: KontaktRecord) => {
    const nv = k.nachrichtenverlauf;
    if (Array.isArray(nv)) return nv.length > 0;
    if (typeof nv === 'string') { try { return (JSON.parse(nv) as unknown[]).length > 0; } catch { return true; } }
    return false;
  };
  const execNoMsg = aktiveKontakte.filter(k => re_Exec.test(kontaktText(k)) && !hasMsg(k));
  const gfNoMsg = aktiveKontakte.filter(k => re_GF.test(kontaktText(k)) && !hasMsg(k));

  const getConnectedTimestamp = (k: KontaktRecord) => {
    if (k.vernetzt_am) {
      const t = new Date(k.vernetzt_am).getTime();
      if (!isNaN(t) && t > 0) return t;
    }
    const t = new Date(k.created || 0).getTime();
    return isNaN(t) ? 0 : t;
  };

  const stagnantTotal = aktiveKontakte.filter(k =>
    k.status !== 'Parkposition' &&
    k.status !== 'Pool' &&
    isContactStagnated(k, 14)
  );
  // Älteste Vernetzung ganz oben
  const stagnantSorted = [...stagnantTotal].sort((a, b) => getConnectedTimestamp(a) - getConnectedTimestamp(b));

  const actions: { key: string; icon: React.ReactNode; text: string; count: number; list: KontaktRecord[] }[] = [];
  if (stagnantSorted.length > 0) {
    actions.push({
      key: 'stagnant',
      icon: <AlertCircle className="w-4 h-4" />,
      text: 'Aktive Kontakte überprüfen',
      count: stagnantSorted.length,
      list: stagnantSorted.slice(0, 8)
    });
  }
  if (execNoMsg.length > 0) actions.push({ key: 'execs', icon: <Target className="w-4 h-4" />, text: 'Recruiter / Executive-Search ansprechen', count: execNoMsg.length, list: execNoMsg.slice(0, 6) });
  if (gfNoMsg.length > 0) actions.push({ key: 'gfs', icon: <UserRound className="w-4 h-4" />, text: 'Geschäftsführer / Entscheider ansprechen', count: gfNoMsg.length, list: gfNoMsg.slice(0, 6) });

  // ── Letzte Kontakte (für Mitte statt Funnel) ──────────────────────────
  const lastContacts = [...aktiveKontakte]
    .sort((a, b) => new Date(b.updated || b.created || 0).getTime() - new Date(a.updated || a.created || 0).getTime())
    .slice(0, 4);

  // ── KI-Follow-up ──────────────────────────────────────────────────────
  const [aiModal, setAiModal] = useState<{ kontakt: KontaktRecord; action: string } | null>(null);
  const [aiDraft, setAiDraft] = useState('');
  const [aiLoading, setAiLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  const buildHistory = (k: KontaktRecord): string => {
    const msgs = Array.isArray(k.nachrichtenverlauf) ? k.nachrichtenverlauf : [];
    if (!msgs.length) return 'Bisher kein Verlauf vorhanden.';
    return msgs.slice(-6).map((m: any) => {
      const who = (m.absender === 'ich' || m.absender === 'user' || m.richtung === 'ausgehend') ? 'Ich' : (k.name || 'Kontakt');
      return `[${m.datum || m.timestamp || m.date || ''}] ${who}: ${m.text || m.inhalt || ''}`;
    }).join('\n');
  };

  const generateDraft = async () => {
    if (!aiModal) return;
    setAiLoading(true); setAiDraft(''); setCopied(false);
    try {
      const history = buildHistory(aiModal.kontakt);
      const prompt =
        'Du bist ein diskreter, hochprofessioneller B2B-Assistent. Schreibe ein kurzes, persönliches und unaufdringliches Follow-up (max. 3-4 Sätze) auf Deutsch basierend auf dem folgenden bisherigen Verlauf:\n\n' +
        history;
      const res = await fetch(`${OMNI_BASE}/chat/completions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: 'omniroute',
          messages: [
            { role: 'system', content: 'Du bist ein diskreter, hochprofessioneller B2B-Assistent für deutschsprachige Follow-ups.' },
            { role: 'user', content: prompt },
          ],
          temperature: 0.7,
          max_tokens: 150,
        }),
      });
      const data = await res.json().catch(() => ({}));
      const text: string = data?.choices?.[0]?.message?.content?.trim?.();
      if (text) { setAiDraft(text); return; }
      setAiDraft('⚠ Keine KI-Antwort erhalten. (OmniRoute erreichbar, aber leere Antwort.)');
    } catch (err) {
      setAiDraft('⚠ Es konnte keine KI-Antwort geladen werden. OmniRoute unter ' + OMNI_BASE + ' ist nicht erreichbar – starte den Dienst bzw. prüfe die URL.');
    } finally {
      setAiLoading(false);
    }
  };

  const copyDraft = async () => {
    try { await navigator.clipboard.writeText(aiDraft); setCopied(true); setTimeout(() => setCopied(false), 1800); } catch {}
  };

  const statuses = ['Vernetzt', 'Erstnachricht', 'Im Dialog', 'Interview vereinbart', 'Regelmäßiger Kontakt', 'Parkposition'];

  const gesperrtCount = kontakte.length - aktiveKontakte.length;
  const pct = (n: number) => (aktiveKontakte.length ? Math.round((n / aktiveKontakte.length) * 100) : 0);
  const maxRole = Math.max(gfCount, execCount, decisionCount, hrCount, interimCount, financeCount, consultingCount, qualityCount, investorCount, 1);
  const maxStatus = Math.max(...statuses.map(s => countStatus(s)), 1);
  const maxFunnel = Math.max(countStatus('Vernetzt'), erstNachricht, imDialog, interview, 1);

  const card = `rounded-xl border bg-white dark:bg-zinc-900 p-3 flex flex-col ${
    isLight ? 'border-zinc-200 shadow-md' : 'border-zinc-800 shadow-[0_4px_16px_0_rgba(0,0,0,0.35)]'
  }`;
  const h3cls = `text-[15px] font-black uppercase tracking-wider mb-2 flex items-center gap-1.5 ${isLight ? 'text-zinc-500' : 'text-zinc-400'}`;
  const accent = 'text-[var(--mission-accent,#10b981)]';

  // KPI cards: compact + plain black value text (not red)
  const kpis = [
    { label: 'Aktive Kontakte', value: aktiveKontakte.length, icon: <Users className="w-4 h-4" />, sub: 'Netzwerk' },
    { label: 'Reply-Rate', value: `${replyRate}%`, icon: <MessageSquare className="w-4 h-4" />, sub: '→ Dialog' },
    { label: 'Meeting-Rate', value: `${meetingRate}%`, icon: <CalendarIcon className="w-4 h-4" />, sub: '→ Interview' },
    { label: 'Recruiter / Exec', value: execCount, icon: <Target className="w-4 h-4" />, sub: `${execNoMsg.length} offen` },
    { label: 'Stagniert', value: stagnantTotal.length, icon: <AlertCircle className="w-4 h-4" />, sub: 'überprüfen' },
    { label: 'Nächste Termine', value: upcoming.length, icon: <CalendarIcon className="w-4 h-4" />, sub: 'kommende' },
  ];

  // Rollen-Einträge (aus der einheitlichen Zuordnung)
  // ANZEIGE-Reihenfolge exakt nach Vorgabe des Nutzers – unabhängig von der
  // Zuordnungs-Priorität (die in ROLL_GROUP_DEFS für die Klassifikation gilt).
  const ROLL_DISPLAY_ORDER = ['gf', 'decision', 'investor', 'exec', 'hr', 'finance', 'interim', 'consult', 'quality'];
  const rollRows = [
    ...ROLL_DISPLAY_ORDER
      .map(key => {
        const def = ROLL_GROUP_DEFS.find(d => d.key === key)!;
        return { key, label: def.label, value: groupMap.get(key)?.length || 0, filter: (k: KontaktRecord) => assignGroup(k) === key };
      }),
    { key: 'sonstig', label: 'Sonstige', value: otherCount, filter: (k: KontaktRecord) => assignGroup(k) === 'sonstig' },
  ];

  // Rollen-Liste Panel State
  const [selectedRolle, setSelectedRolle] = useState<{ label: string; kontakte: KontaktRecord[] } | null>(null);
  const openRollePanel = (row: typeof rollRows[0]) => {
    setSelectedRolle({ label: row.label, kontakte: aktiveKontakte.filter(row.filter) });
  };

  return (
    <div className="h-full flex flex-col min-h-0 gap-4 overflow-auto pr-1 mission-control-root">

      {/* KPI-Zeile (kleiner, schwarzer Wert) */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-2 shrink-0">
        {kpis.map((k, i) => (
          <div key={i} className={`rounded-xl border bg-white dark:bg-zinc-900 p-2.5 flex flex-col gap-1 ${
            isLight ? 'border-zinc-200 shadow-md' : 'border-zinc-800 shadow-[0_4px_16px_0_rgba(0,0,0,0.35)]'
          }`}>
            <div className="flex items-center justify-between">
              <span className={`text-[15px] font-mono font-bold uppercase tracking-wide truncate ${isLight ? 'text-zinc-400' : 'text-zinc-500'}`}>{k.label}</span>
              <span className={`w-5 h-5 rounded-md flex items-center justify-center shrink-0 ${accent} ${isLight ? 'bg-emerald-50' : 'bg-emerald-500/15'}`}>{k.icon}</span>
            </div>
            <div className={`text-[22px] leading-none font-bold tracking-tight ${isLight ? 'text-zinc-900' : 'text-zinc-100'}`}>{k.value}</div>

          </div>
        ))}
      </div>

      {/* 3-Spalten: links Rollen+Status, Mitte Funnel+Termine, rechts Aktionen */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 flex-1 min-h-0">
                {/* Spalte 1: Rollen oben, Status darunter */}
        <div className="flex flex-col gap-4 min-h-0 overflow-y-auto pr-1">
          <div className={card}>
            <h3 className={h3cls}><Building2 className={`w-3.5 h-3.5 ${accent}`} /> Rollen-Verteilung</h3>
            <div className="space-y-2">
              {rollRows.map((row, i) => (
                <div key={i} className="relative">
                  <div className="flex items-center justify-between text-[14px]">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <button
                        onClick={() => openRollePanel(row)}
                        className={`font-semibold truncate text-left transition hover:underline underline-offset-2 cursor-pointer ${
                          isLight ? 'text-zinc-700 hover:text-accent-main' : 'text-zinc-300 hover:text-accent-main'
                        }`}
                      >
                        {row.label}
                      </button>
                      {/* Info-Icon: öffnet Beschreibung + Keywords der Gruppe */}
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); setOpenHelp(openHelp === row.key ? null : row.key); }}
                        className={`p-0.5 rounded-full shrink-0 transition cursor-pointer ${
                          openHelp === row.key
                            ? 'text-accent-main bg-accent-light'
                            : isLight ? 'text-zinc-400 hover:text-accent-main hover:bg-zinc-100' : 'text-zinc-500 hover:text-accent-main hover:bg-zinc-800'
                        }`}
                        title="Was gehört zu dieser Gruppe?"
                      >
                        <Info className="w-3.5 h-3.5" />
                      </button>
                    </div>
                    <span className={`font-mono font-bold shrink-0 ${isLight ? 'text-zinc-500' : 'text-zinc-400'}`}>{row.value} ({pct(row.value)}%)</span>
                  </div>
                  <div className={`mt-0.5 h-1 rounded-full overflow-hidden ${isLight ? 'bg-zinc-100' : 'bg-zinc-800'}`}>
                    <div className="h-full rounded-full bg-[var(--mission-accent,#10b981)]" style={{ width: `${Math.round((row.value / maxRole) * 100)}%` }} />
                  </div>

                  {/* Info-Popover */}
                  {openHelp === row.key && (
                    <div
                      onClick={(e) => e.stopPropagation()}
                      className={`absolute left-0 top-full mt-1 z-30 w-72 rounded-xl border shadow-2xl p-3 text-xs ${
                        isLight ? 'bg-white border-zinc-200 text-zinc-700' : 'bg-zinc-900 border-zinc-700 text-zinc-200'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2 mb-1.5">
                        <span className={`font-bold ${isLight ? 'text-zinc-800' : 'text-zinc-100'}`}>{row.label}</span>
                        <button type="button" onClick={() => setOpenHelp(null)}
                          className={`p-0.5 rounded cursor-pointer ${isLight ? 'text-zinc-400 hover:text-zinc-600 hover:bg-zinc-100' : 'text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800'}`}>
                          <X className="w-3 h-3" />
                        </button>
                      </div>
                      <p className={`mb-2 leading-relaxed ${isLight ? 'text-zinc-600' : 'text-zinc-300'}`}>{ROLL_INFO[row.key]?.was}</p>
                      <div className={`pt-1.5 border-t ${isLight ? 'border-zinc-200' : 'border-zinc-700'}`}>
                        <span className={`block text-[10px] font-bold uppercase tracking-wide mb-1 ${isLight ? 'text-zinc-400' : 'text-zinc-500'}`}>Zugeordnete Begriffe</span>
                        <p className={`font-mono text-[10px] leading-snug ${isLight ? 'text-zinc-500' : 'text-zinc-400'}`}>{ROLL_INFO[row.key]?.begriffe}</p>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div className={card}>
            <h3 className={h3cls}><Database className={`w-3.5 h-3.5 ${accent}`} /> Status-Verteilung</h3>
            <div className="space-y-1.5">
              {statuses.map(s => {
                const n = countStatus(s);
                return (
                  <div key={s}>
                    <div className="flex items-center justify-between text-[14px]">
                      <span className={`font-semibold truncate ${isLight ? 'text-zinc-700' : 'text-zinc-300'}`}>{s}</span>
                      <span className="font-mono font-bold shrink-0 text-zinc-400">{n}</span>
                    </div>
                    <div className={`mt-0.5 h-1 rounded-full overflow-hidden ${isLight ? 'bg-zinc-100' : 'bg-zinc-800'}`}>
                      <div className="h-full rounded-full bg-[var(--mission-accent,#10b981)]" style={{ width: `${Math.round((n / maxStatus) * 100)}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Spalte 2 (Mitte): Letzte Kontakte + Nächste Termine */}
        <div className="flex flex-col gap-4 min-h-0 overflow-y-auto pr-1">
          <div className={card}>
            <h3 className={h3cls}><UserRound className={`w-3.5 h-3.5 ${accent}`} /> Letzte Kontakte</h3>
            {lastContacts.length === 0 ? (
              <div className={`text-[15px] italic ${isLight ? 'text-zinc-400' : 'text-zinc-500'}`}>Noch keine Kontakte vorhanden.</div>
            ) : (
              <div className="space-y-2">
                {lastContacts.map(k => {
                  const av = getProfilbildUrl(k);
                  return (
                    <button
                      key={k.id}
                      onClick={() => onOpenKontakt?.(k)}
                      title="Profil öffnen"
                      className={`w-full text-left rounded-lg border p-2 flex items-center gap-2.5 transition ${
                        isLight
                          ? 'border-zinc-200 bg-zinc-50/60 hover:bg-blue-50/60 hover:border-zinc-300'
                          : 'border-zinc-800 bg-zinc-900/40 hover:bg-zinc-800/60'
                      }`}
                    >
                      {av ? <img src={av} className="w-9 h-9 rounded-full object-cover shrink-0" alt="" />
                        : <span className={`w-9 h-9 rounded-full flex items-center justify-center text-[13px] font-bold shrink-0 ${
                            isLight ? 'bg-zinc-200 text-zinc-600' : 'bg-zinc-700 text-zinc-300'
                          }`}>{(k.name || '?')[0].toUpperCase()}</span>}
                      <div className="flex-1 min-w-0">
                        <div className={`text-[15px] font-bold truncate ${isLight ? 'text-zinc-800' : 'text-zinc-100'}`}>{k.name}</div>
                        {k.LinkedInheader && (
                          <div className={`text-[12px] italic truncate ${isLight ? 'text-zinc-400' : 'text-zinc-500'}`}>{k.LinkedInheader}</div>
                        )}
                        <div className={`text-[13px] truncate ${isLight ? 'text-zinc-500' : 'text-zinc-400'}`}>
                          {k.unternehmen || k.rolle || ''}
                        </div>
                      </div>
                      <span className={`shrink-0 text-[11px] font-mono ${
                        isLight ? 'text-zinc-400' : 'text-zinc-500'
                      }`}>{k.updated ? new Date(k.updated).toLocaleDateString('de-DE') : ''}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <div className={card}>
            <h3 className={h3cls}><CalendarIcon className={`w-3.5 h-3.5 ${accent}`} /> Nächste Termine & Interviews</h3>
            {!termineLoaded ? (
              <div className="text-[15px] text-zinc-400 animate-pulse">Lade Termine…</div>
            ) : upcoming.length === 0 ? (
              <div className="text-[15px] italic text-zinc-400">Aktuell keine anstehenden Termine geplant.</div>
            ) : (
              <div className="space-y-2">
                {upcoming.map(t => {
                  const k = kontaktById(t.kontaktId);
                  const av = k ? getProfilbildUrl(k) : null;
                  return (
                    <button
                      key={t.id}
                      onClick={() => k && onOpenKontakt?.(k)}
                      className={`w-full text-left rounded-lg border p-2 flex items-center gap-2 ${
                        isLight ? 'border-zinc-200 bg-zinc-50/40 hover:bg-blue-50/60' : 'border-zinc-800 bg-zinc-900/40 hover:bg-zinc-800/60'
                      }`}
                    >
                      {av ? <img src={av} className="w-6 h-6 rounded-full object-cover" alt="" />
                        : <span className={`w-6 h-6 rounded-full flex items-center justify-center text-[15px] font-bold ${isLight ? 'bg-zinc-100 text-zinc-500' : 'bg-zinc-800 text-zinc-300'}`}>{k?.name?.[0]?.toUpperCase() || '•'}</span>}
                      <div className="flex-1 min-w-0">
                        <div className={`text-[15px] font-bold truncate ${isLight ? 'text-zinc-800' : 'text-zinc-100'}`}>{k ? k.name : t.titel}</div>
                        <div className="text-[14px] truncate opacity-70">{k?.unternehmen || k?.rolle || t.ort || t.titel}</div>
                      </div>
                      <span className={`shrink-0 px-1.5 py-0.5 rounded text-[13px] font-bold ${isLight ? 'bg-emerald-50 text-emerald-700' : 'bg-emerald-500/15 text-emerald-300'}`}>{formatTerminBadge(t.start)}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>

{/* Spalte 3: Was heute tun */}
        <div className="flex flex-col min-h-0">
          <div className={card + ' flex-1 min-h-0'}>
            <h3 className={h3cls}><Sparkles className={`w-3.5 h-3.5 ${accent}`} /> Was heute tun?</h3>
            {actions.length === 0 ? (
              <div className="flex-1 flex flex-col items-center justify-center text-center gap-2 text-zinc-400">
                <span className="text-2xl">✓</span>
                <p className="text-xs">Keine dringenden Handlungen.</p>
              </div>
            ) : (
              <div className="flex-1 overflow-y-auto space-y-2.5 pr-1">
                {actions.map(a => (
                  <div key={a.key} className={`rounded-xl border p-2.5 flex flex-col gap-2 ${
                    isLight ? 'border-zinc-200 shadow-md' : 'border-zinc-800 shadow-[0_4px_16px_0_rgba(0,0,0,0.35)]'
                  }`}>
                    <div className="flex items-center justify-between">
                      <span className={`text-[14px] font-bold flex items-center gap-1.5 ${isLight ? 'text-zinc-800' : 'text-zinc-100'}`}>
                        <span className={accent}>{a.icon}</span>{a.text}
                      </span>
                      <span className={`text-base font-black ${isLight ? 'text-zinc-800' : 'text-zinc-100'}`}>{a.count}</span>
                    </div>

                    <div className="space-y-1">
                      {a.list.map(k => {
                        const av = getProfilbildUrl(k);
                        const vernetztStr = k.vernetzt_am
                          ? new Date(k.vernetzt_am).toLocaleDateString('de-DE')
                          : (k.created ? new Date(k.created).toLocaleDateString('de-DE') : '');

                        return (
                          <button
                            key={k.id}
                            type="button"
                            onClick={() => onOpenKontakt?.(k)}
                            title="Kontaktprofil öffnen & bearbeiten"
                            className={`w-full text-left rounded-lg p-1.5 px-2 flex items-center gap-2 border transition cursor-pointer ${
                              isLight
                                ? 'border-zinc-200/80 bg-zinc-50 hover:bg-blue-50/80 hover:border-zinc-300 text-zinc-800'
                                : 'border-zinc-800/80 bg-zinc-800/40 hover:bg-zinc-800 hover:border-zinc-700 text-zinc-100'
                            }`}
                          >
                            {av ? (
                              <img src={av} className="w-6 h-6 rounded-full object-cover shrink-0" alt="" />
                            ) : (
                              <span className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 ${
                                isLight ? 'bg-zinc-200 text-zinc-600' : 'bg-zinc-700 text-zinc-300'
                              }`}>
                                {(k.name || '?')[0].toUpperCase()}
                              </span>
                            )}

                            <div className="flex-1 min-w-0">
                              <div className="text-[13px] font-bold truncate flex items-center justify-between">
                                <span className="truncate">{k.name}</span>
                                {vernetztStr && (
                                  <span className={`text-[10px] font-mono shrink-0 ml-1.5 font-normal ${isLight ? 'text-zinc-400' : 'text-zinc-500'}`} title="Vernetzt am">
                                    {vernetztStr}
                                  </span>
                                )}
                              </div>
                              <div className={`text-[11px] truncate ${isLight ? 'text-zinc-500' : 'text-zinc-400'}`}>
                                {k.unternehmen || k.rolle || ''}
                              </div>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* AI-Modal */}
      {aiModal && (
        <div className="fixed inset-0 z-[199] bg-black/60 flex items-center justify-center p-4" onClick={() => setAiModal(null)}>
          <div onClick={(e) => e.stopPropagation()} className={`rounded-2xl border p-5 w-full max-w-lg shadow-2xl ${isLight ? 'bg-white border-zinc-200' : 'bg-zinc-900 border-zinc-800'}`}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-black flex items-center gap-2"><Sparkles className={`w-4 h-4 ${accent}`} /> KI-Nachfass</h3>
              <button type="button" onClick={() => setAiModal(null)} title="Schließen"
                className={`p-1.5 rounded-md cursor-pointer inline-flex items-center justify-center transition ${isLight ? 'hover:bg-zinc-100 text-zinc-500' : 'hover:bg-zinc-800 text-zinc-300'}`}>
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="mb-3">
              <div className={`text-[15px] font-bold ${isLight ? 'text-zinc-800' : 'text-zinc-100'}`}>{aiModal.kontakt.name}</div>
              <div className="text-[14px] opacity-60">{aiModal.kontakt.unternehmen || aiModal.kontakt.rolle || ''}</div>
            </div>
            {!aiDraft ? (
              <button onClick={generateDraft} disabled={aiLoading}
                className="w-full px-3 py-2 rounded-xl text-[15px] font-bold flex items-center justify-center gap-2 text-white bg-[var(--mission-accent,#10b981)] hover:opacity-90 disabled:opacity-50">
                {aiLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                {aiLoading ? 'Entwerfe…' : 'KI-Nachricht entwerfen'}
              </button>
            ) : (
              <div>
                <textarea value={aiDraft} readOnly rows={5} className={`w-full p-2.5 rounded-xl border text-[15px] font-sans resize-none ${isLight ? 'bg-zinc-50 border-zinc-200' : 'bg-zinc-950 border-zinc-700'}`} />
                <div className="flex gap-2 mt-2">
                  <button onClick={copyDraft}
                    className={`flex-1 px-3 py-2 rounded-xl text-[15px] font-bold inline-flex items-center justify-center gap-1.5 cursor-pointer ${isLight ? 'bg-zinc-100 hover:bg-zinc-200' : 'bg-zinc-800 hover:bg-zinc-700'}`}>
                    {copied ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Clipboard className="w-3.5 h-3.5" />}
                    {copied ? 'Kopiert!' : 'In Zwischenablage kopieren'}
                  </button>
                  <button onClick={() => setAiModal(null)}
                    className="px-3 py-2 rounded-xl text-[15px] font-bold text-white bg-[var(--mission-accent,#10b981)] hover:opacity-90 cursor-pointer">Fertig</button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Rollen-Liste Panel */}
      <RollenListePanel
        open={selectedRolle !== null}
        rollenLabel={selectedRolle?.label ?? ''}
        kontakte={selectedRolle?.kontakte ?? []}
        themeMode={themeMode}
        onClose={() => setSelectedRolle(null)}
        onOpenKontakt={(k) => {
          setSelectedRolle(null);
          onOpenKontakt?.(k);
        }}
        onOpenDesign={onOpenDesign}
        onStatusChange={(k, status) => {
          const updated = { ...k, status: status as KontaktRecord['status'] };
          // Elternstate live aktualisieren (Badge + Statistik)
          onKontaktUpdate?.(updated);
        }}
      />
    </div>
  );
}
