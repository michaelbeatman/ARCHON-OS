"use client";

import React, { useState, useEffect, useRef } from 'react';
import { KontaktRecord, pb } from '@/lib/pocketbase';
import { transcribeAudioOnly, summarizeText } from '@/utils/aiAudio';
import {
  MessageSquare, Star, Trash2, Pencil, Mic, Square, Loader2, Users,
  ChevronDown, ChevronUp, FileText, Mail, Send, X, Plus
} from 'lucide-react';

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

  const cleaned = sanitizeAndCleanLinks(rawText);
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

export function formatChatMessageDate(rawDate?: string): string {
  if (!rawDate) return '';
  try {
    // Try standard parse first (ISO 8601 with T, RFC 2822, etc.)
    let d = new Date(rawDate);
    // Fallback: some older imports used "YYYY-MM-DD HH:mm" (space-separated)
    // which is ambiguous and fails in Safari. Replace space with T.
    if (isNaN(d.getTime()) && /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(rawDate)) {
      d = new Date(rawDate.replace(' ', 'T'));
    }
    if (isNaN(d.getTime())) return String(rawDate);
    return d.toLocaleString('de-DE', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  } catch (e) {
    return String(rawDate);
  }
}

export interface NachrichtenverlaufPanelProps {
  kontakt: KontaktRecord | null;
  onUpdate?: (updatedKontakt: KontaktRecord) => void;
  themeMode?: 'light' | 'dark';
  /** Wird bei jeder Änderung des Aufnahme-/Verarbeitungsstatus aufgerufen.
   *  active=true => es läuft eine Audio-Aufnahme oder Transkription.
   *  Der Parent (KontaktDrawer) sperrt damit das Schließen des Fensters. */
  onRecordingStateChange?: (active: boolean) => void;
  /** Registriert beim Parent eine Stopp-Funktion, die ALLE Aufnahmen dieses
   *  Panels beendet (Audio-Diktat, Notiz-Diktat, Meeting-Diktat). Das
   *  Vollbild-Overlay im Drawer ruft sie auf. */
  registerPanelStopHandler?: (fn: () => void) => void;
  /** Meldet dem Parent, ob im Panel gerade eine Aufnahme AKTIV läuft
   *  (nicht nur Transkription) - für die korrekte Overlay-Anzeige. */
  onPanelRecordingChange?: (active: boolean) => void;
  /** Meldet dem Parent die aktuell laufende Aufnahmezeit (Sekunden) für die
   *  Timer-Anzeige im Vollbild-Overlay. */
  onPanelTimeChange?: (seconds: number) => void;
}

export function NachrichtenverlaufPanel({
  kontakt,
  onUpdate,
  themeMode = 'light',
  onRecordingStateChange,
  registerPanelStopHandler,
  onPanelRecordingChange,
  onPanelTimeChange
}: NachrichtenverlaufPanelProps) {
  const isLight = themeMode === 'light';

  const [messages, setMessages] = useState<any[]>([]);
  const [channelFilter, setChannelFilter] = useState<'all' | 'linkedin' | 'email' | 'meeting' | 'note'>('all');
  const [expandedTranscripts, setExpandedTranscripts] = useState<Record<string, boolean>>({});

  // Audio recording state
  const [isRecording, setIsRecording] = useState(false);
  const [recordingTime, setRecordingTime] = useState(0);
  const [isProcessingAudio, setIsProcessingAudio] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<any>(null);
  const SEGMENT_DURATION_SEC = 600; // 10 Minuten
  const streamRef = useRef<MediaStream | null>(null);
  const isFinalStopRef = useRef(false);
  const segmentCountRef = useRef(0);
  const accumulatedTranscriptRef = useRef('');

  // Note Modal state
  const [isNoteModalOpen, setIsNoteModalOpen] = useState(false);
  const [noteModalText, setNoteModalText] = useState('');
  const [editingNoteId, setEditingNoteId] = useState<string | null>(null);
  const [editingNoteText, setEditingNoteText] = useState('');

  // Modal Audio Recording state
  const [isModalRecording, setIsModalRecording] = useState(false);
  const [modalRecordingTime, setModalRecordingTime] = useState(0);
  const [isModalProcessingAudio, setIsModalProcessingAudio] = useState(false);
  const modalMediaRecorderRef = useRef<MediaRecorder | null>(null);
  const modalAudioChunksRef = useRef<Blob[]>([]);
  const modalTimerRef = useRef<any>(null);
  const modalStreamRef = useRef<MediaStream | null>(null);
  const modalIsFinalStopRef = useRef(false);
  const modalSegmentCountRef = useRef(0);

  // MEETING-DIKTAT (Zwei-Spur): Mikrofon (Michael Keller) + Tab-Audio (Gegenüber)
  const [isMeetingRecording, setIsMeetingRecording] = useState(false);
  const [meetingRecordingTime, setMeetingRecordingTime] = useState(0);
  const [isMeetingProcessingAudio, setIsMeetingProcessingAudio] = useState(false);
  const meetingMicRecorderRef = useRef<MediaRecorder | null>(null);
  const meetingTabRecorderRef = useRef<MediaRecorder | null>(null);
  const meetingMicChunksRef = useRef<Blob[]>([]);
  const meetingTabChunksRef = useRef<Blob[]>([]);
  const meetingMicStreamRef = useRef<MediaStream | null>(null);
  const meetingTabStreamRef = useRef<MediaStream | null>(null);
  const meetingTimerRef = useRef<any>(null);
  const meetingIsFinalStopRef = useRef(false);
  const meetingSegmentCountRef = useRef(0);
  const meetingTranscriptRef = useRef('');

  const chatEndRef = useRef<HTMLDivElement>(null);

  // Sync messages when kontakt prop changes
  useEffect(() => {
    if (kontakt?.nachrichtenverlauf) {
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
  }, [kontakt]);

  // Meldet dem Parent (KontaktDrawer) den Aufnahme-/Verarbeitungsstatus,
  // damit das Fenster während Aufnahme/Transkription nicht geschlossen wird.
  useEffect(() => {
    if (!onRecordingStateChange) return;
    const active =
      isRecording ||
      isModalRecording ||
      isMeetingRecording ||
      isProcessingAudio ||
      isModalProcessingAudio ||
      isMeetingProcessingAudio;
    onRecordingStateChange(active);
  }, [isRecording, isModalRecording, isMeetingRecording, isProcessingAudio, isModalProcessingAudio, isMeetingProcessingAudio, onRecordingStateChange]);


  // Timestamp robust parsen (beide Formate: "YYYY-MM-DD HH:mm:ss UTC" und ISO-T)
  const parseTs = (ts?: string) => {
    if (!ts) return 0;
    let d = new Date(ts);
    if (isNaN(d.getTime()) && /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(ts)) {
      d = new Date(ts.replace(' ', 'T'));
    }
    return isNaN(d.getTime()) ? 0 : d.getTime();
  };

  // Save updated messages to PocketBase
  // WICHTIG: Vor dem Speichern chronologisch AUFSTEIGEND sortieren (älteste
  // zuerst) - identisch zur Ordnung des LinkedIn-Import-Skripts. So bleibt die
  // gespeicherte Reihenfolge stabil und es entstehen keine Duplikate beim
  // nächsten Import (Reihenfolge ist Teil des Merge-Vergleichs).
  const saveMessagesToPb = async (updatedList: any[]) => {
    const sorted = [...updatedList].sort((a, b) => parseTs(b.timestamp) - parseTs(a.timestamp));  // juengste zuerst
    setMessages(sorted);
    if (kontakt?.id) {
      try {
        const updatedRecord = await pb.collection('Kontakte').update<KontaktRecord>(kontakt.id, {
          nachrichtenverlauf: sorted
        });
        if (onUpdate) {
          onUpdate(updatedRecord);
        }
      } catch (err) {
        console.error("Failed to update nachrichtenverlauf in PB:", err);
      }
    }
  };

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
          const newMsg = {
            id: Date.now().toString(),
            type: 'meeting',
            sender: 'user',
            text: summary,
            rawTranscript: fullText,
            timestamp: new Date().toISOString()
          };
          const updated = [...messages, newMsg];
          await saveMessagesToPb(updated);
        }
      }
    } catch (err: any) {
      if (final) {
        alert(`Audio-Verarbeitung fehlgeschlagen: ${err.message || 'Unbekannter Fehler'}`);
      } else {
        console.warn('[Archon CRM] Segment-Transkription fehlgeschlagen (übersprungen):', err);
      }
    } finally {
      setIsProcessingAudio(false);
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

  const handleDeleteMessage = async (msgId: string) => {
    const updatedMessages = (messages || []).filter((msg: any, idx: number) => {
      const currentId = msg.id || idx.toString();
      return currentId !== msgId;
    });
    await saveMessagesToPb(updatedMessages);
  };

  const handleToggleStarMessage = async (msgId: string) => {
    const updatedMessages = (messages || []).map((msg: any, idx: number) => {
      const currentId = msg.id || idx.toString();
      if (currentId === msgId) {
        return { ...msg, isStarred: !msg.isStarred };
      }
      return msg;
    });
    await saveMessagesToPb(updatedMessages);
  };

  const handleSaveEditedNote = async (msgId: string) => {
    if (!editingNoteText.trim()) return;
    const updatedMessages = (messages || []).map((msg: any, idx: number) => {
      const currentId = msg.id || idx.toString();
      if (currentId === msgId) {
        return { ...msg, text: editingNoteText.trim() };
      }
      return msg;
    });
    await saveMessagesToPb(updatedMessages);
    setEditingNoteId(null);
    setEditingNoteText('');
  };

  const handleAddNoteMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    // Während Diktat-Aufnahme/Transkription nicht speichern/schließen
    if (isModalRecording || isModalProcessingAudio) return;
    if (!noteModalText.trim()) return;

    const newMsg = {
      id: Date.now().toString(),
      type: 'note',
      sender: 'user',
      text: noteModalText.trim(),
      timestamp: new Date().toISOString()
    };

    const updated = [...messages, newMsg];
    await saveMessagesToPb(updated);
    setNoteModalText('');
    setIsNoteModalOpen(false);
  };

  // ================= MEETING-DIKTAT (Zwei-Spur) =================
  // Spur 1: Mikrofon (Michael Keller / Ich) — Spur 2: Tab-Audio (Gegenüber).
  // Beide werden parallel aufgenommen und segmentiert (10 Min). Jedes Segment
  // wird getrennt transkribiert und mit dem jeweiligen Sprecher-Label versehen.
  const startMeetingSegmentRecorders = () => {
    const micStream = meetingMicStreamRef.current;
    const tabStream = meetingTabStreamRef.current;
    if (!micStream || !tabStream) return;
    meetingSegmentCountRef.current += 1;

    // --- Spur 1: Mikrofon (Michael Keller) ---
    meetingMicChunksRef.current = [];
    const micRec = new MediaRecorder(micStream);
    meetingMicRecorderRef.current = micRec;
    micRec.ondataavailable = (e) => { if (e.data.size > 0) meetingMicChunksRef.current.push(e.data); };
    micRec.onstop = () => {
      const blob = new Blob(meetingMicChunksRef.current, { type: 'audio/webm' });
      void transcribeMeetingSegment(blob, 'user');
    };
    micRec.start();

    // --- Spur 2: Tab-Audio (Gegenüber) ---
    meetingTabChunksRef.current = [];
    const tabRec = new MediaRecorder(tabStream);
    meetingTabRecorderRef.current = tabRec;
    tabRec.ondataavailable = (e) => { if (e.data.size > 0) meetingTabChunksRef.current.push(e.data); };
    tabRec.onstop = () => {
      const blob = new Blob(meetingTabChunksRef.current, { type: 'audio/webm' });
      void transcribeMeetingSegment(blob, 'contact');
    };
    tabRec.start();
  };

  // Ein Segment einer Spur transkribieren; am Ende (beide final) zusammenfassen.
  const meetingDoneRef = useRef({ mic: false, tab: false });
  const transcribeMeetingSegment = async (blob: Blob, track: 'user' | 'contact') => {
    const label = track === 'user'
      ? (kontakt?.id ? 'Michael Keller' : 'Michael Keller')
      : (kontakt?.name || 'Gegenüber');
    const segmentIdx = meetingSegmentCountRef.current;
    setIsMeetingProcessingAudio(true);
    try {
      const apiKey = process.env.NEXT_PUBLIC_GROQ_API_KEY || localStorage.getItem('groq_api_key') || '';
      const transcript = await transcribeAudioOnly(blob, apiKey);
      if (transcript && transcript.trim()) {
        const line = `[${label}] ${transcript.trim()}`;
        meetingTranscriptRef.current += (meetingTranscriptRef.current ? '\n\n' : '') + line;
      }
    } catch (err: any) {
      console.warn(`[Archon CRM] Meeting-Segment (${track}) fehlgeschlagen:`, err);
    } finally {
      setIsMeetingProcessingAudio(false);
    }

    // Finalen Abschluss prüfen: beide Spuren fertig?
    if (meetingIsFinalStopRef.current) {
      if (track === 'user') meetingDoneRef.current.mic = true;
      else meetingDoneRef.current.tab = true;
      if (meetingDoneRef.current.mic && meetingDoneRef.current.tab) {
        meetingDoneRef.current = { mic: false, tab: false };
        await finalizeMeetingTranscript();
      }
    }
  };

  const finalizeMeetingTranscript = async () => {
    try {
      const fullText = meetingTranscriptRef.current;
      meetingTranscriptRef.current = '';
      if (!fullText) return;
      const apiKey = process.env.NEXT_PUBLIC_GROQ_API_KEY || localStorage.getItem('groq_api_key') || '';
      const summary = await summarizeText(fullText, apiKey);
      const newMsg = {
        id: Date.now().toString(),
        type: 'meeting',
        channel: 'meeting',
        sender: 'user',
        text: summary,
        rawTranscript: fullText,
        timestamp: new Date().toISOString()
      };
      const updated = [...messages, newMsg];
      await saveMessagesToPb(updated);
    } catch (err: any) {
      alert(`Meeting-Verarbeitung fehlgeschlagen: ${err.message || 'Fehler'}`);
    }
  };

  const startMeetingRecording = async () => {
    try {
      // Spur 1: Mikrofon (Michael Keller)
      const micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // Spur 2: Tab-Audio (Gegenüber) — Browser zeigt Tab-Auswahl.
      // WICHTIG: Chrome verlangt bei getDisplayMedia zwingend video:true
      // (video:false wirft NotSupportedError). Das Video wird danach verworfen.
      const tabStream = await navigator.mediaDevices.getDisplayMedia({
        video: true,
        audio: true
      } as any);
      // Video-Track verwerfen - wir wollen nur das Tab-Audio
      tabStream.getVideoTracks().forEach(t => t.stop());
      if (!tabStream.getAudioTracks().length) {
        micStream.getTracks().forEach(t => t.stop());
        tabStream.getTracks().forEach(t => t.stop());
        alert('Kein Tab-Audio ausgewählt. Bitte im Dialog "Tab-Audio teilen" aktivieren.');
        return;
      }

      meetingMicStreamRef.current = micStream;
      meetingTabStreamRef.current = tabStream;
      meetingIsFinalStopRef.current = false;
      meetingSegmentCountRef.current = 0;
      meetingTranscriptRef.current = '';
      meetingDoneRef.current = { mic: false, tab: false };
      startMeetingSegmentRecorders();
      setIsMeetingRecording(true);
      setMeetingRecordingTime(0);

      meetingTimerRef.current = setInterval(() => {
        setMeetingRecordingTime(prev => {
          const next = prev + 1;
          // Segment-Wechsel bei 10 Minuten: beide Recorder stoppen (onstop startet neu)
          if (next >= SEGMENT_DURATION_SEC) {
            meetingIsFinalStopRef.current = false;
            if (meetingMicRecorderRef.current?.state === 'recording') meetingMicRecorderRef.current.stop();
            if (meetingTabRecorderRef.current?.state === 'recording') meetingTabRecorderRef.current.stop();
            // onstop der letzten Spur startet die nächste Segment-Runde
            meetingIsFinalStopRef.current = false;
            setTimeout(() => {
              if (isMeetingRecording) startMeetingSegmentRecorders();
            }, 300);
            return 0;
          }
          return next;
        });
      }, 1000);
    } catch (err: any) {
      alert(`Meeting-Aufnahme nicht möglich: ${err.message || 'Fehler'}. Für Tab-Audio muss der Gesprächs-Tab im Video-Call freigegeben werden.`);
    }
  };

  const stopMeetingRecording = () => {
    if (meetingTimerRef.current) {
      clearInterval(meetingTimerRef.current);
      meetingTimerRef.current = null;
    }
    meetingIsFinalStopRef.current = true;
    if (meetingMicRecorderRef.current?.state === 'recording') meetingMicRecorderRef.current.stop();
    if (meetingTabRecorderRef.current?.state === 'recording') meetingTabRecorderRef.current.stop();
    // Streams sauber beenden (nach kurzer Wartezeit, damit onstop fertig transkribiert)
    setTimeout(() => {
      meetingMicStreamRef.current?.getTracks().forEach(t => t.stop());
      meetingTabStreamRef.current?.getTracks().forEach(t => t.stop());
      meetingMicStreamRef.current = null;
      meetingTabStreamRef.current = null;
    }, 2000);
    setIsMeetingRecording(false);
  };

  // Registriert beim Parent die Stopp-Funktion für ALLE Panel-Aufnahmen.
  useEffect(() => {
    if (!registerPanelStopHandler) return;
    registerPanelStopHandler(() => {
      if (isRecording) stopRecording();
      if (isModalRecording) stopModalRecording();
      if (isMeetingRecording) stopMeetingRecording();
    });
  }, [registerPanelStopHandler, isRecording, isModalRecording, isMeetingRecording]);

  // Meldet dem Parent, ob im Panel eine Aufnahme AKTIV läuft (Overlay-Anzeige).
  useEffect(() => {
    if (!onPanelRecordingChange) return;
    onPanelRecordingChange(isRecording || isModalRecording || isMeetingRecording);
  }, [isRecording, isModalRecording, isMeetingRecording, onPanelRecordingChange]);

  // Meldet dem Parent die aktuell laufende Aufnahmezeit (Overlay-Timer).
  useEffect(() => {
    if (!onPanelTimeChange) return;
    if (isRecording) onPanelTimeChange(recordingTime);
    else if (isModalRecording) onPanelTimeChange(modalRecordingTime);
    else if (isMeetingRecording) onPanelTimeChange(meetingRecordingTime);
  }, [isRecording, isModalRecording, isMeetingRecording, recordingTime, modalRecordingTime, meetingRecordingTime, onPanelTimeChange]);

  const toggleTranscript = (msgId: string) => {
    setExpandedTranscripts(prev => ({
      ...prev,
      [msgId]: !prev[msgId]
    }));
  };

  // Deduplizieren und nach Channel filtern
  const filteredMessages = React.useMemo(() => {
    // Duplikate im Speicher für das Rendering bereinigen
    const uniqueMap = new Map<string, any>();
    messages.forEach((item, index) => {
      const textSnippet = (item.text || '').trim();
      const timeSnippet = item.timestamp || '';
      const senderSnippet = item.sender || '';
      const key = item.id 
        ? `${item.id}_${senderSnippet}_${timeSnippet}_${textSnippet.slice(0, 40)}`
        : `msg-${index}_${senderSnippet}_${textSnippet.slice(0, 40)}`;
      
      if (!uniqueMap.has(key)) {
        uniqueMap.set(key, { ...item, _uniqueKey: `key-${index}-${key}` });
      }
    });

    const uniqueMessages = Array.from(uniqueMap.values());

    return uniqueMessages
      .filter((msg) => {
        let ch = msg.type || msg.channel || 'linkedin';
        const isNote = ch === 'note' || (!!msg.text && (msg.text.includes('NOTIZ') || msg.text.includes('NACHTRAG')));
        if (isNote) ch = 'note';

        if (channelFilter === 'all') return true;
        if (channelFilter === 'linkedin') return ch === 'linkedin';
        if (channelFilter === 'email') return ch === 'email';
        if (channelFilter === 'meeting') return ch === 'meeting' || ch === 'audio';
        if (channelFilter === 'note') return ch === 'note';
        return true;
      })
      .sort((a, b) => parseTs(b.timestamp) - parseTs(a.timestamp));  // juengste zuerst
  }, [messages, channelFilter]);

  return (
    <div className="w-full h-full min-h-0 flex flex-col overflow-hidden">
      
      {/* HEADER BAR */}
      <div className={`pb-3 border-b flex items-center justify-between shrink-0 mb-3 gap-2 ${
        isLight ? 'border-zinc-200' : 'border-zinc-800'
      }`}>
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-bold font-sans">Nachrichtenverlauf</h3>
        </div>

        {/* KANAL-FILTER BUTTONS */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-0.5">
          {(['all', 'linkedin', 'email', 'meeting', 'note'] as const).map((ch) => {
            const isActive = channelFilter === ch;
            const activeClass =
              ch === 'all'
                ? 'bg-accent-main text-white shadow-xs font-bold border border-accent-main'
                : ch === 'linkedin'
                ? 'bg-blue-600 text-white shadow-xs font-bold border border-blue-600'
                : ch === 'email'
                ? 'bg-orange-600 text-white shadow-xs font-bold border border-orange-600'
                : ch === 'meeting'
                ? 'bg-red-600 text-white shadow-xs font-bold border border-red-600'
                : 'bg-emerald-600 text-white shadow-xs font-bold border border-emerald-600';

            return (
              <button
                key={ch}
                type="button"
                onClick={() => setChannelFilter(ch)}
                className={`px-3 py-1 rounded-full text-[11px] font-mono transition cursor-pointer shrink-0 ${
                  isActive
                    ? activeClass
                    : isLight
                    ? 'bg-zinc-100 border border-zinc-200 text-zinc-700 font-semibold hover:bg-zinc-200 hover:text-zinc-900'
                    : 'bg-zinc-800 border border-zinc-700 text-zinc-200 font-medium hover:bg-zinc-700 hover:text-white'
                }`}
              >
                {ch === 'all' ? 'Alle' : ch === 'linkedin' ? 'LinkedIn' : ch === 'email' ? 'E-Mail' : ch === 'meeting' ? 'Meeting' : 'Notizen'}
              </button>
            );
          })}
        </div>
      </div>

      {/* MESSAGES LIST SCROLL CONTAINER */}
      <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden space-y-3 pr-2 font-sans text-xs">
        {filteredMessages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-zinc-400 gap-2">
            <MessageSquare className="w-8 h-8 text-zinc-300 dark:text-zinc-700" />
            <p className="text-xs font-mono">
              {channelFilter === 'all' ? 'Noch keine Nachrichten vorhanden.' : `Keine Nachrichten im Kanal "${channelFilter === 'note' ? 'Notizen' : channelFilter === 'meeting' ? 'Meeting' : channelFilter === 'email' ? 'E-Mail' : 'LinkedIn'}".`}
            </p>
          </div>
        ) : (
          filteredMessages.map((msg, idx) => {
            const isUser = msg.sender === 'user' || msg.sender === 'Ich' || msg.sender === 'Michael Keller' || msg.sender === 'me';
            const senderName = isUser
              ? 'Ich'
              : (!msg.sender || msg.sender === 'contact' || msg.sender === 'kontakt')
              ? (kontakt?.name || 'Kontakt')
              : msg.sender;
            const msgDate = formatChatMessageDate(msg.timestamp || msg.date || msg.time);
            let msgChannel = msg.type || msg.channel || 'linkedin';
            const isNote = msgChannel === 'note' || (!!msg.text && (msg.text.includes('NOTIZ') || msg.text.includes('NACHTRAG')));
            if (isNote) msgChannel = 'note';
            const msgId = msg.id || idx.toString();
            const isExpanded = !!expandedTranscripts[msgId];

            // Farbmatrix für Nachrichtentypen (WCAG AAA Tint-Shade Pattern)
            const getCardStyle = (type: string) => {
              switch (type) {
                case 'email':
                  return {
                    border: 'border-[#EA580C]',
                    headerBg: 'bg-[#FFEDD5]',
                    headerBgVar: 'var(--contact-message-header-email-bg, #FFEDD5)',
                    headerText: 'text-[#C2410C]',
                    headerTextVar: 'var(--contact-message-text, #C2410C)',
                    Icon: Mail,
                    label: 'E-Mail'
                  };
                case 'note':
                  return {
                    border: 'border-[#059669]',
                    headerBg: 'bg-[#D1FAE5]',
                    headerBgVar: 'var(--contact-message-header-note-bg, #D1FAE5)',
                    headerText: 'text-[#047857]',
                    headerTextVar: 'var(--contact-message-text, #047857)',
                    Icon: FileText,
                    label: 'Notiz'
                  };
                case 'meeting':
                case 'audio':
                  return {
                    border: 'border-[#E11D48]',
                    headerBg: 'bg-[#FFE4E6]',
                    headerBgVar: 'var(--contact-message-header-meeting-bg, #FFE4E6)',
                    headerText: 'text-[#BE123C]',
                    headerTextVar: 'var(--contact-message-text, #BE123C)',
                    Icon: Mic,
                    label: 'Audio-Diktat'
                  };
                case 'linkedin':
                default:
                  return {
                    border: 'border-[#0A66C2]',
                    headerBg: 'bg-[#E0F2FE]',
                    headerBgVar: 'var(--contact-message-header-linkedin-bg, #E0F2FE)',
                    headerText: 'text-[#0369A1]',
                    headerTextVar: 'var(--contact-message-text, #0369A1)',
                    Icon: LinkedinIcon,
                    label: 'LinkedIn'
                  };
              }
            };

            // Ausrichtungsklasse dynamisch ermitteln (WhatsApp-Style Offset & CRM Elemente volle Breite)
            const getAlignmentClass = (type: string, sender: string) => {
              if (type === 'note' || type === 'audio' || type === 'meeting') {
                return 'w-full mx-0 mb-3';
              }
              const isUserSender = sender === 'user' || sender === 'Ich' || sender === 'Michael Keller' || sender === 'me';
              return isUserSender
                ? 'w-[92%] ml-auto mr-0 mb-3'  // Rechtsbündig (Ausgehend)
                : 'w-[92%] mr-auto ml-0 mb-3'; // Linksbündig (Eingehend)
            };

            const currentStyle = getCardStyle(msgChannel);
            const CardIcon = currentStyle.Icon;
            const alignClass = getAlignmentClass(msgChannel, msg.sender);

            return (
              <div
                key={msg._uniqueKey || msgId || `msg-${idx}`}
                className={`rounded-xl border-2 overflow-hidden bg-white shadow-md hover:shadow-lg transition-shadow duration-200 font-sans ${currentStyle.border} ${alignClass} chat-card-root ${isUser ? 'outbound' : 'inbound'}`}
              >
                {/* Header Bar */}
                <div
                  className={`flex items-center justify-between px-4 py-2 ${currentStyle.headerBg} ${currentStyle.headerText}`}
                  style={{ backgroundColor: currentStyle.headerBgVar, color: currentStyle.headerTextVar }}
                >
                  <div className="flex items-center gap-2 font-semibold text-sm">
                    <CardIcon className="w-4 h-4 shrink-0" />
                    <span>{currentStyle.label}</span>
                    <span className="opacity-40">•</span>
                    <span className="font-medium">{senderName}</span>
                  </div>

                  <div className="flex items-center gap-3 text-xs">
                    <span className="text-zinc-600 font-medium">{msgDate}</span>
                    <button
                      type="button"
                      onClick={() => handleToggleStarMessage(msgId)}
                      className="focus:outline-none cursor-pointer"
                      title={msg.isStarred ? "Markierung aufheben" : "Nachricht markieren"}
                    >
                      <Star className={`w-4 h-4 transition ${msg.isStarred ? 'text-amber-400 fill-amber-400' : 'text-zinc-400 hover:text-zinc-600'}`} />
                    </button>

                    {/* Email Delete */}
                    {msgChannel === 'email' && (
                      <button
                        type="button"
                        onClick={() => handleDeleteMessage(msgId)}
                        title="E-Mail löschen"
                        className="text-zinc-400 hover:text-rose-600 transition cursor-pointer"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}

                    {/* Notiz Actions */}
                    {msgChannel === 'note' && (
                      <>
                        <button
                          type="button"
                          onClick={() => {
                            setEditingNoteId(msgId);
                            setEditingNoteText(msg.text.replace('📌 NOTIZ / NACHTRAG:\n', ''));
                          }}
                          title="Notiz bearbeiten"
                          className="text-zinc-400 hover:text-emerald-700 transition cursor-pointer"
                        >
                          <Pencil className="w-3.5 h-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDeleteMessage(msgId)}
                          title="Notiz löschen"
                          className="text-zinc-400 hover:text-rose-600 transition cursor-pointer"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </>
                    )}

                    {/* Audio/Meeting Actions */}
                    {(msgChannel === 'meeting' || msgChannel === 'audio') && (
                      <button
                        type="button"
                        onClick={() => handleDeleteMessage(msgId)}
                        title="Meeting-Protokoll löschen"
                        className="text-zinc-400 hover:text-rose-600 transition cursor-pointer"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </div>

                {/* Body Content */}
                <div className={`p-4 text-sm leading-relaxed whitespace-pre-line break-words [overflow-wrap:anywhere] ${
                  isLight ? 'text-zinc-800' : 'text-zinc-100'
                }`}>
                  {msgChannel === 'note' && editingNoteId === msgId ? (
                    <div className="space-y-2">
                      <textarea
                        rows={3}
                        value={editingNoteText}
                        onChange={(e) => setEditingNoteText(e.target.value)}
                        className="w-full p-2 text-xs border border-emerald-400 rounded-lg text-black font-semibold resize-none focus:outline-none focus:ring-1 focus:ring-emerald-500"
                      />
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => setEditingNoteId(null)}
                          className="px-2 py-1 text-xs text-zinc-500 hover:bg-zinc-100 rounded cursor-pointer"
                        >
                          Abbrechen
                        </button>
                        <button
                          type="button"
                          onClick={() => handleSaveEditedNote(msgId)}
                          className="px-3 py-1 text-xs bg-emerald-600 text-white rounded font-bold hover:bg-emerald-700 cursor-pointer"
                        >
                          Speichern
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      {renderFormattedBody(msg.text)}

                      {/* Audio Transcript Collapsible */}
                      {(msgChannel === 'meeting' || msgChannel === 'audio') && msg.rawTranscript && (
                        <div className="pt-2 border-t border-rose-200 mt-3">
                          <button
                            type="button"
                            onClick={() => toggleTranscript(msgId)}
                            className="text-xs font-bold text-rose-700 hover:text-rose-800 flex items-center gap-1 mt-1 cursor-pointer"
                          >
                            {isExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                            <span>{isExpanded ? 'Transkript verbergen' : 'Transkript anzeigen'}</span>
                          </button>

                          {isExpanded && (
                            <div className="mt-2 p-3 bg-zinc-50 border border-rose-300 rounded-xl text-zinc-900 font-mono text-xs leading-relaxed whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
                              {renderFormattedBody(msg.rawTranscript)}
                            </div>
                          )}
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>
            );
          })
        )}
        <div ref={chatEndRef} />
      </div>

      {/* MINIMALISTISCHE SCHALTLEISTE (SCHMALER & RECHTSBÜNDIG) */}
      <div className={`mt-auto pt-3 border-t flex items-center justify-end gap-2.5 ${isLight ? 'border-zinc-200' : 'border-zinc-800'} py-2 shrink-0`}>
        <button
          type="button"
          onClick={() => {
            setNoteModalText('');
            setIsNoteModalOpen(true);
          }}
          className="py-1.5 px-3 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-xs shadow-xs transition flex items-center gap-1.5 cursor-pointer shrink-0"
        >
          <FileText className="w-3.5 h-3.5" />
          <span>+ Notiz</span>
        </button>

        {!isRecording ? (
          <button
            type="button"
            onClick={startRecording}
            disabled={isProcessingAudio}
            className={`py-1.5 px-3 rounded-xl font-bold text-xs shadow-xs transition flex items-center gap-1.5 cursor-pointer shrink-0 ${
              isProcessingAudio
                ? 'bg-rose-900/50 text-rose-300 border border-rose-800 cursor-not-allowed'
                : 'bg-rose-600 hover:bg-rose-700 text-white'
            }`}
          >
            {isProcessingAudio ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin text-rose-300" />
                <span>Transkribiere...</span>
              </>
            ) : (
              <>
                <Mic className="w-3.5 h-3.5" />
                <span>Audio-Diktat</span>
              </>
            )}
          </button>
        ) : (
          <button
            type="button"
            onClick={stopRecording}
            className="py-1.5 px-3 rounded-xl bg-rose-600 animate-pulse text-white font-bold text-xs shadow-xs transition flex items-center gap-1.5 cursor-pointer shrink-0"
          >
            <Square className="w-3.5 h-3.5 fill-white" />
            <span>Stopp ({formatRecordingTime(recordingTime)})</span>
          </button>
        )}

        {/* MEETING-DIKTAT (blau): Mikrofon + Tab-Audio (Gegenüber) */}
        {!isMeetingRecording ? (
          <button
            type="button"
            onClick={startMeetingRecording}
            disabled={isMeetingProcessingAudio || isRecording || isModalRecording}
            className={`py-1.5 px-3 rounded-xl font-bold text-xs shadow-xs transition flex items-center gap-1.5 cursor-pointer shrink-0 ${
              isMeetingProcessingAudio
                ? 'bg-blue-900/50 text-blue-300 border border-blue-800 cursor-not-allowed'
                : (isRecording || isModalRecording)
                ? 'bg-blue-900/40 text-blue-300 border border-blue-800 cursor-not-allowed'
                : 'bg-blue-600 hover:bg-blue-700 text-white'
            }`}
            title="Meeting-Diktat: nimmt deine Stimme (Mikrofon) UND die Stimme des Gegenübers (Tab-Audio) auf. Vorher den Video-Call-Tab im Browser-Tab-Dialog auswählen und Tab-Audio teilen."
          >
            {isMeetingProcessingAudio ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-300" />
                <span>Verarbeite...</span>
              </>
            ) : (
              <>
                <Users className="w-3.5 h-3.5" />
                <span>Meeting-Diktat</span>
              </>
            )}
          </button>
        ) : (
          <button
            type="button"
            onClick={stopMeetingRecording}
            className="py-1.5 px-3 rounded-xl bg-blue-600 animate-pulse text-white font-bold text-xs shadow-xs transition flex items-center gap-1.5 cursor-pointer shrink-0"
          >
            <Square className="w-3.5 h-3.5 fill-white" />
            <span>Stopp ({formatRecordingTime(meetingRecordingTime)})</span>
          </button>
        )}
      </div>

      {/* NOTIZ-MODAL OVERLAY */}
      {isNoteModalOpen && (
        <div className="fixed inset-0 z-50 overflow-hidden bg-black/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className={`w-full max-w-lg rounded-2xl border p-5 shadow-2xl space-y-4 animate-in zoom-in-95 duration-150 flex flex-col ${
            isLight ? 'bg-white border-zinc-200 text-zinc-900' : 'bg-zinc-900 border-zinc-800 text-zinc-100'
          }`}>
            <div className="flex items-center justify-between pb-3 border-b border-zinc-200 dark:border-zinc-800">
              <div className="flex items-center gap-2">
                <FileText className="w-5 h-5 text-emerald-600" />
                <h3 className="font-bold text-sm font-sans">Neue Notiz hinzufügen</h3>
              </div>
              <button
                type="button"
                onClick={() => {
                  // Während Diktat-Aufnahme/Transkription nicht schließen
                  if (isModalRecording || isModalProcessingAudio) return;
                  setIsNoteModalOpen(false);
                }}
                title={
                  isModalRecording || isModalProcessingAudio
                    ? 'Diktat läuft — erst stoppen'
                    : 'Schließen'
                }
                className={`p-1 rounded-lg transition cursor-pointer ${
                  isModalRecording || isModalProcessingAudio
                    ? 'text-rose-500 hover:text-rose-600 dark:text-rose-400'
                    : 'text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200'
                }`}
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleAddNoteMessage} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-zinc-600 dark:text-zinc-400 mb-1.5">
                  Notiztext
                </label>
                <textarea
                  rows={5}
                  required
                  value={noteModalText}
                  onChange={(e) => setNoteModalText(e.target.value)}
                  placeholder="Notiz eingeben..."
                  className={`w-full p-3 rounded-xl text-xs border transition resize-none focus:outline-none focus:ring-2 focus:ring-emerald-500 font-sans ${
                    isLight
                      ? 'bg-zinc-50 border-zinc-300 text-zinc-900 placeholder:text-zinc-400'
                      : 'bg-zinc-950 border-zinc-800 text-zinc-100 placeholder:text-zinc-600'
                  }`}
                />
              </div>

              {/* Diktieren im Notiz-Modal */}
              <div className="flex items-center justify-between bg-zinc-100 dark:bg-zinc-800/60 p-2.5 rounded-xl border border-zinc-200 dark:border-zinc-700/60">
                <span className="text-xs font-semibold text-zinc-600 dark:text-zinc-300 flex items-center gap-1.5">
                  <Mic className="w-3.5 h-3.5 text-rose-500" />
                  Notiz per Sprache diktieren
                </span>

                {!isModalRecording ? (
                  <button
                    type="button"
                    onClick={startModalRecording}
                    disabled={isModalProcessingAudio}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold transition flex items-center gap-1.5 cursor-pointer ${
                      isModalProcessingAudio
                        ? 'bg-zinc-300 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-600 cursor-not-allowed'
                        : 'bg-rose-600 hover:bg-rose-700 text-white shadow-xs'
                    }`}
                  >
                    {isModalProcessingAudio ? (
                      <>
                        <Loader2 className="w-3.5 h-3.5 animate-spin text-zinc-400" />
                        <span>Transkribiere...</span>
                      </>
                    ) : (
                      <>
                        <Mic className="w-3.5 h-3.5" />
                        <span>Diktieren</span>
                      </>
                    )}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={stopModalRecording}
                    className="px-3 py-1.5 rounded-lg bg-rose-600 animate-pulse text-white font-bold text-xs shadow-xs transition flex items-center gap-1.5 cursor-pointer"
                  >
                    <Square className="w-3.5 h-3.5 fill-white" />
                    <span>Stoppen ({formatRecordingTime(modalRecordingTime)})</span>
                  </button>
                )}
              </div>

              <div className="flex justify-end gap-2 pt-2 border-t border-zinc-200 dark:border-zinc-800">
                <button
                  type="button"
                  onClick={() => {
                    // Während Diktat-Aufnahme/Transkription nicht schließen
                    if (isModalRecording || isModalProcessingAudio) return;
                    setIsNoteModalOpen(false);
                  }}
                  className={`px-4 py-2 rounded-xl text-xs font-semibold transition cursor-pointer ${
                    isLight ? 'bg-zinc-100 text-zinc-700 hover:bg-zinc-200' : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'
                  }`}
                >
                  {isModalRecording || isModalProcessingAudio ? 'Diktat läuft…' : 'Abbrechen'}
                </button>
                <button
                  type="submit"
                  className="px-5 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-xs transition shadow-sm cursor-pointer"
                >
                  Notiz speichern
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

    </div>
  );
}
