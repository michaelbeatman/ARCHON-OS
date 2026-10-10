"use client";

import React, { useState } from 'react';
import { X, Code, Copy, Check, Terminal, ExternalLink } from 'lucide-react';

interface ApiPreviewModalProps {
  isOpen: boolean;
  onClose: () => void;
  themeMode?: 'light' | 'dark';
}

export function ApiPreviewModal({ isOpen, onClose, themeMode = 'light' }: ApiPreviewModalProps) {
  const [activeTab, setActiveTab] = useState<'js' | 'curl'>('js');
  const [copied, setCopied] = useState(false);

  if (!isOpen) return null;

  const isLight = themeMode === 'light';

  const jsSnippets = `// PocketBase JavaScript SDK (Collection: kontakte)
import PocketBase from 'pocketbase';

const pb = new PocketBase('http://localhost:8090');

// 1. Alle Kontakte abrufen
const records = await pb.collection('kontakte').getFullList({
  sort: '-updated',
});

// 2. Einzelnen Kontakt abrufen
const record = await pb.collection('kontakte').getOne('RECORD_ID');

// 3. Neuen Kontakt erstellen
const newRecord = await pb.collection('kontakte').create({
  name: 'Marcus Vance',
  unternehmen: 'Vance Capital',
  rolle: 'Managing Partner',
  region: 'Frankfurt',
  status: 'Interview vereinbart',
  rating: 5
});

// 4. Kontakt aktualisieren
await pb.collection('kontakte').update('RECORD_ID', {
  status: 'Gesperrt_1Jahr',
  einladung_zurueckgezogen_am: '${new Date().toISOString().split('T')[0]}'
});

// 5. Realtime-Subscription (Echtzeit-Updates)
pb.collection('kontakte').subscribe('*', (e) => {
  console.log(e.action, e.record);
});`;

  const curlSnippets = `# cURL HTTP API Examples (Collection: kontakte)

# 1. Alle Kontakte abrufen (GET)
curl -X GET "http://localhost:8090/api/collections/kontakte/records?sort=-updated"

# 2. Einzelnen Kontakt abrufen (GET)
curl -X GET "http://localhost:8090/api/collections/kontakte/records/RECORD_ID"

# 3. Neuen Kontakt erstellen (POST)
curl -X POST "http://localhost:8090/api/collections/kontakte/records" \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "Marcus Vance",
    "unternehmen": "Vance Capital",
    "status": "Vernetzt"
  }'

# 4. Kontakt aktualisieren (PATCH)
curl -X PATCH "http://localhost:8090/api/collections/kontakte/records/RECORD_ID" \\
  -H "Content-Type: application/json" \\
  -d '{
    "status": "Gesperrt_1Jahr"
  }'`;

  const codeToCopy = activeTab === 'js' ? jsSnippets : curlSnippets;

  const handleCopy = () => {
    navigator.clipboard.writeText(codeToCopy);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/70 backdrop-blur-md flex items-center justify-center p-4">
      <div className={`w-full max-w-3xl rounded-2xl border p-6 shadow-2xl space-y-4 animate-in zoom-in-95 duration-150 ${
        isLight ? 'bg-white border-zinc-200 text-zinc-900' : 'bg-zinc-900 border-zinc-800 text-zinc-100'
      }`}>

        {/* Header */}
        <div className="flex items-center justify-between border-b pb-3 border-zinc-200 dark:border-zinc-800">
          <div className="flex items-center gap-2">
            <Code className="w-5 h-5 text-emerald-600" />
            <h2 className="text-sm font-bold tracking-tight font-mono">&lt;/&gt; API Preview & Code Snippets</h2>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-600 border border-emerald-500/30 font-bold">
              kontakte
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-zinc-200 dark:hover:bg-zinc-800 text-zinc-400 transition"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Language Tabs & Copy Button */}
        <div className="flex items-center justify-between">
          <div className={`flex items-center p-1 rounded-lg border text-xs font-semibold ${
            isLight ? 'bg-zinc-100 border-zinc-300' : 'bg-zinc-950 border-zinc-800'
          }`}>
            <button
              onClick={() => setActiveTab('js')}
              className={`flex items-center gap-1.5 px-3 py-1 rounded-md transition font-mono ${
                activeTab === 'js'
                  ? isLight ? 'bg-white text-emerald-700 font-bold shadow-xs' : 'bg-zinc-800 text-emerald-300 font-bold'
                  : 'text-zinc-500 hover:text-zinc-800'
              }`}
            >
              <span>JS SDK</span>
            </button>
            <button
              onClick={() => setActiveTab('curl')}
              className={`flex items-center gap-1.5 px-3 py-1 rounded-md transition font-mono ${
                activeTab === 'curl'
                  ? isLight ? 'bg-white text-emerald-700 font-bold shadow-xs' : 'bg-zinc-800 text-emerald-300 font-bold'
                  : 'text-zinc-500 hover:text-zinc-800'
              }`}
            >
              <Terminal className="w-3.5 h-3.5" />
              <span>cURL</span>
            </button>
          </div>

          <button
            onClick={handleCopy}
            className="px-3 py-1.5 rounded-lg border text-xs font-semibold hover:bg-emerald-500/10 hover:border-emerald-500 text-emerald-600 border-emerald-500/30 flex items-center gap-1.5 transition"
          >
            {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copied ? 'Kopiert!' : 'Code kopieren'}</span>
          </button>
        </div>

        {/* Code Box */}
        <div className={`p-4 rounded-xl border font-mono text-xs overflow-x-auto max-h-96 leading-relaxed ${
          isLight ? 'bg-zinc-950 text-emerald-400 border-zinc-800' : 'bg-zinc-950 text-emerald-400 border-zinc-800'
        }`}>
          <pre>{codeToCopy}</pre>
        </div>

        {/* Footer Link */}
        <div className="pt-2 border-t border-zinc-200 dark:border-zinc-800 flex justify-between items-center text-xs">
          <a
            href="http://localhost:8090/_/"
            target="_blank"
            rel="noopener noreferrer"
            className="text-emerald-600 font-mono font-bold hover:underline flex items-center gap-1"
          >
            <span>PocketBase Admin UI Webhook Docs</span>
            <ExternalLink className="w-3.5 h-3.5" />
          </a>
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg bg-emerald-600 text-white font-bold hover:bg-emerald-500 transition shadow-md text-xs"
          >
            Schließen
          </button>
        </div>

      </div>
    </div>
  );
}
