'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import {
  Target,
  BarChart3,
  Users,
  Calendar,
  MessageSquare,
  Image as ImageIcon,
  Clapperboard,
  FileText,
  Database,
  Palette
} from 'lucide-react';
import ReportView from '@/components/ReportView';

export default function BerichtePage() {
  const [themeMode, setThemeMode] = useState<'dark' | 'light'>('dark');
  const isLight = themeMode === 'light';

  useEffect(() => {
    // Read theme mode from localStorage if available
    const stored = localStorage.getItem('archon_theme_mode');
    if (stored === 'light' || stored === 'dark') {
      setThemeMode(stored);
    }
  }, []);

  return (
    <div className={`flex h-screen w-screen overflow-hidden ${isLight ? 'bg-zinc-100 text-zinc-900' : 'bg-zinc-950 text-zinc-100'}`}>
      {/* LEFT SIDEBAR (CRM NAVIGATION) */}
      <aside className={`w-64 shrink-0 flex flex-col justify-between border-r no-print ${
        isLight ? 'bg-white border-zinc-200' : 'bg-zinc-900/90 border-zinc-800'
      }`}>
        <div>
          {/* Logo & Brand Header */}
          <div className="p-4 border-b border-zinc-800/40">
            <Link href="/crm" className="flex items-center gap-2 font-bold tracking-tight text-sm">
              <span className="text-xl">⚡</span>
              <div>
                <div className="text-xs font-mono uppercase text-indigo-400">ARCHON CRM</div>
                <div className="text-zinc-200 text-sm font-semibold">Management Suite</div>
              </div>
            </Link>
          </div>

          {/* Nav Items */}
          <nav className="p-3 space-y-1">
            <div className="pt-2 text-[10px] font-mono text-zinc-500 uppercase px-2">
              DATENBANK & CRM
            </div>

            <Link
              href="/crm"
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-semibold transition ${
                isLight
                  ? 'text-zinc-600 hover:text-zinc-900 hover:bg-zinc-100'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
              }`}
            >
              <Target className="w-4 h-4" />
              <span>Mission Control</span>
            </Link>

            <Link
              href="/crm"
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-semibold transition ${
                isLight
                  ? 'text-zinc-600 hover:text-zinc-900 hover:bg-zinc-100'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
              }`}
            >
              <BarChart3 className="w-4 h-4" />
              <span>Pipeline</span>
            </Link>

            <Link
              href="/crm"
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-semibold transition ${
                isLight
                  ? 'text-zinc-600 hover:text-zinc-900 hover:bg-zinc-100'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
              }`}
            >
              <Users className="w-4 h-4" />
              <span>Kontakte</span>
            </Link>

            <Link
              href="/crm"
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-semibold transition ${
                isLight
                  ? 'text-zinc-600 hover:text-zinc-900 hover:bg-zinc-100'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
              }`}
            >
              <Calendar className="w-4 h-4" />
              <span>Kalender</span>
            </Link>

            <Link
              href="/crm"
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-semibold transition ${
                isLight
                  ? 'text-zinc-600 hover:text-zinc-900 hover:bg-zinc-100'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
              }`}
            >
              <MessageSquare className="w-4 h-4" />
              <span>Alle Nachrichten</span>
            </Link>

            <Link
              href="/crm"
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-semibold transition ${
                isLight
                  ? 'text-zinc-600 hover:text-zinc-900 hover:bg-zinc-100'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
              }`}
            >
              <ImageIcon className="w-4 h-4" />
              <span>Media Board</span>
            </Link>

            <Link
              href="/crm"
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-semibold transition ${
                isLight
                  ? 'text-zinc-600 hover:text-zinc-900 hover:bg-zinc-100'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
              }`}
            >
              <Clapperboard className="w-4 h-4" />
              <span>Content Studio</span>
            </Link>

            {/* BERICHTE (ACTIVE ROUTE) */}
            <div
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-bold transition ${
                isLight
                  ? 'bg-indigo-50 border border-indigo-200 text-indigo-700 shadow-xs'
                  : 'bg-indigo-950/60 border border-indigo-500/40 text-indigo-400'
              }`}
            >
              <FileText className="w-4 h-4 text-indigo-500" />
              <span>Berichte</span>
              <span className="ml-auto text-[9px] font-mono px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300">
                WORM
              </span>
            </div>
          </nav>
        </div>

        {/* Footer */}
        <div className={`p-3 border-t text-[11px] font-mono space-y-1.5 ${
          isLight ? 'border-zinc-200 bg-zinc-50 text-zinc-600' : 'border-zinc-800/80 bg-zinc-950/40 text-zinc-400'
        }`}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 font-bold text-indigo-400">
              <Database className="w-3.5 h-3.5" />
              <span>berichte / WORM</span>
            </div>
            <span className="text-[9px] text-emerald-400">● aktiv</span>
          </div>
        </div>
      </aside>

      {/* MAIN REPORT VIEW */}
      <ReportView themeMode={themeMode} />
    </div>
  );
}
