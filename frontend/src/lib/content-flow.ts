/**
 * Framework-unabhaengige Helfer fuer die Uebergabe zwischen dem
 * Media-/Video-Studio (`/crm`) und der Content-Maschine (`/content-studio`).
 * Kein Next.js-Navigation-API noetig: die Uebergabe laeuft ueber `?media=`.
 */

export const CONTENT_STUDIO_PATH = '/content-studio';
export const MEDIA_HANDOFF_PARAM = 'media';

/**
 * Liest die `media`-Query auf. Mehrere IDs (Batch) sind kommasepariert.
 * Default ist die aktuelle URL; SSR-safe, weil `window` guards sind.
 */
export function readMediaHandoff(
  search: string = typeof window === 'undefined' ? '' : window.location.search
): string[] {
  if (!search) return [];
  const raw = new URLSearchParams(search).get(MEDIA_HANDOFF_PARAM);
  if (!raw) return [];
  return Array.from(
    new Set(
      raw
        .split(',')
        .map((id) => id.trim())
        .filter(Boolean)
    )
  );
}

/** Ziel-Link fuer die Uebergabe einer einzelnen Media-ID oder eines Batches. */
export function buildMediaHandoffHref(ids: string | string[]): string {
  const list = (Array.isArray(ids) ? ids : [ids])
    .map((id) => id.trim())
    .filter(Boolean);
  if (list.length === 0) return CONTENT_STUDIO_PATH;
  const params = new URLSearchParams();
  params.set(MEDIA_HANDOFF_PARAM, list.join(','));
  return `${CONTENT_STUDIO_PATH}?${params.toString()}`;
}

/** Vorlage fuer die vorausgefuellten Quell-Notizen der Kampagne. */
export function buildMediaHandoffNote(ids: string[]): string {
  const list = ids.map((id) => id.trim()).filter(Boolean);
  if (list.length === 0) return '';
  const subject =
    list.length === 1
      ? `Media-ID ${list[0]}`
      : `${list.length} Medien (${list.join(', ')})`;
  return `Media-Übergabe aus dem Content Studio: ${subject}`;
}
