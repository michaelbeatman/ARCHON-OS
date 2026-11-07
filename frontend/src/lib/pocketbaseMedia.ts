export function getPocketbaseMediaUrl(): string {
  if (typeof window !== 'undefined') {
    // In browser, use the same-origin Next.js proxy route to guarantee 100% connectivity
    return `${window.location.origin}/api/media`;
  }
  return process.env.INTERNAL_POCKETBASE_MEDIA_URL || 'http://host.docker.internal:8092/api';
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

export interface LinkedinContentRecord {
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

export function getMediaFileUrl(record: Partial<MediaItemRecord | VideoBatchRecord>, filename?: string): string | null {
  if (!record || !record.id) return null;
  const targetFile = filename || (record as any).file || (record as any).output_video_file;
  if (!targetFile) return null;
  const collectionName = (record as any).collectionName || ((record as any).batch_type ? 'video_batches' : 'media_items');
  
  if (typeof window !== 'undefined') {
    return `/api/media/files/${collectionName}/${record.id}/${targetFile}`;
  }
  return `http://host.docker.internal:8092/api/files/${collectionName}/${record.id}/${targetFile}`;
}
