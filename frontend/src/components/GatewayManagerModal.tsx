"use client";

import React, { useEffect, useState, useCallback } from "react";
import { X, Play, Square, RefreshCw, Loader2, Settings2 } from "lucide-react";

interface GatewayProfile {
  id: string;
  status: "running" | "stopped" | "unknown";
  autostart: boolean;
  last_used: string | null;
}

interface GatewayManagerModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8501";

export const GatewayManagerModal: React.FC<GatewayManagerModalProps> = ({
  isOpen,
  onClose,
}) => {
  const [profiles, setProfiles] = useState<GatewayProfile[]>([]);
  const [idleTimeout, setIdleTimeout] = useState(30);
  const [idleInput, setIdleInput] = useState("30");
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savedTimeout, setSavedTimeout] = useState(false);

  const fetchProfiles = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/gateway/list`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setProfiles(data.profiles || []);
      setIdleTimeout(data.idle_timeout_minutes ?? 30);
      setIdleInput(String(data.idle_timeout_minutes ?? 30));
    } catch (e: any) {
      setError(`Fehler beim Laden: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) fetchProfiles();
  }, [isOpen, fetchProfiles]);

  const handleStart = async (profileId: string) => {
    setActionLoading(profileId);
    try {
      await fetch(`${API_BASE}/api/v1/gateway/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile_id: profileId }),
      });
      await fetchProfiles();
    } finally {
      setActionLoading(null);
    }
  };

  const handleStop = async (profileId: string) => {
    setActionLoading(profileId);
    try {
      await fetch(`${API_BASE}/api/v1/gateway/stop`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile_id: profileId }),
      });
      await fetchProfiles();
    } finally {
      setActionLoading(null);
    }
  };

  const handleStopAll = async () => {
    const running = profiles.filter(
      (p) => p.status === "running" && p.id !== "default"
    );
    for (const p of running) {
      await handleStop(p.id);
    }
  };

  const handleAutostartToggle = async (profileId: string, value: boolean) => {
    try {
      await fetch(`${API_BASE}/api/v1/gateway/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ autostart: { [profileId]: value } }),
      });
      setProfiles((prev) =>
        prev.map((p) => (p.id === profileId ? { ...p, autostart: value } : p))
      );
    } catch {}
  };

  const handleSaveTimeout = async () => {
    const val = parseInt(idleInput, 10);
    if (isNaN(val) || val < 1) return;
    try {
      await fetch(`${API_BASE}/api/v1/gateway/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ idle_timeout_minutes: val }),
      });
      setIdleTimeout(val);
      setSavedTimeout(true);
      setTimeout(() => setSavedTimeout(false), 1800);
    } catch {}
  };

  const runningCount = profiles.filter((p) => p.status === "running").length;

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative w-[680px] max-h-[85vh] bg-white rounded-2xl shadow-2xl flex flex-col overflow-hidden border border-zinc-200">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-100 bg-gradient-to-r from-indigo-50 to-white">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-indigo-600 flex items-center justify-center shadow-md shadow-indigo-200">
              <Settings2 className="w-5 h-5 text-white" />
            </div>
            <div>
              <h2 className="text-base font-bold text-zinc-800 tracking-tight">
                Gateway Manager
              </h2>
              <p className="text-xs text-zinc-400">
                {runningCount} aktiv · {profiles.length} Profile total
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={fetchProfiles}
              disabled={loading}
              className="p-2 rounded-lg hover:bg-zinc-100 text-zinc-400 hover:text-zinc-600 transition"
              title="Aktualisieren"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            </button>
            <button
              onClick={onClose}
              className="p-2 rounded-lg hover:bg-zinc-100 text-zinc-400 hover:text-zinc-600 transition"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Idle-Timeout Settings Bar */}
        <div className="px-6 py-3 bg-zinc-50 border-b border-zinc-100 flex items-center gap-3 text-sm">
          <span className="text-zinc-500 font-medium">Auto-Stop nach Inaktivität:</span>
          <input
            type="number"
            min={1}
            max={480}
            value={idleInput}
            onChange={(e) => setIdleInput(e.target.value)}
            className="w-16 px-2 py-1 border border-zinc-200 rounded-lg text-center text-zinc-700 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 bg-white"
          />
          <span className="text-zinc-400 text-xs">Minuten</span>
          <button
            onClick={handleSaveTimeout}
            className="px-3 py-1 bg-indigo-600 text-white text-xs font-semibold rounded-lg hover:bg-indigo-700 transition"
          >
            {savedTimeout ? "✓ Gespeichert" : "Speichern"}
          </button>
          <span className="ml-auto text-xs text-zinc-400">
            Autostart-Profile bleiben immer aktiv
          </span>
        </div>

        {/* Profile List */}
        <div className="overflow-y-auto flex-1 px-6 py-4">
          {error && (
            <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded-xl text-red-600 text-sm">
              {error}
            </div>
          )}

          {loading && profiles.length === 0 ? (
            <div className="flex items-center justify-center py-16 gap-3 text-zinc-400">
              <Loader2 className="w-5 h-5 animate-spin" />
              <span className="text-sm">Lade Profile...</span>
            </div>
          ) : (
            <>
              {/* Table Header */}
              <div className="grid grid-cols-[1fr_auto_auto_auto] gap-3 px-3 py-2 text-[10px] font-bold text-zinc-400 uppercase tracking-wider border-b border-zinc-100 mb-1">
                <span>Profil</span>
                <span className="w-20 text-center">Status</span>
                <span className="w-20 text-center">Autostart</span>
                <span className="w-24 text-center">Aktion</span>
              </div>

              {/* Profile Rows */}
              <div className="space-y-0.5">
                {profiles.map((p) => {
                  const isRunning = p.status === "running";
                  const isDefault = p.id === "default";
                  const isActing = actionLoading === p.id;

                  return (
                    <div
                      key={p.id}
                      className={`grid grid-cols-[1fr_auto_auto_auto] items-center gap-3 px-3 py-2.5 rounded-xl transition ${
                        isRunning
                          ? "bg-emerald-50 border border-emerald-100"
                          : "bg-zinc-50 border border-transparent hover:border-zinc-200"
                      }`}
                    >
                      {/* Profile Name */}
                      <div className="flex items-center gap-2.5 min-w-0">
                        <span
                          className={`w-2 h-2 rounded-full shrink-0 ${
                            isRunning
                              ? "bg-emerald-500 shadow-[0_0_6px_2px_rgba(16,185,129,0.4)] animate-pulse"
                              : "bg-zinc-300"
                          }`}
                        />
                        <span
                          className={`text-sm font-medium truncate ${
                            isRunning ? "text-zinc-800" : "text-zinc-500"
                          }`}
                        >
                          {p.id}
                          {isDefault && (
                            <span className="ml-1.5 text-[10px] font-bold text-indigo-500 bg-indigo-50 px-1.5 py-0.5 rounded">
                              MASTER
                            </span>
                          )}
                        </span>
                      </div>

                      {/* Status Badge */}
                      <div className="w-20 text-center">
                        <span
                          className={`inline-block text-[10px] font-bold px-2 py-0.5 rounded-full ${
                            isRunning
                              ? "bg-emerald-100 text-emerald-700"
                              : "bg-zinc-200 text-zinc-500"
                          }`}
                        >
                          {isRunning ? "Running" : "Stopped"}
                        </span>
                      </div>

                      {/* Autostart Toggle */}
                      <div className="w-20 flex justify-center">
                        <button
                          onClick={() =>
                            !isDefault &&
                            handleAutostartToggle(p.id, !p.autostart)
                          }
                          disabled={isDefault}
                          title={
                            isDefault
                              ? "Default ist immer aktiv"
                              : p.autostart
                              ? "Autostart deaktivieren"
                              : "Autostart aktivieren"
                          }
                          className={`relative w-9 h-5 rounded-full transition-colors duration-200 ${
                            p.autostart || isDefault
                              ? "bg-indigo-500"
                              : "bg-zinc-200"
                          } ${isDefault ? "opacity-60 cursor-default" : "cursor-pointer"}`}
                        >
                          <span
                            className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform duration-200 ${
                              p.autostart || isDefault
                                ? "translate-x-4"
                                : "translate-x-0"
                            }`}
                          />
                        </button>
                      </div>

                      {/* Action Button */}
                      <div className="w-24 flex justify-center">
                        {isDefault ? (
                          <span className="text-[10px] text-zinc-400 italic">
                            immer aktiv
                          </span>
                        ) : isActing ? (
                          <Loader2 className="w-4 h-4 animate-spin text-zinc-400" />
                        ) : isRunning ? (
                          <button
                            onClick={() => handleStop(p.id)}
                            className="flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold text-red-600 bg-red-50 border border-red-200 rounded-lg hover:bg-red-100 transition"
                          >
                            <Square className="w-3 h-3" />
                            Stop
                          </button>
                        ) : (
                          <button
                            onClick={() => handleStart(p.id)}
                            className="flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg hover:bg-emerald-100 transition"
                          >
                            <Play className="w-3 h-3" />
                            Start
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-zinc-100 bg-zinc-50 flex items-center justify-between">
          <button
            onClick={handleStopAll}
            disabled={runningCount <= 1}
            className="px-4 py-1.5 text-xs font-semibold text-red-600 border border-red-200 rounded-lg hover:bg-red-50 transition disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Alle stoppen (ausser Default)
          </button>
          <span className="text-[10px] text-zinc-400 font-mono">
            Idle-Timeout: {idleTimeout} Min · Archon OS v2.0
          </span>
        </div>
      </div>
    </div>
  );
};
