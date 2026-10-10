"use client";

import React from 'react';
import { KontaktRecord } from '@/lib/pocketbase';
import { NachrichtenverlaufPanel } from './NachrichtenverlaufPanel';
import { X, MessageSquare } from 'lucide-react';

interface NachrichtenverlaufModalProps {
  isOpen: boolean;
  onClose: () => void;
  kontakt: KontaktRecord | null;
  onUpdate: (updatedKontakt: KontaktRecord) => void;
  themeMode?: 'light' | 'dark';
}

export function NachrichtenverlaufModal({
  isOpen,
  onClose,
  kontakt,
  onUpdate,
  themeMode = 'light'
}: NachrichtenverlaufModalProps) {
  if (!isOpen || !kontakt) return null;

  const isLight = themeMode === 'light';

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/70 backdrop-blur-md flex items-center justify-center p-4">
      <div className={`w-full max-w-2xl h-[85vh] rounded-2xl border p-5 shadow-2xl animate-in zoom-in-95 duration-150 flex flex-col ${
        isLight ? 'bg-white border-zinc-200 text-zinc-900' : 'bg-zinc-900 border-zinc-800 text-zinc-100'
      }`}>
        {/* Modal Header */}
        <div className="flex items-center justify-between pb-3 border-b border-zinc-200 dark:border-zinc-800 mb-3 shrink-0">
          <div className="flex items-center gap-2">
            <MessageSquare className="w-5 h-5 text-accent-main shrink-0" />
            <h2 className="font-bold text-base font-sans text-accent-main">
              {kontakt.name}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-full bg-accent-main text-white hover:opacity-90 transition shadow-xs cursor-pointer flex items-center justify-center"
            title="Schließen"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Reusable NachrichtenverlaufPanel Component */}
        <div className="flex-1 min-h-0 min-w-0 overflow-hidden">
          <NachrichtenverlaufPanel
            kontakt={kontakt}
            onUpdate={onUpdate}
            themeMode={themeMode}
          />
        </div>
      </div>
    </div>
  );
}
