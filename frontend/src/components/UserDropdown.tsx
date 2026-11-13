"use client";

import React, { useState } from 'react';
import { pb } from '@/lib/pocketbase';
import { User, LogOut, ExternalLink, Settings, Shield, ChevronDown, Edit3, Activity, Code, Upload, Palette } from 'lucide-react';

interface UserDropdownProps {
  user: any;
  onLogout: () => void;
  onOpenProfile: () => void;
  onOpenSettings: () => void;
  onOpenLogs?: () => void;
  onOpenApiPreview?: () => void;
  onOpenCsvImport?: () => void;
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
  themeMode = 'light'
}: UserDropdownProps) {
  const [open, setOpen] = useState(false);
  const isLight = themeMode === 'light';

  const userEmail = user?.email || 'admin@archon.local';
  const userName = user?.name || userEmail.split('@')[0];
  const userInitials = userName.substring(0, 2).toUpperCase();

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg border text-xs font-semibold transition ${
          isLight
            ? 'bg-slate-50 border-slate-300 text-slate-800 hover:bg-slate-100'
            : 'bg-slate-950 border-slate-800 text-slate-200 hover:bg-slate-900'
        }`}
      >
        <div className="w-6 h-6 rounded-md bg-accent-main text-white flex items-center justify-center font-mono text-[10px] font-bold shadow-xs">
          {userInitials}
        </div>
        <span className="max-w-[120px] truncate">{userName}</span>
        <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
      </button>

      {open && (
        <div
          onClick={() => setOpen(false)}
          className={`absolute right-0 top-10 z-50 w-64 rounded-xl border p-2 shadow-2xl space-y-1 animate-in fade-in zoom-in-95 duration-150 ${
            isLight ? 'bg-white border-slate-200 text-slate-900' : 'bg-slate-900 border-slate-800 text-slate-100'
          }`}
        >
          {/* User Info Header */}
          <div className={`p-2.5 border-b rounded-lg ${
            isLight ? 'bg-slate-50 border-slate-200' : 'bg-slate-950/60 border-slate-800'
          }`}>
            <p className="text-xs font-bold truncate">{userName}</p>
            <p className="text-[10px] font-mono text-accent-main truncate">{userEmail}</p>
          </div>

          {/* Menu Items */}
          <button
            onClick={() => { setOpen(false); onOpenProfile(); }}
            className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition ${
              isLight ? 'hover:bg-slate-100 text-slate-700' : 'hover:bg-slate-800 text-slate-300'
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
              isLight ? 'hover:bg-slate-100 text-slate-700' : 'hover:bg-slate-800 text-slate-300'
            }`}
          >
            <span className="flex items-center gap-2.5">
              <Shield className="w-4 h-4 text-blue-600" />
              <span>PocketBase Admin UI</span>
            </span>
            <ExternalLink className="w-3.5 h-3.5 text-slate-400" />
          </a>

          {/* NEW ITEMS BETWEEN POCKETBASE ADMIN UI AND EINSTELLUNGEN */}
          {onOpenApiPreview && (
            <button
              onClick={() => { setOpen(false); onOpenApiPreview(); }}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-mono font-bold transition ${
                isLight ? 'hover:bg-slate-100 text-slate-700' : 'hover:bg-slate-800 text-slate-300'
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
                isLight ? 'hover:bg-slate-100 text-slate-700' : 'hover:bg-slate-800 text-slate-300'
              }`}
            >
              <Upload className="w-4 h-4 text-cyan-600" />
              <span>📥 Importieren (CSV)</span>
            </button>
          )}

          <button
            onClick={() => { setOpen(false); onOpenSettings(); }}
            className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition ${
              isLight ? 'hover:bg-slate-100 text-slate-700' : 'hover:bg-slate-800 text-slate-300'
            }`}
          >
            <Palette className="w-4 h-4 text-accent-main" />
            <span>Design & Einstellungen</span>
          </button>

          {onOpenLogs && (
            <button
              onClick={() => { setOpen(false); onOpenLogs(); }}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition ${
                isLight ? 'hover:bg-slate-100 text-slate-700' : 'hover:bg-slate-800 text-slate-300'
              }`}
            >
              <Activity className="w-4 h-4 text-rose-500" />
              <span>System Logs</span>
            </button>
          )}

          <div className={`border-t my-1 ${isLight ? 'border-slate-200' : 'border-slate-800'}`} />

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
