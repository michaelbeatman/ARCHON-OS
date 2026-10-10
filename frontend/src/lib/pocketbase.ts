import PocketBase from 'pocketbase';

export const POCKETBASE_URL = process.env.NEXT_PUBLIC_POCKETBASE_URL || 'http://localhost:8090';

export const pb = new PocketBase(POCKETBASE_URL);

// Auto cancellation of duplicate requests disabled for smooth UI transitions
pb.autoCancellation(false);

export interface KontaktRecord {
  id: string;
  name: string;
  unternehmen?: string;
  rolle?: string;
  region?: string;
  linkedin_url?: string;
  email?: string;
  telefon_1?: string;
  telefon_2?: string;
  tags?: string[];
  vernetzt_am?: string;
  einladung_zurueckgezogen_am?: string;
  status: 'Unvernetzt' | 'Vernetzt' | 'Erstnachricht' | 'Im Dialog' | 'Interview vereinbart' | 'Regelmäßiger Kontakt' | 'Parkposition' | 'Pool' | 'Irrelevant' | 'Gesperrt_1Jahr' | 'Kein_Interesse';
  rating?: number;
  naechster_schritt?: string;
  kommentar?: string;
  RollenVerteilungzuordnung?: string;
  LinkedInheader?: string;
  Linkedin_info?: string;
  nachrichtenverlauf?: any;
  webseite?: string;
  adresse?: string;
  profilbild?: string;
  deleted_at?: string | null;
  created: string;
  updated: string;
}

export interface BerichtMetriken {
  total: number;
  messaged: number;
  dialog: number;
  calls: number;
  rates: {
    messageRate: number;
    callRate: number;
    dialogRate?: number;
  };
}

export interface BerichtRecord {
  id: string;
  titel: string;
  zeitraum_start: string;
  zeitraum_ende: string;
  kohorte: string;
  metriken: BerichtMetriken;
  executive_summary?: string;
  created: string;
  updated: string;
}

export const STATUS_COLUMNS = [
  { id: 'Unvernetzt', title: 'Unvernetzt', color: 'border-zinc-700 bg-zinc-900/40 text-zinc-300', icon: '👤' },
  { id: 'Vernetzt', title: 'Vernetzt', color: 'border-blue-900/60 bg-blue-950/30 text-blue-300', icon: '🤝' },
  { id: 'Erstnachricht', title: 'Erstnachricht', color: 'border-purple-900/60 bg-purple-950/30 text-purple-300', icon: '💬' },
  { id: 'Im Dialog', title: 'Im Dialog', color: 'border-cyan-900/60 bg-cyan-950/30 text-cyan-300', icon: '🔄' },
  { id: 'Interview vereinbart', title: 'Interview vereinbart', color: 'border-emerald-900/60 bg-emerald-950/30 text-emerald-300', icon: '📅' },
  { id: 'Regelmäßiger Kontakt', title: 'Regelmäßiger Kontakt', color: 'border-teal-900/60 bg-teal-950/30 text-teal-300', icon: '🔁' },
  { id: 'Parkposition', title: 'Parkposition', color: 'border-amber-900/60 bg-amber-950/30 text-amber-300', icon: '📁' },
  { id: 'Pool', title: 'Pool', color: 'border-violet-900/60 bg-violet-950/30 text-violet-300', icon: '🔮' },
  { id: 'Irrelevant', title: 'Irrelevant', color: 'border-zinc-800/80 bg-zinc-950/40 text-zinc-400', icon: '❓' },
  { id: 'Gesperrt_1Jahr', title: 'Gesperrt (1 Jahr)', color: 'border-rose-900/80 bg-rose-950/40 text-rose-300', icon: '⛔' },
  { id: 'Kein_Interesse', title: 'Kein Interesse', color: 'border-zinc-800/80 bg-zinc-950/40 text-zinc-400', icon: '🚫' }
] as const;

export function getProfilbildUrl(record: Partial<KontaktRecord>): string | null {
  if (!record || !record.profilbild) return null;
  const val = record.profilbild.trim();
  if (!val) return null;

  if (val.startsWith('http://') || val.startsWith('https://') || val.startsWith('data:')) {
    return val;
  }

  if (record.id) {
    return pb.files.getURL(record as any, val);
  }

  return val;
}

// ── MEDIA POCKETBASE INSTANCE (PORT 8092) ──────────────────────────────────
export const POCKETBASE_MEDIA_URL =
  process.env.NEXT_PUBLIC_POCKETBASE_MEDIA_URL ||
  (typeof window !== 'undefined'
    ? `${window.location.protocol}//${window.location.hostname}:8092`
    : 'http://localhost:8092');

export const pbMedia = new PocketBase(POCKETBASE_MEDIA_URL);
pbMedia.autoCancellation(false);

export interface VideoBatchRecord {
  id: string;
  title?: string;
  batch_type: 'shorts_9_16' | 'longform_16_9' | 'sonstiges';
  target_duration_seconds?: number;
  current_duration_seconds?: number;
  clip_count?: number;
  status: 'collecting' | 'ready_to_render' | 'rendering' | 'completed' | 'failed';
  output_video_file?: string;
  rendered_at?: string;
  created: string;
  updated: string;
}

export interface MediaItemRecord {
  id: string;
  file?: string;
  media_type: 'video' | 'image' | 'audio' | 'sonstiges';
  format?: 'hochkant_9_16' | 'breitbild_16_9' | 'quadratisch_1_1' | 'sonstiges';
  aspect_ratio?: string;
  width?: number;
  height?: number;
  duration_seconds?: number;
  file_size_bytes?: number;
  original_filename?: string;
  source?: 'telegram' | 'manual_upload' | 'whatsapp' | 'sonstiges';
  status: 'unprocessed' | 'assigned_to_batch' | 'rendered' | 'archived';
  batch_id?: string;
  metadata_json?: any;
  received_at?: string;
  created: string;
  updated: string;
}

export interface LinkedInContentRecord {
  id: string;
  url?: string;
  title?: string;
  raw_content?: string;
  user_note?: string;
  summary?: string;
  draft_post?: string;
  status: 'inbox' | 'drafted' | 'scheduled' | 'published' | 'archived';
  received_at?: string;
  created: string;
  updated: string;
}

export interface StudioSettingsRecord {
  id: string;
  key: string;
  data_json?: any;
  description?: string;
  created: string;
  updated: string;
}

export function getMediaFileUrl(record: { id: string; [key: string]: any }, filename?: string): string | null {
  if (!record || !record.id || !filename) return null;
  const val = String(filename).trim();
  if (!val) return null;
  if (val.startsWith('http://') || val.startsWith('https://') || val.startsWith('data:')) {
    return val;
  }
  return pbMedia.files.getURL(record as any, val);
}


