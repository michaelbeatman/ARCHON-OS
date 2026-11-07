"use client";

import React, { useState } from "react";
import { Zap, Plus, Edit2, Trash2, X, Check, Clock, FileText, Users, Globe } from "lucide-react";

export interface TriggerItem {
  id: string;
  name: string;
  type: "obsidian" | "crm" | "cron" | "webhook";
  condition: string;
  isPredefined?: boolean;
}

export const PREDEFINED_TRIGGERS: TriggerItem[] = [
  {
    id: "trig-obsidian-1",
    name: "Neuer Obsidian Notiz-Eintrag",
    type: "obsidian",
    condition: "Datei im Ordner C:\\Mein Obsidian geändert/erstellt",
    isPredefined: true
  },
  {
    id: "trig-crm-1",
    name: "Neuer PocketBase CRM Kontakt",
    type: "crm",
    condition: "Neuer Datensatz in PocketBase Collection 'kontakte'",
    isPredefined: true
  },
  {
    id: "trig-cron-1",
    name: "Tägliche Zeitsteuerung (09:00 Uhr)",
    type: "cron",
    condition: "Cron: 0 9 * * * (Jeden Tag um 9:00 Uhr)",
    isPredefined: true
  },
  {
    id: "trig-webhook-1",
    name: "Eingehender Webhook / REST Event",
    type: "webhook",
    condition: "POST /api/webhooks/incoming",
    isPredefined: true
  }
];

interface TriggerManagerModalProps {
  isOpen: boolean;
  onClose: () => void;
  triggers: TriggerItem[];
  onSaveTriggers: (triggers: TriggerItem[]) => void;
}

export const TriggerManagerModal: React.FC<TriggerManagerModalProps> = ({
  isOpen,
  onClose,
  triggers,
  onSaveTriggers
}) => {
  const [triggerList, setTriggerList] = useState<TriggerItem[]>(triggers);
  const [editingId, setEditingId] = useState<string | null>(null);
  
  // Form State
  const [name, setName] = useState("");
  const [type, setType] = useState<"obsidian" | "crm" | "cron" | "webhook">("obsidian");
  const [condition, setCondition] = useState("");

  if (!isOpen) return null;

  const handleStartCreate = () => {
    setEditingId("new");
    setName("");
    setType("obsidian");
    setCondition("");
  };

  const handleStartEdit = (trig: TriggerItem) => {
    setEditingId(trig.id);
    setName(trig.name);
    setType(trig.type);
    setCondition(trig.condition);
  };

  const handleDelete = (id: string) => {
    const updated = triggerList.filter((t) => t.id !== id);
    setTriggerList(updated);
    onSaveTriggers(updated);
  };

  const handleSaveForm = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    let updated: TriggerItem[];
    if (editingId === "new") {
      const newTrig: TriggerItem = {
        id: `custom-trig-${Date.now()}`,
        name: name.trim(),
        type,
        condition: condition.trim() || "Benutzerdefinierte Bedingung",
        isPredefined: false
      };
      updated = [...triggerList, newTrig];
    } else {
      updated = triggerList.map((t) =>
        t.id === editingId ? { ...t, name: name.trim(), type, condition: condition.trim() } : t
      );
    }

    setTriggerList(updated);
    onSaveTriggers(updated);
    setEditingId(null);
  };

  const getTriggerIcon = (tType: string) => {
    switch (tType) {
      case "obsidian":
        return <FileText className="w-4 h-4 text-purple-400" />;
      case "crm":
        return <Users className="w-4 h-4 text-emerald-400" />;
      case "cron":
        return <Clock className="w-4 h-4 text-amber-400" />;
      case "webhook":
        return <Globe className="w-4 h-4 text-sky-400" />;
      default:
        return <Zap className="w-4 h-4 text-indigo-400" />;
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-2xl overflow-hidden shadow-2xl font-sans">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-950/40">
          <div className="flex items-center gap-2.5">
            <Zap className="w-5 h-5 text-amber-400 animate-pulse" />
            <h2 className="text-base font-bold text-slate-100 font-mono">
              Trigger & Event-Verwaltung
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content Body */}
        <div className="p-6 max-h-[70vh] overflow-y-auto space-y-5">
          {/* Action Header */}
          <div className="flex items-center justify-between">
            <p className="text-xs text-slate-400">
              Vordefinierte und eigene Trigger zur automatischen Auslösung von Agenten-Workflows.
            </p>
            <button
              onClick={handleStartCreate}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold shadow-lg shadow-indigo-600/20 transition"
            >
              <Plus className="w-4 h-4" />
              <span>Neuer Trigger</span>
            </button>
          </div>

          {/* Trigger List */}
          <div className="space-y-2">
            {triggerList.map((trig) => (
              <div
                key={trig.id}
                className="p-3 bg-slate-950/70 border border-slate-800 rounded-xl flex items-center justify-between gap-3 hover:border-slate-700 transition"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div className="p-2 rounded-lg bg-slate-900 border border-slate-800 shrink-0">
                    {getTriggerIcon(trig.type)}
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-bold text-slate-200 truncate">
                        {trig.name}
                      </span>
                      {trig.isPredefined && (
                        <span className="text-[9px] bg-slate-800 text-slate-400 border border-slate-700 px-1.5 py-0.2 rounded font-mono">
                          STANDARD
                        </span>
                      )}
                    </div>
                    <p className="text-[11px] text-slate-400 truncate mt-0.5 font-mono">
                      {trig.condition}
                    </p>
                  </div>
                </div>

                {/* Edit / Trash Actions */}
                <div className="flex items-center gap-1.5 shrink-0">
                  <button
                    onClick={() => handleStartEdit(trig)}
                    className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition"
                    title="Trigger bearbeiten"
                  >
                    <Edit2 className="w-3.5 h-3.5" />
                  </button>
                  {!trig.isPredefined && (
                    <button
                      onClick={() => handleDelete(trig.id)}
                      className="p-1.5 rounded-lg text-rose-400 hover:text-rose-300 hover:bg-rose-950/40 transition"
                      title="Trigger löschen"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Form Modal / Inlined Edit Form */}
          {editingId !== null && (
            <form onSubmit={handleSaveForm} className="mt-4 p-4 bg-slate-950 border border-indigo-500/40 rounded-xl space-y-3 font-sans">
              <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                <span className="text-xs font-bold text-indigo-400 font-mono">
                  {editingId === "new" ? "➕ Neuen Trigger erstellen" : "✏️ Trigger bearbeiten"}
                </span>
                <button
                  type="button"
                  onClick={() => setEditingId(null)}
                  className="text-slate-400 hover:text-slate-200"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <label className="block text-[11px] text-slate-400 mb-1 font-semibold">Name des Triggers</label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="z.B. Mail empfangen"
                    className="w-full px-3 py-1.5 bg-slate-900 border border-slate-800 rounded-lg text-slate-100 outline-none focus:border-indigo-500"
                    required
                  />
                </div>
                <div>
                  <label className="block text-[11px] text-slate-400 mb-1 font-semibold">Typ</label>
                  <select
                    value={type}
                    onChange={(e) => setType(e.target.value as any)}
                    className="w-full px-3 py-1.5 bg-slate-900 border border-slate-800 rounded-lg text-slate-100 outline-none focus:border-indigo-500"
                  >
                    <option value="obsidian">📝 Obsidian Notiz</option>
                    <option value="crm">📇 PocketBase CRM</option>
                    <option value="cron">⏰ Zeitsteuerung (Cron)</option>
                    <option value="webhook">🌐 Webhook / HTTP Event</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-[11px] text-slate-400 mb-1 font-semibold">Bedingung / Auslöser-Pfad</label>
                <input
                  type="text"
                  value={condition}
                  onChange={(e) => setCondition(e.target.value)}
                  placeholder="z.B. C:\Mein Obsidian\Bewerbung"
                  className="w-full px-3 py-1.5 bg-slate-900 border border-slate-800 rounded-lg text-slate-100 font-mono outline-none focus:border-indigo-500"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setEditingId(null)}
                  className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-semibold"
                >
                  Abbrechen
                </button>
                <button
                  type="submit"
                  className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold shadow-md shadow-indigo-600/30 flex items-center gap-1.5"
                >
                  <Check className="w-4 h-4" />
                  <span>Speichern</span>
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};
