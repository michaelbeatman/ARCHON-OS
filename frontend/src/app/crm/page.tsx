"use client";

import React, { useState, useEffect, useRef } from 'react';
import { pb, KontaktRecord, STATUS_COLUMNS, getProfilbildUrl } from '@/lib/pocketbase';
import { KontaktDrawer } from '@/components/KontaktDrawer';
import { AuthModal } from '@/components/AuthModal';
import { UserDropdown } from '@/components/UserDropdown';
import { ProfileModal } from '@/components/ProfileModal';
import { SettingsModal, AccentColor, ACCENT_COLORS } from '@/components/SettingsModal';
import { DesignEditorTab } from '@/components/DesignEditorTab';
import { applyCustomAccentColors } from '@/lib/colorTheme';
import { CsvImportModal } from '@/components/CsvImportModal';
import { ApiPreviewModal } from '@/components/ApiPreviewModal';
import { NachrichtenverlaufModal } from '@/components/NachrichtenverlaufModal';
import { EditCollectionModal } from '@/components/EditCollectionModal';
import { PbSettingsModal } from '@/components/PbSettingsModal';
import { WatchdogModal } from '@/components/WatchdogModal';
import { CalendarView } from '@/components/CalendarView';
import { AlleNachrichtenView } from '@/components/AlleNachrichtenView';
import { MediaBoardView } from '@/components/MediaBoardView';
import { MissionControlView } from '@/components/MissionControlView';
import { ContentStudioView } from '@/components/ContentStudioView';
import { TeambildungFlowCanvas } from '@/components/TeambildungFlowCanvas';
import { UnifiedAgentControlPanel } from '@/components/UnifiedAgentControlPanel';
import CssLiveStudio from '@/components/CssLiveStudio';
import {
  Bot,
  Radar,
  Settings2,
  Search,
  Plus,
  Filter,
  LayoutGrid,
  List,
  Star,
  Building2,
  MapPin,
  Calendar,
  AlertTriangle,
  Target,
  RefreshCw,
  UserCheck,
  CheckCircle2,
  SlidersHorizontal,
  Database,
  BarChart3,
  Users,
  Settings,
  ShieldAlert,
  Sun,
  Moon,
  Columns,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  ArrowDown,
  ArrowUpDown,
  GripVertical,
  RotateCcw,
  Upload,
  User,
  FilterX,
  CheckSquare,
  Square,
  Clock,
  Palette,
  Paintbrush,
  Sparkles,
  Code,
  Trash2,
  MessageSquare,
  Image as ImageIcon,
  CheckSquare2,
  Cog,
  Tag,
  X,
  Boxes,
  Cpu,
  Zap,
  Film,
  Clapperboard
} from 'lucide-react';


// Column definition interface representing all 15 fields from PocketBase schema
interface ColumnConfig {
  key: string;
  label: string;
  typeIcon: string;
  defaultVisible: boolean;
  isTechnical?: boolean;
}

const DEFAULT_COLUMNS: ColumnConfig[] = [
  { key: 'name', label: 'Name', typeIcon: 'T', defaultVisible: true },
  { key: 'tags', label: 'Tags', typeIcon: '🏷️', defaultVisible: false },
  { key: 'email', label: 'E-Mail', typeIcon: '@', defaultVisible: true },
  { key: 'webseite', label: 'Webseite', typeIcon: '🌐', defaultVisible: true },
  { key: 'adresse', label: 'Adresse', typeIcon: '📍', defaultVisible: true },
  { key: 'telefon_1', label: 'Telefon 1', typeIcon: '📞', defaultVisible: true },
  { key: 'telefon_2', label: 'Telefon 2', typeIcon: '📞', defaultVisible: false },
  { key: 'linkedin_url', label: 'LinkedIn URL', typeIcon: '🔗', defaultVisible: false },
  { key: 'unternehmen', label: 'Unternehmen', typeIcon: 'T', defaultVisible: true },
  { key: 'rolle', label: 'Rolle / Position', typeIcon: 'T', defaultVisible: true },
  { key: 'status', label: 'Status', typeIcon: '≡', defaultVisible: true },
  { key: 'region', label: 'Region', typeIcon: 'T', defaultVisible: true },
  { key: 'rating', label: 'Rating', typeIcon: '#', defaultVisible: true },
  { key: 'naechster_schritt', label: 'Nächster Schritt', typeIcon: 'T', defaultVisible: true },
  { key: 'vernetzt_am', label: 'Vernetzt / Erstellt', typeIcon: '📅', defaultVisible: true },
  { key: 'einladung_zurueckgezogen_am', label: 'Sperrfrist Date', typeIcon: '📅', defaultVisible: true },
  { key: 'LinkedInheader', label: 'LinkedIn Headline', typeIcon: 'T', defaultVisible: false },
  { key: 'Linkedin_info', label: 'LinkedIn Info', typeIcon: 'T', defaultVisible: false },
  { key: 'RollenVerteilungzuordnung', label: 'Rollen-Zuordnung', typeIcon: '≡', defaultVisible: false },
  { key: 'kommentar', label: 'Kommentar / Notizen', typeIcon: 'T', defaultVisible: false },
  { key: 'nachrichtenverlauf', label: 'Nachrichtenverlauf', typeIcon: '{}', defaultVisible: true },
  { key: 'profilbild', label: 'Profilbild', typeIcon: '🖼️', defaultVisible: false },
  { key: 'id', label: 'System ID (id)', typeIcon: 'Ow', defaultVisible: false, isTechnical: true },
  { key: 'created', label: 'Erstellt am (created)', typeIcon: '📅', defaultVisible: false, isTechnical: true },
  { key: 'updated', label: 'Aktualisiert am', typeIcon: '📅', defaultVisible: true },
];

const LOCAL_STORAGE_KEY = 'crm_column_preferences_v2';
const LOCAL_STORAGE_WIDTHS_KEY = 'archon_crm_column_widths_v1';

const DEFAULT_COLUMN_WIDTHS: Record<string, number> = {
  name: 180,
  tags: 160,
  email: 200,
  webseite: 160,
  adresse: 180,
  telefon_1: 150,
  telefon_2: 150,
  linkedin_url: 140,
  unternehmen: 170,
  rolle: 170,
  status: 140,
  region: 130,
  rating: 100,
  naechster_schritt: 180,
  vernetzt_am: 120,
  einladung_zurueckgezogen_am: 130,
  kommentar: 200,
  LinkedInheader: 200,
  Linkedin_info: 220,
  RollenVerteilungzuordnung: 150,
  nachrichtenverlauf: 140,
  profilbild: 100,
  id: 120,
  created: 140,
  updated: 140
};

export default function CrmPage() {
  const [hasMounted, setHasMounted] = useState(false);

  useEffect(() => {
    setHasMounted(true);
    try {
      localStorage.removeItem('crm_theme_live_overrides');
      const st = document.getElementById('crm-live-custom-styles');
      if (st) st.remove();
    } catch {}
  }, []);

  const [kontakte, setKontakte] = useState<KontaktRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'pipeline' | 'tabelle'>('pipeline');
  const [selectedNav, setSelectedNav] = useState<'orchestrator' | 'agent-control' | 'pipeline' | 'kontakte' | 'dashboard' | 'settings' | 'kalender' | 'nachrichten' | 'mediaboard' | 'content-studio' | 'mission'>('mission');
  const [activeAgentId, setActiveAgentId] = useState<string>('hermes');

  // Auth & User State
  const [currentUser, setCurrentUser] = useState<any>(pb.authStore.model);
  const [isAuthModalOpen, setIsAuthModalOpen] = useState<boolean>(!pb.authStore.isValid);

  // Modals
  const [isProfileModalOpen, setIsProfileModalOpen] = useState(false);
  const [isWatchdogModalOpen, setIsWatchdogModalOpen] = useState(false);
  const [isSettingsModalOpen, setIsSettingsModalOpen] = useState(false);
  const [isDesignEditorOpen, setIsDesignEditorOpen] = useState(false);
  const [isPbSettingsModalOpen, setIsPbSettingsModalOpen] = useState(false);
  const [pbSettingsSection, setPbSettingsSection] = useState('Application');
  const [isEditCollectionModalOpen, setIsEditCollectionModalOpen] = useState(false);
  const [isCsvModalOpen, setIsCsvModalOpen] = useState(false);
  const [isApiPreviewModalOpen, setIsApiPreviewModalOpen] = useState(false);

  // Nachrichtenverlauf Modal State
  const [nachrichtenModalOpen, setNachrichtenModalOpen] = useState(false);
  const [selectedNachrichtenKontakt, setSelectedNachrichtenKontakt] = useState<KontaktRecord | null>(null);

  // Theme Mode & Accent Color
  const [themeMode, setThemeMode] = useState<'light' | 'dark'>('light');
  const [accentColor, setAccentColor] = useState<AccentColor>('emerald');
  const [primaryAccentHex, setPrimaryAccentHex] = useState<string>('#10b981');
  const [secondaryAccentHex, setSecondaryAccentHex] = useState<string>('#ecfdf5');

  // Custom Logo State
  const [customLogoUrl, setCustomLogoUrl] = useState<string>('');

  // Undo Stack State for Soft Delete
  interface UndoItem {
    id: string;
    name: string;
    deleted_at: string;
  }
  const [undoStack, setUndoStack] = useState<UndoItem[]>([]);
  const [undoToastVisible, setUndoToastVisible] = useState(false);

  const pushToUndoStack = (items: { id: string; name: string }[]) => {
    const newItems: UndoItem[] = items.map(item => ({
      id: item.id,
      name: item.name,
      deleted_at: new Date().toISOString()
    }));
    setUndoStack(prev => [...newItems, ...prev].slice(0, 5));
    setUndoToastVisible(true);
  };

  const handleUndo = async (itemToUndo?: UndoItem) => {
    const target = itemToUndo || undoStack[0];
    if (!target) return;

    try {
      await pb.collection('Kontakte').update(target.id, { deleted_at: null });
      setUndoStack(prev => prev.filter(item => item.id !== target.id));
      if (undoStack.length <= 1) {
        setUndoToastVisible(false);
      }
      fetchKontakte();
    } catch (err) {
      console.error('Undo failed:', err);
    }
  };

  // Kanban Icons State
  const [kanbanIcons, setKanbanIcons] = useState<Record<string, string>>({});

  const loadKanbanIcons = () => {
    try {
      const raw = localStorage.getItem('archon_crm_kanban_icons_v1');
      if (raw) {
        setKanbanIcons(JSON.parse(raw));
      } else {
        setKanbanIcons({});
      }
    } catch {}
  };

  useEffect(() => {
    loadKanbanIcons();
    const handler = () => loadKanbanIcons();
    window.addEventListener('archon_crm_icons_updated', handler);
    return () => window.removeEventListener('archon_crm_icons_updated', handler);
  }, []);



  const getColumnIcon = (colId: string) => {
    if (kanbanIcons[colId]) return kanbanIcons[colId];
    const col = STATUS_COLUMNS.find(c => c.id === colId);
    return col?.icon || '👤';
  };

  // Rendert ein Spalten-Icon: Erkennt eingefügten SVG-Code und zeigt ihn als
  // echtes Symbol (statt als rohen Text). Emojis/Buchstaben bleiben wie zuvor.
  const ColumnIcon = ({ colId }: { colId: string }) => {
    const raw = getColumnIcon(colId);
    if (typeof raw === 'string' && /<\s*svg[\s>]/i.test(raw)) {
      return (
        <span
          className="inline-flex items-center justify-center h-[1.25em] w-[1.25em] [&_svg]:w-full [&_svg]:h-full"
          dangerouslySetInnerHTML={{ __html: raw }}
        />
      );
    }
    return <>{raw}</>;
  };

  // Load Theme Settings from Database/LocalStorage
  useEffect(() => {
    const applyVariables = (variables: Record<string, string>) => {
      Object.entries(variables).forEach(([key, value]) => {
        if (key.startsWith('--') && value) {
          document.documentElement.style.setProperty(key, value);
        }
      });
    };

    const loadTheme = async () => {
      // 1. First load from localStorage for quick rendering
      try {
        const localSettingsRaw = localStorage.getItem('archon_crm_theme_settings_v1');
        if (localSettingsRaw) {
          const localSettings = JSON.parse(localSettingsRaw);
          if (localSettings.themeMode) setThemeMode(localSettings.themeMode);
          if (localSettings.accentColor) setAccentColor(localSettings.accentColor);
          if (localSettings.primaryAccentHex) setPrimaryAccentHex(localSettings.primaryAccentHex);
          if (localSettings.secondaryAccentHex) setSecondaryAccentHex(localSettings.secondaryAccentHex);
          if (localSettings.customLogoUrl) setCustomLogoUrl(localSettings.customLogoUrl);
          if (localSettings.variables) applyVariables(localSettings.variables);
        } else {
          // Fallback: load individual legacy localStorage variables
          const savedPrimary = localStorage.getItem('archon_crm_primary_accent_hex');
          const savedSecondary = localStorage.getItem('archon_crm_secondary_accent_hex');
          if (savedPrimary) {
            setPrimaryAccentHex(savedPrimary);
            if (savedSecondary) setSecondaryAccentHex(savedSecondary);
            applyCustomAccentColors(savedPrimary, savedSecondary || undefined);
          }
          const savedAccent = localStorage.getItem('archon_crm_accent_color_v1') as AccentColor;
          if (savedAccent) {
            setAccentColor(savedAccent);
            document.documentElement.setAttribute('data-accent', savedAccent);
          }
        }

        const allKeys = [
          '--background', '--foreground', '--accent-primary', '--accent-primary-hover',
          '--sidebar-bg', '--sidebar-text', '--sidebar-active-bg', '--sidebar-active-text', '--header-bg',
          '--contact-drawer-bg', '--contact-link-color', '--contact-linkedin-link',
          '--contact-message-inbound-bg', '--contact-message-outbound-bg', '--contact-message-text',
          '--contact-message-header-email-bg', '--contact-message-header-note-bg', '--contact-message-header-meeting-bg', '--contact-message-header-linkedin-bg',
          '--contact-message-history-btn-bg', '--contact-message-history-btn-border', '--contact-message-history-btn-text',
          '--contact-nextstep-color',
          '--contact-tag-bg', '--contact-tag-border', '--contact-tag-text', '--contact-tag-prefix',
          '--kanban-bg', '--kanban-card-bg', '--kanban-card-border',
          '--calendar-bg', '--calendar-grid-border', '--calendar-card-bg',
          '--calendar-event-google-bg', '--calendar-event-google-text',
          '--calendar-event-outlook-bg', '--calendar-event-outlook-text',
          '--calendar-event-crm-bg', '--calendar-event-crm-text',
          '--mediaboard-bg', '--mediaboard-postit-bg', '--mediaboard-card-bg', '--mediaboard-border',
          '--mission-bg', '--mission-card-bg', '--mission-card-border', '--mission-accent', '--mission-text',
          '--studio-bg', '--studio-card-bg', '--studio-card-border', '--studio-input-bg', '--studio-input-text', '--studio-input-border',
          '--studio-accent', '--studio-accent-hover', '--studio-text', '--studio-text-muted',
          '--studio-tab-active-bg', '--studio-tab-active-text', '--studio-tab-active-border'
        ];
        allKeys.forEach(k => {
          const val = localStorage.getItem(`archon_theme_var_${k}`);
          if (val) {
            document.documentElement.style.setProperty(k, val);
          }
        });
      } catch (e) {
        console.warn("Failed loading theme from localStorage", e);
      }

      // 2. Fetch from PocketBase users collection if authenticated
      if (pb.authStore.isValid && pb.authStore.model) {
        try {
          const userRecord = await pb.collection('users').getOne(pb.authStore.model.id);
          const themeSettings = userRecord.theme_settings;
          if (themeSettings) {
            const settingsObj = typeof themeSettings === 'string' ? JSON.parse(themeSettings) : themeSettings;
            if (settingsObj.themeMode) setThemeMode(settingsObj.themeMode);
            if (settingsObj.accentColor) setAccentColor(settingsObj.accentColor);
            if (settingsObj.primaryAccentHex) setPrimaryAccentHex(settingsObj.primaryAccentHex);
            if (settingsObj.secondaryAccentHex) setSecondaryAccentHex(settingsObj.secondaryAccentHex);
            if (settingsObj.customLogoUrl) setCustomLogoUrl(settingsObj.customLogoUrl);
            if (settingsObj.variables) applyVariables(settingsObj.variables);

            // Sync back to localstorage for cache consistency
            localStorage.setItem('archon_crm_theme_settings_v1', JSON.stringify(settingsObj));
            Object.entries(settingsObj.variables || {}).forEach(([k, v]) => {
              if (typeof v === 'string') localStorage.setItem(`archon_theme_var_${k}`, v);
            });
          }
        } catch (err) {
          console.warn("Could not retrieve custom theme settings from PocketBase user collection.", err);
        }
      }
    };

    loadTheme();
  }, [currentUser]);

  const handleSaveThemeSettings = async () => {
    const allKeys = [
      '--background', '--foreground', '--accent-primary', '--accent-primary-hover',
      '--sidebar-bg', '--sidebar-text', '--sidebar-active-bg', '--sidebar-active-text', '--header-bg',
      '--contact-drawer-bg', '--contact-link-color', '--contact-linkedin-link',
      '--contact-message-inbound-bg', '--contact-message-outbound-bg', '--contact-message-text',
      '--contact-message-header-email-bg', '--contact-message-header-note-bg', '--contact-message-header-meeting-bg', '--contact-message-header-linkedin-bg',
      '--contact-message-history-btn-bg', '--contact-message-history-btn-border', '--contact-message-history-btn-text',
      '--contact-nextstep-color',
      '--contact-tag-bg', '--contact-tag-border', '--contact-tag-text', '--contact-tag-prefix',
      '--kanban-bg', '--kanban-card-bg', '--kanban-card-border',
      '--calendar-bg', '--calendar-grid-border', '--calendar-card-bg',
      '--calendar-event-google-bg', '--calendar-event-google-text',
      '--calendar-event-outlook-bg', '--calendar-event-outlook-text',
      '--calendar-event-crm-bg', '--calendar-event-crm-text',
      '--mediaboard-bg', '--mediaboard-postit-bg', '--mediaboard-card-bg', '--mediaboard-border',
      '--mission-bg', '--mission-card-bg', '--mission-card-border', '--mission-accent', '--mission-text',
      '--studio-bg', '--studio-card-bg', '--studio-card-border', '--studio-input-bg', '--studio-input-text', '--studio-input-border',
      '--studio-accent', '--studio-accent-hover', '--studio-text', '--studio-text-muted',
      '--studio-tab-active-bg', '--studio-tab-active-text', '--studio-tab-active-border'
    ];
    const vars: Record<string, string> = {};
    const rootStyles = getComputedStyle(document.documentElement);
    allKeys.forEach(k => {
      vars[k] = rootStyles.getPropertyValue(k).trim() || localStorage.getItem(`archon_theme_var_${k}`) || '';
    });

    const themeSettings = {
      themeMode,
      accentColor,
      primaryAccentHex,
      secondaryAccentHex,
      customLogoUrl,
      variables: vars
    };

    // Save to localStorage
    try {
      localStorage.setItem('archon_crm_theme_settings_v1', JSON.stringify(themeSettings));
      // Save individual fields for backwards compatibility
      localStorage.setItem('archon_crm_primary_accent_hex', primaryAccentHex);
      localStorage.setItem('archon_crm_secondary_accent_hex', secondaryAccentHex);
      localStorage.setItem('archon_crm_accent_color_v1', accentColor);
      localStorage.setItem('archon_crm_custom_logo_v1', customLogoUrl);
    } catch (e) {}

    // Save to PocketBase users collection if authenticated
    if (pb.authStore.isValid && pb.authStore.model) {
      try {
        await pb.collection('users').update(pb.authStore.model.id, {
          theme_settings: themeSettings
        });
        console.log("[Theme Sync] Custom theme saved to PocketBase user record.");
      } catch (err) {
        console.warn(
          "Could not save theme to PocketBase users collection. " +
          "If this is on your own server, please add a 'theme_settings' field (Type: JSON) to the 'users' collection.",
          err
        );
      }
    }
  };

  const handlePrimaryAccentHexChange = (hex: string) => {
    setPrimaryAccentHex(hex);
    applyCustomAccentColors(hex, secondaryAccentHex);
    try {
      localStorage.setItem('archon_crm_primary_accent_hex', hex);
    } catch (e) {}
  };

  const handleSecondaryAccentHexChange = (hex: string) => {
    setSecondaryAccentHex(hex);
    applyCustomAccentColors(primaryAccentHex, hex);
    try {
      localStorage.setItem('archon_crm_secondary_accent_hex', hex);
    } catch (e) {}
  };

  const handleAccentColorChange = (color: AccentColor) => {
    setAccentColor(color);
    document.documentElement.setAttribute('data-accent', color);
    const preset = ACCENT_COLORS.find(c => c.id === color);
    if (preset) {
      setPrimaryAccentHex(preset.hex);
      setSecondaryAccentHex('');
      applyCustomAccentColors(preset.hex, '');
      try {
        localStorage.setItem('archon_crm_primary_accent_hex', preset.hex);
        localStorage.removeItem('archon_crm_secondary_accent_hex');
      } catch (e) {}
    }
    try {
      localStorage.setItem('archon_crm_accent_color_v1', color);
    } catch (e) {}
  };

  const handleCustomLogoChange = (url: string) => {
    setCustomLogoUrl(url);
    try {
      if (url) {
        localStorage.setItem('archon_crm_custom_logo_v1', url);
      } else {
        localStorage.removeItem('archon_crm_custom_logo_v1');
      }
    } catch (e) {}
  };

  // Bulk Selection State
  const [selectedRowIds, setSelectedRowIds] = useState<string[]>([]);
  const [bulkStatusTarget, setBulkStatusTarget] = useState<string>('');

  // Advanced Filters
  const [searchTerm, setSearchTerm] = useState('');
  const [ratingFilter, setRatingFilter] = useState<number | 'ALL'>('ALL');
  const [regionFilter, setRegionFilter] = useState('');
  const DEFAULT_STATUS_FILTERS = STATUS_COLUMNS.filter(c => c.id !== 'Gesperrt_1Jahr').map(c => c.id);
  const [selectedStatusFilters, setSelectedStatusFilters] = useState<string[]>(DEFAULT_STATUS_FILTERS);
  const [statusDropdownOpen, setStatusDropdownOpen] = useState(false);
  const [selectedTagFilters, setSelectedTagFilters] = useState<string[]>([]);
  const [tagDropdownOpen, setTagDropdownOpen] = useState(false);
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  // Drag & Drop State for Kanban
  const [draggedCardId, setDraggedCardId] = useState<string | null>(null);
  const [dragOverColumnId, setDragOverColumnId] = useState<string | null>(null);

  // Slide-Over Drawer state
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedKontakt, setSelectedKontakt] = useState<KontaktRecord | null>(null);

  // Mission Control Contact Search
  const [missionSearch, setMissionSearch] = useState('');
  const [missionResults, setMissionResults] = useState<KontaktRecord[]>([]);
  const [missionSearchFocused, setMissionSearchFocused] = useState(false);
  const [missionHighlight, setMissionHighlight] = useState(0);
  const missionSearchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const q = missionSearch.trim().toLowerCase();
    if (!q) { setMissionResults([]); return; }
    setMissionResults(
      kontakte.filter(k =>
        (k.name || '').toLowerCase().includes(q) ||
        (k.unternehmen || '').toLowerCase().includes(q) ||
        (k.rolle || '').toLowerCase().includes(q)
      ).slice(0, 8)
    );
    setMissionHighlight(0);
  }, [missionSearch, kontakte]);

  const openMissionContact = (k: KontaktRecord) => {
    setMissionSearch('');
    setMissionResults([]);
    setSelectedNav('kontakte');
    setActiveTab('tabelle');
    setTimeout(() => { setSelectedKontakt(k); setDrawerOpen(true); }, 50);
  };

  const handleMissionSearchKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setMissionHighlight(i => Math.min(i + 1, missionResults.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setMissionHighlight(i => Math.max(i - 1, 0)); }
    else if (e.key === 'Enter') { e.preventDefault(); const t = missionResults[missionHighlight] ?? missionResults[0]; if (t) openMissionContact(t); }
    else if (e.key === 'Escape') { setMissionSearch(''); setMissionResults([]); }
  };

  // Column Visibility & Order State
  const [columnOrder, setColumnOrder] = useState<string[]>(DEFAULT_COLUMNS.map(c => c.key));
  const [columnVisibility, setColumnVisibility] = useState<Record<string, boolean>>(() => {
    const initial: Record<string, boolean> = {};
    DEFAULT_COLUMNS.forEach(c => { initial[c.key] = c.defaultVisible; });
    return initial;
  });

  const [columnDropdownOpen, setColumnDropdownOpen] = useState(false);
  const [draggedColKey, setDraggedColKey] = useState<string | null>(null);

  // Column Resizing State
  const [columnWidths, setColumnWidths] = useState<Record<string, number>>(DEFAULT_COLUMN_WIDTHS);
  const [resizingColKey, setResizingColKey] = useState<string | null>(null);
  const [resizeStartX, setResizeStartX] = useState<number>(0);
  const [resizeStartWidth, setResizeStartWidth] = useState<number>(0);

  // Connection state
  const [isLiveConnected, setIsLiveConnected] = useState(false);

  // Listen to Auth Store Changes
  useEffect(() => {
    return pb.authStore.onChange((token, model) => {
      setCurrentUser(model);
      setIsAuthModalOpen(!pb.authStore.isValid);
    });
  }, []);

  // Restore column preferences & widths from LocalStorage
  useEffect(() => {
    try {
      const saved = localStorage.getItem(LOCAL_STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (parsed.columnOrder && Array.isArray(parsed.columnOrder)) {
          setColumnOrder(parsed.columnOrder);
        }
        if (parsed.columnVisibility && typeof parsed.columnVisibility === 'object') {
          setColumnVisibility(parsed.columnVisibility);
        }
      }
      const savedWidths = localStorage.getItem(LOCAL_STORAGE_WIDTHS_KEY);
      if (savedWidths) {
        const parsedWidths = JSON.parse(savedWidths);
        if (parsedWidths && typeof parsedWidths === 'object') {
          setColumnWidths(prev => ({ ...prev, ...parsedWidths }));
        }
      }
    } catch (e) {
      console.warn('Could not restore column settings:', e);
    }
  }, []);

  // Handle Column Resizing Drag
  const handleResizeMouseDown = (e: React.MouseEvent, colKey: string) => {
    e.stopPropagation();
    e.preventDefault();
    setResizingColKey(colKey);
    setResizeStartX(e.clientX);
    setResizeStartWidth(columnWidths[colKey] || DEFAULT_COLUMN_WIDTHS[colKey] || 150);
  };

  useEffect(() => {
    if (!resizingColKey) return;

    const handleMouseMove = (e: MouseEvent) => {
      const delta = e.clientX - resizeStartX;
      const newWidth = Math.max(70, resizeStartWidth + delta);
      setColumnWidths(prev => {
        const next = { ...prev, [resizingColKey]: newWidth };
        try {
          localStorage.setItem(LOCAL_STORAGE_WIDTHS_KEY, JSON.stringify(next));
        } catch (err) {}
        return next;
      });
    };

    const handleMouseUp = () => {
      setResizingColKey(null);
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [resizingColKey, resizeStartX, resizeStartWidth]);

  // Save column preferences to LocalStorage
  const saveColumnPreferences = (newOrder: string[], newVisibility: Record<string, boolean>) => {
    setColumnOrder(newOrder);
    setColumnVisibility(newVisibility);
    try {
      localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify({
        columnOrder: newOrder,
        columnVisibility: newVisibility
      }));
    } catch (e) {
      console.warn('Could not save column settings:', e);
    }
  };

  const toggleColumnVisibility = (key: string) => {
    const nextVisibility = { ...columnVisibility, [key]: !columnVisibility[key] };
    saveColumnPreferences(columnOrder, nextVisibility);
  };

  const resetColumnPreferences = () => {
    const defaultOrder = DEFAULT_COLUMNS.map(c => c.key);
    const defaultVis: Record<string, boolean> = {};
    DEFAULT_COLUMNS.forEach(c => { defaultVis[c.key] = c.defaultVisible; });
    saveColumnPreferences(defaultOrder, defaultVis);
  };

  const moveColumn = (key: string, direction: 'left' | 'right') => {
    const idx = columnOrder.indexOf(key);
    if (idx < 0) return;
    const targetIdx = direction === 'left' ? idx - 1 : idx + 1;
    if (targetIdx < 0 || targetIdx >= columnOrder.length) return;

    const newOrder = [...columnOrder];
    const temp = newOrder[idx];
    newOrder[idx] = newOrder[targetIdx];
    newOrder[targetIdx] = temp;
    saveColumnPreferences(newOrder, columnVisibility);
  };

  // Fetch contacts
  const fetchKontakte = async () => {
    try {
      setLoading(true);
      const records = await pb.collection('Kontakte').getFullList<KontaktRecord>({
        sort: 'name',
      });
      // Filter out soft-deleted contacts
      const activeRecords = records.filter(r => !r.deleted_at);
      setKontakte(activeRecords);
      setIsLiveConnected(true);
    } catch (err) {
      console.warn('PocketBase fetch error:', err);
      setIsLiveConnected(false);
    } finally {
      setLoading(false);
    }
  };

  // Fetch initial contacts & setup realtime subscription
  useEffect(() => {
    fetchKontakte();

    let unsubscribe: (() => void) | undefined;
    pb.collection('Kontakte').subscribe<KontaktRecord>('*', (e) => {
      if (e.action === 'create') {
        if (!e.record.deleted_at) {
          setKontakte((prev) => [e.record, ...prev]);
        }
      } else if (e.action === 'update') {
        if (e.record.deleted_at) {
          setKontakte((prev) => prev.filter((k) => k.id !== e.record.id));
        } else {
          setKontakte((prev) => {
            const exists = prev.some(k => k.id === e.record.id);
            if (exists) {
              return prev.map((k) => (k.id === e.record.id ? e.record : k));
            } else {
              return [e.record, ...prev];
            }
          });
        }
      } else if (e.action === 'delete') {
        setKontakte((prev) => prev.filter((k) => k.id !== e.record.id));
      }
    }).then((unsub) => {
      unsubscribe = unsub;
    }).catch((err) => console.warn('Realtime subscription warning:', err));

    return () => {
      if (unsubscribe) unsubscribe();
      pb.collection('Kontakte').unsubscribe('*');
    };
  }, []);

  // Unique list of regions from dataset
  const availableRegions = Array.from(
    new Set(kontakte.map((k) => k.region).filter(Boolean))
  ) as string[];

  // Unique list of tags from dataset
  const allUniqueTags = Array.from(
    new Set(kontakte.flatMap((k) => (Array.isArray(k.tags) ? k.tags : [])).filter(Boolean))
  ).sort();

  // Gesamtzahl aller Nachrichten (für den Sidebar-Badge)
  const nachrichtenCount = React.useMemo(() => {
    let count = 0;
    for (const k of kontakte) {
      const nv = k.nachrichtenverlauf;
      if (!nv) continue;
      if (Array.isArray(nv)) count += nv.length;
      else if (typeof nv === 'string') {
        try { const p = JSON.parse(nv); if (Array.isArray(p)) count += p.length; } catch { /* ignore */ }
      }
    }
    return count;
  }, [kontakte]);

  // Sorting State
  const [sortField, setSortField] = useState<string>('name');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc');

  const handleSort = (fieldKey: string) => {
    if (sortField === fieldKey) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(fieldKey);
      setSortDirection('asc');
    }
  };

  // Filtered & Sorted contacts calculation
  const filteredKontakte = React.useMemo(() => {
    const list = kontakte.filter((k) => {
      const matchesSearch =
        !searchTerm ||
        k.name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        k.unternehmen?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        k.rolle?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        k.region?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        (Array.isArray(k.tags) && k.tags.some(t => t.toLowerCase().includes(searchTerm.toLowerCase())));

      const matchesRating = ratingFilter === 'ALL' || k.rating === ratingFilter;
      const matchesRegion = !regionFilter || k.region?.toLowerCase().includes(regionFilter.toLowerCase());

      const matchesStatusList =
        selectedStatusFilters.length === 0 || selectedStatusFilters.includes(k.status);

      const matchesTagList =
        selectedTagFilters.length === 0 ||
        (Array.isArray(k.tags) && selectedTagFilters.every((t) => k.tags!.includes(t)));

      let matchesDate = true;
      if (dateFrom || dateTo) {
        const kDate = k.vernetzt_am || k.einladung_zurueckgezogen_am;
        if (!kDate) {
          matchesDate = false;
        } else {
          if (dateFrom && kDate < dateFrom) matchesDate = false;
          if (dateTo && kDate > dateTo) matchesDate = false;
        }
      }

      return matchesSearch && matchesRating && matchesRegion && matchesStatusList && matchesTagList && matchesDate;
    });

    if (sortField) {
      list.sort((a, b) => {
        // Special chronological sorting for dates
        if (['vernetzt_am', 'created', 'updated', 'einladung_zurueckgezogen_am'].includes(sortField)) {
          let timeA = 0;
          let timeB = 0;
          
          if (sortField === 'vernetzt_am') {
            timeA = new Date(a.vernetzt_am || a.created || 0).getTime();
            timeB = new Date(b.vernetzt_am || b.created || 0).getTime();
          } else if (sortField === 'created') {
            timeA = new Date(a.created || a.vernetzt_am || 0).getTime();
            timeB = new Date(b.created || b.vernetzt_am || 0).getTime();
          } else {
            timeA = new Date((a as any)[sortField] || 0).getTime();
            timeB = new Date((b as any)[sortField] || 0).getTime();
          }

          if (isNaN(timeA)) timeA = 0;
          if (isNaN(timeB)) timeB = 0;

          return sortDirection === 'asc' ? timeA - timeB : timeB - timeA;
        }

        let valA: any = (a as any)[sortField];
        let valB: any = (b as any)[sortField];

        if (valA === undefined || valA === null) valA = '';
        if (valB === undefined || valB === null) valB = '';

        if (Array.isArray(valA)) valA = valA.join(', ');
        if (Array.isArray(valB)) valB = valB.join(', ');

        if (typeof valA === 'number' && typeof valB === 'number') {
          return sortDirection === 'asc' ? valA - valB : valB - valA;
        }

        const strA = String(valA).toLowerCase();
        const strB = String(valB).toLowerCase();

        if (strA < strB) return sortDirection === 'asc' ? -1 : 1;
        if (strA > strB) return sortDirection === 'asc' ? 1 : -1;
        return 0;
      });
    }

    return list;
  }, [kontakte, searchTerm, ratingFilter, regionFilter, selectedStatusFilters, selectedTagFilters, dateFrom, dateTo, sortField, sortDirection]);

  // Bulk Selection Handlers
  const handleSelectAllRows = () => {
    if (selectedRowIds.length === filteredKontakte.length) {
      setSelectedRowIds([]);
    } else {
      setSelectedRowIds(filteredKontakte.map((k) => k.id));
    }
  };

  const toggleSelectRow = (id: string) => {
    setSelectedRowIds((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    );
  };

  const handleBulkDelete = async () => {
    if (selectedRowIds.length === 0) return;
    if (!confirm(`${selectedRowIds.length} Kontakte in den Papierkorb verschieben?`)) return;

    try {
      const nowIso = new Date().toISOString();
      const itemsToUndo = selectedRowIds.map(id => {
        const k = kontakte.find(c => c.id === id);
        return { id, name: k?.name || 'Kontakt' };
      });
      for (const id of selectedRowIds) {
        await pb.collection('Kontakte').update(id, { deleted_at: nowIso });
      }
      setKontakte((prev) => prev.filter((k) => !selectedRowIds.includes(k.id)));
      setSelectedRowIds([]);
      pushToUndoStack(itemsToUndo);
    } catch (err) {
      console.error('Bulk delete failed:', err);
    }
  };

  const handleBulkStatusChange = async (newStatus: string) => {
    if (selectedRowIds.length === 0 || !newStatus) return;
    const today = new Date().toISOString().split('T')[0];
    const isGesperrt = newStatus === 'Gesperrt_1Jahr';

    try {
      for (const id of selectedRowIds) {
        const updatePayload: any = { status: newStatus };
        if (isGesperrt) updatePayload.einladung_zurueckgezogen_am = today;
        await pb.collection('Kontakte').update(id, updatePayload);
      }
      setKontakte((prev) =>
        prev.map((k) =>
          selectedRowIds.includes(k.id)
            ? {
                ...k,
                status: newStatus as any,
                einladung_zurueckgezogen_am: isGesperrt ? today : k.einladung_zurueckgezogen_am
              }
            : k
        )
      );
      setSelectedRowIds([]);
      setBulkStatusTarget('');
    } catch (err) {
      console.error('Bulk status update failed:', err);
    }
  };

  // Drag & Drop Handlers for Kanban Cards
  const handleCardDragStart = (e: React.DragEvent, id: string) => {
    e.dataTransfer.setData('text/plain', id);
    setDraggedCardId(id);
  };

  const handleColumnDragOver = (e: React.DragEvent, colId: string) => {
    e.preventDefault();
    setDragOverColumnId(colId);
  };

  const handleColumnDragLeave = () => {
    setDragOverColumnId(null);
  };

  const handleColumnDrop = async (e: React.DragEvent, newStatus: string) => {
    e.preventDefault();
    setDragOverColumnId(null);

    const cardId = e.dataTransfer.getData('text/plain') || draggedCardId;
    if (!cardId) return;

    const target = kontakte.find(k => k.id === cardId);
    if (!target || target.status === newStatus) return;

    const today = new Date().toISOString().split('T')[0];
    const isGesperrt = newStatus === 'Gesperrt_1Jahr';

    const updatePayload: any = { status: newStatus };
    if (isGesperrt) {
      updatePayload.einladung_zurueckgezogen_am = today;
    }

    setKontakte(prev => prev.map(k => {
      if (k.id === cardId) {
        return {
          ...k,
          status: newStatus as any,
          einladung_zurueckgezogen_am: isGesperrt ? today : k.einladung_zurueckgezogen_am
        };
      }
      return k;
    }));

    try {
      await pb.collection('Kontakte').update(cardId, updatePayload);
    } catch (err) {
      console.error('Failed to update kontakt status on drop:', err);
      fetchKontakte();
    }
  };

  // Drag & Drop for Table Header Reordering
  const handleTableColDragStart = (e: React.DragEvent, key: string) => {
    setDraggedColKey(key);
    e.dataTransfer.setData('text/plain', key);
  };

  const handleTableColDrop = (e: React.DragEvent, targetKey: string) => {
    e.preventDefault();
    if (!draggedColKey || draggedColKey === targetKey) return;

    const fromIdx = columnOrder.indexOf(draggedColKey);
    const toIdx = columnOrder.indexOf(targetKey);
    if (fromIdx < 0 || toIdx < 0) return;

    const newOrder = [...columnOrder];
    newOrder.splice(fromIdx, 1);
    newOrder.splice(toIdx, 0, draggedColKey);
    saveColumnPreferences(newOrder, columnVisibility);
    setDraggedColKey(null);
  };

  const handleCardClick = (kontakt: KontaktRecord) => {
    setSelectedKontakt(kontakt);
    setDrawerOpen(true);
  };

  const handleCreateNew = () => {
    setSelectedKontakt(null);
    setDrawerOpen(true);
  };

  const handleSaveDrawer = (savedRecord: KontaktRecord) => {
    setSelectedKontakt(savedRecord);
    setKontakte((prev) => {
      const idx = prev.findIndex((item) => item.id === savedRecord.id);
      if (idx >= 0) {
        const copy = [...prev];
        copy[idx] = savedRecord;
        return copy;
      }
      return [savedRecord, ...prev];
    });
  };

  const handleDeleteDrawer = (id: string) => {
    const k = kontakte.find((item) => item.id === id);
    if (k) {
      pushToUndoStack([{ id, name: k.name || 'Kontakt' }]);
    }
    setKontakte((prev) => prev.filter((item) => item.id !== id));
  };

  const toggleStatusFilter = (statusId: string) => {
    setSelectedStatusFilters((prev) =>
      prev.includes(statusId)
        ? prev.filter((s) => s !== statusId)
        : [...prev, statusId]
    );
  };

  const resetAllFilters = () => {
    setSearchTerm('');
    setRatingFilter('ALL');
    setRegionFilter('');
    setSelectedStatusFilters([]);
    setDateFrom('');
    setDateTo('');
  };

  const isLight = themeMode === 'light';

  // Visible columns in user's ordering
  const activeVisibleColumns = columnOrder
    .map(key => DEFAULT_COLUMNS.find(c => c.key === key))
    .filter((col): col is ColumnConfig => !!col && !!columnVisibility[col.key]);

  // Helper cell renderer for all 15 PocketBase fields
  const renderTableCell = (colKey: string, k: KontaktRecord) => {
    switch (colKey) {
      case 'name':
        return (
          <div className="font-bold flex items-center gap-2 text-accent-main">
            <div className="w-6 h-6 rounded bg-accent-light border border-accent-light flex items-center justify-center font-mono text-[10px] text-accent-main font-bold shrink-0">
              {k.name ? k.name.substring(0, 2).toUpperCase() : '??'}
            </div>
            <span>{k.name}</span>
          </div>
        );
      case 'tags':
        if (!Array.isArray(k.tags) || k.tags.length === 0) {
          return <span className="text-slate-400 font-mono text-[10px]">-</span>;
        }
        const visibleTags = k.tags.slice(0, 2);
        const extraCount = k.tags.length - visibleTags.length;

        return (
          <div className="flex items-center gap-1 whitespace-nowrap overflow-hidden" title={k.tags.join(', ')}>
            {visibleTags.map((t) => (
              <span
                key={t}
                className="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-accent-light text-accent-main border border-accent-light shrink-0"
              >
                🏷️ {t}
              </span>
            ))}
            {extraCount > 0 && (
              <span className="px-1.5 py-0.5 rounded-full text-[10px] font-mono font-bold bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-300 dark:border-slate-700 shrink-0">
                +{extraCount}
              </span>
            )}
          </div>
        );
      case 'email':
        return k.email ? (
          <a
            href={`mailto:${k.email}`}
            onClick={(e) => e.stopPropagation()}
            className="text-blue-600 dark:text-blue-400 hover:underline font-mono text-[11px] font-semibold flex items-center gap-1"
            title="E-Mail in Outlook / Mail-App öffnen"
          >
            ✉️ {k.email}
          </a>
        ) : <span className="text-slate-400 font-mono text-[10px]">-</span>;
      case 'webseite': {
        const webVal = (k.webseite || (k as any).Webseite || '').trim();
        return webVal ? (
          <a
            href={webVal.startsWith('http') ? webVal : `https://${webVal}`}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="text-indigo-600 dark:text-indigo-400 hover:underline font-mono text-[11px] font-bold flex items-center gap-1"
            title="Webseite im neuen Tab öffnen"
          >
            🌐 {webVal.replace(/^https?:\/\//, '')}
          </a>
        ) : <span className="text-slate-400 font-mono text-[10px]">-</span>;
      }
      case 'adresse':
        return (
          <span className="font-mono text-[11px] truncate max-w-[160px] inline-block" title={k.adresse}>
            {k.adresse ? k.adresse.replace(/\n/g, ', ') : '-'}
          </span>
        );
      case 'telefon_1':
        return k.telefon_1 ? (
          <a href={`tel:${k.telefon_1}`} onClick={(e) => e.stopPropagation()} className="text-accent-main hover:underline font-mono text-[11px]">
            📞 {k.telefon_1}
          </a>
        ) : <span>-</span>;
      case 'telefon_2':
        return k.telefon_2 ? (
          <a href={`tel:${k.telefon_2}`} onClick={(e) => e.stopPropagation()} className="text-slate-500 hover:underline font-mono text-[11px]">
            📞 {k.telefon_2}
          </a>
        ) : <span>-</span>;
      case 'linkedin_url':
        return k.linkedin_url ? (
          <a href={k.linkedin_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className="text-indigo-600 hover:underline font-mono text-[11px] font-bold">
            🔗 LinkedIn
          </a>
        ) : <span>-</span>;
      case 'unternehmen':
        return <span>{k.unternehmen || '-'}</span>;
      case 'rolle':
        return <span>{k.rolle || '-'}</span>;
      case 'LinkedInheader':
        return (
          <span className="font-sans text-[11px] text-slate-700 dark:text-slate-300 max-w-[240px] truncate inline-block" title={k.LinkedInheader || ''}>
            {k.LinkedInheader || '-'}
          </span>
        );
      case 'Linkedin_info':
        return (
          <span className="font-sans text-[11px] text-slate-500 dark:text-slate-400 max-w-[200px] truncate inline-block" title={k.Linkedin_info || ''}>
            {k.Linkedin_info || '-'}
          </span>
        );
      case 'RollenVerteilungzuordnung':
        return (
          <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-slate-700">
            {k.RollenVerteilungzuordnung || '-'}
          </span>
        );
      case 'status':
        return (
          <span className={`px-2 py-0.5 rounded text-[10px] font-mono border font-semibold ${
            isLight ? 'bg-slate-100 border-slate-300 text-slate-800' : 'bg-slate-950 border-slate-700 text-slate-300'
          }`}>
            {k.status}
          </span>
        );
      case 'region':
        return <span>{k.region || '-'}</span>;
      case 'rating': {
        // KI-Tier aus Tags lesen — getrennt von den Sternen (Nutzerbewertung)
        const tierTag = (k.tags || []).find((t: string) =>
          ['s-tier','a-tier','b-tier','c-tier'].includes(t)
        );
        const tierLabel: Record<string, { label: string; dot: string }> = {
          's-tier': { label: 'S', dot: 'bg-amber-400' },
          'a-tier': { label: 'A', dot: 'bg-emerald-500' },
          'b-tier': { label: 'B', dot: 'bg-sky-500' },
          'c-tier': { label: 'C', dot: 'bg-slate-400' },
        };
        const ti = tierTag ? tierLabel[tierTag] : null;
        return (
          <span className="flex items-center gap-1.5">
            {ti && (
              <span className="flex items-center gap-0.5">
                <span className={`w-1.5 h-1.5 rounded-full inline-block shrink-0 ${ti.dot}`} />
                <span className="text-[10px] font-semibold text-slate-500 font-mono">{ti.label}</span>
              </span>
            )}
            {k.rating && Number(k.rating) > 0 ? (
              <span className="font-mono text-amber-500 tracking-tight text-xs select-none">
                {'⭐'.repeat(Math.min(Math.max(Number(k.rating), 1), 5))}
              </span>
            ) : !ti ? <span className="text-slate-400 font-mono text-[10px]">-</span> : null}
          </span>
        );
      }
      case 'naechster_schritt':
        return <span className="font-mono text-accent-main font-bold">{k.naechster_schritt || '-'}</span>;
      case 'vernetzt_am': {
        const d = k.vernetzt_am || k.created;
        return <span className="font-mono text-[11px] font-medium">{d ? new Date(d).toLocaleDateString('de-DE') : '-'}</span>;
      }
      case 'einladung_zurueckgezogen_am':
        return (
          <span className="font-mono text-[11px]">
            {k.einladung_zurueckgezogen_am ? new Date(k.einladung_zurueckgezogen_am).toLocaleDateString('de-DE') : '-'}
          </span>
        );
      case 'kommentar':
        return <span className="font-mono text-[10px] truncate max-w-[150px] inline-block">{k.kommentar || '-'}</span>;
      case 'nachrichtenverlauf':
        return (
          <button
            onClick={(e) => {
              e.stopPropagation();
              setSelectedNachrichtenKontakt(k);
              setNachrichtenModalOpen(true);
            }}
            className="px-2.5 py-1 rounded bg-accent-light border border-accent-light text-accent-main hover:bg-accent-main hover:text-white font-mono text-[11px] font-bold transition flex items-center gap-1.5 cursor-pointer"
          >
            <MessageSquare className="w-3.5 h-3.5" />
            <span>💬 Verlauf</span>
          </button>
        );
      case 'profilbild':
        const imgUrl = getProfilbildUrl(k);
        return imgUrl ? (
          <div className="w-7 h-7 rounded-full overflow-hidden border border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 flex items-center justify-center shrink-0">
            <img src={imgUrl} alt={k.name} className="w-full h-full object-fill" />
          </div>
        ) : (
          <span className="text-slate-400 font-mono text-[10px]">-</span>
        );
      case 'id':
        return <span className="font-mono text-[10px] text-slate-400 bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded">{k.id}</span>;
      case 'created': {
        const d = k.created || k.vernetzt_am;
        return <span className="font-mono text-[11px] font-medium">{d ? new Date(d).toLocaleDateString('de-DE') : '-'}</span>;
      }
      case 'updated':
        return <span className="font-mono text-[11px] font-medium">{k.updated ? new Date(k.updated).toLocaleDateString('de-DE') : '-'}</span>;
      default:
        return <span>-</span>;
    }
  };

  if (!hasMounted) {
    return null;
  }

  return (
    <div
      data-theme={themeMode}
      className={`flex h-screen font-sans antialiased overflow-hidden transition-colors duration-200 ${themeMode} ${
        isLight ? 'bg-slate-100 text-slate-900 selection:bg-emerald-500/20 selection:text-emerald-900' : 'bg-slate-950 text-slate-100 selection:bg-emerald-500/30 selection:text-emerald-200'
      }`}
    >

      {/* AUTH MODAL */}
      <AuthModal
        isOpen={isAuthModalOpen}
        onLoginSuccess={() => {
          setIsAuthModalOpen(false);
          fetchKontakte();
        }}
        themeMode={themeMode}
      />

      {/* PROFILE MODAL */}
      <ProfileModal
        isOpen={isProfileModalOpen}
        onClose={() => setIsProfileModalOpen(false)}
        user={currentUser}
        onUpdateSuccess={() => setCurrentUser(pb.authStore.model)}
        themeMode={themeMode}
      />

      {/* SETTINGS MODAL */}
      <SettingsModal
        isOpen={isSettingsModalOpen}
        onClose={() => setIsSettingsModalOpen(false)}
        themeMode={themeMode}
        onThemeChange={setThemeMode}
        activeView={activeTab}
        onViewChange={setActiveTab}
        accentColor={accentColor}
        onAccentColorChange={handleAccentColorChange}
        primaryAccentHex={primaryAccentHex}
        onPrimaryAccentHexChange={handlePrimaryAccentHexChange}
        secondaryAccentHex={secondaryAccentHex}
        onSecondaryAccentHexChange={handleSecondaryAccentHexChange}
        customLogoUrl={customLogoUrl}
        onCustomLogoChange={handleCustomLogoChange}
        designEditorOpen={isDesignEditorOpen}
        onDesignEditorToggle={setIsDesignEditorOpen}
        onSaveThemeSettings={handleSaveThemeSettings}
        onContactRestored={fetchKontakte}
      />

      {/* INTERNET WATCHDOG RADAR MODAL (KOGNITION SÄULE 4) */}
      <WatchdogModal
        isOpen={isWatchdogModalOpen}
        onClose={() => setIsWatchdogModalOpen(false)}
        themeMode={themeMode}
      />

      {/* POCKETBASE APPLICATION SETTINGS MODAL (Bild 1) */}
      <PbSettingsModal
        isOpen={isPbSettingsModalOpen}
        onClose={() => setIsPbSettingsModalOpen(false)}
        defaultSection={pbSettingsSection}
        themeMode={themeMode}
      />

      {/* EDIT COLLECTION MODAL (Bild 2) */}
      <EditCollectionModal
        isOpen={isEditCollectionModalOpen}
        onClose={() => setIsEditCollectionModalOpen(false)}
        themeMode={themeMode}
      />

      {/* CSV IMPORT MODAL */}
      <CsvImportModal
        isOpen={isCsvModalOpen}
        onClose={() => setIsCsvModalOpen(false)}
        onImportComplete={fetchKontakte}
        themeMode={themeMode}
      />

      {/* API PREVIEW MODAL */}
      <ApiPreviewModal
        isOpen={isApiPreviewModalOpen}
        onClose={() => setIsApiPreviewModalOpen(false)}
        themeMode={themeMode}
      />

      {/* NACHRICHTENVERLAUF MODAL */}
      <NachrichtenverlaufModal
        isOpen={nachrichtenModalOpen}
        onClose={() => setNachrichtenModalOpen(false)}
        kontakt={selectedNachrichtenKontakt}
        onUpdate={(updated) => {
          setSelectedNachrichtenKontakt(updated);
          setKontakte((prev) => prev.map((k) => (k.id === updated.id ? updated : k)));
        }}
        themeMode={themeMode}
      />



      {/* LEFT SIDEBAR */}
      <aside className={`w-64 border-r flex flex-col justify-between shrink-0 transition-colors sidebar-root ${
        isLight ? 'bg-white border-slate-200 shadow-sm' : 'bg-slate-900/60 border-slate-800/80 backdrop-blur-md'
      }`}>
        <div>
          {/* Logo & Header (Ganze Spaltenbreite) */}
          <div className={`h-16 w-full border-b flex items-center justify-center overflow-hidden shrink-0 transition-colors header-root ${
            isLight ? 'border-slate-200 bg-white' : 'border-slate-800/80 bg-slate-900/80'
          }`}>
            <button
              type="button"
              onClick={() => setSelectedNav('mission')}
              className="w-full h-full block cursor-pointer"
              title="Mission Control"
            >
              <img
                src={customLogoUrl || '/archon-logo.png'}
                alt="Archon CRM"
                className="w-full h-full object-cover transition-all"
              />
            </button>
          </div>

          {/* Navigation Items */}
          <nav className="p-3 space-y-1">
            <div className="pt-2 border-t border-slate-800/40 text-[10px] font-mono text-slate-500 uppercase px-2">
              DATENBANK & CRM
            </div>
            <button
              onClick={() => setSelectedNav('mission')}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-semibold transition cursor-pointer sidebar-item ${
                selectedNav === 'mission'
                  ? 'sidebar-item-active ' + (isLight
                    ? 'bg-accent-soft text-accent-main border border-accent-soft shadow-xs font-bold'
                    : 'bg-accent-light border border-accent-light text-accent-main font-bold')
                  : isLight
                  ? 'text-slate-600 hover:text-slate-900 hover:bg-slate-100 border border-transparent'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 border border-transparent'
              }`}
            >
              <Target className="w-4 h-4" />
              <span>Mission Control</span>
            </button>

            <button
              onClick={() => { setSelectedNav('pipeline'); setActiveTab('pipeline'); }}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-semibold transition cursor-pointer sidebar-item ${
                selectedNav === 'pipeline'
                  ? 'sidebar-item-active ' + (isLight
                    ? 'bg-accent-soft text-accent-main border border-accent-soft shadow-xs font-bold'
                    : 'bg-accent-light border border-accent-light text-accent-main font-bold')
                  : isLight
                  ? 'text-slate-600 hover:text-slate-900 hover:bg-slate-100 border border-transparent'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 border border-transparent'
              }`}
            >
              <BarChart3 className="w-4 h-4" />
              <span>Pipeline</span>
              <span className={`ml-auto font-mono text-[10px] px-1.5 py-0.5 rounded font-bold ${
                isLight ? 'bg-slate-200 text-slate-700' : 'bg-slate-800 text-slate-300'
              }`}>
                {kontakte.length}
              </span>
            </button>

            <button
              onClick={() => { setSelectedNav('kontakte'); setActiveTab('tabelle'); }}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-semibold transition cursor-pointer sidebar-item ${
                selectedNav === 'kontakte'
                  ? 'sidebar-item-active ' + (isLight
                    ? 'bg-accent-soft text-accent-main border border-accent-soft shadow-xs font-bold'
                    : 'bg-accent-light border border-accent-light text-accent-main font-bold')
                  : isLight
                  ? 'text-slate-600 hover:text-slate-900 hover:bg-slate-100 border border-transparent'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 border border-transparent'
              }`}
            >
              <Users className="w-4 h-4" />
              <span>Kontakte</span>
            </button>

            <button
              onClick={() => setSelectedNav('kalender')}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-semibold transition cursor-pointer sidebar-item ${
                selectedNav === 'kalender'
                  ? 'sidebar-item-active ' + (isLight
                    ? 'bg-accent-soft text-accent-main border border-accent-soft shadow-xs font-bold'
                    : 'bg-accent-light border border-accent-light text-accent-main font-bold')
                  : isLight
                  ? 'text-slate-600 hover:text-slate-900 hover:bg-slate-100 border border-transparent'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 border border-transparent'
              }`}
            >
              <Calendar className="w-4 h-4" />
              <span>Kalender</span>
            </button>

            <button
              onClick={() => setSelectedNav('nachrichten')}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-semibold transition cursor-pointer sidebar-item ${
                selectedNav === 'nachrichten'
                  ? 'sidebar-item-active ' + (isLight
                    ? 'bg-accent-soft text-accent-main border border-accent-soft shadow-xs font-bold'
                    : 'bg-accent-light border border-accent-light text-accent-main font-bold')
                  : isLight
                  ? 'text-slate-600 hover:text-slate-900 hover:bg-slate-100 border border-transparent'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 border border-transparent'
              }`}
            >
              <MessageSquare className="w-4 h-4" />
              <span>Alle Nachrichten</span>
              <span className={`ml-auto font-mono text-[10px] px-1.5 py-0.5 rounded font-bold ${
                isLight ? 'bg-slate-200 text-slate-700' : 'bg-slate-800 text-slate-300'
              }`}>
                {nachrichtenCount}
              </span>
            </button>

            <button
              onClick={() => setSelectedNav('mediaboard')}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-semibold transition cursor-pointer sidebar-item ${
                selectedNav === 'mediaboard'
                  ? 'sidebar-item-active ' + (isLight
                    ? 'bg-accent-soft text-accent-main border border-accent-soft shadow-xs font-bold'
                    : 'bg-accent-light border border-accent-light text-accent-main font-bold')
                  : isLight
                  ? 'text-slate-600 hover:text-slate-900 hover:bg-slate-100 border border-transparent'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 border border-transparent'
              }`}
            >
              <ImageIcon className="w-4 h-4" />
              <span>Media Board</span>
            </button>

            <button
              onClick={() => setSelectedNav('content-studio')}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-semibold transition cursor-pointer sidebar-item ${
                selectedNav === 'content-studio'
                  ? 'sidebar-item-active ' + (isLight
                    ? 'bg-accent-soft text-accent-main border border-accent-soft shadow-xs font-bold'
                    : 'bg-accent-light border border-accent-light text-accent-main font-bold')
                  : isLight
                  ? 'text-slate-600 hover:text-slate-900 hover:bg-slate-100 border border-transparent'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 border border-transparent'
              }`}
            >
              <Clapperboard className="w-4 h-4" />
              <span>Content Studio</span>
            </button>

          </nav>
        </div>

        {/* Sidebar Footer */}
        <div className={`p-3 border-t text-[11px] font-mono space-y-2 ${
          isLight ? 'border-slate-200 bg-slate-50 text-slate-600' : 'border-slate-800/80 bg-slate-950/40 text-slate-400'
        }`}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 font-bold text-accent-main">
              <Database className="w-3.5 h-3.5 shrink-0" />
              <span>Port 8090 / kontakte</span>
            </div>
            <button
              type="button"
              onClick={() => window.dispatchEvent(new CustomEvent('archon_toggle_css_studio'))}
              className="p-1 rounded-md hover:bg-indigo-500/20 text-slate-400 hover:text-indigo-400 transition flex items-center gap-1 text-[10px] font-bold cursor-pointer"
              title="CSS Live Studio öffnen (Alt + S)"
            >
              <Palette className="w-3.5 h-3.5 text-indigo-400" />
              <span className="text-indigo-400 font-mono">CSS</span>
            </button>
          </div>
          <div className="flex items-center justify-between text-[10px] font-mono text-accent-main font-semibold">
            <div className="flex items-center gap-1.5 pl-5.5">
              <span className="w-1.5 h-1.5 rounded-full bg-accent-main animate-pulse shrink-0" />
              <span>PocketBase SDK</span>
            </div>
            <span className="text-[9px] text-emerald-400">
              ● aktiv
            </span>
          </div>
        </div>
      </aside>

      {/* RIGHT MAIN CONTENT AREA */}
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
        
        {/* HEADER TOP BAR */}
        <header className={`h-16 border-b px-6 flex items-center justify-between shrink-0 transition-colors header-root ${
          isLight ? 'bg-white border-slate-200 shadow-xs' : 'bg-slate-900/80 border-slate-800/80 backdrop-blur-md'
        }`}>
          {/* Top-Left Title: "Kontakte" (doppelt so groß) */}
            <h2 className={`font-black text-2xl tracking-tight font-mono ${
              isLight ? 'text-slate-900' : 'text-slate-100'
            }`}>
              {selectedNav === 'orchestrator'
                ? 'Teambildung (Flow Orchestrator)'
                : selectedNav === 'agent-control'
                ? 'Agenten-Steuerung (WebUI)'
                : selectedNav === 'pipeline'
                ? 'Pipeline'
                : selectedNav === 'kontakte'
                ? 'Kontakte'
                : selectedNav === 'kalender'
                ? 'Kalender'
                : selectedNav === 'nachrichten'
                ? 'Alle Nachrichten'
                : selectedNav === 'mission'
                ? 'Mission Control'
                : selectedNav === 'mediaboard'
                ? 'Media Board'
                : selectedNav === 'content-studio'
                ? 'Content Studio'
                : 'PocketBase CRM'}
            </h2>

          {/* Action Buttons & Top Right Settings Cog + User Menu */}
          <div className="flex items-center gap-3">
            
            {/* MISSION CONTROL CONTACT SEARCH – only visible on Mission Control */}
            {selectedNav === 'mission' && (
              <div className="relative">
                <Search className={`absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 pointer-events-none ${
                  isLight ? 'text-slate-400' : 'text-slate-500'
                }`} />
                <input
                  ref={missionSearchRef}
                  type="text"
                  value={missionSearch}
                  onChange={e => setMissionSearch(e.target.value)}
                  onKeyDown={handleMissionSearchKey}
                  onFocus={() => setMissionSearchFocused(true)}
                  onBlur={() => setTimeout(() => setMissionSearchFocused(false), 150)}
                  placeholder="Kontakt suchen…"
                  className={`w-44 pl-8 pr-3 py-1.5 rounded-lg border text-xs outline-none transition
                    ${
                      isLight
                        ? 'bg-white border-slate-200 text-slate-900 placeholder-slate-400 focus:border-accent-main focus:ring-1 focus:ring-accent-main/20'
                        : 'bg-slate-800 border-slate-700 text-slate-100 placeholder-slate-500 focus:border-accent-main focus:ring-1 focus:ring-accent-main/20'
                    }`}
                />
                {missionSearchFocused && missionResults.length > 0 && (
                  <div className={`absolute top-full right-0 mt-1 w-72 rounded-xl border shadow-2xl z-50 overflow-hidden
                    ${isLight ? 'bg-white border-slate-200' : 'bg-slate-900 border-slate-700'}`}>
                    {missionResults.map((k, idx) => (
                      <button
                        key={k.id}
                        type="button"
                        onMouseDown={() => openMissionContact(k)}
                        onMouseEnter={() => setMissionHighlight(idx)}
                        className={`w-full flex items-center gap-2.5 px-3 py-2 text-left transition cursor-pointer
                          ${
                            idx === missionHighlight
                              ? isLight ? 'bg-slate-100' : 'bg-slate-800'
                              : isLight ? 'hover:bg-slate-50' : 'hover:bg-slate-800/60'
                          }`}
                      >
                        <div className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 text-[10px] font-bold
                          ${isLight ? 'bg-slate-200 text-slate-600' : 'bg-slate-700 text-slate-300'}`}>
                          {(k.name || '?')[0].toUpperCase()}
                        </div>
                        <div className="min-w-0">
                          <div className={`text-xs font-semibold truncate ${isLight ? 'text-slate-900' : 'text-slate-100'}`}>{k.name}</div>
                          <div className={`text-[10px] truncate ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>
                            {[k.rolle, k.unternehmen].filter(Boolean).join(' · ')}
                          </div>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* INTERNET WATCHDOG / RADAR BUTTON (KOGNITION SÄULE 4) */}
            <button
              onClick={() => setIsWatchdogModalOpen(true)}
              className={`px-3 py-1.5 rounded-lg border text-xs font-semibold flex items-center gap-1.5 transition cursor-pointer ${
                isLight ? 'bg-white border-slate-200 text-slate-700 hover:bg-slate-50' : 'bg-slate-850 border-slate-700 text-slate-200 hover:bg-slate-800'
              }`}
              title="Internet-Watchdog & Web-Radar (Kognition Säule 4)"
            >
              <Radar className="w-3.5 h-3.5 text-cyan-400 animate-pulse" />
              <span>📡 Radar</span>
            </button>

            {/* DESIGN & EINSTELLUNGEN BUTTON */}
            <button
              onClick={() => setIsSettingsModalOpen(true)}
              className={`px-3 py-1.5 rounded-lg border text-xs font-semibold flex items-center gap-1.5 transition cursor-pointer ${
                isLight ? 'bg-white border-slate-200 text-slate-700 hover:bg-slate-50' : 'bg-slate-850 border-slate-700 text-slate-200 hover:bg-slate-800'
              }`}
              title="Design, Farben & Kalender Einstellungen"
            >
              <Palette className="w-3.5 h-3.5 text-accent-main" />
              <span>Design & Einstellungen</span>
            </button>

            {/* NEW RECORD / KONTAKT BUTTON */}
            <button
              onClick={handleCreateNew}
              className="px-3.5 py-1.5 rounded-lg bg-accent-main hover:bg-accent-main-hover text-white font-bold text-xs transition shadow-md flex items-center gap-1.5 cursor-pointer"
            >
              <Plus className="w-4 h-4" />
              <span>Neuer Kontakt</span>
            </button>

            {/* USER PROFILE DROPDOWN */}
            <UserDropdown
              user={currentUser}
              onLogout={() => {
                pb.authStore.clear();
                setCurrentUser(null);
                setIsAuthModalOpen(true);
              }}
              onOpenProfile={() => setIsProfileModalOpen(true)}
              onOpenSettings={() => setIsSettingsModalOpen(true)}
              onOpenLogs={() => {
                setPbSettingsSection('Logs');
                setIsPbSettingsModalOpen(true);
              }}
              onOpenApiPreview={() => setIsApiPreviewModalOpen(true)}
              onOpenCsvImport={() => setIsCsvModalOpen(true)}
              themeMode={themeMode}
            />

            {/* TOP RIGHT SETTINGS COG GEAR BUTTON (Bild 1 & 3 Style) */}
            <button
              onClick={() => {
                setPbSettingsSection('Application');
                setIsPbSettingsModalOpen(true);
              }}
              className={`p-2 rounded-lg border text-xs font-semibold transition ${
                isLight ? 'bg-slate-50 border-slate-300 text-slate-700 hover:bg-slate-100' : 'bg-slate-950 border-slate-800 text-slate-200 hover:bg-slate-900'
              }`}
              title="PocketBase Application Settings (System-Einstellungen)"
            >
              <Cog className="w-4 h-4 text-emerald-600 animate-spin-slow" />
            </button>
          </div>
        </header>

        {/* SECONDARY TOOLBAR: FILTER BAR, BULK ACTIONS & TREFFER BADGE */}
        {(selectedNav === 'pipeline' || selectedNav === 'kontakte') && (
          <div className={`px-6 py-2.5 border-b flex flex-wrap items-center justify-between gap-3 text-xs shrink-0 transition-colors ${
            isLight ? 'bg-white border-slate-200' : 'bg-slate-900/40 border-slate-800'
          }`}>
          
          {/* SEARCH & FILTERS */}
          <div className="flex flex-wrap items-center gap-2">
            
            {/* RECORD COUNT TREFFER BADGE (Links vom Suchfeld) */}
            <span className={`text-xs font-mono px-3 py-1 rounded-lg border font-bold ${
              isLight ? 'bg-slate-100 text-slate-700 border-slate-300' : 'bg-slate-800 text-slate-300 border-slate-700'
            }`}>
              {filteredKontakte.length} Treffer
            </span>

            {/* Search Input */}
            <div className="relative flex items-center">
              <Search className="w-3.5 h-3.5 absolute left-2.5 text-slate-400 pointer-events-none" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Search term or filter..."
                className={`pl-8 pr-7 py-1 w-64 border rounded-lg text-xs font-mono transition ${
                  isLight
                    ? 'bg-slate-50 border-slate-300 text-slate-900 placeholder-slate-400 focus:border-emerald-500'
                    : 'bg-slate-950 border-slate-800 text-slate-100 placeholder-slate-500 focus:border-emerald-500/60'
                }`}
              />
              {searchTerm && (
                <button
                  type="button"
                  onClick={() => setSearchTerm('')}
                  title="Suche leeren"
                  className="absolute right-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition p-0.5 rounded-md cursor-pointer flex items-center justify-center"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>

            {/* Multi-Select Status Dropdown */}
            <div className="relative">
              <button
                onClick={() => setStatusDropdownOpen(!statusDropdownOpen)}
                className={`px-2.5 py-1 rounded-lg border text-xs font-semibold flex items-center gap-1.5 transition ${
                  selectedStatusFilters.length > 0
                    ? 'bg-accent-light border-accent-light text-accent-main font-bold'
                    : isLight ? 'bg-slate-50 border-slate-300 text-slate-700' : 'bg-slate-950 border-slate-800 text-slate-300'
                }`}
              >
                <Filter className="w-3.5 h-3.5 text-accent-main" />
                <span>
                  Status {selectedStatusFilters.length > 0 ? `(${selectedStatusFilters.length})` : ''}
                </span>
              </button>

              {statusDropdownOpen && (
                <div className={`absolute left-0 top-9 z-40 w-56 rounded-xl border p-3 shadow-2xl space-y-2 animate-in fade-in zoom-in-95 duration-150 ${
                  isLight ? 'bg-white border-slate-200 text-slate-900' : 'bg-slate-900 border-slate-800 text-slate-100'
                }`}>
                  <div className="flex items-center justify-between pb-1 border-b border-slate-200 dark:border-slate-800">
                    <span className="font-bold text-[11px] uppercase tracking-wider text-slate-400">Status wählen</span>
                    {selectedStatusFilters.length > 0 && (
                      <button
                        onClick={() => setSelectedStatusFilters(DEFAULT_STATUS_FILTERS)}
                        className="text-[10px] text-accent-main hover:underline font-bold"
                      >
                        Standard
                      </button>
                    )}
                  </div>
                  <div className="space-y-1 max-h-48 overflow-y-auto">
                    {STATUS_COLUMNS.map((col) => {
                      const isChecked = selectedStatusFilters.includes(col.id);
                      return (
                        <label
                          key={col.id}
                          onClick={() => toggleStatusFilter(col.id)}
                          className={`flex items-center gap-2 p-1.5 rounded cursor-pointer text-xs select-none transition ${
                            isLight
                              ? 'hover:bg-accent-soft hover:text-accent-main text-slate-800'
                              : 'hover:bg-accent-light hover:text-accent-main text-slate-200'
                          }`}
                        >
                          {isChecked ? (
                            <CheckSquare className="w-4 h-4 text-accent-main shrink-0" />
                          ) : (
                            <Square className="w-4 h-4 text-slate-400 shrink-0" />
                          )}
                          <span className={isChecked ? 'font-semibold text-accent-main' : ''}>{col.title}</span>
                        </label>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>

            {/* Multi-Select Tags Dropdown */}
            <div className="relative">
              <button
                onClick={() => setTagDropdownOpen(!tagDropdownOpen)}
                className={`px-2.5 py-1 rounded-lg border text-xs font-semibold flex items-center gap-1.5 transition ${
                  selectedTagFilters.length > 0
                    ? 'bg-accent-light border-accent-light text-accent-main font-bold'
                    : isLight ? 'bg-slate-50 border-slate-300 text-slate-700' : 'bg-slate-950 border-slate-800 text-slate-300'
                }`}
              >
                <Tag className="w-3.5 h-3.5 text-accent-main" />
                <span>
                  Tags {selectedTagFilters.length > 0 ? `(${selectedTagFilters.length})` : ''}
                </span>
              </button>

              {tagDropdownOpen && (
                <div className={`absolute left-0 top-9 z-40 w-60 rounded-xl border p-3 shadow-2xl space-y-2 animate-in fade-in zoom-in-95 duration-150 ${
                  isLight ? 'bg-white border-slate-200 text-slate-900' : 'bg-slate-900 border-slate-800 text-slate-100'
                }`}>
                  <div className="flex items-center justify-between pb-1 border-b border-slate-200 dark:border-slate-800">
                    <span className="font-bold text-[11px] uppercase tracking-wider text-slate-400">Filter nach Tags</span>
                    {selectedTagFilters.length > 0 && (
                      <button
                        onClick={() => setSelectedTagFilters([])}
                        className="text-[10px] text-rose-500 hover:underline font-bold"
                      >
                        Zurücksetzen
                      </button>
                    )}
                  </div>
                  <div className="space-y-1 max-h-48 overflow-y-auto">
                    {allUniqueTags.length === 0 ? (
                      <div className="text-[11px] text-slate-400 italic p-2 text-center">Keine Tags in der DB vorhanden</div>
                    ) : (
                      allUniqueTags.map((tag) => {
                        const isChecked = selectedTagFilters.includes(tag);
                        return (
                          <label
                            key={tag}
                            onClick={() => {
                              setSelectedTagFilters(prev =>
                                prev.includes(tag) ? prev.filter(t => t !== tag) : [...prev, tag]
                              );
                            }}
                            className="flex items-center gap-2 p-1.5 rounded hover:bg-slate-100 dark:hover:bg-slate-800 cursor-pointer text-xs select-none"
                          >
                            {isChecked ? (
                              <CheckSquare className="w-4 h-4 text-accent-main shrink-0" />
                            ) : (
                              <Square className="w-4 h-4 text-slate-400 shrink-0" />
                            )}
                            <span className="font-mono text-xs font-bold text-accent-main">🏷️ {tag}</span>
                          </label>
                        );
                      })
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Region Filter */}
            <select
              value={regionFilter}
              onChange={(e) => setRegionFilter(e.target.value)}
              className={`px-2.5 py-1 border rounded-lg text-xs font-semibold focus:outline-none transition ${
                isLight ? 'bg-slate-50 border-slate-300 text-slate-800' : 'bg-slate-950 border-slate-800 text-slate-200'
              }`}
            >
              <option value="">Alle Regionen</option>
              {availableRegions.map(reg => (
                <option key={reg} value={reg}>{reg}</option>
              ))}
            </select>

            {/* Date Range Inputs */}
            <div className="flex items-center gap-1 font-mono text-[11px]">
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className={`px-2 py-0.5 border rounded text-xs ${
                  isLight ? 'bg-slate-50 border-slate-300' : 'bg-slate-950 border-slate-800'
                }`}
                title="Datum ab"
              />
              <span>bis</span>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className={`px-2 py-0.5 border rounded text-xs ${
                  isLight ? 'bg-slate-50 border-slate-300' : 'bg-slate-950 border-slate-800'
                }`}
                title="Datum bis"
              />
            </div>

            {/* Reset All Filters Button */}
            {(searchTerm || ratingFilter !== 'ALL' || regionFilter || selectedStatusFilters.length > 0 || dateFrom || dateTo) && (
              <button
                onClick={resetAllFilters}
                className="p-1 rounded-lg hover:bg-rose-500/10 text-rose-500 transition"
                title="Alle Filter zurücksetzen"
              >
                <FilterX className="w-4 h-4" />
              </button>
            )}
          </div>

          {/* RIGHT SIDE OF TOOLBAR: BULK ACTIONS, COLUMN VISIBILITY & ZAHNRAD + REFRESH */}
          <div className="flex items-center gap-2">

            {/* BULK SELECTION BAR */}
            {selectedRowIds.length > 0 && (
              <div className="flex items-center gap-2 px-3 py-1 rounded-lg bg-accent-light border border-accent-light text-accent-main font-mono font-bold animate-in fade-in duration-150">
                <span>{selectedRowIds.length} ausgewählt</span>
                <select
                  value={bulkStatusTarget}
                  onChange={(e) => {
                    setBulkStatusTarget(e.target.value);
                    if (e.target.value) handleBulkStatusChange(e.target.value);
                  }}
                  className="px-2 py-0.5 rounded text-[11px] bg-accent-main text-white font-sans font-bold border-none outline-none cursor-pointer"
                >
                  <option value="">Status ändern...</option>
                  {STATUS_COLUMNS.map((s) => (
                    <option key={s.id} value={s.id}>{s.title}</option>
                  ))}
                </select>

                <button
                  onClick={handleBulkDelete}
                  className="p-1 rounded text-rose-600 hover:bg-rose-500/20 transition"
                  title="Ausgewählte löschen"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            )}

            {/* Column Visibility Dropdown */}
            <div className="relative">
              <button
                onClick={() => setColumnDropdownOpen(!columnDropdownOpen)}
                className={`p-1.5 rounded-lg border text-xs font-semibold transition cursor-pointer ${
                  isLight ? 'bg-slate-50 border-slate-300 text-slate-700 hover:bg-slate-100' : 'bg-slate-950 border-slate-800 text-slate-300 hover:bg-slate-900'
                }`}
                title="Spalten anpassen"
              >
                <Columns className="w-4 h-4 text-accent-main" />
              </button>

              {columnDropdownOpen && (
                <div className={`absolute right-0 top-9 z-40 w-80 rounded-xl border p-4 shadow-2xl space-y-4 animate-in fade-in zoom-in-95 duration-150 ${
                  isLight ? 'bg-white border-slate-200 text-slate-900' : 'bg-slate-900 border-slate-800 text-slate-100'
                }`}>
                  <div className="flex items-center justify-between pb-2 border-b border-slate-200 dark:border-slate-800">
                    <h3 className="text-xs font-bold uppercase tracking-wider flex items-center gap-1.5">
                      <Columns className="w-4 h-4 text-accent-main" />
                      <span>Custom Views & Spalten ({DEFAULT_COLUMNS.length} Felder)</span>
                    </h3>
                    <button
                      onClick={resetColumnPreferences}
                      className="text-[10px] font-mono text-slate-500 hover:text-accent-main flex items-center gap-1 transition"
                    >
                      <RotateCcw className="w-3 h-3" />
                      <span>Reset</span>
                    </button>
                  </div>

                  <div className="max-h-72 overflow-y-auto space-y-1.5 pr-1 text-xs">
                    {columnOrder.map((key) => {
                      const col = DEFAULT_COLUMNS.find((c) => c.key === key);
                      if (!col) return null;
                      const isVis = !!columnVisibility[key];

                      return (
                        <div
                          key={key}
                          className={`flex items-center justify-between p-2 rounded border transition ${
                            isLight
                              ? isVis ? 'bg-slate-50 border-slate-200' : 'bg-slate-100/50 border-slate-200/50 text-slate-400'
                              : isVis ? 'bg-slate-950/60 border-slate-800' : 'bg-slate-950/20 border-slate-900 text-slate-500'
                          }`}
                        >
                          <label className="flex items-center gap-2 cursor-pointer flex-1 select-none">
                            <input
                              type="checkbox"
                              checked={isVis}
                              onChange={() => toggleColumnVisibility(key)}
                              className="rounded accent-color-input cursor-pointer"
                            />
                            <span className="font-mono text-[11px] font-bold text-slate-400 border px-1 rounded">
                              {col.typeIcon}
                            </span>
                            <span className={`font-semibold ${col.isTechnical ? 'font-mono text-[11px]' : ''}`}>
                              {col.label}
                            </span>
                          </label>

                          <div className="flex items-center gap-1 ml-2">
                            <button
                              onClick={() => moveColumn(key, 'left')}
                              className="p-1 rounded hover:bg-slate-200 dark:hover:bg-slate-800 text-slate-500 transition"
                            >
                              <ArrowLeft className="w-3 h-3" />
                            </button>
                            <button
                              onClick={() => moveColumn(key, 'right')}
                              className="p-1 rounded hover:bg-slate-200 dark:hover:bg-slate-800 text-slate-500 transition"
                            >
                              <ArrowRight className="w-3 h-3" />
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>

            {/* ZAHNRAD (⚙️ Edit Collection Modal) RECHTS NEBEN SPALTENZEICHEN */}
            <button
              onClick={() => setIsEditCollectionModalOpen(true)}
              className={`p-1.5 rounded-lg border transition cursor-pointer ${
                isLight ? 'bg-slate-50 border-slate-300 text-slate-600 hover:bg-slate-100' : 'bg-slate-950 border-slate-800 text-slate-300 hover:bg-slate-900'
              }`}
              title="Edit kontakte collection (Schema & API Rules)"
            >
              <Settings className="w-4 h-4 text-slate-500 hover:text-accent-main" />
            </button>

            {/* AKTUALISIEREN-BUTTON (🔄 Neu laden) RECHTS NEBEN SPALTENZEICHEN */}
            <button
              onClick={fetchKontakte}
              className={`p-1.5 rounded-lg border transition cursor-pointer ${
                isLight ? 'bg-slate-50 border-slate-300 text-slate-600 hover:bg-slate-100' : 'bg-slate-950 border-slate-800 text-slate-300 hover:bg-slate-900'
              }`}
              title="Kontakte neu laden"
            >
              <RefreshCw className="w-4 h-4 text-slate-500 hover:text-accent-main" />
            </button>
          </div>
        </div>
        )}

        {/* WORKSPACE VIEW CONTENT */}
        <div className={`flex-1 overflow-auto p-6 transition-colors ${
          isLight ? 'bg-slate-100/70' : 'bg-slate-950/90'
        }`}>

          {/* ORCHESTRATOR FLOW GRAPH VIEW */}
          {selectedNav === 'orchestrator' ? (
            <div className="h-full rounded-2xl overflow-hidden border border-slate-800 shadow-2xl">
              <TeambildungFlowCanvas
                agents={[
                  { id: 'hermes', name: 'Hermes Agent v0.20', role: 'Strategie, Memory & System-Steuerung' },
                  { id: 'gpt-researcher', name: 'GPT Researcher', role: 'Tiefen-Recherche & Web Scraping' },
                  { id: 'openhands', name: 'OpenHands Coder', role: 'Entwicklung & Refactoring' },
                  { id: 'pocketbase-mcp', name: 'PocketBase CRM Agent', role: 'CRM Kontakte & Verläufe' }
                ]}
                onSelectAgentView={(agentId) => {
                  setActiveAgentId(agentId);
                  setSelectedNav('agent-control');
                }}
              />
            </div>
          ) : selectedNav === 'agent-control' ? (
            /* UNIFIED SINGLE-AGENT CONTROL PANEL (WebUI Style) */
            <div className="h-full rounded-2xl overflow-hidden border border-slate-800 shadow-2xl">
              <UnifiedAgentControlPanel initialAgentId={activeAgentId} />
            </div>
          ) : loading && selectedNav !== 'kalender' ? (
            <div className="h-full flex flex-col items-center justify-center text-slate-500 gap-3">
              <RefreshCw className="w-6 h-6 animate-spin text-emerald-600" />
              <p className="text-xs font-mono font-semibold">Synchronisiere PocketBase CRM Daten...</p>
            </div>
          ) : selectedNav === 'kalender' ? (
            /* KALENDER VIEW */
            <CalendarView themeMode={themeMode} />
          ) : selectedNav === 'nachrichten' ? (
            /* ALLE NACHRICHTEN - CHRONOLOGISCHE ÜBERSICHT */
            <AlleNachrichtenView
              themeMode={themeMode}
              kontakte={kontakte}
              loading={loading}
              onOpenKontakt={(id) => {
                const k = kontakte.find(x => x.id === id);
                if (k) {
                  setSelectedKontakt(k);
                  setDrawerOpen(true);
                }
              }}
            />
          ) : selectedNav === 'mission' ? (
            /* MISSION CONTROL - STRATEGISCHE ÜBERSICHT */
            <MissionControlView
              kontakte={kontakte}
              themeMode={themeMode}
              onOpenKontakt={(k) => { setSelectedKontakt(k); setDrawerOpen(true); }}
              onNavigateToKontakte={() => { setSelectedNav('kontakte'); setActiveTab('tabelle'); }}
              onOpenDesign={() => { setIsDesignEditorOpen(true); setIsSettingsModalOpen(true); }}
              onKontaktUpdate={(updated) => {
                setKontakte(prev => prev.map(k => (k.id === updated.id ? updated : k)));
              }}
            />
          ) : selectedNav === 'mediaboard' ? (
            /* MEDIA BOARD - PINWAND FÜR GRAFIKEN & IDEEN */
            <MediaBoardView themeMode={themeMode} />
          ) : selectedNav === 'content-studio' ? (
            /* CONTENT STUDIO - VIDEO KOMPILATIONEN, LINKEDIN GHOSTWRITING & DISTRIBUTION */
            <ContentStudioView themeMode={themeMode} />
          ) : activeTab === 'pipeline' ? (



            /* KANBAN PIPELINE BOARD VIEW WITH DRAG & DROP */
            <div className="flex gap-4 overflow-x-auto pb-4 h-full kanban-view-root">
              {STATUS_COLUMNS.map((col) => {
                const columnKontakte = filteredKontakte.filter((k) => {
                  const hasVernetztDate = !!(k.vernetzt_am || (k as any).vernetzt_ab);

                  if (col.id === 'Unvernetzt') {
                    if (k.status === 'Unvernetzt') return true;
                    if (!hasVernetztDate && (!k.status || k.status === 'Vernetzt')) return true;
                    return false;
                  }

                  if (col.id === 'Vernetzt') {
                    if (k.status === 'Vernetzt' && !hasVernetztDate) return false;
                    return k.status === 'Vernetzt';
                  }

                  return k.status === col.id;
                });
                const isGesperrtCol = col.id === 'Gesperrt_1Jahr';
                const isDragOver = dragOverColumnId === col.id;

                return (
                  <div
                    key={col.id}
                    onDragOver={(e) => handleColumnDragOver(e, col.id)}
                    onDragLeave={handleColumnDragLeave}
                    onDrop={(e) => handleColumnDrop(e, col.id)}
                    className={`w-72 shrink-0 rounded-xl border p-3 flex flex-col h-full transition-all ${
                      isDragOver
                        ? 'border-emerald-500 ring-2 ring-emerald-500/30 bg-emerald-500/10'
                        : isLight
                        ? 'bg-white border-slate-200 shadow-sm'
                        : `${col.color} bg-slate-900/40 backdrop-blur-sm`
                    }`}
                  >
                    {/* Column Header */}
                    <div className={`flex items-center justify-between pb-3 border-b mb-3 ${
                      isLight ? 'border-slate-200' : 'border-slate-800/60'
                    }`}>
                      <div className="flex items-center gap-2">
                        <ColumnIcon colId={col.id} />
                        <h3 className={`text-xs font-bold uppercase tracking-wider ${
                          isLight ? 'text-slate-800' : 'text-slate-200'
                        }`}>
                          {col.title}
                        </h3>
                      </div>
                      <span className={`text-[11px] font-mono font-bold px-2 py-0.5 rounded-full border ${
                        isLight ? 'bg-slate-100 border-slate-300 text-slate-800' : 'bg-slate-950 border-slate-800 text-slate-300'
                      }`}>
                        {columnKontakte.length}
                      </span>
                    </div>

                    {/* Cards Container */}
                    <div className="flex-1 overflow-y-auto space-y-3 pr-1">
                      {columnKontakte.length === 0 ? (
                        <div className={`h-24 border border-dashed rounded-lg flex items-center justify-center text-xs font-medium ${
                          isLight ? 'border-slate-300 text-slate-400' : 'border-slate-800 text-slate-600'
                        }`}>
                          Keine Kontakte
                        </div>
                      ) : (
                        columnKontakte.map((k) => {
                          const pUrl = getProfilbildUrl(k);
                          const initials = k.name
                            ? k.name.split(' ').map((n) => n[0]).filter(Boolean).slice(0, 2).join('').toUpperCase()
                            : '??';

                          return (
                            <div
                              key={k.id}
                              draggable
                              onDragStart={(e) => handleCardDragStart(e, k.id)}
                              onClick={() => handleCardClick(k)}
                              className={`group p-3.5 rounded-xl border transition-all cursor-grab active:cursor-grabbing space-y-2 relative overflow-hidden ${
                                draggedCardId === k.id ? 'opacity-40 scale-95' : ''
                              } ${
                                isLight
                                  ? isGesperrtCol
                                    ? 'bg-rose-50/80 border-rose-200 hover:border-rose-400'
                                    : 'bg-white border-slate-200 hover:border-[var(--accent-primary)] hover:shadow-md'
                                  : isGesperrtCol
                                  ? 'bg-rose-950/10 border-rose-900/60 hover:border-rose-600'
                                  : 'bg-slate-900 border-slate-800/80 hover:border-[var(--accent-primary)]/50 hover:bg-slate-900/80'
                              }`}
                            >
                              {/* Card Header: Name (zweizeilig erlaubt) + Rating & Small Top-Right Profile Picture */}
                              <div className="flex items-start justify-between gap-2">
                                <div className="flex-1 min-w-0 pr-1">
                                  <h4 className={`font-bold text-xs leading-tight line-clamp-2 break-words transition ${
                                    isLight ? 'text-slate-900 group-hover:text-[var(--accent-primary)]' : 'text-slate-100 group-hover:text-[var(--accent-primary)]'
                                  }`}>
                                    {k.name}
                                  </h4>
                                  {/* Nutzer-Sterne – nur wenn Rating vorhanden */}
                                  {k.rating && Number(k.rating) > 0 && (
                                    <div className="flex flex-wrap items-center gap-1.5 mt-1">
                                      <span className="text-amber-500 text-[10px] tracking-tight select-none font-mono">
                                        {'⭐'.repeat(Math.min(Math.max(Number(k.rating), 1), 5))}
                                      </span>
                                    </div>
                                  )}
                                </div>

                                {/* Profilbild klein oben rechts */}
                                {pUrl ? (
                                  <img
                                    src={pUrl}
                                    alt={k.name}
                                    className="w-9 h-9 rounded-full object-fill border border-slate-200 dark:border-slate-700 shrink-0 shadow-xs"
                                  />
                                ) : (
                                  <div className={`w-9 h-9 rounded-full font-bold text-[11px] flex items-center justify-center shrink-0 border ${
                                    isLight ? 'bg-slate-100 border-slate-200 text-slate-600' : 'bg-slate-800 border-slate-700 text-slate-300'
                                  }`}>
                                    {initials}
                                  </div>
                                )}
                              </div>

                              {/* Company & Role */}
                              {(k.unternehmen || k.rolle) && (
                                <div className={`text-[11px] font-medium flex items-center gap-1.5 ${
                                  isLight ? 'text-slate-600' : 'text-slate-400'
                                }`}>
                                  <Building2 className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                                  <span className="truncate">
                                    {k.unternehmen} {k.rolle ? `• ${k.rolle}` : ''}
                                  </span>
                                </div>
                              )}

                              {/* Region */}
                              {k.region && (
                                <div className="text-[10px] flex items-center gap-1 text-slate-500">
                                  <MapPin className="w-3 h-3 text-slate-400 shrink-0" />
                                  <span className="truncate">{k.region}</span>
                                </div>
                              )}

                              {/* Nachrichtenverlauf Button */}
                              {k.nachrichtenverlauf && (
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setSelectedNachrichtenKontakt(k);
                                    setNachrichtenModalOpen(true);
                                  }}
                                  style={{
                                    backgroundColor: 'var(--contact-message-history-btn-bg)',
                                    borderColor: 'var(--contact-message-history-btn-border)',
                                    color: 'var(--contact-message-history-btn-text)',
                                  }}
                                  className="w-full text-left px-2.5 py-1.5 rounded-lg border font-mono text-[10px] font-bold transition flex items-center justify-between cursor-pointer mt-1 hover:opacity-90"
                                >
                                  <span className="flex items-center gap-1.5">
                                    <MessageSquare className="w-3.5 h-3.5" style={{ color: 'var(--contact-message-history-btn-text)' }} />
                                    <span>Nachrichtenverlauf</span>
                                  </span>
                                  <span style={{ color: 'var(--contact-message-history-btn-text)' }}>➔</span>
                                </button>
                              )}

                              {/* 1-Year Cooldown Warning Banner */}
                              {isGesperrtCol && (
                                <div className={`p-1.5 rounded-lg border text-[10px] font-mono flex items-center gap-1.5 ${
                                  isLight ? 'bg-rose-100 border-rose-300 text-rose-800 font-bold' : 'bg-rose-950/60 border-rose-900/80 text-rose-300'
                                }`}>
                                  <ShieldAlert className="w-3.5 h-3.5 text-rose-600 shrink-0" />
                                  <span>
                                    Sperrfrist: {k.einladung_zurueckgezogen_am ? new Date(k.einladung_zurueckgezogen_am).toLocaleDateString('de-DE') : 'Aktiv'}
                                  </span>
                                </div>
                              )}

                              {/* Next step indicator – Farbe über CSS-Variable steuerbar */}
                              {k.naechster_schritt && (
                                <div
                                  className="text-[10px] font-mono truncate font-bold pt-0.5"
                                  style={{ color: 'var(--contact-nextstep-color, #059669)' }}
                                >
                                  ➔ {k.naechster_schritt}
                                </div>
                              )}
                            </div>
                          );
                        })
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (

            /* TABELLE VIEW MIT STICKY HEADER, RESIZING & ALPHABETISCHER SORTIERUNG */
            <div className={`rounded-xl border max-h-[calc(100vh-175px)] overflow-auto shadow-sm ${
              isLight ? 'bg-white border-slate-200' : 'bg-slate-900/40 border-slate-800'
            }`}>
              <table className={`w-full text-left text-xs table-fixed border-collapse ${
                isLight ? 'text-slate-800' : 'text-slate-300'
              }`}>
                <thead className={`sticky top-0 z-20 border-b font-mono uppercase text-[10px] tracking-wider font-bold select-none shadow-xs ${
                  isLight ? 'bg-slate-100 border-slate-200 text-slate-700' : 'bg-slate-950 border-slate-800 text-slate-300'
                }`}>
                  <tr>
                    <th className={`p-3 w-10 text-center sticky top-0 z-20 ${isLight ? 'bg-slate-100' : 'bg-slate-950'}`}>
                      <input
                        type="checkbox"
                        checked={selectedRowIds.length > 0 && selectedRowIds.length === filteredKontakte.length}
                        onChange={handleSelectAllRows}
                        className="rounded accent-emerald-600 cursor-pointer"
                      />
                    </th>

                    {activeVisibleColumns.map((col) => {
                      const width = columnWidths[col.key] || DEFAULT_COLUMN_WIDTHS[col.key] || 150;
                      const isSorted = sortField === col.key;

                      return (
                        <th
                          key={col.key}
                          style={{ width: `${width}px` }}
                          draggable
                          onDragStart={(e) => handleTableColDragStart(e, col.key)}
                          onDragOver={(e) => e.preventDefault()}
                          onDrop={(e) => handleTableColDrop(e, col.key)}
                          onClick={() => handleSort(col.key)}
                          className={`p-3 relative group sticky top-0 z-20 cursor-pointer transition select-none ${
                            isSorted
                              ? isLight
                                ? 'bg-accent-soft text-accent-main font-bold border-b-2 border-accent-soft shadow-xs'
                                : 'bg-accent-light text-accent-main font-bold border-b-2 border-accent-light shadow-xs'
                              : isLight
                              ? 'bg-slate-100 text-slate-700 hover:bg-accent-soft hover:text-accent-main'
                              : 'bg-slate-950 text-slate-300 hover:bg-accent-light hover:text-accent-main'
                          } ${
                            draggedColKey === col.key ? 'opacity-40 border-2 border-dashed border-accent-main' : ''
                          }`}
                        >
                          <div className="flex items-center justify-between gap-1.5 truncate">
                            <div className="flex items-center gap-1.5 truncate">
                              <span className="font-mono text-[11px] font-semibold text-slate-400 dark:text-slate-500 shrink-0">
                                {col.typeIcon}
                              </span>
                              <span className="truncate">{col.label}</span>
                            </div>

                            <div className="shrink-0 flex items-center pr-1">
                              {isSorted ? (
                                sortDirection === 'asc' ? (
                                  <ArrowUp className="w-3.5 h-3.5 text-accent-main" />
                                ) : (
                                  <ArrowDown className="w-3.5 h-3.5 text-accent-main" />
                                )
                              ) : (
                                <ArrowUpDown className="w-3.5 h-3.5 text-slate-400 opacity-0 group-hover:opacity-100 transition" />
                              )}
                            </div>
                          </div>

                          {/* Interactive Column Resize Handle */}
                          <div
                            onMouseDown={(e) => {
                              e.stopPropagation();
                              handleResizeMouseDown(e, col.key);
                            }}
                            className="absolute right-0 top-0 bottom-0 w-2.5 cursor-col-resize hover:bg-accent-main/80 active:bg-accent-main transition z-30 opacity-40 hover:opacity-100"
                            title="Spaltenbreite anpassen"
                          />
                        </th>
                      );
                    })}
                    <th className={`p-3 w-28 text-right sticky top-0 z-20 ${isLight ? 'bg-slate-100' : 'bg-slate-950'}`}>
                      Aktionen
                    </th>
                  </tr>
                </thead>
                <tbody className={`divide-y ${isLight ? 'divide-slate-200' : 'divide-slate-800/60'}`}>
                  {filteredKontakte.length === 0 ? (
                    <tr>
                      <td colSpan={activeVisibleColumns.length + 2} className="p-8 text-center text-slate-400 font-mono">
                        Keine Kontakte gefunden.
                      </td>
                    </tr>
                  ) : (
                    filteredKontakte.map((k) => {
                      const isSelected = selectedRowIds.includes(k.id);

                      return (
                        <tr
                          key={k.id}
                          onClick={() => handleCardClick(k)}
                          className={`transition cursor-pointer ${
                            isSelected
                              ? isLight ? 'bg-emerald-50/80' : 'bg-emerald-950/20'
                              : isLight ? 'hover:bg-slate-50' : 'hover:bg-slate-800/40'
                          }`}
                        >
                          <td className="p-3 text-center" onClick={(e) => e.stopPropagation()}>
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onChange={() => toggleSelectRow(k.id)}
                              className="rounded accent-emerald-600 cursor-pointer"
                            />
                          </td>

                          {activeVisibleColumns.map((col) => (
                            <td key={col.key} className="p-3 truncate" style={{ maxWidth: `${columnWidths[col.key] || DEFAULT_COLUMN_WIDTHS[col.key] || 150}px` }}>
                              {renderTableCell(col.key, k)}
                            </td>
                          ))}

                          <td className="p-3 text-right font-mono text-emerald-600 font-bold hover:underline shrink-0">
                            Bearbeiten ➔
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          )}

        </div>

      </main>

      {/* SLIDE-OVER DETAIL DRAWER */}
      <KontaktDrawer
        kontakt={selectedKontakt}
        isOpen={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onSave={handleSaveDrawer}
        onDelete={handleDeleteDrawer}
        themeMode={themeMode}
      />

      {/* UNDO TOAST NOTIFICATION */}
      {undoToastVisible && undoStack.length > 0 && (
        <div className="fixed bottom-6 right-6 z-50 animate-in slide-in-from-bottom-5 duration-200 select-none">
          <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-slate-900/95 text-white shadow-2xl border border-slate-700 backdrop-blur-md">
            <Trash2 className="w-4 h-4 text-rose-400 shrink-0" />
            <span className="text-xs font-medium">
              {undoStack.length === 1
                ? `"${undoStack[0].name}" in den Papierkorb verschoben.`
                : `${undoStack.length} Kontakte in den Papierkorb verschoben.`}
            </span>
            <button
              type="button"
              onClick={() => handleUndo()}
              className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold transition cursor-pointer shadow-sm ml-2"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Rückgängig
            </button>
            <button
              type="button"
              onClick={() => setUndoToastVisible(false)}
              className="p-1 text-slate-400 hover:text-white transition cursor-pointer"
              title="Schließen"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* CSS LIVE STUDIO INSPECTOR & STYLER (Hardened & Scoped) */}
      <CssLiveStudio />

    </div>
  );
}
