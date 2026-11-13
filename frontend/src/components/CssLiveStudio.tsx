'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { 
  Palette, Code, Save, RotateCcw, X, Minus,
  Check, Sliders, MousePointer, Copy, CheckCheck,
  Move, Type, Square, Maximize2, Layout, Sparkles,
  PlusCircle, ChevronDown, List, PaintBucket, GripVertical
} from 'lucide-react';

interface StudioRules {
  [selector: string]: {
    [property: string]: string;
  };
}

const CSS_PROPERTIES_SUGGESTIONS = [
  "accent-color", "align-content", "align-items", "align-self", "animation",
  "aspect-ratio", "backdrop-filter", "background", "background-color", "background-image",
  "background-position", "background-repeat", "background-size", "border", "border-color",
  "border-radius", "border-style", "border-width", "bottom", "box-shadow", "box-sizing",
  "clip-path", "color", "column-gap", "cursor", "display", "filter", "flex",
  "flex-direction", "flex-grow", "flex-shrink", "flex-wrap", "font-family", "font-size",
  "font-weight", "gap", "grid-template-columns", "grid-template-rows", "height", "inset",
  "justify-content", "justify-items", "left", "letter-spacing", "line-height", "margin",
  "margin-bottom", "margin-left", "margin-right", "margin-top", "max-height", "max-width",
  "min-height", "min-width", "opacity", "outline", "overflow", "overflow-x", "overflow-y",
  "padding", "padding-bottom", "padding-left", "padding-right", "padding-top", "position",
  "right", "text-align", "text-decoration", "text-transform", "top", "transform",
  "transition", "user-select", "visibility", "width", "z-index"
];

export default function CssLiveStudio() {
  const [isOpen, setIsOpen] = useState(false);
  const [isMinimized, setIsMinimized] = useState(false);
  const [activeTab, setActiveTab] = useState<'visual' | 'rules' | 'raw'>('visual');
  const [inspecting, setInspecting] = useState(false);
  const [gizmoActive, setGizmoActive] = useState(true);
  const [currentSelector, setCurrentSelector] = useState('');
  const [selectedTag, setSelectedTag] = useState('none');
  const [studioRules, setStudioRules] = useState<StudioRules>({});
  const [rawCss, setRawCss] = useState('');
  const [savedSuccess, setSavedSuccess] = useState(false);
  const [copied, setCopied] = useState(false);

  // Selected element for gizmo & live computed values
  const selectedElementRef = useRef<HTMLElement | null>(null);
  const [gizmoRect, setGizmoRect] = useState<{ top: number; left: number; width: number; height: number; radius: number } | null>(null);

  // Custom prop inputs
  const [customPropName, setCustomPropName] = useState('');
  const [customPropVal, setCustomPropVal] = useState('');

  // Window Dragging
  const studioRef = useRef<HTMLDivElement | null>(null);
  const [position, setPosition] = useState<{ x: number; y: number } | null>(null);
  const dragRef = useRef<{ startX: number; startY: number; initX: number; initY: number } | null>(null);

  // Load saved overrides
  useEffect(() => {
    async function loadSaved() {
      try {
        const sanitizeRules = (rulesObj: Record<string, any>) => {
          if (!rulesObj) return {};
          const clean: Record<string, any> = {};
          for (const [sel, props] of Object.entries(rulesObj)) {
            // Strip destructive selectors matching the contact drawer or general utilities
            if (
              sel === '.gap-4' ||
              sel === '.p-6' ||
              sel === '.grid-cols-1' ||
              sel.includes('div.fixed > div.w-full') ||
              sel.includes('contact-drawer-container') ||
              sel.includes('div.p-4')
            ) {
              continue;
            }
            clean[sel] = props;
          }
          return clean;
        };

        const local = localStorage.getItem('crm_theme_live_overrides');
        if (local) {
          const parsed = JSON.parse(local);
          if (parsed.rules) {
            const clean = sanitizeRules(parsed.rules);
            setStudioRules(clean);
            localStorage.setItem('crm_theme_live_overrides', JSON.stringify({ ...parsed, rules: clean }));
          }
          if (parsed.rawCss) setRawCss(parsed.rawCss);
        }
        
        const res = await fetch('/api/theme/live_overrides');
        if (res.ok) {
          const data = await res.json();
          if (data.rules && Object.keys(data.rules).length > 0) {
            const clean = sanitizeRules(data.rules);
            setStudioRules(clean);
          }
          if (data.rawCss) {
            setRawCss(data.rawCss);
          }
        }
      } catch (e) {
        console.error('Failed to load CRM live overrides:', e);
      }
    }
    loadSaved();
  }, []);

  // Keyboard shortcut Alt + S & Custom Event & Ctrl+S Save
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.altKey && (e.key === 's' || e.key === 'S')) {
        e.preventDefault();
        setIsOpen((prev) => !prev);
        setIsMinimized(false);
      }
      if ((e.ctrlKey || e.metaKey) && (e.key === 's' || e.key === 'S')) {
        if (isOpen && !isMinimized) {
          e.preventDefault();
          handleSave();
        }
      }
    };
    const handleCustomToggle = () => {
      setIsOpen((prev) => !prev);
      setIsMinimized(false);
    };
    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('archon_toggle_css_studio', handleCustomToggle);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('archon_toggle_css_studio', handleCustomToggle);
    };
  }, [isOpen, isMinimized]);

  // Update Gizmo Rect based on selected element
  const updateGizmoRect = useCallback(() => {
    if (!selectedElementRef.current || !gizmoActive || !isOpen || isMinimized) {
      setGizmoRect(null);
      return;
    }
    const el = selectedElementRef.current;
    const rect = el.getBoundingClientRect();
    const computed = window.getComputedStyle(el);
    const radius = parseFloat(computed.borderRadius) || 0;
    setGizmoRect({
      top: rect.top,
      left: rect.left,
      width: rect.width,
      height: rect.height,
      radius
    });
  }, [gizmoActive, isOpen, isMinimized]);

  useEffect(() => {
    updateGizmoRect();
    window.addEventListener('scroll', updateGizmoRect, true);
    window.addEventListener('resize', updateGizmoRect);
    return () => {
      window.removeEventListener('scroll', updateGizmoRect, true);
      window.removeEventListener('resize', updateGizmoRect);
    };
  }, [updateGizmoRect]);

  // Inject styles to head with priority !important
  useEffect(() => {
    let styleTag = document.getElementById('crm-live-custom-styles');
    if (!styleTag) {
      styleTag = document.createElement('style');
      styleTag.id = 'crm-live-custom-styles';
      document.head.appendChild(styleTag);
    }

    let cssText = '/* Archon CRM CSS Live Studio */\n';
    cssText += '#archon-css-studio, #archon-css-studio-minimized, #archon-css-highlighter, #archon-css-gizmo { z-index: 99999999 !important; }\n\n';

    for (const [sel, props] of Object.entries(studioRules)) {
      if (!props || Object.keys(props).length === 0) continue;
      // Never allow overriding general utility classes or contact drawer container heights
      if (
        sel === '.gap-4' ||
        sel === '.p-6' ||
        sel === '.grid-cols-1' ||
        sel.includes('div.fixed > div.w-full') ||
        sel.includes('contact-drawer-container') ||
        sel.includes('div.p-4')
      ) {
        continue;
      }
      cssText += sel + ' {\n';
      for (const [p, v] of Object.entries(props)) {
        if (v !== undefined && v !== '') {
          // Block accidental global height expansions on general selectors
          if (p === 'height' && parseInt(String(v), 10) > 400 && !sel.startsWith('#')) continue;
          const hasImp = String(v).includes('!important');
          cssText += '  ' + p + ': ' + v + (hasImp ? '' : ' !important') + ';\n';
        }
      }
      cssText += '}\n\n';
    }

    if (rawCss && rawCss.trim() && !rawCss.includes('/* Archon CRM CSS Live Studio */')) {
      cssText += rawCss + '\n';
    }

    styleTag.innerHTML = cssText;
    updateGizmoRect();
  }, [studioRules, rawCss, updateGizmoRect]);

  // Smart Selector Generator
  const generateSmartSelector = (el: HTMLElement): string => {
    if (el.id) return '#' + el.id;
    if (el.dataset && el.dataset.role) return `[data-role="${el.dataset.role}"]`;

    // Reject structural container elements in modals/drawers from being styled blindly
    if (el.classList.contains('contact-drawer-container') || el.id === 'contact-drawer-window') {
      return '#contact-drawer-window';
    }

    // Try unique class that isn't a Tailwind utility or layout primitive
    if (el.className && typeof el.className === 'string') {
      const classes = el.className.split(/\s+/).filter(c => 
        c && 
        !c.startsWith('hover:') && !c.startsWith('focus:') && !c.startsWith('active:') &&
        !c.includes('/') && !c.includes(':') &&
        !c.startsWith('p-') && !c.startsWith('px-') && !c.startsWith('py-') &&
        !c.startsWith('m-') && !c.startsWith('gap-') && !c.startsWith('w-') && !c.startsWith('h-') &&
        !c.startsWith('flex') && !c.startsWith('grid') && !c.startsWith('border') &&
        !c.startsWith('bg-') && !c.startsWith('text-')
      );
      for (const cls of classes) {
        if (cls.length > 2 && document.querySelectorAll(`.${cls}`).length === 1) {
          return '.' + cls;
        }
      }
    }

    // Build unique, safe scoped selector
    // If element is inside an identified container, scope to it
    const scopedRoot = el.closest('[id], .mission-control-root, .sidebar-root, .contact-drawer-container, .mediaboard-view-root, .calendar-view-root');
    let scopePrefix = '';
    if (scopedRoot && scopedRoot !== el) {
      if (scopedRoot.id) scopePrefix = '#' + scopedRoot.id + ' ';
      else {
        const rootCls = Array.from(scopedRoot.classList).find(c => c.endsWith('-root') || c.endsWith('-container'));
        if (rootCls) scopePrefix = '.' + rootCls + ' ';
      }
    }

    const path: string[] = [];
    let cur: HTMLElement | null = el;
    while (cur && cur !== document.body && cur !== scopedRoot && path.length < 3) {
      let part = cur.tagName.toLowerCase();
      if (cur.id) {
        part += '#' + cur.id;
        path.unshift(part);
        break;
      }
      if (cur.className && typeof cur.className === 'string') {
        const meaningfulCls = cur.className.split(/\s+/).find(c => 
          c && !c.startsWith('hover:') && !c.startsWith('focus:') && !c.includes('/') && !c.includes(':') &&
          !c.startsWith('w-') && !c.startsWith('h-') && !c.startsWith('p-') && !c.startsWith('m-') && !c.startsWith('gap-')
        );
        if (meaningfulCls) part += '.' + meaningfulCls;
      }
      path.unshift(part);
      cur = cur.parentElement;
    }
    return (scopePrefix + path.join(' > ')).trim() || el.tagName.toLowerCase();
  };

  // Inspect element mode
  useEffect(() => {
    if (!inspecting) return;

    let highlighter = document.getElementById('archon-css-highlighter');
    if (!highlighter) {
      highlighter = document.createElement('div');
      highlighter.id = 'archon-css-highlighter';
      highlighter.style.cssText = 'position:fixed;pointer-events:none;border:2px solid #6366f1;background:rgba(99,102,241,0.15);z-index:99999999;transition:all 0.05s ease-out;border-radius:4px;';
      document.body.appendChild(highlighter);
    }
    highlighter.style.display = 'block';

    const onMouseOver = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (!target || target.closest('#archon-css-studio') || target.closest('#archon-css-studio-minimized') || target.closest('#archon-css-gizmo')) return;
      
      const rect = target.getBoundingClientRect();
      if (highlighter) {
        highlighter.style.top = rect.top + 'px';
        highlighter.style.left = rect.left + 'px';
        highlighter.style.width = rect.width + 'px';
        highlighter.style.height = rect.height + 'px';
      }
    };

    const onClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (!target || target.closest('#archon-css-studio') || target.closest('#archon-css-studio-minimized') || target.closest('#archon-css-gizmo')) return;
      e.preventDefault();
      e.stopPropagation();

      selectedElementRef.current = target;
      setSelectedTag(target.tagName.toLowerCase());

      const sel = generateSmartSelector(target);
      setCurrentSelector(sel);
      setInspecting(false);
      if (highlighter) highlighter.style.display = 'none';
      updateGizmoRect();
    };

    window.addEventListener('mouseover', onMouseOver);
    window.addEventListener('click', onClick, true);

    return () => {
      window.removeEventListener('mouseover', onMouseOver);
      window.removeEventListener('click', onClick, true);
      if (highlighter) highlighter.style.display = 'none';
    };
  }, [inspecting, updateGizmoRect]);

  const handlePropChange = (prop: string, value: string) => {
    if (!currentSelector) return;
    setStudioRules((prev) => {
      const currentRule = { ...(prev[currentSelector] || {}) };
      if (value === '' || value === undefined) {
        delete currentRule[prop];
      } else {
        currentRule[prop] = value;
      }
      
      if (Object.keys(currentRule).length === 0) {
        const next = { ...prev };
        delete next[currentSelector];
        return next;
      }
      return { ...prev, [currentSelector]: currentRule };
    });
  };

  const getPropVal = (prop: string): string => {
    if (!currentSelector) return '';
    if (studioRules[currentSelector] && studioRules[currentSelector][prop] !== undefined) {
      return studioRules[currentSelector][prop];
    }
    if (selectedElementRef.current) {
      const comp = window.getComputedStyle(selectedElementRef.current);
      const val = (comp as any)[prop] || comp.getPropertyValue(prop);
      if (val && val !== 'rgba(0, 0, 0, 0)' && val !== 'none' && val !== 'normal' && val !== 'auto') {
        return val;
      }
    }
    return '';
  };

  // Drag Position Gizmo handler
  const handleGizmoMoveMouseDown = (e: React.MouseEvent) => {
    if (!selectedElementRef.current) return;
    e.preventDefault();
    e.stopPropagation();

    const el = selectedElementRef.current;
    const startX = e.clientX;
    const startY = e.clientY;
    const computed = window.getComputedStyle(el);
    const isRelativeOrAbsolute = computed.position === 'relative' || computed.position === 'absolute' || computed.position === 'fixed';

    const initLeft = parseFloat(computed.left) || 0;
    const initTop = parseFloat(computed.top) || 0;

    const onMouseMove = (moveEvt: MouseEvent) => {
      const dx = moveEvt.clientX - startX;
      const dy = moveEvt.clientY - startY;
      if (!isRelativeOrAbsolute) {
        el.style.position = 'relative';
      }
      el.style.left = `${initLeft + dx}px`;
      el.style.top = `${initTop + dy}px`;
      updateGizmoRect();
    };

    const onMouseUp = (upEvt: MouseEvent) => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);

      const dx = upEvt.clientX - startX;
      const dy = upEvt.clientY - startY;
      if (dx !== 0 || dy !== 0) {
        if (!isRelativeOrAbsolute) {
          handlePropChange('position', 'relative');
        }
        handlePropChange('left', `${initLeft + dx}px`);
        handlePropChange('top', `${initTop + dy}px`);
      }
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  };

  // Resize Corner/Edge Gizmo handler
  const handleGizmoResizeMouseDown = (e: React.MouseEvent, dir: string) => {
    if (!selectedElementRef.current) return;
    e.preventDefault();
    e.stopPropagation();

    const el = selectedElementRef.current;
    const startX = e.clientX;
    const startY = e.clientY;
    const startW = el.offsetWidth;
    const startH = el.offsetHeight;

    const onMouseMove = (moveEvt: MouseEvent) => {
      const dx = moveEvt.clientX - startX;
      const dy = moveEvt.clientY - startY;

      let newW = startW;
      let newH = startH;

      if (dir.includes('e')) newW = Math.max(16, startW + dx);
      if (dir.includes('w')) newW = Math.max(16, startW - dx);
      if (dir.includes('s')) newH = Math.max(16, startH + dy);
      if (dir.includes('n')) newH = Math.max(16, startH - dy);

      el.style.width = `${newW}px`;
      el.style.height = `${newH}px`;
      updateGizmoRect();
    };

    const onMouseUp = (upEvt: MouseEvent) => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);

      const dx = upEvt.clientX - startX;
      const dy = upEvt.clientY - startY;

      let finalW = startW;
      let finalH = startH;
      if (dir.includes('e')) finalW = Math.max(16, startW + dx);
      if (dir.includes('w')) finalW = Math.max(16, startW - dx);
      if (dir.includes('s')) finalH = Math.max(16, startH + dy);
      if (dir.includes('n')) finalH = Math.max(16, startH - dy);

      if (finalW !== startW) handlePropChange('width', `${finalW}px`);
      if (finalH !== startH) handlePropChange('height', `${finalH}px`);
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  };

  // Corner Radius Gizmo handler
  const handleGizmoRadiusMouseDown = (e: React.MouseEvent) => {
    if (!selectedElementRef.current) return;
    e.preventDefault();
    e.stopPropagation();

    const el = selectedElementRef.current;
    const startX = e.clientX;
    const computed = window.getComputedStyle(el);
    const initRadius = parseFloat(computed.borderRadius) || 0;

    const onMouseMove = (moveEvt: MouseEvent) => {
      const dx = moveEvt.clientX - startX;
      const newRadius = Math.max(0, Math.min(100, Math.round(initRadius + dx * 0.4)));
      el.style.borderRadius = `${newRadius}px`;
      updateGizmoRect();
    };

    const onMouseUp = (upEvt: MouseEvent) => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
      const dx = upEvt.clientX - startX;
      const finalRadius = Math.max(0, Math.min(100, Math.round(initRadius + dx * 0.4)));
      handlePropChange('border-radius', `${finalRadius}px`);
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  };

  // Studio Modal Drag
  const handleStudioDragStart = (e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest('button') || (e.target as HTMLElement).closest('input')) return;
    e.preventDefault();
    const studio = studioRef.current;
    if (!studio) return;
    const rect = studio.getBoundingClientRect();
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      initX: rect.left,
      initY: rect.top
    };

    const onPointerMove = (moveEvt: PointerEvent) => {
      if (!dragRef.current) return;
      const dx = moveEvt.clientX - dragRef.current.startX;
      const dy = moveEvt.clientY - dragRef.current.startY;
      const newX = Math.max(10, Math.min(window.innerWidth - 480, dragRef.current.initX + dx));
      const newY = Math.max(10, Math.min(window.innerHeight - 80, dragRef.current.initY + dy));
      setPosition({ x: newX, y: newY });
    };

    const onPointerUp = () => {
      dragRef.current = null;
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
    };

    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
  };

  async function handleSave() {
    try {
      const payload = { rules: studioRules, rawCss: rawCss };
      localStorage.setItem('crm_theme_live_overrides', JSON.stringify(payload));
      
      const res = await fetch('/api/theme/live_overrides', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        setSavedSuccess(true);
        setTimeout(() => setSavedSuccess(false), 2000);
      }
    } catch (err) {
      console.error('Error saving overrides:', err);
    }
  };

  const activeRulesCount = Object.keys(studioRules).reduce((acc, sel) => {
    return acc + Object.keys(studioRules[sel] || {}).length;
  }, 0);

  return (
    <>
      {/* 1. INTERACTIVE TRANSFORM GIZMO (DRAG POSITION, RESIZE, RADIUS) */}
      {gizmoRect && gizmoActive && isOpen && !isMinimized && (
        <div 
          id="archon-css-gizmo"
          style={{
            position: 'fixed',
            top: gizmoRect.top + 'px',
            left: gizmoRect.left + 'px',
            width: gizmoRect.width + 'px',
            height: gizmoRect.height + 'px',
            borderRadius: gizmoRect.radius + 'px',
          }}
          className="pointer-events-auto border-2 border-dashed border-indigo-400 bg-indigo-500/10 z-[99999997] select-none transition-[border-color]"
        >
          {/* Top Move Handle (Drag Position) */}
          <div 
            onMouseDown={handleGizmoMoveMouseDown}
            className="absolute -top-7 left-1/2 -translate-x-1/2 bg-indigo-600 hover:bg-indigo-500 text-white font-mono text-[10px] px-2 py-0.5 rounded shadow-md flex items-center gap-1 cursor-move active:bg-indigo-700 whitespace-nowrap"
            title="Position frei mit der Maus verschieben"
          >
            <Move className="w-3 h-3" /> Position ziehen
          </div>

          {/* Info Badge */}
          <div className="absolute -bottom-6 left-1/2 -translate-x-1/2 bg-slate-900/95 text-indigo-200 border border-indigo-500/40 font-mono text-[9px] px-2 py-0.5 rounded-full shadow whitespace-nowrap">
            {Math.round(gizmoRect.width)}px × {Math.round(gizmoRect.height)}px · R: {gizmoRect.radius}px
          </div>

          {/* Corner Resize Handles */}
          <div onMouseDown={(e) => handleGizmoResizeMouseDown(e, 'nw')} className="absolute -top-2 -left-2 w-3.5 h-3.5 bg-white border-2 border-indigo-600 rounded-xs cursor-nwse-resize shadow hover:scale-125 transition-transform" />
          <div onMouseDown={(e) => handleGizmoResizeMouseDown(e, 'ne')} className="absolute -top-2 -right-2 w-3.5 h-3.5 bg-white border-2 border-indigo-600 rounded-xs cursor-nesw-resize shadow hover:scale-125 transition-transform" />
          <div onMouseDown={(e) => handleGizmoResizeMouseDown(e, 'sw')} className="absolute -bottom-2 -left-2 w-3.5 h-3.5 bg-white border-2 border-indigo-600 rounded-xs cursor-nesw-resize shadow hover:scale-125 transition-transform" />
          <div onMouseDown={(e) => handleGizmoResizeMouseDown(e, 'se')} className="absolute -bottom-2 -right-2 w-3.5 h-3.5 bg-white border-2 border-indigo-600 rounded-xs cursor-nwse-resize shadow hover:scale-125 transition-transform" />

          {/* Edge Handles */}
          <div onMouseDown={(e) => handleGizmoResizeMouseDown(e, 'w')} className="absolute top-1/2 -left-1.5 -translate-y-1/2 w-2.5 h-5 bg-indigo-600 rounded-xs cursor-ew-resize hover:scale-110 shadow" />
          <div onMouseDown={(e) => handleGizmoResizeMouseDown(e, 'e')} className="absolute top-1/2 -right-1.5 -translate-y-1/2 w-2.5 h-5 bg-indigo-600 rounded-xs cursor-ew-resize hover:scale-110 shadow" />
          <div onMouseDown={(e) => handleGizmoResizeMouseDown(e, 'n')} className="absolute -top-1.5 left-1/2 -translate-x-1/2 h-2.5 w-5 bg-indigo-600 rounded-xs cursor-ns-resize hover:scale-110 shadow" />
          <div onMouseDown={(e) => handleGizmoResizeMouseDown(e, 's')} className="absolute -bottom-1.5 left-1/2 -translate-x-1/2 h-2.5 w-5 bg-indigo-600 rounded-xs cursor-ns-resize hover:scale-110 shadow" />

          {/* Corner Radius Knob */}
          <div onMouseDown={handleGizmoRadiusMouseDown} className="absolute top-2 left-2 w-3.5 h-3.5 bg-amber-400 border border-slate-900 rounded-full cursor-pointer shadow hover:scale-125 transition-transform" title="Eckenrundung ziehen" />
        </div>
      )}

      {/* 2. MINIMIZED FLOATING BADGE */}
      {isMinimized && (
        <div 
          id="archon-css-studio-minimized"
          onClick={() => { setIsMinimized(false); setIsOpen(true); }}
          className="fixed bottom-6 left-6 z-[99999999] bg-slate-900/95 text-white border border-indigo-500/60 rounded-full shadow-2xl px-4 py-2 flex items-center gap-2 cursor-pointer hover:scale-105 hover:bg-slate-800 transition backdrop-blur-md"
        >
          <span className="w-2.5 h-2.5 rounded-full bg-indigo-500 animate-ping" />
          <Palette className="w-4 h-4 text-indigo-400" />
          <span className="text-xs font-mono font-bold text-indigo-200">CRM CSS Studio</span>
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-indigo-600 text-white font-bold">
            {activeRulesCount}
          </span>
        </div>
      )}

      {/* 3. MAIN FLOATING STUDIO WINDOW */}
      {isOpen && !isMinimized && (
        <div 
          ref={studioRef}
          id="archon-css-studio"
          style={position ? { left: `${position.x}px`, top: `${position.y}px`, right: 'auto' } : undefined}
          className="fixed top-14 right-6 w-[470px] max-w-[95vw] h-[min(84vh,calc(100vh-4.5rem))] max-h-[calc(100vh-4.5rem)] z-[99999999] flex flex-col bg-slate-950/95 text-slate-100 border-2 border-indigo-500/70 rounded-2xl shadow-[0_20px_60px_rgba(0,0,0,0.8)] backdrop-blur-xl animate-in zoom-in-95 duration-200 select-none overflow-hidden font-sans"
        >
          {/* Draggable Header */}
          <div 
            onPointerDown={handleStudioDragStart}
            className="p-3 bg-gradient-to-r from-slate-900 via-indigo-950/70 to-slate-900 border-b border-indigo-500/30 flex items-center justify-between shrink-0 cursor-grab active:cursor-grabbing"
          >
            <div className="flex items-center gap-2">
              <GripVertical className="w-4 h-4 text-slate-400" />
              <Palette className="w-4 h-4 text-indigo-400" />
              <span className="font-extrabold text-xs tracking-wider text-white uppercase">CRM CSS Live Studio</span>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 font-bold">
                {activeRulesCount} Regeln
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={handleSave}
                className="px-3 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold shadow-md transition flex items-center gap-1 cursor-pointer"
                title="Dauerhaft speichern (Strg + S)"
              >
                {savedSuccess ? <Check className="w-3.5 h-3.5 text-white" /> : <Save className="w-3.5 h-3.5" />}
                <span>{savedSuccess ? 'Gespeichert!' : 'Speichern'}</span>
              </button>
              <button 
                type="button" 
                onClick={() => setIsMinimized(true)}
                className="p-1 rounded hover:bg-white/10 text-slate-400 hover:text-white transition cursor-pointer"
                title="Minimieren"
              >
                <Minus className="w-3.5 h-3.5" />
              </button>
              <button 
                type="button" 
                onClick={() => setIsOpen(false)}
                className="p-1 rounded hover:bg-rose-500/20 text-slate-400 hover:text-rose-400 transition font-bold cursor-pointer"
                title="Schließen (Alt + S)"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Action Ribbon: Inspect & Gizmo Mode */}
          <div className="p-2.5 bg-slate-900/90 border-b border-slate-800 flex flex-col gap-2 shrink-0">
            <div className="grid grid-cols-3 gap-2">
              <button
                type="button"
                onClick={() => setInspecting(!inspecting)}
                className={'py-1.5 px-2 rounded-xl font-bold text-xs flex items-center justify-center gap-1 transition cursor-pointer shadow-xs ' + (
                  inspecting ? 'bg-rose-500 text-white animate-pulse' : 'bg-indigo-600 hover:bg-indigo-500 text-white'
                )}
              >
                <MousePointer className="w-3.5 h-3.5" />
                {inspecting ? 'Klicke...' : '🎯 Wählen'}
              </button>
              <button
                type="button"
                onClick={() => setGizmoActive(!gizmoActive)}
                className={'py-1.5 px-2 rounded-xl font-bold text-xs flex items-center justify-center gap-1 transition cursor-pointer border ' + (
                  gizmoActive ? 'bg-indigo-500/30 border-indigo-400 text-indigo-200' : 'bg-slate-800 border-slate-700 text-slate-400'
                )}
              >
                <Move className="w-3.5 h-3.5" />
                {gizmoActive ? '✋ Ecken: AN' : '✋ Ecken: AUS'}
              </button>
              <button
                type="button"
                onClick={handleSave}
                className="py-1.5 px-2 rounded-xl font-bold text-xs flex items-center justify-center gap-1 transition cursor-pointer bg-emerald-600 hover:bg-emerald-500 text-white shadow-xs"
                title="Dauerhaft auf Server speichern (Strg + S)"
              >
                {savedSuccess ? <Check className="w-3.5 h-3.5 text-white" /> : <Save className="w-3.5 h-3.5" />}
                <span>{savedSuccess ? 'Gespeichert' : 'Speichern'}</span>
              </button>
            </div>

            {/* Target Selector Path Display */}
            <div className="flex items-center gap-1.5 bg-slate-950/80 border border-slate-700/70 rounded-lg px-2.5 py-1">
              <span className="text-[10px] font-mono text-indigo-400 font-bold shrink-0">CSS Ziel:</span>
              <input
                type="text"
                value={currentSelector}
                onChange={(e) => {
                  setCurrentSelector(e.target.value);
                  try {
                    const el = document.querySelector(e.target.value);
                    if (el instanceof HTMLElement) {
                      selectedElementRef.current = el;
                      setSelectedTag(el.tagName.toLowerCase());
                      updateGizmoRect();
                    }
                  } catch (_) {}
                }}
                placeholder="Klicke ein Element an oder tippe z.B. #kanban-board, .sidebar-root"
                className="flex-1 bg-transparent text-xs font-mono text-indigo-300 focus:outline-none placeholder-slate-500"
              />
              <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">
                {selectedTag}
              </span>
            </div>
          </div>

          {/* Navigation Tabs */}
          <div className="flex items-center border-b border-slate-800 bg-slate-900/60 p-1 gap-1 text-xs shrink-0">
            <button
              type="button"
              onClick={() => setActiveTab('visual')}
              className={'flex-1 py-1.5 px-3 rounded-lg font-bold flex items-center justify-center gap-1.5 transition cursor-pointer ' + (
                activeTab === 'visual' ? 'bg-indigo-600 text-white shadow-md' : 'text-slate-400 hover:text-slate-200'
              )}
            >
              <Sliders className="w-3.5 h-3.5" /> Visual Builder
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('rules')}
              className={'flex-1 py-1.5 px-3 rounded-lg font-bold flex items-center justify-center gap-1.5 transition cursor-pointer ' + (
                activeTab === 'rules' ? 'bg-indigo-600 text-white shadow-md' : 'text-slate-400 hover:text-slate-200'
              )}
            >
              <List className="w-3.5 h-3.5" /> Alle Regeln
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('raw')}
              className={'flex-1 py-1.5 px-3 rounded-lg font-bold flex items-center justify-center gap-1.5 transition cursor-pointer ' + (
                activeTab === 'raw' ? 'bg-indigo-600 text-white shadow-md' : 'text-slate-400 hover:text-slate-200'
              )}
            >
              <Code className="w-3.5 h-3.5" /> Raw CSS
            </button>
          </div>

          {/* Tab Contents */}
          <div className="flex-1 overflow-y-auto p-3 space-y-2.5 text-xs custom-scrollbar">
            {activeTab === 'visual' && (
              <>
                {currentSelector ? (
                  <div className="space-y-2.5">
                    {/* 1. TYPOGRAFIE & SCHRIFT */}
                    <details className="group bg-slate-900/70 border border-slate-800 rounded-xl overflow-hidden" open>
                      <summary className="flex items-center justify-between p-2.5 font-bold text-xs text-indigo-300 cursor-pointer select-none bg-slate-900/90 hover:bg-slate-800/80 transition">
                        <span className="flex items-center gap-2"><Type className="w-3.5 h-3.5 text-indigo-400" /> Typografie & Schrift</span>
                        <ChevronDown className="w-3.5 h-3.5 transition-transform group-open:rotate-180 text-slate-400" />
                      </summary>
                      <div className="p-3 space-y-2.5 border-t border-slate-800/80 bg-slate-950/40">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-slate-300 font-mono text-[11px]">Schriftfarbe:</span>
                          <div className="flex items-center gap-1.5">
                            <input 
                              type="color" 
                              value={getPropVal('color') || '#ffffff'}
                              onChange={(e) => handlePropChange('color', e.target.value)}
                              className="w-6 h-6 rounded border border-slate-700 cursor-pointer p-0 bg-transparent" 
                            />
                            <input 
                              type="text" 
                              value={getPropVal('color')}
                              onChange={(e) => handlePropChange('color', e.target.value)}
                              placeholder="#ffffff" 
                              className="w-24 bg-slate-900 border border-slate-700 rounded px-2 py-0.5 font-mono text-[11px] text-white focus:outline-none focus:border-indigo-500" 
                            />
                          </div>
                        </div>

                        <div>
                          <div className="flex justify-between text-[11px] font-mono text-slate-300 mb-1">
                            <span>Schriftgröße:</span>
                            <span className="text-indigo-400 font-bold">{getPropVal('font-size') || '14px'}</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <input 
                              type="range" 
                              min="8" 
                              max="64" 
                              value={parseFloat(getPropVal('font-size')) || 14}
                              onChange={(e) => handlePropChange('font-size', e.target.value + 'px')}
                              className="flex-1 accent-indigo-500 cursor-pointer" 
                            />
                            <input 
                              type="text" 
                              value={getPropVal('font-size')}
                              onChange={(e) => handlePropChange('font-size', e.target.value)}
                              placeholder="14px"
                              className="w-16 bg-slate-900 border border-slate-700 rounded px-1.5 py-0.5 text-center font-mono text-[11px] text-white focus:outline-none" 
                            />
                          </div>
                        </div>

                        <div className="grid grid-cols-2 gap-2 font-mono">
                          <div>
                            <label className="block text-[10px] text-slate-400 mb-1">Dicke (weight)</label>
                            <select 
                              value={getPropVal('font-weight') || 'normal'}
                              onChange={(e) => handlePropChange('font-weight', e.target.value)}
                              className="w-full bg-slate-900 border border-slate-700 rounded p-1 text-[11px] text-white focus:outline-none"
                            >
                              <option value="normal">Normal (400)</option>
                              <option value="500">Medium (500)</option>
                              <option value="600">Semibold (600)</option>
                              <option value="bold">Bold (700)</option>
                              <option value="800">Extrabold (800)</option>
                            </select>
                          </div>
                          <div>
                            <label className="block text-[10px] text-slate-400 mb-1">Ausrichtung (align)</label>
                            <select 
                              value={getPropVal('text-align') || 'inherit'}
                              onChange={(e) => handlePropChange('text-align', e.target.value)}
                              className="w-full bg-slate-900 border border-slate-700 rounded p-1 text-[11px] text-white focus:outline-none"
                            >
                              <option value="inherit">Standard</option>
                              <option value="left">Links</option>
                              <option value="center">Zentriert</option>
                              <option value="right">Rechts</option>
                            </select>
                          </div>
                        </div>
                      </div>
                    </details>

                    {/* 2. HINTERGRUND & FÜLLUNG */}
                    <details className="group bg-slate-900/70 border border-slate-800 rounded-xl overflow-hidden" open>
                      <summary className="flex items-center justify-between p-2.5 font-bold text-xs text-indigo-300 cursor-pointer select-none bg-slate-900/90 hover:bg-slate-800/80 transition">
                        <span className="flex items-center gap-2"><PaintBucket className="w-3.5 h-3.5 text-indigo-400" /> Hintergrund & Füllung</span>
                        <ChevronDown className="w-3.5 h-3.5 transition-transform group-open:rotate-180 text-slate-400" />
                      </summary>
                      <div className="p-3 space-y-2.5 border-t border-slate-800/80 bg-slate-950/40 font-mono">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-slate-300 text-[11px]">Hintergrundfarbe:</span>
                          <div className="flex items-center gap-1.5">
                            <input 
                              type="color" 
                              value={getPropVal('background-color') || '#0f172a'}
                              onChange={(e) => handlePropChange('background-color', e.target.value)}
                              className="w-6 h-6 rounded border border-slate-700 cursor-pointer p-0 bg-transparent" 
                            />
                            <input 
                              type="text" 
                              value={getPropVal('background-color')}
                              onChange={(e) => handlePropChange('background-color', e.target.value)}
                              placeholder="#0f172a" 
                              className="w-24 bg-slate-900 border border-slate-700 rounded px-2 py-0.5 text-[11px] text-white focus:outline-none focus:border-indigo-500" 
                            />
                          </div>
                        </div>

                        <div>
                          <label className="block text-[10px] text-slate-400 mb-1">Hintergrundbild / Gradient</label>
                          <input 
                            type="text" 
                            value={getPropVal('background-image')}
                            onChange={(e) => handlePropChange('background-image', e.target.value)}
                            placeholder="url('...') oder linear-gradient(...)"
                            className="w-full bg-slate-900 border border-slate-700 rounded p-1 text-[11px] text-white focus:outline-none" 
                          />
                        </div>

                        <div className="grid grid-cols-2 gap-2">
                          <div>
                            <label className="block text-[10px] text-slate-400 mb-1">Deckkraft (opacity)</label>
                            <input 
                              type="range" 
                              min="0" 
                              max="1" 
                              step="0.05" 
                              value={parseFloat(getPropVal('opacity')) || 1}
                              onChange={(e) => handlePropChange('opacity', e.target.value)}
                              className="w-full accent-indigo-500 cursor-pointer" 
                            />
                          </div>
                          <div>
                            <label className="block text-[10px] text-slate-400 mb-1">Backdrop-Blur</label>
                            <input 
                              type="text" 
                              value={getPropVal('backdrop-filter')}
                              onChange={(e) => handlePropChange('backdrop-filter', e.target.value)}
                              placeholder="z.B. blur(10px)"
                              className="w-full bg-slate-900 border border-slate-700 rounded p-1 text-[11px] text-white focus:outline-none" 
                            />
                          </div>
                        </div>
                      </div>
                    </details>

                    {/* 3. RAHMEN & ECKENRUNDUNG */}
                    <details className="group bg-slate-900/70 border border-slate-800 rounded-xl overflow-hidden" open>
                      <summary className="flex items-center justify-between p-2.5 font-bold text-xs text-indigo-300 cursor-pointer select-none bg-slate-900/90 hover:bg-slate-800/80 transition">
                        <span className="flex items-center gap-2"><Square className="w-3.5 h-3.5 text-indigo-400" /> Rahmen & Ecken (Border)</span>
                        <ChevronDown className="w-3.5 h-3.5 transition-transform group-open:rotate-180 text-slate-400" />
                      </summary>
                      <div className="p-3 space-y-2.5 border-t border-slate-800/80 bg-slate-950/40 font-mono">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-slate-300 text-[11px]">Rahmenfarbe:</span>
                          <div className="flex items-center gap-1.5">
                            <input 
                              type="color" 
                              value={getPropVal('border-color') || '#334155'}
                              onChange={(e) => handlePropChange('border-color', e.target.value)}
                              className="w-6 h-6 rounded border border-slate-700 cursor-pointer p-0 bg-transparent" 
                            />
                            <input 
                              type="text" 
                              value={getPropVal('border-color')}
                              onChange={(e) => handlePropChange('border-color', e.target.value)}
                              placeholder="#334155" 
                              className="w-24 bg-slate-900 border border-slate-700 rounded px-2 py-0.5 text-[11px] text-white focus:outline-none focus:border-indigo-500" 
                            />
                          </div>
                        </div>

                        <div className="grid grid-cols-2 gap-2">
                          <div>
                            <label className="block text-[10px] text-slate-400 mb-1">Breite (width)</label>
                            <input 
                              type="text" 
                              value={getPropVal('border-width')}
                              onChange={(e) => handlePropChange('border-width', e.target.value)}
                              placeholder="1px, 2px"
                              className="w-full bg-slate-900 border border-slate-700 rounded p-1 text-[11px] text-white focus:outline-none" 
                            />
                          </div>
                          <div>
                            <label className="block text-[10px] text-slate-400 mb-1">Stil (style)</label>
                            <select 
                              value={getPropVal('border-style') || 'solid'}
                              onChange={(e) => handlePropChange('border-style', e.target.value)}
                              className="w-full bg-slate-900 border border-slate-700 rounded p-1 text-[11px] text-white focus:outline-none"
                            >
                              <option value="solid">Solid</option>
                              <option value="dashed">Dashed</option>
                              <option value="dotted">Dotted</option>
                              <option value="none">Keiner</option>
                            </select>
                          </div>
                        </div>

                        <div>
                          <div className="flex justify-between text-[11px] text-slate-300 mb-1">
                            <span>Eckenrundung (radius):</span>
                            <span className="text-indigo-400 font-bold">{getPropVal('border-radius') || '0px'}</span>
                          </div>
                          <input 
                            type="range" 
                            min="0" 
                            max="48" 
                            value={parseFloat(getPropVal('border-radius')) || 0}
                            onChange={(e) => handlePropChange('border-radius', e.target.value + 'px')}
                            className="w-full accent-indigo-500 cursor-pointer" 
                          />
                        </div>
                      </div>
                    </details>

                    {/* 4. ABSTÄNDE & BOX-MODELL */}
                    <details className="group bg-slate-900/70 border border-slate-800 rounded-xl overflow-hidden">
                      <summary className="flex items-center justify-between p-2.5 font-bold text-xs text-indigo-300 cursor-pointer select-none bg-slate-900/90 hover:bg-slate-800/80 transition">
                        <span className="flex items-center gap-2"><Maximize2 className="w-3.5 h-3.5 text-indigo-400" /> Abstände & Box-Modell</span>
                        <ChevronDown className="w-3.5 h-3.5 transition-transform group-open:rotate-180 text-slate-400" />
                      </summary>
                      <div className="p-3 space-y-2.5 border-t border-slate-800/80 bg-slate-950/40 font-mono">
                        {/* Margin & Padding Diagram */}
                        <div className="p-2 border border-dashed border-amber-500/40 bg-amber-500/5 rounded-lg text-center text-[10px]">
                          <span className="text-amber-400 font-bold block mb-1">MARGIN (Außen)</span>
                          <div className="flex justify-center mb-1">
                            <input 
                              type="text" 
                              value={getPropVal('margin-top')} 
                              onChange={(e) => handlePropChange('margin-top', e.target.value)} 
                              placeholder="T: 0" 
                              className="w-16 bg-slate-950 border border-slate-700 rounded px-1 py-0.5 text-center text-amber-300" 
                            />
                          </div>
                          <div className="flex items-center justify-between gap-1 mb-1">
                            <input 
                              type="text" 
                              value={getPropVal('margin-left')} 
                              onChange={(e) => handlePropChange('margin-left', e.target.value)} 
                              placeholder="L: 0" 
                              className="w-16 bg-slate-950 border border-slate-700 rounded px-1 py-0.5 text-center text-amber-300" 
                            />
                            <div className="flex-1 p-2 border border-indigo-500/50 bg-indigo-500/10 rounded text-center mx-1">
                              <span className="text-indigo-300 font-bold block mb-1">PADDING (Innen)</span>
                              <div className="flex justify-center mb-1">
                                <input 
                                  type="text" 
                                  value={getPropVal('padding-top')} 
                                  onChange={(e) => handlePropChange('padding-top', e.target.value)} 
                                  placeholder="T: 8px" 
                                  className="w-14 bg-slate-950 border border-slate-700 rounded px-1 py-0.5 text-center text-indigo-300" 
                                />
                              </div>
                              <div className="flex items-center justify-between gap-1 mb-1">
                                <input 
                                  type="text" 
                                  value={getPropVal('padding-left')} 
                                  onChange={(e) => handlePropChange('padding-left', e.target.value)} 
                                  placeholder="L: 8px" 
                                  className="w-14 bg-slate-950 border border-slate-700 rounded px-1 py-0.5 text-center text-indigo-300" 
                                />
                                <span className="text-[9px] text-slate-400">INHALT</span>
                                <input 
                                  type="text" 
                                  value={getPropVal('padding-right')} 
                                  onChange={(e) => handlePropChange('padding-right', e.target.value)} 
                                  placeholder="R: 8px" 
                                  className="w-14 bg-slate-950 border border-slate-700 rounded px-1 py-0.5 text-center text-indigo-300" 
                                />
                              </div>
                              <div className="flex justify-center">
                                <input 
                                  type="text" 
                                  value={getPropVal('padding-bottom')} 
                                  onChange={(e) => handlePropChange('padding-bottom', e.target.value)} 
                                  placeholder="B: 8px" 
                                  className="w-14 bg-slate-950 border border-slate-700 rounded px-1 py-0.5 text-center text-indigo-300" 
                                />
                              </div>
                            </div>
                            <input 
                              type="text" 
                              value={getPropVal('margin-right')} 
                              onChange={(e) => handlePropChange('margin-right', e.target.value)} 
                              placeholder="R: 0" 
                              className="w-16 bg-slate-950 border border-slate-700 rounded px-1 py-0.5 text-center text-amber-300" 
                            />
                          </div>
                          <div className="flex justify-center">
                            <input 
                              type="text" 
                              value={getPropVal('margin-bottom')} 
                              onChange={(e) => handlePropChange('margin-bottom', e.target.value)} 
                              placeholder="B: 0" 
                              className="w-16 bg-slate-950 border border-slate-700 rounded px-1 py-0.5 text-center text-amber-300" 
                            />
                          </div>
                        </div>

                        {/* Dimensions Width & Height */}
                        <div className="grid grid-cols-2 gap-2">
                          <div>
                            <label className="block text-[10px] text-slate-400 mb-1">Breite (width)</label>
                            <input 
                              type="text" 
                              value={getPropVal('width')}
                              onChange={(e) => handlePropChange('width', e.target.value)}
                              placeholder="auto / 100% / 320px"
                              className="w-full bg-slate-900 border border-slate-700 rounded p-1 text-[11px] text-white focus:outline-none" 
                            />
                          </div>
                          <div>
                            <label className="block text-[10px] text-slate-400 mb-1">Höhe (height)</label>
                            <input 
                              type="text" 
                              value={getPropVal('height')}
                              onChange={(e) => handlePropChange('height', e.target.value)}
                              placeholder="auto / 40px / 100%"
                              className="w-full bg-slate-900 border border-slate-700 rounded p-1 text-[11px] text-white focus:outline-none" 
                            />
                          </div>
                        </div>
                      </div>
                    </details>

                    {/* 5. LAYOUT, POSITION & FLEXBOX */}
                    <details className="group bg-slate-900/70 border border-slate-800 rounded-xl overflow-hidden">
                      <summary className="flex items-center justify-between p-2.5 font-bold text-xs text-indigo-300 cursor-pointer select-none bg-slate-900/90 hover:bg-slate-800/80 transition">
                        <span className="flex items-center gap-2"><Layout className="w-3.5 h-3.5 text-indigo-400" /> Position, Layout & Flexbox</span>
                        <ChevronDown className="w-3.5 h-3.5 transition-transform group-open:rotate-180 text-slate-400" />
                      </summary>
                      <div className="p-3 space-y-2.5 border-t border-slate-800/80 bg-slate-950/40 font-mono">
                        <div className="grid grid-cols-2 gap-2">
                          <div>
                            <label className="block text-[10px] text-slate-400 mb-1">Position</label>
                            <select 
                              value={getPropVal('position') || 'static'}
                              onChange={(e) => handlePropChange('position', e.target.value)}
                              className="w-full bg-slate-900 border border-slate-700 rounded p-1 text-[11px] text-white focus:outline-none"
                            >
                              <option value="static">static</option>
                              <option value="relative">relative</option>
                              <option value="absolute">absolute</option>
                              <option value="fixed">fixed</option>
                              <option value="sticky">sticky</option>
                            </select>
                          </div>
                          <div>
                            <label className="block text-[10px] text-slate-400 mb-1">Anzeige (display)</label>
                            <select 
                              value={getPropVal('display') || 'inherit'}
                              onChange={(e) => handlePropChange('display', e.target.value)}
                              className="w-full bg-slate-900 border border-slate-700 rounded p-1 text-[11px] text-white focus:outline-none"
                            >
                              <option value="inherit">Standard</option>
                              <option value="flex">flex</option>
                              <option value="grid">grid</option>
                              <option value="block">block</option>
                              <option value="inline-block">inline-block</option>
                              <option value="none">none</option>
                            </select>
                          </div>
                        </div>

                        <div className="grid grid-cols-2 gap-2">
                          <div>
                            <label className="block text-[10px] text-slate-400 mb-1">Links (left)</label>
                            <input 
                              type="text" 
                              value={getPropVal('left')}
                              onChange={(e) => handlePropChange('left', e.target.value)}
                              placeholder="z.B. 20px"
                              className="w-full bg-slate-900 border border-slate-700 rounded p-1 text-[11px] text-white focus:outline-none" 
                            />
                          </div>
                          <div>
                            <label className="block text-[10px] text-slate-400 mb-1">Oben (top)</label>
                            <input 
                              type="text" 
                              value={getPropVal('top')}
                              onChange={(e) => handlePropChange('top', e.target.value)}
                              placeholder="z.B. 40px"
                              className="w-full bg-slate-900 border border-slate-700 rounded p-1 text-[11px] text-white focus:outline-none" 
                            />
                          </div>
                        </div>

                        <div className="grid grid-cols-2 gap-2">
                          <div>
                            <label className="block text-[10px] text-slate-400 mb-1">Z-Index (Ebene)</label>
                            <input 
                              type="number" 
                              value={getPropVal('z-index')}
                              onChange={(e) => handlePropChange('z-index', e.target.value)}
                              placeholder="10, 50"
                              className="w-full bg-slate-900 border border-slate-700 rounded p-1 text-[11px] text-white focus:outline-none" 
                            />
                          </div>
                          <div>
                            <label className="block text-[10px] text-slate-400 mb-1">Abstand (gap)</label>
                            <input 
                              type="text" 
                              value={getPropVal('gap')}
                              onChange={(e) => handlePropChange('gap', e.target.value)}
                              placeholder="8px, 1rem"
                              className="w-full bg-slate-900 border border-slate-700 rounded p-1 text-[11px] text-white focus:outline-none" 
                            />
                          </div>
                        </div>
                      </div>
                    </details>

                    {/* 6. EFFEKTE & SCHATTEN */}
                    <details className="group bg-slate-900/70 border border-slate-800 rounded-xl overflow-hidden">
                      <summary className="flex items-center justify-between p-2.5 font-bold text-xs text-indigo-300 cursor-pointer select-none bg-slate-900/90 hover:bg-slate-800/80 transition">
                        <span className="flex items-center gap-2"><Sparkles className="w-3.5 h-3.5 text-indigo-400" /> Schatten & Effekte</span>
                        <ChevronDown className="w-3.5 h-3.5 transition-transform group-open:rotate-180 text-slate-400" />
                      </summary>
                      <div className="p-3 space-y-2.5 border-t border-slate-800/80 bg-slate-950/40 font-mono">
                        <div>
                          <label className="block text-[10px] text-slate-400 mb-1">Schatten (box-shadow)</label>
                          <select 
                            onChange={(e) => handlePropChange('box-shadow', e.target.value)}
                            className="w-full bg-slate-900 border border-slate-700 rounded p-1 text-[11px] text-white focus:outline-none mb-1.5"
                          >
                            <option value="">Preset wählen...</option>
                            <option value="none">Kein Schatten</option>
                            <option value="0 1px 3px rgba(0,0,0,0.1)">Subtil (1px)</option>
                            <option value="0 4px 6px -1px rgba(0,0,0,0.1)">Mittel (Medium)</option>
                            <option value="0 10px 15px -3px rgba(0,0,0,0.2)">Prominent (Large)</option>
                            <option value="0 0 20px rgba(99, 102, 241, 0.4)">Indigo Glow</option>
                            <option value="0 0 20px rgba(16, 185, 129, 0.4)">Emerald Glow</option>
                          </select>
                          <input 
                            type="text" 
                            value={getPropVal('box-shadow')}
                            onChange={(e) => handlePropChange('box-shadow', e.target.value)}
                            placeholder="Eigener Wert z.B. 0 4px 20px rgba(0,0,0,0.2)"
                            className="w-full bg-slate-900 border border-slate-700 rounded p-1 text-[11px] text-white focus:outline-none" 
                          />
                        </div>

                        <div className="grid grid-cols-2 gap-2">
                          <div>
                            <label className="block text-[10px] text-slate-400 mb-1">Mauszeiger (cursor)</label>
                            <select 
                              value={getPropVal('cursor') || 'auto'}
                              onChange={(e) => handlePropChange('cursor', e.target.value)}
                              className="w-full bg-slate-900 border border-slate-700 rounded p-1 text-[11px] text-white focus:outline-none"
                            >
                              <option value="auto">auto</option>
                              <option value="pointer">pointer</option>
                              <option value="default">default</option>
                              <option value="move">move</option>
                            </select>
                          </div>
                          <div>
                            <label className="block text-[10px] text-slate-400 mb-1">Animation (transition)</label>
                            <input 
                              type="text" 
                              value={getPropVal('transition')}
                              onChange={(e) => handlePropChange('transition', e.target.value)}
                              placeholder="all 0.2s ease"
                              className="w-full bg-slate-900 border border-slate-700 rounded p-1 text-[11px] text-white focus:outline-none" 
                            />
                          </div>
                        </div>
                      </div>
                    </details>

                    {/* 7. BELIEBIGE FREIE CSS PROPERTY HINZUFÜGEN */}
                    <div className="bg-indigo-950/40 border border-indigo-500/40 rounded-xl p-2.5 space-y-2">
                      <span className="text-[11px] font-bold text-indigo-300 flex items-center gap-1.5 font-mono">
                        <PlusCircle className="w-3.5 h-3.5 text-indigo-400" />
                        Beliebige CSS-Eigenschaft hinzufügen
                      </span>
                      <div className="flex items-center gap-1.5 font-mono">
                        <input 
                          type="text" 
                          list="crm-css-property-list"
                          value={customPropName}
                          onChange={(e) => setCustomPropName(e.target.value)}
                          placeholder="z.B. transform, filter"
                          className="flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-[11px] text-white focus:outline-none focus:border-indigo-500" 
                        />
                        <input 
                          type="text" 
                          value={customPropVal}
                          onChange={(e) => setCustomPropVal(e.target.value)}
                          placeholder="z.B. scale(1.05)"
                          className="flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-[11px] text-white focus:outline-none focus:border-indigo-500" 
                        />
                        <button 
                          type="button" 
                          onClick={() => {
                            if (!customPropName.trim()) return;
                            handlePropChange(customPropName.trim(), customPropVal.trim());
                            setCustomPropName('');
                            setCustomPropVal('');
                          }}
                          className="px-3 py-1 bg-indigo-600 hover:bg-indigo-500 text-white rounded font-bold text-xs transition cursor-pointer"
                        >
                          +
                        </button>
                      </div>
                      <datalist id="crm-css-property-list">
                        {CSS_PROPERTIES_SUGGESTIONS.map((p) => (
                          <option key={p} value={p} />
                        ))}
                      </datalist>
                    </div>
                  </div>
                ) : (
                  <div className="text-center py-12 text-slate-500 space-y-2 font-mono">
                    <MousePointer className="w-8 h-8 mx-auto text-indigo-400/40" />
                    <p className="text-xs">Klicke oben auf „🎯 Element Auswählen“ oder tippe einen Selektor ein, um Styles zu bearbeiten.</p>
                  </div>
                )}
              </>
            )}

            {/* TAB 2: ALLE REGELN */}
            {activeTab === 'rules' && (
              <div className="space-y-2 font-mono">
                <div className="flex items-center justify-between text-slate-400 text-[11px] pb-1 border-b border-slate-800">
                  <span>Gespeicherte Selektoren ({Object.keys(studioRules).length}):</span>
                  <button 
                    type="button" 
                    onClick={() => {
                      if (confirm('Möchtest du alle CSS-Regeln löschen?')) {
                        setStudioRules({});
                      }
                    }}
                    className="text-rose-400 hover:text-rose-300 text-[10px] cursor-pointer"
                  >
                    Alle löschen
                  </button>
                </div>
                {Object.keys(studioRules).length === 0 ? (
                  <div className="text-slate-500 text-center py-8 text-xs">Noch keine Regeln definiert.</div>
                ) : (
                  Object.entries(studioRules).map(([sel, props]) => (
                    <div key={sel} className="bg-slate-900 border border-slate-800 rounded-xl p-2.5 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-indigo-300 font-bold text-xs truncate max-w-[280px]">{sel}</span>
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            onClick={() => {
                              setCurrentSelector(sel);
                              setActiveTab('visual');
                              try {
                                const el = document.querySelector(sel);
                                if (el instanceof HTMLElement) {
                                  selectedElementRef.current = el;
                                  setSelectedTag(el.tagName.toLowerCase());
                                  updateGizmoRect();
                                }
                              } catch (_) {}
                            }}
                            className="px-2 py-0.5 rounded bg-indigo-600/30 hover:bg-indigo-600 text-indigo-300 hover:text-white text-[10px] cursor-pointer"
                          >
                            Bearbeiten
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setStudioRules((prev) => {
                                const next = { ...prev };
                                delete next[sel];
                                return next;
                              });
                            }}
                            className="px-2 py-0.5 rounded bg-rose-900/30 hover:bg-rose-900 text-rose-300 text-[10px] cursor-pointer"
                          >
                            Löschen
                          </button>
                        </div>
                      </div>
                      <div className="bg-slate-950 p-2 rounded-lg text-[11px] space-y-1">
                        {Object.entries(props).map(([p, v]) => (
                          <div key={p} className="flex items-center justify-between">
                            <span className="text-slate-400">{p}:</span>
                            <span className="text-emerald-400 font-bold">{v}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}

            {/* TAB 3: RAW CSS */}
            {activeTab === 'raw' && (
              <div className="space-y-2 font-mono">
                <div className="flex items-center justify-between">
                  <label className="font-bold text-slate-400 text-[11px] uppercase tracking-wider">
                    Raw CSS Stylesheet
                  </label>
                  <button
                    type="button"
                    onClick={() => {
                      const styleTag = document.getElementById('crm-live-custom-styles');
                      const textToCopy = styleTag ? styleTag.innerHTML : rawCss;
                      navigator.clipboard.writeText(textToCopy);
                      setCopied(true);
                      setTimeout(() => setCopied(false), 2000);
                    }}
                    className="text-[11px] text-indigo-400 hover:text-indigo-300 flex items-center gap-1 cursor-pointer"
                  >
                    {copied ? <CheckCheck className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                    {copied ? 'Kopiert!' : 'Kopieren'}
                  </button>
                </div>
                <textarea
                  value={rawCss}
                  onChange={(e) => setRawCss(e.target.value)}
                  placeholder="/* Freie CSS-Regeln hier eintragen. Greift sofort live im DOM! */&#10;.sidebar-root {&#10;  background: #0f172a !important;&#10;}"
                  rows={14}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl p-3 text-xs text-indigo-200 focus:outline-none focus:border-indigo-500 leading-relaxed custom-scrollbar"
                />
              </div>
            )}
          </div>

          {/* Action Footer */}
          <div className="p-3 bg-slate-900/90 border-t border-slate-800/80 flex items-center justify-between shrink-0 font-mono">
            <button
              type="button"
              onClick={() => {
                if (confirm('Möchtest du alle CSS-Live-Regeln zurücksetzen?')) {
                  setStudioRules({});
                  setRawCss('');
                  localStorage.removeItem('crm_theme_live_overrides');
                  fetch('/api/theme/live_overrides', { method: 'DELETE' }).catch(() => {});
                }
              }}
              className="px-3 py-1.5 rounded-lg border border-slate-700 text-slate-400 hover:text-rose-400 hover:border-rose-500/40 text-xs font-bold transition flex items-center gap-1.5 cursor-pointer"
            >
              <RotateCcw className="w-3.5 h-3.5" /> Reset
            </button>

            <button
              type="button"
              onClick={handleSave}
              className="px-4 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold shadow-lg shadow-indigo-600/30 transition flex items-center gap-1.5 cursor-pointer"
            >
              {savedSuccess ? <Check className="w-3.5 h-3.5 text-emerald-300" /> : <Save className="w-3.5 h-3.5" />}
              {savedSuccess ? 'Gespeichert!' : 'Dauerhaft Speichern'}
            </button>
          </div>
        </div>
      )}
    </>
  );
}
