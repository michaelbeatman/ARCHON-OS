"use client";

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  MediaItemRecord, VideoBatchRecord, LinkedinContentRecord,
  getMediaFileUrl
} from '@/lib/pocketbaseMedia';
import {
  Film, Video, Image as ImageIcon, Sparkles, Sliders, Settings,
  Play, RefreshCw, Search, Layers, FileText, ExternalLink,
  LayoutGrid, List, Check, Cpu, AlertCircle, Download,
  Clock, Database, Eye, Info, Trash2, Tag, Plus, X, Filter,
  ArrowUpDown, ArrowUp, ArrowDown, CheckSquare, GripVertical
} from 'lucide-react';

interface Props {
  themeMode: 'light' | 'dark';
}

type TabType = 'pool' | 'batches' | 'linkedin' | 'settings';

export const PRESET_CATEGORIES = [
  { id: 'animals', label: '🐶 Lustiges Tier / Hund', color: 'bg-emerald-100 text-emerald-800 border-emerald-300' },
  { id: 'fail', label: '💥 Total-Fail / Panne', color: 'bg-rose-100 text-rose-800 border-rose-300' },
  { id: 'party', label: '🍻 Besoffen / Party', color: 'bg-amber-100 text-amber-800 border-amber-300' },
  { id: 'satire', label: '🎭 Satire & Memes', color: 'bg-purple-100 text-purple-800 border-purple-300' },
  { id: 'wtf', label: '😲 WTF / Kurioses', color: 'bg-pink-100 text-pink-800 border-pink-300' },
  { id: 'facts', label: '💡 Wissen & Lifehack', color: 'bg-cyan-100 text-cyan-800 border-cyan-300' },
];

function formatDate(dateStr?: string) {
  if (!dateStr) return '—';
  try {
    return new Date(dateStr).toLocaleDateString('de-DE', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  } catch {
    return dateStr;
  }
}

function formatDuration(sec?: number) {
  if (!sec) return '0s';
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  if (m > 0) return `${m}m ${s}s`;
  return `${sec}s`;
}

function formatBytes(bytes?: number) {
  if (!bytes) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
}

export function ContentStudioView({ themeMode }: Props) {
  const isLight = themeMode === 'light';

  const [activeTab, setActiveTab] = useState<TabType>('pool');
  const [mediaItems, setMediaItems] = useState<MediaItemRecord[]>([]);
  const [batches, setBatches] = useState<VideoBatchRecord[]>([]);
  const [linkedinItems, setLinkedinItems] = useState<LinkedinContentRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Search & Filters
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTypeFilter, setSelectedTypeFilter] = useState<'all' | 'video' | 'image'>('all');
  const [selectedCategoryFilter, setSelectedCategoryFilter] = useState<string>('all');
  const [viewMode, setViewMode] = useState<'table' | 'grid'>('table');

  // Sorting State (Default: Empfangsdatum descending - Neuestes ganz oben)
  const [sortField, setSortField] = useState<string>('received_at');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc');

  const handleSort = (field: string) => {
    if (sortField === field) {
      setSortDirection(prev => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDirection(
        field === 'received_at' || field === 'duration_seconds' || field === 'file_size_bytes' ? 'desc' : 'asc'
      );
    }
  };

  // Video Preview Modal & Tagging
  const [previewItem, setPreviewItem] = useState<MediaItemRecord | null>(null);
  const [editingItem, setEditingItem] = useState<MediaItemRecord | null>(null);
  const [customTagInput, setCustomTagInput] = useState('');
  const [isUpdatingTag, setIsUpdatingTag] = useState(false);

  // Delete Confirmation Modal
  const [deleteConfirmItem, setDeleteConfirmItem] = useState<MediaItemRecord | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  // Multi-Selection State & Bulk Actions
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkDeleteConfirmOpen, setBulkDeleteConfirmOpen] = useState(false);
  const [isBulkDeleting, setIsBulkDeleting] = useState(false);
  const [showOnlySelected, setShowOnlySelected] = useState(false);

  // Settings State
  const [settings, setSettings] = useState({
    shortsTarget: 180,
    longformTarget: 660,
    resolution: '1080p',
    audioNormalize: true,
    aiProvider: 'openrouter',
    aiModel: 'google/gemini-2.5-flash',
    linkedinPrompt: 'Erstelle aus den folgenden Notizen einen hochkarätigen deutschsprachigen LinkedIn-Post mit starker Hook, 3-4 prägnanten Absätzen, Mehrwert und 3 relevanten Hashtags.',
  });
  const [settingsSaved, setSettingsSaved] = useState(false);

  // Batch Reordering State & Drag & Drop
  const [shortsOrder, setShortsOrder] = useState<string[]>([]);
  const [youtubeOrder, setYoutubeOrder] = useState<string[]>([]);
  const [draggedShortsIdx, setDraggedShortsIdx] = useState<number | null>(null);
  const [draggedYoutubeIdx, setDraggedYoutubeIdx] = useState<number | null>(null);

  // Robust Data Fetching
  const loadAllData = useCallback(async () => {
    setLoading(true);
    setErrorMsg(null);

    const endpoints = [
      '/api/media/collections/media_items/records?perPage=100&sort=-received_at',
      '/api/media/collections/media_items/records?perPage=100',
      'http://localhost:8092/api/collections/media_items/records?perPage=100&sort=-received_at'
    ];

    let loaded = false;

    for (const ep of endpoints) {
      try {
        const res = await fetch(ep, { cache: 'no-store' });
        if (res.ok) {
          const data = await res.json();
          if (data && Array.isArray(data.items)) {
            setMediaItems(data.items);
            loaded = true;
            break;
          }
        }
      } catch (e) {
        // try next
      }
    }

    if (!loaded) {
      setErrorMsg('Verbindung zu Media-PocketBase wird aufgebaut...');
    }

    // Batches & LinkedIn content
    try {
      const [batchesRes, linkedinRes] = await Promise.all([
        fetch('/api/media/collections/video_batches/records?perPage=50&sort=-created', { cache: 'no-store' }).catch(() => null),
        fetch('/api/media/collections/linkedin_content/records?perPage=50&sort=-created', { cache: 'no-store' }).catch(() => null),
      ]);

      if (batchesRes && batchesRes.ok) {
        const bData = await batchesRes.json();
        setBatches(bData.items || []);
      }
      if (linkedinRes && linkedinRes.ok) {
        const lData = await linkedinRes.json();
        setLinkedinItems(lData.items || []);
      }
    } catch (err) {
      console.warn('Notice:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAllData();
    const interval = setInterval(loadAllData, 8000);
    return () => clearInterval(interval);
  }, [loadAllData]);

  // Ordered clips for Batches
  const shortsClips = useMemo(() => {
    const base = mediaItems.filter(m => m.media_type === 'video' && m.format === 'hochkant_9_16' && m.status === 'unprocessed');
    if (shortsOrder.length === 0) return base;
    return [...base].sort((a, b) => {
      const idxA = shortsOrder.indexOf(a.id);
      const idxB = shortsOrder.indexOf(b.id);
      if (idxA === -1 && idxB === -1) return 0;
      if (idxA === -1) return 1;
      if (idxB === -1) return -1;
      return idxA - idxB;
    });
  }, [mediaItems, shortsOrder]);

  const youtubeClips = useMemo(() => {
    const base = mediaItems.filter(m => m.media_type === 'video' && m.format !== 'hochkant_9_16' && m.status === 'unprocessed');
    if (youtubeOrder.length === 0) return base;
    return [...base].sort((a, b) => {
      const idxA = youtubeOrder.indexOf(a.id);
      const idxB = youtubeOrder.indexOf(b.id);
      if (idxA === -1 && idxB === -1) return 0;
      if (idxA === -1) return 1;
      if (idxB === -1) return -1;
      return idxA - idxB;
    });
  }, [mediaItems, youtubeOrder]);

  // Statistics
  const stats = useMemo(() => {
    const totalClips = mediaItems.filter(m => m.media_type === 'video').length;
    const totalImages = mediaItems.filter(m => m.media_type === 'image').length;
    const unprocessedVideos = mediaItems.filter(m => m.media_type === 'video' && m.status === 'unprocessed');
    
    const shortsSeconds = shortsClips.reduce((acc, c) => acc + (c.duration_seconds || 0), 0);
    const longformSeconds = youtubeClips.reduce((acc, c) => acc + (c.duration_seconds || 0), 0);

    return {
      totalClips,
      totalImages,
      unprocessedCount: unprocessedVideos.length,
      shortsClipsCount: shortsClips.length,
      shortsSeconds: Math.round(shortsSeconds * 10) / 10,
      longformClipsCount: youtubeClips.length,
      longformSeconds: Math.round(longformSeconds * 10) / 10,
    };
  }, [mediaItems, shortsClips, youtubeClips]);

  // Tagging & Categorization update
  const handleUpdateItemTags = async (item: MediaItemRecord, newCategory?: string, newTags?: string[]) => {
    setIsUpdatingTag(true);
    const existingMeta = item.metadata_json || {};
    const updatedMeta = {
      ...existingMeta,
      category: newCategory !== undefined ? newCategory : existingMeta.category,
      tags: newTags !== undefined ? newTags : existingMeta.tags || [],
    };

    try {
      const res = await fetch(`/api/media/collections/media_items/records/${item.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ metadata_json: updatedMeta })
      });

      if (res.ok) {
        const updatedItem = { ...item, metadata_json: updatedMeta };
        setMediaItems(prev => prev.map(m => m.id === item.id ? updatedItem : m));
        if (previewItem?.id === item.id) setPreviewItem(updatedItem);
        if (editingItem?.id === item.id) setEditingItem(updatedItem);
      }
    } catch (err) {
      console.error('Error updating tags:', err);
    } finally {
      setIsUpdatingTag(false);
    }
  };

  // Delete Item Action
  const handleDeleteItem = async (item: MediaItemRecord) => {
    setIsDeleting(true);
    try {
      const res = await fetch(`/api/media/collections/media_items/records/${item.id}`, {
        method: 'DELETE'
      });

      if (res.ok || res.status === 204 || res.status === 200) {
        setMediaItems(prev => prev.filter(m => m.id !== item.id));
        if (previewItem?.id === item.id) setPreviewItem(null);
        if (editingItem?.id === item.id) setEditingItem(null);
        setDeleteConfirmItem(null);
      } else {
        alert('Löschen fehlgeschlagen. Bitte versuche es erneut.');
      }
    } catch (err) {
      console.error('Error deleting media item:', err);
      alert('Netzwerkfehler beim Löschen.');
    } finally {
      setIsDeleting(false);
    }
  };

  // Multi-Selection Actions
  const toggleSelectOne = (id: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === filteredAndSortedMedia.length && filteredAndSortedMedia.length > 0) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredAndSortedMedia.map(m => m.id)));
    }
  };

  const clearSelection = () => {
    setSelectedIds(new Set());
    setShowOnlySelected(false);
  };

  // Bulk Delete Handler
  const handleBulkDelete = async () => {
    if (selectedIds.size === 0) return;
    setIsBulkDeleting(true);
    const idsToDelete = Array.from(selectedIds);
    try {
      await Promise.all(
        idsToDelete.map(id =>
          fetch(`/api/media/collections/media_items/records/${id}`, { method: 'DELETE' }).catch(() => null)
        )
      );
      setMediaItems(prev => prev.filter(m => !selectedIds.has(m.id)));
      if (previewItem && selectedIds.has(previewItem.id)) setPreviewItem(null);
      if (editingItem && selectedIds.has(editingItem.id)) setEditingItem(null);
      setSelectedIds(new Set());
      setBulkDeleteConfirmOpen(false);
    } catch (err) {
      console.error('Error during bulk delete:', err);
      alert('Fehler beim Löschen einiger Elemente.');
    } finally {
      setIsBulkDeleting(false);
    }
  };

  // Bulk Update Category Handler
  const handleBulkUpdateCategory = async (category: string) => {
    if (selectedIds.size === 0) return;
    const idsToUpdate = Array.from(selectedIds);
    try {
      await Promise.all(
        idsToUpdate.map(async id => {
          const item = mediaItems.find(m => m.id === id);
          if (!item) return;
          const meta = { ...(item.metadata_json || {}), category };
          await fetch(`/api/media/collections/media_items/records/${id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ metadata_json: meta })
          }).catch(() => null);
        })
      );
      setMediaItems(prev =>
        prev.map(m => (selectedIds.has(m.id) ? { ...m, metadata_json: { ...(m.metadata_json || {}), category } } : m))
      );
    } catch (err) {
      console.error('Error in bulk categorization:', err);
    }
  };

  // Filtered & Sorted Media Items (Default: Neuestes oben)
  const filteredAndSortedMedia = useMemo(() => {
    const list = mediaItems.filter(item => {
      if (showOnlySelected && !selectedIds.has(item.id)) return false;
      if (selectedTypeFilter !== 'all' && item.media_type !== selectedTypeFilter) return false;
      
      const meta = item.metadata_json || {};
      if (selectedCategoryFilter !== 'all') {
        if (selectedCategoryFilter === 'uncategorized') {
          if (meta.category) return false;
        } else {
          if (meta.category !== selectedCategoryFilter && !(meta.tags || []).includes(selectedCategoryFilter)) {
            return false;
          }
        }
      }

      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const name = (item.original_filename || item.file || item.id || '').toLowerCase();
        const cat = (meta.category || '').toLowerCase();
        const tags = (meta.tags || []).join(' ').toLowerCase();
        return name.includes(q) || cat.includes(q) || tags.includes(q);
      }
      return true;
    });

    return list.sort((a, b) => {
      let valA: any = 0;
      let valB: any = 0;

      if (sortField === 'received_at') {
        valA = new Date(a.received_at || a.created || 0).getTime();
        valB = new Date(b.received_at || b.created || 0).getTime();
      } else if (sortField === 'duration_seconds') {
        valA = a.duration_seconds || 0;
        valB = b.duration_seconds || 0;
      } else if (sortField === 'file_size_bytes') {
        valA = a.file_size_bytes || 0;
        valB = b.file_size_bytes || 0;
      } else if (sortField === 'category') {
        valA = (a.metadata_json?.category || '').toLowerCase();
        valB = (b.metadata_json?.category || '').toLowerCase();
      } else if (sortField === 'original_filename') {
        valA = (a.original_filename || a.file || '').toLowerCase();
        valB = (b.original_filename || b.file || '').toLowerCase();
      } else if (sortField === 'media_type') {
        valA = (a.media_type || '').toLowerCase();
        valB = (b.media_type || '').toLowerCase();
      } else if (sortField === 'format') {
        valA = (a.format || '').toLowerCase();
        valB = (b.format || '').toLowerCase();
      } else if (sortField === 'status') {
        valA = (a.status || '').toLowerCase();
        valB = (b.status || '').toLowerCase();
      } else {
        valA = ((a as any)[sortField] || '').toString().toLowerCase();
        valB = ((b as any)[sortField] || '').toString().toLowerCase();
      }

      if (valA < valB) return sortDirection === 'asc' ? -1 : 1;
      if (valA > valB) return sortDirection === 'asc' ? 1 : -1;
      return 0;
    });
  }, [mediaItems, selectedTypeFilter, selectedCategoryFilter, searchQuery, sortField, sortDirection]);

  const formatDuration = (seconds?: number) => {
    if (!seconds) return '—';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m > 0 ? `${m}m ` : ''}${s}s (${seconds}s)`;
  };

  const formatBytes = (bytes?: number) => {
    if (!bytes) return '—';
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const getCategoryBadge = (categoryKey?: string) => {
    if (!categoryKey) return null;
    const cat = PRESET_CATEGORIES.find(c => c.id === categoryKey);
    if (cat) {
      return (
        <span className={`px-2 py-0.5 rounded-md text-[10px] font-bold border ${cat.color}`}>
          {cat.label}
        </span>
      );
    }
    return (
      <span className="px-2 py-0.5 rounded-md text-[10px] font-bold bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 border border-zinc-300 dark:border-zinc-700">
        🏷️ {categoryKey}
      </span>
    );
  };

  const renderSortHeader = (label: string, field: string, align: 'left' | 'center' | 'right' = 'left', className = '') => {
    const isSorted = sortField === field;
    return (
      <th
        onClick={() => handleSort(field)}
        className={`p-3 select-none cursor-pointer transition group hover:text-accent-main ${
          isSorted ? 'text-accent-main font-black' : isLight ? 'text-zinc-700' : 'text-zinc-300'
        } ${align === 'center' ? 'text-center' : align === 'right' ? 'text-right' : 'text-left'} ${className}`}
        title={`Sortieren nach ${label} (${isSorted && sortDirection === 'asc' ? 'Absteigend' : 'Aufsteigend'})`}
      >
        <div className={`flex items-center gap-1.5 ${align === 'center' ? 'justify-center' : align === 'right' ? 'justify-end' : 'justify-start'}`}>
          <span>{label}</span>
          <span className={`text-[10px] transition ${isSorted ? 'opacity-100 font-bold' : 'opacity-30 group-hover:opacity-80'}`}>
            {isSorted ? (sortDirection === 'asc' ? '▲' : '▼') : '↕'}
          </span>
        </div>
      </th>
    );
  };

  const saveSettings = () => {
    setSettingsSaved(true);
    setTimeout(() => setSettingsSaved(false), 2000);
  };

  return (
    <div className="h-full flex flex-col min-h-0 gap-3">
      
      {/* ── KOPFZEILE: TITEL + REITER-TABS + REFRESH ── */}
      <div className="flex flex-wrap items-center justify-between gap-3 shrink-0 pb-2 border-b border-zinc-200 dark:border-zinc-800">
        <div className="flex items-center gap-2.5">
          <Film className="w-5 h-5 text-accent-main" />
          <h3 className="font-black text-lg tracking-tight font-mono">Content Studio</h3>
          <span className={`text-[11px] font-mono px-2 py-0.5 rounded-full font-bold ${
            isLight ? 'bg-zinc-200 text-zinc-700' : 'bg-zinc-800 text-zinc-300'
          }`}>
            {mediaItems.length} Rohdateien
          </span>
        </div>

        {/* ── REITER TABS IN HEADER ── */}
        <div className="flex items-center gap-1 overflow-x-auto">
          <button
            onClick={() => setActiveTab('pool')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition cursor-pointer ${
              activeTab === 'pool'
                ? 'bg-accent-soft text-accent-main font-bold border border-accent-soft shadow-xs'
                : isLight ? 'text-zinc-600 hover:bg-zinc-100' : 'text-zinc-400 hover:bg-zinc-800'
            }`}
          >
            <Layers className="w-3.5 h-3.5" />
            <span>Medien-Auffangpool</span>
            <span className="text-[10px] font-bold">({mediaItems.length})</span>
          </button>

          <button
            onClick={() => setActiveTab('batches')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition cursor-pointer ${
              activeTab === 'batches'
                ? 'bg-accent-soft text-accent-main font-bold border border-accent-soft shadow-xs'
                : isLight ? 'text-zinc-600 hover:bg-zinc-100' : 'text-zinc-400 hover:bg-zinc-800'
            }`}
          >
            <Video className="w-3.5 h-3.5" />
            <span>Video-Kompilationen & Schnitt</span>
          </button>

          <button
            onClick={() => setActiveTab('linkedin')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition cursor-pointer ${
              activeTab === 'linkedin'
                ? 'bg-accent-soft text-accent-main font-bold border border-accent-soft shadow-xs'
                : isLight ? 'text-zinc-600 hover:bg-zinc-100' : 'text-zinc-400 hover:bg-zinc-800'
            }`}
          >
            <FileText className="w-3.5 h-3.5" />
            <span>LinkedIn Studio</span>
            <span className="text-[10px] font-bold">({linkedinItems.length})</span>
          </button>

          <button
            onClick={() => setActiveTab('settings')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition cursor-pointer ${
              activeTab === 'settings'
                ? 'bg-accent-soft text-accent-main font-bold border border-accent-soft shadow-xs'
                : isLight ? 'text-zinc-600 hover:bg-zinc-100' : 'text-zinc-400 hover:bg-zinc-800'
            }`}
          >
            <Settings className="w-3.5 h-3.5" />
            <span>Einstellungen, KI & Status</span>
          </button>

          <button
            onClick={loadAllData}
            title="Neu laden"
            className={`p-2 rounded-lg border transition cursor-pointer ml-1 ${
              isLight ? 'bg-white border-zinc-200 text-zinc-700 hover:bg-zinc-100' : 'bg-zinc-900 border-zinc-800 text-zinc-300 hover:bg-zinc-800'
            }`}
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-accent-main' : ''}`} />
          </button>
        </div>
      </div>

      {/* ── TAB 1: MEDIEN-AUFFANGPOOL (ALLE ROHDATEIEN) ── */}
      {activeTab === 'pool' && (
        <div className="flex-1 flex flex-col min-h-0 gap-3">
          
          {/* Sub-Toolbar: Suche + Typen + View-Toggle */}
          <div className="flex flex-wrap items-center justify-between gap-3 shrink-0">
            <div className="flex items-center gap-2 flex-1 max-w-md">
              <div className={`flex items-center gap-2 px-3 py-1.5 rounded-xl border w-full ${
                isLight ? 'bg-white border-zinc-200' : 'bg-zinc-900 border-zinc-800'
              }`}>
                <Search className="w-3.5 h-3.5 text-zinc-400 shrink-0" />
                <input
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Dateiname, Kategorie oder Tag suchen..."
                  className="bg-transparent text-xs font-semibold focus:outline-none w-full placeholder:text-zinc-400"
                />
              </div>
            </div>

            <div className="flex items-center gap-2">
              {/* Type Filter Pills */}
              <div className={`flex items-center rounded-lg border p-0.5 text-xs font-semibold ${
                isLight ? 'bg-zinc-100 border-zinc-200' : 'bg-zinc-950 border-zinc-800'
              }`}>
                <button
                  onClick={() => setSelectedTypeFilter('all')}
                  className={`px-2.5 py-1 rounded-md transition cursor-pointer ${
                    selectedTypeFilter === 'all'
                      ? isLight ? 'bg-white text-zinc-900 shadow-xs border border-zinc-200 font-bold' : 'bg-zinc-800 text-zinc-100 font-bold'
                      : isLight ? 'text-zinc-600 hover:text-zinc-900' : 'text-zinc-400 hover:text-zinc-200'
                  }`}
                >
                  Alle ({mediaItems.length})
                </button>
                <button
                  onClick={() => setSelectedTypeFilter('video')}
                  className={`px-2.5 py-1 rounded-md transition cursor-pointer ${
                    selectedTypeFilter === 'video'
                      ? isLight ? 'bg-white text-accent-main shadow-xs border border-zinc-200 font-bold' : 'bg-zinc-800 text-accent-main font-bold'
                      : isLight ? 'text-zinc-600 hover:text-zinc-900' : 'text-zinc-400 hover:text-zinc-200'
                  }`}
                >
                  Videos ({stats.totalClips})
                </button>
                <button
                  onClick={() => setSelectedTypeFilter('image')}
                  className={`px-2.5 py-1 rounded-md transition cursor-pointer ${
                    selectedTypeFilter === 'image'
                      ? isLight ? 'bg-white text-accent-main shadow-xs border border-zinc-200 font-bold' : 'bg-zinc-800 text-accent-main font-bold'
                      : isLight ? 'text-zinc-600 hover:text-zinc-900' : 'text-zinc-400 hover:text-zinc-200'
                  }`}
                >
                  Bilder ({stats.totalImages})
                </button>
              </div>

              {/* View Mode Toggle */}
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setViewMode('table')}
                  className={`p-1.5 rounded-lg border transition cursor-pointer ${
                    viewMode === 'table'
                      ? isLight ? 'bg-white border-zinc-300 text-accent-main shadow-xs' : 'bg-zinc-800 border-zinc-700 text-accent-main'
                      : isLight ? 'border-transparent text-zinc-400' : 'border-transparent text-zinc-500'
                  }`}
                  title="Tabellenansicht"
                >
                  <List className="w-4 h-4" />
                </button>
                <button
                  onClick={() => setViewMode('grid')}
                  className={`p-1.5 rounded-lg border transition cursor-pointer ${
                    viewMode === 'grid'
                      ? isLight ? 'bg-white border-zinc-300 text-accent-main shadow-xs' : 'bg-zinc-800 border-zinc-700 text-accent-main'
                      : isLight ? 'border-transparent text-zinc-400' : 'border-transparent text-zinc-500'
                  }`}
                  title="Kachelansicht"
                >
                  <LayoutGrid className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>

          {/* ── KATEGORIE-FILTER BAR (KURATIERUNG) ── */}
          <div className="flex items-center gap-1.5 overflow-x-auto pb-1 text-xs">
            <span className="text-[11px] font-bold text-zinc-400 uppercase flex items-center gap-1 shrink-0 mr-1">
              <Filter className="w-3 h-3" /> Kuratieren:
            </span>
            <button
              onClick={() => setSelectedCategoryFilter('all')}
              className={`px-2.5 py-1 rounded-lg border transition cursor-pointer shrink-0 font-medium ${
                selectedCategoryFilter === 'all'
                  ? 'bg-accent-soft text-accent-main font-bold border-accent-soft'
                  : isLight ? 'bg-white border-zinc-200 text-zinc-600 hover:bg-zinc-50' : 'bg-zinc-900 border-zinc-800 text-zinc-400 hover:bg-zinc-800'
              }`}
            >
              Alle Themen ({mediaItems.length})
            </button>
            {PRESET_CATEGORIES.map(cat => {
              const count = mediaItems.filter(m => (m.metadata_json?.category === cat.id) || (m.metadata_json?.tags || []).includes(cat.id)).length;
              return (
                <button
                  key={cat.id}
                  onClick={() => setSelectedCategoryFilter(cat.id)}
                  className={`px-2.5 py-1 rounded-lg border transition cursor-pointer shrink-0 flex items-center gap-1 ${
                    selectedCategoryFilter === cat.id
                      ? 'bg-accent-soft text-accent-main font-bold border-accent-soft'
                      : isLight ? 'bg-white border-zinc-200 text-zinc-700 hover:bg-zinc-50' : 'bg-zinc-900 border-zinc-800 text-zinc-300 hover:bg-zinc-800'
                  }`}
                >
                  <span>{cat.label}</span>
                  <span className="text-[10px] opacity-70">({count})</span>
                </button>
              );
            })}
            <button
              onClick={() => setSelectedCategoryFilter('uncategorized')}
              className={`px-2.5 py-1 rounded-lg border transition cursor-pointer shrink-0 font-medium ${
                selectedCategoryFilter === 'uncategorized'
                  ? 'bg-accent-soft text-accent-main font-bold border-accent-soft'
                  : isLight ? 'bg-white border-zinc-200 text-zinc-500 hover:bg-zinc-50' : 'bg-zinc-900 border-zinc-800 text-zinc-400 hover:bg-zinc-800'
              }`}
            >
              ⏳ Noch ohne Tag ({mediaItems.filter(m => !m.metadata_json?.category).length})
            </button>
          </div>

          {/* ── BULK ACTIONS TOOLBAR ── */}
          {selectedIds.size > 0 && (
            <div className={`p-3 rounded-xl border flex flex-wrap items-center justify-between gap-3 animate-in fade-in slide-in-from-top-2 duration-150 ${
              isLight ? 'bg-accent-soft/30 border-accent-soft text-zinc-900' : 'bg-accent-soft/10 border-accent-soft/30 text-zinc-100'
            }`}>
              <div className="flex items-center gap-3">
                <span className="font-mono font-bold text-xs flex items-center gap-1.5 text-accent-main">
                  <CheckSquare className="w-4 h-4" />
                  {selectedIds.size} {selectedIds.size === 1 ? 'Datei' : 'Dateien'} ausgewählt
                </span>

                <button
                  onClick={() => setShowOnlySelected(prev => !prev)}
                  className={`px-2.5 py-1 rounded-lg border font-mono text-[11px] font-semibold transition cursor-pointer flex items-center gap-1 ${
                    showOnlySelected
                      ? 'bg-accent-main text-white border-accent-main'
                      : isLight ? 'bg-white border-zinc-300 text-zinc-700 hover:bg-zinc-50' : 'bg-zinc-800 border-zinc-700 text-zinc-300 hover:bg-zinc-700'
                  }`}
                >
                  <Filter className="w-3 h-3" />
                  {showOnlySelected ? 'Alle wieder anzeigen' : `Nur Auswahl filtern (${selectedIds.size})`}
                </button>
              </div>

              <div className="flex items-center gap-2 flex-wrap">
                {/* Quick Category Dropdown for Selected */}
                <div className="flex items-center gap-1">
                  <span className="text-[11px] font-mono text-zinc-500">Kategorie zuweisen:</span>
                  <select
                    onChange={(e) => {
                      if (e.target.value) {
                        handleBulkUpdateCategory(e.target.value);
                        e.target.value = '';
                      }
                    }}
                    defaultValue=""
                    className={`px-2 py-1 rounded-lg border font-mono text-[11px] font-medium cursor-pointer focus:outline-none ${
                      isLight ? 'bg-white border-zinc-300 text-zinc-800' : 'bg-zinc-800 border-zinc-700 text-zinc-200'
                    }`}
                  >
                    <option value="" disabled>Auswählen...</option>
                    {PRESET_CATEGORIES.map(cat => (
                      <option key={cat.id} value={cat.id}>{cat.label}</option>
                    ))}
                  </select>
                </div>

                <button
                  onClick={() => setBulkDeleteConfirmOpen(true)}
                  className="px-3 py-1 rounded-lg bg-rose-600 hover:bg-rose-700 text-white font-mono text-xs font-bold flex items-center gap-1.5 cursor-pointer shadow-xs transition"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  Ausgewählte löschen ({selectedIds.size})
                </button>

                <button
                  onClick={clearSelection}
                  className={`px-2.5 py-1 rounded-lg border font-mono text-[11px] font-medium cursor-pointer transition ${
                    isLight ? 'border-zinc-300 text-zinc-600 hover:bg-zinc-100' : 'border-zinc-700 text-zinc-400 hover:bg-zinc-800'
                  }`}
                >
                  Auswahl aufheben
                </button>
              </div>
            </div>
          )}

          {/* Table / Grid Box */}
          <div className={`flex-1 overflow-auto rounded-xl border ${
            isLight ? 'bg-white border-zinc-200 shadow-xs' : 'bg-zinc-900 border-zinc-800 shadow-md'
          }`}>
            {loading && mediaItems.length === 0 ? (
              <div className="p-12 flex flex-col items-center justify-center gap-3 text-zinc-400 font-mono text-xs">
                <RefreshCw className="w-6 h-6 animate-spin text-accent-main" />
                <span>Lade Rohdateien aus dem Medien-Auffangpool...</span>
              </div>
            ) : filteredAndSortedMedia.length === 0 ? (
              <div className="p-12 text-center font-mono text-xs flex flex-col items-center gap-3">
                <Video className="w-10 h-10 text-accent-main opacity-50" />
                <span className={`font-bold text-sm ${isLight ? 'text-zinc-800' : 'text-zinc-200'}`}>
                  Keine Mediendateien im gewählten Filter gefunden.
                </span>
                <span className={`text-xs ${isLight ? 'text-zinc-500' : 'text-zinc-400'}`}>
                  Setze den Filter zurück oder sende Videos an @Beatman_bot auf Telegram.
                </span>
                <button
                  onClick={() => { setSelectedTypeFilter('all'); setSelectedCategoryFilter('all'); setSearchQuery(''); setShowOnlySelected(false); }}
                  className="mt-2 px-3.5 py-1.5 rounded-lg bg-accent-main text-white font-bold text-xs flex items-center gap-1.5 cursor-pointer hover:opacity-90 transition"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  Filter zurücksetzen
                </button>
              </div>
            ) : viewMode === 'table' ? (
              <table className="w-full text-left text-xs border-collapse font-mono">
                <thead className={`sticky top-0 z-10 uppercase text-[10px] font-bold border-b ${
                  isLight ? 'bg-zinc-100 border-zinc-200 text-zinc-700' : 'bg-zinc-950 border-zinc-800 text-zinc-300'
                }`}>
                  <tr>
                    <th className="p-3 w-10 text-center" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={filteredAndSortedMedia.length > 0 && selectedIds.size === filteredAndSortedMedia.length}
                        onChange={toggleSelectAll}
                        className="w-4 h-4 rounded border-zinc-300 dark:border-zinc-700 text-accent-main focus:ring-accent-main cursor-pointer"
                        title="Alle auswählen"
                      />
                    </th>
                    <th className="p-3 w-12 text-center">Vorschau</th>
                    {renderSortHeader('Dateiname & ID', 'original_filename')}
                    {renderSortHeader('Kategorie / Tag', 'category')}
                    {renderSortHeader('Typ', 'media_type')}
                    {renderSortHeader('Format', 'format')}
                    {renderSortHeader('Dauer', 'duration_seconds')}
                    {renderSortHeader('Größe', 'file_size_bytes')}
                    {renderSortHeader('Status', 'status')}
                    {renderSortHeader('Empfangsdatum', 'received_at')}
                    <th className="p-3 text-right">Aktionen</th>
                  </tr>
                </thead>
                <tbody className={`divide-y ${isLight ? 'divide-zinc-100 text-zinc-900' : 'divide-zinc-800/60 text-zinc-100'}`}>
                  {filteredAndSortedMedia.map((item) => {
                    const fileUrl = getMediaFileUrl(item);
                    const isVideo = item.media_type === 'video';
                    const meta = item.metadata_json || {};
                    const isSelected = selectedIds.has(item.id);

                    return (
                      <tr
                        key={item.id}
                        onClick={() => setPreviewItem(item)}
                        className={`cursor-pointer transition ${
                          isSelected
                            ? isLight ? 'bg-accent-soft/20 font-semibold' : 'bg-accent-soft/10 font-semibold'
                            : isLight ? 'hover:bg-zinc-50' : 'hover:bg-zinc-800/40'
                        }`}
                      >
                        <td className="p-2.5 w-10 text-center" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={(e) => toggleSelectOne(item.id, e as any)}
                            className="w-4 h-4 rounded border-zinc-300 dark:border-zinc-700 text-accent-main focus:ring-accent-main cursor-pointer"
                          />
                        </td>

                        <td className="p-2.5 text-center" onClick={(e) => e.stopPropagation()}>
                          <button
                            onClick={() => setPreviewItem(item)}
                            className="w-8 h-8 rounded-lg bg-accent-soft hover:bg-accent-light text-accent-main flex items-center justify-center transition shrink-0 mx-auto cursor-pointer"
                          >
                            {isVideo ? <Play className="w-3.5 h-3.5 fill-current" /> : <ImageIcon className="w-3.5 h-3.5" />}
                          </button>
                        </td>

                        <td className="p-3 font-bold truncate max-w-xs">
                          <div className="truncate">{item.original_filename || item.file || item.id}</div>
                          <div className={`text-[10px] font-normal ${isLight ? 'text-zinc-500' : 'text-zinc-400'}`}>{item.id}</div>
                        </td>

                        {/* Kategorie / Tag Spalte */}
                        <td className="p-3" onClick={(e) => e.stopPropagation()}>
                          <div className="flex items-center gap-1.5 flex-wrap">
                            {meta.category ? (
                              getCategoryBadge(meta.category)
                            ) : (
                              <button
                                onClick={() => setEditingItem(item)}
                                className={`px-2 py-0.5 rounded text-[10px] font-medium border border-dashed transition cursor-pointer flex items-center gap-1 ${
                                  isLight ? 'border-zinc-300 text-zinc-500 hover:border-accent-main hover:text-accent-main' : 'border-zinc-700 text-zinc-400 hover:border-accent-main hover:text-accent-main'
                                }`}
                              >
                                <Tag className="w-2.5 h-2.5" /> + Taggen
                              </button>
                            )}
                            {(meta.tags || []).map((t: string) => (
                              <span key={t} className="px-1.5 py-0.2 rounded text-[9px] font-bold bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300">
                                #{t}
                              </span>
                            ))}
                          </div>
                        </td>

                        <td className="p-3">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                            isVideo
                              ? isLight ? 'bg-blue-100 text-blue-800 border border-blue-200' : 'bg-blue-950/60 text-blue-200 border border-blue-800'
                              : isLight ? 'bg-purple-100 text-purple-800 border border-purple-200' : 'bg-purple-950/60 text-purple-200 border border-purple-800'
                          }`}>
                            {item.media_type}
                          </span>
                        </td>

                        <td className="p-3">
                          <span className={`text-[11px] font-semibold ${isLight ? 'text-zinc-700' : 'text-zinc-300'}`}>
                            {item.format === 'hochkant_9_16' ? '📱 9:16 Shorts' : item.format === 'breitbild_16_9' ? '🖥️ 16:9 YouTube' : item.format === 'quadratisch_1_1' ? '⏹️ 1:1 Quadrat' : item.format || '—'}
                          </span>
                        </td>

                        <td className="p-3 font-bold text-accent-main">
                          {formatDuration(item.duration_seconds)}
                        </td>

                        <td className={`p-3 ${isLight ? 'text-zinc-600' : 'text-zinc-400'}`}>
                          {formatBytes(item.file_size_bytes)}
                        </td>

                        <td className="p-3">
                          <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                            item.status === 'unprocessed'
                              ? isLight ? 'bg-amber-100 text-amber-800 border border-amber-300' : 'bg-amber-950/60 text-amber-200 border border-amber-700'
                              : isLight ? 'bg-emerald-100 text-emerald-800 border border-emerald-300' : 'bg-emerald-950/60 text-emerald-200 border border-emerald-700'
                          }`}>
                            {item.status === 'unprocessed' ? '⏳ Unbearbeitet' : '✓ Verarbeitet'}
                          </span>
                        </td>

                        <td className={`p-3 text-[11px] ${isLight ? 'text-zinc-600' : 'text-zinc-400'}`}>
                          {formatDate(item.received_at || item.created)}
                        </td>

                        <td className="p-3 text-right" onClick={(e) => e.stopPropagation()}>
                          <div className="flex items-center justify-end gap-1.5">
                            <button
                              onClick={() => setEditingItem(item)}
                              className={`p-1.5 rounded-lg border transition cursor-pointer ${
                                isLight ? 'border-zinc-200 text-zinc-600 hover:text-accent-main hover:border-accent-main' : 'border-zinc-700 text-zinc-400 hover:text-accent-main hover:border-accent-main'
                              }`}
                              title="Taggen & Kategorisieren"
                            >
                              <Tag className="w-3.5 h-3.5" />
                            </button>
                            <button
                              onClick={() => setPreviewItem(item)}
                              className={`p-1.5 rounded-lg border transition cursor-pointer ${
                                isLight ? 'border-zinc-200 text-zinc-600 hover:text-accent-main hover:border-accent-main' : 'border-zinc-700 text-zinc-400 hover:text-accent-main hover:border-accent-main'
                              }`}
                              title="Vorschau / Abspielen"
                            >
                              <Eye className="w-3.5 h-3.5" />
                            </button>
                            <button
                              onClick={() => setDeleteConfirmItem(item)}
                              className="p-1.5 rounded-lg border border-rose-200 dark:border-rose-900 text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-950/50 transition cursor-pointer"
                              title="Video aus Pool löschen"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <div className="p-4 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                {filteredAndSortedMedia.map((item) => {
                  const isVideo = item.media_type === 'video';
                  const meta = item.metadata_json || {};
                  const isSelected = selectedIds.has(item.id);

                  return (
                    <div
                      key={item.id}
                      onClick={() => setPreviewItem(item)}
                      className={`rounded-xl border p-3 flex flex-col gap-2 cursor-pointer transition relative group ${
                        isSelected
                          ? 'border-accent-main bg-accent-soft/10 ring-1 ring-accent-main'
                          : isLight ? 'bg-zinc-50 border-zinc-200 hover:border-accent-main' : 'bg-zinc-950 border-zinc-800 hover:border-accent-main'
                      }`}
                    >
                      <div className={`aspect-video rounded-lg flex items-center justify-center overflow-hidden relative ${
                        isLight ? 'bg-zinc-200' : 'bg-black/50'
                      }`}>
                        {/* Checkbox */}
                        <div className="absolute top-2 left-2 z-10" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={(e) => toggleSelectOne(item.id, e as any)}
                            className="w-4 h-4 rounded border-zinc-300 dark:border-zinc-700 text-accent-main focus:ring-accent-main cursor-pointer shadow-md"
                          />
                        </div>

                        {isVideo ? (
                          <div className="flex flex-col items-center gap-1 text-accent-main">
                            <Play className="w-7 h-7 group-hover:scale-110 transition" />
                            <span className="text-[10px] font-bold font-mono px-2 py-0.5 rounded bg-black/70 text-white">
                              {formatDuration(item.duration_seconds)}
                            </span>
                          </div>
                        ) : (
                          <ImageIcon className="w-7 h-7 text-purple-500" />
                        )}

                        {/* Top corner actions */}
                        <div className="absolute top-1.5 right-1.5 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition" onClick={(e) => e.stopPropagation()}>
                          <button
                            onClick={() => setEditingItem(item)}
                            className="p-1 rounded-md bg-black/70 text-white hover:bg-accent-main"
                            title="Taggen"
                          >
                            <Tag className="w-3 h-3" />
                          </button>
                          <button
                            onClick={() => setDeleteConfirmItem(item)}
                            className="p-1 rounded-md bg-black/70 text-rose-400 hover:bg-rose-600 hover:text-white"
                            title="Löschen"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </div>
                      </div>

                      <div className="flex flex-col gap-1">
                        <div className="flex items-center justify-between text-[11px] font-mono">
                          <span className={`font-bold truncate ${isLight ? 'text-zinc-800' : 'text-zinc-200'}`}>
                            {item.original_filename || item.file}
                          </span>
                          <span className={`px-1.5 py-0.2 rounded text-[9px] font-bold uppercase shrink-0 ${
                            item.status === 'unprocessed' ? 'bg-amber-100 text-amber-800' : 'bg-emerald-100 text-emerald-800'
                          }`}>
                            {item.status}
                          </span>
                        </div>

                        {/* Category badge */}
                        <div className="flex items-center gap-1 flex-wrap pt-0.5">
                          {meta.category ? (
                            getCategoryBadge(meta.category)
                          ) : (
                            <span className="text-[10px] text-zinc-400 italic">Keine Kategorie</span>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── TAB 2: VIDEO-KOMPILATIONEN (STAPEL) ── */}
      {activeTab === 'batches' && (
        <div className="flex-1 overflow-auto grid grid-cols-1 lg:grid-cols-2 gap-4">
          
          {/* Shorts Stapel (9:16) */}
          <div className={`p-5 rounded-xl border flex flex-col gap-4 ${
            isLight ? 'bg-white border-zinc-200 shadow-xs' : 'bg-zinc-900 border-zinc-800 shadow-md'
          }`}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-xl">📱</span>
                <div>
                  <h3 className={`font-bold text-sm font-mono ${isLight ? 'text-zinc-900' : 'text-zinc-100'}`}>
                    SHORTS STAPEL (9:16)
                  </h3>
                  <p className={`text-[11px] font-mono ${isLight ? 'text-zinc-600' : 'text-zinc-400'}`}>
                    Ziel: {settings.shortsTarget}s (~{Math.round(settings.shortsTarget / 60)} Min) für YouTube Shorts & TikTok
                  </p>
                </div>
              </div>
              <span className="text-xs font-mono font-bold px-2 py-1 rounded-lg bg-accent-soft text-accent-main">
                {stats.shortsClipsCount} Clips gesammelt
              </span>
            </div>

            {/* Progress bar */}
            <div>
              <div className="flex justify-between text-xs font-mono font-bold mb-1">
                <span>Fortschritt: {stats.shortsSeconds}s / {settings.shortsTarget}s</span>
                <span className={stats.shortsSeconds >= settings.shortsTarget ? 'text-emerald-500 font-bold' : ''}>
                  {Math.round((stats.shortsSeconds / settings.shortsTarget) * 100)}%
                </span>
              </div>
              <div className={`w-full h-3 rounded-full overflow-hidden ${isLight ? 'bg-zinc-100' : 'bg-zinc-800'}`}>
                <div
                  className="h-full rounded-full bg-accent-main transition-all duration-500"
                  style={{ width: `${Math.min(100, (stats.shortsSeconds / settings.shortsTarget) * 100)}%` }}
                />
              </div>
            </div>

            {/* Scrollable Clips List */}
            <div className={`p-3 rounded-xl border text-xs font-mono flex flex-col gap-1.5 ${
              isLight ? 'bg-zinc-50 border-zinc-200' : 'bg-zinc-950 border-zinc-800'
            }`}>
              <div className="flex items-center justify-between font-bold uppercase text-[10px] pb-1 border-b border-zinc-200 dark:border-zinc-800">
                <span className={isLight ? 'text-zinc-700' : 'text-zinc-400'}>Aktuelle Clips im Shorts-Puffer:</span>
                <span className="text-[9px] text-zinc-500 normal-case">Grip zum Umsortieren ziehen</span>
              </div>

              <div className="max-h-[340px] overflow-y-auto space-y-1 pr-1">
                {(() => {
                  if (shortsClips.length === 0) {
                    return (
                      <div className={`italic py-4 text-center text-xs ${isLight ? 'text-zinc-500' : 'text-zinc-400'}`}>
                        Noch keine 9:16 Hochkant-Videos empfangen.
                      </div>
                    );
                  }

                  let runningTotal = 0;
                  let thresholdReached = false;
                  const rows: React.ReactNode[] = [];

                  shortsClips.forEach((clip, index) => {
                    runningTotal += clip.duration_seconds || 0;
                    const isDragged = draggedShortsIdx === index;

                    rows.push(
                      <div
                        key={clip.id}
                        draggable
                        onDragStart={() => setDraggedShortsIdx(index)}
                        onDragOver={(e) => e.preventDefault()}
                        onDrop={(e) => {
                          e.preventDefault();
                          if (draggedShortsIdx === null || draggedShortsIdx === index) return;
                          const reordered = [...shortsClips];
                          const [moved] = reordered.splice(draggedShortsIdx, 1);
                          reordered.splice(index, 0, moved);
                          setShortsOrder(reordered.map(i => i.id));
                          setDraggedShortsIdx(null);
                        }}
                        className={`flex items-center justify-between py-1.5 px-2 rounded-lg border transition group select-none ${
                          isDragged
                            ? 'opacity-40 border-dashed border-accent-main'
                            : isLight
                            ? 'border-zinc-200/80 hover:bg-zinc-100/90 text-zinc-800'
                            : 'border-zinc-800/80 hover:bg-zinc-900 text-zinc-200'
                        }`}
                      >
                        {/* Left: Grip + Index + Play + Filename */}
                        <div className="flex items-center gap-1.5 min-w-0 flex-1">
                          <span
                            className="cursor-grab active:cursor-grabbing text-zinc-400 hover:text-accent-main p-0.5 shrink-0"
                            title="Gedrückt halten zum Umsortieren"
                          >
                            <GripVertical className="w-3.5 h-3.5" />
                          </span>
                          <span className="text-[11px] font-mono text-zinc-400 w-5 shrink-0 select-none">
                            {index + 1}.
                          </span>
                          <button
                            onClick={() => setPreviewItem(clip)}
                            className="p-1 rounded-md text-accent-main hover:bg-accent-soft hover:scale-110 transition cursor-pointer shrink-0"
                            title="Clip abspielen"
                          >
                            <Play className="w-3 h-3 fill-current" />
                          </button>
                          <span
                            onClick={() => setPreviewItem(clip)}
                            className="truncate text-xs font-mono font-medium hover:text-accent-main hover:underline cursor-pointer"
                            title={clip.original_filename || clip.file}
                          >
                            {clip.original_filename || clip.file}
                          </span>
                        </div>

                        {/* Right: Duration + Delete */}
                        <div className="flex items-center gap-2 shrink-0 ml-2">
                          <span className="font-bold text-accent-main text-xs font-mono">
                            {clip.duration_seconds ? `${clip.duration_seconds.toFixed(1)}s` : '0s'}
                          </span>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setDeleteConfirmItem(clip);
                            }}
                            className="p-1 rounded hover:bg-rose-500/20 text-zinc-400 hover:text-rose-500 transition cursor-pointer"
                            title="Clip löschen"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    );

                    // Threshold cut marker
                    if (!thresholdReached && runningTotal >= settings.shortsTarget) {
                      thresholdReached = true;
                      rows.push(
                        <div
                          key="shorts-threshold-marker"
                          className={`my-2.5 p-3 rounded-xl border flex flex-col gap-2 shadow-xs animate-in fade-in ${
                            isLight ? 'bg-emerald-50 border-emerald-300 text-emerald-950' : 'bg-emerald-950/30 border-emerald-500/40 text-emerald-200'
                          }`}
                        >
                          <div className="flex items-center justify-between text-xs font-mono font-bold">
                            <span className="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400">
                              <Check className="w-4 h-4" /> 100% Zielzeit erreicht ({runningTotal.toFixed(1)}s / {settings.shortsTarget}s)
                            </span>
                            <span className="text-[10px] bg-emerald-500/20 text-emerald-700 dark:text-emerald-300 px-2 py-0.5 rounded-md font-mono uppercase">
                              Batch 1 voll ({index + 1} Clips)
                            </span>
                          </div>
                          <button
                            className="w-full py-2.5 rounded-lg font-mono text-xs font-bold bg-accent-main hover:bg-accent-main-hover text-white transition shadow-xs flex items-center justify-center gap-2 cursor-pointer"
                          >
                            <Sparkles className="w-4 h-4" />
                            Shorts-Kompilation (Batch 1) jetzt manuell rendern
                          </button>
                          {index < shortsClips.length - 1 && (
                            <div className={`text-[10px] font-bold font-mono uppercase tracking-wider pt-1.5 border-t ${
                              isLight ? 'border-emerald-200 text-zinc-600' : 'border-emerald-800/40 text-zinc-400'
                            }`}>
                              Überhang / Folge-Puffer (Batch 2):
                            </div>
                          )}
                        </div>
                      );
                    }
                  });

                  return rows;
                })()}
              </div>
            </div>

            {/* Standalone Button if threshold not yet reached */}
            {stats.shortsSeconds < settings.shortsTarget && (
              <button
                className="w-full py-2.5 rounded-xl font-mono text-xs font-bold bg-accent-main hover:bg-accent-main-hover text-white transition shadow-xs flex items-center justify-center gap-2 cursor-pointer"
              >
                <Sparkles className="w-4 h-4" />
                Shorts-Kompilation jetzt manuell rendern
              </button>
            )}
          </div>

          {/* Long-form YouTube Stapel (16:9) */}
          <div className={`p-5 rounded-xl border flex flex-col gap-4 ${
            isLight ? 'bg-white border-zinc-200 shadow-xs' : 'bg-zinc-900 border-zinc-800 shadow-md'
          }`}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-xl">🖥️</span>
                <div>
                  <h3 className={`font-bold text-sm font-mono ${isLight ? 'text-zinc-900' : 'text-zinc-100'}`}>
                    YOUTUBE STAPEL (16:9)
                  </h3>
                  <p className={`text-[11px] font-mono ${isLight ? 'text-zinc-600' : 'text-zinc-400'}`}>
                    Ziel: {settings.longformTarget}s (~{Math.round(settings.longformTarget / 60)} Min) für Monetarisierung & Mid-Rolls
                  </p>
                </div>
              </div>
              <span className="text-xs font-mono font-bold px-2 py-1 rounded-lg bg-accent-soft text-accent-main">
                {stats.longformClipsCount} Clips gesammelt
              </span>
            </div>

            {/* Progress bar */}
            <div>
              <div className="flex justify-between text-xs font-mono font-bold mb-1">
                <span>Fortschritt: {stats.longformSeconds}s / {settings.longformTarget}s</span>
                <span className={stats.longformSeconds >= settings.longformTarget ? 'text-emerald-500 font-bold' : ''}>
                  {Math.round((stats.longformSeconds / settings.longformTarget) * 100)}%
                </span>
              </div>
              <div className={`w-full h-3 rounded-full overflow-hidden ${isLight ? 'bg-zinc-100' : 'bg-zinc-800'}`}>
                <div
                  className="h-full rounded-full bg-accent-main transition-all duration-500"
                  style={{ width: `${Math.min(100, (stats.longformSeconds / settings.longformTarget) * 100)}%` }}
                />
              </div>
            </div>

            {/* Scrollable Clips List */}
            <div className={`p-3 rounded-xl border text-xs font-mono flex flex-col gap-1.5 ${
              isLight ? 'bg-zinc-50 border-zinc-200' : 'bg-zinc-950 border-zinc-800'
            }`}>
              <div className="flex items-center justify-between font-bold uppercase text-[10px] pb-1 border-b border-zinc-200 dark:border-zinc-800">
                <span className={isLight ? 'text-zinc-700' : 'text-zinc-400'}>Aktuelle Clips im YouTube-Puffer:</span>
                <span className="text-[9px] text-zinc-500 normal-case">Grip zum Umsortieren ziehen</span>
              </div>

              <div className="max-h-[340px] overflow-y-auto space-y-1 pr-1">
                {(() => {
                  if (youtubeClips.length === 0) {
                    return (
                      <div className={`italic py-4 text-center text-xs ${isLight ? 'text-zinc-500' : 'text-zinc-400'}`}>
                        Noch keine 16:9 Breitbild-Videos empfangen.
                      </div>
                    );
                  }

                  let runningTotal = 0;
                  let thresholdReached = false;
                  const rows: React.ReactNode[] = [];

                  youtubeClips.forEach((clip, index) => {
                    runningTotal += clip.duration_seconds || 0;
                    const isDragged = draggedYoutubeIdx === index;

                    rows.push(
                      <div
                        key={clip.id}
                        draggable
                        onDragStart={() => setDraggedYoutubeIdx(index)}
                        onDragOver={(e) => e.preventDefault()}
                        onDrop={(e) => {
                          e.preventDefault();
                          if (draggedYoutubeIdx === null || draggedYoutubeIdx === index) return;
                          const reordered = [...youtubeClips];
                          const [moved] = reordered.splice(draggedYoutubeIdx, 1);
                          reordered.splice(index, 0, moved);
                          setYoutubeOrder(reordered.map(i => i.id));
                          setDraggedYoutubeIdx(null);
                        }}
                        className={`flex items-center justify-between py-1.5 px-2 rounded-lg border transition group select-none ${
                          isDragged
                            ? 'opacity-40 border-dashed border-accent-main'
                            : isLight
                            ? 'border-zinc-200/80 hover:bg-zinc-100/90 text-zinc-800'
                            : 'border-zinc-800/80 hover:bg-zinc-900 text-zinc-200'
                        }`}
                      >
                        {/* Left: Grip + Index + Play + Filename */}
                        <div className="flex items-center gap-1.5 min-w-0 flex-1">
                          <span
                            className="cursor-grab active:cursor-grabbing text-zinc-400 hover:text-accent-main p-0.5 shrink-0"
                            title="Gedrückt halten zum Umsortieren"
                          >
                            <GripVertical className="w-3.5 h-3.5" />
                          </span>
                          <span className="text-[11px] font-mono text-zinc-400 w-5 shrink-0 select-none">
                            {index + 1}.
                          </span>
                          <button
                            onClick={() => setPreviewItem(clip)}
                            className="p-1 rounded-md text-accent-main hover:bg-accent-soft hover:scale-110 transition cursor-pointer shrink-0"
                            title="Clip abspielen"
                          >
                            <Play className="w-3 h-3 fill-current" />
                          </button>
                          <span
                            onClick={() => setPreviewItem(clip)}
                            className="truncate text-xs font-mono font-medium hover:text-accent-main hover:underline cursor-pointer"
                            title={clip.original_filename || clip.file}
                          >
                            {clip.original_filename || clip.file}
                          </span>
                        </div>

                        {/* Right: Duration + Delete */}
                        <div className="flex items-center gap-2 shrink-0 ml-2">
                          <span className="font-bold text-accent-main text-xs font-mono">
                            {clip.duration_seconds ? `${clip.duration_seconds.toFixed(1)}s` : '0s'}
                          </span>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setDeleteConfirmItem(clip);
                            }}
                            className="p-1 rounded hover:bg-rose-500/20 text-zinc-400 hover:text-rose-500 transition cursor-pointer"
                            title="Clip löschen"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    );

                    // Threshold cut marker
                    if (!thresholdReached && runningTotal >= settings.longformTarget) {
                      thresholdReached = true;
                      rows.push(
                        <div
                          key="youtube-threshold-marker"
                          className={`my-2.5 p-3 rounded-xl border flex flex-col gap-2 shadow-xs animate-in fade-in ${
                            isLight ? 'bg-emerald-50 border-emerald-300 text-emerald-950' : 'bg-emerald-950/30 border-emerald-500/40 text-emerald-200'
                          }`}
                        >
                          <div className="flex items-center justify-between text-xs font-mono font-bold">
                            <span className="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400">
                              <Check className="w-4 h-4" /> 100% Zielzeit erreicht ({runningTotal.toFixed(1)}s / {settings.longformTarget}s)
                            </span>
                            <span className="text-[10px] bg-emerald-500/20 text-emerald-700 dark:text-emerald-300 px-2 py-0.5 rounded-md font-mono uppercase">
                              Batch 1 voll ({index + 1} Clips)
                            </span>
                          </div>
                          <button
                            className="w-full py-2.5 rounded-lg font-mono text-xs font-bold bg-accent-main hover:bg-accent-main-hover text-white transition shadow-xs flex items-center justify-center gap-2 cursor-pointer"
                          >
                            <Sparkles className="w-4 h-4" />
                            YouTube-Kompilation (Batch 1) jetzt manuell rendern
                          </button>
                          {index < youtubeClips.length - 1 && (
                            <div className={`text-[10px] font-bold font-mono uppercase tracking-wider pt-1.5 border-t ${
                              isLight ? 'border-emerald-200 text-zinc-600' : 'border-emerald-800/40 text-zinc-400'
                            }`}>
                              Überhang / Folge-Puffer (Batch 2):
                            </div>
                          )}
                        </div>
                      );
                    }
                  });

                  return rows;
                })()}
              </div>
            </div>

            {/* Standalone Button if threshold not yet reached */}
            {stats.longformSeconds < settings.longformTarget && (
              <button
                className="w-full py-2.5 rounded-xl font-mono text-xs font-bold bg-accent-main hover:bg-accent-main-hover text-white transition shadow-xs flex items-center justify-center gap-2 cursor-pointer"
              >
                <Sparkles className="w-4 h-4" />
                YouTube-Kompilation jetzt manuell rendern
              </button>
            )}
          </div>

          {/* Schnitt- & Render-Parameter (Agentic Montage) */}
          <div className={`p-5 rounded-xl border flex flex-col gap-4 col-span-1 lg:col-span-2 ${
            isLight ? 'bg-white border-zinc-200 shadow-xs' : 'bg-zinc-900 border-zinc-800 shadow-md'
          }`}>
            <div className="flex items-center justify-between border-b pb-2">
              <div className="flex items-center gap-2">
                <Sliders className="w-4 h-4 text-accent-main" />
                <h3 className={`font-bold text-sm font-mono ${isLight ? 'text-zinc-900' : 'text-zinc-100'}`}>
                  SCHNITT- & RENDER-PARAMETER (AGENTIC MONTAGE)
                </h3>
              </div>
              <span className={`text-[11px] font-mono ${isLight ? 'text-zinc-500' : 'text-zinc-400'}`}>
                FFmpeg & OpenMontage Presets
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 font-mono text-xs">
              <div>
                <label className="font-bold flex justify-between mb-1">
                  <span>Zielzeit Shorts (Sekunden):</span>
                  <span className="text-accent-main">{settings.shortsTarget}s (~{Math.round(settings.shortsTarget / 60)} Min)</span>
                </label>
                <input
                  type="range"
                  min="60"
                  max="180"
                  step="15"
                  value={settings.shortsTarget}
                  onChange={(e) => setSettings({ ...settings, shortsTarget: Number(e.target.value) })}
                  className="w-full accent-emerald-600"
                />
              </div>

              <div>
                <label className="font-bold flex justify-between mb-1">
                  <span>Zielzeit YouTube (Sekunden):</span>
                  <span className="text-accent-main">{settings.longformTarget}s (~{(settings.longformTarget / 60).toFixed(1)} Min)</span>
                </label>
                <input
                  type="range"
                  min="480"
                  max="900"
                  step="30"
                  value={settings.longformTarget}
                  onChange={(e) => setSettings({ ...settings, longformTarget: Number(e.target.value) })}
                  className="w-full accent-emerald-600"
                />
              </div>

              <div>
                <label className="font-bold block mb-1">Ausgabe-Auflösung:</label>
                <select
                  value={settings.resolution}
                  onChange={(e) => setSettings({ ...settings, resolution: e.target.value })}
                  className={`p-2 rounded-lg border w-full ${isLight ? 'bg-zinc-50 border-zinc-200 text-zinc-900' : 'bg-zinc-950 border-zinc-800 text-zinc-100'}`}
                >
                  <option value="1080p">1080p Full HD (Empfohlen)</option>
                  <option value="4k">4K Ultra HD</option>
                  <option value="720p">720p HD</option>
                </select>
              </div>

              <div className="flex flex-col justify-end">
                <div className="flex items-center gap-2 mb-2">
                  <input
                    type="checkbox"
                    id="norm"
                    checked={settings.audioNormalize}
                    onChange={(e) => setSettings({ ...settings, audioNormalize: e.target.checked })}
                    className="rounded accent-emerald-600 cursor-pointer"
                  />
                  <label htmlFor="norm" className="font-bold cursor-pointer select-none">
                    Lautstärke angleichen (EBU R128 Loudness)
                  </label>
                </div>
                <button
                  onClick={saveSettings}
                  className="w-full py-2 rounded-xl font-bold bg-accent-main hover:bg-accent-main-hover text-white flex items-center justify-center gap-2 cursor-pointer shadow-xs transition"
                >
                  {settingsSaved ? <Check className="w-4 h-4" /> : <Settings className="w-4 h-4" />}
                  {settingsSaved ? 'Parameter gespeichert!' : 'Schnittparameter speichern'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── TAB 3: LINKEDIN STUDIO ── */}
      {activeTab === 'linkedin' && (
        <div className="flex-1 overflow-auto grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className={`p-4 rounded-xl border flex flex-col gap-3 ${
            isLight ? 'bg-white border-zinc-200 shadow-xs' : 'bg-zinc-900 border-zinc-800 shadow-md'
          }`}>
            <h3 className={`text-xs font-mono font-bold uppercase ${isLight ? 'text-zinc-700' : 'text-zinc-300'}`}>
              Eingegangene Artikel & Links ({linkedinItems.length})
            </h3>
            <div className="space-y-2 overflow-auto">
              {linkedinItems.length === 0 ? (
                <div className={`p-8 text-center text-xs font-mono ${isLight ? 'text-zinc-500' : 'text-zinc-400'}`}>
                  Noch keine Links oder Textnotizen vorhanden. Sende Artikel an @Beatman_bot auf Telegram.
                </div>
              ) : (
                linkedinItems.map((item) => (
                  <div
                    key={item.id}
                    className={`p-3 rounded-xl border space-y-1.5 ${isLight ? 'bg-zinc-50 border-zinc-200 text-zinc-900' : 'bg-zinc-950 border-zinc-800 text-zinc-100'}`}
                  >
                    <div className="font-bold text-xs">{item.title || item.url}</div>
                    {item.user_note && <div className={`text-xs italic ${isLight ? 'text-zinc-600' : 'text-zinc-400'}`}>"{item.user_note}"</div>}
                    <button className="px-2.5 py-1 rounded-lg bg-accent-main text-white font-mono text-[11px] font-bold flex items-center gap-1 cursor-pointer hover:opacity-90">
                      <Sparkles className="w-3 h-3" /> Post-Entwurf generieren
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className={`p-4 rounded-xl border flex flex-col gap-3 ${
            isLight ? 'bg-white border-zinc-200 shadow-xs' : 'bg-zinc-900 border-zinc-800 shadow-md'
          }`}>
            <h3 className={`text-xs font-mono font-bold uppercase ${isLight ? 'text-zinc-700' : 'text-zinc-300'}`}>
              LinkedIn Post-Editor & Vorschau
            </h3>
            <textarea
              placeholder="Hier erscheint der KI-generierte LinkedIn Post-Entwurf..."
              className={`w-full flex-1 p-3 rounded-xl border font-sans text-xs outline-none resize-none min-h-[220px] ${
                isLight ? 'bg-zinc-50 border-zinc-200 text-zinc-900' : 'bg-zinc-950 border-zinc-800 text-zinc-100'
              }`}
            />
            <div className="flex justify-end gap-2">
              <button className={`px-3 py-1.5 rounded-lg border font-mono text-xs font-bold ${
                isLight ? 'border-zinc-300 text-zinc-700 hover:bg-zinc-100' : 'border-zinc-700 text-zinc-300 hover:bg-zinc-800'
              }`}>
                Als Entwurf speichern
              </button>
              <button className="px-4 py-1.5 rounded-lg font-mono text-xs font-bold bg-accent-main text-white hover:opacity-90">
                Veröffentlichen
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── TAB 4: EINSTELLUNGEN, KI & STATUS ── */}
      {activeTab === 'settings' && (
        <div className={`flex-1 overflow-auto p-6 rounded-xl border max-w-3xl mx-auto space-y-6 ${
          isLight ? 'bg-white border-zinc-200 shadow-xs' : 'bg-zinc-900 border-zinc-800 shadow-md'
        }`}>
          <div>
            <h2 className="text-sm font-bold font-mono text-accent-main uppercase">KI-Provider & Sprachmodelle</h2>
            <p className={`text-xs ${isLight ? 'text-zinc-600' : 'text-zinc-400'}`}>Konfiguriere LLMs für automatisierte Titel, Skripte und Post-Texte.</p>
          </div>

          <div className="space-y-4 font-mono text-xs">
            <div>
              <label className="font-bold block mb-1">KI-Provider:</label>
              <select
                value={settings.aiProvider}
                onChange={(e) => setSettings({ ...settings, aiProvider: e.target.value })}
                className={`p-2 rounded-lg border w-full ${isLight ? 'bg-zinc-50 border-zinc-200 text-zinc-900' : 'bg-zinc-950 border-zinc-800 text-zinc-100'}`}
              >
                <option value="openrouter">OpenRouter (Direkt)</option>
                <option value="gemini">Google Gemini API (Direkt)</option>
                <option value="groq">Groq (Ultra-Fast)</option>
                <option value="omniroute">OmniRoute (Lokaler Router)</option>
              </select>
            </div>

            <div>
              <label className="font-bold block mb-1">Sprachmodell:</label>
              <input
                type="text"
                value={settings.aiModel}
                onChange={(e) => setSettings({ ...settings, aiModel: e.target.value })}
                className={`p-2 rounded-lg border w-full ${isLight ? 'bg-zinc-50 border-zinc-200 text-zinc-900' : 'bg-zinc-950 border-zinc-800 text-zinc-100'}`}
              />
            </div>

            <div>
              <label className="font-bold block mb-1">LinkedIn System-Prompt:</label>
              <textarea
                rows={3}
                value={settings.linkedinPrompt}
                onChange={(e) => setSettings({ ...settings, linkedinPrompt: e.target.value })}
                className={`p-2 rounded-lg border w-full font-sans text-xs ${isLight ? 'bg-zinc-50 border-zinc-200 text-zinc-900' : 'bg-zinc-950 border-zinc-800 text-zinc-100'}`}
              />
            </div>

            <button
              onClick={saveSettings}
              className="w-full py-2.5 rounded-xl font-bold bg-accent-main hover:bg-accent-main-hover text-white flex items-center justify-center gap-2 cursor-pointer shadow-xs transition"
            >
              {settingsSaved ? <Check className="w-4 h-4" /> : <Settings className="w-4 h-4" />}
              {settingsSaved ? 'Modell-Einstellungen gespeichert!' : 'KI-Einstellungen speichern'}
            </button>
          </div>

          <div className="pt-4 border-t border-zinc-200 dark:border-zinc-800 space-y-3">
            <div>
              <h2 className="text-sm font-bold font-mono text-accent-main uppercase">System & Infrastruktur-Status</h2>
              <p className={`text-xs ${isLight ? 'text-zinc-600' : 'text-zinc-400'}`}>Status der Media-Services, Montage-Engine und Anbindungen.</p>
            </div>

            <div className="space-y-2 font-mono text-xs">
              <div className={`p-3 rounded-xl border flex justify-between items-center ${isLight ? 'bg-zinc-50 border-zinc-200' : 'bg-zinc-950 border-zinc-800'}`}>
                <span>Media-PocketBase Instanz:</span>
                <span className="font-bold text-accent-main">Port 8092 (/api/media Proxy)</span>
              </div>
              <div className={`p-3 rounded-xl border flex justify-between items-center ${isLight ? 'bg-zinc-50 border-zinc-200' : 'bg-zinc-950 border-zinc-800'}`}>
                <span>OpenMontage Storyboard & Server:</span>
                <span className="font-bold text-emerald-600">Port 4750 (Docker Container Aktiv)</span>
              </div>
              <div className={`p-3 rounded-xl border flex justify-between items-center ${isLight ? 'bg-zinc-50 border-zinc-200' : 'bg-zinc-950 border-zinc-800'}`}>
                <span>Telegram Bot Empfänger:</span>
                <span className="font-bold text-emerald-600">@Beatman_bot (Google Gemini 2.5 Flash Aktiv)</span>
              </div>
              <div className={`p-3 rounded-xl border flex justify-between items-center ${isLight ? 'bg-zinc-50 border-zinc-200' : 'bg-zinc-950 border-zinc-800'}`}>
                <span>FFmpeg-Schnitt-Worker:</span>
                <span className="font-bold text-amber-600">Bereit für Docker</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── PREVIEW VIDEO / IMAGE MODAL ── */}
      {previewItem && (
        <div
          onClick={() => setPreviewItem(null)}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-150"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className={`w-full max-w-2xl rounded-2xl border p-4 shadow-2xl flex flex-col gap-3 ${
              isLight ? 'bg-white border-zinc-200 text-zinc-900' : 'bg-zinc-900 border-zinc-800 text-zinc-100'
            }`}
          >
            <div className={`flex items-center justify-between border-b pb-2 ${isLight ? 'border-zinc-200' : 'border-zinc-800'}`}>
              <div className="font-mono font-bold text-xs truncate">
                {previewItem.original_filename || previewItem.file}
              </div>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setEditingItem(previewItem)}
                  className="p-1 rounded-lg hover:bg-accent-soft text-accent-main cursor-pointer"
                  title="Kategorie / Tags bearbeiten"
                >
                  <Tag className="w-4 h-4" />
                </button>
                <button
                  onClick={() => setDeleteConfirmItem(previewItem)}
                  className="p-1 rounded-lg hover:bg-rose-50 text-rose-500 cursor-pointer"
                  title="Löschen"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
                <button
                  onClick={() => setPreviewItem(null)}
                  className={`p-1 rounded-lg cursor-pointer ${isLight ? 'text-zinc-500 hover:text-zinc-800' : 'text-zinc-400 hover:text-zinc-100'}`}
                >
                  ✕
                </button>
              </div>
            </div>

            <div className="aspect-video bg-black rounded-xl overflow-hidden flex items-center justify-center">
              {previewItem.media_type === 'video' ? (
                <video
                  src={getMediaFileUrl(previewItem) || ''}
                  controls
                  autoPlay
                  className="w-full h-full object-contain"
                />
              ) : (
                <img
                  src={getMediaFileUrl(previewItem) || ''}
                  alt=""
                  className="w-full h-full object-contain"
                />
              )}
            </div>

            <div className="flex items-center justify-between flex-wrap gap-2 pt-1">
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-[11px] font-bold text-zinc-400 font-mono">Thema:</span>
                {previewItem.metadata_json?.category ? (
                  getCategoryBadge(previewItem.metadata_json.category)
                ) : (
                  <span className="text-[11px] text-zinc-400 italic">Noch nicht zugewiesen</span>
                )}
                {(previewItem.metadata_json?.tags || []).map((t: string) => (
                  <span key={t} className="px-1.5 py-0.2 rounded text-[10px] font-mono font-bold bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300">
                    #{t}
                  </span>
                ))}
              </div>

              <div className={`grid grid-cols-3 gap-3 font-mono text-[11px] ${isLight ? 'text-zinc-600' : 'text-zinc-400'}`}>
                <div>Dauer: <span className={`font-bold ${isLight ? 'text-zinc-900' : 'text-zinc-100'}`}>{previewItem.duration_seconds || 0}s</span></div>
                <div>Maße: <span className={`font-bold ${isLight ? 'text-zinc-900' : 'text-zinc-100'}`}>{previewItem.width}×{previewItem.height}</span></div>
                <div>Größe: <span className={`font-bold ${isLight ? 'text-zinc-900' : 'text-zinc-100'}`}>{formatBytes(previewItem.file_size_bytes)}</span></div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── TAGGING / KURATIERUNGS-MODAL ── */}
      {editingItem && (
        <div
          onClick={() => setEditingItem(null)}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-150"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className={`w-full max-w-lg rounded-2xl border p-5 shadow-2xl flex flex-col gap-4 ${
              isLight ? 'bg-white border-zinc-200 text-zinc-900' : 'bg-zinc-900 border-zinc-800 text-zinc-100'
            }`}
          >
            <div className={`flex items-center justify-between border-b pb-2 ${isLight ? 'border-zinc-200' : 'border-zinc-800'}`}>
              <div className="flex items-center gap-2">
                <Tag className="w-4 h-4 text-accent-main" />
                <h3 className="font-bold text-xs font-mono">Video kuratieren & taggen</h3>
              </div>
              <button
                onClick={() => setEditingItem(null)}
                className={`p-1 rounded-lg cursor-pointer ${isLight ? 'text-zinc-500 hover:text-zinc-800' : 'text-zinc-400 hover:text-zinc-100'}`}
              >
                ✕
              </button>
            </div>

            <div className="text-xs font-mono truncate text-zinc-500">
              Datei: <span className="font-bold text-zinc-800 dark:text-zinc-200">{editingItem.original_filename || editingItem.file}</span>
            </div>

            {/* Schnellkategorien */}
            <div className="space-y-2">
              <label className="text-xs font-mono font-bold block">Haupt-Thema auswählen:</label>
              <div className="grid grid-cols-2 gap-2">
                {PRESET_CATEGORIES.map(cat => {
                  const isSelected = editingItem.metadata_json?.category === cat.id;
                  return (
                    <button
                      key={cat.id}
                      onClick={() => handleUpdateItemTags(editingItem, isSelected ? '' : cat.id)}
                      className={`p-2 rounded-xl text-xs font-mono font-bold text-left border transition cursor-pointer flex items-center justify-between ${
                        isSelected
                          ? 'bg-accent-main text-white border-accent-main shadow-xs'
                          : isLight ? 'bg-zinc-50 border-zinc-200 text-zinc-700 hover:bg-zinc-100' : 'bg-zinc-950 border-zinc-800 text-zinc-300 hover:bg-zinc-800'
                      }`}
                    >
                      <span>{cat.label}</span>
                      {isSelected && <Check className="w-3.5 h-3.5 shrink-0" />}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Freitext-Tags */}
            <div className="space-y-2 pt-2 border-t border-zinc-200 dark:border-zinc-800">
              <label className="text-xs font-mono font-bold block">Zusätzliche Stichwörter / Tags:</label>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={customTagInput}
                  onChange={(e) => setCustomTagInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && customTagInput.trim()) {
                      e.preventDefault();
                      const currentTags = editingItem.metadata_json?.tags || [];
                      const tagClean = customTagInput.trim().replace(/^#/, '');
                      if (!currentTags.includes(tagClean)) {
                        handleUpdateItemTags(editingItem, undefined, [...currentTags, tagClean]);
                      }
                      setCustomTagInput('');
                    }
                  }}
                  placeholder="Tag eingeben + Enter (z.B. lustig, gassi, urlaub)..."
                  className={`flex-1 px-3 py-1.5 rounded-lg border text-xs font-mono outline-none ${
                    isLight ? 'bg-zinc-50 border-zinc-200 text-zinc-900 focus:border-accent-main' : 'bg-zinc-950 border-zinc-800 text-zinc-100 focus:border-accent-main'
                  }`}
                />
                <button
                  onClick={() => {
                    if (customTagInput.trim()) {
                      const currentTags = editingItem.metadata_json?.tags || [];
                      const tagClean = customTagInput.trim().replace(/^#/, '');
                      if (!currentTags.includes(tagClean)) {
                        handleUpdateItemTags(editingItem, undefined, [...currentTags, tagClean]);
                      }
                      setCustomTagInput('');
                    }
                  }}
                  className="px-3 py-1.5 rounded-lg bg-accent-main text-white font-mono text-xs font-bold flex items-center gap-1 cursor-pointer hover:opacity-90"
                >
                  <Plus className="w-3.5 h-3.5" /> Hinzufügen
                </button>
              </div>

              {/* Tag Liste */}
              <div className="flex items-center gap-1.5 flex-wrap pt-1 min-h-[30px]">
                {(editingItem.metadata_json?.tags || []).map((t: string) => (
                  <span
                    key={t}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-mono font-bold bg-accent-soft text-accent-main border border-accent-soft"
                  >
                    #{t}
                    <button
                      onClick={() => {
                        const currentTags = editingItem.metadata_json?.tags || [];
                        handleUpdateItemTags(editingItem, undefined, currentTags.filter((x: string) => x !== t));
                      }}
                      className="hover:text-rose-500 cursor-pointer ml-0.5"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                ))}
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2 border-t border-zinc-200 dark:border-zinc-800">
              <button
                onClick={() => setEditingItem(null)}
                className="px-4 py-2 rounded-xl font-mono text-xs font-bold bg-accent-main text-white hover:opacity-90 cursor-pointer"
              >
                Fertig
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── LÖSCHEN BESTÄTIGUNGS-MODAL ── */}
      {deleteConfirmItem && (
        <div
          onClick={() => setDeleteConfirmItem(null)}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-150"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className={`w-full max-w-md rounded-2xl border p-5 shadow-2xl flex flex-col gap-4 ${
              isLight ? 'bg-white border-zinc-200 text-zinc-900' : 'bg-zinc-900 border-zinc-800 text-zinc-100'
            }`}
          >
            <div className="flex items-center gap-2.5 text-rose-600">
              <div className="w-8 h-8 rounded-lg bg-rose-100 dark:bg-rose-950/60 flex items-center justify-center">
                <Trash2 className="w-4 h-4" />
              </div>
              <h3 className="font-bold text-sm font-mono">Video aus Auffangpool löschen?</h3>
            </div>

            <p className="text-xs font-mono text-zinc-600 dark:text-zinc-400">
              Möchtest du die Datei <span className="font-bold text-zinc-900 dark:text-zinc-100">{deleteConfirmItem.original_filename || deleteConfirmItem.file}</span> wirklich endgültig aus der Datenbank entfernen?
            </p>

            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                disabled={isDeleting}
                onClick={() => setDeleteConfirmItem(null)}
                className={`px-3 py-1.5 rounded-lg border font-mono text-xs font-bold cursor-pointer ${
                  isLight ? 'border-zinc-300 text-zinc-700 hover:bg-zinc-100' : 'border-zinc-700 text-zinc-300 hover:bg-zinc-800'
                }`}
              >
                Abbrechen
              </button>
              <button
                disabled={isDeleting}
                onClick={() => handleDeleteItem(deleteConfirmItem)}
                className="px-4 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-700 text-white font-mono text-xs font-bold flex items-center gap-1.5 cursor-pointer shadow-xs transition"
              >
                {isDeleting ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
                {isDeleting ? 'Wird gelöscht...' : 'Endgültig löschen'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── BULK LÖSCHEN BESTÄTIGUNGS-MODAL ── */}
      {bulkDeleteConfirmOpen && (
        <div
          onClick={() => setBulkDeleteConfirmOpen(false)}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-150"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className={`w-full max-w-md rounded-2xl border p-5 shadow-2xl flex flex-col gap-4 ${
              isLight ? 'bg-white border-zinc-200 text-zinc-900' : 'bg-zinc-900 border-zinc-800 text-zinc-100'
            }`}
          >
            <div className="flex items-center gap-2.5 text-rose-600">
              <div className="w-8 h-8 rounded-lg bg-rose-100 dark:bg-rose-950/60 flex items-center justify-center">
                <Trash2 className="w-4 h-4" />
              </div>
              <h3 className="font-bold text-sm font-mono">{selectedIds.size} Videos endgültig löschen?</h3>
            </div>

            <p className="text-xs font-mono text-zinc-600 dark:text-zinc-400">
              Möchtest du die <span className="font-bold text-rose-600">{selectedIds.size} ausgewählten Dateien</span> wirklich unwiderruflich aus dem Auffangpool entfernen?
            </p>

            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                disabled={isBulkDeleting}
                onClick={() => setBulkDeleteConfirmOpen(false)}
                className={`px-3 py-1.5 rounded-lg border font-mono text-xs font-bold cursor-pointer ${
                  isLight ? 'border-zinc-300 text-zinc-700 hover:bg-zinc-100' : 'border-zinc-700 text-zinc-300 hover:bg-zinc-800'
                }`}
              >
                Abbrechen
              </button>
              <button
                disabled={isBulkDeleting}
                onClick={handleBulkDelete}
                className="px-4 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-700 text-white font-mono text-xs font-bold flex items-center gap-1.5 cursor-pointer shadow-xs transition"
              >
                {isBulkDeleting ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
                {isBulkDeleting ? 'Werden gelöscht...' : `Alle ${selectedIds.size} löschen`}
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
