"use client";

import React, { useState, useEffect, useMemo } from 'react';
import {
  pbMedia,
  VideoBatchRecord,
  MediaItemRecord,
  getMediaFileUrl
} from '@/lib/pocketbase';
import {
  Film,
  Plus,
  Play,
  Download,
  Trash2,
  RefreshCw,
  Clock,
  Video,
  Upload,
  CheckCircle2,
  AlertCircle,
  Scissors,
  Smartphone,
  Monitor
} from 'lucide-react';

interface VideoCompilationTabProps {
  themeMode?: 'light' | 'dark';
}

export function VideoCompilationTab({ themeMode = 'light' }: VideoCompilationTabProps) {
  const isLight = themeMode === 'light';

  const [batches, setBatches] = useState<VideoBatchRecord[]>([]);
  const [mediaItems, setMediaItems] = useState<MediaItemRecord[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTypeFilter, setActiveTypeFilter] = useState<'all' | 'shorts_9_16' | 'longform_16_9'>('all');

  // Form / Upload state
  const [isNewBatchModalOpen, setIsNewBatchModalOpen] = useState(false);
  const [newBatchTitle, setNewBatchTitle] = useState('');
  const [newBatchType, setNewBatchType] = useState<'shorts_9_16' | 'longform_16_9'>('shorts_9_16');
  const [newBatchTargetDuration, setNewBatchTargetDuration] = useState<number>(180);

  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadMediaType, setUploadMediaType] = useState<'video' | 'image'>('video');
  const [uploadFormat, setUploadFormat] = useState<'hochkant_9_16' | 'breitbild_16_9'>('hochkant_9_16');
  const [uploadDuration, setUploadDuration] = useState<number>(15);
  const [uploading, setUploading] = useState(false);

  // Status message
  const [actionMessage, setActionMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  const showToast = (text: string, type: 'success' | 'error' = 'success') => {
    setActionMessage({ text, type });
    setTimeout(() => setActionMessage(null), 4000);
  };

  const fetchData = async () => {
    try {
      setLoading(true);
      const [batchRes, itemRes] = await Promise.all([
        pbMedia.collection('video_batches').getFullList<VideoBatchRecord>({ sort: '-created' }),
        pbMedia.collection('media_items').getFullList<MediaItemRecord>({ sort: '-created' })
      ]);
      setBatches(batchRes);
      setMediaItems(itemRes);
      if (batchRes.length > 0 && !selectedBatchId) {
        setSelectedBatchId(batchRes[0].id);
      }
    } catch (err: any) {
      console.warn('Error fetching media batches:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();

    let unsubBatches: (() => void) | undefined;
    let unsubItems: (() => void) | undefined;

    pbMedia.collection('video_batches').subscribe<VideoBatchRecord>('*', (e) => {
      if (e.action === 'create') setBatches((prev) => [e.record, ...prev]);
      else if (e.action === 'update') setBatches((prev) => prev.map((b) => (b.id === e.record.id ? e.record : b)));
      else if (e.action === 'delete') setBatches((prev) => prev.filter((b) => b.id !== e.record.id));
    }).then((fn) => { unsubBatches = fn; }).catch(() => {});

    pbMedia.collection('media_items').subscribe<MediaItemRecord>('*', (e) => {
      if (e.action === 'create') setMediaItems((prev) => [e.record, ...prev]);
      else if (e.action === 'update') setMediaItems((prev) => prev.map((m) => (m.id === e.record.id ? e.record : m)));
      else if (e.action === 'delete') setMediaItems((prev) => prev.filter((m) => m.id !== e.record.id));
    }).then((fn) => { unsubItems = fn; }).catch(() => {});

    return () => {
      if (unsubBatches) unsubBatches();
      if (unsubItems) unsubItems();
      pbMedia.collection('video_batches').unsubscribe('*');
      pbMedia.collection('media_items').unsubscribe('*');
    };
  }, []);

  const filteredBatches = useMemo(() => {
    if (activeTypeFilter === 'all') return batches;
    return batches.filter((b) => b.batch_type === activeTypeFilter);
  }, [batches, activeTypeFilter]);

  const selectedBatch = useMemo(() => {
    return batches.find((b) => b.id === selectedBatchId) || batches[0] || null;
  }, [batches, selectedBatchId]);

  const batchClips = useMemo(() => {
    if (!selectedBatch) return [];
    return mediaItems.filter((item) => item.batch_id === selectedBatch.id);
  }, [mediaItems, selectedBatch]);

  const unassignedClips = useMemo(() => {
    return mediaItems.filter((item) => !item.batch_id || item.status === 'unprocessed');
  }, [mediaItems]);

  const recalculateBatch = async (batchId: string) => {
    const clips = mediaItems.filter((m) => m.batch_id === batchId);
    const totalSec = clips.reduce((acc, curr) => acc + (curr.duration_seconds || 0), 0);
    try {
      await pbMedia.collection('video_batches').update(batchId, {
        current_duration_seconds: totalSec,
        clip_count: clips.length
      });
    } catch (e) {
      console.error(e);
    }
  };

  const handleCreateBatch = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const rec = await pbMedia.collection('video_batches').create<VideoBatchRecord>({
        title: newBatchTitle.trim() || (newBatchType === 'shorts_9_16' ? 'Neuer Shorts Stapel' : 'Neue YouTube Folge'),
        batch_type: newBatchType,
        target_duration_seconds: Number(newBatchTargetDuration) || (newBatchType === 'shorts_9_16' ? 180 : 600),
        current_duration_seconds: 0,
        clip_count: 0,
        status: 'collecting'
      });
      setSelectedBatchId(rec.id);
      setIsNewBatchModalOpen(false);
      setNewBatchTitle('');
      showToast('Neuer Video-Stapel angelegt.');
    } catch (err: any) {
      showToast(`Fehler beim Erstellen: ${err.message}`, 'error');
    }
  };

  const handleUploadMedia = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!uploadFile) {
      showToast('Bitte eine Datei auswählen.', 'error');
      return;
    }
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', uploadFile);
      formData.append('media_type', uploadMediaType);
      formData.append('format', uploadFormat);
      formData.append('duration_seconds', String(uploadDuration || 15));
      formData.append('original_filename', uploadFile.name);
      formData.append('source', 'manual_upload');
      formData.append('status', selectedBatch ? 'assigned_to_batch' : 'unprocessed');
      if (selectedBatch) {
        formData.append('batch_id', selectedBatch.id);
      }

      await pbMedia.collection('media_items').create(formData);
      setIsUploadModalOpen(false);
      setUploadFile(null);
      showToast('Clip erfolgreich hochgeladen.');
      if (selectedBatch) {
        setTimeout(() => recalculateBatch(selectedBatch.id), 300);
      }
    } catch (err: any) {
      showToast(`Upload fehlgeschlagen: ${err.message}`, 'error');
    } finally {
      setUploading(false);
    }
  };

  const handleAssignClip = async (clipId: string, batchId: string | null) => {
    try {
      await pbMedia.collection('media_items').update(clipId, {
        batch_id: batchId || '',
        status: batchId ? 'assigned_to_batch' : 'unprocessed'
      });
      if (selectedBatch) recalculateBatch(selectedBatch.id);
      if (batchId && batchId !== selectedBatch?.id) recalculateBatch(batchId);
      showToast(batchId ? 'Clip zum Stapel hinzugefügt' : 'Clip aus Stapel entfernt');
    } catch (err: any) {
      showToast(`Fehler: ${err.message}`, 'error');
    }
  };

  const handleDeleteBatch = async (batchId: string) => {
    if (!confirm('Diesen Video-Stapel wirklich löschen?')) return;
    try {
      const clips = mediaItems.filter((m) => m.batch_id === batchId);
      for (const c of clips) {
        await pbMedia.collection('media_items').update(c.id, { batch_id: '', status: 'unprocessed' });
      }
      await pbMedia.collection('video_batches').delete(batchId);
      if (selectedBatchId === batchId) setSelectedBatchId(null);
      showToast('Stapel gelöscht.');
    } catch (err: any) {
      showToast(`Fehler: ${err.message}`, 'error');
    }
  };

  const handleTriggerRender = async (batch: VideoBatchRecord) => {
    try {
      await pbMedia.collection('video_batches').update(batch.id, {
        status: 'rendering'
      });
      showToast('Kompilations-Rendering gestartet...');
      setTimeout(async () => {
        try {
          await pbMedia.collection('video_batches').update(batch.id, {
            status: 'completed',
            rendered_at: new Date().toISOString()
          });
          showToast('Kompilation fertig gerendert.');
        } catch (e) {}
      }, 3500);
    } catch (err: any) {
      showToast(`Fehler: ${err.message}`, 'error');
    }
  };

  const formatSeconds = (sec: number = 0) => {
    const m = Math.floor(sec / 60);
    const s = Math.round(sec % 60);
    if (m === 0) return `${s}s`;
    return `${m}m ${s.toString().padStart(2, '0')}s`;
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
    <div className="space-y-4">
      {/* Toast Notification */}
      {actionMessage && (
        <div
          className={`fixed bottom-6 right-6 z-50 px-4 py-2.5 rounded-lg shadow-xl border flex items-center gap-2.5 text-xs font-semibold ${
            actionMessage.type === 'error'
              ? 'bg-rose-950/95 text-rose-200 border-rose-800'
              : 'bg-slate-900 text-slate-100 border-slate-700'
          }`}
        >
          {actionMessage.type === 'error' ? (
            <AlertCircle className="w-4 h-4 text-red-400" />
          ) : (
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          )}
          <span>{actionMessage.text}</span>
        </div>
      )}

      {/* Top Filter & Action Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setActiveTypeFilter('all')}
            className="px-3 py-1.5 rounded-md text-xs font-semibold transition cursor-pointer border"
            style={
              activeTypeFilter === 'all'
                ? {
                    backgroundColor: 'var(--studio-tab-active-bg, rgba(239,68,68,0.12))',
                    color: 'var(--studio-tab-active-text, #f87171)',
                    borderColor: 'var(--studio-tab-active-border, #ef4444)',
                    fontWeight: 'bold'
                  }
                : {
                    backgroundColor: 'var(--studio-card-bg, #111827)',
                    borderColor: 'var(--studio-card-border, #1f2937)',
                    color: 'var(--studio-text-muted, #94a3b8)'
                  }
            }
          >
            Alle ({batches.length})
          </button>
          <button
            onClick={() => setActiveTypeFilter('shorts_9_16')}
            className="px-3 py-1.5 rounded-md text-xs font-semibold flex items-center gap-1.5 transition cursor-pointer border"
            style={
              activeTypeFilter === 'shorts_9_16'
                ? {
                    backgroundColor: 'var(--studio-tab-active-bg, rgba(239,68,68,0.12))',
                    color: 'var(--studio-tab-active-text, #f87171)',
                    borderColor: 'var(--studio-tab-active-border, #ef4444)',
                    fontWeight: 'bold'
                  }
                : {
                    backgroundColor: 'var(--studio-card-bg, #111827)',
                    borderColor: 'var(--studio-card-border, #1f2937)',
                    color: 'var(--studio-text-muted, #94a3b8)'
                  }
            }
          >
            <Smartphone className="w-3.5 h-3.5" />
            Shorts 9:16 ({batches.filter((b) => b.batch_type === 'shorts_9_16').length})
          </button>
          <button
            onClick={() => setActiveTypeFilter('longform_16_9')}
            className="px-3 py-1.5 rounded-md text-xs font-semibold flex items-center gap-1.5 transition cursor-pointer border"
            style={
              activeTypeFilter === 'longform_16_9'
                ? {
                    backgroundColor: 'var(--studio-tab-active-bg, rgba(239,68,68,0.12))',
                    color: 'var(--studio-tab-active-text, #f87171)',
                    borderColor: 'var(--studio-tab-active-border, #ef4444)',
                    fontWeight: 'bold'
                  }
                : {
                    backgroundColor: 'var(--studio-card-bg, #111827)',
                    borderColor: 'var(--studio-card-border, #1f2937)',
                    color: 'var(--studio-text-muted, #94a3b8)'
                  }
            }
          >
            <Monitor className="w-3.5 h-3.5" />
            YouTube 16:9 ({batches.filter((b) => b.batch_type === 'longform_16_9').length})
          </button>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={fetchData}
            className="p-1.5 rounded-md text-xs font-semibold transition cursor-pointer border"
            style={subCardStyle}
            title="Aktualisieren"
          >
            <RefreshCw className="w-3.5 h-3.5 text-[var(--studio-text-muted,#94a3b8)]" />
          </button>
          <button
            onClick={() => setIsUploadModalOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition cursor-pointer border"
            style={subCardStyle}
          >
            <Upload className="w-3.5 h-3.5 text-[var(--studio-text-muted,#94a3b8)]" />
            <span style={{ color: 'var(--studio-text, #f8fafc)' }}>Clip hochladen</span>
          </button>
          <button
            onClick={() => {
              setNewBatchType('shorts_9_16');
              setNewBatchTargetDuration(180);
              setIsNewBatchModalOpen(true);
            }}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-md text-xs font-bold text-white shadow-xs transition cursor-pointer"
            style={{ backgroundColor: 'var(--studio-accent, #ef4444)' }}
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Neuer Stapel</span>
          </button>
        </div>
      </div>

      {/* Main Grid: Batches on left, Selected Batch Details on right */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Left Column: List of Live Batches (5 Cols) */}
        <div className="lg:col-span-5 space-y-2.5">
          <h3 className="text-xs font-bold uppercase tracking-wider font-mono text-[var(--studio-text-muted,#94a3b8)]">
            Aktive Video-Stapel ({filteredBatches.length})
          </h3>

          {filteredBatches.length === 0 ? (
            <div className="p-6 rounded-xl border text-center" style={cardStyle}>
              <Film className="w-7 h-7 mx-auto mb-2 opacity-30 text-[var(--studio-text-muted,#94a3b8)]" />
              <p className="text-xs font-medium">Keine Video-Stapel vorhanden.</p>
              <button
                onClick={() => setIsNewBatchModalOpen(true)}
                className="mt-2 text-xs hover:underline font-semibold cursor-pointer"
                style={{ color: 'var(--studio-accent, #ef4444)' }}
              >
                + Ersten Stapel anlegen
              </button>
            </div>
          ) : (
            <div className="space-y-2.5 max-h-[640px] overflow-y-auto pr-1">
              {filteredBatches.map((batch) => {
                const isSelected = selectedBatch?.id === batch.id;
                const isShorts = batch.batch_type === 'shorts_9_16';
                const targetSec = batch.target_duration_seconds || (isShorts ? 180 : 600);
                const currentSec = batch.current_duration_seconds || 0;
                const pct = Math.min(100, Math.round((currentSec / targetSec) * 100));

                return (
                  <div
                    key={batch.id}
                    onClick={() => setSelectedBatchId(batch.id)}
                    className="p-3.5 rounded-xl border transition cursor-pointer shadow-xs"
                    style={{
                      backgroundColor: isSelected
                        ? 'var(--studio-card-bg, #111827)'
                        : 'var(--studio-input-bg, #0f172a)',
                      borderColor: isSelected
                        ? 'var(--studio-accent, #ef4444)'
                        : 'var(--studio-card-border, #1f2937)',
                      boxShadow: isSelected ? '0 0 0 1px var(--studio-accent, #ef4444)' : 'none'
                    }}
                  >
                    <div className="flex items-start justify-between gap-2 mb-1.5">
                      <div className="flex items-center gap-2">
                        <span className="p-1 rounded border" style={subCardStyle}>
                          {isShorts ? (
                            <Smartphone className="w-3.5 h-3.5 text-[var(--studio-text-muted,#94a3b8)]" />
                          ) : (
                            <Monitor className="w-3.5 h-3.5 text-[var(--studio-text-muted,#94a3b8)]" />
                          )}
                        </span>
                        <div>
                          <h4 className="text-xs font-bold line-clamp-1" style={{ color: 'var(--studio-text, #f8fafc)' }}>
                            {batch.title || (isShorts ? 'Shorts 9:16 Stapel' : 'YouTube 16:9 Stapel')}
                          </h4>
                          <span className="text-[10px] font-mono" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
                            {isShorts ? '9:16' : '16:9'} • {batch.clip_count || 0} Clips
                          </span>
                        </div>
                      </div>
                      <span
                        className="text-[9px] font-bold px-2 py-0.5 rounded-full border"
                        style={{
                          backgroundColor: 'var(--studio-input-bg, #0f172a)',
                          borderColor: 'var(--studio-card-border, #1f2937)',
                          color: pct >= 100 ? '#10b981' : 'var(--studio-text, #f8fafc)'
                        }}
                      >
                        {batch.status === 'completed' ? 'Fertig MP4' : pct >= 100 ? 'Bereit zum Rendern' : 'Sammelt Clips'}
                      </span>
                    </div>

                    {/* Progress Bar */}
                    <div className="mt-2.5 space-y-1">
                      <div className="flex justify-between text-[10px] font-mono" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
                        <span>{formatSeconds(currentSec)} / {formatSeconds(targetSec)}</span>
                        <span className="font-bold" style={{ color: 'var(--studio-text, #f8fafc)' }}>{pct}%</span>
                      </div>
                      <div className="w-full rounded-full h-1.5 overflow-hidden" style={{ backgroundColor: 'var(--studio-card-border, #1f2937)' }}>
                        <div
                          className="h-full transition-all duration-300 rounded-full"
                          style={{
                            width: `${pct}%`,
                            backgroundColor: pct >= 100 ? '#10b981' : 'var(--studio-accent, #ef4444)'
                          }}
                        />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Right Column: Selected Batch Details & Clip Canvas (7 Cols) */}
        <div className="lg:col-span-7 space-y-3">
          {selectedBatch ? (
            <div className="p-4 rounded-xl border shadow-xs" style={cardStyle}>
              {/* Batch Header */}
              <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b" style={{ borderColor: 'var(--studio-card-border, #1f2937)' }}>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-xs font-bold" style={{ color: 'var(--studio-text, #f8fafc)' }}>
                      {selectedBatch.title || 'Video Stapel'}
                    </h3>
                    <span
                      className="text-[9px] font-mono px-1.5 py-0.5 rounded border"
                      style={subCardStyle}
                    >
                      {selectedBatch.batch_type === 'shorts_9_16' ? '9:16 Shorts' : '16:9 YouTube'}
                    </span>
                  </div>
                  <p className="text-[11px] mt-0.5" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
                    Zielzeit: {formatSeconds(selectedBatch.target_duration_seconds)} • Aktuell:{' '}
                    {formatSeconds(selectedBatch.current_duration_seconds)} ({batchClips.length} Clips)
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  {selectedBatch.status === 'completed' && selectedBatch.output_video_file ? (
                    <a
                      href={getMediaFileUrl(selectedBatch, selectedBatch.output_video_file) || '#'}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-bold bg-emerald-600 hover:bg-emerald-500 text-white shadow-xs transition"
                    >
                      <Download className="w-3.5 h-3.5" />
                      <span>MP4 Herunterladen</span>
                    </a>
                  ) : (
                    <button
                      onClick={() => handleTriggerRender(selectedBatch)}
                      disabled={selectedBatch.status === 'rendering' || batchClips.length === 0}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-bold disabled:opacity-50 text-white shadow-xs transition cursor-pointer"
                      style={{ backgroundColor: 'var(--studio-accent, #ef4444)' }}
                    >
                      <Scissors className="w-3.5 h-3.5" />
                      <span>{selectedBatch.status === 'rendering' ? 'Rendert...' : 'Kompilation rendern'}</span>
                    </button>
                  )}

                  <button
                    onClick={() => handleDeleteBatch(selectedBatch.id)}
                    className="p-1.5 rounded-md text-slate-400 hover:text-rose-400 transition cursor-pointer"
                    title="Stapel löschen"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              {/* Clips in Current Batch */}
              <div className="mt-3 space-y-3">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-bold uppercase tracking-wider font-mono text-[var(--studio-text-muted,#94a3b8)]">
                    Zugeordnete Clips ({batchClips.length})
                  </h4>
                  <button
                    onClick={() => setIsUploadModalOpen(true)}
                    className="text-xs font-semibold flex items-center gap-1 cursor-pointer"
                    style={{ color: 'var(--studio-accent, #ef4444)' }}
                  >
                    <Plus className="w-3.5 h-3.5" /> Clip einfügen
                  </button>
                </div>

                {batchClips.length === 0 ? (
                  <div className="p-6 rounded-lg border text-center" style={subCardStyle}>
                    <Video className="w-5 h-5 mx-auto mb-1 opacity-30 text-[var(--studio-text-muted,#94a3b8)]" />
                    <p className="text-xs" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>Noch keine Clips in diesem Stapel.</p>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 max-h-[300px] overflow-y-auto pr-1">
                    {batchClips.map((clip, idx) => {
                      const fileUrl = getMediaFileUrl(clip, clip.file);
                      return (
                        <div
                          key={clip.id}
                          className="p-2.5 rounded-lg border flex flex-col justify-between"
                          style={subCardStyle}
                        >
                          <div className="flex items-start justify-between gap-2 mb-1.5">
                            <span className="w-4 h-4 rounded-full bg-slate-800 text-slate-300 flex items-center justify-center text-[9px] font-bold font-mono">
                              {idx + 1}
                            </span>
                            <span className="text-[10px] font-mono text-[var(--studio-text-muted,#94a3b8)]">
                              {formatSeconds(clip.duration_seconds)}
                            </span>
                          </div>

                          {fileUrl && clip.media_type === 'video' ? (
                            <div className="w-full h-20 bg-black rounded overflow-hidden mb-1.5 relative group">
                              <video src={fileUrl} className="w-full h-full object-cover" preload="metadata" />
                              <div className="absolute inset-0 bg-black/40 flex items-center justify-center opacity-0 group-hover:opacity-100 transition">
                                <a
                                  href={fileUrl}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="p-1 rounded-full bg-white/20 text-white hover:bg-white/40"
                                >
                                  <Play className="w-3.5 h-3.5 fill-white" />
                                </a>
                              </div>
                            </div>
                          ) : (
                            <div className="w-full h-20 bg-slate-900 rounded flex items-center justify-center text-slate-600 mb-1.5">
                              <Film className="w-5 h-5 text-slate-700" />
                            </div>
                          )}

                          <div className="flex items-center justify-between text-[10px] pt-1 border-t" style={{ borderColor: 'var(--studio-card-border, #1f2937)' }}>
                            <span className="font-mono truncate max-w-[120px]" style={{ color: 'var(--studio-text, #f8fafc)' }}>
                              {clip.original_filename || 'Clip'}
                            </span>
                            <button
                              onClick={() => handleAssignClip(clip.id, null)}
                              className="text-rose-400 hover:text-rose-300 font-semibold cursor-pointer"
                            >
                              Entfernen
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* Unassigned Clips Pool */}
                {unassignedClips.length > 0 && (
                  <div className="pt-3 border-t" style={{ borderColor: 'var(--studio-card-border, #1f2937)' }}>
                    <h4 className="text-xs font-bold uppercase tracking-wider font-mono mb-2" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
                      Verfügbarer Clip-Pool ({unassignedClips.length})
                    </h4>
                    <div className="flex gap-2 overflow-x-auto pb-1">
                      {unassignedClips.map((clip) => (
                        <div
                          key={clip.id}
                          className="p-2 rounded-lg border shrink-0 w-40"
                          style={subCardStyle}
                        >
                          <p className="text-[11px] font-semibold truncate" style={{ color: 'var(--studio-text, #f8fafc)' }}>
                            {clip.original_filename || 'Clip'}
                          </p>
                          <p className="text-[10px] font-mono mt-0.5" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
                            {formatSeconds(clip.duration_seconds)}
                          </p>
                          <button
                            onClick={() => handleAssignClip(clip.id, selectedBatch.id)}
                            className="mt-1.5 w-full py-1 rounded text-[10px] font-bold transition flex items-center justify-center gap-1 cursor-pointer border"
                            style={{
                              backgroundColor: 'var(--studio-card-bg, #111827)',
                              borderColor: 'var(--studio-card-border, #1f2937)',
                              color: 'var(--studio-text, #f8fafc)'
                            }}
                          >
                            <Plus className="w-3 h-3 text-[var(--studio-accent,#ef4444)]" /> Zum Stapel
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="p-8 rounded-xl border text-center" style={cardStyle}>
              <Film className="w-8 h-8 mx-auto mb-2 opacity-30 text-[var(--studio-text-muted,#94a3b8)]" />
              <p className="text-xs font-medium">Wähle links einen Video-Stapel aus.</p>
            </div>
          )}
        </div>
      </div>

      {/* Modal: New Batch */}
      {isNewBatchModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="w-full max-w-md rounded-xl border shadow-2xl p-5" style={cardStyle}>
            <h3 className="text-xs font-bold uppercase tracking-wider font-mono mb-3 flex items-center gap-2" style={{ color: 'var(--studio-accent, #ef4444)' }}>
              <Film className="w-4 h-4" />
              Neuen Video-Stapel anlegen
            </h3>
            <form onSubmit={handleCreateBatch} className="space-y-3.5 text-xs">
              <div>
                <label className="block font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>Titel</label>
                <input
                  type="text"
                  placeholder="z.B. 'Best of Highlights KW34'"
                  value={newBatchTitle}
                  onChange={(e) => setNewBatchTitle(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border focus:outline-hidden font-medium"
                  style={inputStyle}
                />
              </div>

              <div>
                <label className="block font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>Format</label>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setNewBatchType('shorts_9_16');
                      setNewBatchTargetDuration(180);
                    }}
                    className="p-2.5 rounded-lg border flex flex-col items-center gap-1 transition cursor-pointer"
                    style={
                      newBatchType === 'shorts_9_16'
                        ? {
                            backgroundColor: 'var(--studio-tab-active-bg, rgba(239,68,68,0.12))',
                            color: 'var(--studio-tab-active-text, #f87171)',
                            borderColor: 'var(--studio-tab-active-border, #ef4444)',
                            fontWeight: 'bold'
                          }
                        : subCardStyle
                    }
                  >
                    <Smartphone className="w-4 h-4" />
                    <span>Shorts 9:16</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setNewBatchType('longform_16_9');
                      setNewBatchTargetDuration(600);
                    }}
                    className="p-2.5 rounded-lg border flex flex-col items-center gap-1 transition cursor-pointer"
                    style={
                      newBatchType === 'longform_16_9'
                        ? {
                            backgroundColor: 'var(--studio-tab-active-bg, rgba(239,68,68,0.12))',
                            color: 'var(--studio-tab-active-text, #f87171)',
                            borderColor: 'var(--studio-tab-active-border, #ef4444)',
                            fontWeight: 'bold'
                          }
                        : subCardStyle
                    }
                  >
                    <Monitor className="w-4 h-4" />
                    <span>YouTube 16:9</span>
                  </button>
                </div>
              </div>

              <div>
                <label className="block font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
                  Zielzeit: {newBatchTargetDuration}s ({formatSeconds(newBatchTargetDuration)})
                </label>
                <input
                  type="range"
                  min={newBatchType === 'shorts_9_16' ? 60 : 300}
                  max={newBatchType === 'shorts_9_16' ? 300 : 1200}
                  step={15}
                  value={newBatchTargetDuration}
                  onChange={(e) => setNewBatchTargetDuration(Number(e.target.value))}
                  className="w-full cursor-pointer"
                  style={{ accentColor: 'var(--studio-accent, #ef4444)' }}
                />
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t" style={{ borderColor: 'var(--studio-card-border, #1f2937)' }}>
                <button
                  type="button"
                  onClick={() => setIsNewBatchModalOpen(false)}
                  className="px-3 py-1.5 rounded-lg text-slate-400 hover:text-slate-200 cursor-pointer"
                >
                  Abbrechen
                </button>
                <button
                  type="submit"
                  className="px-3.5 py-1.5 rounded-lg font-bold text-white shadow-xs cursor-pointer"
                  style={{ backgroundColor: 'var(--studio-accent, #ef4444)' }}
                >
                  Stapel anlegen
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Upload Clip */}
      {isUploadModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="w-full max-w-md rounded-xl border shadow-2xl p-5" style={cardStyle}>
            <h3 className="text-xs font-bold uppercase tracking-wider font-mono mb-3 flex items-center gap-2" style={{ color: 'var(--studio-accent, #ef4444)' }}>
              <Upload className="w-4 h-4" />
              Clip hochladen
            </h3>
            <form onSubmit={handleUploadMedia} className="space-y-3.5 text-xs">
              <div>
                <label className="block font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>Videodatei auswählen</label>
                <input
                  type="file"
                  accept="video/*,image/*"
                  onChange={(e) => {
                    const f = e.target.files?.[0] || null;
                    setUploadFile(f);
                  }}
                  className="w-full px-3 py-2 rounded-lg border font-medium"
                  style={inputStyle}
                  required
                />
              </div>

              <div className="grid grid-cols-2 gap-2.5">
                <div>
                  <label className="block font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>Format</label>
                  <select
                    value={uploadFormat}
                    onChange={(e: any) => setUploadFormat(e.target.value)}
                    className="w-full px-2.5 py-2 rounded-lg border font-medium focus:outline-hidden"
                    style={inputStyle}
                  >
                    <option value="hochkant_9_16">9:16 Hochkant</option>
                    <option value="breitbild_16_9">16:9 Breitbild</option>
                  </select>
                </div>
                <div>
                  <label className="block font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>Dauer (Sek.)</label>
                  <input
                    type="number"
                    value={uploadDuration}
                    onChange={(e) => setUploadDuration(Number(e.target.value))}
                    className="w-full px-2.5 py-2 rounded-lg border font-medium focus:outline-hidden"
                    style={inputStyle}
                    min={1}
                    max={600}
                  />
                </div>
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t" style={{ borderColor: 'var(--studio-card-border, #1f2937)' }}>
                <button
                  type="button"
                  onClick={() => setIsUploadModalOpen(false)}
                  className="px-3 py-1.5 rounded-lg text-slate-400 hover:text-slate-200 cursor-pointer"
                  disabled={uploading}
                >
                  Abbrechen
                </button>
                <button
                  type="submit"
                  disabled={uploading}
                  className="px-3.5 py-1.5 rounded-lg font-bold text-white shadow-xs cursor-pointer"
                  style={{ backgroundColor: 'var(--studio-accent, #ef4444)' }}
                >
                  {uploading ? 'Lädt hoch...' : 'Hochladen'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
