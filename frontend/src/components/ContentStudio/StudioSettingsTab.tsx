"use client";

import React, { useState, useEffect } from 'react';
import {
  pbMedia,
  POCKETBASE_MEDIA_URL,
  StudioSettingsRecord
} from '@/lib/pocketbase';
import {
  Activity,
  Download,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  HardDrive,
  Paintbrush,
  Palette,
  RotateCcw,
  Sun,
  Moon,
  Sliders,
  Sparkles,
  ChevronDown
} from 'lucide-react';
import { USER_COLOR_PALETTES, ColorPaletteGroup } from '@/lib/colorTheme';

interface StudioSettingsTabProps {
  themeMode?: 'light' | 'dark';
}

const STUDIO_CSS_VARS = [
  { key: '--studio-bg', label: 'Studio Hintergrund', defaultDark: '#0b0f19', defaultLight: '#f8fafc' },
  { key: '--studio-card-bg', label: 'Karten / Kachel Hintergrund', defaultDark: '#111827', defaultLight: '#ffffff' },
  { key: '--studio-card-border', label: 'Karten Rahmen', defaultDark: '#1f2937', defaultLight: '#e2e8f0' },
  { key: '--studio-input-bg', label: 'Input & Dropdown Hintergrund', defaultDark: '#0f172a', defaultLight: '#ffffff' },
  { key: '--studio-input-text', label: 'Input & Dropdown Schriftfarbe', defaultDark: '#f8fafc', defaultLight: '#0f172a' },
  { key: '--studio-input-border', label: 'Input & Dropdown Rahmen', defaultDark: '#334155', defaultLight: '#cbd5e1' },
  { key: '--studio-accent', label: 'Studio Akzentfarbe (Buttons / Regler)', defaultDark: '#ef4444', defaultLight: '#dc2626' },
  { key: '--studio-accent-hover', label: 'Akzentfarbe Hover', defaultDark: '#dc2626', defaultLight: '#b91c1c' },
  { key: '--studio-text', label: 'Haupttext Farbe', defaultDark: '#f8fafc', defaultLight: '#0f172a' },
  { key: '--studio-text-muted', label: 'Dezenter Text / Labels', defaultDark: '#94a3b8', defaultLight: '#64748b' },
  { key: '--studio-tab-active-bg', label: 'Aktiver Reiter Hintergrund', defaultDark: 'rgba(239, 68, 68, 0.12)', defaultLight: '#fef2f2' },
  { key: '--studio-tab-active-text', label: 'Aktiver Reiter Text', defaultDark: '#f87171', defaultLight: '#dc2626' },
  { key: '--studio-tab-active-border', label: 'Aktiver Reiter Rahmen', defaultDark: '#ef4444', defaultLight: '#dc2626' },
];

const STUDIO_THEME_PRESETS = [
  {
    id: 'slate_rubin',
    name: 'Schiefer & Rubinrot (Standard)',
    icon: '🔴',
    theme: 'dark' as const,
    vars: {
      '--studio-bg': '#0b0f19',
      '--studio-card-bg': '#111827',
      '--studio-card-border': '#1f2937',
      '--studio-input-bg': '#0f172a',
      '--studio-input-text': '#f8fafc',
      '--studio-input-border': '#334155',
      '--studio-accent': '#ef4444',
      '--studio-accent-hover': '#dc2626',
      '--studio-text': '#f8fafc',
      '--studio-text-muted': '#94a3b8',
      '--studio-tab-active-bg': 'rgba(239, 68, 68, 0.12)',
      '--studio-tab-active-text': '#f87171',
      '--studio-tab-active-border': '#ef4444'
    }
  },
  {
    id: 'dark_gold',
    name: 'Dunkel & Bernstein/Gold',
    icon: '👑',
    theme: 'dark' as const,
    vars: {
      '--studio-bg': '#0b0f19',
      '--studio-card-bg': '#14213d',
      '--studio-card-border': '#1f2937',
      '--studio-input-bg': '#000000',
      '--studio-input-text': '#ffffff',
      '--studio-input-border': '#fca311',
      '--studio-accent': '#fca311',
      '--studio-accent-hover': '#e5980b',
      '--studio-text': '#ffffff',
      '--studio-text-muted': '#e5e5e5',
      '--studio-tab-active-bg': 'rgba(252, 163, 17, 0.15)',
      '--studio-tab-active-text': '#fca311',
      '--studio-tab-active-border': '#fca311'
    }
  },
  {
    id: 'emerald_forest',
    name: 'Smaragd & Waldgrün',
    icon: '🌿',
    theme: 'dark' as const,
    vars: {
      '--studio-bg': '#081c15',
      '--studio-card-bg': '#1b4332',
      '--studio-card-border': '#2d6a4f',
      '--studio-input-bg': '#081c15',
      '--studio-input-text': '#d8f3dc',
      '--studio-input-border': '#40916c',
      '--studio-accent': '#52b788',
      '--studio-accent-hover': '#40916c',
      '--studio-text': '#d8f3dc',
      '--studio-text-muted': '#95d5b2',
      '--studio-tab-active-bg': 'rgba(82, 183, 136, 0.15)',
      '--studio-tab-active-text': '#52b788',
      '--studio-tab-active-border': '#52b788'
    }
  },
  {
    id: 'light_clean',
    name: 'Helles Minimal-Design (Hell)',
    icon: '☀️',
    theme: 'light' as const,
    vars: {
      '--studio-bg': '#f8fafc',
      '--studio-card-bg': '#ffffff',
      '--studio-card-border': '#e2e8f0',
      '--studio-input-bg': '#ffffff',
      '--studio-input-text': '#0f172a',
      '--studio-input-border': '#cbd5e1',
      '--studio-accent': '#dc2626',
      '--studio-accent-hover': '#b91c1c',
      '--studio-text': '#0f172a',
      '--studio-text-muted': '#64748b',
      '--studio-tab-active-bg': '#fef2f2',
      '--studio-tab-active-text': '#dc2626',
      '--studio-tab-active-border': '#dc2626'
    }
  }
];

export function StudioSettingsTab({ themeMode = 'dark' }: StudioSettingsTabProps) {
  const isLight = themeMode === 'light';

  // DB Health state
  const [pbStatus, setPbStatus] = useState<'testing' | 'connected' | 'error'>('testing');
  const [stats, setStats] = useState({
    batchCount: 0,
    itemCount: 0,
    linkedinCount: 0
  });

  // Theme Variables state
  const [cssVariables, setCssVariables] = useState<Record<string, string>>({});
  const [pickerTarget, setPickerTarget] = useState<string | null>(null);
  const [toast, setToast] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  const showToast = (text: string, type: 'success' | 'error' = 'success') => {
    setToast({ text, type });
    setTimeout(() => setToast(null), 3500);
  };

  // Load current computed CSS variables on mount
  useEffect(() => {
    const rootStyles = getComputedStyle(document.documentElement);
    const vars: Record<string, string> = {};
    STUDIO_CSS_VARS.forEach((item) => {
      const live = rootStyles.getPropertyValue(item.key).trim();
      const local = typeof window !== 'undefined' ? localStorage.getItem(`archon_theme_var_${item.key}`) : null;
      vars[item.key] = local || live || (isLight ? item.defaultLight : item.defaultDark);
    });
    setCssVariables(vars);
  }, [themeMode, isLight]);

  const handleVarChange = (key: string, value: string) => {
    document.documentElement.style.setProperty(key, value);
    setCssVariables((prev) => ({ ...prev, [key]: value }));
    try {
      localStorage.setItem(`archon_theme_var_${key}`, value);
    } catch (e) {}
  };

  const handleApplyPreset = (preset: typeof STUDIO_THEME_PRESETS[0]) => {
    Object.entries(preset.vars).forEach(([key, val]) => {
      document.documentElement.style.setProperty(key, val);
      try {
        localStorage.setItem(`archon_theme_var_${key}`, val);
      } catch (e) {}
    });
    setCssVariables((prev) => ({ ...prev, ...preset.vars }));
    showToast(`Preset "${preset.name}" angewendet.`);
  };

  const handleResetToDefaults = () => {
    STUDIO_CSS_VARS.forEach((item) => {
      const def = isLight ? item.defaultLight : item.defaultDark;
      document.documentElement.style.setProperty(item.key, def);
      try {
        localStorage.removeItem(`archon_theme_var_${item.key}`);
      } catch (e) {}
    });
    const resetVars: Record<string, string> = {};
    STUDIO_CSS_VARS.forEach((item) => {
      resetVars[item.key] = isLight ? item.defaultLight : item.defaultDark;
    });
    setCssVariables(resetVars);
    showToast('Studio-Farben auf Standard zurückgesetzt.');
  };

  const checkHealth = async () => {
    setPbStatus('testing');
    try {
      const health = await pbMedia.health.check();
      if (health.code === 200) {
        setPbStatus('connected');
        const [batches, items, linkedin] = await Promise.all([
          pbMedia.collection('video_batches').getList(1, 1),
          pbMedia.collection('media_items').getList(1, 1),
          pbMedia.collection('linkedin_content').getList(1, 1)
        ]);
        setStats({
          batchCount: batches.totalItems,
          itemCount: items.totalItems,
          linkedinCount: linkedin.totalItems
        });
      } else {
        setPbStatus('error');
      }
    } catch (e) {
      setPbStatus('error');
    }
  };

  useEffect(() => {
    checkHealth();
  }, []);

  const handleExportConfig = async () => {
    try {
      const settings = await pbMedia.collection('studio_settings').getFullList<StudioSettingsRecord>();
      const blob = new Blob([JSON.stringify({ settings, cssVariables }, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `archon-content-studio-config-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      showToast('Konfiguration erfolgreich exportiert.');
    } catch (err: any) {
      showToast(`Export fehlgeschlagen: ${err.message}`, 'error');
    }
  };

  return (
    <div className="space-y-5 max-w-5xl">
      {/* Toast */}
      {toast && (
        <div
          className={`fixed bottom-6 right-6 z-50 px-4 py-2.5 rounded-lg shadow-xl border flex items-center gap-2.5 text-xs font-semibold ${
            toast.type === 'error'
              ? 'bg-rose-950/95 text-rose-200 border-rose-800'
              : 'bg-slate-900 text-slate-100 border-slate-700'
          }`}
        >
          {toast.type === 'error' ? (
            <AlertCircle className="w-4 h-4 text-red-400" />
          ) : (
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          )}
          <span>{toast.text}</span>
        </div>
      )}

      {/* SECTION 1: STUDIO DESIGN & COLOR CUSTOMIZER */}
      <div
        className={`p-4 rounded-xl border space-y-4 ${
          isLight ? 'bg-white border-slate-200 shadow-xs' : 'bg-slate-900 border-slate-800 shadow-md'
        }`}
      >
        <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-slate-800">
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider font-mono text-[var(--studio-accent,#ef4444)] flex items-center gap-2">
              <Paintbrush className="w-4 h-4" />
              Content Studio Design & Farben
            </h3>
            <p className="text-[11px] text-[var(--studio-text-muted,#94a3b8)] mt-0.5">
              Passe Hintergründe, Dropdown-Farben, Schriftkontraste und Akzente in Echtzeit an.
            </p>
          </div>

          <button
            onClick={handleResetToDefaults}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition cursor-pointer"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span>Standard wiederherstellen</span>
          </button>
        </div>

        {/* Schnell-Presets */}
        <div>
          <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-slate-400 block mb-2">
            Schnell-Vorlagen
          </span>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {STUDIO_THEME_PRESETS.map((p) => (
              <button
                key={p.id}
                onClick={() => handleApplyPreset(p)}
                className={`p-2.5 rounded-lg border text-left transition cursor-pointer flex flex-col justify-between gap-1.5 ${
                  isLight
                    ? 'bg-slate-50 hover:bg-slate-100 border-slate-200'
                    : 'bg-slate-950/60 hover:bg-slate-950 border-slate-800'
                }`}
              >
                <div className="flex items-center gap-1.5">
                  <span className="text-sm">{p.icon}</span>
                  <span className="text-xs font-bold text-slate-200 line-clamp-1">{p.name}</span>
                </div>
                <div className="flex items-center gap-1 mt-1">
                  <span className="w-3 h-3 rounded-full border border-white/20" style={{ backgroundColor: p.vars['--studio-bg'] }} />
                  <span className="w-3 h-3 rounded-full border border-white/20" style={{ backgroundColor: p.vars['--studio-card-bg'] }} />
                  <span className="w-3 h-3 rounded-full border border-white/20" style={{ backgroundColor: p.vars['--studio-input-bg'] }} />
                  <span className="w-3 h-3 rounded-full border border-white/20" style={{ backgroundColor: p.vars['--studio-accent'] }} />
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Live Preview Box & Variables Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 pt-2">
          {/* Left: Color Inputs List (7 Cols) */}
          <div className="lg:col-span-7 space-y-2.5">
            <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-slate-400 block">
              Einzelfarben & Kontraste
            </span>

            <div className="space-y-2 max-h-[460px] overflow-y-auto pr-1">
              {STUDIO_CSS_VARS.map((item) => {
                const currentVal = cssVariables[item.key] || (isLight ? item.defaultLight : item.defaultDark);
                const isPickerOpen = pickerTarget === item.key;

                return (
                  <div
                    key={item.key}
                    className={`p-2.5 rounded-lg border flex flex-col gap-1.5 transition ${
                      isLight ? 'bg-slate-50 border-slate-200' : 'bg-slate-950/60 border-slate-800'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <span className="text-xs font-semibold text-slate-200 block truncate">{item.label}</span>
                        <span className="text-[10px] font-mono text-slate-500 block truncate">{item.key}</span>
                      </div>

                      <div className="flex items-center gap-2 shrink-0">
                        {/* Native Color Picker Box */}
                        <div className="relative flex items-center">
                          <input
                            type="color"
                            value={currentVal.startsWith('#') ? currentVal : '#ef4444'}
                            onChange={(e) => handleVarChange(item.key, e.target.value)}
                            className="w-7 h-7 rounded border border-slate-700 cursor-pointer p-0 bg-transparent"
                            title="Farbe wählen"
                          />
                        </div>

                        {/* Hex Input */}
                        <input
                          type="text"
                          value={currentVal}
                          onChange={(e) => handleVarChange(item.key, e.target.value)}
                          className="w-24 px-2 py-1 rounded bg-slate-900 border border-slate-700 text-slate-200 font-mono text-[11px] focus:outline-hidden"
                        />

                        {/* Palette Swatch Trigger */}
                        <button
                          onClick={() => setPickerTarget(isPickerOpen ? null : item.key)}
                          className={`p-1.5 rounded border text-xs transition cursor-pointer ${
                            isPickerOpen
                              ? 'bg-red-500/20 border-red-500 text-red-400'
                              : 'bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700'
                          }`}
                          title="Farbpaletten"
                        >
                          <Palette className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>

                    {/* Expandable Palette Swatches */}
                    {isPickerOpen && (
                      <div className="mt-2 pt-2 border-t border-slate-800 space-y-2">
                        {USER_COLOR_PALETTES.map((group) => (
                          <div key={group.id} className="space-y-1">
                            <span className="text-[10px] font-mono text-slate-400 flex items-center gap-1">
                              <span>{group.icon}</span> {group.name}
                            </span>
                            <div className="flex flex-wrap gap-1">
                              {group.colors.map((c) => (
                                <button
                                  key={c.hex}
                                  onClick={() => {
                                    handleVarChange(item.key, c.hex);
                                    setPickerTarget(null);
                                  }}
                                  className="w-5 h-5 rounded border border-white/20 hover:scale-110 transition cursor-pointer shadow-xs"
                                  style={{ backgroundColor: c.hex }}
                                  title={c.hex}
                                />
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Right: Live Interactive Component Preview (5 Cols) */}
          <div className="lg:col-span-5 space-y-2.5">
            <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-slate-400 block">
              Live Vorschau (Sofort sichtbar)
            </span>

            {/* Studio Styled Simulated Container */}
            <div
              className="p-4 rounded-xl border space-y-3 transition-colors shadow-lg"
              style={{
                backgroundColor: 'var(--studio-bg, #0b0f19)',
                borderColor: 'var(--studio-card-border, #1f2937)',
                color: 'var(--studio-text, #f8fafc)'
              }}
            >
              {/* Fake Tab Bar */}
              <div className="flex items-center gap-1 pb-2 border-b" style={{ borderColor: 'var(--studio-card-border, #1f2937)' }}>
                <span
                  className="px-2.5 py-1 rounded text-[11px] font-bold border-b-2"
                  style={{
                    backgroundColor: 'var(--studio-tab-active-bg, rgba(239,68,68,0.12))',
                    color: 'var(--studio-tab-active-text, #f87171)',
                    borderColor: 'var(--studio-tab-active-border, #ef4444)'
                  }}
                >
                  Aktiver Tab
                </span>
                <span className="px-2.5 py-1 text-[11px]" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
                  Inaktiver Tab
                </span>
              </div>

              {/* Fake Card */}
              <div
                className="p-3 rounded-lg border space-y-2.5"
                style={{
                  backgroundColor: 'var(--studio-card-bg, #111827)',
                  borderColor: 'var(--studio-card-border, #1f2937)'
                }}
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold" style={{ color: 'var(--studio-text, #f8fafc)' }}>
                    Karten-Titel
                  </span>
                  <span className="text-[10px]" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
                    Unterzeile
                  </span>
                </div>

                {/* Simulated Dropdown & Input */}
                <div className="space-y-1.5">
                  <label className="text-[11px] font-semibold block" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
                    Dropdown Auswahl (z.B. Format / Länge)
                  </label>
                  <select
                    className="w-full px-2.5 py-1.5 rounded-lg border text-xs font-medium focus:outline-hidden"
                    style={{
                      backgroundColor: 'var(--studio-input-bg, #0f172a)',
                      color: 'var(--studio-input-text, #f8fafc)',
                      borderColor: 'var(--studio-input-border, #334155)'
                    }}
                  >
                    <option>Shorts 9:16 (180 Sek. / 3 Min.)</option>
                    <option>YouTube 16:9 (600 Sek. / 10 Min.)</option>
                  </select>
                </div>

                <div className="space-y-1.5">
                  <label className="text-[11px] font-semibold block" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
                    Texteingabe
                  </label>
                  <input
                    type="text"
                    defaultValue="Beispiel Hook oder Titel..."
                    className="w-full px-2.5 py-1.5 rounded-lg border text-xs focus:outline-hidden"
                    style={{
                      backgroundColor: 'var(--studio-input-bg, #0f172a)',
                      color: 'var(--studio-input-text, #f8fafc)',
                      borderColor: 'var(--studio-input-border, #334155)'
                    }}
                  />
                </div>

                {/* Simulated Button & Slider */}
                <div className="space-y-2 pt-1">
                  <div className="flex items-center justify-between text-xs">
                    <span style={{ color: 'var(--studio-text, #f8fafc)' }}>Zielzeit-Regler</span>
                    <span className="font-bold font-mono" style={{ color: 'var(--studio-accent, #ef4444)' }}>
                      180s
                    </span>
                  </div>
                  <input
                    type="range"
                    min="60"
                    max="300"
                    defaultValue="180"
                    className="w-full cursor-pointer"
                    style={{ accentColor: 'var(--studio-accent, #ef4444)' }}
                  />
                </div>

                <button
                  className="w-full py-1.5 rounded-lg text-white text-xs font-bold shadow-xs transition"
                  style={{
                    backgroundColor: 'var(--studio-accent, #ef4444)'
                  }}
                >
                  Aktions-Button (Render / Speichern)
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* SECTION 2: POCKETBASE DIAGNOSE & BACKUP */}
      <div
        className={`p-4 rounded-xl border space-y-3 ${
          isLight ? 'bg-white border-slate-200' : 'bg-slate-900 border-slate-800'
        }`}
      >
        <div className="flex items-center justify-between">
          <span className="text-xs font-bold uppercase tracking-wider font-mono text-[var(--studio-accent,#ef4444)] flex items-center gap-1.5">
            <Activity className="w-3.5 h-3.5" />
            Media-PocketBase (Port 8092)
          </span>
          <span className="text-xs font-bold font-mono">
            {pbStatus === 'connected' && (
              <span className="text-emerald-400 flex items-center gap-1">
                <CheckCircle2 className="w-3.5 h-3.5" /> Verbunden
              </span>
            )}
            {pbStatus === 'error' && (
              <span className="text-red-400 flex items-center gap-1">
                <AlertCircle className="w-3.5 h-3.5" /> Offline
              </span>
            )}
            {pbStatus === 'testing' && <span className="text-amber-400 animate-pulse">Prüfe...</span>}
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-1">
          <div
            className="p-3 rounded-lg border"
            style={{
              backgroundColor: 'var(--studio-input-bg, #0f172a)',
              borderColor: 'var(--studio-card-border, #1f2937)'
            }}
          >
            <span className="text-[10px] font-mono text-slate-400 block uppercase">Video-Stapel</span>
            <span className="text-lg font-bold font-mono text-slate-100 mt-0.5 block">{stats.batchCount}</span>
            <span className="text-[10px] text-slate-500">in 'video_batches'</span>
          </div>

          <div
            className="p-3 rounded-lg border"
            style={{
              backgroundColor: 'var(--studio-input-bg, #0f172a)',
              borderColor: 'var(--studio-card-border, #1f2937)'
            }}
          >
            <span className="text-[10px] font-mono text-slate-400 block uppercase">Medien-Dateien</span>
            <span className="text-lg font-bold font-mono text-slate-100 mt-0.5 block">{stats.itemCount}</span>
            <span className="text-[10px] text-slate-500">in 'media_items'</span>
          </div>

          <div
            className="p-3 rounded-lg border"
            style={{
              backgroundColor: 'var(--studio-input-bg, #0f172a)',
              borderColor: 'var(--studio-card-border, #1f2937)'
            }}
          >
            <span className="text-[10px] font-mono text-slate-400 block uppercase">LinkedIn Inhalte</span>
            <span className="text-lg font-bold font-mono text-slate-100 mt-0.5 block">{stats.linkedinCount}</span>
            <span className="text-[10px] text-slate-500">in 'linkedin_content'</span>
          </div>
        </div>

        <div className="pt-2 border-t border-slate-800 flex flex-wrap items-center justify-between gap-2 text-xs">
          <span className="text-slate-400 font-mono text-[11px]">
            Host: <span className="text-slate-200">{POCKETBASE_MEDIA_URL}</span>
          </span>
          <div className="flex items-center gap-3">
            <button
              onClick={handleExportConfig}
              className="text-slate-300 hover:text-slate-100 text-[11px] font-semibold flex items-center gap-1 cursor-pointer"
            >
              <Download className="w-3 h-3" /> Konfiguration als JSON
            </button>
            <a
              href="http://localhost:8092/_/"
              target="_blank"
              rel="noopener noreferrer"
              className="text-red-400 hover:text-red-300 font-semibold text-[11px]"
            >
              PocketBase Admin ↗
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
