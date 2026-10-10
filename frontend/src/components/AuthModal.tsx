"use client";

import React, { useState } from 'react';
import { pb } from '@/lib/pocketbase';
import { Lock, Mail, Key, ShieldCheck, AlertCircle, LogIn } from 'lucide-react';

interface AuthModalProps {
  isOpen: boolean;
  onLoginSuccess: () => void;
  themeMode?: 'light' | 'dark';
}

export function AuthModal({ isOpen, onLoginSuccess, themeMode = 'light' }: AuthModalProps) {
  const [identity, setIdentity] = useState('michaelbeatman@outlook.com');
  const [password, setPassword] = useState('Mackie.d8b');
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  if (!isOpen) return null;

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setErrorMsg('');

    try {
      // Try auth as superuser first
      try {
        await pb.collection('_superusers').authWithPassword(identity, password);
      } catch (e1) {
        // Fallback to regular users collection
        await pb.collection('users').authWithPassword(identity, password);
      }
      onLoginSuccess();
    } catch (err: any) {
      console.error('Login error:', err);
      setErrorMsg(err.message || 'Ungültige Zugangsdaten. Bitte E-Mail und Passwort prüfen.');
    } finally {
      setLoading(false);
    }
  };

  const isLight = themeMode === 'light';

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/70 backdrop-blur-md flex items-center justify-center p-4">
      <div className={`w-full max-w-md rounded-2xl border p-8 shadow-2xl space-y-6 animate-in zoom-in-95 duration-200 ${
        isLight ? 'bg-white border-zinc-200 text-zinc-900' : 'bg-zinc-900 border-zinc-800 text-zinc-100'
      }`}>
        
        {/* Header */}
        <div className="text-center space-y-2">
          <div className="w-12 h-12 rounded-2xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-600 flex items-center justify-center mx-auto text-xl font-bold font-mono shadow-lg shadow-emerald-500/10">
            PB
          </div>
          <h2 className="text-xl font-bold tracking-tight">PocketBase CRM Login</h2>
          <p className={`text-xs ${isLight ? 'text-zinc-500' : 'text-zinc-400'}`}>
            Melde dich an, um Zugriff auf die Kontakte-Collection zu erhalten.
          </p>
        </div>

        {errorMsg && (
          <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-600 text-xs flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        <form onSubmit={handleLogin} className="space-y-4">
          <div>
            <label className={`block text-xs font-bold uppercase tracking-wider mb-1.5 ${
              isLight ? 'text-zinc-700' : 'text-zinc-300'
            }`}>
              E-Mail / Benutzername
            </label>
            <div className="relative">
              <Mail className="w-4 h-4 absolute left-3 top-3 text-zinc-400" />
              <input
                type="text"
                required
                value={identity}
                onChange={(e) => setIdentity(e.target.value)}
                placeholder="michaelbeatman@outlook.com"
                className={`w-full pl-9 pr-3 py-2.5 border rounded-lg text-xs transition outline-none font-mono ${
                  isLight ? 'bg-zinc-50 border-zinc-300 text-zinc-900 focus:border-emerald-500' : 'bg-zinc-950 border-zinc-800 text-zinc-100 focus:border-emerald-500/60'
                }`}
              />
            </div>
          </div>

          <div>
            <label className={`block text-xs font-bold uppercase tracking-wider mb-1.5 ${
              isLight ? 'text-zinc-700' : 'text-zinc-300'
            }`}>
              Passwort
            </label>
            <div className="relative">
              <Key className="w-4 h-4 absolute left-3 top-3 text-zinc-400" />
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className={`w-full pl-9 pr-3 py-2.5 border rounded-lg text-xs transition outline-none font-mono ${
                  isLight ? 'bg-zinc-50 border-zinc-300 text-zinc-900 focus:border-emerald-500' : 'bg-zinc-950 border-zinc-800 text-zinc-100 focus:border-emerald-500/60'
                }`}
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs transition shadow-lg shadow-emerald-500/20 flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {loading ? <ShieldCheck className="w-4 h-4 animate-spin" /> : <LogIn className="w-4 h-4" />}
            <span>{loading ? 'Authentifiziere...' : 'Anmelden'}</span>
          </button>
        </form>

        <div className={`p-3 rounded-lg border text-[11px] font-mono text-center ${
          isLight ? 'bg-zinc-50 border-zinc-200 text-zinc-500' : 'bg-zinc-950/60 border-zinc-800 text-zinc-400'
        }`}>
          Voreingestellter Admin Account:<br />
          <span className="font-bold text-emerald-600">michaelbeatman@outlook.com</span>
        </div>

      </div>
    </div>
  );
}
