"use client";

import React, { useState, useEffect, useMemo } from 'react';
import {
  pbMedia,
  LinkedInContentRecord
} from '@/lib/pocketbase';
import {
  FileText,
  Plus,
  Sparkles,
  ExternalLink,
  Trash2,
  RefreshCw,
  Copy,
  Check,
  Send,
  Calendar,
  ThumbsUp,
  MessageCircle,
  Repeat2,
  Globe,
  MoreHorizontal,
  List,
  AlertCircle,
  CheckCircle2,
  Link2
} from 'lucide-react';

interface LinkedInStudioTabProps {
  themeMode?: 'light' | 'dark';
}

const PROMPT_PRESETS = [
  {
    id: 'takeaways',
    label: '💡 3 Key Takeaways & Framework',
    prompt: 'Erstelle einen prägnanten LinkedIn-Post im Stil eines Senior Execs. 1 starker Hook-Satz ohne Floskeln, dann 3 strukturierte Bulletpoints mit konkreten Erkenntnissen, gefolgt von einer offenen Diskussionsfrage als Call-to-Action.'
  },
  {
    id: 'contrarian',
    label: '🔥 Konträre These / Contrarian View',
    prompt: 'Schreibe einen provokanten LinkedIn-Post, der eine gängige Branchen-Meinung sachlich zerlegt. Starte mit einer ungemütlichen Wahrheit, begründe sie in 3 kurzen Absätzen mit Fakten und schließe mit einem klaren Fazit.'
  },
  {
    id: 'storytelling',
    label: '📖 Storytelling / Founder Journey',
    prompt: 'Schreibe einen persönlichen, reflektierten Post. Erzähle eine kurze Learnings-Story: Ausgangslage, unerwarteter Fehler/Hürde, Erkenntnis und konkreter Nutzen für den Leser.'
  },
  {
    id: 'case_study',
    label: '📊 Problem → Lösung → Resultat',
    prompt: 'Erstelle eine kurze Case-Study als LinkedIn-Post. Format: Das Problem (1 Satz) -> Die unkonventionelle Lösung (2 Sätze) -> Das messbare Ergebnis (Zahlen/KPIs).'
  }
];

export function LinkedInStudioTab({ themeMode = 'light' }: LinkedInStudioTabProps) {
  const isLight = themeMode === 'light';

  const [items, setItems] = useState<LinkedInContentRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<'all' | LinkedInContentRecord['status']>('all');

  // Form State
  const [isNewModalOpen, setIsNewModalOpen] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newUrl, setNewUrl] = useState('');
  const [newRawContent, setNewRawContent] = useState('');
  const [newUserNote, setNewUserNote] = useState('');

  // Active Editor State
  const [currentDraft, setCurrentDraft] = useState('');
  const [currentStatus, setCurrentStatus] = useState<LinkedInContentRecord['status']>('inbox');
  const [selectedPresetId, setSelectedPresetId] = useState(PROMPT_PRESETS[0].id);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showFullPostInPreview, setShowFullPostInPreview] = useState(false);

  // Toast
  const [toast, setToast] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  const showToast = (text: string, type: 'success' | 'error' = 'success') => {
    setToast({ text, type });
    setTimeout(() => setToast(null), 3500);
  };

  const fetchItems = async () => {
    try {
      setLoading(true);
      const res = await pbMedia.collection('linkedin_content').getFullList<LinkedInContentRecord>({
        sort: '-created'
      });
      setItems(res);
      if (res.length > 0 && !selectedId) {
        setSelectedId(res[0].id);
        setCurrentDraft(res[0].draft_post || '');
        setCurrentStatus(res[0].status || 'inbox');
      }
    } catch (err: any) {
      console.warn('Error fetching LinkedIn content:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchItems();

    let unsub: (() => void) | undefined;
    pbMedia.collection('linkedin_content').subscribe<LinkedInContentRecord>('*', (e) => {
      if (e.action === 'create') setItems((prev) => [e.record, ...prev]);
      else if (e.action === 'update') {
        setItems((prev) => prev.map((item) => (item.id === e.record.id ? e.record : item)));
        if (selectedId === e.record.id) {
          setCurrentDraft(e.record.draft_post || '');
          setCurrentStatus(e.record.status || 'inbox');
        }
      } else if (e.action === 'delete') {
        setItems((prev) => prev.filter((item) => item.id !== e.record.id));
      }
    }).then((fn) => { unsub = fn; }).catch(() => {});

    return () => {
      if (unsub) unsub();
      pbMedia.collection('linkedin_content').unsubscribe('*');
    };
  }, []);

  const selectedItem = useMemo(() => {
    return items.find((it) => it.id === selectedId) || items[0] || null;
  }, [items, selectedId]);

  useEffect(() => {
    if (selectedItem) {
      setCurrentDraft(selectedItem.draft_post || '');
      setCurrentStatus(selectedItem.status || 'inbox');
      setShowFullPostInPreview(false);
    }
  }, [selectedItem?.id]);

  const filteredItems = useMemo(() => {
    if (statusFilter === 'all') return items;
    return items.filter((it) => it.status === statusFilter);
  }, [items, statusFilter]);

  const handleCreateNew = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const rec = await pbMedia.collection('linkedin_content').create<LinkedInContentRecord>({
        title: newTitle.trim() || 'Neuer Artikel/Beitrag',
        url: newUrl.trim() || undefined,
        raw_content: newRawContent.trim() || undefined,
        user_note: newUserNote.trim() || undefined,
        status: 'inbox',
        received_at: new Date().toISOString()
      });
      setIsNewModalOpen(false);
      setNewTitle('');
      setNewUrl('');
      setNewRawContent('');
      setNewUserNote('');
      setSelectedId(rec.id);
      showToast('Eintrag in Inbox gespeichert.');
    } catch (err: any) {
      showToast(`Fehler: ${err.message}`, 'error');
    }
  };

  const handleSaveDraft = async () => {
    if (!selectedItem) return;
    setIsSaving(true);
    try {
      await pbMedia.collection('linkedin_content').update(selectedItem.id, {
        draft_post: currentDraft,
        status: currentStatus
      });
      showToast('Entwurf gespeichert.');
    } catch (err: any) {
      showToast(`Fehler beim Speichern: ${err.message}`, 'error');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDeleteItem = async (id: string) => {
    if (!confirm('Diesen Eintrag wirklich löschen?')) return;
    try {
      await pbMedia.collection('linkedin_content').delete(id);
      if (selectedId === id) setSelectedId(null);
      showToast('Eintrag gelöscht.');
    } catch (err: any) {
      showToast(`Fehler: ${err.message}`, 'error');
    }
  };

  // KI-Post Generator via OmniRoute / LLM
  const handleGenerateAI = async () => {
    if (!selectedItem) return;
    setIsGenerating(true);
    const preset = PROMPT_PRESETS.find((p) => p.id === selectedPresetId) || PROMPT_PRESETS[0];

    const sourceContext = `
Titel: ${selectedItem.title || 'Kein Titel'}
URL: ${selectedItem.url || 'Keine URL'}
Notizen: ${selectedItem.user_note || 'Keine'}
Inhalt: ${selectedItem.raw_content ? selectedItem.raw_content.slice(0, 3000) : 'Kein Volltext'}
`.trim();

    const systemPrompt = `Du bist ein erfahrener B2B-Ghostwriter für Executives.
Schreibe auf Deutsch. Keine typischen KI-Floskeln (kein 'Tauchen wir ein', 'In der heutigen dynamischen Welt', 'Lasst uns diskutieren').
Verwende saubere Absätze, pointierte Sätze und hohe Informationsdichte.
Formatiere Überschriften oder Hooks mit Unicode-Fettung für LinkedIn (z.B. 𝗭𝗶𝗲𝗹 oder 𝗙𝗮𝗸𝘁).`;

    const userPrompt = `${preset.prompt}\n\nBasis-Informationen zum Artikel/Thema:\n${sourceContext}`;

    try {
      const res = await fetch('http://localhost:20128/v1/chat/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: 'omniroute',
          messages: [
            { role: 'system', content: systemPrompt },
            { role: 'user', content: userPrompt }
          ],
          temperature: 0.7
        })
      });

      if (res.ok) {
        const data = await res.json();
        const generated = data.choices?.[0]?.message?.content || '';
        if (generated) {
          setCurrentDraft(generated);
          setCurrentStatus('drafted');
          showToast('KI-Post generiert.');
          return;
        }
      }
      throw new Error('OmniRoute Antwort leer');
    } catch (err) {
      const sampleHook = selectedItem.title ? `Viele unterschätzen "${selectedItem.title}":` : 'Die meisten machen beim Skalieren denselben Fehler:';
      const fallbackPost = `𝗙𝗮𝗸𝘁: ${sampleHook}

Wer heute Prozesse automatisieren will, stolpert selten über die Technologie – sondern über unklare Schnittstellen.

Hier sind die 3 wichtigsten Hebel aus der Praxis:

• 𝟭. 𝗦𝘁𝗿𝘂𝗸𝘁𝘂𝗿 𝘃𝗼𝗿 𝗦𝗽𝗲𝗲𝗱: Saubere Schemas und Datentypen schlagen Ad-hoc-Skripte jedes Mal.
• 𝟮. 𝗘𝗰𝗵𝘁𝘇𝗲𝗶𝘁-𝗦𝘆𝗻𝗰: Polling erzeugt Latenz. Realtime-Events halten Systeme konsistent.
• 𝟯. 𝗙𝗼𝗸𝘂𝘀 𝗮𝘂𝗳 𝗱𝗲𝗻 𝗡𝘂𝘁𝘇𝗲𝗿: Ein Tool ist nur so gut wie die Reibungslosigkeit im Arbeitsalltag.

${selectedItem.user_note ? `Praxis-Notiz: ${selectedItem.user_note}\n\n` : ''}Wie löst ihr das aktuell in eurer Architektur? Diskutiert gerne in den Kommentaren. 👇

${selectedItem.url ? `🔗 Quelle: ${selectedItem.url}` : ''}`;

      setCurrentDraft(fallbackPost);
      setCurrentStatus('drafted');
      showToast('Entwurf mit Template-Engine erstellt.');
    } finally {
      setIsGenerating(false);
    }
  };

  const handleCopyClipboard = () => {
    navigator.clipboard.writeText(currentDraft);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
    showToast('In Zwischenablage kopiert.');
  };

  const insertFormatting = (prefix: string, suffix: string = '') => {
    const textarea = document.getElementById('linkedin-draft-textarea') as HTMLTextAreaElement;
    if (!textarea) return;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const text = textarea.value;
    const selected = text.substring(start, end) || 'Text';
    const replacement = `${prefix}${selected}${suffix}`;
    const newText = text.substring(0, start) + replacement + text.substring(end);
    setCurrentDraft(newText);
    setTimeout(() => {
      textarea.focus();
      textarea.setSelectionRange(start + prefix.length, start + prefix.length + selected.length);
    }, 50);
  };

  const inputStyle = {
    backgroundColor: 'var(--studio-input-bg, #121215)',
    color: 'var(--studio-input-text, #f8fafc)',
    borderColor: 'var(--studio-input-border, #334155)'
  };

  const cardStyle = {
    backgroundColor: 'var(--studio-card-bg, #111827)',
    borderColor: 'var(--studio-card-border, #1f2937)',
    color: 'var(--studio-text, #f8fafc)'
  };

  const subCardStyle = {
    backgroundColor: 'var(--studio-input-bg, #121215)',
    borderColor: 'var(--studio-card-border, #1f2937)'
  };

  return (
    <div className="space-y-4">
      {/* Toast Notification */}
      {toast && (
        <div
          className={`fixed bottom-6 right-6 z-50 px-4 py-2.5 rounded-lg shadow-xl border flex items-center gap-2.5 text-xs font-semibold ${
            toast.type === 'error'
              ? 'bg-rose-950/95 text-rose-200 border-rose-800'
              : 'bg-zinc-900 text-zinc-100 border-zinc-700'
          }`}
        >
          {toast.type === 'error' ? <AlertCircle className="w-4 h-4 text-red-400" /> : <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
          <span>{toast.text}</span>
        </div>
      )}

      {/* Top Filter & Action Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-1.5">
          {(['all', 'inbox', 'drafted', 'scheduled', 'published'] as const).map((st) => (
            <button
              key={st}
              onClick={() => setStatusFilter(st)}
              className="px-3 py-1.5 rounded-md text-xs font-semibold transition cursor-pointer capitalize border"
              style={
                statusFilter === st
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
              {st === 'all' ? `Alle (${items.length})` : `${st} (${items.filter((i) => i.status === st).length})`}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={fetchItems}
            className="p-1.5 rounded-md text-xs font-semibold transition cursor-pointer border"
            style={subCardStyle}
            title="Aktualisieren"
          >
            <RefreshCw className="w-3.5 h-3.5 text-[var(--studio-text-muted,#94a3b8)]" />
          </button>
          <button
            onClick={() => setIsNewModalOpen(true)}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-md text-xs font-bold text-white shadow-xs transition cursor-pointer"
            style={{ backgroundColor: 'var(--studio-accent, #ef4444)' }}
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Neuer Artikel / Link</span>
          </button>
        </div>
      </div>

      {/* Main Grid: Inbox list on left, Editor & LinkedIn Preview on right */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Left Column: Inbox List (4 Cols) */}
        <div className="lg:col-span-4 space-y-2.5">
          <h3 className="text-xs font-bold uppercase tracking-wider font-mono text-[var(--studio-text-muted,#94a3b8)]">
            Eingegangene Artikel & Links ({filteredItems.length})
          </h3>

          {filteredItems.length === 0 ? (
            <div className="p-6 rounded-xl border text-center" style={cardStyle}>
              <FileText className="w-7 h-7 mx-auto mb-2 opacity-30 text-[var(--studio-text-muted,#94a3b8)]" />
              <p className="text-xs font-medium">Keine Artikel vorhanden.</p>
              <button
                onClick={() => setIsNewModalOpen(true)}
                className="mt-2 text-xs hover:underline font-semibold cursor-pointer"
                style={{ color: 'var(--studio-accent, #ef4444)' }}
              >
                + Artikel erfassen
              </button>
            </div>
          ) : (
            <div className="space-y-2 max-h-[640px] overflow-y-auto pr-1">
              {filteredItems.map((item) => {
                const isSelected = selectedItem?.id === item.id;

                return (
                  <div
                    key={item.id}
                    onClick={() => setSelectedId(item.id)}
                    className="p-3 rounded-xl border transition cursor-pointer shadow-xs"
                    style={{
                      backgroundColor: isSelected
                        ? 'var(--studio-card-bg, #111827)'
                        : 'var(--studio-input-bg, #121215)',
                      borderColor: isSelected
                        ? 'var(--studio-accent, #ef4444)'
                        : 'var(--studio-card-border, #1f2937)',
                      boxShadow: isSelected ? '0 0 0 1px var(--studio-accent, #ef4444)' : 'none'
                    }}
                  >
                    <div className="flex items-start justify-between gap-2 mb-1">
                      <h4 className="text-xs font-bold line-clamp-1" style={{ color: 'var(--studio-text, #f8fafc)' }}>
                        {item.title || 'Ohne Titel'}
                      </h4>
                      <span
                        className="text-[9px] font-bold px-1.5 py-0.5 rounded-full shrink-0 border"
                        style={{
                          backgroundColor: 'var(--studio-input-bg, #121215)',
                          borderColor: 'var(--studio-card-border, #1f2937)',
                          color: item.status === 'published' ? '#10b981' : 'var(--studio-text-muted, #94a3b8)'
                        }}
                      >
                        {item.status}
                      </span>
                    </div>

                    {item.url && (
                      <p className="text-[10px] font-mono truncate flex items-center gap-1 mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
                        <Link2 className="w-3 h-3 shrink-0" />
                        {item.url}
                      </p>
                    )}

                    {item.user_note && (
                      <p className="text-[11px] line-clamp-1 italic" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
                        "{item.user_note}"
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Right Column: Split Screen Editor (4 Cols) + LinkedIn Preview (4 Cols) */}
        <div className="lg:col-span-8 grid grid-cols-1 md:grid-cols-2 gap-4">
          {selectedItem ? (
            <>
              {/* Editor Column */}
              <div className="p-4 rounded-xl border flex flex-col justify-between shadow-xs" style={cardStyle}>
                <div>
                  {/* Header / Article Info */}
                  <div className="pb-2.5 border-b mb-3 flex items-start justify-between gap-2" style={{ borderColor: 'var(--studio-card-border, #1f2937)' }}>
                    <div>
                      <h4 className="text-xs font-bold line-clamp-1" style={{ color: 'var(--studio-text, #f8fafc)' }}>
                        {selectedItem.title}
                      </h4>
                      {selectedItem.url && (
                        <a
                          href={selectedItem.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[10px] hover:underline flex items-center gap-1 mt-0.5"
                          style={{ color: 'var(--studio-accent, #ef4444)' }}
                        >
                          <ExternalLink className="w-2.5 h-2.5" /> Original-Link
                        </a>
                      )}
                    </div>
                    <button
                      onClick={() => handleDeleteItem(selectedItem.id)}
                      className="text-zinc-400 hover:text-rose-400 p-1 cursor-pointer"
                      title="Löschen"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>

                  {/* AI Generator Control Box */}
                  <div className="p-3 rounded-lg border mb-3 space-y-2" style={subCardStyle}>
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-bold flex items-center gap-1.5" style={{ color: 'var(--studio-text, #f8fafc)' }}>
                        <Sparkles className="w-3.5 h-3.5" style={{ color: 'var(--studio-accent, #ef4444)' }} />
                        KI-Post Generator
                      </span>
                      <span className="text-[9px] font-mono text-[var(--studio-text-muted,#94a3b8)]">OmniRoute</span>
                    </div>

                    <select
                      value={selectedPresetId}
                      onChange={(e) => setSelectedPresetId(e.target.value)}
                      className="w-full px-2 py-1.5 rounded border text-[11px] font-medium focus:outline-hidden"
                      style={inputStyle}
                    >
                      {PROMPT_PRESETS.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.label}
                        </option>
                      ))}
                    </select>

                    <button
                      onClick={handleGenerateAI}
                      disabled={isGenerating}
                      className="w-full py-1.5 rounded-md disabled:opacity-50 text-white font-bold text-xs shadow-xs transition flex items-center justify-center gap-1.5 cursor-pointer"
                      style={{ backgroundColor: 'var(--studio-accent, #ef4444)' }}
                    >
                      <Sparkles className="w-3.5 h-3.5" />
                      <span>{isGenerating ? 'Generiere...' : 'Entwurf mit KI erstellen'}</span>
                    </button>
                  </div>

                  {/* Toolbar */}
                  <div className="flex items-center justify-between gap-1 pb-1.5 mb-2 border-b text-xs" style={{ borderColor: 'var(--studio-card-border, #1f2937)', color: 'var(--studio-text-muted, #94a3b8)' }}>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => insertFormatting('• ')}
                        className="p-1 rounded hover:bg-zinc-800 cursor-pointer"
                        title="Bullet Point"
                      >
                        <List className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => insertFormatting('𝗙𝗮𝗸𝘁: ')}
                        className="px-1.5 py-0.5 rounded hover:bg-zinc-800 font-bold text-[10px] cursor-pointer"
                        title="Bold Headline"
                      >
                        𝗙
                      </button>
                      <button
                        onClick={() => insertFormatting('💡 ')}
                        className="p-1 rounded hover:bg-zinc-800 text-xs cursor-pointer"
                      >
                        💡
                      </button>
                      <button
                        onClick={() => insertFormatting('👇 ')}
                        className="p-1 rounded hover:bg-zinc-800 text-xs cursor-pointer"
                      >
                        👇
                      </button>
                    </div>

                    <div className="text-[10px] font-mono" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
                      {currentDraft.length} Zeichen • {currentDraft.split(/\s+/).filter(Boolean).length} Wörter
                    </div>
                  </div>

                  {/* Draft Textarea */}
                  <textarea
                    id="linkedin-draft-textarea"
                    rows={11}
                    value={currentDraft}
                    onChange={(e) => setCurrentDraft(e.target.value)}
                    placeholder="Schreibe deinen LinkedIn-Post oder generiere einen mit KI..."
                    className="w-full p-2.5 rounded-lg border text-xs font-mono focus:outline-hidden resize-none leading-relaxed"
                    style={inputStyle}
                  />
                </div>

                {/* Bottom Save & Status Bar */}
                <div className="pt-2.5 border-t flex items-center justify-between gap-2 mt-2" style={{ borderColor: 'var(--studio-card-border, #1f2937)' }}>
                  <select
                    value={currentStatus}
                    onChange={(e: any) => setCurrentStatus(e.target.value)}
                    className="px-2 py-1.5 rounded-md border text-[11px] font-medium"
                    style={inputStyle}
                  >
                    <option value="inbox">Inbox</option>
                    <option value="drafted">Entwurf (Drafted)</option>
                    <option value="scheduled">Geplant (Scheduled)</option>
                    <option value="published">Veröffentlicht</option>
                    <option value="archived">Archiviert</option>
                  </select>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleCopyClipboard}
                      className="p-1.5 rounded-md text-xs transition cursor-pointer border"
                      style={subCardStyle}
                      title="Kopieren"
                    >
                      {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                    </button>
                    <button
                      onClick={handleSaveDraft}
                      disabled={isSaving}
                      className="px-3.5 py-1.5 rounded-md font-bold disabled:opacity-50 text-white text-xs shadow-xs transition cursor-pointer"
                      style={{ backgroundColor: 'var(--studio-accent, #ef4444)' }}
                    >
                      {isSaving ? 'Speichert...' : 'Speichern'}
                    </button>
                  </div>
                </div>
              </div>

              {/* LinkedIn Post Live Preview Column */}
              <div className="p-4 rounded-xl border flex flex-col justify-between shadow-xs" style={cardStyle}>
                <div>
                  <div className="flex items-center justify-between pb-2 mb-3 border-b" style={{ borderColor: 'var(--studio-card-border, #1f2937)' }}>
                    <span className="text-[10px] font-bold uppercase tracking-wider font-mono" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
                      LinkedIn Vorschau
                    </span>
                    <span className="text-[10px] font-mono" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>Feed Post</span>
                  </div>

                  {/* LinkedIn Card */}
                  <div className="p-4 rounded-lg border shadow-xs" style={subCardStyle}>
                    {/* User Header */}
                    <div className="flex items-start justify-between gap-3 mb-3">
                      <div className="flex items-center gap-2.5">
                        <div
                          className="w-9 h-9 rounded-full border flex items-center justify-center font-bold text-xs shadow-xs"
                          style={{
                            backgroundColor: 'var(--studio-card-bg, #111827)',
                            borderColor: 'var(--studio-card-border, #1f2937)',
                            color: 'var(--studio-text, #f8fafc)'
                          }}
                        >
                          MB
                        </div>
                        <div>
                          <h5 className="text-xs font-bold leading-tight" style={{ color: 'var(--studio-text, #f8fafc)' }}>Michael Beatman</h5>
                          <p className="text-[10px] leading-tight" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
                            Founder & AI Systems Architect
                          </p>
                          <p className="text-[9px] flex items-center gap-1 mt-0.5" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
                            Gerade eben • <Globe className="w-2.5 h-2.5" />
                          </p>
                        </div>
                      </div>
                      <button className="text-zinc-500 hover:text-zinc-300">
                        <MoreHorizontal className="w-3.5 h-3.5" />
                      </button>
                    </div>

                    {/* Post Text */}
                    <div className="text-xs whitespace-pre-line leading-relaxed mb-3" style={{ color: 'var(--studio-text, #f8fafc)' }}>
                      {currentDraft ? (
                        <>
                          {showFullPostInPreview || currentDraft.length <= 180 ? (
                            currentDraft
                          ) : (
                            <>
                              {currentDraft.slice(0, 180)}...
                              <button
                                onClick={() => setShowFullPostInPreview(true)}
                                className="font-semibold ml-1 cursor-pointer hover:underline"
                                style={{ color: 'var(--studio-accent, #ef4444)' }}
                              >
                                ...mehr anzeigen
                              </button>
                            </>
                          )}
                        </>
                      ) : (
                        <span className="italic" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
                          (Kein Text vorhanden.)
                        </span>
                      )}
                    </div>

                    {/* Link Card Attachment */}
                    {selectedItem.url && (
                      <div className="p-2 rounded border flex items-center justify-between gap-2.5 mb-3" style={cardStyle}>
                        <div className="overflow-hidden">
                          <p className="text-[11px] font-bold truncate" style={{ color: 'var(--studio-text, #f8fafc)' }}>{selectedItem.title || 'Link-Vorschau'}</p>
                          <p className="text-[9px] truncate" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>{selectedItem.url}</p>
                        </div>
                        <ExternalLink className="w-3.5 h-3.5 shrink-0" style={{ color: 'var(--studio-text-muted, #94a3b8)' }} />
                      </div>
                    )}

                    {/* Engagement Mockup */}
                    <div className="pt-2 border-t flex items-center justify-between text-[10px] px-1" style={{ borderColor: 'var(--studio-card-border, #1f2937)', color: 'var(--studio-text-muted, #94a3b8)' }}>
                      <span className="flex items-center gap-1">
                        <span className="w-3.5 h-3.5 rounded-full flex items-center justify-center text-[8px]" style={{ backgroundColor: 'var(--studio-card-bg, #111827)', color: 'var(--studio-accent, #ef4444)' }}>👍</span>
                        24 Likes
                      </span>
                      <span>6 Kommentare</span>
                    </div>

                    {/* Action Bar */}
                    <div className="pt-2 mt-1 border-t grid grid-cols-4 gap-1 text-center text-[10px] font-semibold" style={{ borderColor: 'var(--studio-card-border, #1f2937)', color: 'var(--studio-text-muted, #94a3b8)' }}>
                      <button className="py-1 rounded hover:bg-zinc-800/60 flex items-center justify-center gap-1 cursor-pointer">
                        <ThumbsUp className="w-3 h-3" /> Like
                      </button>
                      <button className="py-1 rounded hover:bg-zinc-800/60 flex items-center justify-center gap-1 cursor-pointer">
                        <MessageCircle className="w-3 h-3" /> Kommentar
                      </button>
                      <button className="py-1 rounded hover:bg-zinc-800/60 flex items-center justify-center gap-1 cursor-pointer">
                        <Repeat2 className="w-3 h-3" /> Repost
                      </button>
                      <button className="py-1 rounded hover:bg-zinc-800/60 flex items-center justify-center gap-1 cursor-pointer">
                        <Send className="w-3 h-3" /> Senden
                      </button>
                    </div>
                  </div>
                </div>

                <div className="pt-2 text-center">
                  <span className="text-[9px] font-mono" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>
                    LinkedIn Algorithmus Ready
                  </span>
                </div>
              </div>
            </>
          ) : (
            <div className="col-span-2 p-8 rounded-xl border text-center" style={cardStyle}>
              <FileText className="w-8 h-8 mx-auto mb-2 opacity-30 text-[var(--studio-text-muted,#94a3b8)]" />
              <p className="text-xs font-medium">Wähle links einen Artikel aus.</p>
            </div>
          )}
        </div>
      </div>

      {/* Modal: New Item */}
      {isNewModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="w-full max-w-lg rounded-xl border shadow-2xl p-5" style={cardStyle}>
            <h3 className="text-xs font-bold uppercase tracking-wider font-mono mb-3 flex items-center gap-2" style={{ color: 'var(--studio-accent, #ef4444)' }}>
              <FileText className="w-4 h-4" />
              Neuen Artikel erfassen
            </h3>
            <form onSubmit={handleCreateNew} className="space-y-3 text-xs">
              <div>
                <label className="block font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>Titel / Thema</label>
                <input
                  type="text"
                  placeholder="z.B. 'Architektur-Update KW34'"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border focus:outline-hidden font-medium"
                  style={inputStyle}
                  required
                />
              </div>

              <div>
                <label className="block font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>URL / Quelle (optional)</label>
                <input
                  type="url"
                  placeholder="https://..."
                  value={newUrl}
                  onChange={(e) => setNewUrl(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border focus:outline-hidden font-medium"
                  style={inputStyle}
                />
              </div>

              <div>
                <label className="block font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>Notizen / Hook-Gedanken</label>
                <textarea
                  rows={2}
                  placeholder="Was ist die Kernbotschaft?"
                  value={newUserNote}
                  onChange={(e) => setNewUserNote(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border focus:outline-hidden font-medium"
                  style={inputStyle}
                />
              </div>

              <div>
                <label className="block font-semibold mb-1" style={{ color: 'var(--studio-text-muted, #94a3b8)' }}>Roh-Inhalt (optional)</label>
                <textarea
                  rows={4}
                  placeholder="Volltext oder Auszug hier einfügen..."
                  value={newRawContent}
                  onChange={(e) => setNewRawContent(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border focus:outline-hidden font-mono text-[11px]"
                  style={inputStyle}
                />
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t" style={{ borderColor: 'var(--studio-card-border, #1f2937)' }}>
                <button
                  type="button"
                  onClick={() => setIsNewModalOpen(false)}
                  className="px-3 py-1.5 rounded-lg text-zinc-400 hover:text-zinc-200 cursor-pointer"
                >
                  Abbrechen
                </button>
                <button
                  type="submit"
                  className="px-3.5 py-1.5 rounded-lg font-bold text-white shadow-xs cursor-pointer"
                  style={{ backgroundColor: 'var(--studio-accent, #ef4444)' }}
                >
                  Speichern
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
