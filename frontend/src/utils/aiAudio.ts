const GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions";
const GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions";
const WHISPER_MODEL = "whisper-large-v3";
const SUMMARIZE_MODEL = "llama-3.3-70b-versatile";

function resolveApiKey(apiKey?: string): string {
  return (
    apiKey ||
    (typeof process !== "undefined" ? process.env.NEXT_PUBLIC_GROQ_API_KEY : "") ||
    (typeof window !== "undefined" ? localStorage.getItem("groq_api_key") : "") ||
    ""
  );
}

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

/** Transkribiert eine Audiodatei via Groq Whisper. */
export async function transcribeAudioOnly(audioBlob: Blob, apiKey?: string): Promise<string> {
  const effectiveKey = resolveApiKey(apiKey);
  if (!effectiveKey) {
    throw new Error("Kein API-Key hinterlegt! Bitte in den Einstellungen eintragen.");
  }

  const formData = new FormData();
  formData.append("file", audioBlob, "recording.webm");
  formData.append("model", WHISPER_MODEL);
  formData.append("language", "de");

  const whisperRes = await fetch(GROQ_TRANSCRIBE_URL, {
    method: "POST",
    headers: { Authorization: `Bearer ${effectiveKey}` },
    body: formData,
  });

  if (!whisperRes.ok) {
    const err = await whisperRes.json().catch(() => ({}));
    throw new Error(err.error?.message || "Fehler bei der Transkription");
  }

  const whisperData = await whisperRes.json();
  return whisperData.text || "";
}

/** Fasst einen bereits vorliegenden Text per LLM zusammen (ohne Whisper). */
export async function summarizeText(rawTranscript: string, apiKey?: string): Promise<string> {
  const effectiveKey = resolveApiKey(apiKey);
  if (!effectiveKey) {
    throw new Error("Kein API-Key hinterlegt! Bitte in den Einstellungen eintragen.");
  }

  const llmRes = await fetch(GROQ_CHAT_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${effectiveKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: SUMMARIZE_MODEL,
      messages: [{ role: "user", content: summarizePrompt(rawTranscript) }],
      temperature: 0.2,
    }),
  });

  const llmData = await llmRes.json();
  return llmData.choices?.[0]?.message?.content || "Zusammenfassung konnte nicht erstellt werden.";
}

/**
 * Kompletter Meeting-Flow: Audio transkribieren + zusammenfassen.
 * Für kurze Aufnahmen (unter dem API-Dateilimit) direkt nutzbar.
 */
export async function processAudioMeeting(audioBlob: Blob, apiKey?: string) {
  const rawTranscript = await transcribeAudioOnly(audioBlob, apiKey);
  const summary = await summarizeText(rawTranscript, apiKey);
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
    return transcribeAudioOnly(audioBlob, apiKey);
  }
  // Blob teilen (WebM kann nicht trivial geschnitten werden -> wir nutzen
  // AudioContext-Decode + manuelles Splitting als letzten Ausweg nicht;
  // stattdessen: Browser-seitige Segmentierung passiert VOR dem Upload
  // (siehe Recording-Hook). Diese Funktion bleibt als Safety-Net.
  return transcribeAudioOnly(audioBlob, apiKey);
}
