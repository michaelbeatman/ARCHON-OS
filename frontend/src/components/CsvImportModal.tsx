"use client";

import React, { useState, useRef } from 'react';
import { pb, KontaktRecord } from '@/lib/pocketbase';
import { X, UploadCloud, FileText, CheckCircle2, AlertCircle, Loader2, ArrowRight, Table, Layers } from 'lucide-react';

interface CsvImportModalProps {
  isOpen: boolean;
  onClose: () => void;
  onImportComplete: () => void;
  themeMode?: 'light' | 'dark';
}

export function CsvImportModal({
  isOpen,
  onClose,
  onImportComplete,
  themeMode = 'light'
}: CsvImportModalProps) {
  const [step, setStep] = useState<'upload' | 'mapping' | 'importing' | 'complete'>('upload');
  const [file, setFile] = useState<File | null>(null);
  const [csvHeaders, setCsvHeaders] = useState<string[]>([]);
  const [csvRows, setCsvRows] = useState<string[][]>([]);
  const [mapping, setMapping] = useState<{
    name: string;
    firstName: string;
    lastName: string;
    unternehmen: string;
    rolle: string;
    vernetzt_am: string;
    region: string;
  }>({
    name: '',
    firstName: '',
    lastName: '',
    unternehmen: '',
    rolle: '',
    vernetzt_am: '',
    region: ''
  });

  const [progress, setProgress] = useState(0);
  const [totalCount, setTotalCount] = useState(0);
  const [importedCount, setImportedCount] = useState(0);
  const [failedCount, setFailedCount] = useState(0);
  const [errorList, setErrorList] = useState<string[]>([]);

  const fileInputRef = useRef<HTMLInputElement>(null);

  if (!isOpen) return null;

  const isLight = themeMode === 'light';

  // Parse CSV line taking quotes into account
  const parseCsvLine = (text: string, delimiter: string = ','): string[] => {
    const result: string[] = [];
    let cur = '';
    let inQuotes = false;

    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (c === '"') {
        inQuotes = !inQuotes;
      } else if (c === delimiter && !inQuotes) {
        result.push(cur.trim().replace(/^"(.*)"$/, '$1'));
        cur = '';
      } else {
        cur += c;
      }
    }
    result.push(cur.trim().replace(/^"(.*)"$/, '$1'));
    return result;
  };

  const handleFileSelect = (selectedFile: File) => {
    setFile(selectedFile);
    const reader = new FileReader();

    reader.onload = (e) => {
      const text = e.target?.result as string;
      if (!text) return;

      const lines = text.split(/\r?\n/).filter(line => line.trim().length > 0);
      if (lines.length === 0) return;

      // Auto-detect separator (, or ;)
      const sample = lines[0];
      const delimiter = sample.includes(';') ? ';' : ',';

      const headers = parseCsvLine(lines[0], delimiter);
      const rows = lines.slice(1).map(line => parseCsvLine(line, delimiter));

      setCsvHeaders(headers);
      setCsvRows(rows);

      // Auto-guess mapping for common LinkedIn export column names
      const autoMap = {
        name: '',
        firstName: '',
        lastName: '',
        unternehmen: '',
        rolle: '',
        vernetzt_am: '',
        region: ''
      };

      headers.forEach(h => {
        const lower = h.toLowerCase();
        if (lower.includes('first name') || lower.includes('vorname')) autoMap.firstName = h;
        else if (lower.includes('last name') || lower.includes('nachname')) autoMap.lastName = h;
        else if (lower === 'name' || lower.includes('full name')) autoMap.name = h;
        else if (lower.includes('company') || lower.includes('firma') || lower.includes('unternehmen')) autoMap.unternehmen = h;
        else if (lower.includes('position') || lower.includes('title') || lower.includes('rolle')) autoMap.rolle = h;
        else if (lower.includes('connected') || lower.includes('vernetzt') || lower.includes('date')) autoMap.vernetzt_am = h;
        else if (lower.includes('location') || lower.includes('region') || lower.includes('ort')) autoMap.region = h;
      });

      setMapping(autoMap);
      setStep('mapping');
    };

    reader.readAsText(selectedFile);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFileSelect(e.dataTransfer.files[0]);
    }
  };

  const startBatchImport = async () => {
    setStep('importing');
    setTotalCount(csvRows.length);
    let success = 0;
    let failed = 0;
    const errors: string[] = [];

    for (let i = 0; i < csvRows.length; i++) {
      const row = csvRows[i];

      // Build name
      let fullName = '';
      if (mapping.name && mapping.name !== 'none') {
        const colIdx = csvHeaders.indexOf(mapping.name);
        if (colIdx >= 0) fullName = row[colIdx] || '';
      }
      if (!fullName) {
        let fn = '';
        let ln = '';
        if (mapping.firstName && mapping.firstName !== 'none') {
          const idx = csvHeaders.indexOf(mapping.firstName);
          if (idx >= 0) fn = row[idx] || '';
        }
        if (mapping.lastName && mapping.lastName !== 'none') {
          const idx = csvHeaders.indexOf(mapping.lastName);
          if (idx >= 0) ln = row[idx] || '';
        }
        fullName = `${fn} ${ln}`.trim();
      }

      if (!fullName) {
        fullName = `Kontakt ${i + 1}`;
      }

      // Build other fields
      const getVal = (colName: string) => {
        if (!colName || colName === 'none') return '';
        const idx = csvHeaders.indexOf(colName);
        return idx >= 0 ? row[idx] || '' : '';
      };

      const unternehmen = getVal(mapping.unternehmen);
      const rolle = getVal(mapping.rolle);
      const region = getVal(mapping.region);
      const vernetztRaw = getVal(mapping.vernetzt_am);

      let vernetzt_am = '';
      if (vernetztRaw) {
        const parsedDate = new Date(vernetztRaw);
        if (!isNaN(parsedDate.getTime())) {
          vernetzt_am = parsedDate.toISOString().split('T')[0];
        }
      }

      try {
        await pb.collection('Kontakte').create({
          name: fullName,
          unternehmen: unternehmen || undefined,
          rolle: rolle || undefined,
          region: region || undefined,
          vernetzt_am: vernetzt_am || undefined,
          status: vernetzt_am ? 'Vernetzt' : 'Unvernetzt',
          rating: 3,
          naechster_schritt: 'Erstnachricht verfassen'
        });
        success++;
      } catch (err: any) {
        failed++;
        errors.push(`Zeile ${i + 2} (${fullName}): ${err.message || 'Fehler beim Erstellen'}`);
      }

      setImportedCount(success);
      setFailedCount(failed);
      setProgress(Math.round(((i + 1) / csvRows.length) * 100));
    }

    setErrorList(errors);
    setStep('complete');
    onImportComplete();
  };

  const previewRows = csvRows.slice(0, 5);

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/70 backdrop-blur-md flex items-center justify-center p-4">
      <div className={`w-full max-w-2xl rounded-2xl border p-6 shadow-2xl space-y-5 animate-in zoom-in-95 duration-150 ${
        isLight ? 'bg-white border-zinc-200 text-zinc-900' : 'bg-zinc-900 border-zinc-800 text-zinc-100'
      }`}>

        {/* Header */}
        <div className="flex items-center justify-between border-b pb-3 border-zinc-200 dark:border-zinc-800">
          <div className="flex items-center gap-2">
            <UploadCloud className="w-5 h-5 text-emerald-600" />
            <h2 className="text-sm font-bold tracking-tight">LinkedIn CSV Import</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-zinc-200 dark:hover:bg-zinc-800 text-zinc-400 transition"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* STEP 1: UPLOAD DROPZONE */}
        {step === 'upload' && (
          <div className="space-y-4">
            <div
              onDragOver={(e) => e.preventDefault()}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition flex flex-col items-center justify-center gap-3 ${
                isLight
                  ? 'border-emerald-500/40 bg-emerald-50/50 hover:bg-emerald-50 hover:border-emerald-600'
                  : 'border-emerald-500/30 bg-emerald-950/20 hover:bg-emerald-950/40 hover:border-emerald-500/60'
              }`}
            >
              <div className="w-12 h-12 rounded-2xl bg-emerald-500/10 text-emerald-600 flex items-center justify-center font-bold text-xl shadow-lg shadow-emerald-500/10">
                📥
              </div>
              <div>
                <p className="font-bold text-sm">Ziehe deine LinkedIn CSV-Datei hierhin</p>
                <p className="text-xs text-zinc-400 mt-1">oder klicke, um eine Datei von deiner Festplatte auszuwählen</p>
              </div>
              <span className="text-[10px] font-mono px-2.5 py-1 rounded-full bg-zinc-200 dark:bg-zinc-800 text-zinc-500 font-semibold">
                Unterstützt .csv (z. B. Connections.csv)
              </span>
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv"
                className="hidden"
                onChange={(e) => e.target.files?.[0] && handleFileSelect(e.target.files[0])}
              />
            </div>
          </div>
        )}

        {/* STEP 2: MAPPING & PREVIEW */}
        {step === 'mapping' && (
          <div className="space-y-4 text-xs">
            <div className="flex items-center justify-between p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-600 font-mono">
              <span className="font-bold flex items-center gap-2">
                <FileText className="w-4 h-4" />
                {file?.name}
              </span>
              <span>{csvRows.length} Zeilen erkannt</span>
            </div>

            {/* Column Mapping Inputs */}
            <div className="space-y-2">
              <h3 className="font-bold text-xs uppercase tracking-wider text-zinc-400">Feld-Zuordnung (Mapping)</h3>
              <div className="grid grid-cols-2 gap-3 p-3 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-950/40">

                <div>
                  <label className="block text-[11px] font-bold mb-1">Vorname (First Name)</label>
                  <select
                    value={mapping.firstName}
                    onChange={(e) => setMapping({ ...mapping, firstName: e.target.value })}
                    className="w-full p-2 border rounded-lg text-xs bg-white dark:bg-zinc-900 border-zinc-300 dark:border-zinc-800"
                  >
                    <option value="none">-- Nicht zuordnen --</option>
                    {csvHeaders.map(h => <option key={h} value={h}>{h}</option>)}
                  </select>
                </div>

                <div>
                  <label className="block text-[11px] font-bold mb-1">Nachname (Last Name)</label>
                  <select
                    value={mapping.lastName}
                    onChange={(e) => setMapping({ ...mapping, lastName: e.target.value })}
                    className="w-full p-2 border rounded-lg text-xs bg-white dark:bg-zinc-900 border-zinc-300 dark:border-zinc-800"
                  >
                    <option value="none">-- Nicht zuordnen --</option>
                    {csvHeaders.map(h => <option key={h} value={h}>{h}</option>)}
                  </select>
                </div>

                <div>
                  <label className="block text-[11px] font-bold mb-1">Unternehmen (Company)</label>
                  <select
                    value={mapping.unternehmen}
                    onChange={(e) => setMapping({ ...mapping, unternehmen: e.target.value })}
                    className="w-full p-2 border rounded-lg text-xs bg-white dark:bg-zinc-900 border-zinc-300 dark:border-zinc-800"
                  >
                    <option value="none">-- Nicht zuordnen --</option>
                    {csvHeaders.map(h => <option key={h} value={h}>{h}</option>)}
                  </select>
                </div>

                <div>
                  <label className="block text-[11px] font-bold mb-1">Rolle / Position</label>
                  <select
                    value={mapping.rolle}
                    onChange={(e) => setMapping({ ...mapping, rolle: e.target.value })}
                    className="w-full p-2 border rounded-lg text-xs bg-white dark:bg-zinc-900 border-zinc-300 dark:border-zinc-800"
                  >
                    <option value="none">-- Nicht zuordnen --</option>
                    {csvHeaders.map(h => <option key={h} value={h}>{h}</option>)}
                  </select>
                </div>

                <div>
                  <label className="block text-[11px] font-bold mb-1">Vernetzt am (Connected On)</label>
                  <select
                    value={mapping.vernetzt_am}
                    onChange={(e) => setMapping({ ...mapping, vernetzt_am: e.target.value })}
                    className="w-full p-2 border rounded-lg text-xs bg-white dark:bg-zinc-900 border-zinc-300 dark:border-zinc-800"
                  >
                    <option value="none">-- Nicht zuordnen --</option>
                    {csvHeaders.map(h => <option key={h} value={h}>{h}</option>)}
                  </select>
                </div>

                <div>
                  <label className="block text-[11px] font-bold mb-1">Region / Ort</label>
                  <select
                    value={mapping.region}
                    onChange={(e) => setMapping({ ...mapping, region: e.target.value })}
                    className="w-full p-2 border rounded-lg text-xs bg-white dark:bg-zinc-900 border-zinc-300 dark:border-zinc-800"
                  >
                    <option value="none">-- Nicht zuordnen --</option>
                    {csvHeaders.map(h => <option key={h} value={h}>{h}</option>)}
                  </select>
                </div>

              </div>
            </div>

            {/* 5-Row Preview Table */}
            <div className="space-y-1.5">
              <h4 className="font-bold text-[11px] text-zinc-400 flex items-center gap-1.5">
                <Table className="w-3.5 h-3.5" />
                <span>Vorschau der ersten 5 Zeilen</span>
              </h4>
              <div className="border rounded-xl overflow-x-auto max-h-36 border-zinc-200 dark:border-zinc-800">
                <table className="w-full text-left text-[11px]">
                  <thead className="bg-zinc-100 dark:bg-zinc-950 font-bold border-b border-zinc-200 dark:border-zinc-800">
                    <tr>
                      {csvHeaders.slice(0, 5).map(h => <th key={h} className="p-2 truncate">{h}</th>)}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800/60 font-mono">
                    {previewRows.map((row, idx) => (
                      <tr key={idx}>
                        {row.slice(0, 5).map((cell, cIdx) => (
                          <td key={cIdx} className="p-2 truncate max-w-[120px]">{cell}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="pt-3 border-t border-zinc-200 dark:border-zinc-800 flex justify-between">
              <button
                type="button"
                onClick={() => setStep('upload')}
                className="px-4 py-2 rounded-lg bg-zinc-200 dark:bg-zinc-800 font-semibold hover:bg-zinc-300 dark:hover:bg-zinc-700 transition"
              >
                Zurück
              </button>
              <button
                type="button"
                onClick={startBatchImport}
                className="px-5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold transition shadow-md flex items-center gap-2"
              >
                <span>Import starten ({csvRows.length} Kontakte)</span>
                <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}

        {/* STEP 3: IMPORTING PROGRESS */}
        {step === 'importing' && (
          <div className="py-8 space-y-4 text-center">
            <Loader2 className="w-10 h-10 animate-spin text-emerald-600 mx-auto" />
            <h3 className="font-bold text-sm">Importiere Kontakte in PocketBase...</h3>

            {/* Progress Bar */}
            <div className="w-full bg-zinc-200 dark:bg-zinc-800 rounded-full h-3 overflow-hidden max-w-md mx-auto">
              <div
                className="bg-emerald-500 h-full transition-all duration-200"
                style={{ width: `${progress}%` }}
              />
            </div>

            <p className="font-mono text-xs text-zinc-400">
              {importedCount} von {totalCount} verarbeitet ({progress}%)
            </p>
          </div>
        )}

        {/* STEP 4: COMPLETE SUMMARY */}
        {step === 'complete' && (
          <div className="space-y-4 text-xs">
            <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-600 text-center space-y-1">
              <CheckCircle2 className="w-8 h-8 mx-auto text-emerald-600" />
              <h3 className="font-bold text-base">Import erfolgreich abgeschlossen!</h3>
              <p className="font-mono text-xs">
                {importedCount} Kontakte neu zu PocketBase hinzugefügt.
              </p>
            </div>

            {failedCount > 0 && (
              <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-600 space-y-1">
                <p className="font-bold flex items-center gap-1.5">
                  <AlertCircle className="w-4 h-4" />
                  <span>{failedCount} Zeilen konnten nicht importiert werden:</span>
                </p>
                <div className="max-h-24 overflow-y-auto font-mono text-[10px] space-y-0.5">
                  {errorList.map((err, idx) => <p key={idx}>{err}</p>)}
                </div>
              </div>
            )}

            <div className="pt-3 border-t border-zinc-200 dark:border-zinc-800 flex justify-end">
              <button
                type="button"
                onClick={onClose}
                className="px-5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold transition shadow-md"
              >
                Fertigstellen & Schließen
              </button>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
