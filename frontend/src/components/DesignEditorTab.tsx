import React, { useState, useEffect, useRef } from 'react';
import {
  Paintbrush, Palette, Sun, Moon, X, Trash2, Plus, Copy, RotateCcw
} from 'lucide-react';
import { USER_COLOR_PALETTES } from '@/lib/colorTheme';

interface DesignEditorTabProps {
  isLight: boolean;
  themeMode: 'light' | 'dark';
  onThemeChange: (mode: 'light' | 'dark') => void;
  accentColor: 'emerald' | 'blue' | 'purple' | 'amber' | 'rose' | 'teal';
  onAccentColorChange?: (color: 'emerald' | 'blue' | 'purple' | 'amber' | 'rose' | 'teal') => void;
  primaryAccentHex?: string;
  onPrimaryAccentHexChange?: (hex: string) => void;
  secondaryAccentHex?: string;
  onSecondaryAccentHexChange?: (hex: string) => void;
  customLogoUrl?: string;
  onCustomLogoChange?: (url: string) => void;
}

const THEME_PRESETS = [
  {
    id: 'ocean',
    name: 'Ozean Blau (Dunkel)',
    icon: '🌊',
    theme: 'dark' as const,
    variables: {
      '--background': '#0b0f19',
      '--foreground': '#f8fafc',
      '--accent-primary': '#2a6f97',
      '--accent-primary-hover': '#1d4ed8',
      '--sidebar-bg': '#0f172a',
      '--sidebar-text': '#f8fafc',
      '--header-bg': '#0b0f19',
      '--kanban-bg': '#0b0f19',
      '--kanban-card-bg': '#111827',
      '--kanban-card-border': '#1f2937',
      '--contact-drawer-bg': '#0b0f19',
      '--contact-link-color': '#38bdf8',
      '--contact-linkedin-link': '#0077b5',
      '--contact-message-inbound-bg': '#1e293b',
      '--contact-message-outbound-bg': '#0f172a',
      '--contact-message-text': '#f8fafc',
      '--contact-message-header-email-bg': '#FFEDD5',
      '--contact-message-header-note-bg': '#D1FAE5',
      '--contact-message-header-meeting-bg': '#FFE4E6',
      '--contact-message-header-linkedin-bg': '#E0F2FE',
      '--calendar-bg': '#0b0f19',
      '--calendar-grid-border': '#1f2937',
      '--calendar-card-bg': '#111827',
      '--calendar-event-google-bg': '#0284c7',
      '--calendar-event-outlook-bg': '#4f46e5',
      '--calendar-event-crm-bg': '#10b981',
      '--mediaboard-bg': '#0b0f19',
      '--mediaboard-card-bg': '#111827',
      '--mediaboard-postit-bg': '#fef08a',
      '--mediaboard-border': '#1f2937'
    }
  },
  {
    id: 'emerald_forest',
    name: 'Smaragd Wald (Dunkel)',
    icon: '🌿',
    theme: 'dark' as const,
    variables: {
      '--background': '#081c15',
      '--foreground': '#d8f3dc',
      '--accent-primary': '#52b788',
      '--accent-primary-hover': '#40916c',
      '--sidebar-bg': '#1b4332',
      '--sidebar-text': '#d8f3dc',
      '--header-bg': '#081c15',
      '--kanban-bg': '#081c15',
      '--kanban-card-bg': '#1b4332',
      '--kanban-card-border': '#2d6a4f',
      '--contact-drawer-bg': '#081c15',
      '--contact-link-color': '#52b788',
      '--contact-linkedin-link': '#0077b5',
      '--contact-message-inbound-bg': '#2d6a4f',
      '--contact-message-outbound-bg': '#1b4332',
      '--contact-message-text': '#d8f3dc',
      '--contact-message-header-email-bg': '#FFEDD5',
      '--contact-message-header-note-bg': '#D1FAE5',
      '--contact-message-header-meeting-bg': '#FFE4E6',
      '--contact-message-header-linkedin-bg': '#E0F2FE',
      '--calendar-bg': '#081c15',
      '--calendar-grid-border': '#2d6a4f',
      '--calendar-card-bg': '#1b4332',
      '--calendar-event-google-bg': '#0284c7',
      '--calendar-event-outlook-bg': '#4f46e5',
      '--calendar-event-crm-bg': '#10b981',
      '--mediaboard-bg': '#081c15',
      '--mediaboard-card-bg': '#1b4332',
      '--mediaboard-postit-bg': '#fde047',
      '--mediaboard-border': '#2d6a4f'
    }
  },
  {
    id: 'light_ocean',
    name: 'Helles Ozeanblau (Hell)',
    icon: '☀️',
    theme: 'light' as const,
    variables: {
      '--background': '#f8fafc',
      '--foreground': '#0f172a',
      '--accent-primary': '#0284c7',
      '--accent-primary-hover': '#0369a1',
      '--sidebar-bg': '#ffffff',
      '--sidebar-text': '#1e293b',
      '--header-bg': '#ffffff',
      '--kanban-bg': '#f1f5f9',
      '--kanban-card-bg': '#ffffff',
      '--kanban-card-border': '#e2e8f0',
      '--contact-drawer-bg': '#ffffff',
      '--contact-link-color': '#2563eb',
      '--contact-linkedin-link': '#0a66c2',
      '--contact-message-inbound-bg': '#ffffff',
      '--contact-message-outbound-bg': '#f8fafc',
      '--contact-message-text': '#0f172a',
      '--contact-message-header-email-bg': '#FFEDD5',
      '--contact-message-header-note-bg': '#D1FAE5',
      '--contact-message-header-meeting-bg': '#FFE4E6',
      '--contact-message-header-linkedin-bg': '#E0F2FE',
      '--calendar-bg': '#ffffff',
      '--calendar-grid-border': '#e2e8f0',
      '--calendar-card-bg': '#ffffff',
      '--calendar-event-google-bg': '#0284c7',
      '--calendar-event-outlook-bg': '#4f46e5',
      '--calendar-event-crm-bg': '#10b981',
      '--mediaboard-bg': '#f8fafc',
      '--mediaboard-card-bg': '#ffffff',
      '--mediaboard-postit-bg': '#fef08a',
      '--mediaboard-border': '#e2e8f0'
    }
  }
];

const subTabKeys = {
  global: [
    '--background',
    '--foreground',
    '--text-muted',
    '--accent-primary',
    '--accent-primary-hover',
    '--sidebar-bg',
    '--sidebar-text',
    '--sidebar-active-bg',
    '--sidebar-active-text',
    '--header-bg',
    '--header-text'
  ],
  kanban: ['--kanban-bg', '--kanban-card-bg', '--kanban-card-border'],
  contacts: [
    '--contact-drawer-bg',
    '--contact-link-color',
    '--contact-linkedin-link',
    '--contact-message-inbound-bg',
    '--contact-message-outbound-bg',
    '--contact-message-text',
    '--contact-message-header-email-bg',
    '--contact-message-header-note-bg',
    '--contact-message-header-meeting-bg',
    '--contact-message-header-linkedin-bg',
    '--contact-message-history-btn-bg',
    '--contact-message-history-btn-border',
    '--contact-message-history-btn-text',
    '--contact-nextstep-color',
    '--contact-tag-bg',
    '--contact-tag-border',
    '--contact-tag-text',
    '--contact-tag-prefix'
  ],
  calendar: [
    '--calendar-bg',
    '--calendar-grid-border',
    '--calendar-card-bg',
    '--calendar-event-google-bg',
    '--calendar-event-google-text',
    '--calendar-event-outlook-bg',
    '--calendar-event-outlook-text',
    '--calendar-event-crm-bg',
    '--calendar-event-crm-text'
  ],
  media: ['--mediaboard-bg', '--mediaboard-card-bg', '--mediaboard-postit-bg', '--mediaboard-border'],
  mission: ['--mission-bg', '--mission-card-bg', '--mission-card-border', '--mission-accent', '--mission-text'],
  studio: [
    '--studio-bg',
    '--studio-card-bg',
    '--studio-card-border',
    '--studio-input-bg',
    '--studio-input-text',
    '--studio-input-border',
    '--studio-accent',
    '--studio-accent-hover',
    '--studio-text',
    '--studio-text-muted',
    '--studio-tab-active-bg',
    '--studio-tab-active-text',
    '--studio-tab-active-border'
  ]
};

const variableLabels: Record<string, string> = {
  '--background': 'Hintergrund Global',
  '--foreground': 'Textfarbe Global (Dunkler Text)',
  '--text-muted': 'Textfarbe Sekundär (Gedämpft)',
  '--accent-primary': 'Akzentfarbe',
  '--accent-primary-hover': 'Akzentfarbe Hover',
  '--sidebar-bg': 'Sidebar Hintergrund',
  '--sidebar-text': 'Sidebar Text',
  '--sidebar-active-bg': 'Sidebar Aktiv Hintergrund',
  '--sidebar-active-text': 'Sidebar Aktiv Text',
  '--header-bg': 'Kopfzeile Hintergrund',
  '--header-text': 'Kopfzeile Textfarbe',

  '--kanban-bg': 'Kanban Hintergrund',
  '--kanban-card-bg': 'Karten Hintergrund',
  '--kanban-card-border': 'Karten Rahmen',

  '--contact-drawer-bg': 'Detailfenster Hintergrund',
  '--contact-link-color': 'E-Mail & Web Links',
  '--contact-linkedin-link': 'LinkedIn Link',
  '--contact-message-inbound-bg': 'Inbound Nachricht Blase',
  '--contact-message-outbound-bg': 'Outbound Nachricht Blase',
  '--contact-message-text': 'Nachrichten Textfarbe',
  '--contact-message-header-email-bg': 'Inbound Mail-Header',
  '--contact-message-header-note-bg': 'Notiz-Header',
  '--contact-message-header-meeting-bg': 'Meeting-Header',
  '--contact-message-header-linkedin-bg': 'LinkedIn-Header',
  '--contact-message-history-btn-bg': 'Button Verlauf Hintergrund',
  '--contact-message-history-btn-border': 'Button Verlauf Rahmen',
  '--contact-message-history-btn-text': 'Button Verlauf Text',
  '--contact-nextstep-color': 'Nächster Schritt: Textfarbe',
  '--contact-tag-bg': 'Tags: Hintergrundfarbe',
  '--contact-tag-border': 'Tags: Rahmenfarbe',
  '--contact-tag-text': 'Tags: Textfarbe',
  '--contact-tag-prefix': 'Tags: Symbol / Präfix',

  '--calendar-bg': 'Kalender Hintergrund',
  '--calendar-grid-border': 'Gitterlinien',
  '--calendar-card-bg': 'Kachel Hintergrund',
  '--calendar-event-google-bg': 'Google Termine',
  '--calendar-event-google-text': 'Google Termine Text',
  '--calendar-event-outlook-bg': 'Outlook Termine',
  '--calendar-event-outlook-text': 'Outlook Termine Text',
  '--calendar-event-crm-bg': 'CRM Termine',
  '--calendar-event-crm-text': 'CRM Termine Text',

  '--mediaboard-bg': 'Board Hintergrund',
  '--mediaboard-card-bg': 'Karten Hintergrund',
  '--mediaboard-postit-bg': 'Post-it Zettel',
  '--mediaboard-border': 'Karten Rahmen',

  '--mission-bg': 'Mission Control Hintergrund',
  '--mission-card-bg': 'Karten Hintergrund',
  '--mission-card-border': 'Karten Rahmen',
  '--mission-accent': 'Akzent / Icons',
  '--mission-text': 'Textfarbe',

  '--studio-bg': 'Studio Hintergrund',
  '--studio-card-bg': 'Karten Hintergrund',
  '--studio-card-border': 'Karten Rahmen',
  '--studio-input-bg': 'Input & Dropdown Hintergrund',
  '--studio-input-text': 'Input & Dropdown Schriftfarbe',
  '--studio-input-border': 'Input & Dropdown Rahmen',
  '--studio-accent': 'Akzentfarbe (Buttons / Regler)',
  '--studio-accent-hover': 'Akzent Hover',
  '--studio-text': 'Haupttext Farbe',
  '--studio-text-muted': 'Dezenter Text',
  '--studio-tab-active-bg': 'Aktiver Reiter Hintergrund',
  '--studio-tab-active-text': 'Aktiver Reiter Text',
  '--studio-tab-active-border': 'Aktiver Reiter Rahmen'
};

function getDefaultVal(key: string): string {
  const defaults: Record<string, string> = {
    '--background': '#0b0f19',
    '--foreground': '#f8fafc',
    '--accent-primary': '#10b981',
    '--accent-primary-hover': '#059669',
    '--sidebar-bg': '#0f172a',
    '--sidebar-text': '#f8fafc',
    '--sidebar-active-bg': 'rgba(16, 185, 129, 0.15)',
    '--sidebar-active-text': '#10b981',
    '--header-bg': '#0f172a',

    '--kanban-bg': '#0b0f19',
    '--kanban-card-bg': '#1e293b',
    '--kanban-card-border': '#334155',

    '--contact-drawer-bg': '#0f172a',
    '--contact-link-color': '#2563eb',
    '--contact-linkedin-link': '#0077b5',
    '--contact-message-inbound-bg': '#1e293b',
    '--contact-message-outbound-bg': '#0f172a',
    '--contact-message-text': '#f8fafc',
    '--contact-message-header-email-bg': '#FFEDD5',
    '--contact-message-header-note-bg': '#D1FAE5',
    '--contact-message-header-meeting-bg': '#FFE4E6',
    '--contact-message-header-linkedin-bg': '#E0F2FE',
    '--contact-message-history-btn-bg': 'rgba(16, 185, 129, 0.1)',
    '--contact-message-history-btn-border': 'rgba(16, 185, 129, 0.3)',
    '--contact-message-history-btn-text': '#10b981',
    '--contact-nextstep-color': '#059669',
    '--contact-tag-bg': '#ecfdf5',
    '--contact-tag-border': '#a7f3d0',
    '--contact-tag-text': '#047857',
    '--contact-tag-prefix': '🏷️',

    '--calendar-bg': '#0b0f19',
    '--calendar-grid-border': '#334155',
    '--calendar-card-bg': '#1e293b',
    '--calendar-event-google-bg': '#0284c7',
    '--calendar-event-google-text': '#ffffff',
    '--calendar-event-outlook-bg': '#4f46e5',
    '--calendar-event-outlook-text': '#ffffff',
    '--calendar-event-crm-bg': '#10b981',
    '--calendar-event-crm-text': '#ffffff',

    '--mediaboard-bg': '#0b0f19',
    '--mediaboard-card-bg': '#1e293b',
    '--mediaboard-postit-bg': '#fef08a',
    '--mediaboard-border': '#334155',

    '--mission-bg': '#0b0f19',
    '--mission-card-bg': '#1e293b',
    '--mission-card-border': '#374151',
    '--mission-accent': '#10b981',
    '--mission-text': '#f8fafc',

    '--studio-bg': '#0b0f19',
    '--studio-card-bg': '#111827',
    '--studio-card-border': '#1f2937',
    '--studio-input-bg': '#0f172a',
    '--studio-input-text': '#f8fafc',
    '--studio-input-border': '#334155',
    '--studio-accent': '#ef4444',
    '--studio-accent-hover': '#dc2626',
    '--studio-text': '#f8fafc',
    '--studio-text-muted': '#94a3b8',
    '--studio-tab-active-bg': 'rgba(239, 68, 68, 0.12)',
    '--studio-tab-active-text': '#f87171',
    '--studio-tab-active-border': '#ef4444'
  };
  return defaults[key] || '';
}

const STATUS_COLUMN_KEYS = [
  { id: 'Unvernetzt', title: 'Unvernetzt', defaultIcon: '👤' },
  { id: 'Vernetzt', title: 'Vernetzt', defaultIcon: '🤝' },
  { id: 'Erstnachricht', title: 'Erstnachricht', defaultIcon: '💬' },
  { id: 'Im Dialog', title: 'Im Dialog', defaultIcon: '🔄' },
  { id: 'Interview vereinbart', title: 'Interview vereinbart', defaultIcon: '📅' },
  { id: 'Regelmäßiger Kontakt', title: 'Regelmäßiger Kontakt', defaultIcon: '🔁' },
  { id: 'Parkposition', title: 'Parkposition', defaultIcon: '📁' },
  { id: 'Pool', title: 'Pool', defaultIcon: '🔮' },
  { id: 'Gesperrt_1Jahr', title: 'Gesperrt (1 Jahr)', defaultIcon: '⛔' }
];

export function DesignEditorTab({
  isLight,
  themeMode,
  onThemeChange,
  primaryAccentHex,
  onPrimaryAccentHexChange,
  secondaryAccentHex,
  onSecondaryAccentHexChange,
  customLogoUrl = '',
  onCustomLogoChange
}: DesignEditorTabProps) {
  const [cssVariables, setCssVariables] = useState<Record<string, string>>({});
  const [pickerTarget, setPickerTarget] = useState<string | null>(null);
  const [subTab, setSubTab] = useState<'global' | 'kanban' | 'contacts' | 'calendar' | 'media' | 'mission' | 'studio'>('global');

  // Custom Presets State
  const [customPresets, setCustomPresets] = useState<any[]>([]);
  const [selectedPresetId, setSelectedPresetId] = useState('');
  const [newPresetName, setNewPresetName] = useState('');

  // Kanban Icons State
  const [customIcons, setCustomIcons] = useState<Record<string, string>>({});

  useEffect(() => {
    try {
      const raw = localStorage.getItem('archon_crm_kanban_icons_v1');
      if (raw) setCustomIcons(JSON.parse(raw));
    } catch {}
  }, []);

  const handleIconChange = (colId: string, val: string) => {
    const updated = { ...customIcons, [colId]: val };
    setCustomIcons(updated);
    localStorage.setItem('archon_crm_kanban_icons_v1', JSON.stringify(updated));
    window.dispatchEvent(new Event('archon_crm_icons_updated'));
  };

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load custom presets from local storage on mount
  useEffect(() => {
    try {
      const stored = localStorage.getItem('archon_custom_presets_v2');
      if (stored) {
        setCustomPresets(JSON.parse(stored));
      } else {
        localStorage.setItem('archon_custom_presets_v2', JSON.stringify(THEME_PRESETS));
        setCustomPresets(THEME_PRESETS);
      }
    } catch (e) {
      setCustomPresets(THEME_PRESETS);
    }
  }, []);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = (event) => {
        if (event.target?.result) {
          onCustomLogoChange?.(event.target.result as string);
        }
      };
      reader.readAsDataURL(file);
    }
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    const file = e.clipboardData.files?.[0];
    if (file && file.type.startsWith('image/')) {
      const reader = new FileReader();
      reader.onload = (event) => {
        if (event.target?.result) {
          onCustomLogoChange?.(event.target.result as string);
        }
      };
      reader.readAsDataURL(file);
    }
  };

  const getCurrentVal = () => {
    if (pickerTarget === 'primary') return primaryAccentHex || '#10b981';
    if (pickerTarget === 'secondary') return secondaryAccentHex || '#ecfdf5';
    if (pickerTarget && cssVariables[pickerTarget]) return cssVariables[pickerTarget];
    return '#10b981';
  };

  const handleColorSelect = (hex: string) => {
    if (pickerTarget === 'primary') {
      onPrimaryAccentHexChange?.(hex);
    } else if (pickerTarget === 'secondary') {
      onSecondaryAccentHexChange?.(hex);
    } else if (pickerTarget) {
      handleCssVarChange(pickerTarget, hex);
    }
    setPickerTarget(null);
  };

  useEffect(() => {
    const rootStyles = getComputedStyle(document.documentElement);
    const vars: Record<string, string> = {};

    const allKeys = [
      ...subTabKeys.global,
      ...subTabKeys.kanban,
      ...subTabKeys.contacts,
      ...subTabKeys.calendar,
      ...subTabKeys.media,
      ...subTabKeys.mission,
      ...subTabKeys.studio
    ];

    allKeys.forEach(k => {
      vars[k] = rootStyles.getPropertyValue(k).trim() || getDefaultVal(k);
    });

    setCssVariables(vars);
  }, [themeMode, primaryAccentHex, secondaryAccentHex]);

  const handleCssVarChange = (key: string, value: string) => {
    document.documentElement.style.setProperty(key, value);
    setCssVariables(prev => ({ ...prev, [key]: value }));
    try {
      localStorage.setItem(`archon_theme_var_${key}`, value);
    } catch (e) {}
  };

  const handlePresetSelect = (presetId: string) => {
    const preset = customPresets.find(p => p.id === presetId);
    if (!preset) return;

    setSelectedPresetId(presetId);
    onThemeChange(preset.theme);

    Object.entries(preset.variables).forEach(([key, val]) => {
      document.documentElement.style.setProperty(key, val as string);
      try {
        localStorage.setItem(`archon_theme_var_${key}`, val as string);
      } catch (e) {}
    });

    if (preset.variables['--accent-primary']) {
      onPrimaryAccentHexChange?.(preset.variables['--accent-primary']);
    }

    setCssVariables(prev => ({ ...prev, ...preset.variables }));
  };

  const handleSaveCurrentAsPreset = () => {
    if (!newPresetName.trim()) {
      alert('Bitte geben Sie einen Namen für die Designvorlage ein.');
      return;
    }
    const newId = 'custom_' + Date.now();
    const newPreset = {
      id: newId,
      name: newPresetName.trim(),
      icon: '🎨',
      theme: themeMode,
      variables: { ...cssVariables }
    };
    const updated = [...customPresets, newPreset];
    setCustomPresets(updated);
    localStorage.setItem('archon_custom_presets_v2', JSON.stringify(updated));
    setSelectedPresetId(newId);
    setNewPresetName('');
  };

  const handleDeletePreset = (id: string) => {
    if (!confirm('Diese Designvorlage wirklich löschen?')) return;
    const updated = customPresets.filter(p => p.id !== id);
    setCustomPresets(updated);
    localStorage.setItem('archon_custom_presets_v2', JSON.stringify(updated));
    if (selectedPresetId === id) setSelectedPresetId('');
  };

  const handleResetToDefault = () => {
    if (!confirm('Alle Design-Einstellungen auf Standard zurücksetzen?')) return;
    const allKeys = [
      ...subTabKeys.global,
      ...subTabKeys.kanban,
      ...subTabKeys.contacts,
      ...subTabKeys.calendar,
      ...subTabKeys.media,
      ...subTabKeys.mission
    ];
    allKeys.forEach(k => {
      const def = getDefaultVal(k);
      document.documentElement.style.setProperty(k, def);
      localStorage.removeItem(`archon_theme_var_${k}`);
    });
    // Reset accents
    onPrimaryAccentHexChange?.('#10b981');
    onSecondaryAccentHexChange?.('#ecfdf5');
    onThemeChange('light');

    // Refresh state
    const vars: Record<string, string> = {};
    allKeys.forEach(k => {
      vars[k] = getDefaultVal(k);
    });
    setCssVariables(vars);
    setSelectedPresetId('');
  };

  return (
    <div className="space-y-4 text-xs" onPaste={handlePaste}>
      
      {/* 1. Logo-Verwaltung */}
      <div className="space-y-2">
        <label className={`block font-bold uppercase text-[10px] tracking-wider ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>
          CRM Firmenlogo (Oben links)
        </label>
        <div className="flex items-center justify-between gap-4 p-3 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/40">
          <div className="flex-1 flex items-center justify-center min-h-[64px] max-h-[80px] bg-white dark:bg-slate-950 p-2 rounded-lg border border-slate-200 dark:border-slate-800 overflow-hidden shadow-inner">
            <img
              src={customLogoUrl || '/archon-logo.png'}
              alt="Logo"
              className="max-h-12 w-auto object-contain"
            />
          </div>
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            accept="image/*"
            className="hidden"
          />
          <div className="flex flex-col gap-2 shrink-0 w-28">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="px-2.5 py-1.5 rounded-lg bg-accent-main text-white font-bold text-[10px] transition cursor-pointer hover:opacity-90 text-center"
            >
              Bild auswählen...
            </button>
            <button
              type="button"
              onClick={() => onCustomLogoChange?.('')}
              className={`px-2.5 py-1.5 rounded-lg font-bold text-[10px] transition cursor-pointer text-center ${
                isLight ? 'bg-rose-100 text-rose-700 hover:bg-rose-200' : 'bg-rose-950/60 text-rose-350 hover:bg-rose-900/80'
              }`}
            >
              Löschen
            </button>
          </div>
        </div>
      </div>

      {/* 2. Theme Mode Selection */}
      <div className="space-y-2 pt-2 border-t border-slate-200 dark:border-slate-800">
        <label className={`block font-bold uppercase text-[10px] tracking-wider ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>
          Erscheinungsbild / Theme
        </label>
        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={() => onThemeChange('light')}
            className={`p-3 rounded-xl border flex items-center gap-2 font-semibold transition cursor-pointer ${
              isLight
                ? 'bg-amber-400/15 border-amber-400 text-amber-900 shadow-xs'
                : 'border-slate-800 text-slate-400 hover:border-slate-700'
            }`}
          >
            <Sun className="w-4 h-4 text-amber-500" />
            <span>Hell Mode</span>
          </button>
          <button
            type="button"
            onClick={() => onThemeChange('dark')}
            className={`p-3 rounded-xl border flex items-center gap-2 font-semibold transition cursor-pointer ${
              !isLight
                ? 'bg-accent-light border-accent-light text-accent-main shadow-xs'
                : 'border-slate-300 text-slate-600 hover:border-slate-400'
            }`}
          >
            <Moon className="w-4 h-4 text-accent-main" />
            <span>Dunkel Mode</span>
          </button>
        </div>
      </div>

      {/* 3. Eigene Design-Vorlagen verwalten */}
      <div className="space-y-2 pt-2 border-t border-slate-200 dark:border-slate-800">
        <label className={`block font-bold uppercase text-[10px] tracking-wider ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>
          Eigene Design-Vorlagen
        </label>
        
        <div className="flex gap-2">
          <select
            value={selectedPresetId}
            onChange={(e) => handlePresetSelect(e.target.value)}
            className={`flex-1 p-2 rounded-xl border font-semibold text-xs focus:outline-none ${
              isLight ? 'border-slate-200 bg-white text-slate-800' : 'border-slate-800 bg-slate-900 text-slate-100'
            }`}
          >
            <option value="" disabled>-- Vorlage auswählen --</option>
            {customPresets.map((p) => (
              <option key={p.id} value={p.id}>
                {p.icon} {p.name}
              </option>
            ))}
          </select>

          {selectedPresetId && (
            <button
              type="button"
              onClick={() => handleDeletePreset(selectedPresetId)}
              className="p-2 rounded-xl border border-red-500/30 text-red-500 hover:bg-red-500/10 transition cursor-pointer flex items-center justify-center shrink-0"
              title="Vorlage löschen"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          )}

          <button
            type="button"
            onClick={handleResetToDefault}
            className={`px-3 py-2 rounded-xl border flex items-center gap-1.5 font-bold transition cursor-pointer ${
              isLight ? 'bg-slate-100 border-slate-200 hover:bg-slate-250 text-slate-700' : 'bg-slate-850 border-slate-800 hover:bg-slate-800 text-slate-200'
            }`}
            title="Design komplett auf Standard zurücksetzen"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span>Standard</span>
          </button>
        </div>

        {/* Neues Preset speichern */}
        <div className="flex gap-2 pt-1">
          <input
            type="text"
            placeholder="Name für neue Vorlage..."
            value={newPresetName}
            onChange={(e) => setNewPresetName(e.target.value)}
            className={`flex-1 p-2 rounded-xl border text-[11px] font-medium ${
              isLight ? 'border-slate-300 text-slate-900 bg-white' : 'border-slate-700 text-slate-100 bg-slate-900'
            }`}
          />
          <button
            type="button"
            onClick={handleSaveCurrentAsPreset}
            className="px-3 py-2 rounded-xl bg-accent-main text-white font-bold transition hover:opacity-90 cursor-pointer flex items-center gap-1 shrink-0"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Speichern</span>
          </button>
        </div>
      </div>

      {/* 4. Reitersystem (Tabs) */}
      <div className="space-y-2 pt-3 border-t border-slate-200 dark:border-slate-800">
        <div className="flex border-b border-slate-200 dark:border-slate-800 gap-1.5 mb-3 overflow-x-auto">
          {(['global', 'kanban', 'contacts', 'calendar', 'media', 'mission', 'studio'] as const).map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setSubTab(tab)}
              className={`pb-1.5 px-2 border-b-2 font-bold text-[11px] transition cursor-pointer whitespace-nowrap ${
                subTab === tab ? 'border-accent-main text-accent-main' : 'border-transparent text-slate-400 hover:text-slate-300'
              }`}
            >
              {tab === 'global' && 'Global & Menü'}
              {tab === 'kanban' && 'Pipeline'}
              {tab === 'contacts' && 'Nachrichten & Links'}
              {tab === 'calendar' && 'Kalender'}
              {tab === 'media' && 'Media Board'}
              {tab === 'mission' && 'Mission Control'}
              {tab === 'studio' && 'Content Studio'}
            </button>
          ))}
        </div>

        {/* Variables Editor list for selected sub-tab */}
        <div className="p-3 rounded-xl border border-slate-200 dark:border-slate-800 space-y-2.5 bg-slate-50/20 dark:bg-slate-900/10">
          {subTabKeys[subTab].map((key) => {
            const value = cssVariables[key] || getDefaultVal(key);

            if (key === '--contact-tag-prefix') {
              return (
                <div key={key} className="flex items-center gap-2">
                  <span className={`font-mono text-xs font-semibold w-1/3 truncate ${isLight ? 'text-slate-800' : 'text-slate-200'}`} title={key}>
                    {variableLabels[key] || key}
                  </span>
                  <div className="flex-1 flex items-center gap-1.5">
                    <select
                      value={value}
                      onChange={(e) => handleCssVarChange(key, e.target.value)}
                      className={`p-1.5 rounded-md border text-[11px] font-sans ${
                        isLight ? 'border-slate-300 text-slate-900 bg-white' : 'border-slate-700 text-slate-100 bg-slate-900'
                      }`}
                    >
                      <option value="🏷️">🏷️ Etikett</option>
                      <option value="#"># Raute</option>
                      <option value="✦">✦ Stern</option>
                      <option value="•">• Bullet</option>
                      <option value="">Kein Symbol</option>
                    </select>
                    <input
                      type="text"
                      value={value}
                      onChange={(e) => handleCssVarChange(key, e.target.value)}
                      placeholder="Eigener Text..."
                      className={`flex-1 p-1.5 rounded-md border text-[11px] font-mono ${
                        isLight ? 'border-slate-300 text-slate-900 bg-white' : 'border-slate-700 text-slate-100 bg-slate-900'
                      }`}
                    />
                  </div>
                </div>
              );
            }

            return (
              <div key={key} className="flex items-center gap-2">
                <span className={`font-mono text-xs font-semibold w-1/3 truncate ${isLight ? 'text-slate-800' : 'text-slate-200'}`} title={key}>
                  {variableLabels[key] || key}
                </span>
                <div className="flex-1 flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => setPickerTarget(key)}
                    className="w-5 h-5 rounded-full border border-slate-300 dark:border-slate-700 shrink-0 shadow-xs transition transform hover:scale-110 cursor-pointer"
                    style={{ backgroundColor: value || '#10b981' }}
                    title={`Farbpalette für ${key} öffnen`}
                  />
                  <input
                    type="text"
                    value={value}
                    onChange={(e) => handleCssVarChange(key, e.target.value)}
                    className={`flex-1 p-1.5 rounded-md border text-[11px] font-mono ${
                      isLight ? 'border-slate-300 text-slate-900 bg-white' : 'border-slate-700 text-slate-100 bg-slate-900'
                    }`}
                  />
                  <button
                    type="button"
                    onClick={() => setPickerTarget(key)}
                    className="p-1 rounded-md border border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 transition cursor-pointer"
                    title={`Farbpalette für ${key} öffnen`}
                  >
                    <Palette className="w-3.5 h-3.5 text-accent-main" />
                  </button>
                </div>
              </div>
            );
          })}

          {/* Status Spalten Icons Option */}
          {subTab === 'kanban' && (
            <div className="pt-3 border-t border-slate-200 dark:border-slate-800/60 mt-3 space-y-2">
              <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                Status Spalten Icons
              </h4>
              <div className="grid grid-cols-1 gap-2.5">
                {STATUS_COLUMN_KEYS.map((col) => {
                  const val = customIcons[col.id] || col.defaultIcon;
                  const isSvg = typeof val === 'string' && /<\s*svg[\s>]/i.test(val);
                  return (
                    <div key={col.id} className="flex items-center gap-2">
                      <span className="text-[10px] text-slate-400 w-1/4 truncate">
                        {col.title}
                      </span>
                      {/* Vorschau: SVGs als echtes Symbol, Emojis direkt */}
                      <span className="flex items-center justify-center w-6 h-6 shrink-0">
                        {isSvg ? (
                          <span
                            className="inline-flex items-center justify-center w-[1.25em] h-[1.25em] [&_svg]:w-full [&_svg]:h-full"
                            dangerouslySetInnerHTML={{ __html: val }}
                          />
                        ) : (
                          <span className="text-base leading-none">{val}</span>
                        )}
                      </span>
                      <input
                        type="text"
                        value={val}
                        onChange={(e) => handleIconChange(col.id, e.target.value)}
                        className={`flex-1 min-w-0 p-1.5 rounded-md border text-xs font-mono ${
                          isLight ? 'border-slate-300 text-slate-900 bg-white' : 'border-slate-700 text-slate-100 bg-slate-900'
                        }`}
                        placeholder={col.defaultIcon}
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Color Swatch Palette Picker Popover */}
      {pickerTarget && (
        <div className="fixed inset-0 z-60 overflow-hidden bg-black/75 backdrop-blur-md flex items-center justify-center p-4">
          <div className={`w-full max-w-lg rounded-2xl border p-5 shadow-2xl space-y-4 animate-in zoom-in-95 duration-150 max-h-[85vh] overflow-y-auto ${
            isLight ? 'bg-white border-slate-200 text-slate-900' : 'bg-slate-900 border-slate-800 text-slate-100'
          }`}>
            <div className="flex items-center justify-between border-b pb-3 border-slate-200 dark:border-slate-800">
              <div className="flex items-center gap-2">
                <Palette className="w-5 h-5 text-accent-main" />
                <div>
                  <h3 className="text-sm font-bold tracking-tight">
                    Farbe auswählen
                  </h3>
                  <p className="text-[11px] text-slate-400">
                    Klicke auf eine Farbe aus deinen Paletten oder gib einen Hex-Code ein.
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setPickerTarget(null)}
                className="p-1.5 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-800 text-slate-400 transition cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex items-center gap-2 p-2.5 rounded-xl border border-slate-200 dark:border-slate-800">
              <span className="font-bold text-[11px] text-slate-400 uppercase">Hex-Code:</span>
              <input
                type="text"
                value={getCurrentVal()}
                onChange={(e) => {
                  const val = e.target.value;
                  if (pickerTarget === 'primary') {
                    onPrimaryAccentHexChange?.(val);
                  } else if (pickerTarget === 'secondary') {
                    onSecondaryAccentHexChange?.(val);
                  } else {
                    handleCssVarChange(pickerTarget, val);
                  }
                }}
                placeholder="#10B981"
                className="flex-1 bg-transparent font-mono text-xs font-bold focus:outline-none uppercase"
              />
              <div
                className="w-6 h-6 rounded-lg border border-slate-300 dark:border-slate-700 shrink-0 shadow-xs"
                style={{ backgroundColor: getCurrentVal() }}
              />
            </div>

            <div className="space-y-4 pt-1">
              {USER_COLOR_PALETTES.map((group) => (
                <div key={group.id} className="space-y-1.5">
                  <div className="flex items-center gap-1.5">
                    <span className="text-sm">{group.icon}</span>
                    <h4 className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                      {group.name} ({group.colors.length})
                    </h4>
                  </div>

                  <div className="grid grid-cols-5 gap-2">
                    {group.colors.map((c) => {
                      const currentVal = getCurrentVal();
                      const isSelected = currentVal?.toLowerCase() === c.hex.toLowerCase();

                      return (
                        <button
                          key={c.hex}
                          type="button"
                          onClick={() => handleColorSelect(c.hex)}
                          className={`group/swatch p-1.5 rounded-xl border flex flex-col items-center gap-1 transition cursor-pointer relative ${
                            isSelected
                              ? 'ring-2 ring-emerald-500 border-emerald-500 bg-emerald-500/10'
                              : isLight
                              ? 'border-slate-200 hover:border-slate-400'
                              : 'border-slate-800 hover:border-slate-600'
                          }`}
                          title={c.hex}
                        >
                          <div
                            className="w-full h-8 rounded-lg border border-white/20 shadow-xs transition transform group-hover/swatch:scale-105"
                            style={{ backgroundColor: c.hex }}
                          />
                          <span className="font-mono text-[9px] font-bold truncate tracking-tighter">
                            {c.hex}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>

            <div className="pt-3 border-t border-slate-200 dark:border-slate-800 flex justify-end">
              <button
                type="button"
                onClick={() => setPickerTarget(null)}
                className="px-4 py-1.5 rounded-lg bg-accent-main text-white font-bold text-xs transition cursor-pointer"
              >
                Farbe wählen
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}