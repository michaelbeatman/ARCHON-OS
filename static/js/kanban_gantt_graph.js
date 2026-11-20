// M78: Mission Control Kanban — DAW-Style Gantt-Timeline & Dependency-Graph Views
(function () {
  function escHtml(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function statusColor(status) {
    const s = String(status || '').toLowerCase();
    if (s === 'done') return '#10b981';
    if (s === 'in_progress') return '#3b82f6';
    if (s === 'review') return '#8b5cf6';
    if (s === 'blocked' || s === 'failed') return '#ef4444';
    return '#64748b';
  }

  function statusLabel(status) {
    const s = String(status || '').toLowerCase();
    if (s === 'done') return 'Erledigt';
    if (s === 'in_progress') return 'In Arbeit';
    if (s === 'review') return 'Review';
    if (s === 'blocked') return 'Blockiert';
    if (s === 'failed') return 'Fehlgeschlagen';
    if (s === 'todo') return 'To-Do';
    return status || 'Offen';
  }

  function toDateInputValue(ms) {
    const d = new Date(ms);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  }

  function loadTrackColors() {
    try {
      return JSON.parse(localStorage.getItem('archon_gantt_track_colors') || '{}') || {};
    } catch (e) {
      return {};
    }
  }

  function saveTrackColor(trackId, color) {
    try {
      const map = loadTrackColors();
      if (color) map[trackId] = color;
      else delete map[trackId];
      localStorage.setItem('archon_gantt_track_colors', JSON.stringify(map));
    } catch (e) {}
  }

  let ganttState = {
    preset: '7d',
    startDate: '',
    endDate: '',
    dayWidth: 180,
    items: [],
    collapsedGroups: new Set(),
    trackColors: loadTrackColors()
  };

  function computeGanttWindow(items) {
    const now = new Date();
    const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const dayMs = 86400000;

    if (ganttState.preset === 'custom' && ganttState.startDate && ganttState.endDate) {
      const s = new Date(ganttState.startDate + 'T00:00:00').getTime();
      const e = new Date(ganttState.endDate + 'T23:59:59').getTime();
      if (!Number.isNaN(s) && !Number.isNaN(e) && e > s) {
        return { minT: s, maxT: e };
      }
    }

    if (ganttState.preset === '1d') {
      return { minT: todayStart, maxT: todayStart + dayMs };
    }
    if (ganttState.preset === '3d') {
      return { minT: todayStart - dayMs, maxT: todayStart + 2 * dayMs };
    }
    if (ganttState.preset === '7d') {
      return { minT: todayStart - 2 * dayMs, maxT: todayStart + 5 * dayMs };
    }
    if (ganttState.preset === '14d') {
      return { minT: todayStart - 4 * dayMs, maxT: todayStart + 10 * dayMs };
    }
    if (ganttState.preset === '30d') {
      return { minT: todayStart - 7 * dayMs, maxT: todayStart + 23 * dayMs };
    }

    const times = items.flatMap(i => [new Date(i.start).getTime(), new Date(i.end).getTime()]).filter(t => !Number.isNaN(t));
    if (!times.length) return { minT: todayStart - 2 * dayMs, maxT: todayStart + 5 * dayMs };
    const rawMin = Math.min(...times);
    const rawMax = Math.max(...times);
    const dMin = new Date(rawMin);
    const minDay = new Date(dMin.getFullYear(), dMin.getMonth(), dMin.getDate()).getTime();
    return { minT: minDay, maxT: Math.max(minDay + 5 * dayMs, rawMax + dayMs) };
  }

  function buildGanttTracks(items) {
    const byId = new Map();
    items.forEach(it => byId.set(String(it.id), it));
    const childrenByParent = new Map();
    const attachedIds = new Set();

    // 1. Direct parent_id links
    items.forEach(it => {
      const pid = it.parent_id ? String(it.parent_id) : '';
      if (pid && byId.has(pid) && pid !== String(it.id)) {
        if (!childrenByParent.has(pid)) childrenByParent.set(pid, []);
        childrenByParent.get(pid).push(it);
        attachedIds.add(String(it.id));
      }
    });

    // 2. Inline subtasks arrays if any subtask isn't already a separate top-level item
    items.forEach(it => {
      if (Array.isArray(it.subtasks) && it.subtasks.length) {
        const pid = String(it.id);
        if (!childrenByParent.has(pid)) childrenByParent.set(pid, []);
        const existingIds = new Set(childrenByParent.get(pid).map(c => String(c.id)));
        it.subtasks.forEach((st, idx) => {
          const sid = String(st.id || `${pid}_sub_${idx}`);
          if (byId.has(sid)) {
            if (!existingIds.has(sid)) {
              childrenByParent.get(pid).push(byId.get(sid));
              attachedIds.add(sid);
            }
          } else {
            childrenByParent.get(pid).push({
              id: sid,
              title: st.title || st.name || `Subtask ${idx + 1}`,
              status: st.status || it.status || 'todo',
              assignee: st.assignee || it.assignee || '',
              start: st.started_at || st.created_at || it.start,
              end: st.completed_at || st.due_date || it.end,
              duration_hours: st.duration_hours || Math.max(1, Math.round((it.duration_hours || 2) / Math.max(1, it.subtasks.length))),
              open_target_id: it.id
            });
          }
        });
      }
    });

    const tracks = [];
    items.forEach(it => {
      const id = String(it.id);
      if (attachedIds.has(id)) return;
      const kids = childrenByParent.get(id) || [];
      tracks.push({ item: it, children: kids, isGroup: kids.length > 0 });
    });
    return tracks;
  }

  function enableDragScroll(el) {
    if (!el || el.dataset.dragScrollBound) return;
    el.dataset.dragScrollBound = '1';
    let isDown = false;
    let startX = 0;
    let scrollLeft = 0;
    el.style.cursor = 'grab';
    el.addEventListener('mousedown', (e) => {
      if (e.target.closest('button, input, select, [data-task-bar], [data-gantt-open]')) return;
      isDown = true;
      el.style.cursor = 'grabbing';
      startX = e.pageX - el.offsetLeft;
      scrollLeft = el.scrollLeft;
    });
    window.addEventListener('mouseup', () => {
      if (!isDown) return;
      isDown = false;
      el.style.cursor = 'grab';
    });
    el.addEventListener('mousemove', (e) => {
      if (!isDown) return;
      e.preventDefault();
      const x = e.pageX - el.offsetLeft;
      el.scrollLeft = scrollLeft - (x - startX) * 1.25;
    });
    // Fine-grained horizontal scroll with wheel when holding Shift or using trackpad X
    el.addEventListener('wheel', (e) => {
      if (e.shiftKey && Math.abs(e.deltaY) > 0) {
        e.preventDefault();
        el.scrollLeft += e.deltaY * 0.6;
      }
    }, { passive: false });
  }

  function openGanttTaskDetail(taskId) {
    if (!taskId) return;
    if (typeof window.openTaskDetailModal === 'function') {
      window.openTaskDetailModal(taskId);
    }
  }

  function drawGanttUI(container) {
    const items = ganttState.items || [];
    const tracks = buildGanttTracks(items);
    const { minT, maxT } = computeGanttWindow(items);
    const dayMs = 86400000;
    const totalDays = Math.max(1, Math.ceil((maxT - minT) / dayMs));
    const dayWidth = ganttState.dayWidth || 180;
    const timelineWidth = totalDays * dayWidth;
    const span = Math.max(1, totalDays * dayMs);

    if (!ganttState.startDate) ganttState.startDate = toDateInputValue(minT);
    if (!ganttState.endDate) ganttState.endDate = toDateInputValue(maxT);

    const showHours = dayWidth >= 220;
    const hourStep = dayWidth >= 480 ? 3 : 6;
    const dayHeaders = [];
    const weekdayFmt = new Intl.DateTimeFormat('de-DE', { weekday: 'short' });
    const dateFmt = new Intl.DateTimeFormat('de-DE', { day: '2-digit', month: '2-digit' });
    const nowMs = Date.now();
    const todayStr = toDateInputValue(nowMs);

    for (let d = 0; d < totalDays; d++) {
      const t = minT + d * dayMs;
      const dt = new Date(t);
      const isToday = toDateInputValue(t) === todayStr;
      const isWeekend = dt.getDay() === 0 || dt.getDay() === 6;
      let subTicks = '';
      if (showHours) {
        const ticks = [];
        for (let h = 0; h < 24; h += hourStep) {
          ticks.push(`<div class="flex-1 text-[9px] font-mono text-[var(--muted-foreground)] border-r border-[var(--border)]/40 last:border-r-0">${String(h).padStart(2, '0')}h</div>`);
        }
        subTicks = `<div class="flex border-t border-[var(--border)]/50 mt-0.5 pt-0.5">${ticks.join('')}</div>`;
      }
      dayHeaders.push(`
        <div style="width:${dayWidth}px;min-width:${dayWidth}px;"
             class="shrink-0 px-1 py-1 border-r border-[var(--border)] text-center select-none ${isToday ? 'bg-rose-500/10 text-[#d42a2b] font-bold' : (isWeekend ? 'bg-[var(--secondary)]/50 text-[var(--muted-foreground)]' : 'text-[var(--muted-foreground)]')}">
          <div class="text-[10px] font-mono uppercase leading-tight">${escHtml(weekdayFmt.format(dt))} · ${escHtml(dateFmt.format(dt))}</div>
          ${subTicks}
        </div>
      `);
    }

    const nowPct = ((nowMs - minT) / span) * 100;
    const showNowLine = nowPct >= 0 && nowPct <= 100;

    const renderTrackRow = (item, opts = {}) => {
      const { isGroup = false, isChild = false, childCount = 0, groupId = null, customColor = null } = opts;
      let s = new Date(item.start).getTime();
      let e = new Date(item.end).getTime();
      if (Number.isNaN(s)) s = minT;
      if (Number.isNaN(e) || e <= s) e = s + 3600000;
      const clampedStart = Math.max(minT, s);
      const clampedEnd = Math.min(minT + span, e);
      const visible = clampedEnd > minT && clampedStart < minT + span;
      const leftPx = ((clampedStart - minT) / span) * timelineWidth;
      const widthPx = Math.max(22, ((clampedEnd - clampedStart) / span) * timelineWidth);
      const trackColor = customColor || ganttState.trackColors[String(item.id)] || statusColor(item.status);
      const isCollapsed = isGroup && ganttState.collapsedGroups.has(String(item.id));
      const targetDetailId = item.open_target_id || item.id;

      const gridCols = Array.from({ length: totalDays }, (_, d) => {
        const dt = new Date(minT + d * dayMs);
        const isWeekend = dt.getDay() === 0 || dt.getDay() === 6;
        return `<div style="width:${dayWidth}px;min-width:${dayWidth}px;" class="h-full border-r border-[var(--border)]/50 shrink-0 ${isWeekend ? 'bg-[var(--secondary)]/25' : ''}"></div>`;
      }).join('');

      const toggleBtn = isGroup
        ? `<button type="button" data-gantt-toggle="${escHtml(item.id)}" class="w-5 h-5 rounded hover:bg-[var(--secondary)] flex items-center justify-center text-[var(--foreground)] cursor-pointer shrink-0 font-mono text-xs" title="${isCollapsed ? 'Ordner aufklappen' : 'Ordner zuklappen'}">${isCollapsed ? '▸' : '▾'}</button>`
        : (isChild ? `<span class="w-5 text-center text-[var(--muted-foreground)] font-mono shrink-0">└</span>` : `<span class="w-5 shrink-0"></span>`);

      const colorInputId = `gantt-color-${String(item.id).replace(/[^a-zA-Z0-9_-]/g, '_')}`;
      const colorPicker = !isChild
        ? `<label class="shrink-0 cursor-pointer flex items-center" title="Spur-Farbe anpassen" onclick="event.stopPropagation()">
             <span style="background:${escHtml(trackColor)};" class="w-3 h-3 rounded-sm border border-black/20 inline-block"></span>
             <input id="${colorInputId}" data-gantt-color="${escHtml(item.id)}" type="color" value="${escHtml(trackColor.startsWith('#') ? trackColor : '#3b82f6')}" class="sr-only" />
           </label>`
        : '';

      return `
        <div class="flex items-stretch border-b border-[var(--border)] ${isGroup ? 'bg-[var(--secondary)]/30 font-semibold' : (isChild ? 'bg-[var(--card)]' : 'bg-[var(--card)]')} hover:bg-[var(--secondary)]/45 transition text-xs">
          <div class="w-72 shrink-0 px-2.5 py-2 border-r border-[var(--border)] bg-[var(--card)] sticky left-0 z-10 flex items-center justify-between gap-1.5">
            <div class="flex items-center gap-1.5 min-w-0 flex-1">
              ${toggleBtn}
              ${colorPicker}
              <div data-gantt-open="${escHtml(targetDetailId)}" class="min-w-0 flex-1 cursor-pointer hover:text-[#d42a2b] transition">
                <div class="text-[var(--foreground)] truncate ${isGroup ? 'font-bold' : (isChild ? 'font-normal text-[11px]' : 'font-medium')}" title="${escHtml(item.title)}">${isGroup ? '📁 ' : ''}${escHtml(item.title)}</div>
                <div class="text-[10px] font-mono text-[var(--muted-foreground)] truncate">${escHtml(item.assignee || 'Auto')} · ${escHtml(statusLabel(item.status))}${isGroup ? ` · ${childCount} Subtasks` : ''}</div>
              </div>
            </div>
            <span class="text-[10px] font-mono text-[var(--muted-foreground)] shrink-0">${escHtml(item.duration_hours)}h</span>
          </div>
          <div style="width:${timelineWidth}px;min-width:${timelineWidth}px;" class="relative ${isChild ? 'h-9' : 'h-11'} flex items-center shrink-0">
            <div class="absolute inset-0 flex pointer-events-none">${gridCols}</div>
            ${showNowLine ? `<div style="left:${nowPct.toFixed(2)}%;" class="absolute top-0 bottom-0 w-px bg-[#d42a2b]/80 z-10 pointer-events-none"></div>` : ''}
            ${visible ? `
              <div data-task-bar="1"
                   data-gantt-open="${escHtml(targetDetailId)}"
                   style="left:${leftPx.toFixed(1)}px;width:${widthPx.toFixed(1)}px;background:${escHtml(trackColor)};${isGroup ? 'opacity:0.95;' : 'opacity:0.85;'}"
                   class="absolute ${isChild ? 'h-5' : 'h-6'} rounded-md text-white text-[10px] font-mono font-semibold px-2 flex items-center truncate shadow-xs cursor-pointer hover:opacity-100 z-20"
                   title="${escHtml(item.title)} | ${escHtml(item.start)} → ${escHtml(item.end)} (${escHtml(item.duration_hours)}h)">
                ${escHtml(item.title)}
              </div>` : ''}
          </div>
        </div>`;
    };

    const rowsHtml = tracks.map(tr => {
      const gid = String(tr.item.id);
      const groupColor = ganttState.trackColors[gid] || null;
      let html = renderTrackRow(tr.item, {
        isGroup: tr.isGroup,
        childCount: tr.children.length,
        customColor: groupColor
      });
      if (tr.isGroup && !ganttState.collapsedGroups.has(gid)) {
        html += tr.children.map(ch => renderTrackRow(ch, {
          isChild: true,
          groupId: gid,
          customColor: groupColor
        })).join('');
      }
      return html;
    }).join('');

    const presetBtn = (id, label) => {
      const active = ganttState.preset === id;
      return `<button type="button" data-gantt-preset="${id}" style="${active ? 'background-color:#d42a2b;color:#ffffff;' : ''}" class="h-7 px-2.5 rounded-md text-[11px] font-mono transition cursor-pointer ${active ? 'font-bold' : 'bg-[var(--secondary)] text-[var(--foreground)] hover:opacity-80'}">${label}</button>`;
    };

    container.innerHTML = `
      <div class="rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-xs flex flex-col overflow-hidden">
        <div class="px-3 py-2 border-b border-[var(--border)] bg-[var(--background)] flex items-center justify-between gap-2 flex-wrap">
          <div class="flex items-center gap-1.5 flex-wrap">
            ${presetBtn('1d', '24h')}
            ${presetBtn('3d', '3 Tage')}
            ${presetBtn('7d', '7 Tage')}
            ${presetBtn('14d', '14 Tage')}
            ${presetBtn('30d', '30 Tage')}
            ${presetBtn('all', 'Alle')}
            <span class="text-[var(--border)] px-1">|</span>
            <label class="text-[11px] font-mono text-[var(--muted-foreground)]">Von:</label>
            <input id="gantt-date-start" type="date" value="${escHtml(ganttState.startDate)}" class="h-7 px-2 rounded-md border border-[var(--border)] bg-[var(--card)] text-[11px] font-mono text-[var(--foreground)]" />
            <label class="text-[11px] font-mono text-[var(--muted-foreground)]">Bis:</label>
            <input id="gantt-date-end" type="date" value="${escHtml(ganttState.endDate)}" class="h-7 px-2 rounded-md border border-[var(--border)] bg-[var(--card)] text-[11px] font-mono text-[var(--foreground)]" />
          </div>
          <div class="flex items-center gap-2 text-[11px] font-mono text-[var(--muted-foreground)]">
            <span>Zoom (${Math.round(dayWidth)}px/Tag) · Ziehen / Shift+Rad ↔</span>
            <button type="button" id="gantt-zoom-out" class="h-7 w-7 rounded-md border border-[var(--border)] bg-[var(--card)] hover:bg-[var(--secondary)] text-[var(--foreground)] cursor-pointer font-bold" title="Rauszoomen">−</button>
            <button type="button" id="gantt-zoom-in" class="h-7 w-7 rounded-md border border-[var(--border)] bg-[var(--card)] hover:bg-[var(--secondary)] text-[var(--foreground)] cursor-pointer font-bold" title="Feinkörniger zoomen">+</button>
          </div>
        </div>
        <div id="gantt-scroll-area" class="overflow-x-auto overflow-y-auto max-h-[65vh] bg-[var(--card)] select-none">
          <div style="min-width:${288 + timelineWidth}px;">
            <div class="flex items-stretch border-b border-[var(--border)] bg-[var(--background)] sticky top-0 z-20">
              <div class="w-72 shrink-0 px-3 py-2 border-r border-[var(--border)] bg-[var(--background)] sticky left-0 z-30 text-[11px] font-mono font-bold uppercase tracking-wider text-[var(--muted-foreground)] flex items-center">
                Spuren &amp; Ordner (${tracks.length})
              </div>
              <div class="flex relative">${dayHeaders.join('')}</div>
            </div>
            ${rowsHtml}
          </div>
        </div>
      </div>`;

    container.querySelectorAll('[data-gantt-preset]').forEach(btn => {
      btn.addEventListener('click', () => {
        ganttState.preset = btn.getAttribute('data-gantt-preset');
        if (ganttState.preset === '1d') ganttState.dayWidth = 640;
        else if (ganttState.preset === '3d') ganttState.dayWidth = 320;
        else if (ganttState.preset === '7d') ganttState.dayWidth = 180;
        else if (ganttState.preset === '14d') ganttState.dayWidth = 110;
        else if (ganttState.preset === '30d') ganttState.dayWidth = 70;
        const win = computeGanttWindow(items);
        ganttState.startDate = toDateInputValue(win.minT);
        ganttState.endDate = toDateInputValue(win.maxT);
        drawGanttUI(container);
      });
    });

    container.querySelectorAll('[data-gantt-toggle]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const gid = btn.getAttribute('data-gantt-toggle');
        if (ganttState.collapsedGroups.has(gid)) ganttState.collapsedGroups.delete(gid);
        else ganttState.collapsedGroups.add(gid);
        drawGanttUI(container);
      });
    });

    container.querySelectorAll('[data-gantt-color]').forEach(inp => {
      inp.addEventListener('input', (e) => {
        const tid = inp.getAttribute('data-gantt-color');
        const col = e.target.value;
        ganttState.trackColors[tid] = col;
        saveTrackColor(tid, col);
        drawGanttUI(container);
      });
    });

    container.querySelectorAll('[data-gantt-open]').forEach(el => {
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        openGanttTaskDetail(el.getAttribute('data-gantt-open'));
      });
    });

    const startInp = container.querySelector('#gantt-date-start');
    const endInp = container.querySelector('#gantt-date-end');
    const onDateChange = () => {
      if (startInp && endInp && startInp.value && endInp.value) {
        ganttState.preset = 'custom';
        ganttState.startDate = startInp.value;
        ganttState.endDate = endInp.value;
        drawGanttUI(container);
      }
    };
    if (startInp) startInp.addEventListener('change', onDateChange);
    if (endInp) endInp.addEventListener('change', onDateChange);

    const zOut = container.querySelector('#gantt-zoom-out');
    const zIn = container.querySelector('#gantt-zoom-in');
    if (zOut) zOut.addEventListener('click', () => { ganttState.dayWidth = Math.max(55, Math.round((ganttState.dayWidth || 180) * 0.72)); drawGanttUI(container); });
    if (zIn) zIn.addEventListener('click', () => { ganttState.dayWidth = Math.min(960, Math.round((ganttState.dayWidth || 180) * 1.38)); drawGanttUI(container); });

    const scrollArea = container.querySelector('#gantt-scroll-area');
    enableDragScroll(scrollArea);
  }

  async function renderGantt(container) {
    if (!container) return;
    container.innerHTML = '<div class="p-4 text-sm text-[var(--muted-foreground)]">Lade Gantt-Kalender...</div>';
    try {
      const res = await fetch('/api/operations/kanban/gantt');
      const data = await res.json();
      const items = data.items || [];
      if (!items.length) {
        container.innerHTML = '<div class="p-6 text-sm text-[var(--muted-foreground)] bg-[var(--card)] rounded-xl border border-[var(--border)]">Keine Kanban-Tasks für die Gantt-Timeline vorhanden.</div>';
        return;
      }
      ganttState.items = items;
      const win = computeGanttWindow(items);
      ganttState.startDate = toDateInputValue(win.minT);
      ganttState.endDate = toDateInputValue(win.maxT);
      drawGanttUI(container);
    } catch (err) {
      container.innerHTML = `<div class="p-4 text-sm text-rose-600 bg-rose-50 rounded-xl border border-rose-200">Gantt-Fehler: ${escHtml(err.message)}</div>`;
    }
  }

  function drawGraphEdges(wrapper, edges, highlightNodeId = null) {
    const svg = wrapper.querySelector('#ops-graph-svg');
    if (!svg) return;
    const rect = wrapper.getBoundingClientRect();
    svg.setAttribute('width', Math.max(wrapper.scrollWidth, wrapper.clientWidth));
    svg.setAttribute('height', Math.max(wrapper.scrollHeight, wrapper.clientHeight));
    let paths = '';
    edges.forEach(edge => {
      const fromId = String(edge.from || edge.source || '');
      const toId = String(edge.to || edge.target || '');
      const fromEl = wrapper.querySelector(`[data-graph-node="${CSS.escape(fromId)}"]`);
      const toEl = wrapper.querySelector(`[data-graph-node="${CSS.escape(toId)}"]`);
      if (!fromEl || !toEl) return;
      const r1 = fromEl.getBoundingClientRect();
      const r2 = toEl.getBoundingClientRect();
      const x1 = r1.right - rect.left + wrapper.scrollLeft;
      const y1 = r1.top + r1.height / 2 - rect.top + wrapper.scrollTop;
      const x2 = r2.left - rect.left + wrapper.scrollLeft;
      const y2 = r2.top + r2.height / 2 - rect.top + wrapper.scrollTop;
      const dx = Math.max(36, Math.abs(x2 - x1) * 0.48);
      const isHi = highlightNodeId && (fromId === highlightNodeId || toId === highlightNodeId);
      const stroke = isHi ? '#d42a2b' : '#64748b';
      const sw = isHi ? '2.5' : '1.8';
      const marker = isHi ? 'url(#graph-arrow-active)' : 'url(#graph-arrow)';
      paths += `<path d="M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}" fill="none" stroke="${stroke}" stroke-width="${sw}" opacity="${highlightNodeId && !isHi ? '0.3' : '0.92'}" marker-end="${marker}" />`;
    });
    svg.innerHTML = `
      <defs>
        <marker id="graph-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M 0 1 L 10 5 L 0 9 z" fill="#64748b" />
        </marker>
        <marker id="graph-arrow-active" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M 0 1 L 10 5 L 0 9 z" fill="#d42a2b" />
        </marker>
      </defs>
      ${paths}`;
  }

  function enableGraphNodeInteractions(canvas, edges) {
    const cards = canvas.querySelectorAll('[data-graph-node]');
    cards.forEach(card => {
      let dragging = false;
      let moved = false;
      let startX = 0, startY = 0, origTx = 0, origTy = 0;

      card.addEventListener('mouseenter', () => drawGraphEdges(canvas, edges, card.getAttribute('data-graph-node')));
      card.addEventListener('mouseleave', () => drawGraphEdges(canvas, edges, null));

      card.addEventListener('mousedown', (e) => {
        if (e.button !== 0) return;
        dragging = true;
        moved = false;
        startX = e.clientX;
        startY = e.clientY;
        origTx = parseFloat(card.dataset.tx || '0');
        origTy = parseFloat(card.dataset.ty || '0');
        card.style.zIndex = '30';
        card.style.cursor = 'grabbing';
        e.preventDefault();
      });

      const onMove = (e) => {
        if (!dragging) return;
        const dx = e.clientX - startX;
        const dy = e.clientY - startY;
        if (Math.abs(dx) > 4 || Math.abs(dy) > 4) moved = true;
        const nx = origTx + dx;
        const ny = origTy + dy;
        card.dataset.tx = String(nx);
        card.dataset.ty = String(ny);
        card.style.transform = `translate(${nx}px, ${ny}px)`;
        drawGraphEdges(canvas, edges, card.getAttribute('data-graph-node'));
      };

      const onUp = () => {
        if (!dragging) return;
        dragging = false;
        card.style.zIndex = '10';
        card.style.cursor = 'grab';
        if (!moved) {
          const nid = card.getAttribute('data-graph-node');
          if (nid && typeof window.openTaskDetailModal === 'function') {
            window.openTaskDetailModal(nid);
          }
        }
      };

      window.addEventListener('mousemove', onMove);
      window.addEventListener('mouseup', onUp);
    });
  }

  async function renderGraph(container) {
    if (!container) return;
    container.innerHTML = '<div class="p-4 text-sm text-[var(--muted-foreground)]">Lade Abhängigkeits-Graph...</div>';
    try {
      const res = await fetch('/api/operations/kanban/graph');
      const data = await res.json();
      const nodes = data.nodes || [];
      const edges = data.edges || [];
      if (!nodes.length) {
        container.innerHTML = '<div class="p-6 text-sm text-[var(--muted-foreground)] bg-[var(--card)] rounded-xl border border-[var(--border)]">Keine Tasks für den Abhängigkeits-Graph vorhanden.</div>';
        return;
      }

      const byLayer = new Map();
      nodes.forEach(n => {
        const l = Number(n.layer || 0);
        if (!byLayer.has(l)) byLayer.set(l, []);
        byLayer.get(l).push(n);
      });

      const layersHtml = [...byLayer.entries()].sort((a, b) => a[0] - b[0]).map(([layer, list]) => {
        const cards = list.map(n => `
          <div data-graph-node="${escHtml(n.id)}"
               style="cursor: grab;"
               class="p-3 rounded-xl bg-[var(--card)] border border-[var(--border)] hover:border-[#d42a2b] text-xs shadow-xs transition-colors relative z-10 select-none">
            <div class="flex items-center justify-between gap-2 mb-1.5">
              <span class="font-mono text-[10px] text-[var(--muted-foreground)] truncate">${escHtml(n.id)}</span>
              <span class="px-1.5 py-0.5 rounded-full text-[10px] font-medium text-white shrink-0" style="background:${statusColor(n.status)}">${escHtml(statusLabel(n.status))}</span>
            </div>
            <div class="font-semibold text-[var(--foreground)] line-clamp-2 leading-snug">${escHtml(n.title)}</div>
            <div class="mt-2 pt-1.5 border-t border-[var(--border)]/60 flex items-center justify-between text-[10px] font-mono text-[var(--muted-foreground)]">
              <span>Wartet auf: ${escHtml((n.blocked_by || []).length)}</span>
              <span>Blockiert: ${escHtml((n.blocks || []).length)}</span>
            </div>
          </div>`).join('');
        return `
          <div class="min-w-[230px] max-w-[260px] flex-1 space-y-3">
            <div class="text-[11px] font-mono font-bold uppercase tracking-wider text-[var(--muted-foreground)] px-1">
              Phase ${escHtml(layer + 1)} ${layer === 0 ? '(Start)' : '(Abhängig)'}
            </div>
            ${cards}
          </div>`;
      }).join('');

      container.innerHTML = `
        <div class="rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-xs overflow-hidden">
          <div class="px-4 py-2.5 border-b border-[var(--border)] bg-[var(--background)] flex items-center justify-between gap-3 flex-wrap text-xs">
            <div class="font-mono text-[var(--muted-foreground)]">
              <span class="font-bold text-[var(--foreground)]">${escHtml(nodes.length)}</span> Aufgaben ·
              <span class="font-bold text-[var(--foreground)]">${escHtml(edges.length)}</span> Verknüpfungen ·
              <span>Ziehen zum Verschieben / Klick für Details</span>
            </div>
            <div class="flex items-center gap-3 text-[11px] font-mono text-[var(--muted-foreground)]">
              <span class="inline-flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-slate-500"></span>To-Do</span>
              <span class="inline-flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-blue-500"></span>In Arbeit</span>
              <span class="inline-flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-emerald-500"></span>Erledigt</span>
              <span class="inline-flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-rose-500"></span>Blockiert</span>
            </div>
          </div>
          <div id="ops-graph-canvas" class="relative p-5 bg-[var(--background)]/40 overflow-x-auto overflow-y-auto max-h-[65vh]">
            <svg id="ops-graph-svg" class="absolute top-0 left-0 pointer-events-none" style="z-index: 25;"></svg>
            <div class="relative z-10 flex gap-14 pb-4">${layersHtml}</div>
          </div>
        </div>`;

      const canvas = container.querySelector('#ops-graph-canvas');
      if (canvas) {
        requestAnimationFrame(() => {
          drawGraphEdges(canvas, edges);
          enableGraphNodeInteractions(canvas, edges);
        });
      }
    } catch (err) {
      container.innerHTML = `<div class="p-4 text-sm text-rose-600 bg-rose-50 rounded-xl border border-rose-200">Graph-Fehler: ${escHtml(err.message)}</div>`;
    }
  }

  function setOpsKanbanViewMode(mode) {
    const m = ['board', 'gantt', 'graph'].includes(mode) ? mode : 'board';
    const boardEl = document.getElementById('ops-kanban-columns-container');
    const altEl = document.getElementById('ops-kanban-alt-view');
    const btns = {
      board: document.getElementById('btn-kanban-mode-board'),
      gantt: document.getElementById('btn-kanban-mode-gantt'),
      graph: document.getElementById('btn-kanban-mode-graph'),
    };
    Object.entries(btns).forEach(([k, btn]) => {
      if (!btn) return;
      const active = k === m;
      btn.className = active
        ? 'h-7 px-2.5 rounded-md font-bold text-white transition cursor-pointer'
        : 'h-7 px-2.5 rounded-md font-medium text-muted-custom hover:text-primary-custom transition cursor-pointer';
      if (active) {
        btn.style.setProperty('background-color', '#d42a2b', 'important');
        btn.style.setProperty('color', '#ffffff', 'important');
      } else {
        btn.style.removeProperty('background-color');
        btn.style.removeProperty('color');
      }
    });
    if (m === 'board') {
      if (boardEl) boardEl.classList.remove('hidden');
      if (altEl) altEl.classList.add('hidden');
      return;
    }
    if (boardEl) boardEl.classList.add('hidden');
    if (altEl) {
      altEl.classList.remove('hidden');
      if (m === 'gantt') renderGantt(altEl);
      else if (m === 'graph') renderGraph(altEl);
    }
  }

  window.setOpsKanbanViewMode = setOpsKanbanViewMode;
  window.archonKanbanViews = { renderGantt, renderGraph, setOpsKanbanViewMode };
})();
