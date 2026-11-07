"use client";

import React, { useEffect, useState, useCallback } from "react";
import { 
  Radar, 
  X, 
  Play, 
  RefreshCw, 
  Plus, 
  Trash2, 
  ExternalLink, 
  Check, 
  AlertCircle, 
  Clock, 
  Send, 
  Layers, 
  Sliders,
  Globe,
  Radio,
  FileText
} from "lucide-react";

interface WatchdogTarget {
  id: string;
  name: string;
  category: string;
  type: "search_feed" | "rss" | "web_diff";
  query_or_url: string;
  active: boolean;
  last_check?: string | null;
  last_status?: string | null;
}

interface WatchdogFinding {
  id: string;
  target_id: string;
  target_name: string;
  category: string;
  title: string;
  link: string;
  published: string;
  detected_at: string;
}

interface WatchdogConfig {
  enabled: boolean;
  interval_minutes: number;
  channels: {
    telegram: boolean;
    kanban: boolean;
  };
  targets: WatchdogTarget[];
  last_run: string | null;
  recent_findings: WatchdogFinding[];
}

interface WatchdogModalProps {
  isOpen: boolean;
  onClose: () => void;
  themeMode?: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8501";

export const WatchdogModal: React.FC<WatchdogModalProps> = ({
  isOpen,
  onClose,
  themeMode = "dark"
}) => {
  const isLight = themeMode === "light";

  const [config, setConfig] = useState<WatchdogConfig | null>(null);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [saveStatus, setSaveStatus] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"targets" | "findings" | "settings">("targets");

  // New Target Form State
  const [showAddForm, setShowAddForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [newCategory, setNewCategory] = useState("Markt & Bau");
  const [newType, setNewType] = useState<"search_feed" | "rss" | "web_diff">("search_feed");
  const [newQueryOrUrl, setNewQueryOrUrl] = useState("");

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/watchdog/config`);
      if (res.ok) {
        const data = await res.json();
        setConfig(data);
      }
    } catch (e) {
      console.error("Watchdog config fetch error:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      fetchConfig();
    }
  }, [isOpen, fetchConfig]);

  const saveConfigToServer = async (updated: WatchdogConfig) => {
    setConfig(updated);
    try {
      setSaveStatus("Speichern...");
      const res = await fetch(`${API_BASE}/api/v1/watchdog/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updated)
      });
      if (res.ok) {
        setSaveStatus("Gespeichert");
        setTimeout(() => setSaveStatus(null), 2000);
      }
    } catch (e) {
      setSaveStatus("Fehler beim Speichern");
    }
  };

  const toggleGlobalEnabled = () => {
    if (!config) return;
    const updated = { ...config, enabled: !config.enabled };
    saveConfigToServer(updated);
  };

  const toggleTargetActive = (targetId: string) => {
    if (!config) return;
    const updatedTargets = config.targets.map(t => 
      t.id === targetId ? { ...t, active: !t.active } : t
    );
    saveConfigToServer({ ...config, targets: updatedTargets });
  };

  const deleteTarget = (targetId: string) => {
    if (!config) return;
    const updatedTargets = config.targets.filter(t => t.id !== targetId);
    saveConfigToServer({ ...config, targets: updatedTargets });
  };

  const handleAddTarget = (e: React.FormEvent) => {
    e.preventDefault();
    if (!config || !newName.trim() || !newQueryOrUrl.trim()) return;

    const newTarget: WatchdogTarget = {
      id: `target-${Date.now().toString(36)}`,
      name: newName.trim(),
      category: newCategory.trim() || "Allgemein",
      type: newType,
      query_or_url: newQueryOrUrl.trim(),
      active: true,
      last_check: null,
      last_status: "Neu angelegt"
    };

    const updated = {
      ...config,
      targets: [...config.targets, newTarget]
    };

    saveConfigToServer(updated);
    setNewName("");
    setNewQueryOrUrl("");
    setShowAddForm(false);
  };

  const handleRunNow = async () => {
    setRunning(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/watchdog/run_now`, {
        method: "POST"
      });
      if (res.ok) {
        const data = await res.json();
        if (data.config) {
          setConfig(data.config);
        }
        setSaveStatus(`${data.new_findings_count || 0} neue Treffer erfasst`);
        setTimeout(() => setSaveStatus(null), 3000);
      }
    } catch (e) {
      setSaveStatus("Fehler beim Suchlauf");
    } finally {
      setRunning(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/70 backdrop-blur-xs p-4">
      <div 
        className={`w-full max-w-4xl max-h-[90vh] flex flex-col rounded-2xl border shadow-2xl overflow-hidden transition-all duration-150 ${
          isLight ? "bg-white border-slate-200 text-slate-800" : "bg-slate-900 border-slate-800 text-slate-100"
        }`}
      >
        {/* Header */}
        <div className={`px-6 py-4 border-b flex items-center justify-between shrink-0 ${
          isLight ? "bg-slate-50 border-slate-200" : "bg-slate-950/70 border-slate-800"
        }`}>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500 to-emerald-500 flex items-center justify-center text-white shadow-lg shadow-cyan-500/20">
              <Radar className="w-5 h-5 animate-pulse" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-mono font-bold text-base tracking-tight">Internet-Watchdog (Radar)</h3>
                <span className="text-[10px] px-2 py-0.5 rounded font-mono font-semibold bg-cyan-500/20 text-cyan-400 border border-cyan-500/30">
                  Kognition: Säule 4
                </span>
                {saveStatus && (
                  <span className="text-[10px] text-emerald-400 font-mono animate-pulse">
                    ● {saveStatus}
                  </span>
                )}
              </div>
              <p className={`text-xs ${isLight ? "text-slate-500" : "text-slate-400"}`}>
                Token-freie, autonome Dauerüberwachung für Markt, KI und Web-Quellen
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Global Enabled Toggle */}
            <button
              onClick={toggleGlobalEnabled}
              className={`px-3 py-1.5 rounded-lg border text-xs font-mono font-semibold flex items-center gap-1.5 transition cursor-pointer ${
                config?.enabled
                  ? "bg-emerald-500/20 border-emerald-500/40 text-emerald-400 hover:bg-emerald-500/30"
                  : "bg-slate-800 border-slate-700 text-slate-400 hover:bg-slate-700"
              }`}
            >
              <Radio className={`w-3.5 h-3.5 ${config?.enabled ? "animate-pulse" : ""}`} />
              <span>{config?.enabled ? "Radar Aktiv" : "Pausiert"}</span>
            </button>

            {/* Run Now Button */}
            <button
              onClick={handleRunNow}
              disabled={running}
              className="px-3.5 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-mono text-xs font-bold transition flex items-center gap-1.5 shadow-md shadow-cyan-600/20 cursor-pointer disabled:opacity-50"
              title="Alle aktiven Quellen sofort abfragen"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${running ? "animate-spin" : ""}`} />
              <span>{running ? "Scannt..." : "Jetzt prüfen"}</span>
            </button>

            {/* Close */}
            <button
              onClick={onClose}
              className={`p-1.5 rounded-lg border transition ${
                isLight ? "border-slate-200 hover:bg-slate-100 text-slate-500" : "border-slate-800 hover:bg-slate-800 text-slate-400"
              }`}
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className={`px-6 border-b flex items-center gap-6 text-xs font-mono font-semibold shrink-0 ${
          isLight ? "border-slate-200 bg-white" : "border-slate-800 bg-slate-900"
        }`}>
          <button
            onClick={() => setActiveTab("targets")}
            className={`py-3 border-b-2 transition flex items-center gap-2 cursor-pointer ${
              activeTab === "targets"
                ? "border-cyan-500 text-cyan-400"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <Radio className="w-3.5 h-3.5" />
            <span>Radar-Quellen ({config?.targets?.length || 0})</span>
          </button>

          <button
            onClick={() => setActiveTab("findings")}
            className={`py-3 border-b-2 transition flex items-center gap-2 cursor-pointer ${
              activeTab === "findings"
                ? "border-cyan-500 text-cyan-400"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <FileText className="w-3.5 h-3.5" />
            <span>Letzte Funde ({config?.recent_findings?.length || 0})</span>
          </button>

          <button
            onClick={() => setActiveTab("settings")}
            className={`py-3 border-b-2 transition flex items-center gap-2 cursor-pointer ${
              activeTab === "settings"
                ? "border-cyan-500 text-cyan-400"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <Sliders className="w-3.5 h-3.5" />
            <span>Intervall & Kanäle</span>
          </button>
        </div>

        {/* Content Area */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {/* TAB 1: TARGETS */}
          {activeTab === "targets" && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-xs font-bold font-mono uppercase tracking-wider text-slate-400">
                    Aktive Überwachungs-Ziele
                  </h4>
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    Quellen werden im eingestellten Rhythmus ohne KI-Kosten abgefragt.
                  </p>
                </div>
                <button
                  onClick={() => setShowAddForm(!showAddForm)}
                  className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-cyan-400 border border-slate-700 font-mono text-xs font-semibold flex items-center gap-1.5 transition cursor-pointer"
                >
                  <Plus className="w-3.5 h-3.5" />
                  <span>{showAddForm ? "Abbrechen" : "Neue Quelle"}</span>
                </button>
              </div>

              {/* Add Form */}
              {showAddForm && (
                <form onSubmit={handleAddTarget} className={`p-4 rounded-xl border space-y-3 ${
                  isLight ? "bg-slate-50 border-slate-200" : "bg-slate-950/60 border-slate-800"
                }`}>
                  <div className="font-mono text-xs font-bold text-cyan-400">Neue Radar-Quelle definieren</div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    <div>
                      <label className="text-[10px] font-mono text-slate-400 block mb-1">Bezeichnung</label>
                      <input
                        type="text"
                        value={newName}
                        onChange={e => setNewName(e.target.value)}
                        placeholder="z. B. KfW Förderprogramme"
                        className={`w-full px-3 py-1.5 rounded-lg border text-xs outline-none ${
                          isLight ? "bg-white border-slate-300" : "bg-slate-900 border-slate-700 text-slate-100"
                        }`}
                        required
                      />
                    </div>
                    <div>
                      <label className="text-[10px] font-mono text-slate-400 block mb-1">Kategorie</label>
                      <input
                        type="text"
                        value={newCategory}
                        onChange={e => setNewCategory(e.target.value)}
                        placeholder="Markt & Bau / KI / Wettbewerb"
                        className={`w-full px-3 py-1.5 rounded-lg border text-xs outline-none ${
                          isLight ? "bg-white border-slate-300" : "bg-slate-900 border-slate-700 text-slate-100"
                        }`}
                        required
                      />
                    </div>
                    <div>
                      <label className="text-[10px] font-mono text-slate-400 block mb-1">Typ</label>
                      <select
                        value={newType}
                        onChange={e => setNewType(e.target.value as any)}
                        className={`w-full px-3 py-1.5 rounded-lg border text-xs outline-none ${
                          isLight ? "bg-white border-slate-300" : "bg-slate-900 border-slate-700 text-slate-100"
                        }`}
                      >
                        <option value="search_feed">Google News / Keyword-Suche</option>
                        <option value="rss">Direkter RSS- / Atom-Feed</option>
                        <option value="web_diff">Webseiten-Diff (URL)</option>
                      </select>
                    </div>
                  </div>
                  <div>
                    <label className="text-[10px] font-mono text-slate-400 block mb-1">
                      {newType === "search_feed" ? "Suchbegriffe (mit OR / AND)" : "Ziel-URL"}
                    </label>
                    <input
                      type="text"
                      value={newQueryOrUrl}
                      onChange={e => setNewQueryOrUrl(e.target.value)}
                      placeholder={newType === "search_feed" ? "BauGB OR GEG OR KfW Neubauförderung" : "https://example.com/feed.xml"}
                      className={`w-full px-3 py-1.5 rounded-lg border text-xs outline-none ${
                        isLight ? "bg-white border-slate-300" : "bg-slate-900 border-slate-700 text-slate-100"
                      }`}
                      required
                    />
                  </div>
                  <div className="flex justify-end gap-2 pt-1">
                    <button
                      type="button"
                      onClick={() => setShowAddForm(false)}
                      className="px-3 py-1.5 rounded-lg text-xs font-mono text-slate-400 hover:bg-slate-800"
                    >
                      Abbrechen
                    </button>
                    <button
                      type="submit"
                      className="px-4 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-mono text-xs font-bold"
                    >
                      Quelle hinzufügen
                    </button>
                  </div>
                </form>
              )}

              {/* Target List */}
              <div className="space-y-2.5">
                {config?.targets?.map((target) => (
                  <div
                    key={target.id}
                    className={`p-3.5 rounded-xl border flex items-center justify-between gap-4 transition ${
                      target.active
                        ? isLight ? "bg-slate-50 border-slate-200" : "bg-slate-950/40 border-slate-800/80"
                        : "opacity-60 bg-transparent border-slate-800/40"
                    }`}
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <button
                        onClick={() => toggleTargetActive(target.id)}
                        className={`w-5 h-5 rounded flex items-center justify-center border transition shrink-0 cursor-pointer ${
                          target.active
                            ? "bg-cyan-500 border-cyan-500 text-white"
                            : "border-slate-600 hover:border-slate-500"
                        }`}
                        title={target.active ? "Deaktivieren" : "Aktivieren"}
                      >
                        {target.active && <Check className="w-3.5 h-3.5 stroke-[3]" />}
                      </button>

                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-xs text-slate-200 truncate">{target.name}</span>
                          <span className="text-[10px] px-1.5 py-0.5 rounded font-mono bg-slate-800 text-slate-300 border border-slate-700">
                            {target.category}
                          </span>
                          <span className="text-[9px] font-mono text-slate-500 uppercase">
                            {target.type}
                          </span>
                        </div>
                        <div className="text-[11px] font-mono text-cyan-400/90 truncate mt-0.5">
                          {target.query_or_url}
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-3 shrink-0">
                      {target.last_status && (
                        <span className={`text-[10px] font-mono px-2 py-0.5 rounded border ${
                          target.last_status.startsWith("OK")
                            ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400"
                            : "bg-amber-500/10 border-amber-500/20 text-amber-400"
                        }`}>
                          {target.last_status}
                        </span>
                      )}

                      <button
                        onClick={() => deleteTarget(target.id)}
                        className="p-1.5 rounded hover:bg-rose-500/20 text-slate-500 hover:text-rose-400 transition"
                        title="Quelle löschen"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* TAB 2: FINDINGS */}
          {activeTab === "findings" && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-bold font-mono uppercase tracking-wider text-slate-400">
                  Zuletzt erfasste Einträge
                </h4>
                <span className="text-[10px] font-mono text-slate-500">
                  Letzter Gesamtsuchlauf: {config?.last_run ? new Date(config.last_run).toLocaleTimeString("de-DE") : "Noch kein Lauf"}
                </span>
              </div>

              {(!config?.recent_findings || config.recent_findings.length === 0) ? (
                <div className="text-center py-12 text-slate-500 font-mono text-xs">
                  Noch keine Treffer erfasst. Klicke auf &quot;Jetzt prüfen&quot;, um den ersten Suchlauf zu starten.
                </div>
              ) : (
                <div className="space-y-2">
                  {config.recent_findings.map((f) => (
                    <div
                      key={f.id}
                      className={`p-3 rounded-xl border flex items-center justify-between gap-4 hover:border-slate-700 transition ${
                        isLight ? "bg-slate-50 border-slate-200" : "bg-slate-950/40 border-slate-800/80"
                      }`}
                    >
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] px-1.5 py-0.5 rounded font-mono font-semibold bg-cyan-500/15 text-cyan-300 border border-cyan-500/30">
                            {f.category}
                          </span>
                          <span className="text-[10px] text-slate-500 font-mono">
                            {f.target_name} • {f.detected_at}
                          </span>
                        </div>
                        <div className="text-xs font-medium text-slate-200 mt-1 line-clamp-1">
                          {f.title}
                        </div>
                      </div>

                      {f.link && (
                        <a
                          href={f.link}
                          target="_blank"
                          rel="noreferrer"
                          className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-cyan-400 font-mono text-[11px] font-semibold flex items-center gap-1 transition shrink-0"
                        >
                          <span>Öffnen</span>
                          <ExternalLink className="w-3 h-3" />
                        </a>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* TAB 3: SETTINGS */}
          {activeTab === "settings" && (
            <div className="space-y-6">
              {/* Intervall */}
              <div className={`p-4 rounded-xl border space-y-3 ${
                isLight ? "bg-slate-50 border-slate-200" : "bg-slate-950/40 border-slate-800/80"
              }`}>
                <div className="flex items-center gap-2 font-mono text-xs font-bold text-slate-200">
                  <Clock className="w-4 h-4 text-cyan-400" />
                  <span>Abfrage-Rhythmus (Watchdog Intervall)</span>
                </div>
                <p className="text-[11px] text-slate-400">
                  Wie häufig soll der Watchdog im Hintergrund prüfen? (Reine HTTP-Knoten ohne Token-Kosten).
                </p>
                <div className="flex gap-2">
                  {[15, 30, 60, 120, 360].map((mins) => (
                    <button
                      key={mins}
                      onClick={() => {
                        if (config) saveConfigToServer({ ...config, interval_minutes: mins });
                      }}
                      className={`px-3 py-1.5 rounded-lg border font-mono text-xs transition cursor-pointer ${
                        config?.interval_minutes === mins
                          ? "bg-cyan-500/20 border-cyan-500/50 text-cyan-300 font-bold"
                          : "border-slate-800 hover:bg-slate-800 text-slate-400"
                      }`}
                    >
                      {mins < 60 ? `Alle ${mins} Min.` : `Alle ${mins / 60} Std.`}
                    </button>
                  ))}
                </div>
              </div>

              {/* Benachrichtigungs-Kanäle */}
              <div className={`p-4 rounded-xl border space-y-3 ${
                isLight ? "bg-slate-50 border-slate-200" : "bg-slate-950/40 border-slate-800/80"
              }`}>
                <div className="flex items-center gap-2 font-mono text-xs font-bold text-slate-200">
                  <Send className="w-4 h-4 text-emerald-400" />
                  <span>Benachrichtigungs-Kanäle bei neuen Treffern</span>
                </div>
                <div className="space-y-2">
                  <label className="flex items-center gap-2.5 text-xs text-slate-300 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={config?.channels?.telegram ?? true}
                      onChange={(e) => {
                        if (config) {
                          saveConfigToServer({
                            ...config,
                            channels: { ...config.channels, telegram: e.target.checked }
                          });
                        }
                      }}
                      className="rounded border-slate-700 bg-slate-900 text-cyan-500 focus:ring-0"
                    />
                    <span>Telegram Sofort-Alert (Kompaktes Briefing aufs Handy)</span>
                  </label>

                  <label className="flex items-center gap-2.5 text-xs text-slate-300 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={config?.channels?.kanban ?? true}
                      onChange={(e) => {
                        if (config) {
                          saveConfigToServer({
                            ...config,
                            channels: { ...config.channels, kanban: e.target.checked }
                          });
                        }
                      }}
                      className="rounded border-slate-700 bg-slate-900 text-cyan-500 focus:ring-0"
                    />
                    <span>Archon Kanban-Board (Erstellt Vorgang in Spalte &quot;todo&quot; für Robert)</span>
                  </label>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className={`px-6 py-3 border-t flex items-center justify-between text-[11px] font-mono text-slate-500 shrink-0 ${
          isLight ? "bg-slate-50 border-slate-200" : "bg-slate-950/70 border-slate-800"
        }`}>
          <span>Archon OS • Autonome Kognitions-Engine v2.0</span>
          <span>Intervall: {config?.interval_minutes || 30} Min. • Status: {config?.enabled ? "Aktiv" : "Pausiert"}</span>
        </div>
      </div>
    </div>
  );
};
