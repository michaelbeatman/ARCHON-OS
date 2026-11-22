/**
 * static/js/operations_calendar.js
 * M25 / M104 — Eigene Archon OS Kalender-Engine (100% eigener Code, ohne Fremdbibliothek)
 * Ansichten: Tag, Woche, Monat (mit KW), Jahr, Agenda | Drag & Drop, Resize, Ueberlappungs-Spalten,
 * Outlook-Sidebar, Layer-Filter, Serientermine, Fokuszeit-Finder & Settings-Integration.
 */
(function () {
  "use strict";

  const PREFS_KEY = "archon_calendar_prefs_v1";
  const HOUR_PX = 54;
  const MONTHS_DE = ["Januar", "Februar", "Maerz", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];
  const DAYS_SHORT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];

  let _viewMode = "week"; // "day" | "week" | "month" | "year" | "list"
  let _cursorDate = new Date();
  let _miniDate = new Date();
  let _allEvents = [];
  let _sources = [];
  let _resources = ["Konferenzraum A", "Konferenzraum B", "Beamer / Fahrzeug", "Team: Micha", "Team: Robert"];
  let _searchQuery = "";
  let _catFilter = "all";
  let _timelineSpan = "day"; // "day" | "week"
  let _activeLayers = {
    custom: true,
    focus: true,
    kanban: true,
    workflow: true,
    n8n: true,
    erp: true,
    external: true,
    holiday: true,
    school_holiday: true,
  };

  function getPrefs() {
    const def = {
      initialView: "week",
      slotMinHour: 6,
      slotMaxHour: 22,
      focusDuration: 90,
      showWeekends: true,
      businessStartHour: 9,
      businessEndHour: 18,
      secondaryTz: "America/New_York",
      holidayState: "BY",
      bookingSlug: "mein-termin",
    };
    try {
      const raw = localStorage.getItem(PREFS_KEY);
      if (!raw) return def;
      const p = JSON.parse(raw);
      // Kompatibilitaet mit alten View-Namen
      const map = { timeGridWeek: "week", dayGridMonth: "month", timeGridDay: "day", listWeek: "list" };
      if (map[p.initialView]) p.initialView = map[p.initialView];
      if (p.slotMinTime) p.slotMinHour = parseInt(String(p.slotMinTime).slice(0, 2), 10) || 6;
      if (p.slotMaxTime) p.slotMaxHour = parseInt(String(p.slotMaxTime).slice(0, 2), 10) || 22;
      return { ...def, ...p };
    } catch (_) {
      return def;
    }
  }

  function savePrefs(next) {
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify({ ...getPrefs(), ...next }));
    } catch (_) {}
  }

  const CAL_I18N = {
    en: { today: "Today", day: "Day", week: "Week", month: "Month", year: "Year", resource: "Resources", timeline: "Timeline", agenda: "Agenda", new_ev: "+ New Event", focus: "Focus Time", booking: "Booking Link", print: "Print / PDF", settings: "Settings" },
    fr: { today: "Aujourd'hui", day: "Jour", week: "Semaine", month: "Mois", year: "Annee", resource: "Ressources", timeline: "Chronologie", agenda: "Agenda", new_ev: "+ Nouvel evenement", focus: "Temps focus", booking: "Lien de reservation", print: "Imprimer / PDF", settings: "Parametres" },
    es: { today: "Hoy", day: "Dia", week: "Semana", month: "Mes", year: "Ano", resource: "Recursos", timeline: "Linea de tiempo", agenda: "Agenda", new_ev: "+ Nuevo evento", focus: "Tiempo enfoque", booking: "Enlace reserva", print: "Imprimir / PDF", settings: "Ajustes" },
    pt: { today: "Hoje", day: "Dia", week: "Semana", month: "Mes", year: "Ano", resource: "Recursos", timeline: "Linha do tempo", agenda: "Agenda", new_ev: "+ Novo evento", focus: "Foco", booking: "Link de reserva", print: "Imprimir / PDF", settings: "Configuracoes" },
    ru: { today: "Сегодня", day: "День", week: "Неделя", month: "Месяц", year: "Год", resource: "Ресурсы", timeline: "Таймлайн", agenda: "Повестка", new_ev: "+ Событие", focus: "Фокус", booking: "Ссылка брони", print: "Печать / PDF", settings: "Настройки" },
    ja: { today: "今日", day: "日", week: "週", month: "月", year: "年", resource: "リソース", timeline: "タイムライン", agenda: "予定表", new_ev: "+ 新規予定", focus: "集中時間", booking: "予約リンク", print: "印刷 / PDF", settings: "設定" },
    ko: { today: "오늘", day: "일", week: "주", month: "월", year: "년", resource: "리소스", timeline: "타임라인", agenda: "일정", new_ev: "+ 새 일정", focus: "집중 시간", booking: "예약 링크", print: "인쇄 / PDF", settings: "설정" },
    zh: { today: "今天", day: "日", week: "周", month: "月", year: "年", resource: "资源", timeline: "时间线", agenda: "议程", new_ev: "+ 新建日程", focus: "专注时间", booking: "预约链接", print: "打印 / PDF", settings: "设置" },
  };

  function _calT(key, fallback) {
    if (window.archonI18n && typeof window.archonI18n.t === "function") {
      const tr = window.archonI18n.t(key, "");
      if (tr && tr !== key) return tr;
    }
    const lang = (localStorage.getItem("archon_locale") || navigator.language || "de").slice(0, 2).toLowerCase();
    const shortKey = key.split(".").pop();
    if (CAL_I18N[lang] && CAL_I18N[lang][shortKey]) return CAL_I18N[lang][shortKey];
    return fallback;
  }

  function _escCal(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function toIsoDate(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  function addDays(d, n) {
    const c = new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
    return c;
  }

  function startOfWeek(d) {
    const wd = (d.getDay() + 6) % 7; // Mo=0 .. So=6
    return addDays(d, -wd);
  }

  function getISOWeek(d) {
    const dt = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
    const dayNum = dt.getUTCDay() || 7;
    dt.setUTCDate(dt.getUTCDate() + 4 - dayNum);
    const yearStart = new Date(Date.UTC(dt.getUTCFullYear(), 0, 1));
    return Math.ceil(((dt - yearStart) / 86400000 + 1) / 7);
  }

  function parseMinutes(hhmm) {
    if (!hhmm || !hhmm.includes(":")) return null;
    const [h, m] = hhmm.split(":").map(Number);
    if (Number.isNaN(h) || Number.isNaN(m)) return null;
    return h * 60 + m;
  }

  function fmtMinutes(min) {
    const clamped = Math.max(0, Math.min(23 * 60 + 59, Math.round(min)));
    return `${String(Math.floor(clamped / 60)).padStart(2, "0")}:${String(clamped % 60).padStart(2, "0")}`;
  }

  const OFFLINE_Q_KEY = "archon_cal_offline_queue_v1";
  function _getOfflineQueue() {
    try { return JSON.parse(localStorage.getItem(OFFLINE_Q_KEY) || "[]") || []; } catch (_) { return []; }
  }
  function _saveOfflineQueue(q) {
    try { localStorage.setItem(OFFLINE_Q_KEY, JSON.stringify(q)); } catch (_) {}
    const badge = document.getElementById("cal-offline-badge");
    if (badge) {
      badge.textContent = q.length ? `${q.length} Offline-Sync ausstehend` : "";
      badge.classList.toggle("hidden", !q.length);
    }
  }
  async function flushOfflineQueue() {
    const q = _getOfflineQueue();
    if (!q.length || !navigator.onLine) return;
    const remaining = [];
    for (const item of q) {
      try {
        const res = await fetch(item.url, {
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", ...(item.opts?.headers || {}) },
          ...(item.opts || {}),
        });
        if (!res.ok && res.status >= 500) remaining.push(item);
      } catch (_) {
        remaining.push(item);
      }
    }
    _saveOfflineQueue(remaining);
  }
  window.addEventListener("online", () => { flushOfflineQueue().then(() => reloadCalendarData().catch(() => {})); });

  async function api(url, opts) {
    const method = String(opts?.method || "GET").toUpperCase();
    try {
      const res = await fetch(url, {
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...(opts?.headers || {}) },
        ...(opts || {}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      return data;
    } catch (err) {
      const isNet = !navigator.onLine || err instanceof TypeError;
      if (isNet && method !== "GET" && url.startsWith("/api/v1/calendar/events")) {
        const q = _getOfflineQueue();
        q.push({ url, opts, ts: Date.now() });
        _saveOfflineQueue(q);
        return { status: "queued", offline_queued: true };
      }
      throw err;
    }
  }

  function layerForEvent(ev) {
    if (ev.source === "custom" && ev.category === "focus") return "focus";
    return ev.source || "custom";
  }

  function colorForEvent(ev) {
    if (ev.color) return ev.color;
    const map = {
      custom: "#6366f1",
      focus: "#10b981",
      kanban: "#f59e0b",
      workflow: "#a855f7",
      n8n: "#a855f7",
      erp: "#f43f5e",
      external: "#0ea5e9",
      holiday: "#64748b",
      school_holiday: "#14b8a6",
    };
    return map[layerForEvent(ev)] || "#6366f1";
  }

  function visibleEvents() {
    const q = (_searchQuery || "").trim().toLowerCase();
    return (_allEvents || []).filter((ev) => {
      const layer = layerForEvent(ev);
      if (_activeLayers[layer] === false) return false;
      if (_catFilter !== "all" && layer !== _catFilter && ev.category !== _catFilter) return false;
      if (q) {
        const hay = `${ev.title || ""} ${ev.notes || ""} ${ev.attendees || ""} ${ev.location || ""} ${ev.resource || ""} ${ev.category || ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }

  function getEventRangeMinutes(ev) {
    const sTime = ev.time || ((ev.start || "").includes("T") ? ev.start.slice(11, 16) : "");
    const eTime = (ev.end || "").includes("T") ? ev.end.slice(11, 16) : "";
    const sMin = parseMinutes(sTime);
    if (sMin === null || ev.all_day) return null;
    let eMin = parseMinutes(eTime);
    if (eMin === null || eMin <= sMin) eMin = sMin + 60;
    return { startMin: sMin, endMin: eMin };
  }

  // Spalten-Algorithmus fuer ueberlappende Termine (wie Outlook / Google Calendar)
  function layoutDayTimedEvents(dayEvents) {
    const items = dayEvents
      .map((ev) => {
        const rng = getEventRangeMinutes(ev);
        return rng ? { ev, start: rng.startMin, end: rng.endMin, col: 0, totalCols: 1 } : null;
      })
      .filter(Boolean)
      .sort((a, b) => a.start - b.start || a.end - b.end);

    const clusters = [];
    let curCluster = [];
    let clusterEnd = -1;
    items.forEach((it) => {
      if (!curCluster.length || it.start < clusterEnd) {
        curCluster.push(it);
        clusterEnd = Math.max(clusterEnd, it.end);
      } else {
        clusters.push(curCluster);
        curCluster = [it];
        clusterEnd = it.end;
      }
    });
    if (curCluster.length) clusters.push(curCluster);

    clusters.forEach((cl) => {
      const colEnds = [];
      cl.forEach((it) => {
        let placed = -1;
        for (let c = 0; c < colEnds.length; c++) {
          if (colEnds[c] <= it.start) {
            placed = c;
            colEnds[c] = it.end;
            break;
          }
        }
        if (placed === -1) {
          placed = colEnds.length;
          colEnds.push(it.end);
        }
        it.col = placed;
      });
      const total = Math.max(1, colEnds.length);
      cl.forEach((it) => (it.totalCols = total));
    });

    return items;
  }

  function getDateWindow() {
    if (_viewMode === "day" || _viewMode === "resource" || (_viewMode === "timeline" && _timelineSpan === "day")) {
      const iso = toIsoDate(_cursorDate);
      return { startIso: iso, endIso: iso };
    }
    if (_viewMode === "week" || (_viewMode === "timeline" && _timelineSpan === "week")) {
      const s = startOfWeek(_cursorDate);
      return { startIso: toIsoDate(s), endIso: toIsoDate(addDays(s, 6)) };
    }
    if (_viewMode === "month") {
      const first = new Date(_cursorDate.getFullYear(), _cursorDate.getMonth(), 1);
      const gridStart = startOfWeek(first);
      return { startIso: toIsoDate(gridStart), endIso: toIsoDate(addDays(gridStart, 41)) };
    }
    if (_viewMode === "year") {
      const y = _cursorDate.getFullYear();
      return { startIso: `${y}-01-01`, endIso: `${y}-12-31` };
    }
    // list (30 Tage ab Cursor)
    return { startIso: toIsoDate(_cursorDate), endIso: toIsoDate(addDays(_cursorDate, 30)) };
  }

  function renderMiniCalendar() {
    const el = document.getElementById("cal-mini-month");
    if (!el) return;
    const y = _miniDate.getFullYear();
    const m = _miniDate.getMonth();
    const first = new Date(y, m, 1);
    const startOffset = (first.getDay() + 6) % 7;
    const daysInMonth = new Date(y, m + 1, 0).getDate();
    const todayIso = toIsoDate(new Date());
    const selIso = toIsoDate(_cursorDate);

    let cells = "";
    for (let i = 0; i < startOffset; i++) cells += `<span></span>`;
    for (let d = 1; d <= daysInMonth; d++) {
      const iso = `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      const isToday = iso === todayIso;
      const isSel = iso === selIso;
      cells += `<button type="button" data-mini-day="${iso}" class="w-6 h-6 rounded-full text-[11px] font-mono flex items-center justify-center transition ${
        isToday
          ? "bg-indigo-600 text-white font-bold"
          : isSel
          ? "border border-indigo-400 text-indigo-300 font-bold"
          : "hover:bg-[var(--secondary)] text-[var(--foreground)]"
      }">${d}</button>`;
    }

    el.innerHTML = `
      <div class="flex items-center justify-between mb-1.5">
        <span class="text-xs font-bold">${MONTHS_DE[m]} ${y}</span>
        <div class="flex gap-1">
          <button type="button" id="cal-mini-prev" class="px-1.5 py-0.5 rounded hover:bg-[var(--secondary)] text-xs">‹</button>
          <button type="button" id="cal-mini-next" class="px-1.5 py-0.5 rounded hover:bg-[var(--secondary)] text-xs">›</button>
        </div>
      </div>
      <div class="grid grid-cols-7 gap-0.5 text-center text-[10px] font-mono text-[var(--muted-foreground)] mb-1">
        ${DAYS_SHORT.map((x) => `<span>${x}</span>`).join("")}
      </div>
      <div class="grid grid-cols-7 gap-0.5 justify-items-center">${cells}</div>
    `;

    el.querySelector("#cal-mini-prev").onclick = () => {
      _miniDate = new Date(y, m - 1, 1);
      renderMiniCalendar();
    };
    el.querySelector("#cal-mini-next").onclick = () => {
      _miniDate = new Date(y, m + 1, 1);
      renderMiniCalendar();
    };
    el.querySelectorAll("[data-mini-day]").forEach((b) => {
      b.onclick = () => {
        const [yy, mm, dd] = b.getAttribute("data-mini-day").split("-").map(Number);
        _cursorDate = new Date(yy, mm - 1, dd);
        reloadCalendarData();
      };
    });
  }

  function renderTimeGrid(daysList) {
    const prefs = getPrefs();
    const minH = Math.max(0, Math.min(12, prefs.slotMinHour || 6));
    const maxH = Math.max(minH + 4, Math.min(24, prefs.slotMaxHour || 22));
    const totalHours = maxH - minH;
    const gridH = totalHours * HOUR_PX;
    const todayIso = toIsoDate(new Date());
    const evs = visibleEvents();

    const headerCols = daysList
      .map((d) => {
        const iso = toIsoDate(d);
        const isToday = iso === todayIso;
        return `<div class="flex-1 min-w-[110px] px-2 py-1.5 text-center border-l border-[var(--border)] ${isToday ? "bg-indigo-500/10" : ""}">
          <div class="text-[10px] font-mono uppercase text-[var(--muted-foreground)]">${DAYS_SHORT[(d.getDay() + 6) % 7]}</div>
          <div class="text-xs font-bold ${isToday ? "text-indigo-400" : ""}">${d.getDate()}.${d.getMonth() + 1}.</div>
        </div>`;
      })
      .join("");

    const allDayRow = daysList
      .map((d) => {
        const iso = toIsoDate(d);
        const allDayEvs = evs.filter((e) => e.date === iso && !getEventRangeMinutes(e));
        return `<div class="flex-1 min-w-[110px] p-1 border-l border-[var(--border)] space-y-0.5 min-h-[28px]" data-drop-day="${iso}">
          ${allDayEvs
            .map(
              (e) => `<button type="button" data-ev-id="${_escCal(e.id)}" style="background:${colorForEvent(e)};"
                class="w-full text-left px-1.5 py-0.5 rounded text-[10px] font-semibold text-white truncate block">${_escCal(e.title)}</button>`
            )
            .join("")}
        </div>`;
      })
      .join("");

    const bizStart = prefs.businessStartHour ?? 9;
    const bizEnd = prefs.businessEndHour ?? 18;
    const secTz = prefs.secondaryTz && prefs.secondaryTz !== "none" ? prefs.secondaryTz : "";
    const axisW = secTz ? 88 : 58;
    const secTzShort = secTz ? secTz.split("/").pop().replace(/_/g, " ").slice(0, 6) : "";
    let secFmt = null;
    if (secTz) {
      try {
        secFmt = new Intl.DateTimeFormat("de-DE", { timeZone: secTz, hour: "2-digit", minute: "2-digit" });
      } catch (_) {
        secFmt = null;
      }
    }
    const baseDay = daysList[0] || new Date();
    let hoursAxis = "";
    let hourLines = "";
    for (let h = minH; h < maxH; h++) {
      const top = (h - minH) * HOUR_PX;
      const offHours = h < bizStart || h >= bizEnd ? "bg-black/[0.08]" : "";
      let secLabel = "";
      if (secFmt) {
        const dt = new Date(baseDay.getFullYear(), baseDay.getMonth(), baseDay.getDate(), h, 0, 0);
        secLabel = `<span class="text-[9px] text-indigo-400/80 ml-1">${secFmt.format(dt)}</span>`;
      }
      hoursAxis += `<div style="position:absolute;top:${top - 7}px;right:6px;" class="text-[10px] font-mono text-[var(--muted-foreground)] whitespace-nowrap">${String(h).padStart(2, "0")}:00${secLabel}</div>`;
      hourLines += `<div style="position:absolute;top:${top}px;left:0;right:0;height:${HOUR_PX}px;" class="border-t border-[var(--border)]/60 ${offHours}"></div>`;
    }

    const now = new Date();
    const nowMin = now.getHours() * 60 + now.getMinutes();
    const showNow = nowMin >= minH * 60 && nowMin <= maxH * 60;
    const nowTop = ((nowMin - minH * 60) / 60) * HOUR_PX;

    const dayColumns = daysList
      .map((d) => {
        const iso = toIsoDate(d);
        const dayEvs = evs.filter((e) => e.date === iso);
        const isHoliday = dayEvs.some((e) => e.source === "holiday" || e.category === "holiday");
        const isSchoolHoliday = dayEvs.some((e) => e.source === "school_holiday" || e.category === "school_holiday");
        const laidOut = layoutDayTimedEvents(dayEvs);
        const cards = laidOut
          .map(({ ev, start, end, col, totalCols }) => {
            const clampedStart = Math.max(minH * 60, start);
            const clampedEnd = Math.min(maxH * 60, Math.max(clampedStart + 20, end));
            const top = ((clampedStart - minH * 60) / 60) * HOUR_PX;
            const height = Math.max(22, ((clampedEnd - clampedStart) / 60) * HOUR_PX - 2);
            const leftPct = (col / totalCols) * 100;
            const widthPct = 100 / totalCols;
            const editable = ev.source === "custom";
            return `
              <div data-ev-id="${_escCal(ev.id)}" data-ev-day="${iso}" data-start-min="${start}" data-end-min="${end}"
                style="position:absolute;top:${top}px;height:${height}px;left:calc(${leftPct}% + 2px);width:calc(${widthPct}% - 4px);background:${colorForEvent(ev)};z-index:10;"
                class="rounded-lg px-1.5 py-1 text-white shadow-xs overflow-hidden select-none ${editable ? "cursor-grab" : "cursor-pointer opacity-95"}">
                <div class="text-[9px] font-mono opacity-90 leading-none pointer-events-none">${fmtMinutes(start)}–${fmtMinutes(end)}</div>
                <div class="text-[11px] font-semibold leading-tight line-clamp-2 pointer-events-none">${_escCal(ev.title)}</div>
                ${editable ? `<div data-resize-id="${_escCal(ev.id)}" style="position:absolute;left:0;right:0;bottom:0;height:6px;cursor:ns-resize;" class="hover:bg-white/30"></div>` : ""}
              </div>`;
          })
          .join("");

        const colBg = isHoliday ? "bg-amber-500/[0.06]" : isSchoolHoliday ? "bg-teal-500/[0.05]" : iso === todayIso ? "bg-indigo-500/[0.03]" : "";
        return `
          <div class="flex-1 min-w-[110px] relative border-l border-[var(--border)] ${colBg}"
            data-slot-day="${iso}" style="height:${gridH}px;">
            ${hourLines}
            ${iso === todayIso && showNow ? `<div style="position:absolute;top:${nowTop}px;left:0;right:0;height:2px;background:#ef4444;z-index:20;pointer-events:none;"><span style="position:absolute;left:-4px;top:-3px;width:8px;height:8px;border-radius:99px;background:#ef4444;"></span></div>` : ""}
            ${cards}
          </div>`;
      })
      .join("");

    return `
      <div class="flex flex-col flex-1 min-h-0 overflow-hidden">
        <div class="flex border-b border-[var(--border)] bg-[var(--card)] shrink-0">
          <div style="width:${axisW}px;flex-shrink:0;" class="text-[10px] font-mono text-[var(--muted-foreground)] flex flex-col items-center justify-center leading-tight">
            <span>KW ${getISOWeek(daysList[0])}</span>
            ${secTzShort ? `<span class="text-[8px] text-indigo-400/80">${_escCal(secTzShort)}</span>` : ""}
          </div>
          <div class="flex flex-1 min-w-0">${headerCols}</div>
        </div>
        <div class="flex border-b border-[var(--border)] bg-[var(--page-bg)] shrink-0">
          <div style="width:${axisW}px;flex-shrink:0;" class="text-[9px] font-mono text-[var(--muted-foreground)] flex items-center justify-center">Tag</div>
          <div class="flex flex-1 min-w-0">${allDayRow}</div>
        </div>
        <div id="cal-grid-scroll" class="flex-1 min-h-0 overflow-auto relative bg-[var(--page-bg)]">
          <div class="flex" style="min-height:${gridH}px;">
            <div style="width:${axisW}px;flex-shrink:0;height:${gridH}px;" class="relative bg-[var(--card)]">${hoursAxis}</div>
            <div class="flex flex-1 min-w-0 relative">${dayColumns}</div>
          </div>
        </div>
      </div>`;
  }

  function eventsOnDay(evs, iso) {
    return evs.filter((e) => {
      const s = String(e.date || "").slice(0, 10);
      const en = String(e.end || "").slice(0, 10);
      if (!s) return false;
      if (en && en > s) return iso >= s && iso <= en;
      return s === iso;
    });
  }

  function renderMonthGrid() {
    const prefs = getPrefs();
    const dayCount = prefs.showWeekends === false ? 5 : 7;
    const first = new Date(_cursorDate.getFullYear(), _cursorDate.getMonth(), 1);
    const gridStart = startOfWeek(first);
    const curMonth = _cursorDate.getMonth();
    const todayIso = toIsoDate(new Date());
    const evs = visibleEvents();

    let rowsHtml = "";
    for (let w = 0; w < 6; w++) {
      const weekStart = addDays(gridStart, w * 7);
      let cells = `<div style="width:34px;flex-shrink:0;" class="border-r border-b border-[var(--border)] text-[10px] font-mono text-[var(--muted-foreground)] flex items-start justify-center pt-1.5 bg-[var(--card)]">${getISOWeek(weekStart)}</div>`;
      for (let d = 0; d < dayCount; d++) {
        const day = addDays(weekStart, d);
        const iso = toIsoDate(day);
        const inMonth = day.getMonth() === curMonth;
        const isToday = iso === todayIso;
        const dayEvs = eventsOnDay(evs, iso);
        const shown = dayEvs.slice(0, 3);
        const extra = dayEvs.length - shown.length;

        cells += `
          <div data-month-day="${iso}" class="flex-1 min-w-0 border-r border-b border-[var(--border)] p-1 flex flex-col gap-0.5 overflow-hidden cursor-pointer hover:bg-[var(--secondary)]/30 ${
            inMonth ? "bg-[var(--page-bg)]" : "bg-[var(--card)]/40 opacity-60"
          }">
            <div class="flex items-center justify-between">
              <span class="text-[11px] font-mono px-1.5 py-0.5 rounded-full ${isToday ? "bg-indigo-600 text-white font-bold" : ""}">${day.getDate()}</span>
            </div>
            ${shown
              .map((e) => {
                const isMulti = e.end && String(e.end).slice(0, 10) > String(e.date || "").slice(0, 10);
                const mark = isMulti ? (iso === e.date ? "▶ " : iso === String(e.end).slice(0, 10) ? "◀ " : "↔ ") : "";
                return `<button type="button" data-ev-id="${_escCal(e.id)}" draggable="${e.source === "custom" && !e.parent_id}"
                  style="background:${colorForEvent(e)};"
                  class="w-full text-left px-1.5 py-0.5 rounded text-[10px] font-semibold text-white truncate">${mark}${e.time && !isMulti ? `${e.time} ` : ""}${_escCal(e.title)}</button>`;
              })
              .join("")}
            ${extra > 0 ? `<button type="button" data-more-day="${iso}" class="text-left text-[9px] font-mono text-indigo-400 hover:underline px-1">+${extra} weitere</button>` : ""}
          </div>`;
      }
      rowsHtml += `<div class="flex flex-1 min-h-[92px]">${cells}</div>`;
    }

    return `
      <div class="flex flex-col flex-1 min-h-0 overflow-auto relative">
        <div class="flex border-b border-[var(--border)] bg-[var(--card)] shrink-0">
          <div style="width:34px;flex-shrink:0;" class="py-1.5 text-center text-[10px] font-mono text-[var(--muted-foreground)] border-r border-[var(--border)]">KW</div>
          ${DAYS_SHORT.slice(0, dayCount).map((n) => `<div class="flex-1 py-1.5 text-center text-[11px] font-mono font-bold text-[var(--muted-foreground)] border-r border-[var(--border)]">${n}</div>`).join("")}
        </div>
        <div class="flex-1 flex flex-col min-h-0">${rowsHtml}</div>
        <div id="cal-more-popover" class="hidden fixed z-50 bg-[var(--card)] border border-[var(--border)] rounded-xl shadow-2xl p-3 w-72 max-h-72 overflow-y-auto space-y-1.5"></div>
      </div>`;
  }

  function renderYearGrid() {
    const y = _cursorDate.getFullYear();
    const todayIso = toIsoDate(new Date());
    const counts = {};
    visibleEvents().forEach((e) => {
      if (e.date) counts[e.date] = (counts[e.date] || 0) + 1;
    });

    const cards = MONTHS_DE.map((mName, m) => {
      const first = new Date(y, m, 1);
      const offset = (first.getDay() + 6) % 7;
      const days = new Date(y, m + 1, 0).getDate();
      let cells = "";
      for (let i = 0; i < offset; i++) cells += `<span></span>`;
      for (let d = 1; d <= days; d++) {
        const iso = `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
        const has = counts[iso] || 0;
        const isToday = iso === todayIso;
        cells += `<button type="button" data-year-day="${iso}" class="w-6 h-6 rounded text-[10px] font-mono flex flex-col items-center justify-center relative ${
          isToday ? "bg-indigo-600 text-white font-bold" : "hover:bg-[var(--secondary)]"
        }">${d}${has ? `<span style="width:4px;height:4px;border-radius:99px;background:${isToday ? "#fff" : "#6366f1"};position:absolute;bottom:1px;"></span>` : ""}</button>`;
      }
      return `
        <div class="p-2.5 rounded-xl border border-[var(--border)] bg-[var(--card)] space-y-1.5">
          <div class="text-xs font-bold text-center">${mName}</div>
          <div class="grid grid-cols-7 gap-0.5 text-center text-[9px] font-mono text-[var(--muted-foreground)]">${DAYS_SHORT.map((x) => `<span>${x}</span>`).join("")}</div>
          <div class="grid grid-cols-7 gap-0.5 justify-items-center">${cells}</div>
        </div>`;
    }).join("");

    return `<div class="flex-1 min-h-0 overflow-y-auto p-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">${cards}</div>`;
  }

  function renderAgendaList() {
    const evs = visibleEvents().slice().sort((a, b) => (a.date + (a.time || "")).localeCompare(b.date + (b.time || "")));
    if (!evs.length) {
      return `<div class="p-8 text-center text-xs text-[var(--muted-foreground)]">Keine Termine im ausgewaehlten Zeitraum.</div>`;
    }
    return `
      <div class="flex-1 min-h-0 overflow-y-auto p-3 space-y-2">
        ${evs
          .map(
            (e) => `
          <button type="button" data-ev-id="${_escCal(e.id)}" class="w-full text-left p-2.5 rounded-xl border border-[var(--border)] bg-[var(--card)] hover:border-indigo-400/60 flex items-center justify-between gap-3 text-xs">
            <div class="flex items-center gap-2.5 min-w-0">
              <span class="w-2.5 h-2.5 rounded-full shrink-0" style="background:${colorForEvent(e)}"></span>
              <span class="font-mono text-[11px] text-[var(--muted-foreground)] shrink-0">${_escCal(e.date)} ${e.time ? _escCal(e.time) : "Ganztaegig"}</span>
              <span class="font-semibold truncate">${_escCal(e.title)}</span>
            </div>
            <span class="text-[10px] font-mono px-2 py-0.5 rounded border border-[var(--border)] shrink-0">${_escCal(e.source)}</span>
          </button>`
          )
          .join("")}
      </div>`;
  }

  function renderResourceColumnsView() {
    const prefs = getPrefs();
    const minH = Math.max(0, Math.min(12, prefs.slotMinHour || 6));
    const maxH = Math.max(minH + 4, Math.min(24, prefs.slotMaxHour || 22));
    const totalHours = maxH - minH;
    const gridH = totalHours * HOUR_PX;
    const iso = toIsoDate(_cursorDate);
    const evs = visibleEvents().filter((e) => e.date === iso);
    const cols = [..._resources, "Ohne Ressource"];

    let hoursAxis = "";
    let hourLines = "";
    for (let h = minH; h < maxH; h++) {
      const top = (h - minH) * HOUR_PX;
      hoursAxis += `<div style="position:absolute;top:${top - 7}px;right:8px;" class="text-[10px] font-mono text-[var(--muted-foreground)]">${String(h).padStart(2, "0")}:00</div>`;
      hourLines += `<div style="position:absolute;top:${top}px;left:0;right:0;height:${HOUR_PX}px;" class="border-t border-[var(--border)]/60"></div>`;
    }

    const headerCols = cols
      .map((r) => `<div class="flex-1 min-w-[140px] px-2 py-2 text-center border-l border-[var(--border)] text-xs font-bold truncate">${_escCal(r)}</div>`)
      .join("");

    const resCols = cols
      .map((resName) => {
        const isUnassigned = resName === "Ohne Ressource";
        const colEvs = evs.filter((e) => {
          const rVal = String(e.resource || "").trim();
          return isUnassigned ? !rVal : rVal === resName;
        });
        const laidOut = layoutDayTimedEvents(colEvs);
        const cards = laidOut
          .map(({ ev, start, end, col, totalCols }) => {
            const cS = Math.max(minH * 60, start);
            const cE = Math.min(maxH * 60, Math.max(cS + 20, end));
            const top = ((cS - minH * 60) / 60) * HOUR_PX;
            const height = Math.max(22, ((cE - cS) / 60) * HOUR_PX - 2);
            const leftPct = (col / totalCols) * 100;
            const widthPct = 100 / totalCols;
            const draggable = ev.source === "custom" ? `data-res-ev="1" data-start-min="${start}" data-end-min="${end}"` : "";
            return `<div data-ev-id="${_escCal(ev.id)}" ${draggable} style="position:absolute;top:${top}px;height:${height}px;left:calc(${leftPct}% + 2px);width:calc(${widthPct}% - 4px);background:${colorForEvent(ev)};z-index:10;" class="rounded-lg px-1.5 py-1 text-white shadow-xs overflow-hidden ${ev.source === "custom" ? "cursor-grab" : "cursor-pointer"}">
              <div class="text-[9px] font-mono opacity-90 pointer-events-none">${fmtMinutes(start)}–${fmtMinutes(end)}</div>
              <div class="text-[11px] font-semibold leading-tight truncate pointer-events-none">${_escCal(ev.title)}</div>
            </div>`;
          })
          .join("");
        return `<div class="flex-1 min-w-[140px] relative border-l border-[var(--border)]" data-res-col="${_escCal(isUnassigned ? "" : resName)}" data-res-day="${iso}" style="height:${gridH}px;">
          ${hourLines}
          ${cards}
        </div>`;
      })
      .join("");

    return `
      <div class="flex flex-col flex-1 min-h-0 overflow-hidden">
        <div class="flex border-b border-[var(--border)] bg-[var(--card)] shrink-0">
          <div style="width:58px;flex-shrink:0;" class="text-[10px] font-mono text-[var(--muted-foreground)] flex items-center justify-center">Zeit</div>
          <div class="flex flex-1 min-w-0 overflow-x-auto">${headerCols}</div>
        </div>
        <div class="flex-1 min-h-0 overflow-auto relative bg-[var(--page-bg)]">
          <div class="flex" style="min-height:${gridH}px;">
            <div style="width:58px;flex-shrink:0;height:${gridH}px;" class="relative bg-[var(--card)]">${hoursAxis}</div>
            <div class="flex flex-1 min-w-0 relative">${resCols}</div>
          </div>
        </div>
      </div>`;
  }

  function renderTimelineView() {
    const prefs = getPrefs();
    const minH = Math.max(0, Math.min(12, prefs.slotMinHour || 6));
    const maxH = Math.max(minH + 4, Math.min(24, prefs.slotMaxHour || 22));
    const totalMin = (maxH - minH) * 60;
    const iso = toIsoDate(_cursorDate);
    const rows = [..._resources, "Ohne Ressource"];
    const spanCtrl = `<div class="px-3 py-1.5 border-b border-[var(--border)] bg-[var(--card)] flex items-center justify-between text-xs">
      <span class="font-mono text-[11px] text-[var(--muted-foreground)]">Gantt-Zeitleiste (${_timelineSpan === "week" ? "7 Tage" : "Tag"})</span>
      <button type="button" id="cal-tl-span-btn" class="px-2.5 py-1 rounded-lg border border-[var(--border)] hover:bg-[var(--secondary)] text-[11px] font-semibold">
        ${_timelineSpan === "week" ? "Auf Tages-Stunden wechseln" : "Auf 7-Tage-Woche wechseln"}
      </button>
    </div>`;

    if (_timelineSpan === "week") {
      const s = startOfWeek(_cursorDate);
      const weekDays = Array.from({ length: 7 }, (_, i) => addDays(s, i));
      const allEvs = visibleEvents();
      const dayHeaders = weekDays
        .map((d) => `<div class="flex-1 min-w-[110px] text-center text-[10px] font-mono py-1.5 border-l border-[var(--border)]">${DAYS_SHORT[(d.getDay() + 6) % 7]} ${d.getDate()}.${d.getMonth() + 1}.</div>`)
        .join("");
      const rowHtml = rows
        .map((resName) => {
          const isUnassigned = resName === "Ohne Ressource";
          const cells = weekDays
            .map((d) => {
              const dIso = toIsoDate(d);
              const dEvs = allEvs.filter((e) => {
                const rVal = String(e.resource || "").trim();
                return e.date === dIso && (isUnassigned ? !rVal : rVal === resName);
              });
              const chips = dEvs
                .map((ev) => `<button type="button" data-ev-id="${_escCal(ev.id)}" style="background:${colorForEvent(ev)};" class="w-full text-left px-1.5 py-0.5 rounded text-[10px] text-white font-semibold truncate block">${ev.time ? _escCal(ev.time) + " " : ""}${_escCal(ev.title)}</button>`)
                .join("");
              return `<div class="flex-1 min-w-[110px] p-1 border-l border-[var(--border)]/60 space-y-0.5" data-tl-week-day="${dIso}" data-tl-week-res="${_escCal(isUnassigned ? "" : resName)}">${chips}</div>`;
            })
            .join("");
          return `<div class="flex border-b border-[var(--border)] min-h-[54px] bg-[var(--page-bg)]">
            <div style="width:170px;flex-shrink:0;" class="px-3 py-2 text-xs font-semibold border-r border-[var(--border)] bg-[var(--card)] flex items-center truncate">${_escCal(resName)}</div>
            <div class="flex-1 flex">${cells}</div>
          </div>`;
        })
        .join("");

      return `<div class="flex flex-col flex-1 min-h-0 overflow-auto">${spanCtrl}
        <div class="flex border-b border-[var(--border)] bg-[var(--card)] shrink-0">
          <div style="width:170px;flex-shrink:0;" class="px-3 py-1.5 text-[10px] font-mono uppercase text-[var(--muted-foreground)] border-r border-[var(--border)] flex items-center">Ressource / Raum</div>
          <div class="flex-1 flex">${dayHeaders}</div>
        </div>
        <div class="flex-1">${rowHtml}</div>
      </div>`;
    }

    const evs = visibleEvents().filter((e) => e.date === iso);
    const hourHeaders = [];
    for (let h = minH; h < maxH; h++) {
      hourHeaders.push(`<div class="flex-1 min-w-[54px] text-center text-[10px] font-mono text-[var(--muted-foreground)] py-1.5 border-l border-[var(--border)]">${String(h).padStart(2, "0")}:00</div>`);
    }

    const rowHtml = rows
      .map((resName) => {
        const isUnassigned = resName === "Ohne Ressource";
        const rEvs = evs.filter((e) => {
          const rVal = String(e.resource || "").trim();
          return isUnassigned ? !rVal : rVal === resName;
        });
        const bars = rEvs
          .map((ev) => {
            const rng = getEventRangeMinutes(ev);
            if (!rng) return "";
            const s = Math.max(minH * 60, rng.startMin);
            const e = Math.min(maxH * 60, Math.max(s + 15, rng.endMin));
            const leftPct = ((s - minH * 60) / totalMin) * 100;
            const widthPct = Math.max(2, ((e - s) / totalMin) * 100);
            return `<button type="button" data-ev-id="${_escCal(ev.id)}" style="position:absolute;top:6px;bottom:6px;left:${leftPct}%;width:${widthPct}%;background:${colorForEvent(ev)};" class="rounded-lg px-2 text-left text-white text-[11px] font-semibold truncate shadow-xs hover:brightness-110">
              ${fmtMinutes(rng.startMin)} ${_escCal(ev.title)}
            </button>`;
          })
          .join("");
        return `
          <div class="flex border-b border-[var(--border)] min-h-[48px] bg-[var(--page-bg)]">
            <div style="width:170px;flex-shrink:0;" class="px-3 py-2 text-xs font-semibold border-r border-[var(--border)] bg-[var(--card)] flex items-center truncate">${_escCal(resName)}</div>
            <div class="flex-1 relative flex" data-tl-res="${_escCal(isUnassigned ? "" : resName)}" data-tl-day="${iso}">
              ${Array.from({ length: maxH - minH }, () => `<div class="flex-1 min-w-[54px] border-l border-[var(--border)]/40"></div>`).join("")}
              ${bars}
            </div>
          </div>`;
      })
      .join("");

    return `
      <div class="flex flex-col flex-1 min-h-0 overflow-auto">${spanCtrl}
        <div class="flex border-b border-[var(--border)] bg-[var(--card)] shrink-0">
          <div style="width:170px;flex-shrink:0;" class="px-3 py-1.5 text-[10px] font-mono uppercase text-[var(--muted-foreground)] border-r border-[var(--border)] flex items-center">Ressource / Raum</div>
          <div class="flex-1 flex">${hourHeaders.join("")}</div>
        </div>
        <div class="flex-1">${rowHtml}</div>
      </div>`;
  }

  function renderMainStage() {
    const stage = document.getElementById("archon-calendar-stage");
    const titleEl = document.getElementById("cal-toolbar-title");
    if (!stage) return;

    if (titleEl) {
      if (_viewMode === "year") titleEl.textContent = `${_cursorDate.getFullYear()}`;
      else if (_viewMode === "day" || _viewMode === "resource" || _viewMode === "timeline") {
        titleEl.textContent = `${_cursorDate.getDate()}. ${MONTHS_DE[_cursorDate.getMonth()]} ${_cursorDate.getFullYear()}`;
      } else if (_viewMode === "week") {
        const s = startOfWeek(_cursorDate);
        const e = addDays(s, 6);
        titleEl.textContent = `${s.getDate()}.${s.getMonth() + 1}. – ${e.getDate()}.${e.getMonth() + 1}.${e.getFullYear()} (KW ${getISOWeek(s)})`;
      } else {
        titleEl.textContent = `${MONTHS_DE[_cursorDate.getMonth()]} ${_cursorDate.getFullYear()}`;
      }
    }

    document.querySelectorAll("[data-cal-view]").forEach((b) => {
      const active = b.getAttribute("data-cal-view") === _viewMode;
      b.className = `px-2.5 py-1 rounded-lg text-xs font-semibold transition ${
        active ? "bg-indigo-600 text-white" : "border border-[var(--border)] hover:bg-[var(--secondary)]"
      }`;
    });

    if (_viewMode === "day") {
      stage.innerHTML = renderTimeGrid([_cursorDate]);
    } else if (_viewMode === "week") {
      const s = startOfWeek(_cursorDate);
      const dayCount = getPrefs().showWeekends === false ? 5 : 7;
      stage.innerHTML = renderTimeGrid(Array.from({ length: dayCount }, (_, i) => addDays(s, i)));
    } else if (_viewMode === "month") {
      stage.innerHTML = renderMonthGrid();
    } else if (_viewMode === "year") {
      stage.innerHTML = renderYearGrid();
    } else if (_viewMode === "resource") {
      stage.innerHTML = renderResourceColumnsView();
    } else if (_viewMode === "timeline") {
      stage.innerHTML = renderTimelineView();
    } else {
      stage.innerHTML = renderAgendaList();
    }

    bindStageInteractions(stage);
  }

  function bindStageInteractions(stage) {
    // Termin anklicken -> Detail/Edit-Modal
    stage.querySelectorAll("[data-ev-id]").forEach((el) => {
      el.onclick = (ev) => {
        ev.stopPropagation();
        const id = el.getAttribute("data-ev-id");
        const found = _allEvents.find((x) => x.id === id);
        if (found) openEventEditorModal({ event: found });
      };
    });

    // Jahr-Klick -> zum Tag wechseln
    stage.querySelectorAll("[data-year-day]").forEach((b) => {
      b.onclick = () => {
        const [yy, mm, dd] = b.getAttribute("data-year-day").split("-").map(Number);
        _cursorDate = new Date(yy, mm - 1, dd);
        _viewMode = "day";
        reloadCalendarData();
      };
    });

    // Monat: Klick auf Tag -> neuer Termin | Drag & Drop zwischen Tagen
    stage.querySelectorAll("[data-month-day]").forEach((cell) => {
      const iso = cell.getAttribute("data-month-day");
      cell.onclick = () => openEventEditorModal({ startStr: `${iso}T09:00`, endStr: `${iso}T10:00` });
      cell.ondragover = (e) => e.preventDefault();
      cell.ondrop = async (e) => {
        e.preventDefault();
        const evId = e.dataTransfer.getData("text/plain");
        const found = _allEvents.find((x) => x.id === evId);
        if (!found || found.source !== "custom") return;
        const start = found.time ? `${iso}T${found.time}` : iso;
        await api(`/api/v1/calendar/events/${encodeURIComponent(found.parent_id || found.id)}`, {
          method: "PATCH",
          body: JSON.stringify({ start, date: iso }),
        });
        await reloadCalendarData();
      };
    });
    stage.querySelectorAll("[draggable='true'][data-ev-id]").forEach((b) => {
      b.ondragstart = (e) => e.dataTransfer.setData("text/plain", b.getAttribute("data-ev-id"));
    });

    // "+N weitere" Popover im Monat
    stage.querySelectorAll("[data-more-day]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const iso = btn.getAttribute("data-more-day");
        const pop = document.getElementById("cal-more-popover");
        if (!pop) return;
        const dayEvs = eventsOnDay(visibleEvents(), iso);
        const rect = btn.getBoundingClientRect();
        pop.style.left = Math.min(window.innerWidth - 300, rect.left) + "px";
        pop.style.top = Math.min(window.innerHeight - 280, rect.bottom + 4) + "px";
        pop.classList.remove("hidden");
        pop.innerHTML = `
          <div class="flex items-center justify-between border-b border-[var(--border)] pb-1">
            <span class="text-xs font-bold font-mono">${_escCal(iso)} (${dayEvs.length})</span>
            <button type="button" id="cal-more-close" class="text-xs px-1.5 rounded hover:bg-[var(--secondary)]">✕</button>
          </div>
          ${dayEvs
            .map(
              (ev) => `<button type="button" data-pop-ev="${_escCal(ev.id)}" style="background:${colorForEvent(ev)};"
                class="w-full text-left px-2 py-1 rounded text-[11px] font-semibold text-white truncate">${ev.time ? `${ev.time} ` : ""}${_escCal(ev.title)}</button>`
            )
            .join("")}
        `;
        pop.querySelector("#cal-more-close").onclick = () => pop.classList.add("hidden");
        pop.querySelectorAll("[data-pop-ev]").forEach((b) => {
          b.onclick = () => {
            pop.classList.add("hidden");
            const f = _allEvents.find((x) => x.id === b.getAttribute("data-pop-ev"));
            if (f) openEventEditorModal({ event: f });
          };
        });
      };
    });

    // Zeitraster: Bereich mit Maus aufziehen (15-Min-Raster) oder einfacher Klick
    const prefs = getPrefs();
    const minH = prefs.slotMinHour || 6;

    stage.querySelectorAll("[data-slot-day]").forEach((col) => {
      const iso = col.getAttribute("data-slot-day");
      col.onmousedown = (e) => {
        if (e.button !== 0 || e.target.closest("[data-ev-id]")) return;
        e.preventDefault();
        const rect = col.getBoundingClientRect();
        const yToMin = (clientY) => minH * 60 + Math.max(0, Math.round((((clientY - rect.top) / HOUR_PX) * 60) / 15) * 15);
        const anchorMin = yToMin(e.clientY);
        let curMin = anchorMin + 30;
        let dragged = false;

        const box = document.createElement("div");
        box.style.cssText = "position:absolute;left:3px;right:3px;background:rgba(99,102,241,0.35);border:1.5px solid #6366f1;border-radius:8px;z-index:25;pointer-events:none;padding:2px 6px;font-size:10px;font-family:monospace;color:#fff;";
        col.appendChild(box);

        const updateBox = (sM, eM) => {
          const top = ((sM - minH * 60) / 60) * HOUR_PX;
          const h = Math.max(18, ((eM - sM) / 60) * HOUR_PX);
          box.style.top = top + "px";
          box.style.height = h + "px";
          box.textContent = `${fmtMinutes(sM)} – ${fmtMinutes(eM)}`;
        };
        updateBox(anchorMin, anchorMin + 30);

        const onMove = (mv) => {
          dragged = true;
          curMin = yToMin(mv.clientY);
          const sM = Math.min(anchorMin, curMin);
          const eM = Math.max(sM + 15, Math.max(anchorMin, curMin));
          updateBox(sM, eM);
        };
        const onUp = () => {
          window.removeEventListener("mousemove", onMove);
          window.removeEventListener("mouseup", onUp);
          box.remove();
          const sM = dragged ? Math.min(anchorMin, curMin) : Math.floor(anchorMin / 30) * 30;
          const eM = dragged ? Math.max(sM + 15, Math.max(anchorMin, curMin)) : sM + 60;
          openEventEditorModal({ startStr: `${iso}T${fmtMinutes(sM)}`, endStr: `${iso}T${fmtMinutes(eM)}` });
        };
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
      };
    });

    // Resize am unteren Rand
    stage.querySelectorAll("[data-resize-id]").forEach((handle) => {
      handle.onmousedown = (ev) => {
        ev.stopPropagation();
        ev.preventDefault();
        const evId = handle.getAttribute("data-resize-id");
        const card = handle.closest("[data-ev-id]");
        const found = _allEvents.find((x) => x.id === evId);
        if (!card || !found) return;
        const startY = ev.clientY;
        const origH = card.offsetHeight;
        const origStartMin = Number(card.getAttribute("data-start-min"));
        const origEndMin = Number(card.getAttribute("data-end-min"));
        let newEndMin = origEndMin;

        const onMove = (mv) => {
          const dy = mv.clientY - startY;
          const deltaMin = Math.round(((dy / HOUR_PX) * 60) / 15) * 15;
          newEndMin = Math.max(origStartMin + 15, origEndMin + deltaMin);
          card.style.height = Math.max(20, origH + (deltaMin / 60) * HOUR_PX) + "px";
        };
        const onUp = async () => {
          window.removeEventListener("mousemove", onMove);
          window.removeEventListener("mouseup", onUp);
          if (newEndMin !== origEndMin) {
            let occDate = "";
            if (found.parent_id) {
              occDate = confirm("Nur diese Termin-Instanz aendern?\nOK = Nur diesen Termin | Abbrechen = Gesamte Serie") ? found.date : "";
            }
            await api(`/api/v1/calendar/events/${encodeURIComponent(found.parent_id || found.id)}`, {
              method: "PATCH",
              body: JSON.stringify({
                end: `${found.date}T${fmtMinutes(newEndMin)}`,
                ...(occDate ? { occurrence_date: occDate } : {}),
              }),
            });
            await reloadCalendarData();
          }
        };
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
      };
    });

    // Drag & Drop im Zeitraster (innerhalb des Tages oder auf andere Tagesspalte)
    stage.querySelectorAll("[data-ev-id][data-start-min]").forEach((card) => {
      const evId = card.getAttribute("data-ev-id");
      const found = _allEvents.find((x) => x.id === evId);
      if (!found || found.source !== "custom") return;

      card.onmousedown = (ev) => {
        if (ev.target.closest("[data-resize-id]")) return;
        const startX = ev.clientX;
        const startY = ev.clientY;
        const origTop = parseFloat(card.style.top) || 0;
        const origStartMin = Number(card.getAttribute("data-start-min"));
        const durationMin = Math.max(15, Number(card.getAttribute("data-end-min")) - origStartMin);
        let moved = false;
        let targetDay = found.date;
        let newStartMin = origStartMin;

        const onMove = (mv) => {
          const dx = mv.clientX - startX;
          const dy = mv.clientY - startY;
          if (Math.abs(dx) > 4 || Math.abs(dy) > 4) moved = true;
          if (!moved) return;
          const deltaMin = Math.round(((dy / HOUR_PX) * 60) / 15) * 15;
          newStartMin = Math.max(minH * 60, Math.min(23 * 60, origStartMin + deltaMin));
          card.style.top = Math.max(0, origTop + (deltaMin / 60) * HOUR_PX) + "px";
          const under = document.elementFromPoint(mv.clientX, mv.clientY)?.closest("[data-slot-day]");
          if (under) targetDay = under.getAttribute("data-slot-day");
        };

        const onUp = async () => {
          window.removeEventListener("mousemove", onMove);
          window.removeEventListener("mouseup", onUp);
          if (moved) {
            let occDate = "";
            if (found.parent_id) {
              occDate = confirm("Nur diese Termin-Instanz verschieben?\nOK = Nur diesen Termin | Abbrechen = Gesamte Serie") ? found.date : "";
            }
            await api(`/api/v1/calendar/events/${encodeURIComponent(found.parent_id || found.id)}`, {
              method: "PATCH",
              body: JSON.stringify({
                date: targetDay,
                time: fmtMinutes(newStartMin),
                start: `${targetDay}T${fmtMinutes(newStartMin)}`,
                end: `${targetDay}T${fmtMinutes(newStartMin + durationMin)}`,
                ...(occDate ? { occurrence_date: occDate } : {}),
              }),
            });
            await reloadCalendarData();
          }
        };
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
      };
    });

    // Timeline Span Toggle (Tag / 7 Tage) & Klick auf leeren Ressourcen-Slot
    const tlBtn = stage.querySelector("#cal-tl-span-btn");
    if (tlBtn) {
      tlBtn.onclick = () => {
        _timelineSpan = _timelineSpan === "week" ? "day" : "week";
        reloadCalendarData();
      };
    }

    stage.querySelectorAll("[data-res-col]").forEach((col) => {
      col.onclick = (e) => {
        if (e.target.closest("[data-ev-id]")) return;
        const rect = col.getBoundingClientRect();
        const sM = minH * 60 + Math.max(0, Math.floor((((e.clientY - rect.top) / HOUR_PX) * 60) / 30) * 30);
        const day = col.getAttribute("data-res-day") || toIsoDate(_cursorDate);
        const resName = col.getAttribute("data-res-col") || "";
        openEventEditorModal({ startStr: `${day}T${fmtMinutes(sM)}`, endStr: `${day}T${fmtMinutes(sM + 60)}`, resource: resName });
      };
    });

    stage.querySelectorAll("[data-tl-week-day]").forEach((cell) => {
      cell.onclick = (e) => {
        if (e.target.closest("[data-ev-id]")) return;
        const day = cell.getAttribute("data-tl-week-day");
        const resName = cell.getAttribute("data-tl-week-res") || "";
        openEventEditorModal({ startStr: `${day}T09:00`, endStr: `${day}T10:00`, resource: resName });
      };
    });

    // Drag & Drop zwischen Ressourcen-Spalten
    stage.querySelectorAll('[data-res-ev="1"]').forEach((card) => {
      const evId = card.getAttribute("data-ev-id");
      const found = _allEvents.find((x) => x.id === evId);
      if (!found || found.source !== "custom") return;
      card.onmousedown = (ev) => {
        const startX = ev.clientX;
        const startY = ev.clientY;
        const origTop = parseFloat(card.style.top) || 0;
        const origStartMin = Number(card.getAttribute("data-start-min"));
        const durationMin = Math.max(15, Number(card.getAttribute("data-end-min")) - origStartMin);
        let moved = false;
        let targetRes = found.resource || "";
        let newStartMin = origStartMin;

        const onMove = (mv) => {
          if (Math.abs(mv.clientX - startX) > 4 || Math.abs(mv.clientY - startY) > 4) moved = true;
          if (!moved) return;
          const deltaMin = Math.round(((mv.clientY - startY) / HOUR_PX) * 60 / 15) * 15;
          newStartMin = Math.max(minH * 60, Math.min(23 * 60, origStartMin + deltaMin));
          card.style.top = Math.max(0, origTop + (deltaMin / 60) * HOUR_PX) + "px";
          const under = document.elementFromPoint(mv.clientX, mv.clientY)?.closest("[data-res-col]");
          if (under) targetRes = under.getAttribute("data-res-col") || "";
        };

        const onUp = async () => {
          window.removeEventListener("mousemove", onMove);
          window.removeEventListener("mouseup", onUp);
          if (!moved) return;
          try {
            await api(`/api/v1/calendar/events/${encodeURIComponent(found.parent_id || found.id)}`, {
              method: "PATCH",
              body: JSON.stringify({
                resource: targetRes,
                date: found.date,
                time: fmtMinutes(newStartMin),
                start: `${found.date}T${fmtMinutes(newStartMin)}`,
                end: `${found.date}T${fmtMinutes(newStartMin + durationMin)}`,
                ...(found.parent_id ? { occurrence_date: found.date } : {}),
              }),
            });
            await reloadCalendarData();
          } catch (err) {
            alert(err.message);
            renderMainStage();
          }
        };
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
      };
    });

    // Mobile Touch-Gesten: Horizontaler Swipe zum Blaettern + Touch-Drag fuer Termine
    if (!stage.dataset.touchBound) {
      stage.dataset.touchBound = "1";
      let swX = 0, swY = 0;
      stage.addEventListener("touchstart", (e) => {
        if (e.touches.length !== 1 || e.target.closest("[data-ev-id]")) return;
        swX = e.touches[0].clientX;
        swY = e.touches[0].clientY;
      }, { passive: true });
      stage.addEventListener("touchend", (e) => {
        if (!swX || e.changedTouches.length !== 1) return;
        const dx = e.changedTouches[0].clientX - swX;
        const dy = e.changedTouches[0].clientY - swY;
        swX = 0;
        if (Math.abs(dx) > 75 && Math.abs(dy) < 45) {
          stepCursor(dx < 0 ? 1 : -1);
        }
      }, { passive: true });
    }
    stage.querySelectorAll("[data-ev-id][data-start-min]").forEach((card) => {
      const evId = card.getAttribute("data-ev-id");
      const found = _allEvents.find((x) => x.id === evId);
      if (!found || found.source !== "custom") return;
      card.ontouchstart = (ev) => {
        if (ev.touches.length !== 1) return;
        const t0Y = ev.touches[0].clientY;
        const origTop = parseFloat(card.style.top) || 0;
        const origStartMin = Number(card.getAttribute("data-start-min"));
        const durationMin = Math.max(15, Number(card.getAttribute("data-end-min")) - origStartMin);
        let newStartMin = origStartMin;
        let moved = false;
        const onTMove = (mv) => {
          const dy = mv.touches[0].clientY - t0Y;
          if (Math.abs(dy) > 8) moved = true;
          if (!moved) return;
          mv.preventDefault();
          const dMin = Math.round(((dy / HOUR_PX) * 60) / 15) * 15;
          newStartMin = Math.max(minH * 60, Math.min(23 * 60, origStartMin + dMin));
          card.style.top = Math.max(0, origTop + (dMin / 60) * HOUR_PX) + "px";
        };
        const onTEnd = async () => {
          card.removeEventListener("touchmove", onTMove);
          card.removeEventListener("touchend", onTEnd);
          if (!moved) return;
          await api(`/api/v1/calendar/events/${encodeURIComponent(found.parent_id || found.id)}`, {
            method: "PATCH",
            body: JSON.stringify({
              date: found.date,
              time: fmtMinutes(newStartMin),
              start: `${found.date}T${fmtMinutes(newStartMin)}`,
              end: `${found.date}T${fmtMinutes(newStartMin + durationMin)}`,
              ...(found.parent_id ? { occurrence_date: found.date } : {}),
            }),
          }).catch(() => {});
          await reloadCalendarData();
        };
        card.addEventListener("touchmove", onTMove, { passive: false });
        card.addEventListener("touchend", onTEnd, { once: true });
      };
    });
  }

  function renderExternalSourcesList(targetId) {
    const listEl = document.getElementById(targetId);
    if (!listEl) return;
    if (!_sources.length) {
      listEl.innerHTML = `<div class="text-[10px] text-[var(--muted-foreground)]">Keine externen Kalender verbunden.</div>`;
      return;
    }
    listEl.innerHTML = _sources
      .map(
        (s) => `
      <div class="p-1.5 rounded-lg border border-[var(--border)] bg-[var(--page-bg)] flex items-center justify-between gap-1 text-[11px]">
        <div class="min-w-0">
          <div class="font-semibold truncate">${_escCal(s.name)}</div>
          <div class="text-[9px] font-mono text-[var(--muted-foreground)] truncate">${_escCal(s.provider)} · ${s.event_count || 0} Termine</div>
        </div>
        <div class="flex items-center gap-1 shrink-0">
          <button type="button" data-sync-src="${_escCal(s.id)}" title="Jetzt synchronisieren" class="px-1.5 py-0.5 rounded border border-[var(--border)] hover:bg-[var(--secondary)] text-[10px]">↻</button>
          <button type="button" data-del-src="${_escCal(s.id)}" title="Entfernen" class="text-rose-400 hover:text-rose-300 text-xs">✕</button>
        </div>
      </div>`
      )
      .join("");

    listEl.querySelectorAll("[data-sync-src]").forEach((b) => {
      b.onclick = async () => {
        b.textContent = "…";
        try {
          await api(`/api/v1/calendar/sources/${encodeURIComponent(b.getAttribute("data-sync-src"))}/sync`, { method: "POST" });
          await reloadCalendarData();
        } catch (err) {
          alert(err.message);
        }
      };
    });
    listEl.querySelectorAll("[data-del-src]").forEach((b) => {
      b.onclick = async () => {
        await api(`/api/v1/calendar/sources/${encodeURIComponent(b.getAttribute("data-del-src"))}`, { method: "DELETE" });
        await reloadCalendarData();
      };
    });
  }

  function ensureEventEditorModal() {
    let modal = document.getElementById("cal-event-editor-modal");
    if (!modal) {
      modal = document.createElement("div");
      modal.id = "cal-event-editor-modal";
      modal.className = "hidden fixed inset-0 z-50 bg-black/60 backdrop-blur-xs flex items-center justify-center p-4";
      document.body.appendChild(modal);
    }
    return modal;
  }

  function openEventEditorModal(opts = {}) {
    const existing = opts.event || null;
    const isEdit = Boolean(existing && existing.id && existing.source === "custom");
    const modal = ensureEventEditorModal();

    const startVal = existing?.start
      ? existing.start.slice(0, 16)
      : opts.startStr
      ? opts.startStr.slice(0, 16)
      : `${toIsoDate(_cursorDate)}T09:00`;
    const endVal = existing?.end
      ? existing.end.slice(0, 16)
      : opts.endStr
      ? opts.endStr.slice(0, 16)
      : `${startVal.slice(0, 10)}T10:00`;

    modal.classList.remove("hidden");
    modal.innerHTML = `
      <div class="bg-[var(--card)] text-[var(--foreground)] border border-[var(--border)] rounded-2xl w-[94vw] max-w-lg p-4 shadow-2xl space-y-3 text-xs">
        <div class="flex items-center justify-between border-b border-[var(--border)] pb-2">
          <h3 class="text-sm font-bold">${isEdit ? "Termin bearbeiten" : existing ? "Termindetails" : "Neuer Termin"}</h3>
          <button type="button" id="cal-ed-close" class="px-2 py-1 rounded hover:bg-[var(--secondary)]">✕</button>
        </div>
        <div class="space-y-2">
          <input id="cal-ed-title" value="${_escCal(existing?.title || "")}" placeholder="Titel (z. B. Kunden-Call / Fokuszeit)" class="w-full px-2.5 py-1.5 rounded border border-[var(--border)] bg-[var(--page-bg)] font-semibold" />
          <div class="grid grid-cols-2 gap-2">
            <label class="space-y-0.5">
              <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Start</span>
              <input id="cal-ed-start" type="datetime-local" value="${_escCal(startVal.includes("T") ? startVal : `${startVal}T09:00`)}" class="w-full px-2 py-1 rounded border border-[var(--border)] bg-[var(--page-bg)] font-mono" />
            </label>
            <label class="space-y-0.5">
              <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Ende</span>
              <input id="cal-ed-end" type="datetime-local" value="${_escCal(endVal.includes("T") ? endVal : `${endVal}T10:00`)}" class="w-full px-2 py-1 rounded border border-[var(--border)] bg-[var(--page-bg)] font-mono" />
            </label>
          </div>
          <div class="grid grid-cols-3 gap-2">
            <label class="space-y-0.5">
              <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Kategorie</span>
              <select id="cal-ed-cat" class="w-full px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--page-bg)]">
                <option value="appointment" ${existing?.category === "appointment" ? "selected" : ""}>Termin / Meeting</option>
                <option value="focus" ${existing?.category === "focus" ? "selected" : ""}>Deep-Work / Fokusblock</option>
                <option value="deadline" ${existing?.category === "deadline" ? "selected" : ""}>Frist / Meilenstein</option>
              </select>
            </label>
            <label class="space-y-0.5">
              <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Wiederholung</span>
              <select id="cal-ed-rec" class="w-full px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--page-bg)]">
                <option value="none" ${!existing?.recurrence || existing?.recurrence === "none" ? "selected" : ""}>Keine</option>
                <option value="daily" ${existing?.recurrence === "daily" ? "selected" : ""}>Taeglich</option>
                <option value="weekly" ${existing?.recurrence === "weekly" ? "selected" : ""}>Woechentlich</option>
                <option value="monthly" ${existing?.recurrence === "monthly" ? "selected" : ""}>Monatlich</option>
              </select>
            </label>
            <label class="space-y-0.5">
              <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Erinnerung</span>
              <select id="cal-ed-rem" class="w-full px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--page-bg)]">
                <option value="0" ${Number(existing?.reminder_min || 0) === 0 ? "selected" : ""}>Aus</option>
                <option value="5" ${Number(existing?.reminder_min) === 5 ? "selected" : ""}>5 Min vorher</option>
                <option value="15" ${(existing?.reminder_min === undefined || Number(existing?.reminder_min) === 15) ? "selected" : ""}>15 Min vorher</option>
                <option value="30" ${Number(existing?.reminder_min) === 30 ? "selected" : ""}>30 Min vorher</option>
                <option value="60" ${Number(existing?.reminder_min) === 60 ? "selected" : ""}>60 Min vorher</option>
              </select>
            </label>
          </div>
          <div id="cal-ed-rec-extra" class="${existing?.recurrence && existing.recurrence !== "none" ? "" : "hidden"} p-2 rounded-lg border border-[var(--border)] bg-[var(--page-bg)] space-y-1.5">
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Tage (bei woechentlich):</span>
              ${DAYS_SHORT.map((lbl, idx) => `<label class="flex items-center gap-1 text-[11px] cursor-pointer"><input type="checkbox" data-rec-day="${idx}" ${(existing?.recurrence_days || []).includes(idx) ? "checked" : ""} />${lbl}</label>`).join("")}
            </div>
            <label class="flex items-center gap-2 text-[11px]">
              <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Serie bis (optional):</span>
              <input id="cal-ed-rec-until" type="date" value="${_escCal(existing?.recurrence_until || "")}" class="px-2 py-0.5 rounded border border-[var(--border)] bg-[var(--card)] font-mono" />
            </label>
          </div>
          <div class="grid grid-cols-3 gap-2">
            <input id="cal-ed-loc" value="${_escCal(existing?.location || "")}" placeholder="Ort / Adresse" class="px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--page-bg)]" />
            <input id="cal-ed-url" value="${_escCal(existing?.meeting_url || "")}" placeholder="Meeting-Link (Zoom/Teams/Meet)" class="px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--page-bg)]" />
            <select id="cal-ed-resource" class="px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--page-bg)]">
              <option value="">Keine Ressource</option>
              ${_resources.map((r) => `<option value="${_escCal(r)}" ${(existing?.resource || opts?.resource) === r ? "selected" : ""}>${_escCal(r)}</option>`).join("")}
            </select>
          </div>
          <div class="flex gap-2 items-center">
            <input id="cal-ed-att" value="${_escCal(existing?.attendees || "")}" placeholder="Teilnehmer (E-Mails kommagetrennt)" class="flex-1 px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--page-bg)]" />
            <button type="button" id="cal-ed-findtime-btn" class="px-2.5 py-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 text-[11px] font-semibold shrink-0">Find a Time</button>
          </div>
          <div id="cal-ed-findtime-panel" class="hidden p-2 rounded-lg border border-[var(--border)] bg-[var(--page-bg)] space-y-2 text-[11px]"></div>
          <div id="cal-ed-conflict" class="hidden p-2 rounded-lg border border-rose-500/40 bg-rose-500/10 text-rose-200 text-[11px] space-y-1">
            <div id="cal-ed-conflict-msg"></div>
            <label class="flex items-center gap-1.5 cursor-pointer"><input type="checkbox" id="cal-ed-allow-conflict" /><span>Trotzdem buchen (Doppelbelegung erlauben)</span></label>
          </div>
          ${isEdit && (existing?.attendees || "").trim() ? `
          <div class="p-2 rounded-lg border border-[var(--border)] bg-[var(--page-bg)] space-y-1.5">
            <div class="flex items-center justify-between gap-2">
              <span class="text-[10px] font-mono uppercase text-[var(--muted-foreground)]">Einladungen & RSVP-Status (Klick zum Wechseln)</span>
              <button type="button" id="cal-ed-invite-btn" class="px-2 py-0.5 rounded bg-indigo-500/20 hover:bg-indigo-500/30 border border-indigo-500/40 text-indigo-300 text-[10px] font-semibold">Einladung (.ics) senden</button>
            </div>
            <div id="cal-ed-rsvp-list" class="flex flex-wrap gap-1.5"></div>
          </div>` : ""}
          ${existing?.parent_id ? `
          <label class="flex items-center gap-2 p-2 rounded-lg border border-amber-500/30 bg-amber-500/10 text-amber-200 cursor-pointer text-[11px]">
            <input type="checkbox" id="cal-ed-only-this" checked />
            <span>Nur diesen Serientermin (<strong>${_escCal(existing.date)}</strong>) aendern oder loeschen</span>
          </label>` : ""}
          <label class="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" id="cal-ed-allday" ${existing?.all_day ? "checked" : ""} />
            <span>Ganztaegig</span>
          </label>
          <textarea id="cal-ed-notes" rows="2" placeholder="Notizen / Agenda" class="w-full px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--page-bg)]">${_escCal(existing?.notes || "")}</textarea>
        </div>
        <div class="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-[var(--border)]">
          <div class="flex items-center gap-1.5">
            ${isEdit ? `<button type="button" id="cal-ed-del" class="px-3 py-1.5 rounded-lg border border-rose-500/40 text-rose-400 hover:bg-rose-500/10">Loeschen</button>` : ""}
            ${isEdit && _sources.some((s) => ["caldav", "google_oauth", "outlook_oauth"].includes(s.provider)) ? `<button type="button" id="cal-ed-push" class="px-2.5 py-1.5 rounded-lg border border-sky-500/40 bg-sky-500/10 hover:bg-sky-500/20 text-sky-300 text-[11px] font-semibold">Extern schreiben</button>` : ""}
          </div>
          <div class="flex gap-2">
            <button type="button" id="cal-ed-cancel" class="px-3 py-1.5 rounded-lg border border-[var(--border)] hover:bg-[var(--secondary)]">Schliessen</button>
            ${!existing || isEdit ? `<button type="button" id="cal-ed-save" class="px-4 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold">Speichern</button>` : ""}
          </div>
        </div>
      </div>`;

    const close = () => modal.classList.add("hidden");
    modal.querySelector("#cal-ed-close").onclick = close;
    modal.querySelector("#cal-ed-cancel").onclick = close;

    const rsvpListEl = modal.querySelector("#cal-ed-rsvp-list");
    if (rsvpListEl && isEdit) {
      const rsvpState = { ...(existing.rsvp_status || {}) };
      const colors = {
        pending: "border-slate-500/40 text-slate-300",
        accepted: "border-emerald-500/50 bg-emerald-500/15 text-emerald-300",
        declined: "border-rose-500/50 bg-rose-500/15 text-rose-300",
        tentative: "border-amber-500/50 bg-amber-500/15 text-amber-300",
      };
      const order = ["pending", "accepted", "declined", "tentative"];
      const renderRsvpPills = () => {
        const emails = String(existing.attendees || "").split(",").map((x) => x.trim()).filter(Boolean);
        rsvpListEl.innerHTML = emails
          .map((em) => {
            const st = rsvpState[em] || "pending";
            return `<button type="button" data-rsvp-email="${_escCal(em)}" class="px-2 py-0.5 rounded border text-[10px] font-mono ${colors[st] || colors.pending}">${_escCal(em)}: <strong>${st}</strong></button>`;
          })
          .join("");
        rsvpListEl.querySelectorAll("[data-rsvp-email]").forEach((btn) => {
          btn.onclick = async () => {
            const em = btn.getAttribute("data-rsvp-email");
            const cur = rsvpState[em] || "pending";
            const next = order[(order.indexOf(cur) + 1) % order.length];
            rsvpState[em] = next;
            renderRsvpPills();
            await api(`/api/v1/calendar/events/${encodeURIComponent(existing.parent_id || existing.id)}/rsvp`, {
              method: "POST",
              body: JSON.stringify({ email: em, status: next }),
            }).catch(() => {});
          };
        });
      };
      renderRsvpPills();

      const invBtn = modal.querySelector("#cal-ed-invite-btn");
      if (invBtn) {
        invBtn.onclick = async () => {
          try {
            const res = await api(`/api/v1/calendar/events/${encodeURIComponent(existing.parent_id || existing.id)}/invite`, {
              method: "POST",
            });
            alert(`${(res.sent || []).length} .ics-Einladung(en) im E-Mail-Postausgang erstellt.`);
          } catch (err) {
            alert(err.message);
          }
        };
      }
    }

    const pushBtn = modal.querySelector("#cal-ed-push");
    if (pushBtn && isEdit) {
      pushBtn.onclick = async () => {
        const writable = _sources.find((s) => ["caldav", "google_oauth", "outlook_oauth"].includes(s.provider));
        if (!writable) return alert("Keine beschreibbare Sync-Quelle gefunden.");
        try {
          await api(`/api/v1/calendar/events/${encodeURIComponent(existing.parent_id || existing.id)}/push`, {
            method: "POST",
            body: JSON.stringify({ source_id: writable.id }),
          });
          alert(`Termin erfolgreich an '${writable.name}' gesendet.`);
        } catch (err) {
          alert(err.message);
        }
      };
    }

    const recSel = modal.querySelector("#cal-ed-rec");
    const recExtra = modal.querySelector("#cal-ed-rec-extra");
    if (recSel && recExtra) {
      recSel.onchange = () => recExtra.classList.toggle("hidden", recSel.value === "none");
    }

    const checkConflictUI = async () => {
      const resVal = modal.querySelector("#cal-ed-resource")?.value || "";
      const st = modal.querySelector("#cal-ed-start")?.value || "";
      const en = modal.querySelector("#cal-ed-end")?.value || "";
      const box = modal.querySelector("#cal-ed-conflict");
      const msg = modal.querySelector("#cal-ed-conflict-msg");
      if (!box || !msg) return;
      if (!resVal || !st) { box.classList.add("hidden"); return; }
      try {
        const res = await api(`/api/v1/calendar/check-conflict?resource=${encodeURIComponent(resVal)}&date=${encodeURIComponent(st.slice(0, 10))}&start=${encodeURIComponent(st)}&end=${encodeURIComponent(en)}&exclude_id=${encodeURIComponent(existing?.parent_id || existing?.id || "")}`);
        if (res.has_conflict && res.conflicts?.length) {
          msg.textContent = `Ressourcen-Konflikt: '${resVal}' ist bereits belegt (${res.conflicts[0].title} ${res.conflicts[0].time || ""}).`;
          box.classList.remove("hidden");
        } else {
          box.classList.add("hidden");
        }
      } catch (_) {}
    };
    ["#cal-ed-resource", "#cal-ed-start", "#cal-ed-end"].forEach((sel) => {
      const el = modal.querySelector(sel);
      if (el) el.addEventListener("change", checkConflictUI);
    });
    checkConflictUI();

    const ftBtn = modal.querySelector("#cal-ed-findtime-btn");
    const ftPanel = modal.querySelector("#cal-ed-findtime-panel");
    if (ftBtn && ftPanel) {
      ftBtn.onclick = async () => {
        ftPanel.classList.toggle("hidden");
        if (ftPanel.classList.contains("hidden")) return;
        const dStr = (modal.querySelector("#cal-ed-start")?.value || toIsoDate(_cursorDate)).slice(0, 10);
        const attRaw = modal.querySelector("#cal-ed-att")?.value || "";
        const resVal = modal.querySelector("#cal-ed-resource")?.value || "";
        const list = [resVal, ...attRaw.split(",").map((x) => x.trim())].filter(Boolean);
        ftPanel.innerHTML = `<div class="text-[var(--muted-foreground)]">Pruefe Team-Verfuegbarkeit fuer ${dStr}...</div>`;
        try {
          const data = await api(`/api/v1/calendar/free-busy?date=${encodeURIComponent(dStr)}&resources=${encodeURIComponent(list.join(","))}&duration_min=30`);
          const busyHtml = Object.entries(data.busy || {})
            .map(([name, slots]) => `<div><strong>${_escCal(name)}:</strong> ${slots.length ? slots.map((s) => `<span class="text-rose-300 font-mono">${s.start}–${s.end}</span>`).join(", ") : `<span class="text-emerald-400">Komplett frei</span>`}</div>`)
            .join("");
          const freeHtml = (data.common_free_slots || []).slice(0, 8)
            .map((s) => `<button type="button" data-ft-start="${_escCal(s.start)}" data-ft-end="${_escCal(s.end)}" class="px-2 py-0.5 rounded bg-emerald-500/20 hover:bg-emerald-500/35 border border-emerald-500/40 text-emerald-300 font-mono text-[10px]">${_escCal(s.label)}</button>`)
            .join("");
          ftPanel.innerHTML = `${busyHtml}<div class="pt-1 border-t border-[var(--border)] flex flex-wrap gap-1 items-center"><span class="text-[10px] font-mono text-[var(--muted-foreground)] mr-1">Gemeinsam frei:</span>${freeHtml || "Keine"}</div>`;
          ftPanel.querySelectorAll("[data-ft-start]").forEach((b) => {
            b.onclick = () => {
              modal.querySelector("#cal-ed-start").value = b.getAttribute("data-ft-start");
              modal.querySelector("#cal-ed-end").value = b.getAttribute("data-ft-end");
            };
          });
        } catch (err) {
          ftPanel.innerHTML = `<div class="text-rose-400">${_escCal(err.message)}</div>`;
        }
      };
    }

    const saveBtn = modal.querySelector("#cal-ed-save");
    if (saveBtn) {
      saveBtn.onclick = async () => {
        const title = modal.querySelector("#cal-ed-title").value.trim();
        if (!title) return alert("Bitte Titel eingeben.");
        const start = modal.querySelector("#cal-ed-start").value;
        const end = modal.querySelector("#cal-ed-end").value;
        const all_day = modal.querySelector("#cal-ed-allday").checked;
        const recDays = [];
        modal.querySelectorAll("[data-rec-day]").forEach((c) => {
          if (c.checked) recDays.push(Number(c.getAttribute("data-rec-day")));
        });
        const payload = {
          title,
          start: all_day ? start.slice(0, 10) : start,
          end: all_day ? end.slice(0, 10) : end,
          date: start.slice(0, 10),
          time: all_day ? "" : start.slice(11, 16),
          all_day,
          category: modal.querySelector("#cal-ed-cat").value,
          recurrence: modal.querySelector("#cal-ed-rec").value,
          recurrence_days: recDays,
          recurrence_until: modal.querySelector("#cal-ed-rec-until")?.value || "",
          reminder_min: Number(modal.querySelector("#cal-ed-rem")?.value || 15),
          location: modal.querySelector("#cal-ed-loc").value,
          meeting_url: modal.querySelector("#cal-ed-url").value,
          attendees: modal.querySelector("#cal-ed-att").value,
          resource: modal.querySelector("#cal-ed-resource")?.value || "",
          allow_conflict: Boolean(modal.querySelector("#cal-ed-allow-conflict")?.checked),
          notes: modal.querySelector("#cal-ed-notes").value,
        };
        try {
          if (isEdit) {
            const onlyThis = modal.querySelector("#cal-ed-only-this")?.checked;
            if (existing.parent_id && onlyThis) {
              payload.occurrence_date = existing.date;
            }
            await api(`/api/v1/calendar/events/${encodeURIComponent(existing.parent_id || existing.id)}`, {
              method: "PATCH",
              body: JSON.stringify(payload),
            });
          } else {
            await api("/api/v1/calendar/events", { method: "POST", body: JSON.stringify(payload) });
          }
          close();
          await reloadCalendarData();
        } catch (err) {
          alert(err.message);
        }
      };
    }

    const delBtn = modal.querySelector("#cal-ed-del");
    if (delBtn && isEdit) {
      delBtn.onclick = async () => {
        if (!confirm("Termin wirklich loeschen?")) return;
        const onlyThis = modal.querySelector("#cal-ed-only-this")?.checked;
        const qs = existing.parent_id && onlyThis ? `?occurrence_date=${encodeURIComponent(existing.date)}` : "";
        await api(`/api/v1/calendar/events/${encodeURIComponent(existing.parent_id || existing.id)}${qs}`, { method: "DELETE" });
        close();
        await reloadCalendarData();
      };
    }
  }

  async function reloadCalendarData() {
    const { startIso, endIso } = getDateWindow();
    const prefs = getPrefs();
    const hState = encodeURIComponent(prefs.holidayState || "BY");
    const [evRes, srcRes, resRes] = await Promise.all([
      api(`/api/v1/calendar/events?start_date=${encodeURIComponent(startIso)}&end_date=${encodeURIComponent(endIso)}&holiday_state=${hState}`),
      api("/api/v1/calendar/sources").catch(() => ({ sources: [] })),
      api("/api/v1/calendar/resources").catch(() => ({ resources: _resources })),
    ]);
    _allEvents = evRes.events || [];
    _sources = srcRes.sources || [];
    if (Array.isArray(resRes.resources) && resRes.resources.length) _resources = resRes.resources;
    renderMiniCalendar();
    renderExternalSourcesList("cal-ext-sources-list");
    renderExternalSourcesList("cal-set-sources-list");
    renderMainStage();
  }

  function stepCursor(dir) {
    if (_viewMode === "day" || _viewMode === "resource" || _viewMode === "timeline") _cursorDate = addDays(_cursorDate, dir);
    else if (_viewMode === "week") _cursorDate = addDays(_cursorDate, dir * 7);
    else if (_viewMode === "month") _cursorDate = new Date(_cursorDate.getFullYear(), _cursorDate.getMonth() + dir, 1);
    else if (_viewMode === "year") _cursorDate = new Date(_cursorDate.getFullYear() + dir, 0, 1);
    else _cursorDate = addDays(_cursorDate, dir * 14);
    reloadCalendarData();
  }

  function ensureCalendarPrintStyles() {
    if (document.getElementById("cal-print-styles")) return;
    const st = document.createElement("style");
    st.id = "cal-print-styles";
    st.textContent = `
      @media print {
        body > *:not(#app-root), nav, aside, #ops-tabs-bar, #ops-view-calendar aside, #cal-toolbar-actions, #cal-search-bar { display: none !important; }
        #ops-view-calendar { position: static !important; width: 100% !important; height: auto !important; overflow: visible !important; background: #fff !important; color: #000 !important; }
        #archon-calendar-stage, #cal-grid-scroll { overflow: visible !important; height: auto !important; max-height: none !important; }
      }
    `;
    document.head.appendChild(st);
  }

  function bindKeyboardShortcuts() {
    if (window._calKeysBound) return;
    window._calKeysBound = true;
    document.addEventListener("keydown", (e) => {
      const host = document.getElementById("ops-view-calendar");
      if (!host || host.classList.contains("hidden") || !host.offsetParent) return;
      const tag = (e.target?.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select" || e.target?.isContentEditable) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === "t") { _cursorDate = new Date(); _miniDate = new Date(); reloadCalendarData(); }
      else if (k === "d") { _viewMode = "day"; reloadCalendarData(); }
      else if (k === "w") { _viewMode = "week"; reloadCalendarData(); }
      else if (k === "m") { _viewMode = "month"; reloadCalendarData(); }
      else if (k === "y") { _viewMode = "year"; reloadCalendarData(); }
      else if (k === "a") { _viewMode = "list"; reloadCalendarData(); }
      else if (k === "r") { _viewMode = "resource"; reloadCalendarData(); }
      else if (k === "l") { _viewMode = "timeline"; reloadCalendarData(); }
      else if (k === "n") { e.preventDefault(); openEventEditorModal({}); }
      else if (e.key === "ArrowLeft") { stepCursor(-1); }
      else if (e.key === "ArrowRight") { stepCursor(1); }
    });
  }

  function renderCalendarHostShell() {
    const host = document.getElementById("ops-view-calendar");
    if (!host) return false;
    ensureCalendarPrintStyles();
    bindKeyboardShortcuts();
    if (!host.dataset.calMounted) {
      host.dataset.calMounted = "1";
      _viewMode = getPrefs().initialView || "week";

      host.innerHTML = `
        <div class="px-3 py-2 border-b border-[var(--border)] flex flex-wrap items-center justify-between gap-2 shrink-0 bg-[var(--card)]">
          <div class="flex items-center gap-1.5">
            <button type="button" id="cal-nav-prev" title="Zurueck (Pfeil links)" class="px-2 py-1 rounded-lg border border-[var(--border)] hover:bg-[var(--secondary)] text-xs">‹</button>
            <button type="button" id="cal-nav-today" title="Heute (T)" class="px-2.5 py-1 rounded-lg border border-[var(--border)] hover:bg-[var(--secondary)] text-xs font-semibold">${_escCal(_calT("ui.operations_calendar.today", "Heute"))}</button>
            <button type="button" id="cal-nav-next" title="Vor (Pfeil rechts)" class="px-2 py-1 rounded-lg border border-[var(--border)] hover:bg-[var(--secondary)] text-xs">›</button>
            <span id="cal-toolbar-title" class="text-sm font-bold ml-2"></span>
            <span id="cal-offline-badge" class="hidden ml-2 px-2 py-0.5 rounded bg-amber-500/20 border border-amber-500/40 text-amber-300 text-[10px] font-mono"></span>
          </div>

          <div class="flex items-center gap-1">
            <button type="button" data-cal-view="day" title="Tag (D)">${_escCal(_calT("ui.operations_calendar.day", "Tag"))}</button>
            <button type="button" data-cal-view="week" title="Woche (W)">${_escCal(_calT("ui.operations_calendar.week", "Woche"))}</button>
            <button type="button" data-cal-view="month" title="Monat (M)">${_escCal(_calT("ui.operations_calendar.month", "Monat"))}</button>
            <button type="button" data-cal-view="year" title="Jahr (Y)">${_escCal(_calT("ui.operations_calendar.year", "Jahr"))}</button>
            <button type="button" data-cal-view="resource" title="Ressourcen (R)">${_escCal(_calT("ui.operations_calendar.resource", "Ressourcen"))}</button>
            <button type="button" data-cal-view="timeline" title="Zeitleiste (L)">${_escCal(_calT("ui.operations_calendar.timeline", "Zeitleiste"))}</button>
            <button type="button" data-cal-view="list" title="Agenda (A)">${_escCal(_calT("ui.operations_calendar.agenda", "Agenda"))}</button>
            <button type="button" id="cal-toggle-weekends" class="ml-1 px-2 py-1 rounded-lg border border-[var(--border)] hover:bg-[var(--secondary)] text-[11px] font-mono">${getPrefs().showWeekends === false ? "Mo–Fr" : "Mo–So"}</button>
          </div>

          <div id="cal-search-bar" class="flex flex-wrap items-center gap-1.5">
            <input id="cal-quick-add-input" type="text" placeholder="Quick-Add: z. B. Morgen 14 Uhr Call 45 Min (Enter)" class="px-2.5 py-1 rounded-lg border border-emerald-500/40 bg-[var(--page-bg)] text-xs w-64" />
            <input id="cal-search-input" type="search" value="${_escCal(_searchQuery)}" placeholder="Suche..." class="px-2 py-1 rounded-lg border border-[var(--border)] bg-[var(--page-bg)] text-xs w-32" />
            <select id="cal-cat-filter" class="px-2 py-1 rounded-lg border border-[var(--border)] bg-[var(--page-bg)] text-xs">
              <option value="all">Alle Kategorien</option>
              <option value="appointment">Termine</option>
              <option value="focus">Fokuszeit</option>
              <option value="deadline">Fristen / Kanban</option>
              <option value="workflow">Workflows / Cron</option>
              <option value="erp">ERP / Zahlungen</option>
              <option value="external">Externe</option>
              <option value="holiday">Feiertage</option>
              <option value="school_holiday">Schulferien</option>
            </select>
          </div>

          <div id="cal-toolbar-actions" class="flex flex-wrap items-center gap-1.5">
            <button type="button" id="cal-find-focus" class="px-2.5 py-1 rounded-lg border border-emerald-500/40 bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 text-xs font-semibold">${_escCal(_calT("ui.operations_calendar.focus", "Fokuszeit"))}</button>
            <button type="button" id="cal-booking-link-btn" class="px-2.5 py-1 rounded-lg border border-indigo-500/40 bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-300 text-xs font-semibold">${_escCal(_calT("ui.operations_calendar.booking", "Buchungslink"))}</button>
            <button type="button" id="cal-print-btn" class="px-2 py-1 rounded-lg border border-[var(--border)] hover:bg-[var(--secondary)] text-xs">${_escCal(_calT("ui.operations_calendar.print", "Drucken / PDF"))}</button>
            <a href="/api/v1/calendar/export.ics" class="px-2 py-1 rounded-lg border border-[var(--border)] hover:bg-[var(--secondary)] text-xs font-mono">.ics Export</a>
            <button type="button" id="cal-import-ics-btn" class="px-2 py-1 rounded-lg border border-[var(--border)] hover:bg-[var(--secondary)] text-xs font-mono">.ics Import</button>
            <button type="button" id="cal-open-settings-btn" class="px-2 py-1 rounded-lg border border-[var(--border)] hover:bg-[var(--secondary)] text-xs">${_escCal(_calT("ui.operations_calendar.settings", "Einstellungen"))}</button>
          </div>
        </div>

        <div style="display:flex;flex:1;min-height:0;overflow:hidden;">
          <aside style="width:252px;flex-shrink:0;" class="border-r border-[var(--border)] p-3 overflow-y-auto space-y-3 bg-[var(--card)]">
            <button type="button" id="cal-new-btn" title="Neuer Termin (N)" class="w-full px-3 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold shadow-xs">
              ${_escCal(_calT("ui.operations_calendar.new_ev", "+ Neuer Termin"))}
            </button>
            <div id="cal-mini-month" class="p-2 rounded-xl border border-[var(--border)] bg-[var(--page-bg)]"></div>
            <div class="space-y-1.5">
              <div class="text-[10px] font-mono uppercase tracking-wider text-[var(--muted-foreground)]">Kalender-Layer</div>
              ${[
                ["custom", "Termine & Meetings", "#6366f1"],
                ["focus", "Deep-Work / Fokus", "#10b981"],
                ["kanban", "Kanban-Deadlines", "#f59e0b"],
                ["workflow", "Workflow-Cron-Jobs", "#a855f7"],
                ["erp", "ERP / Zahlungen", "#f43f5e"],
                ["external", "Externe Kalender", "#0ea5e9"],
                ["holiday", "Feiertage (Bundesland)", "#64748b"],
                ["school_holiday", "Schulferien (Bundesland)", "#14b8a6"],
              ]
                .map(
                  ([k, lbl, col]) => `
                <label class="flex items-center gap-2 text-xs cursor-pointer">
                  <input type="checkbox" data-cal-layer="${k}" ${_activeLayers[k] ? "checked" : ""} />
                  <span class="w-2.5 h-2.5 rounded-full shrink-0" style="background:${col}"></span>
                  <span class="truncate">${lbl}</span>
                </label>`
                )
                .join("")}
            </div>
            <div class="pt-2 border-t border-[var(--border)] space-y-2">
              <div class="flex items-center justify-between">
                <span class="text-[10px] font-mono uppercase tracking-wider text-[var(--muted-foreground)]">Externe Kalender</span>
                <button type="button" id="cal-add-source-btn" class="text-[11px] text-indigo-400 hover:underline">+ Settings</button>
              </div>
              <div id="cal-ext-sources-list" class="space-y-1.5"></div>
            </div>
          </aside>

          <div id="archon-calendar-stage" style="flex:1;min-width:0;min-height:0;display:flex;flex-direction:column;overflow:hidden;" class="bg-[var(--page-bg)]"></div>
        </div>
      `;

      host.querySelector("#cal-nav-prev").onclick = () => stepCursor(-1);
      host.querySelector("#cal-nav-next").onclick = () => stepCursor(1);
      host.querySelector("#cal-nav-today").onclick = () => {
        _cursorDate = new Date();
        _miniDate = new Date();
        reloadCalendarData();
      };
      host.querySelectorAll("[data-cal-view]").forEach((b) => {
        b.onclick = () => {
          _viewMode = b.getAttribute("data-cal-view");
          reloadCalendarData();
        };
      });
      const wkBtn = host.querySelector("#cal-toggle-weekends");
      if (wkBtn) {
        wkBtn.onclick = () => {
          const next = getPrefs().showWeekends === false;
          savePrefs({ showWeekends: next });
          wkBtn.textContent = next ? "Mo–So" : "Mo–Fr";
          renderMainStage();
        };
      }

      host.querySelector("#cal-new-btn").onclick = () => openEventEditorModal({});
      host.querySelector("#cal-open-settings-btn").onclick = openCalendarSettings;
      host.querySelector("#cal-add-source-btn").onclick = openCalendarSettings;
      host.querySelector("#cal-print-btn").onclick = () => window.print();
      host.querySelector("#cal-booking-link-btn").onclick = () => {
        const slug = encodeURIComponent(getPrefs().bookingSlug || "mein-termin");
        const url = `${window.location.origin}/static/booking.html?slug=${slug}`;
        if (navigator.clipboard?.writeText) {
          navigator.clipboard.writeText(url).catch(() => {});
        }
        window.open(url, "_blank", "noopener");
      };
      host.querySelector("#cal-search-input").oninput = (e) => {
        _searchQuery = e.target.value || "";
        renderMainStage();
      };
      host.querySelector("#cal-quick-add-input").onkeydown = async (e) => {
        if (e.key !== "Enter") return;
        const txt = e.target.value.trim();
        if (!txt) return;
        e.preventDefault();
        try {
          const low = txt.toLowerCase();
          if (low.startsWith("wann") || low.startsWith("welche") || low.startsWith("was steht") || low.startsWith("verschieb")) {
            const res = await api("/api/v1/calendar/nl-query", { method: "POST", body: JSON.stringify({ text: txt }) });
            alert(res.answer || "Erledigt.");
          } else {
            await api("/api/v1/calendar/quick-add", { method: "POST", body: JSON.stringify({ text: txt }) });
          }
          e.target.value = "";
          await reloadCalendarData();
        } catch (err) {
          alert(err.message);
        }
      };
      host.querySelector("#cal-cat-filter").onchange = (e) => {
        _catFilter = e.target.value || "all";
        renderMainStage();
      };

      host.querySelectorAll("[data-cal-layer]").forEach((chk) => {
        chk.onchange = () => {
          const k = chk.getAttribute("data-cal-layer");
          _activeLayers[k] = chk.checked;
          if (k === "workflow") _activeLayers.n8n = chk.checked;
          renderMainStage();
        };
      });

      host.querySelector("#cal-find-focus").onclick = async () => {
        try {
          const prefs = getPrefs();
          const res = await api(`/api/v1/calendar/focus-slots?duration_min=${prefs.focusDuration || 90}&days_ahead=5`);
          const slots = res.slots || [];
          if (!slots.length) return alert("Keine freien Fokus-Slots in den naechsten 5 Werktagen gefunden.");
          const first = slots[0];
          if (confirm(`Freien Fokus-Slot gefunden:\n${first.label}\n\nDirekt als Deep-Work-Block eintragen?`)) {
            await api("/api/v1/calendar/events", {
              method: "POST",
              body: JSON.stringify({
                title: "Deep-Work Fokusblock",
                start: first.start,
                end: first.end,
                date: first.date,
                time: first.start.slice(11, 16),
                category: "focus",
              }),
            });
            await reloadCalendarData();
          }
        } catch (err) {
          alert(err.message);
        }
      };

      host.querySelector("#cal-import-ics-btn").onclick = async () => {
        const txt = prompt(".ics Kalender-Inhalt (BEGIN:VCALENDAR...) hier einfuegen:");
        if (!txt || !txt.trim()) return;
        try {
          const res = await api("/api/v1/calendar/import-ics", {
            method: "POST",
            body: JSON.stringify({ ics_text: txt }),
          });
          alert(`${res.imported || 0} Termine importiert.`);
          await reloadCalendarData();
        } catch (err) {
          alert(err.message);
        }
      };
    }

    reloadCalendarData().catch(() => {});
    return true;
  }

  function openCalendarSettings() {
    if (typeof window.openSystemSettingsModal === "function") {
      window.openSystemSettingsModal("comm");
    }
    setTimeout(() => {
      injectCalendarSettingsCard();
      const card = document.getElementById("calendar-settings-card");
      if (card) card.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 150);
  }

  function injectCalendarSettingsCard() {
    const commTab = document.getElementById("settings-tab-comm");
    if (!commTab || document.getElementById("calendar-settings-card")) return;

    const prefs = getPrefs();
    const card = document.createElement("div");
    card.id = "calendar-settings-card";
    card.className = "border border-[var(--border)] rounded-xl p-4 bg-[var(--card)] space-y-3 shadow-xs";
    card.innerHTML = `
      <div>
        <h4 class="font-bold text-xs uppercase font-mono tracking-wider text-[var(--foreground)]">Operations Kalender & Externe Sync-Quellen</h4>
        <p class="text-[11px] text-[var(--muted-foreground)]">Standardansicht, Arbeitszeiten und externe Kalender (Google ICS, Microsoft 365 / Outlook ICS, Apple / Nextcloud CalDAV).</p>
      </div>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
        <label class="space-y-1">
          <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Standard-Ansicht</span>
          <select id="cal-set-view" class="w-full px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)]">
            <option value="week" ${prefs.initialView === "week" ? "selected" : ""}>Woche</option>
            <option value="month" ${prefs.initialView === "month" ? "selected" : ""}>Monat</option>
            <option value="day" ${prefs.initialView === "day" ? "selected" : ""}>Tag</option>
            <option value="year" ${prefs.initialView === "year" ? "selected" : ""}>Jahr</option>
            <option value="list" ${prefs.initialView === "list" ? "selected" : ""}>Agenda</option>
          </select>
        </label>
        <label class="space-y-1">
          <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Start-Stunde</span>
          <input id="cal-set-min" type="number" min="0" max="12" value="${_escCal(prefs.slotMinHour ?? 6)}" class="w-full px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)] font-mono" />
        </label>
        <label class="space-y-1">
          <span class="text-[10px] font-mono text-[var(--muted-foreground)]">End-Stunde</span>
          <input id="cal-set-max" type="number" min="14" max="24" value="${_escCal(prefs.slotMaxHour ?? 22)}" class="w-full px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)] font-mono" />
        </label>
        <label class="space-y-1">
          <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Fokus-Block (Min)</span>
          <input id="cal-set-focus" type="number" min="30" max="240" step="15" value="${_escCal(prefs.focusDuration || 90)}" class="w-full px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)] font-mono" />
        </label>
        <label class="space-y-1">
          <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Zweit-Zeitzone</span>
          <select id="cal-set-tz2" class="w-full px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)]">
            <option value="none" ${prefs.secondaryTz === "none" ? "selected" : ""}>Aus</option>
            <option value="America/New_York" ${prefs.secondaryTz === "America/New_York" ? "selected" : ""}>US-EST (New York)</option>
            <option value="America/Los_Angeles" ${prefs.secondaryTz === "America/Los_Angeles" ? "selected" : ""}>US-PST (Los Angeles)</option>
            <option value="UTC" ${prefs.secondaryTz === "UTC" ? "selected" : ""}>UTC</option>
            <option value="Europe/London" ${prefs.secondaryTz === "Europe/London" ? "selected" : ""}>London (GMT/BST)</option>
            <option value="Asia/Tokyo" ${prefs.secondaryTz === "Asia/Tokyo" ? "selected" : ""}>Tokio (JST)</option>
          </select>
        </label>
        <label class="space-y-1">
          <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Feiertage (Bundesland)</span>
          <select id="cal-set-state" class="w-full px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)]">
            ${["BY", "BW", "BE", "BB", "HB", "HH", "HE", "MV", "NI", "NW", "RP", "SL", "SN", "ST", "SH", "TH"]
              .map((st) => `<option value="${st}" ${(prefs.holidayState || "BY") === st ? "selected" : ""}>${st}</option>`)
              .join("")}
          </select>
        </label>
        <label class="space-y-1 md:col-span-2">
          <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Buchungslink-Slug (Cal.com-Stil)</span>
          <input id="cal-set-slug" value="${_escCal(prefs.bookingSlug || "mein-termin")}" class="w-full px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)] font-mono" />
        </label>
      </div>
      <div class="flex justify-end">
        <button type="button" id="cal-set-save-prefs" class="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold">Kalender-Einstellungen speichern</button>
      </div>
      <div class="pt-3 border-t border-[var(--border)] space-y-2">
        <div class="text-[10px] font-mono uppercase tracking-wider text-[var(--muted-foreground)]">Externe Kalender verbinden & Two-Way-Sync (Google / Outlook / CalDAV)</div>
        <div class="grid grid-cols-1 md:grid-cols-4 gap-2 text-xs">
          <input id="cal-src-name" placeholder="Name (z. B. Outlook Firma)" class="px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)]" />
          <select id="cal-src-prov" class="px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)]">
            <option value="google_ics">Google Calendar (.ics)</option>
            <option value="google_oauth">Google Calendar (OAuth Two-Way)</option>
            <option value="outlook_ics">Microsoft 365 / Outlook (.ics)</option>
            <option value="outlook_oauth">Microsoft 365 Graph (OAuth Two-Way)</option>
            <option value="caldav">Apple / Nextcloud (CalDAV Writeback)</option>
            <option value="ics_feed">Allgemeiner .ics Feed</option>
          </select>
          <input id="cal-src-url" placeholder="https://... (.ics, CalDAV oder Calendar-ID)" class="md:col-span-2 px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)] font-mono" />
        </div>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-2 text-xs items-center">
          <input id="cal-src-token" type="password" placeholder="OAuth Bearer Token oder CalDAV Basic Auth (optional)" class="md:col-span-2 px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)] font-mono" />
          <label class="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" id="cal-src-twoway" />
            <span>Two-Way Writeback aktiv</span>
          </label>
        </div>
        <div class="flex justify-end">
          <button type="button" id="cal-src-add-btn" class="px-3 py-1.5 rounded-lg border border-indigo-500/40 bg-indigo-500/15 hover:bg-indigo-500/25 text-indigo-300 text-xs font-semibold">+ Quelle hinzufuegen & synchronisieren</button>
        </div>
        <div id="cal-set-sources-list" class="space-y-1.5"></div>
      </div>
      <div class="pt-3 border-t border-[var(--border)] space-y-2">
        <div class="text-[10px] font-mono uppercase tracking-wider text-[var(--muted-foreground)]">Ressourcen & Raeume (kommagetrennt)</div>
        <div class="flex gap-2 text-xs">
          <input id="cal-set-resources" value="${_escCal(_resources.join(", "))}" class="flex-1 px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)]" />
          <button type="button" id="cal-set-save-res" class="px-3 py-1.5 rounded-lg border border-[var(--border)] hover:bg-[var(--secondary)] text-xs font-semibold">Speichern</button>
        </div>
      </div>
      <div class="pt-3 border-t border-[var(--border)] space-y-2">
        <div class="text-[10px] font-mono uppercase tracking-wider text-[var(--muted-foreground)]">OAuth2 Browser-Login (Google & Microsoft 365)</div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
          <input id="cal-oa-g-cid" placeholder="Google OAuth Client-ID" class="px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)] font-mono" />
          <input id="cal-oa-g-sec" type="password" placeholder="Google Client-Secret" class="px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)] font-mono" />
          <input id="cal-oa-m-cid" placeholder="Microsoft Azure App Client-ID" class="px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)] font-mono" />
          <input id="cal-oa-m-sec" type="password" placeholder="Microsoft Client-Secret" class="px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)] font-mono" />
        </div>
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div class="flex flex-wrap gap-2">
            <button type="button" id="cal-oa-g-connect" class="px-3 py-1.5 rounded-lg border border-sky-500/40 bg-sky-500/10 hover:bg-sky-500/20 text-sky-300 text-xs font-semibold">Mit Google verbinden</button>
            <button type="button" id="cal-oa-m-connect" class="px-3 py-1.5 rounded-lg border border-indigo-500/40 bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-300 text-xs font-semibold">Mit Microsoft 365 verbinden</button>
            <button type="button" id="cal-rsvp-imap-btn" class="px-3 py-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 text-xs font-semibold">RSVP-Postfach pruefen</button>
            <button type="button" id="cal-maint-run-btn" class="px-3 py-1.5 rounded-lg border border-[var(--border)] hover:bg-[var(--secondary)] text-xs font-semibold">Wartung jetzt ausfuehren</button>
          </div>
          <button type="button" id="cal-oa-save-btn" class="px-3 py-1.5 rounded-lg border border-[var(--border)] hover:bg-[var(--secondary)] text-xs font-semibold">OAuth-Daten speichern</button>
        </div>
      </div>
      <div class="pt-3 border-t border-[var(--border)] space-y-2">
        <div class="text-[10px] font-mono uppercase tracking-wider text-[var(--muted-foreground)]">Buchungstypen (Cal.com Multi-Slug, Puffer, Round-Robin, Preis & Fragebogen)</div>
        <div id="cal-set-bt-list" class="space-y-1 text-xs"></div>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
          <input id="cal-bt-slug" placeholder="Slug (z. B. intro-15)" class="px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)] font-mono" />
          <input id="cal-bt-title" placeholder="Titel (z. B. 15-Min Intro)" class="px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)]" />
          <input id="cal-bt-dur" type="number" value="30" placeholder="Dauer (Min)" class="px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)] font-mono" />
          <input id="cal-bt-max" type="number" value="4" placeholder="Max/Tag" class="px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)] font-mono" />
          <input id="cal-bt-bufb" type="number" value="10" placeholder="Puffer vor (Min)" class="px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)] font-mono" />
          <input id="cal-bt-bufa" type="number" value="10" placeholder="Puffer nach (Min)" class="px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)] font-mono" />
          <input id="cal-bt-price" type="number" step="0.01" value="0" placeholder="Preis EUR (0=kostenlos)" class="px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)] font-mono" />
          <input id="cal-bt-color" type="color" value="#6366f1" class="w-full h-8 rounded border border-[var(--border)] bg-[var(--background)]" />
          <input id="cal-bt-team" placeholder="Round-Robin Team (kommagetrennt)" class="md:col-span-2 px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)]" />
          <input id="cal-bt-qs" placeholder="Fragebogen-Felder (kommagetrennt)" class="md:col-span-2 px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--background)]" />
        </div>
        <div class="flex justify-end">
          <button type="button" id="cal-bt-save-btn" class="px-3 py-1.5 rounded-lg border border-indigo-500/40 bg-indigo-500/15 hover:bg-indigo-500/25 text-indigo-300 text-xs font-semibold">Buchungstyp speichern</button>
        </div>
      </div>
    `;
    commTab.appendChild(card);

    async function loadBookingTypesUI() {
      const box = card.querySelector("#cal-set-bt-list");
      if (!box) return;
      try {
        const res = await api("/api/v1/calendar/booking-types");
        const rows = res.types || [];
        box.innerHTML = rows
          .map((bt) => `<div class="flex items-center justify-between p-1.5 rounded border border-[var(--border)] bg-[var(--background)]">
            <span><strong>${_escCal(bt.title)}</strong> <span class="font-mono text-[10px] text-[var(--muted-foreground)]">(${_escCal(bt.slug)} · ${bt.duration_min}m · Puffer ${bt.buffer_before_min || 0}/${bt.buffer_after_min || 0} · ${Number(bt.price_eur || 0) > 0 ? bt.price_eur + "€" : "Gratis"})</span></span>
            <button type="button" data-del-bt="${_escCal(bt.slug)}" class="text-rose-400 hover:underline text-[11px]">Loeschen</button>
          </div>`)
          .join("");
        box.querySelectorAll("[data-del-bt]").forEach((b) => {
          b.onclick = async () => {
            await api(`/api/v1/calendar/booking-types/${encodeURIComponent(b.getAttribute("data-del-bt"))}`, { method: "DELETE" });
            loadBookingTypesUI();
          };
        });
      } catch (_) {}
    }
    loadBookingTypesUI();

    card.querySelector("#cal-bt-save-btn").onclick = async () => {
      try {
        await api("/api/v1/calendar/booking-types", {
          method: "POST",
          body: JSON.stringify({
            slug: card.querySelector("#cal-bt-slug").value.trim(),
            title: card.querySelector("#cal-bt-title").value.trim(),
            duration_min: Number(card.querySelector("#cal-bt-dur").value || 30),
            max_per_day: Number(card.querySelector("#cal-bt-max").value || 4),
            buffer_before_min: Number(card.querySelector("#cal-bt-bufb").value || 0),
            buffer_after_min: Number(card.querySelector("#cal-bt-bufa").value || 0),
            price_eur: Number(card.querySelector("#cal-bt-price").value || 0),
            brand_color: card.querySelector("#cal-bt-color").value || "#6366f1",
            team_members: card.querySelector("#cal-bt-team").value,
            questions: card.querySelector("#cal-bt-qs").value,
          }),
        });
        loadBookingTypesUI();
        alert("Buchungstyp gespeichert.");
      } catch (err) {
        alert(err.message);
      }
    };

    api("/api/v1/calendar/oauth/config").then((res) => {
      const cfg = res.config || {};
      if (cfg.google?.client_id) card.querySelector("#cal-oa-g-cid").value = cfg.google.client_id;
      if (cfg.outlook?.client_id) card.querySelector("#cal-oa-m-cid").value = cfg.outlook.client_id;
    }).catch(() => {});

    card.querySelector("#cal-set-save-res").onclick = async () => {
      const items = card.querySelector("#cal-set-resources").value.split(",").map((x) => x.trim()).filter(Boolean);
      const res = await api("/api/v1/calendar/resources", { method: "POST", body: JSON.stringify({ resources: items }) });
      _resources = res.resources || items;
      alert("Ressourcen gespeichert.");
      if (document.getElementById("ops-view-calendar")?.dataset.calMounted) renderMainStage();
    };

    card.querySelector("#cal-oa-save-btn").onclick = async () => {
      await api("/api/v1/calendar/oauth/config", {
        method: "POST",
        body: JSON.stringify({
          google: { client_id: card.querySelector("#cal-oa-g-cid").value.trim(), client_secret: card.querySelector("#cal-oa-g-sec").value.trim() },
          outlook: { client_id: card.querySelector("#cal-oa-m-cid").value.trim(), client_secret: card.querySelector("#cal-oa-m-sec").value.trim() },
        }),
      });
      alert("OAuth-Konfiguration gespeichert.");
    };

    const launchOAuth = (prov) => {
      const w = window.open(`/api/v1/calendar/oauth/${prov}/start`, "archon_cal_oauth", "width=540,height=680");
      const handler = (ev) => {
        if (ev.data?.type === "archon_cal_oauth_done") {
          window.removeEventListener("message", handler);
          if (w && !w.closed) w.close();
          reloadCalendarData().catch(() => {});
        }
      };
      window.addEventListener("message", handler);
    };
    card.querySelector("#cal-oa-g-connect").onclick = () => launchOAuth("google");
    card.querySelector("#cal-oa-m-connect").onclick = () => launchOAuth("outlook");
    card.querySelector("#cal-rsvp-imap-btn").onclick = async () => {
      try {
        const res = await api("/api/v1/calendar/rsvp/poll-imap", { method: "POST" });
        alert(`IMAP geprueft (${res.polled || 0} Mails, ${(res.updated || []).length} RSVP-Updates).${res.reason ? " Hinweis: " + res.reason : ""}`);
        await reloadCalendarData();
      } catch (err) {
        alert(err.message);
      }
    };
    card.querySelector("#cal-maint-run-btn").onclick = async () => {
      try {
        const res = await api("/api/v1/calendar/maintenance/run", { method: "POST" });
        alert(`Wartung abgeschlossen: ${(res.webhooks_renewed || []).length} Webhook(s) erneuert, ${(res.imap?.updated || []).length} RSVP-Update(s).`);
      } catch (err) {
        alert(err.message);
      }
    };

    card.querySelector("#cal-set-save-prefs").onclick = () => {
      const nextView = card.querySelector("#cal-set-view").value;
      savePrefs({
        initialView: nextView,
        slotMinHour: Number(card.querySelector("#cal-set-min").value || 6),
        slotMaxHour: Number(card.querySelector("#cal-set-max").value || 22),
        focusDuration: Number(card.querySelector("#cal-set-focus").value || 90),
        secondaryTz: card.querySelector("#cal-set-tz2").value || "none",
        holidayState: card.querySelector("#cal-set-state").value || "BY",
        bookingSlug: (card.querySelector("#cal-set-slug").value || "mein-termin").trim(),
      });
      _viewMode = nextView;
      if (document.getElementById("ops-view-calendar")?.dataset.calMounted) {
        reloadCalendarData();
      }
      alert("Kalender-Einstellungen gespeichert.");
    };

    card.querySelector("#cal-src-add-btn").onclick = async () => {
      const name = card.querySelector("#cal-src-name").value.trim();
      const provider = card.querySelector("#cal-src-prov").value;
      const url = card.querySelector("#cal-src-url").value.trim();
      const access_token = card.querySelector("#cal-src-token").value.trim();
      const two_way_sync = card.querySelector("#cal-src-twoway").checked;
      if (!name || !url) return alert("Bitte Name und URL eingeben.");
      try {
        const saved = await api("/api/v1/calendar/sources", {
          method: "POST",
          body: JSON.stringify({ name, provider, url, access_token, two_way_sync }),
        });
        if (saved.source?.id) {
          await api(`/api/v1/calendar/sources/${encodeURIComponent(saved.source.id)}/sync`, { method: "POST" }).catch(() => {});
        }
        card.querySelector("#cal-src-name").value = "";
        card.querySelector("#cal-src-url").value = "";
        card.querySelector("#cal-src-token").value = "";
        await reloadCalendarData();
      } catch (err) {
        alert(err.message);
      }
    };

    reloadCalendarData().catch(() => {});
  }

  window.renderEmbeddedOperationsCalendar = renderCalendarHostShell;
  window.openOperationsCalendar = function () {
    if (typeof window.setOperationsTab === "function") {
      window.setOperationsTab("calendar");
    }
    renderCalendarHostShell();
  };

  function injectTile() {
    if (document.getElementById("ops-subtab-calendar")) return true;
    const anchor =
      document.getElementById("ops-subtab-automation") ||
      document.getElementById("ops-subtab-org") ||
      document.getElementById("ops-subtab-kanban");
    if (!anchor || !anchor.parentNode) return false;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.id = "ops-subtab-calendar";
    btn.title = _calT("ui.operations_calendar.tile_title", "Operations-Kalender");
    btn.setAttribute("onclick", "setOperationsTab('calendar')");
    btn.className =
      "ops-header-tile flex flex-col items-center justify-between min-w-[56px] sm:min-w-[62px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-80 hover:opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
    btn.innerHTML = `
      <div class="tile-icon-wrap w-11 h-11 sm:w-12 sm:h-12 flex items-center justify-center mb-0.5 relative">
        <img src="/static/img/cadre_icons/calendar.png?v=2026112045" alt="Kalender" class="w-full h-full object-contain drop-shadow-xs pointer-events-none">
      </div>
      <span class="ops-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-[var(--foreground)] font-medium leading-none">${_escCal(_calT("ui.operations_calendar.tile_label", "Kalender"))}</span>`;
    anchor.parentNode.insertBefore(btn, anchor.nextSibling);
    return true;
  }

  const _calSettingsObs = new MutationObserver(() => {
    if (document.getElementById("settings-tab-comm") && !document.getElementById("calendar-settings-card")) {
      injectCalendarSettingsCard();
    }
  });
  if (document.body) _calSettingsObs.observe(document.body, { childList: true, subtree: true });

  const _notifiedReminders = new Set();
  function checkCalendarReminders() {
    if (!_allEvents.length) return;
    const now = new Date();
    const todayIso = toIsoDate(now);
    const nowMin = now.getHours() * 60 + now.getMinutes();
    _allEvents.forEach((ev) => {
      const rem = Number(ev.reminder_min || 0);
      if (!rem || ev.date !== todayIso || !ev.time) return;
      const startMin = parseMinutes(ev.time);
      if (startMin === null) return;
      const diff = startMin - nowMin;
      const key = `${ev.id}_${todayIso}`;
      if (diff >= 0 && diff <= rem && !_notifiedReminders.has(key)) {
        _notifiedReminders.add(key);
        const msg = `Termin in ${diff} Min: ${ev.title} (${ev.time})`;
        if (typeof Notification !== "undefined" && Notification.permission === "granted") {
          try { new Notification("Archon OS Kalender", { body: msg }); } catch (_) {}
        }
        if (typeof window.showToast === "function") window.showToast(msg, "info");
      }
    });
  }

  function connectCalendarWebSocket() {
    if (window._calWs && window._calWs.readyState <= 1) return;
    try {
      const proto = window.location.protocol === "https:" ? "wss://" : "ws://";
      const ws = new WebSocket(`${proto}${window.location.host}/api/v1/calendar/ws`);
      window._calWs = ws;
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data || "{}");
          if (msg.type === "calendar_changed" && document.getElementById("ops-view-calendar")?.dataset.calMounted) {
            reloadCalendarData().catch(() => {});
          }
        } catch (_) {}
      };
      ws.onclose = () => { setTimeout(connectCalendarWebSocket, 5000); };
    } catch (_) {}
  }

  function boot() {
    if (!injectTile()) {
      let tries = 0;
      const timer = setInterval(() => {
        tries += 1;
        if (injectTile() || tries > 20) clearInterval(timer);
      }, 400);
    }
    injectCalendarSettingsCard();
    setInterval(checkCalendarReminders, 30000);
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/static/sw_calendar.js").catch(() => {});
    }
    _saveOfflineQueue(_getOfflineQueue());
    connectCalendarWebSocket();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
