"use client";

import React, { useState, useRef } from 'react';
import {
  X,
  UploadCloud,
  FileCheck,
  AlertCircle,
  Loader2,
  CheckCircle2,
  Briefcase,
  Users,
  MessageSquare,
  FileSpreadsheet
} from 'lucide-react';

interface LinkedInImportTabProps {
  isLight: boolean;
  onImportSuccess?: () => void;
}

export function LinkedInImportTab({ isLight, onImportSuccess }: LinkedInImportTabProps) {
  const [connectionsFile, setConnectionsFile] = useState<File | null>(null);
  const [invitationsFile, setInvitationsFile] = useState<File | null>(null);
  const [messagesFile, setMessagesFile] = useState<File | null>(null);

  const [isUploading, setIsUploading] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<{
    totalContactsMapped: number;
    createdCount: number;
    updatedCount: number;
    totalExistingContacts: number;
  } | null>(null);

  const multiInputRef = useRef<HTMLInputElement>(null);
  const connInputRef = useRef<HTMLInputElement>(null);
  const invInputRef = useRef<HTMLInputElement>(null);
  const msgInputRef = useRef<HTMLInputElement>(null);

  const handleAssignFiles = (files: FileList | File[]) => {
    setErrorMessage(null);
    setStatusMessage(null);

    Array.from(files).forEach((f) => {
      const name = f.name.toLowerCase();
      if (name.includes('connections') || name.includes('kontakte')) {
        setConnectionsFile(f);
      } else if (name.includes('invitations') || name.includes('einladungen')) {
        setInvitationsFile(f);
      } else if (name.includes('messages') || name.includes('nachrichten')) {
        setMessagesFile(f);
      }
    });
  };

  const handleDropMulti = (e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleAssignFiles(e.dataTransfer.files);
    }
  };

  const allFilesReady = Boolean(connectionsFile && invitationsFile && messagesFile);

  const handleStartImport = async () => {
    if (!allFilesReady || !connectionsFile || !invitationsFile || !messagesFile) return;

    setIsUploading(true);
    setErrorMessage(null);
    setStatusMessage('LinkedIn-Archiv wird eingelesen, Chatverläufe zusammengeführt und mit PocketBase synchronisiert...');
    setImportResult(null);

    try {
      const formData = new FormData();
      formData.append('connections', connectionsFile);
      formData.append('invitations', invitationsFile);
      formData.append('messages', messagesFile);

      const res = await fetch('/api/contacts/linkedin-import', {
        method: 'POST',
        body: formData,
      });

      const data = await res.json();

      if (!res.ok || !data.success) {
        throw new Error(data.error || 'Fehler beim Ausführen des Imports.');
      }

      setImportResult(data);
      setStatusMessage('LinkedIn-Import erfolgreich abgeschlossen!');
      onImportSuccess?.();
    } catch (err: any) {
      setErrorMessage(err.message || 'Unerwarteter Fehler.');
      setStatusMessage(null);
    } finally {
      setIsUploading(false);
    }
  };

  const handleReset = () => {
    setConnectionsFile(null);
    setInvitationsFile(null);
    setMessagesFile(null);
    setImportResult(null);
    setStatusMessage(null);
    setErrorMessage(null);
  };

  return (
    <div className="space-y-4">
      <div>
        <h3 className={`text-xs font-bold ${isLight ? 'text-zinc-800' : 'text-zinc-200'} flex items-center gap-1.5`}>
          <Briefcase className="w-4 h-4 text-accent-main" />
          <span>LinkedIn Datenarchiv Import</span>
        </h3>
        <p className="text-[11px] text-zinc-500 mt-0.5">
          Füge die drei LinkedIn-Exportdateien ein. Sobald alle 3 Dateien erkannt sind, wird der Import inklusive Chatverläufen und Statusabgleich ausgeführt.
        </p>
      </div>

      {/* Sammel-Drop-Zone */}
      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={handleDropMulti}
        onClick={() => multiInputRef.current?.click()}
        className={`border-2 border-dashed rounded-xl p-4 text-center cursor-pointer transition flex flex-col items-center justify-center gap-2 ${
          isLight
            ? 'border-zinc-300 bg-zinc-50 hover:bg-zinc-100/70 text-zinc-600'
            : 'border-zinc-800 bg-zinc-900/40 hover:bg-zinc-900/70 text-zinc-400'
        }`}
      >
        <UploadCloud className="w-7 h-7 text-accent-main" />
        <div>
          <span className="text-xs font-semibold text-accent-main">
            Alle 3 Dateien hier hineinziehen
          </span>
          <span className="text-xs text-zinc-400"> oder klicken zum gemeinsamen Auswählen</span>
        </div>
        <p className="text-[10px] text-zinc-400">
          Erkennt automatisch Connections.csv, Invitations.csv und messages.csv
        </p>
        <input
          ref={multiInputRef}
          type="file"
          multiple
          accept=".csv"
          className="hidden"
          onChange={(e) => {
            if (e.target.files) handleAssignFiles(e.target.files);
          }}
        />
      </div>

      {/* 3 Kacheln Status */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-2.5">
        {/* 1. Connections */}
        <div
          onClick={() => !connectionsFile && connInputRef.current?.click()}
          className={`p-3 rounded-xl border flex flex-col justify-between transition relative ${
            connectionsFile
              ? isLight
                ? 'border-emerald-200 bg-emerald-50/50'
                : 'border-emerald-900/50 bg-emerald-950/20'
              : isLight
              ? 'border-zinc-200 bg-white hover:border-zinc-300 cursor-pointer'
              : 'border-zinc-800 bg-zinc-900/60 hover:border-zinc-700 cursor-pointer'
          }`}
        >
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <Users className={`w-4 h-4 ${connectionsFile ? 'text-emerald-500' : 'text-zinc-400'}`} />
              <span className="text-xs font-bold">Connections.csv</span>
            </div>
            {connectionsFile ? (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setConnectionsFile(null);
                }}
                className="text-zinc-400 hover:text-rose-500"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            ) : null}
          </div>

          <div className="min-h-[34px] flex items-center">
            {connectionsFile ? (
              <div className="flex items-center gap-1.5 text-[11px] text-emerald-600 font-semibold truncate">
                <FileCheck className="w-3.5 h-3.5 shrink-0" />
                <span className="truncate">{connectionsFile.name}</span>
              </div>
            ) : (
              <span className="text-[11px] text-zinc-400 italic">Fehlt noch (klicken zum Wählen)</span>
            )}
          </div>
          <input
            ref={connInputRef}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={(e) => {
              if (e.target.files?.[0]) setConnectionsFile(e.target.files[0]);
            }}
          />
        </div>

        {/* 2. Invitations */}
        <div
          onClick={() => !invitationsFile && invInputRef.current?.click()}
          className={`p-3 rounded-xl border flex flex-col justify-between transition relative ${
            invitationsFile
              ? isLight
                ? 'border-emerald-200 bg-emerald-50/50'
                : 'border-emerald-900/50 bg-emerald-950/20'
              : isLight
              ? 'border-zinc-200 bg-white hover:border-zinc-300 cursor-pointer'
              : 'border-zinc-800 bg-zinc-900/60 hover:border-zinc-700 cursor-pointer'
          }`}
        >
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <FileSpreadsheet className={`w-4 h-4 ${invitationsFile ? 'text-emerald-500' : 'text-zinc-400'}`} />
              <span className="text-xs font-bold">Invitations.csv</span>
            </div>
            {invitationsFile ? (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setInvitationsFile(null);
                }}
                className="text-zinc-400 hover:text-rose-500"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            ) : null}
          </div>

          <div className="min-h-[34px] flex items-center">
            {invitationsFile ? (
              <div className="flex items-center gap-1.5 text-[11px] text-emerald-600 font-semibold truncate">
                <FileCheck className="w-3.5 h-3.5 shrink-0" />
                <span className="truncate">{invitationsFile.name}</span>
              </div>
            ) : (
              <span className="text-[11px] text-zinc-400 italic">Fehlt noch (klicken zum Wählen)</span>
            )}
          </div>
          <input
            ref={invInputRef}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={(e) => {
              if (e.target.files?.[0]) setInvitationsFile(e.target.files[0]);
            }}
          />
        </div>

        {/* 3. Messages */}
        <div
          onClick={() => !messagesFile && msgInputRef.current?.click()}
          className={`p-3 rounded-xl border flex flex-col justify-between transition relative ${
            messagesFile
              ? isLight
                ? 'border-emerald-200 bg-emerald-50/50'
                : 'border-emerald-900/50 bg-emerald-950/20'
              : isLight
              ? 'border-zinc-200 bg-white hover:border-zinc-300 cursor-pointer'
              : 'border-zinc-800 bg-zinc-900/60 hover:border-zinc-700 cursor-pointer'
          }`}
        >
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <MessageSquare className={`w-4 h-4 ${messagesFile ? 'text-emerald-500' : 'text-zinc-400'}`} />
              <span className="text-xs font-bold">messages.csv</span>
            </div>
            {messagesFile ? (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setMessagesFile(null);
                }}
                className="text-zinc-400 hover:text-rose-500"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            ) : null}
          </div>

          <div className="min-h-[34px] flex items-center">
            {messagesFile ? (
              <div className="flex items-center gap-1.5 text-[11px] text-emerald-600 font-semibold truncate">
                <FileCheck className="w-3.5 h-3.5 shrink-0" />
                <span className="truncate">{messagesFile.name}</span>
              </div>
            ) : (
              <span className="text-[11px] text-zinc-400 italic">Fehlt noch (klicken zum Wählen)</span>
            )}
          </div>
          <input
            ref={msgInputRef}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={(e) => {
              if (e.target.files?.[0]) setMessagesFile(e.target.files[0]);
            }}
          />
        </div>
      </div>

      {/* Fehler & Statusmeldungen */}
      {errorMessage && (
        <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-600 text-xs flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{errorMessage}</span>
        </div>
      )}

      {statusMessage && (
        <div className="p-3 rounded-xl bg-blue-500/10 border border-blue-500/20 text-blue-600 text-xs flex items-center gap-2">
          {isUploading ? <Loader2 className="w-4 h-4 animate-spin shrink-0" /> : <CheckCircle2 className="w-4 h-4 shrink-0" />}
          <span>{statusMessage}</span>
        </div>
      )}

      {/* Ergebnis-Zusammenfassung */}
      {importResult && (
        <div className={`p-4 rounded-xl border space-y-2 ${isLight ? 'bg-zinc-50 border-zinc-200' : 'bg-zinc-900/60 border-zinc-800'}`}>
          <div className="flex items-center gap-2 text-emerald-600 font-bold text-xs">
            <CheckCircle2 className="w-4 h-4" />
            <span>Import-Ergebnis</span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1 font-mono text-[11px]">
            <div className={`p-2 rounded-lg ${isLight ? 'bg-white' : 'bg-zinc-950'} border border-zinc-200 dark:border-zinc-800`}>
              <span className="text-zinc-400 block text-[10px]">Verarbeitet</span>
              <span className="font-bold text-sm text-zinc-700 dark:text-zinc-200">{importResult.totalContactsMapped}</span>
            </div>
            <div className={`p-2 rounded-lg ${isLight ? 'bg-white' : 'bg-zinc-950'} border border-zinc-200 dark:border-zinc-800`}>
              <span className="text-emerald-500 block text-[10px]">Neu angelegt</span>
              <span className="font-bold text-sm text-emerald-600">{importResult.createdCount}</span>
            </div>
            <div className={`p-2 rounded-lg ${isLight ? 'bg-white' : 'bg-zinc-950'} border border-zinc-200 dark:border-zinc-800`}>
              <span className="text-blue-500 block text-[10px]">Aktualisiert</span>
              <span className="font-bold text-sm text-blue-600">{importResult.updatedCount}</span>
            </div>
            <div className={`p-2 rounded-lg ${isLight ? 'bg-white' : 'bg-zinc-950'} border border-zinc-200 dark:border-zinc-800`}>
              <span className="text-zinc-400 block text-[10px]">Gesamtbestand</span>
              <span className="font-bold text-sm text-zinc-700 dark:text-zinc-200">{importResult.totalExistingContacts}</span>
            </div>
          </div>
        </div>
      )}

      {/* Aktions-Leiste */}
      <div className="flex items-center justify-between pt-2">
        <button
          type="button"
          onClick={handleReset}
          disabled={isUploading || (!connectionsFile && !invitationsFile && !messagesFile)}
          className="text-xs text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 disabled:opacity-30 cursor-pointer"
        >
          Dateien zurücksetzen
        </button>

        <button
          type="button"
          disabled={!allFilesReady || isUploading}
          onClick={handleStartImport}
          className={`px-4 py-2 rounded-xl text-xs font-bold flex items-center gap-2 transition shadow-md cursor-pointer ${
            allFilesReady && !isUploading
              ? 'bg-accent-main text-white hover:bg-accent-main-hover'
              : 'bg-zinc-200 dark:bg-zinc-800 text-zinc-400 cursor-not-allowed'
          }`}
        >
          {isUploading ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>Importiert...</span>
            </>
          ) : (
            <>
              <Briefcase className="w-4 h-4" />
              <span>{allFilesReady ? 'LinkedIn-Import jetzt ausführen' : 'Warte auf 3 Dateien...'}</span>
            </>
          )}
        </button>
      </div>
    </div>
  );
}
