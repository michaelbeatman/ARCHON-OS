"use client";

import React, { useState } from 'react';
import { pb } from '@/lib/pocketbase';
import { User, LogOut, ExternalLink, Settings, Shield, ChevronDown, Edit3, Activity, Code, Upload, Palette, Briefcase } from 'lucide-react';

interface UserDropdownProps {
  user: any;
  onLogout: () => void;
  onOpenProfile: () => void;
  onOpenSettings: () => void;
  onOpenLogs?: () => void;
  onOpenApiPreview?: () => void;
  onOpenCsvImport?: () => void;
  onOpenLinkedInImport?: () => void;
  themeMode?: 'light' | 'dark';
}

export function UserDropdown({
  user,
  onLogout,
  onOpenProfile,
  onOpenSettings,
  onOpenLogs,
  onOpenApiPreview,
  onOpenCsvImport,
  onOpenLinkedInImport,
  themeMode = 'light'
}: UserDropdownProps) {
  const [open, setOpen] = useState(false);
  const isLight = themeMode === 'light';

  const userEmail = user?.email || 'michaelbeatman@outlook.com';
  const userName = user?.name || userEmail.split('@')[0];
  const userInitials = userName.substring(0, 2).toUpperCase();

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg border text-xs font-semibold transition ${
          isLight
            ? 'bg-zinc-50 border-zinc-300 text-zinc-800 hover:bg-zinc-100'
            : 'bg-zinc-950 border-zinc-800 text-zinc-200 hover:bg-zinc-900'
        }`}
      >
        <div className="w-6 h-6 rounded-md bg-accent-main text-white flex items-center justify-center font-mono text-[10px] font-bold shadow-xs">
          {userInitials}
        </div>
        <span className="max-w-[120px] truncate">{userName}</span>
        <ChevronDown className="w-3.5 h-3.5 text-zinc-400" />
      </button>

      {open && (
        <div
          onClick={() => setOpen(false)}
          className={`absolute right-0 top-10 z-50 w-64 rounded-xl border p-2 shadow-2xl space-y-1 animate-in fade-in zoom-in-95 duration-150 ${
            isLight ? 'bg-white border-zinc-200 text-zinc-900' : 'bg-zinc-900 border-zinc-800 text-zinc-100'
          }`}
        >
          {/* User Info Header */}
          <div className={`p-2.5 border-b rounded-lg ${
            isLight ? 'bg-zinc-50 border-zinc-200' : 'bg-zinc-950/60 border-zinc-800'
          }`}>
            <p className="text-xs font-bold truncate">{userName}</p>
            <p className="text-[10px] font-mono text-accent-main truncate">{userEmail}</p>
          </div>

          {/* Menu Items */}
          <button
            onClick={() => { setOpen(false); onOpenProfile(); }}
            className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition ${
              isLight ? 'hover:bg-zinc-100 text-zinc-700' : 'hover:bg-zinc-800 text-zinc-300'
            }`}
          >
            <Edit3 className="w-4 h-4 text-accent-main" />
            <span>Profil bearbeiten</span>
          </button>

          <a
            href="http://localhost:8090/_/"
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => setOpen(false)}
            className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs font-medium transition ${
              isLight ? 'hover:bg-zinc-100 text-zinc-700' : 'hover:bg-zinc-800 text-zinc-300'
            }`}
          >
            <span className="flex items-center gap-2.5">
              <Shield className="w-4 h-4 text-blue-600" />
              <span>PocketBase Admin UI</span>
            </span>
            <ExternalLink className="w-3.5 h-3.5 text-zinc-400" />
          </a>

          {/* NEW ITEMS BETWEEN POCKETBASE ADMIN UI AND EINSTELLUNGEN */}
          {onOpenApiPreview && (
            <button
              onClick={() => { setOpen(false); onOpenApiPreview(); }}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-mono font-bold transition ${
                isLight ? 'hover:bg-zinc-100 text-zinc-700' : 'hover:bg-zinc-800 text-zinc-300'
              }`}
            >
              <Code className="w-4 h-4 text-accent-main" />
              <span>&lt;/&gt; API preview</span>
            </button>
          )}

          {onOpenCsvImport && (
            <button
              onClick={() => { setOpen(false); onOpenCsvImport(); }}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition ${
                isLight ? 'hover:bg-zinc-100 text-zinc-700' : 'hover:bg-zinc-800 text-zinc-300'
              }`}
            >
              <Upload className="w-4 h-4 text-cyan-600" />
              <span>📥 Importieren (CSV)</span>
            </button>
          )}

          {onOpenLinkedInImport && (
            <button
              onClick={() => { setOpen(false); onOpenLinkedInImport(); }}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition ${
                isLight ? 'hover:bg-zinc-100 text-zinc-700' : 'hover:bg-zinc-800 text-zinc-300'
              }`}
            >
              <Briefcase className="w-4 h-4 text-emerald-500" />
              <span>💼 LinkedIn Archiv-Import</span>
            </button>
          )}

          <button
            onClick={() => { setOpen(false); onOpenSettings(); }}
            className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition ${
              isLight ? 'hover:bg-zinc-100 text-zinc-700' : 'hover:bg-zinc-800 text-zinc-300'
            }`}
          >
            <Palette className="w-4 h-4 text-accent-main" />
            <span>Design & Einstellungen</span>
          </button>

          {onOpenLogs && (
            <button
              onClick={() => { setOpen(false); onOpenLogs(); }}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition ${
                isLight ? 'hover:bg-zinc-100 text-zinc-700' : 'hover:bg-zinc-800 text-zinc-300'
              }`}
            >
              <Activity className="w-4 h-4 text-rose-500" />
              <span>System Logs</span>
            </button>
          )}

          <div className={`border-t my-1 ${isLight ? 'border-zinc-200' : 'border-zinc-800'}`} />

          <button
            onClick={() => { setOpen(false); onLogout(); }}
            className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-semibold text-rose-600 hover:bg-rose-500/10 transition"
          >
            <LogOut className="w-4 h-4 text-rose-600" />
            <span>Abmelden</span>
          </button>
        </div>
      )}
    </div>
  );
}
