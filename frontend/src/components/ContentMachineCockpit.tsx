'use client';

import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import {
  archonApi,
  ChannelSpec,
  ContentAsset,
  ContentCampaign,
  ContentOverview,
} from '@/lib/archon-api';
import {
  CheckCircle2,
  Clapperboard,
  ExternalLink,
  Play,
  Plus,
  RefreshCw,
  Send,
  Sparkles,
  Trash2,
  Workflow,
  BarChart3,
} from 'lucide-react';

const STATUS_BADGE: Record<string, string> = {
  draft: 'bg-slate-800 text-slate-300 border-slate-700',
  review: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  approved: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  scheduled: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
  published: 'bg-indigo-500/20 text-indigo-300 border-indigo-500/40',
  rejected: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
};

export function ContentMachineCockpit() {
  const [overview, setOverview] = useState<ContentOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  // Campaign creation form
  const [title, setTitle] = useState('');
  const [topic, setTopic] = useState('');
  const [audience, setAudience] = useState('Gruender, Geschaeftsfuehrer & Tech-Entscheider');
  const [notes, setNotes] = useState('');
  const [selectedChannels, setSelectedChannels] = useState<string[]>([
    'linkedin',
    'youtube_longform',
    'youtube_shorts',
    'tiktok',
  ]);

  // Filters
  const [channelFilter, setChannelFilter] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [editingAsset, setEditingAsset] = useState<ContentAsset | null>(null);
  const [metricsAsset, setMetricsAsset] = useState<ContentAsset | null>(null);
  const [metricForm, setMetricForm] = useState({
    views: 0,
    likes: 0,
    comments: 0,
    shares: 0,
    saves: 0,
    ctr_pct: 0,
  });

  // Content-Maschine v2: Quellen-Ingestion
  const [ingestType, setIngestType] = useState<'url' | 'obsidian' | 'transcript'>('url');
  const [ingestInput, setIngestInput] = useState('');
  const [ingestTitle, setIngestTitle] = useState('');

  const loadOverview = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await archonApi.getContentOverview();
      setOverview(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Fehler beim Laden der Content-Maschine');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadOverview();
  }, [loadOverview]);

  const toggleChannel = (ch: string) => {
    setSelectedChannels((prev) =>
      prev.includes(ch) ? prev.filter((x) => x !== ch) : [...prev, ch]
    );
  };

  const handleCreateCampaign = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    setBusyId('create');
    setError(null);
    try {
      await archonApi.createCampaign({
        title: title.trim(),
        topic: (topic || title).trim(),
        target_audience: audience.trim(),
        source_notes: notes.trim(),
        channels: selectedChannels.length > 0 ? selectedChannels : ['linkedin', 'youtube_shorts', 'tiktok'],
      });
      setTitle('');
      setTopic('');
      setNotes('');
      await loadOverview();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Kampagne konnte nicht angelegt werden');
    } finally {
      setBusyId(null);
    }
  };

  const handleGenerate = async (camp: ContentCampaign, dryRun: boolean) => {
    setBusyId(camp.id);
    setError(null);
    try {
      await archonApi.generateCampaignAssets(camp.id, {
        dry_run: dryRun,
        require_hitl_gate: true,
        background: false,
      });
      await loadOverview();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'DAG-Generierung fehlgeschlagen');
    } finally {
      setBusyId(null);
    }
  };

  const handleDeleteCampaign = async (id: string) => {
    setBusyId(id);
    try {
      await archonApi.deleteCampaign(id);
      await loadOverview();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Loeschen fehlgeschlagen');
    } finally {
      setBusyId(null);
    }
  };

  const handleApprove = async (assetId: string) => {
    setBusyId(assetId);
    try {
      await archonApi.approveAsset(assetId);
      await loadOverview();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Freigabe fehlgeschlagen');
    } finally {
      setBusyId(null);
    }
  };

  const handlePublish = async (assetId: string) => {
    const url = window.prompt('Optional: Veroeffentlichte Post-/Video-URL eingeben:', '') || '';
    setBusyId(assetId);
    try {
      await archonApi.publishAsset(assetId, url);
      await loadOverview();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Publishing fehlgeschlagen');
    } finally {
      setBusyId(null);
    }
  };

  const handleSaveAssetEdit = async () => {
    if (!editingAsset) return;
    setBusyId(editingAsset.id);
    try {
      await archonApi.updateAsset(editingAsset.id, {
        title: editingAsset.title,
        hook: editingAsset.hook,
        body: editingAsset.body,
        visual_brief: editingAsset.visual_brief,
        cta: editingAsset.cta,
      });
      setEditingAsset(null);
      await loadOverview();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Speichern fehlgeschlagen');
    } finally {
      setBusyId(null);
    }
  };

  const handleSaveMetrics = async () => {
    if (!metricsAsset) return;
    setBusyId(metricsAsset.id);
    try {
      await archonApi.recordAssetMetrics(metricsAsset.id, metricForm);
      setMetricsAsset(null);
      await loadOverview();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Metriken konnten nicht gespeichert werden');
    } finally {
      setBusyId(null);
    }
  };

  const handleIngestSource = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ingestInput.trim()) return;
    setBusyId('ingest');
    setError(null);
    try {
      await archonApi.ingestSource({
        source_type: ingestType,
        title: ingestTitle.trim() || undefined,
        source_url: ingestType === 'url' ? ingestInput.trim() : undefined,
        obsidian_path: ingestType === 'obsidian' ? ingestInput.trim() : undefined,
        transcript: ingestType === 'transcript' ? ingestInput.trim() : undefined,
        channels: selectedChannels.length > 0 ? selectedChannels : ['linkedin', 'youtube_shorts', 'tiktok'],
      });
      setIngestInput('');
      setIngestTitle('');
      await loadOverview();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Quellen-Ingestion fehlgeschlagen');
    } finally {
      setBusyId(null);
    }
  };

  const handleClipMatrix = async (campId: string, dryRun: boolean) => {
    setBusyId(`clip:${campId}`);
    setError(null);
    try {
      await archonApi.generateClipMatrix(campId, { clip_count: 3, dry_run: dryRun });
      await loadOverview();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Clip-Matrix konnte nicht erzeugt werden');
    } finally {
      setBusyId(null);
    }
  };

  const handlePublishDue = async () => {
    setBusyId('publish-due');
    setError(null);
    try {
      await archonApi.publishDueAssets({ dry_run: false });
      await loadOverview();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Faellige Veroeffentlichung fehlgeschlagen');
    } finally {
      setBusyId(null);
    }
  };

  const channels: ChannelSpec[] = overview?.channels || [];
  const campaigns = overview?.campaigns || [];
  const filteredAssets = (overview?.assets || []).filter((a) => {
    if (channelFilter !== 'all' && a.channel !== channelFilter) return false;
    if (statusFilter !== 'all' && a.status !== statusFilter) return false;
    return true;
  });

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <header className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-fuchsia-600 flex items-center justify-center shadow-lg">
              <Clapperboard className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-tight">Archon Content-Maschine v1</h1>
              <p className="text-xs text-slate-400 font-mono">
                LinkedIn · YouTube Longform &amp; Shorts · TikTok · X/Threads · Newsletter — Direkt auf Archon FastAPI
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Link
              href="/workflows"
              className="px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-900 hover:bg-slate-800 text-xs font-medium flex items-center gap-1.5"
            >
              <Workflow className="w-3.5 h-3.5 text-indigo-400" />
              Workflow-Cockpit
            </Link>
            <Link
              href="/"
              className="px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-900 hover:bg-slate-800 text-xs font-medium"
            >
              Zurueck zum Cockpit
            </Link>
            <button
              onClick={loadOverview}
              disabled={loading}
              className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold flex items-center gap-1.5"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              Aktualisieren
            </button>
          </div>
        </header>

        {error && (
          <div className="p-3 rounded-lg border border-rose-500/40 bg-rose-500/10 text-rose-200 text-xs">
            {error}
          </div>
        )}

        {/* KPI Bar */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {[
            { label: 'Kampagnen', value: campaigns.length },
            { label: 'In Review (HITL)', value: overview?.status_counts?.review || 0 },
            { label: 'Freigegeben', value: (overview?.status_counts?.approved || 0) + (overview?.status_counts?.scheduled || 0) },
            { label: 'Veroeffentlicht', value: overview?.status_counts?.published || 0 },
            { label: 'Aktive Kanaele', value: channels.length },
          ].map((kpi) => (
            <div key={kpi.label} className="p-3.5 rounded-xl border border-slate-800 bg-slate-900/70">
              <div className="text-[11px] font-mono uppercase text-slate-400">{kpi.label}</div>
              <div className="text-2xl font-bold mt-1">{kpi.value}</div>
            </div>
          ))}
        </div>

        {/* Campaign Creator + Campaign List */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
          <form
            onSubmit={handleCreateCampaign}
            className="lg:col-span-5 p-4 rounded-xl border border-slate-800 bg-slate-900/70 space-y-3"
          >
            <h2 className="text-sm font-bold flex items-center gap-2">
              <Plus className="w-4 h-4 text-indigo-400" />
              Neue Multi-Channel-Kampagne
            </h2>
            <div>
              <label className="block text-[11px] font-mono text-slate-400 mb-1">Kampagnen-Titel</label>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="z. B. Warum Multi-Agenten-Workflows 2026 klassische SaaS ersetzen"
                className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-sm focus:outline-none focus:border-indigo-500"
                required
              />
            </div>
            <div>
              <label className="block text-[11px] font-mono text-slate-400 mb-1">Kernthema / These</label>
              <input
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="Optional praezisere These oder Kernfrage"
                className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-sm focus:outline-none focus:border-indigo-500"
              />
            </div>
            <div>
              <label className="block text-[11px] font-mono text-slate-400 mb-1">Zielgruppe</label>
              <input
                value={audience}
                onChange={(e) => setAudience(e.target.value)}
                className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs focus:outline-none focus:border-indigo-500"
              />
            </div>
            <div>
              <label className="block text-[11px] font-mono text-slate-400 mb-1">Quell-Notizen / Fakten</label>
              <textarea
                rows={3}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Zahlen, Kundenbeispiele, Links oder Kernargumente..."
                className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs focus:outline-none focus:border-indigo-500"
              />
            </div>
            <div>
              <label className="block text-[11px] font-mono text-slate-400 mb-1.5">Ziel-Kanaele</label>
              <div className="flex flex-wrap gap-1.5">
                {channels.map((ch) => {
                  const active = selectedChannels.includes(ch.id);
                  return (
                    <button
                      type="button"
                      key={ch.id}
                      onClick={() => toggleChannel(ch.id)}
                      className={`px-2.5 py-1 rounded-md text-xs border transition ${
                        active
                          ? 'bg-indigo-600/25 border-indigo-500 text-indigo-200'
                          : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      {ch.label}
                    </button>
                  );
                })}
              </div>
            </div>
            <button
              type="submit"
              disabled={busyId === 'create'}
              className="w-full py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-sm font-semibold flex items-center justify-center gap-2"
            >
              <Sparkles className="w-4 h-4" />
              Kampagne anlegen
            </button>
          </form>

          {/* Campaigns List */}
          <div className="lg:col-span-7 p-4 rounded-xl border border-slate-800 bg-slate-900/70 space-y-3">
            <h2 className="text-sm font-bold">Aktive Kampagnen &amp; Repurposing-DAGs</h2>
            {campaigns.length === 0 ? (
              <p className="text-xs text-slate-400 py-6 text-center">
                Noch keine Kampagne angelegt. Erstelle links deine erste Multi-Channel-Kampagne.
              </p>
            ) : (
              <div className="space-y-2.5 max-h-[380px] overflow-y-auto pr-1">
                {campaigns.map((camp) => (
                  <div
                    key={camp.id}
                    className="p-3 rounded-lg border border-slate-800 bg-slate-950/70 flex flex-wrap items-center justify-between gap-3"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-sm truncate">{camp.title}</span>
                        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-300">
                          {camp.status}
                        </span>
                      </div>
                      <div className="text-[11px] text-slate-400 mt-0.5 truncate">
                        Kanaele: {camp.channels.join(', ')}
                        {camp.workflow_run_id ? ` · Run: ${camp.workflow_run_id}` : ''}
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <button
                        onClick={() => handleGenerate(camp, false)}
                        disabled={busyId === camp.id}
                        className="px-2.5 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-500 text-xs font-semibold flex items-center gap-1"
                        title="Echten Multi-Agenten-DAG mit LLM ausfuehren"
                      >
                        <Play className="w-3 h-3" />
                        DAG starten
                      </button>
                      <button
                        onClick={() => handleGenerate(camp, true)}
                        disabled={busyId === camp.id}
                        className="px-2.5 py-1.5 rounded-md border border-slate-700 bg-slate-900 hover:bg-slate-800 text-xs"
                        title="Schneller Struktur-Test ohne LLM-Kosten"
                      >
                        Dry-Run
                      </button>
                      <button
                        onClick={() => handleClipMatrix(camp.id, false)}
                        disabled={busyId === `clip:${camp.id}`}
                        className="px-2.5 py-1.5 rounded-md border border-fuchsia-500/40 bg-fuchsia-500/10 hover:bg-fuchsia-500/20 text-fuchsia-200 text-xs"
                        title="3x 9:16 Shorts & TikTok Clips aus Kampagne ableiten"
                      >
                        9:16 Clips
                      </button>
                      <button
                        onClick={() => handleDeleteCampaign(camp.id)}
                        disabled={busyId === camp.id}
                        className="p-1.5 rounded-md text-rose-400 hover:bg-rose-500/10"
                        title="Kampagne loeschen"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Quellen-Ingestion v2 (URL / Obsidian / Transkript -> Kampagne) */}
        <form
          onSubmit={handleIngestSource}
          className="p-4 rounded-xl border border-slate-800 bg-slate-900/70 flex flex-wrap items-end gap-3"
        >
          <div className="w-40">
            <label className="block text-[11px] font-mono text-slate-400 mb-1">Quelle (1 &rarr; 6 Kanaele)</label>
            <select
              value={ingestType}
              onChange={(e) => setIngestType(e.target.value as 'url' | 'obsidian' | 'transcript')}
              className="w-full px-2.5 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs"
            >
              <option value="url">Web-Artikel URL</option>
              <option value="obsidian">Obsidian-Notiz</option>
              <option value="transcript">Rohtranskript</option>
            </select>
          </div>
          <div className="w-56">
            <label className="block text-[11px] font-mono text-slate-400 mb-1">Optionaler Titel</label>
            <input
              value={ingestTitle}
              onChange={(e) => setIngestTitle(e.target.value)}
              placeholder="Auto-Erkennung wenn leer"
              className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs"
            />
          </div>
          <div className="flex-1 min-w-[240px]">
            <label className="block text-[11px] font-mono text-slate-400 mb-1">
              {ingestType === 'url' ? 'https://...' : ingestType === 'obsidian' ? '01_PROJEKTE/.../Bericht.md' : 'Transkript / Notizen'}
            </label>
            <input
              value={ingestInput}
              onChange={(e) => setIngestInput(e.target.value)}
              placeholder={ingestType === 'url' ? 'https://example.com/artikel' : 'Inhalt oder Pfad eingeben'}
              className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs"
              required
            />
          </div>
          <button
            type="submit"
            disabled={busyId === 'ingest'}
            className="px-4 py-2 rounded-lg bg-fuchsia-600 hover:bg-fuchsia-500 text-xs font-semibold"
          >
            Quelle einlesen
          </button>
        </form>

        {/* Assets & Editorial Queue */}
        <section className="p-4 rounded-xl border border-slate-800 bg-slate-900/70 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-sm font-bold">Redaktions- &amp; Publishing-Queue ({filteredAssets.length} Assets)</h2>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <button
                type="button"
                onClick={handlePublishDue}
                disabled={busyId === 'publish-due'}
                className="px-2.5 py-1.5 rounded-lg border border-indigo-500/40 bg-indigo-500/15 hover:bg-indigo-500/25 text-indigo-200 font-medium"
              >
                Faellige publizieren
              </button>
              <select
                value={channelFilter}
                onChange={(e) => setChannelFilter(e.target.value)}
                className="px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-800"
              >
                <option value="all">Alle Kanaele</option>
                {channels.map((ch) => (
                  <option key={ch.id} value={ch.id}>
                    {ch.label}
                  </option>
                ))}
              </select>
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-800"
              >
                <option value="all">Alle Status</option>
                <option value="draft">Entwurf</option>
                <option value="review">In Review (HITL)</option>
                <option value="approved">Freigegeben</option>
                <option value="scheduled">Geplant</option>
                <option value="published">Veroeffentlicht</option>
              </select>
            </div>
          </div>

          {filteredAssets.length === 0 ? (
            <p className="text-xs text-slate-400 py-8 text-center">
              Keine Assets fuer diesen Filter vorhanden. Starte oben einen Kampagnen-DAG.
            </p>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {filteredAssets.map((asset) => (
                <article
                  key={asset.id}
                  className="p-3.5 rounded-xl border border-slate-800 bg-slate-950/80 space-y-2.5 flex flex-col justify-between"
                >
                  <div className="space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[10px] font-mono uppercase px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                        {asset.channel}
                      </span>
                      <div className="flex items-center gap-1.5">
                        {typeof asset.quality_score === 'number' && (
                          <span
                            className={`text-[10px] font-mono px-2 py-0.5 rounded border ${
                              asset.quality_score >= 70
                                ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                                : 'bg-rose-500/15 text-rose-300 border-rose-500/30'
                            }`}
                            title={(asset.quality_report?.issues || []).join(' | ') || 'Qualitaets-Score'}
                          >
                            Q: {asset.quality_score}/100
                          </span>
                        )}
                        <span
                          className={`text-[10px] font-mono px-2 py-0.5 rounded border ${
                            STATUS_BADGE[asset.status] || STATUS_BADGE.draft
                          }`}
                        >
                          {asset.status}
                        </span>
                      </div>
                    </div>
                    <h3 className="font-semibold text-sm">{asset.title}</h3>
                    {asset.hook && (
                      <div className="text-xs text-amber-200/90 bg-amber-500/10 border border-amber-500/20 rounded-md p-2">
                        <span className="font-mono text-[10px] uppercase text-amber-400 block">Hook</span>
                        {asset.hook}
                      </div>
                    )}
                    <p className="text-xs text-slate-300 whitespace-pre-wrap line-clamp-5">{asset.body}</p>
                    {asset.visual_brief && (
                      <div className="text-[11px] text-slate-400">
                        <strong className="text-slate-300">Visual-Brief:</strong> {asset.visual_brief}
                      </div>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5 pt-2 border-t border-slate-800/80">
                    <button
                      onClick={() => setEditingAsset({ ...asset })}
                      className="px-2.5 py-1 rounded-md border border-slate-700 bg-slate-900 hover:bg-slate-800 text-xs"
                    >
                      Bearbeiten
                    </button>
                    {(asset.status === 'review' || asset.status === 'draft') && (
                      <button
                        onClick={() => handleApprove(asset.id)}
                        disabled={busyId === asset.id}
                        className="px-2.5 py-1 rounded-md bg-emerald-600 hover:bg-emerald-500 text-xs font-medium flex items-center gap-1"
                      >
                        <CheckCircle2 className="w-3 h-3" />
                        Freigeben
                      </button>
                    )}
                    {(asset.status === 'approved' || asset.status === 'scheduled') && (
                      <button
                        onClick={() => handlePublish(asset.id)}
                        disabled={busyId === asset.id}
                        className="px-2.5 py-1 rounded-md bg-indigo-600 hover:bg-indigo-500 text-xs font-medium flex items-center gap-1"
                      >
                        <Send className="w-3 h-3" />
                        Als live markieren
                      </button>
                    )}
                    <button
                      onClick={() => {
                        setMetricsAsset(asset);
                        setMetricForm({ views: 0, likes: 0, comments: 0, shares: 0, saves: 0, ctr_pct: 0 });
                      }}
                      className="px-2.5 py-1 rounded-md border border-slate-700 bg-slate-900 hover:bg-slate-800 text-xs flex items-center gap-1"
                    >
                      <BarChart3 className="w-3 h-3 text-sky-400" />
                      Metriken
                    </button>
                    {asset.external_url && (
                      <a
                        href={asset.external_url}
                        target="_blank"
                        rel="noreferrer"
                        className="ml-auto text-xs text-sky-400 hover:underline flex items-center gap-1"
                      >
                        Link <ExternalLink className="w-3 h-3" />
                      </a>
                    )}
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>

        {/* Edit Modal */}
        {editingAsset && (
          <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50">
            <div className="w-full max-w-2xl rounded-xl border border-slate-700 bg-slate-900 p-5 space-y-3">
              <h3 className="font-bold text-sm">Asset bearbeiten ({editingAsset.channel})</h3>
              <input
                value={editingAsset.title}
                onChange={(e) => setEditingAsset({ ...editingAsset, title: e.target.value })}
                className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-sm"
              />
              <textarea
                rows={2}
                value={editingAsset.hook}
                onChange={(e) => setEditingAsset({ ...editingAsset, hook: e.target.value })}
                placeholder="Hook"
                className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs"
              />
              <textarea
                rows={7}
                value={editingAsset.body}
                onChange={(e) => setEditingAsset({ ...editingAsset, body: e.target.value })}
                placeholder="Haupttext / Skript"
                className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs font-mono"
              />
              <input
                value={editingAsset.visual_brief}
                onChange={(e) => setEditingAsset({ ...editingAsset, visual_brief: e.target.value })}
                placeholder="Visual-Brief / Thumbnail / Schnitt-Cues"
                className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs"
              />
              <div className="flex justify-end gap-2 pt-2">
                <button
                  onClick={() => setEditingAsset(null)}
                  className="px-3 py-1.5 rounded-lg border border-slate-700 text-xs"
                >
                  Abbrechen
                </button>
                <button
                  onClick={handleSaveAssetEdit}
                  className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold"
                >
                  Speichern
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Metrics Feedback Modal */}
        {metricsAsset && (
          <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50">
            <div className="w-full max-w-md rounded-xl border border-slate-700 bg-slate-900 p-5 space-y-3">
              <h3 className="font-bold text-sm">Performance erfassen ({metricsAsset.channel})</h3>
              <p className="text-xs text-slate-400">
                Starke Gewinner (&ge;5% Engagement oder &ge;1.000 Views) werden automatisch als Learning im Archon-Memory gespeichert.
              </p>
              <div className="grid grid-cols-2 gap-2 text-xs">
                {(['views', 'likes', 'comments', 'shares', 'saves', 'ctr_pct'] as const).map((k) => (
                  <label key={k} className="space-y-1">
                    <span className="text-slate-400 font-mono uppercase">{k}</span>
                    <input
                      type="number"
                      step={k === 'ctr_pct' ? '0.1' : '1'}
                      value={metricForm[k]}
                      onChange={(e) => setMetricForm({ ...metricForm, [k]: Number(e.target.value) })}
                      className="w-full px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-800"
                    />
                  </label>
                ))}
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  onClick={() => setMetricsAsset(null)}
                  className="px-3 py-1.5 rounded-lg border border-slate-700 text-xs"
                >
                  Abbrechen
                </button>
                <button
                  onClick={handleSaveMetrics}
                  className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-xs font-semibold"
                >
                  Speichern &amp; Lernen
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
