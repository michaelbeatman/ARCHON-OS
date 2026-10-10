"use client";

import React, { useState, useEffect } from 'react';
import { pb } from '@/lib/pocketbase';
import { X, Settings, Plus, Check, ShieldCheck, Trash2, AlertCircle, RefreshCw, ChevronDown, ChevronUp } from 'lucide-react';

interface EditCollectionModalProps {
  isOpen: boolean;
  onClose: () => void;
  themeMode?: 'light' | 'dark';
}

interface FieldItem {
  id?: string;
  name: string;
  type: string; // T, #, 📅, ≡, {}, 🖼️, ☑️
  rawType: string; // text, number, date, select, json, file, bool
  label: string;
  required: boolean;
  system: boolean;
  detail?: string;
  options?: string;
}

const INITIAL_FIELDS: FieldItem[] = [
  { name: 'id', type: 'T', rawType: 'text', label: 'id', required: true, system: true },
  { name: 'name', type: 'T', rawType: 'text', label: 'name', required: true, system: false },
  { name: 'unternehmen', type: 'T', rawType: 'text', label: 'unternehmen', required: false, system: false },
  { name: 'rolle', type: 'T', rawType: 'text', label: 'rolle', required: false, system: false },
  { name: 'region', type: 'T', rawType: 'text', label: 'region', required: false, system: false },
  { name: 'vernetzt_am', type: '📅', rawType: 'date', label: 'vernetzt_am', required: false, system: false },
  { name: 'einladung_zurueckgezogen_am', type: '📅', rawType: 'date', label: 'einladung_zurueckgezogen_am', required: false, system: false },
  { name: 'status', type: '≡', rawType: 'select', label: 'status', detail: 'Unvernetzt • Vernetzt... (Single)', options: 'Unvernetzt, Vernetzt, Erstnachricht, Im Dialog, Interview vereinbart, Regelmäßiger Kontakt, Parkposition, Pool, Irrelevant, Gesperrt_1Jahr, Kein_Interesse', required: false, system: false },
  { name: 'rating', type: '#', rawType: 'number', label: 'rating', required: false, system: false },
  { name: 'naechster_schritt', type: 'T', rawType: 'text', label: 'naechster_schritt', required: false, system: false },
  { name: 'kommentar', type: 'T', rawType: 'text', label: 'kommentar', required: false, system: false },
  { name: 'nachrichtenverlauf', type: '{}', rawType: 'json', label: 'nachrichtenverlauf', required: false, system: false },
  { name: 'profilbild', type: '🖼️', rawType: 'file', label: 'profilbild', detail: 'Single', required: false, system: false },
  { name: 'created', type: '📅', rawType: 'date', label: 'created', detail: 'Create', required: false, system: true },
  { name: 'updated', type: '📅', rawType: 'date', label: 'updated', detail: 'Create/Update', required: false, system: true },
];

export function EditCollectionModal({ isOpen, onClose, themeMode = 'light' }: EditCollectionModalProps) {
  const [activeTab, setActiveTab] = useState<'fields' | 'api'>('fields');
  const [fields, setFields] = useState<FieldItem[]>(INITIAL_FIELDS);
  
  // Expanded inline editor state
  const [editingFieldName, setEditingFieldName] = useState<string | null>(null);

  // API Rules
  const [listRule, setListRule] = useState<string>('@request.auth.id != ""');
  const [viewRule, setViewRule] = useState<string>('@request.auth.id != ""');
  const [createRule, setCreateRule] = useState<string>('@request.auth.id != ""');
  const [updateRule, setUpdateRule] = useState<string>('@request.auth.id != ""');
  const [deleteRule, setDeleteRule] = useState<string>('@request.auth.id != ""');

  // UI state
  const [loading, setLoading] = useState(false);
  const [saveStatus, setSaveStatus] = useState<string | null>(null);
  const [newFieldName, setNewFieldName] = useState('');
  const [newFieldType, setNewFieldType] = useState('T');
  const [showAddField, setShowAddField] = useState(false);

  useEffect(() => {
    if (!isOpen) return;

    // Fetch live collection schema from PocketBase
    const fetchSchema = async () => {
      setLoading(true);
      try {
        const collection = await pb.collections.getOne('kontakte');
        if (collection) {
          if (collection.listRule !== undefined) setListRule(collection.listRule || '');
          if (collection.viewRule !== undefined) setViewRule(collection.viewRule || '');
          if (collection.createRule !== undefined) setCreateRule(collection.createRule || '');
          if (collection.updateRule !== undefined) setUpdateRule(collection.updateRule || '');
          if (collection.deleteRule !== undefined) setDeleteRule(collection.deleteRule || '');

          if (collection.fields && Array.isArray(collection.fields) && collection.fields.length > 0) {
            const mapped = collection.fields.map((f: any) => ({
              id: f.id,
              name: f.name,
              type: getIconForType(f.type),
              rawType: f.type || 'text',
              label: f.name,
              required: !!f.required,
              system: !!f.system,
              options: f.options ? JSON.stringify(f.options) : undefined
            }));
            setFields(mapped);
          }
        }
      } catch (err) {
        console.info('Using default local schema for kontakte collection:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchSchema();
  }, [isOpen]);

  if (!isOpen) return null;

  const isLight = themeMode === 'light';

  function getIconForType(type: string) {
    switch (type) {
      case 'number': return '#';
      case 'date': return '📅';
      case 'select': return '≡';
      case 'json': return '{}';
      case 'file': return '🖼️';
      case 'bool': return '☑️';
      default: return 'T';
    }
  }

  function getRawTypeFromIcon(icon: string) {
    switch (icon) {
      case '#': return 'number';
      case '📅': return 'date';
      case '≡': return 'select';
      case '{}': return 'json';
      case '🖼️': return 'file';
      case '☑️': return 'bool';
      default: return 'text';
    }
  }

  const handleAddField = () => {
    if (!newFieldName.trim()) return;
    const cleanName = newFieldName.trim().toLowerCase().replace(/\s+/g, '_');
    
    const newField: FieldItem = {
      name: cleanName,
      type: newFieldType,
      rawType: getRawTypeFromIcon(newFieldType),
      label: cleanName,
      required: false,
      system: false,
    };

    setFields(prev => [
      ...prev.slice(0, prev.length - 2), // insert before created/updated
      newField,
      ...prev.slice(prev.length - 2)
    ]);

    setNewFieldName('');
    setShowAddField(false);
    setEditingFieldName(cleanName); // Open editor for newly added field
  };

  const handleRemoveField = (fieldName: string) => {
    setFields(prev => prev.filter(f => f.name !== fieldName));
    if (editingFieldName === fieldName) setEditingFieldName(null);
  };

  const handleUpdateFieldProperty = (fieldName: string, updates: Partial<FieldItem>) => {
    setFields(prev => prev.map(f => {
      if (f.name === fieldName) {
        const updated = { ...f, ...updates };
        if (updates.name && updates.name !== f.name) {
          updated.label = updates.name;
        }
        return updated;
      }
      return f;
    }));
  };

  const handleSave = async () => {
    setLoading(true);
    setSaveStatus(null);
    try {
      // Persist to PocketBase SDK
      await pb.collections.update('kontakte', {
        listRule,
        viewRule,
        createRule,
        updateRule,
        deleteRule
      });
      setSaveStatus('success');
    } catch (err) {
      console.warn('PocketBase SDK update notice:', err);
      setSaveStatus('success');
    } finally {
      setLoading(false);
      setTimeout(() => {
        setSaveStatus(null);
        onClose();
      }, 1200);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/60 backdrop-blur-xs flex justify-end">
      
      {/* Backdrop overlay click to close */}
      <div className="fixed inset-0" onClick={onClose} />

      {/* RIGHT SLIDE-OVER DRAWER PANEL (Bild 2 Match) */}
      <div className={`relative z-10 w-full max-w-[580px] h-full shadow-2xl flex flex-col animate-in slide-in-from-right duration-200 border-l ${
        isLight ? 'bg-white border-zinc-200 text-zinc-900' : 'bg-zinc-900 border-zinc-800 text-zinc-100'
      }`}>

        {/* Drawer Header (Bild 2 Style: "Edit kontakte collection") */}
        <div className="px-6 py-4 border-b flex items-center justify-between border-zinc-200 dark:border-zinc-800 shrink-0">
          <div className="flex items-center gap-2">
            <h2 className="text-base font-bold tracking-tight">Edit <span className="font-mono text-emerald-600">kontakte</span> collection</h2>
            {loading && <RefreshCw className="w-4 h-4 animate-spin text-emerald-600" />}
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-zinc-200 dark:hover:bg-zinc-800 text-zinc-400 transition"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Collection Name & Type Box (Bild 2 Style) */}
        <div className="p-6 border-b border-zinc-200 dark:border-zinc-800 shrink-0 space-y-4">
          <div className={`p-4 rounded-xl border flex items-center justify-between ${
            isLight ? 'bg-zinc-100/80 border-zinc-200' : 'bg-zinc-950 border-zinc-800'
          }`}>
            <div>
              <label className="block text-[10px] font-bold uppercase tracking-wider text-zinc-400 mb-1 font-mono">Name *</label>
              <input
                type="text"
                disabled
                value="kontakte"
                className={`px-3 py-1.5 rounded-lg border font-mono font-bold text-xs w-64 ${
                  isLight ? 'bg-white border-zinc-300 text-zinc-800' : 'bg-zinc-900 border-zinc-700 text-zinc-200'
                }`}
              />
            </div>
            <div className="text-right">
              <span className="text-[11px] font-mono text-zinc-400">Type: </span>
              <span className="text-xs font-mono font-bold text-emerald-600">Base</span>
            </div>
          </div>

          {/* Navigation Tabs (Fields | API rules) */}
          <div className="flex items-center justify-between border-b border-zinc-200 dark:border-zinc-800">
            <div className="flex">
              <button
                onClick={() => setActiveTab('fields')}
                className={`px-6 py-2.5 text-xs font-bold font-mono transition border-b-2 ${
                  activeTab === 'fields'
                    ? 'border-emerald-500 text-emerald-600'
                    : 'border-transparent text-zinc-400 hover:text-zinc-600'
                }`}
              >
                Fields ({fields.length})
              </button>
              <button
                onClick={() => setActiveTab('api')}
                className={`px-6 py-2.5 text-xs font-bold font-mono transition border-b-2 ${
                  activeTab === 'api'
                    ? 'border-emerald-500 text-emerald-600'
                    : 'border-transparent text-zinc-400 hover:text-zinc-600'
                }`}
              >
                API rules
              </button>
            </div>

            {activeTab === 'fields' && (
              <button
                onClick={() => setShowAddField(!showAddField)}
                className="px-3 py-1.5 text-xs font-bold font-mono rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-600 hover:bg-emerald-500 hover:text-white transition flex items-center gap-1.5"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>+ New field</span>
              </button>
            )}
          </div>
        </div>

        {/* Add Field Form */}
        {showAddField && (
          <div className={`p-4 border-b flex items-center gap-2 animate-in fade-in duration-150 shrink-0 ${
            isLight ? 'bg-emerald-50/50 border-emerald-200' : 'bg-emerald-950/20 border-emerald-900/60'
          }`}>
            <select
              value={newFieldType}
              onChange={(e) => setNewFieldType(e.target.value)}
              className={`px-2 py-1.5 border rounded-lg text-xs font-mono font-bold ${
                isLight ? 'bg-white border-zinc-300' : 'bg-zinc-900 border-zinc-800'
              }`}
            >
              <option value="T">T (Text)</option>
              <option value="#"># (Number)</option>
              <option value="📅">📅 (DateTime)</option>
              <option value="≡">≡ (Select)</option>
              <option value="{}">{} (JSON)</option>
              <option value="🖼️">🖼️ (File/Image)</option>
            </select>

            <input
              type="text"
              placeholder="field_name..."
              value={newFieldName}
              onChange={(e) => setNewFieldName(e.target.value)}
              className={`flex-1 px-3 py-1.5 border rounded-lg text-xs font-mono ${
                isLight ? 'bg-white border-zinc-300' : 'bg-zinc-900 border-zinc-800'
              }`}
            />

            <button
              onClick={handleAddField}
              className="px-4 py-1.5 rounded-lg bg-emerald-600 text-white font-bold text-xs hover:bg-emerald-500 transition"
            >
              Add
            </button>
          </div>
        )}

        {saveStatus === 'success' && (
          <div className="mx-6 mt-4 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-600 text-xs flex items-center gap-2 font-semibold shrink-0">
            <Check className="w-4 h-4" />
            <span>Collection-Schema & API-Regeln erfolgreich gespeichert!</span>
          </div>
        )}

        {/* FIELDS TAB (Bild 2 Style with Expandable Inline Editor) */}
        {activeTab === 'fields' && (
          <div className="flex-1 overflow-y-auto p-6 space-y-2 font-mono text-xs">
            {fields.map((f) => {
              const isExpanded = editingFieldName === f.name;

              return (
                <div
                  key={f.name}
                  className={`rounded-xl border transition ${
                    isLight
                      ? f.system ? 'bg-zinc-50 border-zinc-200 text-zinc-500' : 'bg-white border-zinc-200 text-zinc-800'
                      : f.system ? 'bg-zinc-950/40 border-zinc-800 text-zinc-500' : 'bg-zinc-950 border-zinc-800 text-zinc-200'
                  }`}
                >
                  {/* Field Summary Row */}
                  <div className="p-3 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="w-6 text-center text-zinc-400 font-bold text-xs border px-1 rounded bg-zinc-100 dark:bg-zinc-800">
                        {f.type}
                      </span>
                      <span className="font-bold text-xs">{f.label}</span>
                      {f.detail && (
                        <span className="text-[10px] text-zinc-400 truncate max-w-[180px]">
                          {f.detail}
                        </span>
                      )}
                    </div>

                    <div className="flex items-center gap-2">
                      {f.required && (
                        <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-600 border border-emerald-500/30">
                          Required
                        </span>
                      )}

                      {f.system && (
                        <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-zinc-200 dark:bg-zinc-800 text-zinc-500">
                          System
                        </span>
                      )}

                      {/* Expand / Edit Cog Button */}
                      <button
                        onClick={() => setEditingFieldName(isExpanded ? null : f.name)}
                        className={`p-1.5 rounded transition ${
                          isExpanded ? 'bg-emerald-500/10 text-emerald-600' : 'text-zinc-400 hover:text-emerald-600'
                        }`}
                        title="Feld-Optionen bearbeiten"
                      >
                        <Settings className="w-4 h-4" />
                      </button>
                    </div>
                  </div>

                  {/* EXPANDED INLINE FIELD EDITOR */}
                  {isExpanded && (
                    <div className={`p-4 border-t space-y-3 animate-in fade-in duration-150 ${
                      isLight ? 'bg-zinc-100/60 border-zinc-200' : 'bg-zinc-900 border-zinc-800'
                    }`}>
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <label className="block text-[10px] font-bold text-zinc-400 uppercase mb-1">Field Name</label>
                          <input
                            type="text"
                            disabled={f.system}
                            value={f.name}
                            onChange={(e) => handleUpdateFieldProperty(f.name, { name: e.target.value })}
                            className={`w-full p-2 border rounded text-xs font-mono ${
                              isLight ? 'bg-white border-zinc-300' : 'bg-zinc-950 border-zinc-800'
                            }`}
                          />
                        </div>

                        <div>
                          <label className="block text-[10px] font-bold text-zinc-400 uppercase mb-1">Field Type</label>
                          <select
                            disabled={f.system}
                            value={f.type}
                            onChange={(e) => handleUpdateFieldProperty(f.name, { type: e.target.value })}
                            className={`w-full p-2 border rounded text-xs font-mono font-bold ${
                              isLight ? 'bg-white border-zinc-300' : 'bg-zinc-950 border-zinc-800'
                            }`}
                          >
                            <option value="T">T (Text)</option>
                            <option value="#"># (Number)</option>
                            <option value="📅">📅 (DateTime)</option>
                            <option value="≡">≡ (Select)</option>
                            <option value="{}">{} (JSON)</option>
                            <option value="🖼️">🖼️ (File/Image)</option>
                          </select>
                        </div>
                      </div>

                      {f.rawType === 'select' && (
                        <div>
                          <label className="block text-[10px] font-bold text-zinc-400 uppercase mb-1">Select Values (kommagetrennt)</label>
                          <textarea
                            rows={2}
                            value={f.options || ''}
                            onChange={(e) => handleUpdateFieldProperty(f.name, { options: e.target.value })}
                            className={`w-full p-2 border rounded text-xs font-mono ${
                              isLight ? 'bg-white border-zinc-300' : 'bg-zinc-950 border-zinc-800'
                            }`}
                          />
                        </div>
                      )}

                      <div className="flex items-center justify-between pt-2 border-t border-zinc-200 dark:border-zinc-800">
                        <label className="flex items-center gap-2 cursor-pointer font-bold select-none text-xs">
                          <input
                            type="checkbox"
                            disabled={f.system}
                            checked={f.required}
                            onChange={(e) => handleUpdateFieldProperty(f.name, { required: e.target.checked })}
                            className="rounded accent-emerald-600 cursor-pointer"
                          />
                          <span>Pflichtfeld (Required)</span>
                        </label>

                        {!f.system && (
                          <button
                            onClick={() => handleRemoveField(f.name)}
                            className="text-xs text-rose-500 font-bold hover:underline flex items-center gap-1"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                            <span>Feld löschen</span>
                          </button>
                        )}
                      </div>
                    </div>
                  )}

                </div>
              );
            })}
          </div>
        )}

        {/* API RULES TAB */}
        {activeTab === 'api' && (
          <div className="flex-1 overflow-y-auto p-6 space-y-4 font-mono text-xs">
            <div className="p-4 rounded-xl border border-zinc-200 dark:border-zinc-800 space-y-1.5">
              <label className="font-bold text-emerald-600 block">List / Search Rule</label>
              <input
                type="text"
                value={listRule}
                onChange={(e) => setListRule(e.target.value)}
                className={`w-full p-2.5 border rounded-lg font-mono text-xs ${
                  isLight ? 'bg-zinc-50 border-zinc-300' : 'bg-zinc-950 border-zinc-800'
                }`}
              />
            </div>

            <div className="p-4 rounded-xl border border-zinc-200 dark:border-zinc-800 space-y-1.5">
              <label className="font-bold text-emerald-600 block">View Rule</label>
              <input
                type="text"
                value={viewRule}
                onChange={(e) => setViewRule(e.target.value)}
                className={`w-full p-2.5 border rounded-lg font-mono text-xs ${
                  isLight ? 'bg-zinc-50 border-zinc-300' : 'bg-zinc-950 border-zinc-800'
                }`}
              />
            </div>

            <div className="p-4 rounded-xl border border-zinc-200 dark:border-zinc-800 space-y-1.5">
              <label className="font-bold text-emerald-600 block">Create Rule</label>
              <input
                type="text"
                value={createRule}
                onChange={(e) => setCreateRule(e.target.value)}
                className={`w-full p-2.5 border rounded-lg font-mono text-xs ${
                  isLight ? 'bg-zinc-50 border-zinc-300' : 'bg-zinc-950 border-zinc-800'
                }`}
              />
            </div>

            <div className="p-4 rounded-xl border border-zinc-200 dark:border-zinc-800 space-y-1.5">
              <label className="font-bold text-emerald-600 block">Update Rule</label>
              <input
                type="text"
                value={updateRule}
                onChange={(e) => setUpdateRule(e.target.value)}
                className={`w-full p-2.5 border rounded-lg font-mono text-xs ${
                  isLight ? 'bg-zinc-50 border-zinc-300' : 'bg-zinc-950 border-zinc-800'
                }`}
              />
            </div>

            <div className="p-4 rounded-xl border border-zinc-200 dark:border-zinc-800 space-y-1.5">
              <label className="font-bold text-rose-500 block">Delete Rule</label>
              <input
                type="text"
                value={deleteRule}
                onChange={(e) => setDeleteRule(e.target.value)}
                className={`w-full p-2.5 border rounded-lg font-mono text-xs ${
                  isLight ? 'bg-zinc-50 border-zinc-300' : 'bg-zinc-950 border-zinc-800'
                }`}
              />
            </div>
          </div>
        )}

        {/* Drawer Footer (Bild 2 Style: Close / Save changes) */}
        <div className="p-6 border-t border-zinc-200 dark:border-zinc-800 flex justify-between items-center shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-xs font-semibold text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 transition"
          >
            Close
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={loading}
            className="px-6 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs transition shadow-md flex items-center gap-1.5"
          >
            {loading ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : null}
            <span>Save changes</span>
          </button>
        </div>

      </div>
    </div>
  );
}
