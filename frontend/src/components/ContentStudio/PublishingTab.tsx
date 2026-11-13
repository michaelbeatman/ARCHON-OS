"use client";

import React, { useState, useEffect } from 'react';
import {
  pbMedia,
  StudioSettingsRecord
} from '@/lib/pocketbase';
import {
  Share2,
  Send,
  Download,
  Save,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  Radio
} from 'lucide-react';

function YoutubeIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" {...props}>
      <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/>
    </svg>
  );
}

function LinkedinIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" {...props}>
      <path d="M19 3a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14m-.5 15.5v-5.3a3.26 3.26 0 0 0-3.26-3.26c-.85 0-1.84.52-2.28 1.3v-1.11h-2.79v8.37h2.79v-4.93c0-.77.62-1.4 1.39-1.4a1.4 1.4 0 0 1 1.4 1.4v4.93h2.75M6.46 10.9v8.37H9.2V10.9H6.46M7.83 6.64c-.87 0-1.57.7-1.57 1.57 0 .86.7 1.57 1.57 1.57.86 0 1.57-.71 1.57-1.57 0-.87-.71-1.57-1.57-1.57z"/>
    </svg>
  );
}

interface PublishingTabProps {
  themeMode?: 'light' | 'dark';
}

interface PublishingConfig {
  youtubeChannelName: string;
  youtubePrivacy: 'private' | 'unlisted' | 'public';
  youtubeAutoUpload: boolean;
  linkedinWebhookUrl: string;
  linkedinAutoSchedule: boolean;
  telegramChatId: string;
  telegramBotEnabled: boolean;
  autoRenderOnBatchFull: boolean;
}

const DEFAULT_PUBLISHING_CONFIG: PublishingConfig = {
  youtubeChannelName: 'Archon Media HQ',
  youtubePrivacy: 'unlisted',
  youtubeAutoUpload: false,
  linkedinWebhookUrl: '',
  linkedinAutoSchedule: false,
  telegramChatId: '-10023456789',
  telegramBotEnabled: true,
  autoRenderOnBatchFull: true
};

export function PublishingTab({ themeMode = 'light' }: PublishingTabProps) {
  const isLight = themeMode === 'light';

  const [config, setConfig] = useState<PublishingConfig>(DEFAULT_PUBLISHING_CONFIG);
  const [recordId, setRecordId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  const showToast = (text: string, type: 'success' | 'error' = 'success') => {
    setToast({ text, type });
    setTimeout(() => setToast(null), 3500);
  };

  const loadConfig = async () => {
    try {
      setLoading(true);
      const list = await pbMedia.collection('studio_settings').getFullList<StudioSettingsRecord>({
        filter: 'key = "publishing_channels"'
      });
      if (list.length > 0) {
        setRecordId(list[0].id);
        if (list[0].data_json) {
          const parsed = typeof list[0].data_json === 'string' ? JSON.parse(list[0].data_json) : list[0].data_json;
          setConfig({ ...DEFAULT_PUBLISHING_CONFIG, ...parsed });
        }
      }
    } catch (err: any) {
      console.warn('Could not load publishing_channels from PB:', err);
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
          key: 'publishing_channels',
          data_json: config,
          description: 'Veröffentlichungskanäle und Webhooks'
        });
        setRecordId(created.id);
      }
      showToast('Einstellungen gespeichert.');
    } catch (err: any) {
      showToast(`Fehler beim Speichern: ${err.message}`, 'error');
    } finally {
      setSaving(false);
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
            Veröffentlichung & Export-Kanäle
          </h3>
          <p className="text-[11px] text-[var(--studio-text-muted,#94a3b8)] mt-0.5">
            Distribution über YouTube, LinkedIn, Telegram und lokale Exporte
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

      {/* Channels Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* YouTube Channel */}
        <div className="p-4 rounded-xl border space-y-3 shadow-xs" style={cardStyle}>
          <div className="flex items-center justify-between pb-2 border-b" style={{ borderColor: 'var(--studio-card-border, #1f2937)' }}>
            <span className="text-xs font-bold flex items-center gap-2" style={{ color: 'var(--studio-text, #f8fafc)' }}>
              <YoutubeIcon className="w-4 h-4" style={{ color: 'var(--studio-accent, #ef4444)' }} />
              YouTube / YouTube Shorts
            </span>
            <span className="text-[9px] font-mono px-1.5 py-0.5 rounded border" style={subCardStyle}>
              Kanal-Sync
            </span>
          </div>

          <div className="space-y-2.5 text-xs">
            <div>
              <label className="block font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>Kanal-Name</label>
              <input
                type="text"
                value={config.youtubeChannelName}
                onChange={(e) => setConfig({ ...config, youtubeChannelName: e.target.value })}
                className="w-full px-2.5 py-1.5 rounded-lg border font-medium focus:outline-hidden"
                style={inputStyle}
              />
            </div>

            <div>
              <label className="block font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>Sichtbarkeit</label>
              <select
                value={config.youtubePrivacy}
                onChange={(e: any) => setConfig({ ...config, youtubePrivacy: e.target.value })}
                className="w-full px-2.5 py-1.5 rounded-lg border font-medium focus:outline-hidden"
                style={inputStyle}
              >
                <option value="unlisted">Nicht gelistet (Unlisted)</option>
                <option value="private">Privat (Private)</option>
                <option value="public">Öffentlich (Public)</option>
              </select>
            </div>
          </div>
        </div>

        {/* LinkedIn Channel */}
        <div className="p-4 rounded-xl border space-y-3 shadow-xs" style={cardStyle}>
          <div className="flex items-center justify-between pb-2 border-b" style={{ borderColor: 'var(--studio-card-border, #1f2937)' }}>
            <span className="text-xs font-bold flex items-center gap-2" style={{ color: 'var(--studio-text, #f8fafc)' }}>
              <LinkedinIcon className="w-4 h-4 text-slate-300" />
              LinkedIn Publishing Webhook
            </span>
            <span className="text-[9px] font-mono px-1.5 py-0.5 rounded border" style={subCardStyle}>
              Feed Sync
            </span>
          </div>

          <div className="space-y-2.5 text-xs">
            <div>
              <label className="block font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>Webhook Endpoint</label>
              <input
                type="url"
                placeholder="https://..."
                value={config.linkedinWebhookUrl}
                onChange={(e) => setConfig({ ...config, linkedinWebhookUrl: e.target.value })}
                className="w-full px-2.5 py-1.5 rounded-lg border font-medium focus:outline-hidden"
                style={inputStyle}
              />
            </div>

            <div className="flex items-center justify-between p-2 rounded-lg border" style={subCardStyle}>
              <div>
                <span className="text-xs font-semibold" style={{ color: 'var(--studio-text, #f8fafc)' }}>Automatische Veröffentlichung</span>
                <p className="text-[10px]" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>Bei Status 'scheduled' direkt ausführen</p>
              </div>
              <input
                type="checkbox"
                checked={config.linkedinAutoSchedule}
                onChange={(e) => setConfig({ ...config, linkedinAutoSchedule: e.target.checked })}
                className="w-4 h-4 cursor-pointer"
                style={{ accentColor: 'var(--studio-accent, #ef4444)' }}
              />
            </div>
          </div>
        </div>

        {/* Telegram Channel */}
        <div className="p-4 rounded-xl border space-y-3 shadow-xs" style={cardStyle}>
          <div className="flex items-center justify-between pb-2 border-b" style={{ borderColor: 'var(--studio-card-border, #1f2937)' }}>
            <span className="text-xs font-bold flex items-center gap-2" style={{ color: 'var(--studio-text, #f8fafc)' }}>
              <Send className="w-4 h-4 text-slate-300" />
              Telegram Broadcast (@Beatman_bot)
            </span>
            <span className="text-[9px] font-mono px-1.5 py-0.5 rounded border" style={subCardStyle}>
              Hermes Bot
            </span>
          </div>

          <div className="space-y-2.5 text-xs">
            <div>
              <label className="block font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>Chat-ID</label>
              <input
                type="text"
                value={config.telegramChatId}
                onChange={(e) => setConfig({ ...config, telegramChatId: e.target.value })}
                className="w-full px-2.5 py-1.5 rounded-lg border font-mono font-medium focus:outline-hidden"
                style={inputStyle}
              />
            </div>

            <div className="flex items-center justify-between p-2 rounded-lg border" style={subCardStyle}>
              <div>
                <span className="text-xs font-semibold" style={{ color: 'var(--studio-text, #f8fafc)' }}>Push-Benachrichtigung</span>
                <p className="text-[10px]" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>Fertige Videos in den Chat senden</p>
              </div>
              <input
                type="checkbox"
                checked={config.telegramBotEnabled}
                onChange={(e) => setConfig({ ...config, telegramBotEnabled: e.target.checked })}
                className="w-4 h-4 cursor-pointer"
                style={{ accentColor: 'var(--studio-accent, #ef4444)' }}
              />
            </div>
          </div>
        </div>

        {/* Auto Automation Triggers */}
        <div className="p-4 rounded-xl border space-y-3 shadow-xs" style={cardStyle}>
          <div className="flex items-center justify-between pb-2 border-b" style={{ borderColor: 'var(--studio-card-border, #1f2937)' }}>
            <span className="text-xs font-bold flex items-center gap-2" style={{ color: 'var(--studio-text, #f8fafc)' }}>
              <Radio className="w-4 h-4" style={{ color: 'var(--studio-accent, #ef4444)' }} />
              Automatisierungs-Trigger
            </span>
            <span className="text-[9px] font-mono px-1.5 py-0.5 rounded border" style={subCardStyle}>
              Auto-Stitch
            </span>
          </div>

          <div className="space-y-2.5 text-xs">
            <div className="flex items-center justify-between p-2.5 rounded-lg border" style={subCardStyle}>
              <div>
                <span className="text-xs font-semibold" style={{ color: 'var(--studio-text, #f8fafc)' }}>Auto-Render bei vollem Stapel</span>
                <p className="text-[10px]" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
                  Startet Rendering automatisch bei 100% Füllstand
                </p>
              </div>
              <input
                type="checkbox"
                checked={config.autoRenderOnBatchFull}
                onChange={(e) => setConfig({ ...config, autoRenderOnBatchFull: e.target.checked })}
                className="w-4 h-4 cursor-pointer"
                style={{ accentColor: 'var(--studio-accent, #ef4444)' }}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
