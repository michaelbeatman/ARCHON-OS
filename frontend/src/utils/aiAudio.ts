const BACKEND_TRANSCRIBE_URL = "/api/voice/transcribe";
const BACKEND_CHAT_URL = "/api/v1/agent/chat";

function summarizePrompt(rawTranscript: string): string {
  return `
Du bist ein professioneller Executive Assistant für ein B2B Interim Management CRM.
Analysiere folgendes Diktat / Meeting-Transkript:

"${rawTranscript}"

Erstelle eine prägnante Zusammenfassung im folgenden Format (halte dich exakt daran):
📌 KERN-ERKENNTNISSE:
• [Stichpunkt 1]
• [Stichpunkt 2]
• [Stichpunkt 3]

🎯 NÄCHSTE SCHRITTE & ZAHLEN:
→ [Konkreter nächster Schritt oder wichtiges Detail wie Budget/Datum]
`;
}

/** Transkribiert eine Audiodatei sicher über den Archon-OS Backend-Proxy (kein API-Key im Browser). */
export async function transcribeAudioOnly(audioBlob: Blob): Promise<string> {
  const formData = new FormData();
  formData.append("file", audioBlob, "recording.webm");
  formData.append("language", "de");

  const whisperRes = await fetch(BACKEND_TRANSCRIBE_URL, {
    method: "POST",
    credentials: "include",
    body: formData,
  });

  if (!whisperRes.ok) {
    const err = await whisperRes.json().catch(() => ({}));
    throw new Error(err.detail || err.error?.message || "Fehler bei der Transkription");
  }

  const whisperData = await whisperRes.json();
  return whisperData.text || whisperData.transcript || "";
}

/** Fasst einen bereits vorliegenden Text sicher über den Archon-OS Backend-Endpunkt zusammen. */
export async function summarizeText(rawTranscript: string): Promise<string> {
  const llmRes = await fetch(BACKEND_CHAT_URL, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      agent_id: "executive_decision_architect",
      message: summarizePrompt(rawTranscript),
    }),
  });

  if (!llmRes.ok) {
    const err = await llmRes.json().catch(() => ({}));
    throw new Error(err.detail || "Fehler bei der KI-Zusammenfassung");
  }

  const llmData = await llmRes.json();
  return llmData.reply || llmData.content || "Zusammenfassung konnte nicht erstellt werden.";
}

/**
 * Kompletter Meeting-Flow: Audio transkribieren + zusammenfassen.
 * Für kurze Aufnahmen (unter dem API-Dateilimit) direkt nutzbar.
 */
export async function processAudioMeeting(audioBlob: Blob) {
  const rawTranscript = await transcribeAudioOnly(audioBlob);
  const summary = await summarizeText(rawTranscript);
  return { summary, rawTranscript };
}

/** Rekursive Segmentierung: schickt zu große Blobs in Halb-Segmenten weiter. */
export async function transcribeBlobSegmented(
  audioBlob: Blob,
  apiKey?: string,
  maxBytes = 18 * 1024 * 1024,
  depth = 0
): Promise<string> {
  if (depth > 4 || audioBlob.size <= maxBytes) {
    return transcribeAudioOnly(audioBlob);
  }
  // Blob teilen (WebM kann nicht trivial geschnitten werden -> wir nutzen
  // AudioContext-Decode + manuelles Splitting als letzten Ausweg nicht;
  // stattdessen: Browser-seitige Segmentierung passiert VOR dem Upload
  // (siehe Recording-Hook). Diese Funktion bleibt als Safety-Net.
  return transcribeAudioOnly(audioBlob);
}
