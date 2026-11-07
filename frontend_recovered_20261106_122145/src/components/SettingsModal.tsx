"use client";

import React, { useState, useEffect } from 'react';
import {
  X, Check, Paintbrush, Calendar, Eye, EyeOff, ExternalLink,
  RefreshCw, CheckCircle2, AlertCircle, Loader2, ChevronRight
} from 'lucide-react';
import { USER_COLOR_PALETTES } from '@/lib/colorTheme';
import { DesignEditorTab } from './DesignEditorTab';
import { pb } from '@/lib/pocketbase';

export type AccentColor = 'emerald' | 'blue' | 'purple' | 'amber' | 'rose' | 'teal';

export interface AccentColorConfig {
  id: AccentColor;
  name: string;
  hex: string;
}

export const ACCENT_COLORS: AccentColorConfig[] = [
  { id: 'emerald', name: 'Smaragd (Grün)', hex: '#10b981' },
  { id: 'blue', name: 'Saphir (Blau)', hex: '#3b82f6' },
  { id: 'purple', name: 'Violett (Purpur)', hex: '#8b5cf6' },
  { id: 'amber', name: 'Amber (Gold)', hex: '#f59e0b' },
  { id: 'rose', name: 'Rubin (Rosé)', hex: '#f43f5e' },
  { id: 'teal', name: 'Türkis (Teal)', hex: '#14b8a6' }
];

export interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  themeMode: 'light' | 'dark';
  onThemeChange: (mode: 'light' | 'dark') => void;
  activeView: 'pipeline' | 'tabelle';
  onViewChange: (view: 'pipeline' | 'tabelle') => void;
  accentColor?: AccentColor;
  onAccentColorChange?: (color: AccentColor) => void;
  primaryAccentHex?: string;
  onPrimaryAccentHexChange?: (hex: string) => void;
  secondaryAccentHex?: string;
  onSecondaryAccentHexChange?: (hex: string) => void;
  customLogoUrl?: string;
  onCustomLogoChange?: (url: string) => void;
  designEditorOpen?: boolean;
  onDesignEditorToggle?: (open: boolean) => void;
  /** If 'kalender', open the modal with the calendar tab pre-selected */
  initialTab?: 'design' | 'kalender';
  onSaveThemeSettings?: () => void;
}

// ─── LocalStorage key ─────────────────────────────────────────────────────────
const CAL_SETTINGS_KEY = 'archon_crm_calendar_settings_v1';

interface CalendarSettings {
  // Google
  googleCredentialsPath: string;
  googleCalendarId: string;
  googleTokenExists: boolean;

  // Outlook – Graph API
  outlookTenantId: string;
  outlookClientId: string;
  outlookClientSecret: string;
  outlookUserEmail: string;

  // Outlook – ICS Feed (alternative)
  outlookIcsUrl: string;

  // General
  lookAheadDays: string;
  lookBackDays: string;
  aggregatorUrl: string;
}

const DEFAULT_CAL: CalendarSettings = {
  googleCredentialsPath: '',
  googleCalendarId: 'primary',
  googleTokenExists: false,
  outlookTenantId: '',
  outlookClientId: '',
  outlookClientSecret: '',
  outlookUserEmail: '',
  outlookIcsUrl: '',
  lookAheadDays: '30',
  lookBackDays: '7',
  aggregatorUrl: 'http://localhost:8421',
};

// ─── Calendar Settings Tab ────────────────────────────────────────────────────

function CalendarSettingsTab({ isLight }: { isLight: boolean }) {
  const [settings, setSettings] = useState<CalendarSettings>(DEFAULT_CAL);
  const [showSecrets, setShowSecrets] = useState(false);
  const [saved, setSaved] = useState(false);
  const [pingStatus, setPingStatus] = useState<'idle' | 'checking' | 'ok' | 'error'>('idle');
  const [outlookMode, setOutlookMode] = useState<'graph' | 'ics'>('ics');

  // Load saved settings on mount
  useEffect(() => {
    try {
      const raw = localStorage.getItem(CAL_SETTINGS_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as Partial<CalendarSettings>;
        setSettings(prev => ({ ...prev, ...parsed }));
        if (parsed.outlookTenantId) setOutlookMode('graph');
        if (parsed.outlookIcsUrl && !parsed.outlookTenantId) setOutlookMode('ics');
      }
    } catch {}
  }, []);

  const update = (key: keyof CalendarSettings, value: string | boolean) => {
    setSettings(prev => ({ ...prev, [key]: value }));
  };

  const handleSave = () => {
    try {
      localStorage.setItem(CAL_SETTINGS_KEY, JSON.stringify(settings));
      // Write a .env snippet to the backend API so the Python aggregator can read it
      // (This is stored client-side only – the backend reads env vars separately)
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch {}
  };

  const handlePingAggregator = async () => {
    setPingStatus('checking');
    try {
      const url = (settings.aggregatorUrl || 'http://localhost:8421').replace(/\/$/, '') + '/events';
      const res = await fetch(url, { signal: AbortSignal.timeout(4000) });
      setPingStatus(res.ok ? 'ok' : 'error');
    } catch {
      setPingStatus('error');
    }
    setTimeout(() => setPingStatus('idle'), 4000);
  };

  const inputCls = `w-full p-2.5 rounded-xl border text-xs font-mono transition focus:outline-none focus:ring-2 focus:ring-emerald-500 ${
    isLight
      ? 'bg-slate-50 border-slate-300 text-slate-900 placeholder:text-slate-400'
      : 'bg-slate-950 border-slate-700 text-slate-100 placeholder:text-slate-500'
  }`;
  const labelCls = `block text-[11px] font-bold mb-1 ${isLight ? 'text-slate-600' : 'text-slate-400'}`;
  const sectionCls = `rounded-xl border p-4 space-y-3 ${
    isLight ? 'border-slate-200 bg-slate-50/50' : 'border-slate-800 bg-slate-900/50'
  }`;
  const sectionTitle = `text-xs font-bold flex items-center gap-2 ${isLight ? 'text-slate-700' : 'text-slate-300'}`;

  return (
    <div className="space-y-5">

      {/* ── Aggregator Connection ── */}
      <div className={sectionCls}>
        <p className={sectionTitle}>
          <span className="w-5 h-5 rounded bg-slate-200 dark:bg-slate-800 flex items-center justify-center text-[10px] font-black">🔗</span>
          Backend-Verbindung
        </p>

        <div>
          <label className={labelCls}>Aggregator URL</label>
          <div className="flex gap-2">
            <input
              type="text"
              value={settings.aggregatorUrl}
              onChange={e => update('aggregatorUrl', e.target.value)}
              placeholder="http://localhost:8421"
              className={inputCls}
            />
            <button
              type="button"
              onClick={handlePingAggregator}
              className={`shrink-0 px-3 py-2 rounded-xl border text-[11px] font-semibold flex items-center gap-1.5 transition cursor-pointer ${
                isLight ? 'bg-white border-slate-300 text-slate-700 hover:bg-slate-100' : 'bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700'
              }`}
              title="Verbindung testen"
            >
              {pingStatus === 'checking' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> :
               pingStatus === 'ok' ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" /> :
               pingStatus === 'error' ? <AlertCircle className="w-3.5 h-3.5 text-rose-500" /> :
               <RefreshCw className="w-3.5 h-3.5" />}
              Test
            </button>
          </div>
          {pingStatus === 'ok' && <p className="text-[11px] text-emerald-600 font-semibold mt-1">✓ Aggregator erreichbar</p>}
          {pingStatus === 'error' && (
            <p className="text-[11px] text-rose-500 font-semibold mt-1">
              ✗ Nicht erreichbar — starte: <code className="font-mono">python scripts/calendar_aggregator.py</code>
            </p>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>Vorausschau (Tage)</label>
            <input
              type="number"
              min="1" max="365"
              value={settings.lookAheadDays}
              onChange={e => update('lookAheadDays', e.target.value)}
              className={inputCls}
            />
          </div>
          <div>
            <label className={labelCls}>Vergangenheit (Tage)</label>
            <input
              type="number"
              min="0" max="365"
              value={settings.lookBackDays}
              onChange={e => update('lookBackDays', e.target.value)}
              className={inputCls}
            />
          </div>
        </div>

        {/* Aggregator start command */}
        <div className={`rounded-lg p-3 font-mono text-[11px] space-y-1 ${isLight ? 'bg-slate-100 text-slate-600' : 'bg-slate-950 text-slate-400'}`}>
          <p className="font-bold text-[10px] uppercase tracking-wider">Start-Befehl</p>
          <p className="select-all">python scripts/calendar_aggregator.py</p>
          <p className="opacity-60 text-[10px]">Installieren: pip install google-api-python-client google-auth-oauthlib msal icalendar requests</p>
        </div>
      </div>

      {/* ── Google Calendar ── */}
      <div className={sectionCls}>
        <p className={sectionTitle}>
          <span className="text-base">🔵</span>
          Google Kalender
        </p>

        <div>
          <label className={labelCls}>Credentials-Datei (Pfad auf dem Server)</label>
          <input
            type="text"
            value={settings.googleCredentialsPath}
            onChange={e => update('googleCredentialsPath', e.target.value)}
            placeholder="credentials.json"
            className={inputCls}
          />
          <p className={`text-[10px] mt-1 ${isLight ? 'text-slate-500' : 'text-slate-500'}`}>
            OAuth2 Desktop-App JSON — herunterladen unter{' '}
            <a
              href="https://console.cloud.google.com/apis/credentials"
              target="_blank"
              rel="noopener noreferrer"
              className="text-sky-500 hover:underline inline-flex items-center gap-0.5"
            >
              console.cloud.google.com <ExternalLink className="w-2.5 h-2.5" />
            </a>
          </p>
        </div>

        <div>
          <label className={labelCls}>Kalender-ID</label>
          <input
            type="text"
            value={settings.googleCalendarId}
            onChange={e => update('googleCalendarId', e.target.value)}
            placeholder="primary  oder  dein@gmail.com"
            className={inputCls}
          />
        </div>

        <div className={`flex items-center gap-2 text-[11px] p-2.5 rounded-lg ${
          isLight ? 'bg-sky-50 border border-sky-200 text-sky-700' : 'bg-sky-950/30 border border-sky-900 text-sky-400'
        }`}>
          <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
          <span>Beim ersten Start öffnet sich ein Browser-Fenster zur Google-Authorisierung. Das Token wird als <code className="font-mono">google_token.json</code> gespeichert.</span>
        </div>
      </div>

      {/* ── Kalender ICS-Feed ── */}
      <div className={sectionCls}>
        <div className="flex items-center justify-between">
          <p className={sectionTitle}>
            <span className="text-base">📅</span>
            ICS-Feed (Google, Outlook, iCloud, etc.)
          </p>
          {/* Mode toggle */}
          <div className={`flex items-center rounded-lg border overflow-hidden text-[11px] font-semibold ${
            isLight ? 'border-slate-300' : 'border-slate-700'
          }`}>
            <button
              type="button"
              onClick={() => setOutlookMode('ics')}
              className={`px-3 py-1.5 transition cursor-pointer ${
                outlookMode === 'ics'
                  ? 'bg-emerald-600 text-white'
                  : isLight ? 'bg-white text-slate-600 hover:bg-slate-50' : 'bg-slate-900 text-slate-400 hover:bg-slate-800'
              }`}
            >
              ICS-Feed URL
            </button>
            <button
              type="button"
              onClick={() => setOutlookMode('graph')}
              className={`px-3 py-1.5 transition cursor-pointer ${
                outlookMode === 'graph'
                  ? 'bg-emerald-600 text-white'
                  : isLight ? 'bg-white text-slate-600 hover:bg-slate-50' : 'bg-slate-900 text-slate-400 hover:bg-slate-800'
              }`}
            >
              Outlook Graph API
            </button>
          </div>
        </div>

        {outlookMode === 'ics' ? (
          <div>
            <label className={labelCls}>ICS / Webcal URL (Google, Outlook, etc.)</label>
            <input
              type="url"
              value={settings.outlookIcsUrl}
              onChange={e => update('outlookIcsUrl', e.target.value)}
              placeholder="https://calendar.google.com/.../basic.ics"
              className={inputCls}
            />
            <p className={`text-[10px] mt-1 ${isLight ? 'text-slate-500' : 'text-slate-500'}`}>
              Hier kannst du private oder öffentliche Kalender-Adressen (.ics) einfügen. Mehrere URLs können mit Komma (,) getrennt werden.
            </p>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>Tenant ID</label>
                <input
                  type="text"
                  value={settings.outlookTenantId}
                  onChange={e => update('outlookTenantId', e.target.value)}
                  placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                  className={inputCls}
                />
              </div>
              <div>
                <label className={labelCls}>Client ID (App-ID)</label>
                <input
                  type="text"
                  value={settings.outlookClientId}
                  onChange={e => update('outlookClientId', e.target.value)}
                  placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                  className={inputCls}
                />
              </div>
            </div>
            <div>
              <label className={labelCls}>Client Secret</label>
              <div className="relative">
                <input
                  type={showSecrets ? 'text' : 'password'}
                  value={settings.outlookClientSecret}
                  onChange={e => update('outlookClientSecret', e.target.value)}
                  placeholder="••••••••••••••••••••••••"
                  className={`${inputCls} pr-10`}
                />
                <button
                  type="button"
                  onClick={() => setShowSecrets(!showSecrets)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 transition cursor-pointer"
                >
                  {showSecrets ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>
            <div>
              <label className={labelCls}>Postfach E-Mail</label>
              <input
                type="email"
                value={settings.outlookUserEmail}
                onChange={e => update('outlookUserEmail', e.target.value)}
                placeholder="dein@unternehmen.de"
                className={inputCls}
              />
            </div>
            <div className={`flex items-start gap-2 text-[11px] p-2.5 rounded-lg ${
              isLight ? 'bg-amber-50 border border-amber-200 text-amber-700' : 'bg-amber-950/30 border border-amber-900 text-amber-400'
            }`}>
              <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              <span>
                Azure AD App braucht die Berechtigung <code className="font-mono">Calendars.Read</code> (Application-Permission, nicht Delegated). Registrierung unter{' '}
                <a href="https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps" target="_blank" rel="noopener noreferrer" className="underline inline-flex items-center gap-0.5">
                  portal.azure.com <ExternalLink className="w-2.5 h-2.5" />
                </a>
              </span>
            </div>
          </>
        )}
      </div>

      {/* ── Env-Datei Vorschau ── */}
      <div className={`rounded-xl border p-4 space-y-2 ${isLight ? 'border-slate-200' : 'border-slate-800'}`}>
        <p className={`text-[11px] font-bold uppercase tracking-wider ${isLight ? 'text-slate-500' : 'text-slate-500'}`}>
          .env-Vorschau (in scripts/.env eintragen)
        </p>
        <pre className={`text-[10px] font-mono leading-relaxed select-all rounded-lg p-3 overflow-x-auto ${
          isLight ? 'bg-slate-100 text-slate-700' : 'bg-slate-950 text-slate-400'
        }`}>
{`GOOGLE_CREDENTIALS_FILE=${settings.googleCredentialsPath || 'credentials.json'}
GOOGLE_CALENDAR_ID=${settings.googleCalendarId || 'primary'}

${outlookMode === 'ics'
  ? `OUTLOOK_ICS_URL=${settings.outlookIcsUrl || ''}`
  : `OUTLOOK_TENANT_ID=${settings.outlookTenantId || ''}
OUTLOOK_CLIENT_ID=${settings.outlookClientId || ''}
OUTLOOK_CLIENT_SECRET=${settings.outlookClientSecret ? '***' : ''}
OUTLOOK_USER_EMAIL=${settings.outlookUserEmail || ''}`
}

LOOK_AHEAD_DAYS=${settings.lookAheadDays || '30'}
LOOK_BACK_DAYS=${settings.lookBackDays || '7'}`}
        </pre>
      </div>

      {/* Save */}
      <div className="flex items-center justify-between pt-1">
        {saved && (
          <span className="flex items-center gap-1.5 text-emerald-600 text-xs font-semibold animate-in fade-in duration-150">
            <CheckCircle2 className="w-4 h-4" />
            Einstellungen gespeichert
          </span>
        )}
        <div className="ml-auto flex gap-2">
          <button
            type="button"
            onClick={handleSave}
            className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-xs transition shadow-sm cursor-pointer"
          >
            Speichern
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Trash Bin Tab ────────────────────────────────────────────────────────────

function TrashBinTab({ isLight, onRestore }: { isLight: boolean; onRestore?: () => void }) {
  const [deletedContacts, setDeletedContacts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);

  const fetchDeleted = async () => {
    try {
      setLoading(true);
      const all = await pb.collection('Kontakte').getFullList({
        sort: '-updated',
      });
      const trashed = all.filter((k: any) => Boolean(k.deleted_at));
      setDeletedContacts(trashed);
    } catch (e) {
      console.warn("Fehler beim Laden des Papierkorbs:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDeleted();
  }, []);

  const handleRestore = async (id: string) => {
    try {
      setActionInProgress(id);
      await pb.collection('Kontakte').update(id, { deleted_at: null });
      setDeletedContacts(prev => prev.filter(k => k.id !== id));
      onRestore?.();
    } catch (err) {
      alert("Fehler beim Wiederherstellen.");
    } finally {
      setActionInProgress(null);
    }
  };

  const handlePermanentDelete = async (id: string, name: string) => {
    if (!confirm(`Kontakt "${name}" wirklich endgültig löschen? Diese Aktion kann nicht rückgängig gemacht werden.`)) {
      return;
    }
    try {
      setActionInProgress(id);
      await pb.collection('Kontakte').delete(id);
      setDeletedContacts(prev => prev.filter(k => k.id !== id));
    } catch (err) {
      alert("Fehler beim endgültigen Löschen.");
    } finally {
      setActionInProgress(null);
    }
  };

  const handleEmptyTrash = async () => {
    if (deletedContacts.length === 0) return;
    if (!confirm(`Möchtest du wirklich alle ${deletedContacts.length} Kontakte im Papierkorb endgültig löschen?`)) {
      return;
    }
    try {
      setLoading(true);
      for (const k of deletedContacts) {
        await pb.collection('Kontakte').delete(k.id);
      }
      setDeletedContacts([]);
    } catch (err) {
      alert("Fehler beim Leeren des Papierkorbs.");
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-12 gap-2 text-slate-500">
        <Loader2 className="w-6 h-6 animate-spin text-emerald-500" />
        <span className="text-xs">Papierkorb wird geladen...</span>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className={`text-xs font-bold ${isLight ? 'text-slate-800' : 'text-slate-200'}`}>
            Papierkorb ({deletedContacts.length})
          </h3>
          <p className="text-[11px] text-slate-500">
            Gelöschte Kontakte können hier wiederhergestellt oder endgültig entfernt werden.
          </p>
        </div>
        {deletedContacts.length > 0 && (
          <button
            type="button"
            onClick={handleEmptyTrash}
            className="px-3 py-1.5 rounded-lg text-xs font-bold bg-rose-600/10 hover:bg-rose-600/20 text-rose-600 border border-rose-600/30 transition cursor-pointer"
          >
            Papierkorb leeren
          </button>
        )}
      </div>

      {deletedContacts.length === 0 ? (
        <div className={`p-8 border border-dashed rounded-xl text-center space-y-2 ${
          isLight ? 'border-slate-300 bg-slate-50/50 text-slate-500' : 'border-slate-800 bg-slate-900/30 text-slate-500'
        }`}>
          <p className="text-sm font-semibold">Der Papierkorb ist leer</p>
          <p className="text-xs text-slate-400">Gelöschte Kontakte landen zunächst hier als Soft-Delete.</p>
        </div>
      ) : (
        <div className="space-y-2 max-h-[50vh] overflow-y-auto pr-1">
          {deletedContacts.map(k => {
            const delDate = k.deleted_at ? new Date(k.deleted_at).toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : 'Unbekannt';
            const isActing = actionInProgress === k.id;

            return (
              <div
                key={k.id}
                className={`p-3 rounded-xl border flex items-center justify-between gap-3 transition ${
                  isLight ? 'border-slate-200 bg-white hover:border-slate-300' : 'border-slate-800 bg-slate-900/60 hover:border-slate-700'
                }`}
              >
                <div className="min-w-0 flex-1">
                  <p className={`text-xs font-bold truncate ${isLight ? 'text-slate-800' : 'text-slate-100'}`}>
                    {k.name || 'Ohne Namen'}
                  </p>
                  <p className="text-[11px] text-slate-500 truncate">
                    {k.unternehmen || k.rolle || 'Keine Positionsangabe'}
                  </p>
                  <span className="text-[10px] text-slate-400 font-mono">
                    Gelöscht am: {delDate}
                  </span>
                </div>

                <div className="flex items-center gap-1.5 shrink-0">
                  <button
                    type="button"
                    disabled={isActing}
                    onClick={() => handleRestore(k.id)}
                    className="px-2.5 py-1.5 rounded-lg text-xs font-bold bg-emerald-600/10 hover:bg-emerald-600/20 text-emerald-600 border border-emerald-600/30 transition cursor-pointer disabled:opacity-50"
                  >
                    Wiederherstellen
                  </button>
                  <button
                    type="button"
                    disabled={isActing}
                    onClick={() => handlePermanentDelete(k.id, k.name)}
                    className="px-2.5 py-1.5 rounded-lg text-xs font-bold bg-rose-600/10 hover:bg-rose-600/20 text-rose-600 border border-rose-600/30 transition cursor-pointer disabled:opacity-50"
                  >
                    Endgültig löschen
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── Main SettingsModal ────────────────────────────────────────────────────────

export function SettingsModal({
  isOpen,
  onClose,
  themeMode,
  onThemeChange,
  activeView,
  onViewChange,
  accentColor = 'emerald',
  onAccentColorChange,
  primaryAccentHex = '#10b981',
  onPrimaryAccentHexChange,
  secondaryAccentHex = '#ecfdf5',
  onSecondaryAccentHexChange,
  customLogoUrl = '',
  onCustomLogoChange,
  designEditorOpen = false,
  onDesignEditorToggle,
  initialTab = 'design',
  onSaveThemeSettings,
  onContactRestored,
}: SettingsModalProps & { onContactRestored?: () => void }) {
  const [activeTab, setActiveTab] = useState<'design' | 'kalender' | 'papierkorb'>(initialTab);
  const [savedNotice, setSavedNotice] = useState(false);

  // Sync tab if parent changes initialTab after open (e.g. deep-link from calendar button)
  useEffect(() => {
    if (isOpen) setActiveTab(initialTab);
  }, [isOpen, initialTab]);

  if (!isOpen) return null;

  const isLight = themeMode === 'light';

  const handleSave = () => {
    onSaveThemeSettings?.();
    setSavedNotice(true);
    setTimeout(() => {
      setSavedNotice(false);
      onClose();
    }, 800);
  };

  const tabCls = (tab: 'design' | 'kalender' | 'papierkorb') =>
    `flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition cursor-pointer whitespace-nowrap ${
      activeTab === tab
        ? 'border-emerald-500 text-emerald-600'
        : isLight
        ? 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'
        : 'border-transparent text-slate-500 hover:text-slate-300 hover:border-slate-600'
    }`;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/70 backdrop-blur-md flex items-center justify-center p-4">
      <div className={`w-full max-w-xl rounded-2xl border shadow-2xl flex flex-col max-h-[90vh] animate-in zoom-in-95 duration-150 ${
        isLight ? 'bg-white border-slate-200 text-slate-900' : 'bg-slate-900 border-slate-800 text-slate-100'
      }`}>

        {/* Header */}
        <div className={`flex items-center justify-between px-5 pt-5 pb-0 shrink-0`}>
          <div className="flex items-center gap-2">
            <Paintbrush className="w-5 h-5 text-accent-main" />
            <h2 className="text-sm font-bold tracking-tight">Einstellungen</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-800 text-slate-400 transition cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Tab bar */}
        <div className={`flex border-b px-2 shrink-0 ${isLight ? 'border-slate-200' : 'border-slate-800'}`}>
          <button type="button" onClick={() => setActiveTab('design')} className={tabCls('design')}>
            <Paintbrush className="w-3.5 h-3.5" />
            Design & Farben
          </button>
          <button type="button" onClick={() => setActiveTab('kalender')} className={tabCls('kalender')}>
            <Calendar className="w-3.5 h-3.5" />
            Kalender-APIs
          </button>
          <button type="button" onClick={() => setActiveTab('papierkorb')} className={tabCls('papierkorb')}>
            <span className="text-xs">🗑️</span>
            Papierkorb
          </button>
        </div>

        {/* Saved notice */}
        {savedNotice && (
          <div className="mx-5 mt-3 p-3 rounded-lg bg-accent-light border border-accent-light text-accent-main text-xs flex items-center gap-2 font-semibold shrink-0">
            <Check className="w-4 h-4" />
            <span>Einstellungen erfolgreich gespeichert.</span>
          </div>
        )}

        {/* Tab content — scrollable */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {activeTab === 'design' ? (
            <DesignEditorTab
              isLight={isLight}
              primaryAccentHex={primaryAccentHex}
              secondaryAccentHex={secondaryAccentHex}
              onPrimaryAccentHexChange={onPrimaryAccentHexChange}
              onSecondaryAccentHexChange={onSecondaryAccentHexChange}
              accentColor={accentColor}
              onAccentColorChange={onAccentColorChange}
              themeMode={themeMode}
              onThemeChange={onThemeChange}
              customLogoUrl={customLogoUrl}
              onCustomLogoChange={onCustomLogoChange}
            />
          ) : activeTab === 'kalender' ? (
            <CalendarSettingsTab isLight={isLight} />
          ) : (
            <TrashBinTab isLight={isLight} onRestore={onContactRestored} />
          )}
        </div>

        {/* Footer — only for Design tab (Calendar & Trash tab have their own actions) */}
        {activeTab === 'design' && (
          <div className={`px-5 pb-5 pt-3 border-t flex justify-end gap-2 shrink-0 ${isLight ? 'border-slate-200' : 'border-slate-800'}`}>
            <button
              type="button"
              onClick={onClose}
              className={`px-4 py-2 rounded-lg font-semibold text-xs transition cursor-pointer ${
                isLight ? 'bg-slate-200 text-slate-800 hover:bg-slate-300' : 'bg-slate-800 text-slate-200 hover:bg-slate-700'
              }`}
            >
              Schließen
            </button>
            <button
              type="button"
              onClick={handleSave}
              className="px-4 py-2 rounded-lg bg-accent-main text-white font-bold text-xs transition shadow-md cursor-pointer hover:opacity-90"
            >
              Übernehmen
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
