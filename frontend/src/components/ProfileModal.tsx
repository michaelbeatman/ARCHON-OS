"use client";

import React, { useState } from 'react';
import { pb } from '@/lib/pocketbase';
import { X, User, Key, CheckCircle, AlertCircle, Loader2 } from 'lucide-react';

interface ProfileModalProps {
  isOpen: boolean;
  onClose: () => void;
  user: any;
  onUpdateSuccess: () => void;
  themeMode?: 'light' | 'dark';
}

export function ProfileModal({
  isOpen,
  onClose,
  user,
  onUpdateSuccess,
  themeMode = 'light'
}: ProfileModalProps) {
  const [name, setName] = useState(user?.name || '');
  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');
  const [oldPassword, setOldPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  if (!isOpen) return null;

  const isLight = themeMode === 'light';

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setErrorMsg('');
    setSuccessMsg('');

    if (password && password !== passwordConfirm) {
      setErrorMsg('Die neuen Passwörter stimmen nicht überein.');
      setLoading(false);
      return;
    }

    try {
      const updateData: any = {};
      if (name) updateData.name = name;
      if (password) {
        updateData.password = password;
        updateData.passwordConfirm = passwordConfirm;
        if (oldPassword) updateData.oldPassword = oldPassword;
      }

      if (user?.id) {
        // Try user collection first
        try {
          await pb.collection('users').update(user.id, updateData);
        } catch {
          // Fallback to superuser update if authenticated as admin
          if (pb.authStore.model?.collectionName === '_superusers') {
            await pb.collection('_superusers').update(user.id, updateData);
          }
        }
      }

      setSuccessMsg('Profil erfolgreich aktualisiert.');
      onUpdateSuccess();
      setTimeout(() => {
        onClose();
      }, 1200);
    } catch (err: any) {
      console.error('Profile update error:', err);
      setErrorMsg(err.message || 'Fehler beim Speichern des Profils.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/70 backdrop-blur-md flex items-center justify-center p-4">
      <div className={`w-full max-w-md rounded-2xl border p-6 shadow-2xl space-y-5 animate-in zoom-in-95 duration-150 ${
        isLight ? 'bg-white border-slate-200 text-slate-900' : 'bg-slate-900 border-slate-800 text-slate-100'
      }`}>
        
        {/* Header */}
        <div className="flex items-center justify-between border-b pb-3 border-slate-200 dark:border-slate-800">
          <div className="flex items-center gap-2">
            <User className="w-5 h-5 text-emerald-600" />
            <h2 className="text-sm font-bold tracking-tight">Profil bearbeiten</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-800 text-slate-400 transition"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {errorMsg && (
          <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-600 text-xs flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        {successMsg && (
          <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-600 text-xs flex items-center gap-2 font-semibold">
            <CheckCircle className="w-4 h-4 shrink-0" />
            <span>{successMsg}</span>
          </div>
        )}

        <form onSubmit={handleSave} className="space-y-4 text-xs">
          <div>
            <label className={`block font-bold mb-1 ${isLight ? 'text-slate-700' : 'text-slate-300'}`}>
              E-Mail Adresse (Read-only)
            </label>
            <input
              type="text"
              disabled
              value={user?.email || 'admin@archon.local'}
              className={`w-full px-3 py-2 border rounded-lg font-mono text-xs opacity-70 ${
                isLight ? 'bg-slate-100 border-slate-300 text-slate-600' : 'bg-slate-950 border-slate-800 text-slate-400'
              }`}
            />
          </div>

          <div>
            <label className={`block font-bold mb-1 ${isLight ? 'text-slate-700' : 'text-slate-300'}`}>
              Name / Anzeigename
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="z. B. Michael Beatman"
              className={`w-full px-3 py-2 border rounded-lg text-xs font-semibold focus:outline-none transition ${
                isLight ? 'bg-slate-50 border-slate-300 text-slate-900 focus:border-emerald-500' : 'bg-slate-950 border-slate-800 text-slate-100 focus:border-emerald-500/60'
              }`}
            />
          </div>

          <div className="pt-2 border-t border-slate-200 dark:border-slate-800 space-y-3">
            <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <Key className="w-3.5 h-3.5 text-amber-500" />
              <span>Passwort ändern (Optional)</span>
            </p>

            <div>
              <label className="block text-[11px] text-slate-500 mb-1">Neues Passwort</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Mindestens 8 Zeichen"
                className={`w-full px-3 py-2 border rounded-lg text-xs font-mono transition ${
                  isLight ? 'bg-slate-50 border-slate-300 text-slate-900' : 'bg-slate-950 border-slate-800 text-slate-100'
                }`}
              />
            </div>

            {password && (
              <div>
                <label className="block text-[11px] text-slate-500 mb-1">Passwort bestätigen</label>
                <input
                  type="password"
                  value={passwordConfirm}
                  onChange={(e) => setPasswordConfirm(e.target.value)}
                  placeholder="Passwort erneut eingeben"
                  className={`w-full px-3 py-2 border rounded-lg text-xs font-mono transition ${
                    isLight ? 'bg-slate-50 border-slate-300 text-slate-900' : 'bg-slate-950 border-slate-800 text-slate-100'
                  }`}
                />
              </div>
            )}
          </div>

          <div className="pt-3 border-t border-slate-200 dark:border-slate-800 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className={`px-4 py-2 rounded-lg font-semibold text-xs transition ${
                isLight ? 'bg-slate-200 text-slate-800 hover:bg-slate-300' : 'bg-slate-800 text-slate-200 hover:bg-slate-700'
              }`}
            >
              Abbrechen
            </button>
            <button
              type="submit"
              disabled={loading}
              className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs transition shadow-md flex items-center gap-1.5 disabled:opacity-50"
            >
              {loading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              <span>Speichern</span>
            </button>
          </div>
        </form>

      </div>
    </div>
  );
}
