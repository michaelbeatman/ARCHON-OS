"use client";

import React, { useState, useEffect } from 'react';
import {
  pbMedia,
  StudioSettingsRecord
} from '@/lib/pocketbase';
import {
  Cpu,
  Bot,
  Save,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  Sparkles,
  Server,
  Radio
} from 'lucide-react';

interface AIProviderTabProps {
  themeMode?: 'light' | 'dark';
}

interface AIConfig {
  omnirouteUrl: string;
  defaultProvider: 'omniroute' | 'gemini' | 'groq' | 'openrouter';
  linkedinModel: string;
  transcriptionModel: string;
  titlerModel: string;
  temperature: number;
  systemPromptLinkedIn: string;
  systemPromptVideoTitler: string;
}

const DEFAULT_AI_CONFIG: AIConfig = {
  omnirouteUrl: 'http://localhost:20128/v1',
  defaultProvider: 'omniroute',
  linkedinModel: 'google/gemini-2.5-flash',
  transcriptionModel: 'whisper-large-v3',
  titlerModel: 'meta-llama/llama-3.3-70b-instruct',
  temperature: 0.7,
  systemPromptLinkedIn: `Du bist ein erfahrener B2B-Ghostwriter für Executives.
Schreibe auf Deutsch. Keine typischen KI-Floskeln (kein 'Tauchen wir ein', 'In der heutigen dynamischen Welt', 'Lasst uns diskutieren').
Verwende saubere Absätze, pointierte Sätze und hohe Informationsdichte.`,
  systemPromptVideoTitler: `Erstelle 3 klickstarke, aber seriöse YouTube & Shorts-Titel für ein B2B/Tech-Video. Kein billiger Clickbait, sondern hoher Neugierfaktor mit Substanz.`
};

export function AIProviderTab({ themeMode = 'light' }: AIProviderTabProps) {
  const isLight = themeMode === 'light';

  const [config, setConfig] = useState<AIConfig>(DEFAULT_AI_CONFIG);
  const [recordId, setRecordId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [pingStatus, setPingStatus] = useState<'idle' | 'testing' | 'online' | 'offline'>('idle');
  const [toast, setToast] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  const showToast = (text: string, type: 'success' | 'error' = 'success') => {
    setToast({ text, type });
    setTimeout(() => setToast(null), 3500);
  };

  const loadConfig = async () => {
    try {
      setLoading(true);
      const list = await pbMedia.collection('studio_settings').getFullList<StudioSettingsRecord>({
        filter: 'key = "ai_providers"'
      });
      if (list.length > 0) {
        setRecordId(list[0].id);
        if (list[0].data_json) {
          const parsed = typeof list[0].data_json === 'string' ? JSON.parse(list[0].data_json) : list[0].data_json;
          setConfig({ ...DEFAULT_AI_CONFIG, ...parsed });
        }
      }
    } catch (err: any) {
      console.warn('Could not load ai_providers config from PB:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadConfig();
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      if (recordId) {
        await pbMedia.collection('studio_settings').update(recordId, {
          data_json: config
        });
      } else {
        const created = await pbMedia.collection('studio_settings').create<StudioSettingsRecord>({
          key: 'ai_providers',
          data_json: config,
          description: 'AI Provider & Model Configuration für Content Studio'
        });
        setRecordId(created.id);
      }
      showToast('KI-Konfiguration gespeichert.');
    } catch (err: any) {
      showToast(`Fehler beim Speichern: ${err.message}`, 'error');
    } finally {
      setSaving(false);
    }
  };

  const testOmniroutePing = async () => {
    setPingStatus('testing');
    try {
      const res = await fetch(`${config.omnirouteUrl}/models`, { method: 'GET' });
      if (res.ok) {
        setPingStatus('online');
        showToast('OmniRoute erreichbar (Port 20128).');
      } else {
        setPingStatus('offline');
        showToast('OmniRoute meldet Fehler.', 'error');
      }
    } catch (e) {
      setPingStatus('offline');
      showToast('OmniRoute nicht erreichbar.', 'error');
    }
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
            Provider & KI-Modelle
          </h3>
          <p className="text-[11px] text-[var(--studio-text-muted,#94a3b8)] mt-0.5">
            Zentrales LLM-Routing für Ghostwriting, Transkription und Hook-Generierung
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={loadConfig}
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

      {/* Section 1: OmniRoute Local Gateway */}
      <div className="p-4 rounded-xl border space-y-3 shadow-xs" style={cardStyle}>
        <div className="flex items-center justify-between">
          <h4 className="text-xs font-bold uppercase tracking-wider font-mono flex items-center gap-1.5" style={{ color: 'var(--studio-accent, #ef4444)' }}>
            <Server className="w-3.5 h-3.5" />
            1. OmniRoute Local Gateway
          </h4>
          <span className="flex items-center gap-1.5 text-[11px] font-mono">
            {pingStatus === 'online' && <span className="text-emerald-400">● Online (Port 20128)</span>}
            {pingStatus === 'offline' && <span className="text-red-400">● Offline</span>}
            {pingStatus === 'testing' && <span className="text-amber-400 animate-pulse">● Prüfe...</span>}
            {pingStatus === 'idle' && <span className="text-slate-500">● Nicht geprüft</span>}
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-12 gap-3 pt-1">
          <div className="md:col-span-8">
            <label className="block text-xs font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
              OmniRoute Base URL
            </label>
            <input
              type="text"
              value={config.omnirouteUrl}
              onChange={(e) => setConfig({ ...config, omnirouteUrl: e.target.value })}
              className="w-full px-2.5 py-1.5 rounded-lg border text-xs font-mono focus:outline-hidden font-medium"
              style={inputStyle}
            />
          </div>
          <div className="md:col-span-4 flex items-end">
            <button
              onClick={testOmniroutePing}
              className="w-full py-1.5 rounded-lg text-xs font-semibold flex items-center justify-center gap-1.5 border transition cursor-pointer"
              style={subCardStyle}
            >
              <Radio className="w-3.5 h-3.5 text-[var(--studio-text-muted,#94a3b8)]" />
              <span style={{ color: 'var(--studio-text, #f8fafc)' }}>Verbindung testen</span>
            </button>
          </div>
        </div>
      </div>

      {/* Section 2: Task Model Assignment */}
      <div className="p-4 rounded-xl border space-y-3 shadow-xs" style={cardStyle}>
        <h4 className="text-xs font-bold uppercase tracking-wider font-mono flex items-center gap-1.5" style={{ color: 'var(--studio-accent, #ef4444)' }}>
          <Bot className="w-3.5 h-3.5" />
          2. Modell-Zuweisung
        </h4>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-1">
          <div>
            <label className="block text-xs font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
              LinkedIn Ghostwriter Modell
            </label>
            <select
              value={config.linkedinModel}
              onChange={(e) => setConfig({ ...config, linkedinModel: e.target.value })}
              className="w-full px-2.5 py-1.5 rounded-lg border text-xs font-medium focus:outline-hidden"
              style={inputStyle}
            >
              <option value="google/gemini-2.5-flash">Google Gemini 2.5 Flash</option>
              <option value="anthropic/claude-3.5-sonnet">Claude 3.5 Sonnet</option>
              <option value="deepseek/deepseek-chat">DeepSeek Chat V3</option>
              <option value="meta-llama/llama-3.3-70b-instruct">Llama 3.3 70B</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
              Sprach-Transkription (STT)
            </label>
            <select
              value={config.transcriptionModel}
              onChange={(e) => setConfig({ ...config, transcriptionModel: e.target.value })}
              className="w-full px-2.5 py-1.5 rounded-lg border text-xs font-medium focus:outline-hidden"
              style={inputStyle}
            >
              <option value="whisper-large-v3">Whisper Large V3</option>
              <option value="groq-whisper">Groq Whisper Turbo</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
              Video Titler & Hook Modell
            </label>
            <select
              value={config.titlerModel}
              onChange={(e) => setConfig({ ...config, titlerModel: e.target.value })}
              className="w-full px-2.5 py-1.5 rounded-lg border text-xs font-medium focus:outline-hidden"
              style={inputStyle}
            >
              <option value="meta-llama/llama-3.3-70b-instruct">Llama 3.3 70B</option>
              <option value="google/gemini-2.5-flash">Gemini 2.5 Flash</option>
            </select>
          </div>
        </div>
      </div>

      {/* Section 3: Prompts */}
      <div className="p-4 rounded-xl border space-y-3 shadow-xs" style={cardStyle}>
        <h4 className="text-xs font-bold uppercase tracking-wider font-mono flex items-center gap-1.5" style={{ color: 'var(--studio-accent, #ef4444)' }}>
          <Sparkles className="w-3.5 h-3.5" />
          3. System-Prompts
        </h4>

        <div className="space-y-3 pt-1">
          <div>
            <label className="block text-xs font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
              LinkedIn Ghostwriter Prompt
            </label>
            <textarea
              rows={3}
              value={config.systemPromptLinkedIn}
              onChange={(e) => setConfig({ ...config, systemPromptLinkedIn: e.target.value })}
              className="w-full p-2.5 rounded-lg border text-xs font-mono focus:outline-hidden leading-relaxed"
              style={inputStyle}
            />
          </div>

          <div>
            <label className="block text-xs font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
              Video Titler Prompt
            </label>
            <textarea
              rows={2}
              value={config.systemPromptVideoTitler}
              onChange={(e) => setConfig({ ...config, systemPromptVideoTitler: e.target.value })}
              className="w-full p-2.5 rounded-lg border text-xs font-mono focus:outline-hidden leading-relaxed"
              style={inputStyle}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
