"use client";

import React, { useState, useEffect, useRef } from 'react';
import { KontaktRecord, STATUS_COLUMNS, pb, getProfilbildUrl } from '@/lib/pocketbase';
import { transcribeAudioOnly, summarizeText } from '@/utils/aiAudio';
import {
  X, Save, Trash2, Calendar, Star, Building2, MapPin, User, MessageSquare, Search,
  AlertTriangle, CheckCircle2, Send, Clock, Image as ImageIcon, Upload, SlidersHorizontal, Settings,
  Plus, ArrowUp, ArrowDown, RotateCcw, Link2, Mail, Phone, Eye, EyeOff, LayoutGrid, Tag, Clipboard, ExternalLink,
  Mic, Square, Loader2, ChevronDown, ChevronUp, FileText, SquarePen, Pencil
} from 'lucide-react';
import { NachrichtenverlaufPanel } from './NachrichtenverlaufPanel';

function LinkedinIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4v-7a6 6 0 0 1 6-6z" />
      <rect x="2" y="9" width="4" height="12" />
      <circle cx="4" cy="4" r="2" />
    </svg>
  );
}

export const sanitizeAndCleanLinks = (text: string): string => {
  if (!text) return '';
  return text
    .replace(/(https?:\/\/[^\s<>]+)\s*<\1>/gi, '$1')
    .replace(/<(https?:\/\/[^\s<>]+)>/gi, '$1')
    .replace(/(\r?\n){2,}/g, '\n')
    .split('\n')
    .map((line) => line.trim())
    .join('\n')
    .trim();
};

export const sanitizeMessageText = sanitizeAndCleanLinks;

export const renderFormattedBody = (rawText: string) => {
  if (!rawText) return null;

  // 1. URLs säubern und doppelte Klammern entfernen
  const cleaned = sanitizeAndCleanLinks(rawText);

  // 2. Text an URLs aufspalten und als React-Nodes rendern
  const urlRegex = /(https?:\/\/[^\s<>]+)/g;
  const parts = cleaned.split(urlRegex);

  return parts.map((part, i) => {
    if (part.match(urlRegex)) {
      return (
        <a
          key={i}
          href={part}
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-600 underline hover:text-blue-800 font-medium break-all"
          onClick={(e) => e.stopPropagation()}
        >
          {part}
        </a>
      );
    }
    return part;
  });
};

export type FieldWidth = 'full' | 'half' | 'third' | 'two-thirds';

export interface FormFieldConfig {
  key: string;
  label: string;
  type: 'text' | 'email' | 'url' | 'tel' | 'select' | 'rating' | 'date' | 'datetime-local' | 'textarea' | 'profilbild_preview' | 'tags';
  width: FieldWidth;
  visible: boolean;
  order: number;
  options?: string[];
  placeholder?: string;
  isCustom?: boolean;
}

export function getFieldWidthClass(field: FormFieldConfig): string {
  switch (field.width) {
    case 'third':
      return 'col-span-4';
    case 'half':
      return 'col-span-6';
    case 'two-thirds':
      return 'col-span-8';
    case 'full':
    default:
      return 'col-span-12';
  }
}

const ROLLEN_OPTIONEN: string[] = ['Executive Search','Recruiter / Headhunter','Private Equity / Investor','Interim / Freelance','HR / Personal','Consulting / Beratung','GF / Inhaber / CEO','Finance / CFO','Quality / GMP','Healthcare / Pharma','Sonstige'];

const DEFAULT_FORM_LAYOUT: FormFieldConfig[] = [
  { key: 'name', label: 'Name *', type: 'text', width: 'half', visible: true, order: 1, placeholder: 'Vorname Nachname' },
  { key: 'profilbild_preview', label: 'Profilbild (145x145)', type: 'profilbild_preview', width: 'half', visible: true, order: 2 },
  { key: 'unternehmen', label: 'Unternehmen', type: 'text', width: 'half', visible: true, order: 3, placeholder: 'Firma GmbH' },
  { key: 'rating', label: 'Rating (1 - 5 Sterne)', type: 'rating', width: 'half', visible: true, order: 4 },
  { key: 'rolle', label: 'Rolle / Position', type: 'text', width: 'half', visible: true, order: 5, placeholder: 'Senior Manager' },
  { key: 'tags', label: 'Tags / Schlagwörter', type: 'tags', width: 'full', visible: true, order: 6 },
  { key: 'email', label: 'E-Mail-Adresse', type: 'email', width: 'half', visible: true, order: 7, placeholder: 'name@firma.de' },
  { key: 'linkedin_url', label: 'LinkedIn Profil URL', type: 'url', width: 'half', visible: true, order: 8, placeholder: 'https://linkedin.com/in/username' },
  { key: 'telefon_1', label: 'Telefon 1 (Hauptnummer)', type: 'tel', width: 'half', visible: true, order: 9, placeholder: '+49 30 123456' },
  { key: 'region', label: 'Region', type: 'text', width: 'half', visible: true, order: 10, placeholder: 'DACH / Berlin' },
  { key: 'status', label: 'Status (Pipeline Phase)', type: 'select', width: 'half', visible: true, order: 11 },
  { key: 'telefon_2', label: 'Telefon 2 (Zweitnummer)', type: 'tel', width: 'half', visible: true, order: 12, placeholder: '+49 170 123456' },
  { key: 'profilbild', label: 'Profilbild (URL / Upload)', type: 'url', width: 'full', visible: true, order: 13, placeholder: 'https://example.com/avatar.jpg oder Dateiname' },
  { key: 'naechster_schritt', label: 'Nächster Schritt', type: 'text', width: 'full', visible: true, order: 14, placeholder: 'z.B. Erstnachricht auf LinkedIn senden' },
  { key: 'vernetzt_am', label: 'Vernetzt seit', type: 'date', width: 'third', visible: true, order: 15 },
  { key: 'einladung_zurueckgezogen_am', label: 'Zurückgezogen', type: 'date', width: 'third', visible: true, order: 16 },
  { key: 'naechster_termin', label: 'Nächster Termin', type: 'datetime-local', width: 'third', visible: true, order: 17 },
  { key: 'webseite', label: 'Webseite', type: 'url', width: 'half', visible: true, order: 18, placeholder: 'https://www.firma.de' },
  { key: 'adresse', label: 'Adresse (Multizeile)', type: 'textarea', width: 'full', visible: true, order: 19, placeholder: 'Musterstraße 123\n10115 Berlin\nDeutschland' },
  { key: 'kommentar', label: 'Notizen & Kommentar', type: 'textarea', width: 'full', visible: true, order: 20, placeholder: 'Wichtige Notizen oder Gesprächsprotokoll...' },
  { key: 'RollenVerteilungzuordnung', label: 'Rollen-Zuordnung (Mission Control)', type: 'select', width: 'half', visible: true, order: 21, placeholder: 'z.B. Executive Search / PE / Consulting' },
  { key: 'LinkedInheader', label: 'LinkedIn Headline', type: 'text', width: 'half', visible: true, order: 22, placeholder: 'Consultant & Co-Lead Private Equity at SSI...' },
  { key: 'Linkedin_info', label: 'LinkedIn Info (mehrzeilig)', type: 'textarea', width: 'full', visible: true, order: 23, placeholder: 'Aus LinkedIn kopierter Profiltext...' },
];

const LOCAL_STORAGE_FORM_LAYOUT_KEY = 'archon_crm_form_layout_v1';

interface KontaktDrawerProps {
  kontakt: KontaktRecord | null;
  isOpen: boolean;
  onClose: () => void;
  onSave: (updated: KontaktRecord) => void;
  onDelete: (id: string) => void;
  themeMode?: 'light' | 'dark';
}

interface MessageItem {
  id?: string;
  sender: 'user' | 'kontakt' | string;
  text: string;
  timestamp?: string;
  date?: string;
  time?: string;
  type?: string;
  channel?: string;
  rawTranscript?: string;
  isStarred?: boolean;
}

export function KontaktDrawer({
  kontakt,
  isOpen,
  onClose,
  onSave,
  onDelete,
  themeMode = 'light'
}: KontaktDrawerProps) {
  console.log(">>> NEUER KONTAKT-DRAWER V2 MIGRATED LOADED <<<");
  // 1. ALL STATES & REFS AT THE VERY TOP
  const [formData, setFormData] = useState<Record<string, any>>({});
  const [saving, setSaving] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [imageError, setImageError] = useState(false);

  // Form Layout Editor State
  const [isEditorMode, setIsEditorMode] = useState(false);
  const [formLayout, setFormLayout] = useState<FormFieldConfig[]>(DEFAULT_FORM_LAYOUT);

  // Add Custom Field Form state
  const [newCustomLabel, setNewCustomLabel] = useState('');
  const [newCustomType, setNewCustomType] = useState<'text' | 'textarea' | 'url' | 'date'>('text');
  const [showAddCustomField, setShowAddCustomField] = useState(false);

  // Nachrichtenverlauf State
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [newMessageText, setNewMessageText] = useState('');
  const [newSenderType, setNewSenderType] = useState<'user' | 'kontakt'>('user');
  const [channelFilter, setChannelFilter] = useState<'all' | 'linkedin' | 'email' | 'meeting' | 'note'>('all');

  // Tag Autocomplete State
  const [allKnownTags, setAllKnownTags] = useState<string[]>([]);
  const [tagInputText, setTagInputText] = useState('');
  const [showTagSuggestions, setShowTagSuggestions] = useState(false);

  // Clipboard & Drag Image Upload State
  const [pastedImageFile, setPastedImageFile] = useState<File | null>(null);
  const [pastedImagePreviewUrl, setPastedImagePreviewUrl] = useState<string | null>(null);
  const [isDragOverAvatar, setIsDragOverAvatar] = useState(false);

  // Chat scroll ref
  const chatEndRef = useRef<HTMLDivElement>(null);

  // AI Audio Recording & Diktat State
  const [isRecording, setIsRecording] = useState(false);
  const [recordingTime, setRecordingTime] = useState(0);
  const [isProcessingAudio, setIsProcessingAudio] = useState(false);
  const [expandedTranscripts, setExpandedTranscripts] = useState<Record<string, boolean>>({});

  // Notiz-Modal & Editing State
  const [isNoteModalOpen, setIsNoteModalOpen] = useState(false);
  const [noteModalText, setNoteModalText] = useState('');
  const [editingNoteId, setEditingNoteId] = useState<string | null>(null);
  const [editingNoteText, setEditingNoteText] = useState('');
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<any>(null);

  // Segmentierte Aufnahme: alle 10 Minuten wird das Audio automatisch in ein
  // neues Segment geteilt, damit jedes Segment unter dem Groq-Dateilimit bleibt.
  const SEGMENT_DURATION_SEC = 600; // 10 Minuten
  const streamRef = useRef<MediaStream | null>(null);
  const isFinalStopRef = useRef(false);
  const segmentCountRef = useRef(0);
  const accumulatedTranscriptRef = useRef('');
  const [segmentStatus, setSegmentStatus] = useState('');

  // Appointment Customization Dialog Modal State
  const [appointmentDialog, setAppointmentDialog] = useState<{
    isOpen: boolean;
    type: 'crm' | 'google';
    title: string;
    dateTime: string;
    durationMinutes: number;
    location: string;
    notes: string;
    attendees: string;
  }>({
    isOpen: false,
    type: 'crm',
    title: '',
    dateTime: '',
    durationMinutes: 30,
    location: '',
    notes: '',
    attendees: ''
  });

  const formatRecordingTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  };

  const startSegmentRecorder = () => {
    const stream = streamRef.current;
    if (!stream) return;
    segmentCountRef.current += 1;
    audioChunksRef.current = [];
    const mediaRecorder = new MediaRecorder(stream);
    mediaRecorderRef.current = mediaRecorder;

    mediaRecorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        audioChunksRef.current.push(event.data);
      }
    };

    mediaRecorder.onstop = () => {
      const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
      const final = isFinalStopRef.current;
      // Sofort nächstes Segment starten (Aufnahme läuft nahtlos weiter),
      // die Transkription läuft parallel im Hintergrund.
      if (!final) {
        startSegmentRecorder();
      } else if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop());
        streamRef.current = null;
      }
      void transcribeSegment(audioBlob, final);
    };

    mediaRecorder.start();
  };

  const transcribeSegment = async (audioBlob: Blob, final: boolean) => {
    setIsProcessingAudio(true);
    setSegmentStatus(final ? 'Letztes Segment wird verarbeitet...' : `Segment ${segmentCountRef.current} wird transkribiert...`);
    try {
      const apiKey = process.env.NEXT_PUBLIC_GROQ_API_KEY || localStorage.getItem('groq_api_key') || '';
      const transcript = await transcribeAudioOnly(audioBlob, apiKey);
      if (transcript) {
        accumulatedTranscriptRef.current += (accumulatedTranscriptRef.current ? '\n' : '') + transcript;
      }

      if (final) {
        const fullText = accumulatedTranscriptRef.current;
        accumulatedTranscriptRef.current = '';
        if (fullText) {
          const summary = await summarizeText(fullText, apiKey);
          const newMsg: MessageItem = {
            id: Date.now().toString(),
            type: 'meeting',
            sender: 'user',
            text: summary,
            rawTranscript: fullText,
            timestamp: new Date().toISOString()
          };
          setMessages(prev => {
            const updated = [...prev, newMsg];
            setFormData(fd => ({ ...fd, nachrichtenverlauf: updated }));
            return updated;
          });
        }
      }
    } catch (err: any) {
      if (final) {
        alert(`Audio-Verarbeitung fehlgeschlagen: ${err.message || 'Unbekannter Fehler'}`);
      } else {
        console.warn('[Archon CRM] Segment-Transkription fehlgeschlagen (wird übersprungen):', err);
      }
    } finally {
      setIsProcessingAudio(false);
      setSegmentStatus('');
    }
  };

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      isFinalStopRef.current = false;
      segmentCountRef.current = 0;
      accumulatedTranscriptRef.current = '';
      startSegmentRecorder();
      setIsRecording(true);
      setRecordingTime(0);

      timerRef.current = setInterval(() => {
        setRecordingTime(prev => {
          const next = prev + 1;
          // Segment-Wechsel bei 10 Minuten: aktuellen Recorder stoppen
          // (onstop startet automatisch das nächste Segment)
          if (next >= SEGMENT_DURATION_SEC && mediaRecorderRef.current?.state === 'recording') {
            mediaRecorderRef.current.stop();
            return 0;
          }
          return next;
        });
      }, 1000);
    } catch (err: any) {
      alert(`Mikrofon-Zugriff verweigert oder nicht verfügbar: ${err.message || 'Fehler'}`);
    }
  };

  const stopRecording = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    isFinalStopRef.current = true;
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
    setIsRecording(false);
  };

  // Modal Audio Recording State
  const [isModalRecording, setIsModalRecording] = useState(false);
  const [modalRecordingTime, setModalRecordingTime] = useState(0);
  const [isModalProcessingAudio, setIsModalProcessingAudio] = useState(false);
  const modalMediaRecorderRef = useRef<MediaRecorder | null>(null);
  const modalAudioChunksRef = useRef<Blob[]>([]);
  const modalTimerRef = useRef<any>(null);
  const modalStreamRef = useRef<MediaStream | null>(null);
  const modalIsFinalStopRef = useRef(false);
  const modalSegmentCountRef = useRef(0);

  // Aufnahme-Lock: true, sobald irgendeine Aufnahme/Transkription läuft
  // (Audio-Diktat, Notiz-Diktat oder Verarbeitung - im Drawer oder im Panel).
  // Solange aktiv, wird das Schließen des Kontaktfelds blockiert.
  const [panelRecordingActive, setPanelRecordingActive] = useState(false);
  // Vom NachrichtenverlaufPanel registrierte Stopp-Funktion (beendet alle
  // Panel-Aufnahmen: Audio-Diktat, Notiz-Diktat, Meeting-Diktat).
  const panelStopRef = useRef<(() => void) | null>(null);
  // True, solange im Panel eine Aufnahme AKTIV läuft (nicht nur Transkription).
  const [panelActiveRecording, setPanelActiveRecording] = useState(false);
  // Aktuelle Aufnahmezeit aus dem Panel (für die Timer-Anzeige im Overlay).
  const [panelTimerSeconds, setPanelTimerSeconds] = useState(0);
  const isAnyRecordingActive =
    isRecording ||
    isModalRecording ||
    panelActiveRecording ||
    isProcessingAudio ||
    isModalProcessingAudio ||
    panelRecordingActive;

  // Vollbild-Sperre: solange eine Aufnahme/Transkription läuft, darf die Seite
  // weder verlassen noch neu geladen werden (sonst gehen alle Audio-Daten verloren).
  useEffect(() => {
    if (!isAnyRecordingActive) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [isAnyRecordingActive]);

  const startModalSegmentRecorder = () => {
    const stream = modalStreamRef.current;
    if (!stream) return;
    modalSegmentCountRef.current += 1;
    modalAudioChunksRef.current = [];
    const mediaRecorder = new MediaRecorder(stream);
    modalMediaRecorderRef.current = mediaRecorder;

    mediaRecorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        modalAudioChunksRef.current.push(event.data);
      }
    };

    mediaRecorder.onstop = () => {
      const audioBlob = new Blob(modalAudioChunksRef.current, { type: 'audio/webm' });
      const final = modalIsFinalStopRef.current;
      if (!final) {
        startModalSegmentRecorder();
      } else if (modalStreamRef.current) {
        modalStreamRef.current.getTracks().forEach(track => track.stop());
        modalStreamRef.current = null;
      }
      void transcribeModalSegment(audioBlob, final);
    };

    mediaRecorder.start();
  };

  const transcribeModalSegment = async (audioBlob: Blob, final: boolean) => {
    setIsModalProcessingAudio(true);
    try {
      const apiKey = process.env.NEXT_PUBLIC_GROQ_API_KEY || localStorage.getItem('groq_api_key') || '';
      const transcript = await transcribeAudioOnly(audioBlob, apiKey);
      if (transcript) {
        setNoteModalText(prev => prev ? `${prev} ${transcript}` : transcript);
      }
    } catch (err: any) {
      if (final) {
        alert(`Diktat-Transkription fehlgeschlagen: ${err.message || 'Fehler'}`);
      } else {
        console.warn('[Archon CRM] Notiz-Segment-Transkription fehlgeschlagen (übersprungen):', err);
      }
    } finally {
      setIsModalProcessingAudio(false);
    }
  };

  const startModalRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      modalStreamRef.current = stream;
      modalIsFinalStopRef.current = false;
      modalSegmentCountRef.current = 0;
      startModalSegmentRecorder();
      setIsModalRecording(true);
      setModalRecordingTime(0);

      modalTimerRef.current = setInterval(() => {
        setModalRecordingTime(prev => {
          const next = prev + 1;
          if (next >= SEGMENT_DURATION_SEC && modalMediaRecorderRef.current?.state === 'recording') {
            modalMediaRecorderRef.current.stop();
            return 0;
          }
          return next;
        });
      }, 1000);
    } catch (err: any) {
      alert(`Mikrofon-Zugriff verweigert oder nicht verfügbar: ${err.message || 'Fehler'}`);
    }
  };

  const stopModalRecording = () => {
    if (modalTimerRef.current) {
      clearInterval(modalTimerRef.current);
      modalTimerRef.current = null;
    }
    modalIsFinalStopRef.current = true;
    if (modalMediaRecorderRef.current && modalMediaRecorderRef.current.state !== 'inactive') {
      modalMediaRecorderRef.current.stop();
    }
    setIsModalRecording(false);
  };

  // Funktion zum Löschen einer Nachricht aus der Historie (Notizen & Meetings)
  const handleDeleteMessage = (msgId: string) => {
    const updatedMessages = (messages || []).filter((msg: any, idx: number) => {
      const currentId = msg.id || idx.toString();
      return currentId !== msgId;
    });
    setMessages(updatedMessages);
    setFormData(prev => ({
      ...prev,
      nachrichtenverlauf: updatedMessages
    }));
  };

  // Funktion zum Umschalten der Stern-Markierung (Bookmark / Favorit) einer Nachricht
  const handleToggleStarMessage = (msgId: string) => {
    const updatedMessages = (messages || []).map((msg: any, idx: number) => {
      const currentId = msg.id || idx.toString();
      if (currentId === msgId) {
        return { ...msg, isStarred: !msg.isStarred };
      }
      return msg;
    });
    setMessages(updatedMessages);
    setFormData(prev => ({
      ...prev,
      nachrichtenverlauf: updatedMessages
    }));
  };

  const handleStartEditNote = (msg: MessageItem, msgId: string) => {
    setEditingNoteId(msgId);
    setEditingNoteText(msg.text.replace('📌 NOTIZ / NACHTRAG:\n', ''));
  };

  // Funktion zum Speichern einer bearbeiteten Notiz
  const handleSaveEditedNote = (msgId: string) => {
    if (!editingNoteText.trim()) return;
    const updatedMessages = (messages || []).map((msg: any, idx: number) => {
      const currentId = msg.id || idx.toString();
      if (currentId === msgId) {
        return { ...msg, text: editingNoteText.trim() };
      }
      return msg;
    });
    setMessages(updatedMessages);
    setFormData(prev => ({
      ...prev,
      nachrichtenverlauf: updatedMessages
    }));
    setEditingNoteId(null);
    setEditingNoteText('');
  };

  const handleCancelEditNote = () => {
    setEditingNoteId(null);
    setEditingNoteText('');
  };

  const toggleTranscript = (msgId: string) => {
    setExpandedTranscripts(prev => ({
      ...prev,
      [msgId]: !prev[msgId]
    }));
  };

  const handleImageFileSelect = (file: File) => {
    const previewUrl = URL.createObjectURL(file);
    setPastedImageFile(file);
    setPastedImagePreviewUrl(previewUrl);
    setImageError(false);
  };

  const handlePasteFromClipboardApi = async (e?: React.MouseEvent) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    try {
      if (!navigator.clipboard || !navigator.clipboard.read) {
        alert('Tipp: Drücke einfach Strg+V auf deiner Tastatur, um ein Bild aus der Zwischenablage einzufügen.');
        return;
      }
      const items = await navigator.clipboard.read();
      for (const item of items) {
        const imageType = item.types.find(t => t.startsWith('image/'));
        if (imageType) {
          const blob = await item.getType(imageType);
          const file = new File([blob], `pasted_avatar_${Date.now()}.png`, { type: imageType });
          handleImageFileSelect(file);
          return;
        }
      }
      alert('Kein Bild im Zwischenspeicher gefunden. Bitte kopiere zuerst ein Bild.');
    } catch (err: any) {
      alert('Zugriff auf die Zwischenablage verwehrt. Drücke bitte einfach Strg+V auf der Tastatur.');
    }
  };

  const saveLayoutConfig = (newLayout: FormFieldConfig[]) => {
    setFormLayout(newLayout);
    try {
      localStorage.setItem(LOCAL_STORAGE_FORM_LAYOUT_KEY, JSON.stringify(newLayout));
    } catch (e) {
      console.warn('Could not save form layout preferences:', e);
    }
  };

  // 2. ALL USEEFFECTS BEFORE CONDITIONAL RETURN
  // Clear pasted image state when kontakt or drawer state changes
  useEffect(() => {
    setPastedImageFile(null);
    setPastedImagePreviewUrl(null);
  }, [kontakt, isOpen]);

  // Global Clipboard Paste Event Listener (Ctrl+V / Strg+V)
  useEffect(() => {
    if (!isOpen) return;

    const handlePaste = (e: ClipboardEvent) => {
      if (e.clipboardData?.files && e.clipboardData.files.length > 0) {
        for (let i = 0; i < e.clipboardData.files.length; i++) {
          const file = e.clipboardData.files[i];
          if (file && file.type.startsWith('image/')) {
            e.preventDefault();
            e.stopPropagation();
            handleImageFileSelect(file);
            return;
          }
        }
      }

      if (e.clipboardData?.items) {
        for (let i = 0; i < e.clipboardData.items.length; i++) {
          const item = e.clipboardData.items[i];
          if (item && item.type.startsWith('image/')) {
            const file = item.getAsFile();
            if (file) {
              e.preventDefault();
              e.stopPropagation();
              handleImageFileSelect(file);
              return;
            }
          }
        }
      }

      const text = e.clipboardData?.getData('text/plain')?.trim();
      if (text && text.startsWith('data:image/')) {
        e.preventDefault();
        e.stopPropagation();
        fetch(text)
          .then(res => res.blob())
          .then(blob => {
            const file = new File([blob], `pasted_avatar_${Date.now()}.png`, { type: blob.type || 'image/png' });
            handleImageFileSelect(file);
          })
          .catch(err => console.warn('Could not parse pasted base64:', err));
      }
    };

    window.addEventListener('paste', handlePaste, true);
    document.addEventListener('paste', handlePaste, true);

    return () => {
      window.removeEventListener('paste', handlePaste, true);
      document.removeEventListener('paste', handlePaste, true);
    };
  }, [isOpen]);

  // Fetch unique existing tags across database
  useEffect(() => {
    if (isOpen) {
      pb.collection('Kontakte').getFullList({ fields: 'tags' })
        .then(records => {
          const set = new Set<string>();
          records.forEach(r => {
            if (Array.isArray(r.tags)) {
              r.tags.forEach((t: string) => {
                if (t && typeof t === 'string') set.add(t.trim());
              });
            }
          });
          setAllKnownTags(Array.from(set));
        })
        .catch(err => console.warn('Could not fetch existing tags:', err));
    }
  }, [isOpen]);

  // Restore Layout Schema from LocalStorage (Permanent Persistence)
  useEffect(() => {
    try {
      const saved = localStorage.getItem(LOCAL_STORAGE_FORM_LAYOUT_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) {
          // Auto-rename old labels to new ones in saved state
          const mapped = parsed.map((f: FormFieldConfig) => {
            if (f.key === 'vernetzt_am') {
              return { ...f, label: 'Vernetzt seit' };
            }
            if (f.key === 'einladung_zurueckgezogen_am') {
              return { ...f, label: 'Zurückgezogen' };
            }
            return f;
          });
          const existingKeys = new Set(mapped.map((f: FormFieldConfig) => f.key));
          const missingDefaults = DEFAULT_FORM_LAYOUT.filter(df => !existingKeys.has(df.key));
          const merged = [...mapped, ...missingDefaults];
          setFormLayout(merged);
        }
      }
    } catch (e) {
      console.warn('Could not restore form layout preferences:', e);
    }
  }, []);

  // Sync formData and messages when drawer opens or kontakt changes
  useEffect(() => {
    setImageError(false);
    setPastedImageFile(null);
    setPastedImagePreviewUrl('');
    if (kontakt) {
      const normalized = { ...kontakt };
      const websiteVal = (kontakt as any).Webseite || kontakt.webseite || '';
      normalized.webseite = websiteVal;
      (normalized as any).Webseite = websiteVal;
      setFormData(normalized);
      
      if (kontakt.nachrichtenverlauf) {
        try {
          let parsed = typeof kontakt.nachrichtenverlauf === 'string'
            ? JSON.parse(kontakt.nachrichtenverlauf)
            : kontakt.nachrichtenverlauf;

          if (Array.isArray(parsed)) {
            setMessages(parsed);
          } else if (typeof parsed === 'string') {
            setMessages([{ id: '1', sender: 'kontakt', text: parsed, timestamp: new Date().toISOString() }]);
          } else {
            setMessages([]);
          }
        } catch (e) {
          setMessages([{ id: '1', sender: 'kontakt', text: String(kontakt.nachrichtenverlauf), timestamp: new Date().toISOString() }]);
        }
      } else {
        setMessages([]);
      }
    } else {
      setFormData({
        name: '',
        email: '',
        telefon_1: '',
        telefon_2: '',
        linkedin_url: '',
        webseite: '',
        Webseite: '',
        unternehmen: '',
        rolle: '',
        region: '',
        status: 'Unvernetzt',
        rating: 0,
        naechster_schritt: '',
        kommentar: '',
        nachrichtenverlauf: null
      });
      setMessages([]);
    }
    setErrorMsg('');
  }, [kontakt, isOpen]);

  // Auto-scroll to bottom of chat when messages change
  useEffect(() => {
    if (isOpen && chatEndRef.current) {
      chatEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages.length, channelFilter, isOpen]);

  // 3. EARLY RETURN ONLY AFTER ALL HOOKS
  if (!isOpen) return null;

  const isLight = themeMode === 'light';

  const handleClipboardPaste = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    handlePasteFromClipboardApi();
  };

  const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleImageFileSelect(file);
  };

  // Safe Date Formatting
  const getSafeDate = (dateVal: any): string => {
    if (!dateVal) return '';
    const str = String(dateVal).trim();
    if (!str || str === 'undefined' || str === 'null') return '';
    if (/^\d{2}\.\d{2}\.\d{4}/.test(str)) return str;

    const isoCompliant = str.includes(' ') && !str.includes('T') ? str.replace(' ', 'T') : str;
    const d = new Date(isoCompliant);
    return !isNaN(d.getTime()) 
      ? d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
      : (str.toLowerCase().includes('invalid') ? '' : str);
  };
  const formatChatMessageDate = getSafeDate;

  // Robust Message Date Parsing to Epoch Milliseconds for Sorting
  const parseMsgTimeToEpoch = (msg: MessageItem): number => {
    const raw = String(msg.timestamp || msg.date || msg.time || '').trim();
    if (!raw) return 0;
    const deMatch = raw.match(/^(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2}))?/);
    if (deMatch) {
      const [, day, month, year, hour = '00', min = '00'] = deMatch;
      return new Date(Number(year), Number(month) - 1, Number(day), Number(hour), Number(min)).getTime() || 0;
    }
    const isoCompliant = raw.includes(' ') && !raw.includes('T') ? raw.replace(' ', 'T') : raw;
    const parsed = new Date(isoCompliant).getTime();
    return isNaN(parsed) ? 0 : parsed;
  };

  // Sort messages: OLDEST TO NEWEST (Chronologisch von oben nach unten)
  const sortedMessages = [...messages].sort((a, b) => {
    return parseMsgTimeToEpoch(a) - parseMsgTimeToEpoch(b);
  });

  // Filtered Nachrichten basierend auf Kanal-Filter
  const filteredMessages = sortedMessages.filter((msg: any) => {
    if (channelFilter === 'all') return true;
    const type = msg.type || msg.channel || 'linkedin';
    const isNote = type === 'note' || (!!msg.text && (msg.text.includes('NOTIZ') || msg.text.includes('NACHTRAG')));
    if (channelFilter === 'note') return isNote;
    if (isNote) return false;
    return type === channelFilter;
  });



  const handleSendMessage = () => {
    if (!newMessageText.trim()) return;

    const newMsg: MessageItem = {
      id: Date.now().toString(),
      sender: newSenderType,
      text: newMessageText.trim(),
      timestamp: new Date().toISOString(),
      type: channelFilter === 'all' ? 'linkedin' : channelFilter
    };

    const updatedMessages = [...messages, newMsg];
    setMessages(updatedMessages);
    setFormData(prev => ({
      ...prev,
      nachrichtenverlauf: updatedMessages
    }));
    setNewMessageText('');
  };

  const handleSaveNote = () => {
    if (!noteModalText.trim()) return;

    const newNote: MessageItem = {
      id: Date.now().toString(),
      type: 'note',
      sender: 'user',
      text: noteModalText.trim(),
      timestamp: new Date().toISOString()
    };

    const updatedMessages = [...messages, newNote];
    setMessages(updatedMessages);
    setFormData(prev => ({
      ...prev,
      nachrichtenverlauf: updatedMessages
    }));
    setNoteModalText('');
    setIsNoteModalOpen(false);
  };

  // PocketBase Date Sanitizer
  const sanitizeDateForPB = (dVal: any): string => {
    if (!dVal) return '';
    const s = String(dVal).trim();
    if (!s || s === 'undefined' || s === 'null') return '';
    if (/^\d{4}-\d{2}-\d{2}/.test(s)) return s.substring(0, 10);
    const GermanMatch = s.match(/^(\d{2})\.(\d{2})\.(\d{4})/);
    if (GermanMatch) return `${GermanMatch[3]}-${GermanMatch[2]}-${GermanMatch[1]}`;
    const parsed = new Date(s);
    return !isNaN(parsed.getTime()) ? parsed.toISOString().substring(0, 10) : '';
  };

  const getInitialDateTime = () => {
    if (formData.naechster_termin) {
      return String(formData.naechster_termin).substring(0, 16);
    }
    const now = new Date();
    now.setMinutes(0);
    now.setSeconds(0);
    now.setMilliseconds(0);
    const tzOffset = now.getTimezoneOffset() * 60000;
    return (new Date(now.getTime() - tzOffset)).toISOString().substring(0, 16);
  };

  const handleSetFollowUpCrmEvent = () => {
    setAppointmentDialog({
      isOpen: true,
      type: 'crm',
      title: `Nachfassen: ${formData.name || 'Kontakt'}`,
      dateTime: getInitialDateTime(),
      durationMinutes: 30,
      location: 'CRM Follow-up',
      notes: `Automatischer Nachfassen-Termin für ${formData.name || 'Kontakt'}.`,
      attendees: formData.email || ''
    });
  };

  const handleSetGoogleCalendarEvent = () => {
    setAppointmentDialog({
      isOpen: true,
      type: 'google',
      title: `Termin: ${formData.name || 'Kontakt'}`,
      dateTime: getInitialDateTime(),
      durationMinutes: 60,
      location: 'Online',
      notes: `Termin mit ${formData.name || 'Kontakt'} (aus CRM geplant).`,
      attendees: formData.email || ''
    });
  };

  const handleConfirmCreateEvent = async () => {
    const { type, title, dateTime, durationMinutes, location, notes, attendees } = appointmentDialog;
    
    if (!dateTime) {
      alert('Bitte wählen Sie ein Datum und eine Uhrzeit für den Termin aus.');
      return;
    }

    try {
      const startStr = new Date(dateTime).toISOString();
      const endStr = new Date(new Date(dateTime).getTime() + durationMinutes * 60 * 1000).toISOString();
      
      // Update form field to keep in sync
      setFormData(prev => ({ ...prev, naechster_termin: dateTime }));

      if (type === 'crm') {
        await pb.collection('termine').create({
          titel: title,
          start: startStr,
          ende: endStr,
          ort: location,
          notiz: notes,
          kontakt: kontakt?.id || '',
        });
        alert(`CRM Nachfassen-Termin erfolgreich für den ${new Date(dateTime).toLocaleString('de-DE')} angelegt!`);
      } else {
        const attendeeList = attendees ? attendees.split(',').map(e => e.trim()).filter(Boolean) : [];
        const res = await fetch('/api/calendar/events', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: title,
            start: startStr,
            end: endStr,
            location: location,
            description: notes,
            attendees: attendeeList
          })
        });

        const data = await res.json();
        if (data.success) {
          alert(`Google-Kalender-Termin erfolgreich für den ${new Date(dateTime).toLocaleString('de-DE')} eingetragen!`);
        } else {
          console.warn("Google Aggregator write failed, falling back to CRM event representation:", data.error);
          
          await pb.collection('termine').create({
            titel: `${title} (Google Fallback)`,
            start: startStr,
            ende: endStr,
            ort: location,
            notiz: `${notes}\n\nGeplant als Google-Termin (Aggregator Offline: ${data.error || 'nicht erreichbar'}).`,
            kontakt: kontakt?.id || '',
          });

          alert(`Hinweis: Der Google-Kalender-Aggregator ist offline oder nicht autorisiert. Der Termin wurde stattdessen im CRM-Kalender hinterlegt.`);
        }
      }
      
      setAppointmentDialog(prev => ({ ...prev, isOpen: false }));
    } catch (err: any) {
      alert(`Fehler beim Erstellen des Termins: ${err.message || err}`);
    }
  };

  const handleSave = async () => {
    if (!formData.name?.trim()) {
      setErrorMsg('Name ist ein Pflichtfeld.');
      return;
    }
    setSaving(true);
    setErrorMsg('');

    try {
      const formDataObj = new FormData();
      const SYSTEM_KEYS = new Set(['id', 'collectionId', 'collectionName', 'created', 'updated', 'profilbild', 'nachrichtenverlauf', 'expand']);

      // 1. Alle normalen Formular-Felder mit Data Sanitization anhängen
      Object.keys(formData).forEach((key) => {
        if (!SYSTEM_KEYS.has(key)) {
          let val = formData[key];
          
          if (key === 'vernetzt_am' || key === 'einladung_zurueckgezogen_am') {
            val = sanitizeDateForPB(val);
          }
          if (key === 'rating') {
            const parsedRating = parseInt(String(val), 10);
            val = isNaN(parsedRating) ? 0 : parsedRating;
          }

          if (Array.isArray(val) || (typeof val === 'object' && val !== null)) {
            formDataObj.append(key, JSON.stringify(val));
          } else if (val !== null && val !== undefined) {
            formDataObj.append(key, String(val));
          }
        }
      });

      // PocketBase erwartet strikt 'Webseite' mit Großbuchstaben
      const websiteVal = formData.webseite || (formData as any).Webseite || '';
      formDataObj.set('Webseite', String(websiteVal));

      // 2. Chat-Verlauf exakt EINMAL anhängen - VORHER chronologisch aufsteigend
      //    sortieren (älteste zuerst), identisch zur Ordnung des LinkedIn-Import-
      //    Skripts. Verhindert Reihenfolge-Duplikate beim nächsten Import.
      const sortedMessages = [...messages].sort((a: any, b: any) => {
        const ta = a?.timestamp ? new Date(String(a.timestamp).replace(' ', 'T')).getTime() : 0;
        const tb = b?.timestamp ? new Date(String(b.timestamp).replace(' ', 'T')).getTime() : 0;
        const na = isNaN(ta) ? 0 : ta;
        const nb = isNaN(tb) ? 0 : tb;
        return nb - na;  // juengste zuerst
      });
      formDataObj.append('nachrichtenverlauf', JSON.stringify(sortedMessages));

      // 3. Profilbild anhängen (NUR wenn eine NEUE Datei ausgewählt wurde)
      let avatarFile: File | null = pastedImageFile;
      const rawPicVal = pastedImagePreviewUrl || formData.profilbild;
      if (!avatarFile && typeof rawPicVal === 'string' && rawPicVal.startsWith('data:image/')) {
        try {
          const res = await fetch(rawPicVal);
          const blob = await res.blob();
          avatarFile = new File([blob], `avatar_${Date.now()}.png`, { type: blob.type || 'image/png' });
        } catch (e) {
          console.warn('Could not convert base64 avatar to file:', e);
        }
      }

      if (avatarFile instanceof File) {
        formDataObj.append('profilbild', avatarFile);
      }

      // Update in PocketBase ausführen
      let savedRecord: KontaktRecord;
      if (kontakt?.id) {
        savedRecord = await pb.collection('Kontakte').update(kontakt.id, formDataObj) as unknown as KontaktRecord;
      } else {
        savedRecord = await pb.collection('Kontakte').create(formDataObj) as unknown as KontaktRecord;
      }

      onSave(savedRecord);
      onClose();
    } catch (err: any) {
      console.error("PocketBase Save Error:", err);
      const detailMsg = err?.data?.message || err?.message || 'Fehler beim Speichern.';
      setErrorMsg(`Fehler beim Speichern: ${detailMsg}`);
      alert("Fehler beim Speichern: " + detailMsg);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!kontakt?.id) return;
    if (!confirm(`Kontakt "${kontakt.name}" in den Papierkorb verschieben?`)) return;

    try {
      await pb.collection('Kontakte').update(kontakt.id, { deleted_at: new Date().toISOString() });
      onDelete(kontakt.id);
      onClose();
    } catch (err: any) {
      setErrorMsg(err.message || 'Fehler beim Verschieben in den Papierkorb.');
    }
  };

  // Cooldown calculation
  const isGesperrt = formData.status === 'Gesperrt_1Jahr';
  let cooldownDaysLeft: number | null = null;
  if (isGesperrt && formData.einladung_zurueckgezogen_am) {
    const lockDate = new Date(formData.einladung_zurueckgezogen_am);
    const unlockDate = new Date(lockDate.getTime() + 365 * 24 * 60 * 60 * 1000);
    const diffTime = unlockDate.getTime() - new Date().getTime();
    cooldownDaysLeft = Math.max(0, Math.ceil(diffTime / (1000 * 60 * 60 * 24)));
  }

  // Layout Customizer Handlers
  const toggleFieldVisibility = (key: string) => {
    const updated = formLayout.map(f => f.key === key ? { ...f, visible: !f.visible } : f);
    saveLayoutConfig(updated);
  };

  const setFieldWidth = (key: string, width: FieldWidth) => {
    const updated = formLayout.map(f => f.key === key ? { ...f, width } : f);
    saveLayoutConfig(updated);
  };

  const moveFieldOrder = (key: string, direction: 'up' | 'down') => {
    const list = [...formLayout].sort((a, b) => a.order - b.order);
    const idx = list.findIndex(f => f.key === key);
    if (idx < 0) return;
    const targetIdx = direction === 'up' ? idx - 1 : idx + 1;
    if (targetIdx < 0 || targetIdx >= list.length) return;

    // Physically swap the items in the array
    const temp = list[idx];
    list[idx] = list[targetIdx];
    list[targetIdx] = temp;

    // Re-assign order numbers sequentially
    const updated = list.map((item, index) => ({
      ...item,
      order: index + 1
    }));

    saveLayoutConfig(updated);
  };

  const handleAddCustomField = () => {
    if (!newCustomLabel.trim()) return;
    const key = `custom_${newCustomLabel.trim().toLowerCase().replace(/\s+/g, '_')}`;
    const newField: FormFieldConfig = {
      key,
      label: newCustomLabel.trim(),
      type: newCustomType,
      width: 'half',
      visible: true,
      order: formLayout.length + 1,
      isCustom: true
    };
    saveLayoutConfig([...formLayout, newField]);
    setNewCustomLabel('');
    setShowAddCustomField(false);
  };

  const handleRemoveCustomField = (key: string) => {
    saveLayoutConfig(formLayout.filter(f => f.key !== key));
  };

  const resetDefaultLayout = () => {
    saveLayoutConfig(DEFAULT_FORM_LAYOUT);
  };

  // Render individual form field based on schema type
  const renderDynamicField = (field: FormFieldConfig) => {
    const val = formData[field.key] || '';

    switch (field.type) {
      case 'profilbild_preview':
        const avatarDisplayUrl = pastedImagePreviewUrl || getProfilbildUrl(formData);
        return (
          <div className="flex flex-col items-center justify-center pt-1">
            <label
              onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setIsDragOverAvatar(true); }}
              onDragEnter={(e) => { e.preventDefault(); e.stopPropagation(); setIsDragOverAvatar(true); }}
              onDragLeave={(e) => { e.preventDefault(); e.stopPropagation(); setIsDragOverAvatar(false); }}
              onDrop={(e) => {
                e.preventDefault();
                e.stopPropagation();
                setIsDragOverAvatar(false);
                const file = e.dataTransfer.files?.[0];
                if (file && file.type.startsWith('image/')) {
                  handleImageFileSelect(file);
                }
              }}
              className={`w-[145px] h-[145px] rounded-xl border-2 overflow-hidden flex flex-col items-center justify-center shadow-md shrink-0 transition relative cursor-pointer group ${
                isDragOverAvatar
                  ? 'border-emerald-500 bg-emerald-500/10'
                  : isLight ? 'bg-slate-100 border-slate-300 hover:border-emerald-500' : 'bg-slate-950 border-slate-800 hover:border-emerald-500/60'
              }`}
              title="Klicken zum Auswählen, Bild hierher ziehen oder Strg+V drücken"
            >
              <input
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleImageFileSelect(file);
                }}
              />

              {avatarDisplayUrl && !imageError ? (
                <img
                  src={avatarDisplayUrl}
                  alt={formData.name || 'Vorschau'}
                  onError={() => setImageError(true)}
                  className="w-full h-full object-cover"
                />
              ) : (
                <div className="flex flex-col items-center gap-1.5 text-center p-2">
                  <div className="text-2xl font-mono font-bold text-slate-400">
                    {formData.name ? formData.name.substring(0, 2).toUpperCase() : 'MA'}
                  </div>
                  <span className="text-[9px] font-mono text-emerald-600 font-bold bg-emerald-500/10 border border-emerald-500/30 px-1.5 py-0.5 rounded">
                    📋 Strg+V zum Einfügen
                  </span>
                </div>
              )}

              <div className="absolute inset-0 bg-black/70 opacity-0 group-hover:opacity-100 transition flex flex-col items-center justify-center text-white text-[10px] font-mono p-2 text-center gap-1">
                <Upload className="w-5 h-5 text-emerald-400" />
                <span className="font-bold">Bild einfügen (Strg+V)</span>
                <span className="text-[9px] text-slate-300">oder Datei wählen</span>
              </div>
            </label>

            {pastedImagePreviewUrl && (
              <span className="mt-1 text-[10px] font-mono text-emerald-600 font-bold flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3" /> Aus Zwischenspeicher geladen
              </span>
            )}
          </div>
        );

      case 'text':
        return (
          <div>
            <label className={`block text-xs font-bold uppercase tracking-wider mb-1.5 ${
              isLight ? 'text-slate-700' : 'text-slate-300'
            }`}>
              {field.label}
            </label>
            <input
              type="text"
              value={val}
              onChange={(e) => setFormData({ ...formData, [field.key]: e.target.value })}
              placeholder={field.placeholder}
              className={`w-full px-3 py-2 border rounded-lg text-sm transition outline-none ${
                isLight ? 'bg-slate-50 border-slate-300 text-slate-900 focus:border-emerald-500' : 'bg-slate-950 border-slate-800 text-slate-100 focus:border-emerald-500/60'
              }`}
            />
          </div>
        );

      case 'email':
        const mailtoVal = String(val || '').trim();
        return (
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className={`block text-xs font-bold uppercase tracking-wider ${
                isLight ? 'text-slate-700' : 'text-slate-300'
              }`}>
                {field.label}
              </label>
              {mailtoVal && (
                <a
                  href={`mailto:${mailtoVal}`}
                  className="text-xs font-bold text-emerald-600 dark:text-emerald-400 hover:underline flex items-center gap-1 cursor-pointer"
                  title="E-Mail in Mail-App öffnen"
                >
                  <Mail className="w-3.5 h-3.5" />
                  <span>Mail schreiben</span>
                </a>
              )}
            </div>
            <div className="relative">
              <Mail className="w-4 h-4 absolute left-3 top-3 text-slate-400" />
              <input
                type="email"
                value={val}
                onChange={(e) => setFormData({ ...formData, [field.key]: e.target.value })}
                placeholder={field.placeholder || 'name@firma.de'}
                className={`w-full pl-9 pr-3 py-2 border rounded-lg text-sm transition outline-none ${
                  isLight ? 'bg-slate-50 border-slate-300 text-slate-900 focus:border-emerald-500' : 'bg-slate-950 border-slate-800 text-slate-100 focus:border-emerald-500/60'
                }`}
              />
            </div>
          </div>
        );

      case 'url':
        if (field.key === 'profilbild') {
          return (
            <div>
              <label className={`block text-xs font-bold uppercase tracking-wider mb-1.5 ${
                isLight ? 'text-slate-700' : 'text-slate-300'
              }`}>
                {field.label}
              </label>

              <div className="relative mb-2">
                <ImageIcon className="w-4 h-4 absolute left-3 top-3 text-slate-400" />
                <input
                  type="text"
                  value={val}
                  onChange={(e) => {
                    setFormData({ ...formData, profilbild: e.target.value });
                    setImageError(false);
                  }}
                  placeholder={field.placeholder}
                  className={`w-full pl-9 pr-3 py-2 border rounded-lg text-sm transition outline-none ${
                    isLight ? 'bg-slate-50 border-slate-300 text-slate-900 focus:border-emerald-500' : 'bg-slate-950 border-slate-800 text-slate-100 focus:border-emerald-500/60'
                  }`}
                />
              </div>

              <div className="flex gap-2 mt-2">
                <button 
                  type="button" 
                  onClick={handleClipboardPaste} 
                  className="bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-medium px-3 py-2 rounded-md flex items-center gap-1.5 shadow-sm cursor-pointer"
                >
                  📋 Aus Zwischenablage (Strg+V)
                </button>
                <label className="bg-slate-700 hover:bg-slate-800 text-white text-xs font-medium px-3 py-2 rounded-md cursor-pointer flex items-center gap-1.5 shadow-sm">
                  📁 Datei wählen
                  <input type="file" accept="image/*" onChange={handleImageUpload} className="hidden" />
                </label>
              </div>
            </div>
          );
        }

        const urlVal = String(val || '').trim();
        const formattedUrl = urlVal
          ? (urlVal.startsWith('http://') || urlVal.startsWith('https://') ? urlVal : `https://${urlVal}`)
          : '';

        return (
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className={`block text-xs font-bold uppercase tracking-wider ${
                isLight ? 'text-slate-700' : 'text-slate-300'
              }`}>
                {field.label}
              </label>
              {formattedUrl && (
                <a
                  href={formattedUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  className="text-xs font-bold text-emerald-600 dark:text-emerald-400 hover:underline flex items-center gap-1 cursor-pointer"
                  title="Link in neuem Tab öffnen"
                >
                  <Link2 className="w-3.5 h-3.5" />
                  <span>Öffnen</span>
                </a>
              )}
            </div>
            <div className="relative flex items-center">
              <Link2 className="w-4 h-4 absolute left-3 text-slate-400" />
              <input
                type="url"
                value={val}
                onChange={(e) => setFormData({ ...formData, [field.key]: e.target.value })}
                placeholder={field.placeholder || 'https://...'}
                className={`w-full pl-9 pr-3 py-2 border rounded-lg text-sm transition outline-none ${
                  isLight ? 'bg-slate-50 border-slate-300 text-slate-900 focus:border-emerald-500' : 'bg-slate-950 border-slate-800 text-slate-100 focus:border-emerald-500/60'
                }`}
              />
            </div>
          </div>
        );

      case 'tel':
        return (
          <div>
            <label className={`block text-xs font-bold uppercase tracking-wider mb-1.5 ${
              isLight ? 'text-slate-700' : 'text-slate-300'
            }`}>
              {field.label}
            </label>
            <div className="relative">
              <Phone className="w-4 h-4 absolute left-3 top-3 text-slate-400" />
              <input
                type="tel"
                value={val}
                onChange={(e) => setFormData({ ...formData, [field.key]: e.target.value })}
                placeholder={field.placeholder || '+49...'}
                className={`w-full pl-9 pr-3 py-2 border rounded-lg text-sm transition outline-none ${
                  isLight ? 'bg-slate-50 border-slate-300 text-slate-900 focus:border-emerald-500' : 'bg-slate-950 border-slate-800 text-slate-100 focus:border-emerald-500/60'
                }`}
              />
            </div>
          </div>
        );

      case 'select':
        return (
          <div>
            <label className={`block text-xs font-bold uppercase tracking-wider mb-1.5 ${
              isLight ? 'text-slate-700' : 'text-slate-300'
            }`}>
              {field.label}
            </label>
            <select
              value={val || 'Vernetzt'}
              onChange={(e) => setFormData({ ...formData, [field.key]: e.target.value })}
              className={`w-full px-3 py-2 border rounded-lg text-sm transition outline-none ${
                isLight ? 'bg-slate-50 border-slate-300 text-slate-900 focus:border-emerald-500' : 'bg-slate-950 border-slate-800 text-slate-100 focus:border-emerald-500/60'
              }`}
            >
              {field.key === 'status' ? STATUS_COLUMNS.map((col) => (
                <option key={col.id} value={col.id}>
                  {col.icon} {col.title}
                </option>
              )) : ROLLEN_OPTIONEN.map((o) => (
                <option key={o} value={o}>{o}</option>
              ))}
            </select>
          </div>
        );

      case 'rating':
        const currentRating = Number(formData.rating || 0);
        return (
          <div className="flex items-center gap-1.5 py-1">
            {[1, 2, 3, 4, 5].map((star) => (
              <button
                key={star}
                type="button"
                onClick={() => setFormData({ ...formData, rating: currentRating === star ? 0 : star })}
                className="p-1 hover:scale-125 transition cursor-pointer outline-none"
                title={`${star} Stern${star > 1 ? 'e' : ''}`}
              >
                <Star
                  className={`w-6 h-6 ${
                    currentRating >= star
                      ? 'fill-amber-400 text-amber-500 drop-shadow-xs'
                      : isLight ? 'text-slate-300 hover:text-amber-300' : 'text-slate-700 hover:text-amber-500/50'
                  }`}
                />
              </button>
            ))}
          </div>
        );

      case 'date':
        return (
          <div>
            <label className={`block text-xs font-bold uppercase tracking-wider mb-1.5 ${
              isLight ? 'text-slate-600' : 'text-slate-400'
            }`}>
              {field.label}
            </label>
            <input
              type="date"
              value={val ? String(val).substring(0, 10) : ''}
              onChange={(e) => setFormData({ ...formData, [field.key]: e.target.value })}
              className={`w-full px-3 py-2 border rounded-lg text-xs transition outline-none ${
                isLight ? 'bg-slate-50 border-slate-300 text-slate-900' : 'bg-slate-950 border-slate-800 text-slate-300'
              }`}
            />
          </div>
        );

      case 'datetime-local':
        return (
          <div>
            <label className={`block text-xs font-bold uppercase tracking-wider mb-1.5 ${
              isLight ? 'text-slate-600' : 'text-slate-400'
            }`}>
              {field.label}
            </label>
            <input
              type="datetime-local"
              value={val ? String(val).substring(0, 16) : ''}
              onChange={(e) => setFormData({ ...formData, [field.key]: e.target.value })}
              className={`w-full px-3 py-2 border rounded-lg text-xs transition outline-none ${
                isLight ? 'bg-slate-50 border-slate-300 text-slate-900' : 'bg-slate-950 border-slate-800 text-slate-300'
              }`}
            />
          </div>
        );

      case 'tags':
        const currentTags: string[] = Array.isArray(formData.tags) ? formData.tags : [];
        const filteredSuggestions = allKnownTags.filter(
          t => !currentTags.includes(t) && t.toLowerCase().includes(tagInputText.toLowerCase().trim())
        );

        const addTag = (rawTag: string) => {
          const cleaned = rawTag.replace(/,/g, '').trim();
          if (!cleaned) return;
          if (currentTags.includes(cleaned)) {
            setTagInputText('');
            return;
          }
          const updated = [...currentTags, cleaned];
          setFormData(prev => ({ ...prev, tags: updated }));
          setTagInputText('');
          setShowTagSuggestions(false);
        };

        const removeTag = (tagToRemove: string) => {
          const updated = currentTags.filter(t => t !== tagToRemove);
          setFormData(prev => ({ ...prev, tags: updated }));
        };

        return (
          <div>
            <label className={`block text-xs font-bold uppercase tracking-wider mb-1.5 ${
              isLight ? 'text-slate-700' : 'text-slate-300'
            }`}>
              {field.label}
            </label>

            <div className={`p-2 border rounded-lg transition min-h-[42px] flex flex-wrap items-center gap-1.5 relative ${
              isLight ? 'bg-slate-50 border-slate-300 text-slate-900 focus-within:border-emerald-500' : 'bg-slate-950 border-slate-800 text-slate-100 focus-within:border-emerald-500/60'
            }`}>
              {currentTags.map((tag) => {
                const prefix = typeof window !== 'undefined' ? (localStorage.getItem('archon_theme_var_--contact-tag-prefix') ?? '🏷️') : '🏷️';
                return (
                  <span
                    key={tag}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-mono font-bold border shrink-0"
                    style={{
                      backgroundColor: 'var(--contact-tag-bg, var(--accent-light, #ecfdf5))',
                      color: 'var(--contact-tag-text, var(--accent-main, #047857))',
                      borderColor: 'var(--contact-tag-border, var(--accent-light, #a7f3d0))'
                    }}
                  >
                    <span>{prefix ? prefix + ' ' : ''}{tag}</span>
                    <button
                      type="button"
                      onClick={() => removeTag(tag)}
                      className="hover:text-rose-500 transition p-0.5"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                );
              })}

              <div className="relative flex-1 min-w-[140px]">
                <input
                  type="text"
                  value={tagInputText}
                  onChange={(e) => {
                    const val = e.target.value;
                    if (val.includes(',')) {
                      addTag(val);
                    } else {
                      setTagInputText(val);
                      setShowTagSuggestions(true);
                    }
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      addTag(tagInputText);
                    }
                  }}
                  onFocus={() => setShowTagSuggestions(true)}
                  placeholder={currentTags.length === 0 ? "Tag eingeben & Enter drücken..." : "+ Tag..."}
                  className="w-full bg-transparent border-none outline-none text-xs font-mono py-1 px-1"
                />

                {showTagSuggestions && tagInputText.trim().length > 0 && filteredSuggestions.length > 0 && (
                  <div className={`absolute left-0 top-full mt-1 w-full max-h-40 overflow-y-auto rounded-lg border shadow-xl z-50 font-mono text-xs ${
                    isLight ? 'bg-white border-slate-200 text-slate-800' : 'bg-slate-900 border-slate-800 text-slate-100'
                  }`}>
                    <div className="p-1 text-[10px] uppercase font-bold text-slate-400 border-b border-slate-200 dark:border-slate-800 px-2 py-1">
                      Existierende Tags Vorschläge:
                    </div>
                    {filteredSuggestions.map((suggestion) => (
                      <button
                        key={suggestion}
                        type="button"
                        onClick={() => addTag(suggestion)}
                        className="w-full text-left px-3 py-1.5 hover:bg-emerald-500/10 hover:text-emerald-600 transition flex items-center gap-1.5"
                      >
                        <Tag className="w-3 h-3 text-emerald-500" />
                        <span>{suggestion}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        );

      case 'textarea':
        return (
          <div>
            <label className={`block text-xs font-bold uppercase tracking-wider mb-1.5 ${
              isLight ? 'text-slate-700' : 'text-slate-300'
            }`}>
              {field.label}
            </label>
            <textarea
              rows={4}
              value={val}
              onChange={(e) => setFormData({ ...formData, [field.key]: e.target.value })}
              placeholder={field.placeholder}
              className={`w-full p-3 border rounded-lg text-xs font-mono transition leading-relaxed outline-none ${
                isLight ? 'bg-slate-50 border-slate-300 text-slate-900' : 'bg-slate-950 border-slate-800 text-slate-200'
              }`}
            />
          </div>
        );

      default:
        return null;
    }
  };

  const sortedActiveFields = [...formLayout]
    .filter(f => f.visible)
    .sort((a, b) => a.order - b.order);

  return (
    <>
    <div
      onClick={() => {
        // Während Aufnahme/Transkription NICHT schließen (Aufnahme schützen)
        if (!isAnyRecordingActive) {
          onClose();
        }
      }}
      data-theme={themeMode}
      className={`fixed inset-0 z-[999] flex items-stretch justify-center bg-black/70 px-4 md:px-8 font-sans backdrop-blur-sm overflow-hidden py-0 ${themeMode}`}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        id="contact-drawer-window"
        className={`w-full max-w-[1350px] h-screen max-h-screen border-x flex flex-col overflow-hidden shadow-2xl relative contact-drawer-container ${
          isLight ? 'bg-white border-slate-200 text-slate-900' : 'bg-slate-900 border-slate-800 text-slate-100'
        }`}
      >
        
        {/* HEADER */}
        <div
          id="contact-drawer-header"
          style={{ height: '72px', maxHeight: '72px', minHeight: '72px', flexShrink: 0, flexGrow: 0 }}
          className={`px-4 py-2 border-b flex-shrink-0 flex justify-between items-center ${
            isLight ? 'bg-slate-50 border-slate-200' : 'bg-slate-800/50 border-slate-800'
          }`}
        >
          <div
            style={{ height: '100%', maxHeight: '72px', display: 'flex', alignItems: 'center' }}
            className="flex items-center gap-4 h-full"
          >
            
            {(pastedImagePreviewUrl || getProfilbildUrl(formData)) && !imageError ? (
              <div className="w-12 h-12 rounded-full overflow-hidden border-2 border-emerald-500/40 shadow-sm shrink-0">
                <img
                  src={pastedImagePreviewUrl || getProfilbildUrl(formData)!}
                  alt={formData.name || 'Profilbild'}
                  onError={() => setImageError(true)}
                  className="w-full h-full object-cover"
                />
              </div>
            ) : (
              <div className="w-12 h-12 rounded-full bg-emerald-500/10 border-2 border-emerald-500/30 flex items-center justify-center text-emerald-600 font-bold font-mono text-lg shrink-0 shadow-sm">
                {formData.name ? formData.name.substring(0, 2).toUpperCase() : '??'}
              </div>
            )}

            <div>
              <div className="flex items-center gap-3">
                <h2 className={`text-xl font-bold tracking-tight ${isLight ? 'text-slate-900' : 'text-slate-100'}`}>
                  {formData.name || (kontakt?.id ? 'Kontakt bearbeiten' : 'Neuer Kontakt')}
                </h2>
                {(formData.name || kontakt?.name) && (
                  <a
                    href={`https://www.google.com/search?q=${encodeURIComponent(formData.name || kontakt?.name || '')}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="p-1 rounded-full text-slate-400 hover:text-accent-main hover:bg-slate-200 dark:hover:bg-slate-700 transition cursor-pointer"
                    title="Auf Google suchen"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Search className="w-4 h-4" />
                  </a>
                )}
              </div>

              <p className={`text-xs font-mono mt-0.5 ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>
                {kontakt?.id ? `ID: ${kontakt.id}` : 'PocketBase Collection: kontakte'}
              </p>
            </div>

          </div>

          <div className="flex items-center gap-2">
            {isAnyRecordingActive && (
              <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold animate-pulse ${
                isLight ? 'bg-rose-100 text-rose-700 border border-rose-300' : 'bg-rose-950/60 text-rose-300 border border-rose-900/60'
              }`}>
                <span className="w-2 h-2 rounded-full bg-rose-500 animate-pulse" />
                <span>🔴 Aufnahme läuft — Schließen gesperrt</span>
              </div>
            )}
            <button
              type="button"
              onClick={() => {
                if (isAnyRecordingActive) {
                  // Aufnahme schützen: kein Schließen, nur Hinweis
                  return;
                }
                onClose();
              }}
              title={isAnyRecordingActive ? 'Aufnahme läuft — erst stoppen, dann schließen' : 'Schließen'}
              className={`p-2 rounded-lg transition cursor-pointer ${
                isLight
                  ? isAnyRecordingActive
                    ? 'text-rose-500 hover:text-rose-700 hover:bg-rose-100'
                    : 'text-slate-500 hover:text-slate-900 hover:bg-slate-200'
                  : isAnyRecordingActive
                    ? 'text-rose-400 hover:text-rose-300 hover:bg-rose-900/40'
                    : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800'
              }`}
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* BODY: FLEXBOX STATT GRID (Garantierte Höhenübertragung) */}
        <div className="flex-1 min-h-0 flex flex-row gap-6 p-6 overflow-hidden">

          {/* LINKE SPALTE: FORMULAR (50% Breite, eigenständig scrollbar) */}
          <div className="w-1/2 h-full min-h-0 min-w-0 overflow-y-auto pr-3 space-y-4">

            {errorMsg && (
              <div className="p-3.5 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0 text-rose-600" />
                <span>{errorMsg}</span>
              </div>
            )}

            {isGesperrt && (
              <div className={`p-4 rounded-xl border space-y-1 ${
                isLight ? 'bg-rose-50 border-rose-200 text-rose-900' : 'bg-rose-950/40 border-rose-900/60 text-rose-200'
              }`}>
                <div className="flex items-center gap-2 font-medium text-sm text-rose-700">
                  <AlertTriangle className="w-4 h-4 text-rose-600" />
                  <span>1-Jahres Cooldown Aktiv</span>
                </div>
                <p className="text-xs text-rose-700">
                  Zurückgezogen am:{' '}
                  <span className="font-mono font-bold">
                    {formData.einladung_zurueckgezogen_am
                      ? new Date(formData.einladung_zurueckgezogen_am).toLocaleDateString('de-DE')
                      : 'Heute (wird automatisch gesetzt)'}
                  </span>
                </p>
                {cooldownDaysLeft !== null && (
                  <div className="mt-2 inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-rose-200 text-rose-900 text-xs font-mono">
                    <span>⏳ Verbleibend:</span>
                    <span className="font-bold">{cooldownDaysLeft} Tage</span>
                  </div>
                )}
              </div>
            )}

            {isEditorMode ? (
              <div className="space-y-4 animate-in fade-in duration-150 font-mono text-xs">
                <div className="flex items-center justify-between pb-2 border-b border-slate-200 dark:border-slate-800">
                  <div>
                    <h3 className="font-bold text-sm font-sans text-emerald-600 flex items-center gap-2">
                      <SlidersHorizontal className="w-4 h-4" />
                      <span>Formular-Editor & Layout Customizer</span>
                    </h3>
                    <p className="text-[11px] text-slate-400 font-sans">
                      Stelle Sichtbarkeit, Reihenfolge und Breite (50% / 100%) für dein persönliches Formular-Design ein.
                    </p>
                  </div>

                  <button
                    onClick={resetDefaultLayout}
                    className="px-2.5 py-1 rounded bg-slate-200 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:text-emerald-600 text-[11px] flex items-center gap-1 font-bold transition"
                  >
                    <RotateCcw className="w-3 h-3" />
                    <span>Reset</span>
                  </button>
                </div>

                <div className="pt-1">
                  {!showAddCustomField ? (
                    <button
                      onClick={() => setShowAddCustomField(true)}
                      className="w-full py-2 border border-dashed rounded-lg text-emerald-600 hover:bg-emerald-500/10 font-bold transition flex items-center justify-center gap-1.5"
                    >
                      <Plus className="w-4 h-4" />
                      <span>+ Custom-Feld hinzufügen</span>
                    </button>
                  ) : (
                    <div className={`p-3 rounded-xl border space-y-2 ${
                      isLight ? 'bg-emerald-50/60 border-emerald-300' : 'bg-emerald-950/20 border-emerald-900'
                    }`}>
                      <p className="font-bold text-emerald-600 font-sans">Neues Custom-Feld anlegen</p>
                      <div className="flex gap-2">
                        <input
                          type="text"
                          placeholder="Feldbezeichnung (z. B. Skypename)..."
                          value={newCustomLabel}
                          onChange={(e) => setNewCustomLabel(e.target.value)}
                          className={`flex-1 p-2 border rounded font-mono text-xs ${
                            isLight ? 'bg-white border-slate-300' : 'bg-slate-900 border-slate-800'
                          }`}
                        />
                        <select
                          value={newCustomType}
                          onChange={(e) => setNewCustomType(e.target.value as any)}
                          className={`p-2 border rounded font-mono text-xs ${
                            isLight ? 'bg-white border-slate-300' : 'bg-slate-900 border-slate-800'
                          }`}
                        >
                          <option value="text">Text</option>
                          <option value="textarea">Mehrzeilig</option>
                          <option value="url">URL</option>
                          <option value="date">Datum</option>
                        </select>
                        <button
                          onClick={handleAddCustomField}
                          className="px-3 py-1 rounded bg-emerald-600 text-white font-bold text-xs"
                        >
                          Hinzufügen
                        </button>
                      </div>
                    </div>
                  )}
                </div>

                <div className="space-y-1.5 max-h-[50vh] overflow-y-auto pr-1">
                  {[...formLayout]
                    .sort((a, b) => a.order - b.order)
                    .map((field) => (
                      <div
                        key={field.key}
                        className={`flex items-center justify-between p-2.5 rounded-lg border transition ${
                          field.visible
                            ? isLight ? 'bg-white border-slate-200' : 'bg-slate-950 border-slate-800'
                            : isLight ? 'bg-slate-100/60 border-slate-200/50 text-slate-400' : 'bg-slate-950/30 border-slate-900 text-slate-600'
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          <button
                            type="button"
                            onClick={() => toggleFieldVisibility(field.key)}
                            className="p-1 text-slate-400 hover:text-emerald-600 transition"
                          >
                            {field.visible ? (
                              <Eye className="w-4 h-4 text-emerald-600" />
                            ) : (
                              <EyeOff className="w-4 h-4 text-slate-400" />
                            )}
                          </button>
                          <span className={`font-bold font-sans ${field.visible ? '' : 'line-through'}`}>
                            {field.label}
                          </span>
                          <span className="text-[10px] text-slate-400 border px-1 rounded bg-slate-100 dark:bg-slate-800">
                            {field.type}
                          </span>
                        </div>

                        <div className="flex items-center gap-2">
                          <div className={`flex items-center p-0.5 rounded-md border text-[10px] font-bold ${
                            isLight ? 'bg-slate-100 border-slate-300' : 'bg-slate-900 border-slate-800'
                          }`}>
                            {([
                              { id: 'third', label: '1/3' },
                              { id: 'half', label: '1/2' },
                              { id: 'two-thirds', label: '2/3' },
                              { id: 'full', label: '100%' }
                            ] as const).map((opt) => (
                              <button
                                key={opt.id}
                                type="button"
                                onClick={() => setFieldWidth(field.key, opt.id)}
                                className={`px-1.5 py-0.5 rounded transition ${
                                  (field.width || 'full') === opt.id
                                    ? 'bg-emerald-600 text-white font-extrabold shadow-2xs'
                                    : 'text-slate-400 hover:text-slate-200'
                                }`}
                              >
                                {opt.label}
                              </button>
                            ))}
                          </div>

                          <div className="flex items-center gap-0.5">
                            <button
                              type="button"
                              onClick={() => moveFieldOrder(field.key, 'up')}
                              className="p-1 hover:bg-slate-200 dark:hover:bg-slate-800 rounded text-slate-400"
                            >
                              <ArrowUp className="w-3.5 h-3.5" />
                            </button>
                            <button
                              type="button"
                              onClick={() => moveFieldOrder(field.key, 'down')}
                              className="p-1 hover:bg-slate-200 dark:hover:bg-slate-800 rounded text-slate-400"
                            >
                              <ArrowDown className="w-3.5 h-3.5" />
                            </button>
                          </div>

                          {field.isCustom && (
                            <button
                              type="button"
                              onClick={() => handleRemoveCustomField(field.key)}
                              className="p-1 text-rose-500 hover:bg-rose-500/10 rounded"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="grid grid-cols-12 gap-4 items-start pb-2">
                  <div className="col-span-8 space-y-4">
                    {sortedActiveFields.find(f => f.key === 'name') &&
                      renderDynamicField(sortedActiveFields.find(f => f.key === 'name')!)}
                    {sortedActiveFields.find(f => f.key === 'unternehmen') &&
                      renderDynamicField(sortedActiveFields.find(f => f.key === 'unternehmen')!)}
                    {sortedActiveFields.find(f => f.key === 'rolle') &&
                      renderDynamicField(sortedActiveFields.find(f => f.key === 'rolle')!)}
                  </div>

                  <div className="col-span-4 flex flex-col items-center justify-between h-full pt-1 space-y-4">
                    {sortedActiveFields.find(f => f.key === 'profilbild_preview') &&
                      renderDynamicField(sortedActiveFields.find(f => f.key === 'profilbild_preview')!)}
                    {sortedActiveFields.find(f => f.key === 'rating') &&
                      renderDynamicField(sortedActiveFields.find(f => f.key === 'rating')!)}
                  </div>
                </div>

                <div className="grid grid-cols-12 gap-4">
                  {sortedActiveFields
                    .filter(f => !['name', 'unternehmen', 'rolle', 'profilbild_preview', 'rating'].includes(f.key))
                    .map((field) => (
                      <div
                        key={field.key}
                        className={getFieldWidthClass(field)}
                      >
                        {renderDynamicField(field)}
                      </div>
                    ))}
                </div>
              </div>
            )}

          </div>

          {/* RECHTE SPALTE: CHAT (50% Breite, eigenständig scrollbar) */}
          <div className="w-1/2 h-full min-h-0 min-w-0 flex flex-col border-l border-slate-200 dark:border-slate-800 pl-6 overflow-hidden">
            <NachrichtenverlaufPanel
              kontakt={kontakt}
              onUpdate={(updatedRecord) => {
                setFormData(prev => ({
                  ...prev,
                  nachrichtenverlauf: updatedRecord.nachrichtenverlauf
                }));
                if (onSave) {
                  onSave(updatedRecord);
                }
              }}
              themeMode={themeMode}
              onRecordingStateChange={setPanelRecordingActive}
              registerPanelStopHandler={(fn) => { panelStopRef.current = fn; }}
              onPanelRecordingChange={setPanelActiveRecording}
              onPanelTimeChange={setPanelTimerSeconds}
            />
          </div>

            </div>

            {/* FOOTER */}
            <div className={`p-4 border-t flex-shrink-0 flex justify-between items-center ${
              isLight ? 'bg-slate-50 border-slate-200' : 'bg-slate-800/50 border-slate-800'
            }`}>
              <div className="flex items-center gap-1.5">
                {kontakt?.id && (
                  <button
                    type="button"
                    onClick={handleDelete}
                    className="p-2 rounded-xl text-rose-500 hover:text-rose-700 hover:bg-rose-500/10 transition cursor-pointer"
                    title="Kontakt löschen"
                  >
                    <Trash2 className="w-[22px] h-[22px]" />
                  </button>
                )}

                <button
                  type="button"
                  onClick={() => setFormData(prev => ({ ...prev, rating: 0 }))}
                  className="p-2 rounded-xl text-amber-500 hover:text-amber-600 hover:bg-amber-500/10 transition cursor-pointer"
                  title="Sterne-Bewertung auf 0 zurücksetzen"
                >
                  <RotateCcw className="w-[22px] h-[22px]" />
                </button>

                <button
                  type="button"
                  onClick={() => setIsEditorMode(!isEditorMode)}
                  className={`p-2 rounded-xl text-emerald-600 hover:text-emerald-700 transition cursor-pointer ${
                    isEditorMode
                      ? 'bg-emerald-500/20 text-emerald-700 font-bold'
                      : 'hover:bg-emerald-500/10'
                  }`}
                  title={isEditorMode ? 'Editor beenden' : 'Formular-Felder anpassen'}
                >
                  <SlidersHorizontal className="w-[22px] h-[22px]" />
                </button>
              </div>

              {/* Middle Actions: Appointment Scheduling */}
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleSetFollowUpCrmEvent}
                  className={`px-3 py-1.5 rounded-lg border text-[11px] font-bold transition cursor-pointer flex items-center gap-1.5 ${
                    isLight
                      ? 'border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100'
                      : 'border-emerald-900/60 bg-emerald-950/40 text-emerald-400 hover:bg-emerald-900/40'
                  }`}
                  title="Grünen CRM-Termin zum Nachfassen planen"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="w-3.5 h-3.5"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/><path d="M17 14h-6"/><path d="M13 18H7"/><path d="M7 14h.01"/><path d="M17 18h.01"/></svg>
                  <span>Nachfassen (CRM)</span>
                </button>

                <button
                  type="button"
                  onClick={handleSetGoogleCalendarEvent}
                  className={`px-3 py-1.5 rounded-lg border text-[11px] font-bold transition cursor-pointer flex items-center gap-1.5 ${
                    isLight
                      ? 'border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100'
                      : 'border-blue-900/60 bg-blue-950/40 text-blue-400 hover:bg-blue-900/40'
                  }`}
                  title="Normalen Google-Kalender-Termin eintragen"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="w-3.5 h-3.5"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/><path d="m9 16 2 2 4-4"/></svg>
                  <span>Termin (Google)</span>
                </button>
              </div>

              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={onClose}
                  className={`px-4 py-2 rounded-lg text-xs font-mono font-bold border transition cursor-pointer ${
                    isLight
                      ? 'border-slate-300 text-slate-600 hover:bg-slate-100'
                      : 'border-slate-700 text-slate-400 hover:bg-slate-800'
                  }`}
                >
                  Abbrechen
                </button>
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={saving}
                  className="px-5 py-2 rounded-lg bg-accent-main bg-accent-main-hover text-white font-bold text-xs transition shadow-md flex items-center gap-2 disabled:opacity-50 cursor-pointer"
                >
                  <Save className="w-4 h-4" />
                  <span>{saving ? 'Speichert...' : 'Speichern'}</span>
                </button>
              </div>
            </div>

          </div>
        </div>

        {/* APPOINTMENT DIALOG MODAL */}
        {appointmentDialog.isOpen && (
          <div className="fixed inset-0 z-[1000] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
            <div className={`w-full max-w-lg rounded-xl border shadow-2xl overflow-hidden flex flex-col ${
              isLight ? 'bg-white border-slate-200 text-slate-900' : 'bg-slate-900 border-slate-800 text-slate-100'
            }`}>
              {/* Header */}
              <div className={`p-4 border-b flex items-center justify-between ${
                isLight ? 'bg-slate-50 border-slate-200' : 'bg-slate-950/60 border-slate-800'
              }`}>
                <div className="flex items-center gap-2.5">
                  <Calendar className="w-5 h-5 text-accent-main" />
                  <div>
                    <h3 className="text-sm font-bold tracking-tight">Termin konfigurieren</h3>
                    <p className="text-[10px] font-mono text-slate-400">
                      Ziel-Kalender: <span className={`font-bold uppercase ${appointmentDialog.type === 'google' ? 'text-blue-400' : 'text-emerald-400'}`}>
                        {appointmentDialog.type === 'google' ? 'Google Calendar' : 'CRM (Lokal)'}
                      </span>
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setAppointmentDialog({ ...appointmentDialog, isOpen: false })}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition cursor-pointer"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {/* Body */}
              <div className="p-5 space-y-4 max-h-[70vh] overflow-y-auto">
                {/* Title */}
                <div>
                  <label className="block text-[10px] font-bold uppercase tracking-wider mb-1.5 text-slate-400">
                    Termin-Titel *
                  </label>
                  <input
                    type="text"
                    value={appointmentDialog.title}
                    onChange={(e) => setAppointmentDialog({ ...appointmentDialog, title: e.target.value })}
                    className={`w-full px-3 py-2 border rounded-lg text-xs transition outline-none ${
                      isLight ? 'bg-slate-50 border-slate-300 text-slate-900' : 'bg-slate-950 border-slate-800 text-slate-300'
                    }`}
                    placeholder="z.B. Kennenlernen"
                    required
                  />
                </div>

                {/* DateTime and Duration in one row */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-[10px] font-bold uppercase tracking-wider mb-1.5 text-slate-400">
                      Startzeitpunkt *
                    </label>
                    <input
                      type="datetime-local"
                      value={appointmentDialog.dateTime}
                      onChange={(e) => setAppointmentDialog({ ...appointmentDialog, dateTime: e.target.value })}
                      className={`w-full px-3 py-2 border rounded-lg text-xs transition outline-none ${
                        isLight ? 'bg-slate-50 border-slate-300 text-slate-900' : 'bg-slate-950 border-slate-800 text-slate-300'
                      }`}
                      required
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] font-bold uppercase tracking-wider mb-1.5 text-slate-400">
                      Dauer
                    </label>
                    <select
                      value={appointmentDialog.durationMinutes}
                      onChange={(e) => setAppointmentDialog({ ...appointmentDialog, durationMinutes: Number(e.target.value) })}
                      className={`w-full px-3 py-2 border rounded-lg text-xs transition outline-none ${
                        isLight ? 'bg-slate-50 border-slate-300 text-slate-900' : 'bg-slate-950 border-slate-800 text-slate-300'
                      }`}
                    >
                      <option value="15">15 Minuten</option>
                      <option value="30">30 Minuten</option>
                      <option value="45">45 Minuten</option>
                      <option value="60">60 Minuten (1 Std.)</option>
                      <option value="90">90 Minuten (1.5 Std.)</option>
                      <option value="120">120 Minuten (2 Std.)</option>
                    </select>
                  </div>
                </div>

                {/* Location */}
                <div>
                  <label className="block text-[10px] font-bold uppercase tracking-wider mb-1.5 text-slate-400">
                    Ort / Location
                  </label>
                  <input
                    type="text"
                    value={appointmentDialog.location}
                    onChange={(e) => setAppointmentDialog({ ...appointmentDialog, location: e.target.value })}
                    className={`w-full px-3 py-2 border rounded-lg text-xs transition outline-none ${
                      isLight ? 'bg-slate-50 border-slate-300 text-slate-900' : 'bg-slate-950 border-slate-800 text-slate-300'
                    }`}
                    placeholder="z.B. Online / Telefon / Microsoft Teams"
                  />
                </div>

                {/* Attendees (E-Mail) */}
                <div>
                  <label className="block text-[10px] font-bold uppercase tracking-wider mb-1.5 text-slate-400">
                    Teilnehmer (E-Mail-Adressen, mit Komma getrennt)
                  </label>
                  <input
                    type="text"
                    value={appointmentDialog.attendees}
                    onChange={(e) => setAppointmentDialog({ ...appointmentDialog, attendees: e.target.value })}
                    className={`w-full px-3 py-2 border rounded-lg text-xs transition outline-none ${
                      isLight ? 'bg-slate-50 border-slate-300 text-slate-900' : 'bg-slate-950 border-slate-800 text-slate-300'
                    }`}
                    placeholder="name@company.com, name2@company.com"
                  />
                </div>

                {/* Notes */}
                <div>
                  <label className="block text-[10px] font-bold uppercase tracking-wider mb-1.5 text-slate-400">
                    Beschreibung / Notiz
                  </label>
                  <textarea
                    value={appointmentDialog.notes}
                    onChange={(e) => setAppointmentDialog({ ...appointmentDialog, notes: e.target.value })}
                    className={`w-full px-3 py-2 border rounded-lg text-xs transition outline-none font-sans leading-relaxed ${
                      isLight ? 'bg-slate-50 border-slate-300 text-slate-900' : 'bg-slate-950 border-slate-800 text-slate-300'
                    }`}
                    rows={3}
                    placeholder="Zusätzliche Details für den Termin..."
                  />
                </div>
              </div>

              {/* Footer */}
              <div className={`p-4 border-t flex items-center justify-end gap-3 ${
                isLight ? 'bg-slate-50 border-slate-200' : 'bg-slate-950/60 border-slate-800'
              }`}>
                <button
                  type="button"
                  onClick={() => setAppointmentDialog({ ...appointmentDialog, isOpen: false })}
                  className={`px-4 py-2 rounded-lg text-xs font-mono font-bold border transition cursor-pointer ${
                    isLight
                      ? 'border-slate-300 text-slate-600 hover:bg-slate-100'
                      : 'border-slate-700 text-slate-400 hover:bg-slate-800'
                  }`}
                >
                  Abbrechen
                </button>
                <button
                  type="button"
                  onClick={handleConfirmCreateEvent}
                  className={`px-5 py-2 rounded-lg text-white font-bold text-xs transition shadow-md flex items-center gap-2 cursor-pointer ${
                    appointmentDialog.type === 'google'
                      ? 'bg-blue-600 hover:bg-blue-700'
                      : 'bg-emerald-600 hover:bg-emerald-700'
                  }`}
                >
                  <Calendar className="w-4 h-4" />
                  <span>Termin anlegen</span>
                </button>
              </div>
            </div>
          </div>
        )}

        {/* VOLLBILD-SPERRE während Aufnahme/Transkription:
            Deckt den kompletten Screen ab (z-[1000] > Drawer z-[999]).
            Alle Klicks werden verschluckt - nur der Stopp-/Warte-Button bleibt. */}
        {isAnyRecordingActive && (
          <div className="fixed inset-0 z-[1000] bg-slate-950/80 backdrop-blur-md flex items-center justify-center p-6">
            <div className={`w-full max-w-md rounded-2xl border p-6 shadow-2xl space-y-4 text-center ${
              isLight ? 'bg-white border-slate-200 text-slate-900' : 'bg-slate-900 border-slate-800 text-slate-100'
            }`}>
              {isRecording || isModalRecording || panelActiveRecording ? (
                <>
                  <div className="flex items-center justify-center gap-2">
                    <span className="w-3 h-3 rounded-full bg-rose-500 animate-pulse" />
                    <h3 className="text-sm font-bold tracking-tight">Aufnahme läuft</h3>
                  </div>
                  <div className="font-mono text-2xl font-bold text-accent-main tabular-nums">
                    {isRecording ? formatRecordingTime(recordingTime) : isModalRecording ? formatRecordingTime(modalRecordingTime) : formatRecordingTime(panelTimerSeconds)}
                  </div>
                  {segmentStatus && (
                    <p className="text-xs text-slate-400 font-semibold">{segmentStatus}</p>
                  )}
                  <p className="text-[11px] text-slate-400">
                    Der Bildschirm ist während der Aufnahme gesperrt.
                    <br />Bitte warten, bis die Aufnahme beendet ist.
                  </p>
                  <button
                    type="button"
                    onClick={() => {
                      if (isRecording) stopRecording();
                      if (isModalRecording) stopModalRecording();
                      if (panelActiveRecording && panelStopRef.current) panelStopRef.current();
                    }}
                    className="w-full py-3 rounded-xl bg-rose-600 hover:bg-rose-700 text-white font-bold text-sm transition shadow-lg flex items-center justify-center gap-2 cursor-pointer"
                  >
                    <Square className="w-4 h-4" />
                    Aufnahme stoppen
                  </button>
                </>
              ) : (
                <>
                  <div className="flex items-center justify-center gap-2">
                    <Loader2 className="w-4 h-4 text-accent-main animate-spin" />
                    <h3 className="text-sm font-bold tracking-tight">Transkription läuft</h3>
                  </div>
                  <p className="text-xs text-slate-400">
                    Die Aufnahme wird verarbeitet. Bitte die Seite nicht verlassen -
                    die Transkription läuft im Hintergrund.
                  </p>
                  <div className="w-full h-1.5 rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden">
                    <div className="h-full rounded-full bg-accent-main animate-pulse w-2/3" />
                  </div>
                </>
              )}
            </div>
          </div>
        )}
    </>
      );
    }
