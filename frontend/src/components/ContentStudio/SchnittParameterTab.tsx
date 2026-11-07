"use client";

import React, { useState, useEffect } from 'react';
import {
  pbMedia,
  StudioSettingsRecord
} from '@/lib/pocketbase';
import {
  SlidersHorizontal,
  Volume2,
  Video,
  Scissors,
  Save,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  Smartphone,
  Monitor,
  Sparkles
} from 'lucide-react';

interface SchnittParameterTabProps {
  themeMode?: 'light' | 'dark';
}

interface CutSettings {
  shortsTargetSec: number;
  youtubeTargetSec: number;
  shortsResolution: string;
  youtubeResolution: string;
  aspectMode: 'blur_pillars' | 'smart_crop' | 'fit_letterbox';
  audioLufsShorts: number;
  audioLufsYouTube: number;
  truePeakLimit: number;
  enableNoiseGate: boolean;
  enableDynamicComp: boolean;
  transitionType: 'hard_cut' | 'crossfade' | 'dip_black' | 'zoom_punch';
  transitionDurationSec: number;
  removeSilences: boolean;
  silenceThresholdDb: number;
  enableAutoSubtitles: boolean;
  subtitleStyle: 'bold_yellow_highlight' | 'clean_white' | 'karaoke_active';
  introBumperText: string;
  outroBumperText: string;
}

const DEFAULT_CUT_SETTINGS: CutSettings = {
  shortsTargetSec: 180,
  youtubeTargetSec: 600,
  shortsResolution: '1080x1920',
  youtubeResolution: '1920x1080',
  aspectMode: 'blur_pillars',
  audioLufsShorts: -16.0,
  audioLufsYouTube: -14.0,
  truePeakLimit: -1.0,
  enableNoiseGate: true,
  enableDynamicComp: true,
  transitionType: 'crossfade',
  transitionDurationSec: 0.4,
  removeSilences: true,
  silenceThresholdDb: -32,
  enableAutoSubtitles: true,
  subtitleStyle: 'bold_yellow_highlight',
  introBumperText: '',
  outroBumperText: 'Danke fürs Zuschauen! Like & Subscribe.'
};

export function SchnittParameterTab({ themeMode = 'light' }: SchnittParameterTabProps) {
  const isLight = themeMode === 'light';

  const [settings, setSettings] = useState<CutSettings>(DEFAULT_CUT_SETTINGS);
  const [recordId, setRecordId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  const showToast = (text: string, type: 'success' | 'error' = 'success') => {
    setToast({ text, type });
    setTimeout(() => setToast(null), 3500);
  };

  const loadSettings = async () => {
    try {
      setLoading(true);
      const list = await pbMedia.collection('studio_settings').getFullList<StudioSettingsRecord>({
        filter: 'key = "cut_parameters"'
      });
      if (list.length > 0) {
        setRecordId(list[0].id);
        if (list[0].data_json) {
          const parsed = typeof list[0].data_json === 'string' ? JSON.parse(list[0].data_json) : list[0].data_json;
          setSettings({ ...DEFAULT_CUT_SETTINGS, ...parsed });
        }
      }
    } catch (err: any) {
      console.warn('Could not load cut_parameters from PB:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSettings();
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      if (recordId) {
        await pbMedia.collection('studio_settings').update(recordId, {
          data_json: settings
        });
      } else {
        const created = await pbMedia.collection('studio_settings').create<StudioSettingsRecord>({
          key: 'cut_parameters',
          data_json: settings,
          description: 'Schnitt- und Audio-Parameter für Video-Kompilationen'
        });
        setRecordId(created.id);
      }
      showToast('Schnitt-Parameter gespeichert.');
    } catch (err: any) {
      showToast(`Fehler beim Speichern: ${err.message}`, 'error');
    } finally {
      setSaving(false);
    }
  };

  const formatSecToMin = (sec: number) => {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    if (m === 0) return `${s} Sek.`;
    return `${m} Min. ${s > 0 ? s + ' Sek.' : ''}`;
  };

  const inputStyle = {
    backgroundColor: 'var(--studio-input-bg, #0f172a)',
    color: 'var(--studio-input-text, #f8fafc)',
    borderColor: 'var(--studio-input-border, #334155)'
  };

  const cardStyle = {
    backgroundColor: 'var(--studio-card-bg, #111827)',
    borderColor: 'var(--studio-card-border, #1f2937)',
    color: 'var(--studio-text, #f8fafc)'
  };

  const subCardStyle = {
    backgroundColor: 'var(--studio-input-bg, #0f172a)',
    borderColor: 'var(--studio-card-border, #1f2937)'
  };

  return (
    <div className="space-y-4 max-w-4xl">
      {/* Toast */}
      {toast && (
        <div
          className={`fixed bottom-6 right-6 z-50 px-4 py-2.5 rounded-lg shadow-xl border flex items-center gap-2.5 text-xs font-semibold ${
            toast.type === 'error'
              ? 'bg-rose-950/95 text-rose-200 border-rose-800'
              : 'bg-slate-900 text-slate-100 border-slate-700'
          }`}
        >
          {toast.type === 'error' ? <AlertCircle className="w-4 h-4 text-red-400" /> : <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
          <span>{toast.text}</span>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-xs font-bold uppercase tracking-wider font-mono text-[var(--studio-text-muted,#94a3b8)]">
            Schnitt- & Render-Parameter
          </h3>
          <p className="text-[11px] text-[var(--studio-text-muted,#94a3b8)] mt-0.5">
            Automatische Zielzeiten, Skalierungsregeln und EBU R128 Audio-Mastering
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={loadSettings}
            className="p-1.5 rounded-md text-xs font-semibold transition cursor-pointer border"
            style={subCardStyle}
            title="Neu laden"
          >
            <RefreshCw className="w-3.5 h-3.5 text-[var(--studio-text-muted,#94a3b8)]" />
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-md font-bold text-xs text-white shadow-xs transition cursor-pointer"
            style={{ backgroundColor: 'var(--studio-accent, #ef4444)' }}
          >
            <Save className="w-3.5 h-3.5" />
            <span>{saving ? 'Speichert...' : 'Speichern'}</span>
          </button>
        </div>
      </div>

      {/* Section 1: Zielzeiten & Pacing */}
      <div className="p-4 rounded-xl border space-y-3 shadow-xs" style={cardStyle}>
        <h4 className="text-xs font-bold uppercase tracking-wider font-mono flex items-center gap-1.5" style={{ color: 'var(--studio-accent, #ef4444)' }}>
          <Scissors className="w-3.5 h-3.5" />
          1. Zielzeiten für Video-Stapel
        </h4>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-1">
          {/* Shorts Target Slider */}
          <div className="space-y-2 p-3 rounded-lg border" style={subCardStyle}>
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold flex items-center gap-1.5" style={{ color: 'var(--studio-text, #f8fafc)' }}>
                <Smartphone className="w-3.5 h-3.5 text-[var(--studio-text-muted,#94a3b8)]" />
                Shorts 9:16 Zielzeit
              </span>
              <span className="text-xs font-bold font-mono" style={{ color: 'var(--studio-accent, #ef4444)' }}>
                {settings.shortsTargetSec}s ({formatSecToMin(settings.shortsTargetSec)})
              </span>
            </div>
            <input
              type="range"
              min={60}
              max={180}
              step={5}
              value={settings.shortsTargetSec}
              onChange={(e) => setSettings({ ...settings, shortsTargetSec: Number(e.target.value) })}
              className="w-full cursor-pointer"
              style={{ accentColor: 'var(--studio-accent, #ef4444)' }}
            />
            <div className="flex justify-between text-[10px] font-mono text-[var(--studio-text-muted,#94a3b8)]">
              <span>60s (1 Min)</span>
              <span>120s (2 Min)</span>
              <span>180s (3 Min)</span>
            </div>
          </div>

          {/* YouTube Target Slider */}
          <div className="space-y-2 p-3 rounded-lg border" style={subCardStyle}>
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold flex items-center gap-1.5" style={{ color: 'var(--studio-text, #f8fafc)' }}>
                <Monitor className="w-3.5 h-3.5 text-[var(--studio-text-muted,#94a3b8)]" />
                YouTube 16:9 Zielzeit
              </span>
              <span className="text-xs font-bold font-mono" style={{ color: 'var(--studio-accent, #ef4444)' }}>
                {formatSecToMin(settings.youtubeTargetSec)}
              </span>
            </div>
            <input
              type="range"
              min={480}
              max={900}
              step={30}
              value={settings.youtubeTargetSec}
              onChange={(e) => setSettings({ ...settings, youtubeTargetSec: Number(e.target.value) })}
              className="w-full cursor-pointer"
              style={{ accentColor: 'var(--studio-accent, #ef4444)' }}
            />
            <div className="flex justify-between text-[10px] font-mono text-[var(--studio-text-muted,#94a3b8)]">
              <span>8 Min</span>
              <span>10 Min</span>
              <span>15 Min</span>
            </div>
          </div>
        </div>
      </div>

      {/* Section 2: Auflösung & Video-Format */}
      <div className="p-4 rounded-xl border space-y-3 shadow-xs" style={cardStyle}>
        <h4 className="text-xs font-bold uppercase tracking-wider font-mono flex items-center gap-1.5" style={{ color: 'var(--studio-accent, #ef4444)' }}>
          <Video className="w-3.5 h-3.5" />
          2. Auflösung & Video-Format
        </h4>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-1">
          <div>
            <label className="block text-xs font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
              Shorts Auflösung
            </label>
            <select
              value={settings.shortsResolution}
              onChange={(e) => setSettings({ ...settings, shortsResolution: e.target.value })}
              className="w-full px-2.5 py-1.5 rounded-lg border text-xs focus:outline-hidden font-medium"
              style={inputStyle}
            >
              <option value="1080x1920">1080 × 1920 (Full HD)</option>
              <option value="720x1280">720 × 1280 (HD)</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
              YouTube Auflösung
            </label>
            <select
              value={settings.youtubeResolution}
              onChange={(e) => setSettings({ ...settings, youtubeResolution: e.target.value })}
              className="w-full px-2.5 py-1.5 rounded-lg border text-xs focus:outline-hidden font-medium"
              style={inputStyle}
            >
              <option value="1920x1080">1920 × 1080 (1080p)</option>
              <option value="3840x2160">3840 × 2160 (4K UHD)</option>
              <option value="1280x720">1280 × 720 (720p)</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
              Aspect Ratio Fitting
            </label>
            <select
              value={settings.aspectMode}
              onChange={(e: any) => setSettings({ ...settings, aspectMode: e.target.value })}
              className="w-full px-2.5 py-1.5 rounded-lg border text-xs focus:outline-hidden font-medium"
              style={inputStyle}
            >
              <option value="blur_pillars">Blur Background</option>
              <option value="smart_crop">Smart Center Crop</option>
              <option value="fit_letterbox">Letterbox</option>
            </select>
          </div>
        </div>

        {/* Transitions */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t" style={{ borderColor: 'var(--studio-card-border, #1f2937)' }}>
          <div>
            <label className="block text-xs font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
              Schnitt-Übergang
            </label>
            <select
              value={settings.transitionType}
              onChange={(e: any) => setSettings({ ...settings, transitionType: e.target.value })}
              className="w-full px-2.5 py-1.5 rounded-lg border text-xs focus:outline-hidden font-medium"
              style={inputStyle}
            >
              <option value="crossfade">Crossfade (0.4s)</option>
              <option value="hard_cut">Hard Cut</option>
              <option value="dip_black">Dip to Black</option>
            </select>
          </div>

          <div className="flex items-center justify-between p-2.5 rounded-lg border" style={subCardStyle}>
            <div>
              <span className="text-xs font-semibold" style={{ color: 'var(--studio-text, #f8fafc)' }}>
                Stille-Entfernung (Jump-Cut)
              </span>
              <p className="text-[10px]" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
                Pausen über 0.5s automatisch trimmen
              </p>
            </div>
            <input
              type="checkbox"
              checked={settings.removeSilences}
              onChange={(e) => setSettings({ ...settings, removeSilences: e.target.checked })}
              className="w-4 h-4 cursor-pointer"
              style={{ accentColor: 'var(--studio-accent, #ef4444)' }}
            />
          </div>
        </div>
      </div>

      {/* Section 3: Audio & Normalisierung */}
      <div className="p-4 rounded-xl border space-y-3 shadow-xs" style={cardStyle}>
        <h4 className="text-xs font-bold uppercase tracking-wider font-mono flex items-center gap-1.5" style={{ color: 'var(--studio-accent, #ef4444)' }}>
          <Volume2 className="w-3.5 h-3.5" />
          3. Audio-Normalisierung (EBU R128)
        </h4>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
          <div className="p-3 rounded-lg border space-y-1.5" style={subCardStyle}>
            <div className="flex justify-between text-xs">
              <span className="font-semibold" style={{ color: 'var(--studio-text, #f8fafc)' }}>YouTube Lautheit</span>
              <span className="font-mono font-bold" style={{ color: 'var(--studio-accent, #ef4444)' }}>
                {settings.audioLufsYouTube} LUFS
              </span>
            </div>
            <input
              type="range"
              min={-20}
              max={-10}
              step={0.5}
              value={settings.audioLufsYouTube}
              onChange={(e) => setSettings({ ...settings, audioLufsYouTube: Number(e.target.value) })}
              className="w-full cursor-pointer"
              style={{ accentColor: 'var(--studio-accent, #ef4444)' }}
            />
          </div>

          <div className="p-3 rounded-lg border space-y-1.5" style={subCardStyle}>
            <div className="flex justify-between text-xs">
              <span className="font-semibold" style={{ color: 'var(--studio-text, #f8fafc)' }}>Shorts / Social Lautheit</span>
              <span className="font-mono font-bold" style={{ color: 'var(--studio-accent, #ef4444)' }}>
                {settings.audioLufsShorts} LUFS
              </span>
            </div>
            <input
              type="range"
              min={-20}
              max={-10}
              step={0.5}
              value={settings.audioLufsShorts}
              onChange={(e) => setSettings({ ...settings, audioLufsShorts: Number(e.target.value) })}
              className="w-full cursor-pointer"
              style={{ accentColor: 'var(--studio-accent, #ef4444)' }}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
          <div className="flex items-center justify-between p-2.5 rounded-lg border" style={subCardStyle}>
            <div>
              <span className="text-xs font-semibold" style={{ color: 'var(--studio-text, #f8fafc)' }}>
                Rauschunterdrückung (Noise Gate)
              </span>
              <p className="text-[10px]" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
                Hintergrundgeräusche filtern
              </p>
            </div>
            <input
              type="checkbox"
              checked={settings.enableNoiseGate}
              onChange={(e) => setSettings({ ...settings, enableNoiseGate: e.target.checked })}
              className="w-4 h-4 cursor-pointer"
              style={{ accentColor: 'var(--studio-accent, #ef4444)' }}
            />
          </div>

          <div className="flex items-center justify-between p-2.5 rounded-lg border" style={subCardStyle}>
            <div>
              <span className="text-xs font-semibold" style={{ color: 'var(--studio-text, #f8fafc)' }}>
                True Peak Limiter (-1.0 dBTP)
              </span>
              <p className="text-[10px]" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
                Verhindert Übersteuern
              </p>
            </div>
            <input
              type="checkbox"
              checked={settings.enableDynamicComp}
              onChange={(e) => setSettings({ ...settings, enableDynamicComp: e.target.checked })}
              className="w-4 h-4 cursor-pointer"
              style={{ accentColor: 'var(--studio-accent, #ef4444)' }}
            />
          </div>
        </div>
      </div>

      {/* Section 4: Untertitel & Bumper */}
      <div className="p-4 rounded-xl border space-y-3 shadow-xs" style={cardStyle}>
        <h4 className="text-xs font-bold uppercase tracking-wider font-mono flex items-center gap-1.5" style={{ color: 'var(--studio-accent, #ef4444)' }}>
          <Sparkles className="w-3.5 h-3.5" />
          4. Untertitel & Bumper
        </h4>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
          <div>
            <label className="block text-xs font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
              Untertitel-Stil
            </label>
            <select
              value={settings.subtitleStyle}
              onChange={(e: any) => setSettings({ ...settings, subtitleStyle: e.target.value })}
              className="w-full px-2.5 py-1.5 rounded-lg border text-xs focus:outline-hidden font-medium"
              style={inputStyle}
            >
              <option value="bold_yellow_highlight">Bold Hook mit Gelber Hervorhebung</option>
              <option value="clean_white">Minimalistisch Weiß</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
              Outro CTA-Text
            </label>
            <input
              type="text"
              value={settings.outroBumperText}
              onChange={(e) => setSettings({ ...settings, outroBumperText: e.target.value })}
              placeholder="z.B. 'Jetzt abonnieren!'"
              className="w-full px-2.5 py-1.5 rounded-lg border text-xs focus:outline-hidden font-medium"
              style={inputStyle}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
