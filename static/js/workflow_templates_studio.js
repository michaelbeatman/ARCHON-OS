/**
 * static/js/workflow_templates_studio.js — M102: Visueller Multi-Agent Prozessablaufplan-Editor
 * Drag & Drop Stationen auf 20px-Raster, konfigurierbare Edge-Bedingungen/Datenübergabe,
 * sowie vollständiger Stations-Inspektor (Prompt, Expected Output, Granulare Tools, Budget & Guardrails/Verbote).
 */
(function () {
  if (window.__workflowTemplatesStudioInitialized) return;
  window.__workflowTemplatesStudioInitialized = true;

  const esc = (v) =>
    String(v == null ? "" : v)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  const GRID = 20;
  const NODE_W = 216;
  const NODE_H = 88;
  const snap = (v) => Math.max(20, Math.round(v / GRID) * GRID);

  const ALL_TOOLS = [
    { id: "web_search", label: "Web-Suche" },
    { id: "file_read", label: "Dateien lesen" },
    { id: "file_write", label: "Dateien schreiben" },
    { id: "shell_exec", label: "Shell / Terminal" },
    { id: "browser", label: "Browser-Steuerung" },
    { id: "crm_read", label: "CRM / Kontakte" },
    { id: "email_send", label: "E-Mail senden" },
    { id: "n8n_webhook", label: "n8n Webhook" },
  ];

  const PRESET_TOOLS = {
    minimal: ["file_read"],
    research: ["web_search", "file_read", "browser", "crm_read"],
    coding: ["file_read", "file_write", "shell_exec"],
    full: ALL_TOOLS.map((t) => t.id),
  };

  const STANDARD_GUARDRAILS = [
    "Keine externen E-Mails oder Nachrichten ohne Freigabe senden",
    "Keine bestehenden Dateien löschen oder destruktiv überschreiben",
    "Keine Zahlungen, Bestellungen oder Verträge auslösen",
    "Keine Zahlen, Zitate oder Quellen erfinden (nur belegte Fakten)",
    "Keine API-Keys, Passwörter oder internen Secrets ausgeben",
    "Keine Produktivsysteme oder Live-Deployments ohne HITL-Gate ändern",
  ];

  const EDGE_CONDITION_LABELS = {
    on_success: "bei Erfolg",
    always: "immer",
    on_failure: "bei Fehler",
    if_expr: "bedingt",
  };

  let _templates = [];
  let _schedules = [];
  let _nodePlugins = [];
  let _marketplaceItems = [];
  let _paletteTab = "standard";
  let _tplSearch = "";
  let _tplCat = "all";
  let _profiles = [];
  let _agents = ["research", "writer", "qa", "engineer", "analyst", "security", "executive_decision_architect", "default"];
  let _activeTpl = null;
  let _selectedNodeId = null;
  let _selectedEdge = null; // { from, to }
  let _inspectorTab = "prompt"; // "prompt" | "tools" | "guardrails"
  let _connectFromId = null;
  let _connectMode = false;
  let _dirty = false;
  let _runParamsOpen = false;
  let _activeRunId = "";
  let _activeRunCostUsd = 0;
  let _liveNodeStates = {}; // { [nodeId]: { status, quality_score, deliverable_path, cost_usd, output_preview, error } }

  // Live-SSE-Listener: Knoten leuchten waehrend der Ausfuehrung in Echtzeit
  window.addEventListener("archon:sse", (ev) => {
    const msg = ev && ev.detail;
    if (!msg || msg.type !== "workflow_node_state" || !msg.payload) return;
    const p = msg.payload;
    if (!p.node_id) return;
    if (p.run_id) _activeRunId = p.run_id;
    _liveNodeStates[p.node_id] = {
      status: p.status || "running",
      quality_score: p.quality_score,
      deliverable_path: p.deliverable_path,
      cost_usd: p.cost_usd,
      output_preview: p.output_preview || "",
      error: p.error || "",
    };
    const card = document.querySelector(`[data-wf-card="${CSS.escape(p.node_id)}"]`);
    if (card) {
      let pill = card.querySelector("[data-wf-live-pill]");
      if (!pill) {
        pill = document.createElement("span");
        pill.setAttribute("data-wf-live-pill", "1");
        pill.className = "absolute -top-2 right-2 px-1.5 py-0.5 rounded-full text-[9px] font-mono font-bold shadow-xs pointer-events-none";
        card.appendChild(pill);
      }
      const st = String(p.status || "");
      const clsMap = {
        running: "bg-sky-500 text-white animate-pulse",
        completed: "bg-emerald-600 text-white",
        skipped_cached: "bg-emerald-700 text-white",
        awaiting_gate: "bg-amber-500 text-black",
        failed: "bg-rose-600 text-white",
        rejected: "bg-rose-700 text-white",
      };
      pill.className =
        "absolute -top-2 right-2 px-1.5 py-0.5 rounded-full text-[9px] font-mono font-bold shadow-xs pointer-events-none " +
        (clsMap[st] || "bg-zinc-600 text-white");
      pill.textContent = p.quality_score != null ? `${st} · Q${p.quality_score}` : st;
    }
  });

  async function apiJson(url, opts = {}) {
    const res = await fetch(url, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    return data;
  }

  function cloneTpl(tpl) {
    const copy = JSON.parse(JSON.stringify(tpl));
    copy.edges = Array.isArray(copy.edges) ? copy.edges : [];
    // Synchronisiere edges aus depends_on falls leer
    (copy.nodes || []).forEach((n) => {
      n.allowed_tools = Array.isArray(n.allowed_tools) && n.allowed_tools.length ? n.allowed_tools : [...(PRESET_TOOLS[n.tool_preset || "research"] || [])];
      n.forbidden_actions = Array.isArray(n.forbidden_actions) ? n.forbidden_actions : [];
      (n.depends_on || []).forEach((dep) => {
        if (!copy.edges.some((e) => e.from === dep && e.to === n.id)) {
          copy.edges.push({ from: dep, to: n.id, condition: "on_success", data_mode: "full_output", label: "" });
        }
      });
    });
    return copy;
  }

  function getEdgeMeta(fromId, toId) {
    if (!_activeTpl) return { from: fromId, to: toId, condition: "on_success", data_mode: "full_output", label: "" };
    let e = (_activeTpl.edges || []).find((x) => x.from === fromId && x.to === toId);
    if (!e) {
      e = { from: fromId, to: toId, condition: "on_success", data_mode: "full_output", label: "" };
      _activeTpl.edges.push(e);
    }
    return e;
  }

  function autoLayoutNodes(nodes) {
    const byId = {};
    (nodes || []).forEach((n) => (byId[n.id] = n));
    const memo = {};
    const visiting = new Set();

    function depth(id) {
      if (memo[id] !== undefined) return memo[id];
      if (visiting.has(id)) return 0;
      visiting.add(id);
      const n = byId[id];
      let d = 0;
      ((n && n.depends_on) || []).forEach((dep) => {
        if (byId[dep]) d = Math.max(d, depth(dep) + 1);
      });
      visiting.delete(id);
      memo[id] = d;
      return d;
    }

    const layers = {};
    (nodes || []).forEach((n) => {
      const l = depth(n.id);
      if (!layers[l]) layers[l] = [];
      layers[l].push(n);
    });

    Object.keys(layers).forEach((lStr) => {
      const l = Number(lStr);
      layers[l].forEach((n, idx) => {
        n.x = snap(40 + l * 280);
        n.y = snap(40 + idx * 120);
      });
    });
  }

  function ensurePositions(tpl) {
    if (!tpl || !Array.isArray(tpl.nodes)) return;
    if (tpl.nodes.some((n) => typeof n.x !== "number" || typeof n.y !== "number")) {
      autoLayoutNodes(tpl.nodes);
    }
  }

  function wouldCreateCycle(nodes, fromId, toId) {
    if (fromId === toId) return true;
    const byId = {};
    nodes.forEach((n) => (byId[n.id] = n));
    const stack = [fromId];
    const seen = new Set();
    while (stack.length) {
      const cur = stack.pop();
      if (cur === toId) return true;
      if (seen.has(cur)) continue;
      seen.add(cur);
      const node = byId[cur];
      if (node && Array.isArray(node.depends_on)) node.depends_on.forEach((d) => stack.push(d));
    }
    return false;
  }

  function linkNodes(fromId, toId) {
    if (!_activeTpl || !fromId || !toId || fromId === toId) return;
    const target = _activeTpl.nodes.find((n) => n.id === toId);
    if (!target) return;
    target.depends_on = target.depends_on || [];
    if (!target.depends_on.includes(fromId)) {
      if (wouldCreateCycle(_activeTpl.nodes, fromId, toId)) {
        alert("Verknüpfung nicht möglich: würde einen Zyklus erzeugen.");
        return;
      }
      target.depends_on.push(fromId);
    }
    getEdgeMeta(fromId, toId);
    _selectedEdge = { from: fromId, to: toId };
    _selectedNodeId = null;
    _dirty = true;
    _connectFromId = null;
    _connectMode = false;
    renderAll();
  }

  function unlinkNodes(fromId, toId) {
    if (!_activeTpl) return;
    const target = _activeTpl.nodes.find((n) => n.id === toId);
    if (target && Array.isArray(target.depends_on)) {
      target.depends_on = target.depends_on.filter((d) => d !== fromId);
    }
    _activeTpl.edges = (_activeTpl.edges || []).filter((e) => !(e.from === fromId && e.to === toId));
    if (_selectedEdge && _selectedEdge.from === fromId && _selectedEdge.to === toId) {
      _selectedEdge = null;
    }
    _dirty = true;
    renderAll();
  }

  function addStation(type, dropX, dropY) {
    if (!_activeTpl) return;
    let counter = _activeTpl.nodes.length + 1;
    let nid = `step_${counter}`;
    const existing = new Set(_activeTpl.nodes.map((n) => n.id));
    while (existing.has(nid)) {
      counter += 1;
      nid = `step_${counter}`;
    }

    let maxX = 40;
    let lastY = 40;
    _activeTpl.nodes.forEach((n) => {
      if ((n.x || 0) >= maxX) {
        maxX = n.x || 40;
        lastY = n.y || 40;
      }
    });
    const newX = typeof dropX === "number" ? snap(dropX) : (_activeTpl.nodes.length ? snap(maxX + 260) : 40);
    const newY = typeof dropY === "number" ? snap(dropY) : (_activeTpl.nodes.length ? snap(lastY) : 40);
    const prevId = _selectedNodeId && existing.has(_selectedNodeId) ? _selectedNodeId : (_activeTpl.nodes.length ? _activeTpl.nodes[_activeTpl.nodes.length - 1].id : null);

    const defaults = {
      agent: { title: `Agent-Station ${counter}`, agent_id: "research", tool_preset: "research", soul_mode: "analytical", require_hitl: false },
      fanout: { title: `Parallel-Zweig ${counter}`, agent_id: "analyst", tool_preset: "research", soul_mode: "strict", require_hitl: false },
      gate: { title: `HITL-Freigabe ${counter}`, agent_id: "executive_decision_architect", tool_preset: "minimal", soul_mode: "strict", require_hitl: true },
      boardroom: { title: `Boardroom-Debatte ${counter}`, agent_id: "executive_decision_architect", tool_preset: "research", soul_mode: "strict", require_hitl: false },
      research: { title: `Research-Lab Auftrag ${counter}`, agent_id: "research", tool_preset: "research", soul_mode: "analytical", require_hitl: false },
    };
    const pluginSpec = _nodePlugins.find((p) => p.plugin_id === type);
    const cfg = pluginSpec
      ? { title: `${pluginSpec.label} ${counter}`, agent_id: "default", tool_preset: "minimal", soul_mode: "default", require_hitl: false }
      : (defaults[type] || defaults.agent);

    const pluginParams = {};
    if (pluginSpec && Array.isArray(pluginSpec.params_schema)) {
      pluginSpec.params_schema.forEach((p) => {
        if (p && p.key) pluginParams[p.key] = p.default !== undefined ? p.default : "";
      });
    }

    _activeTpl.nodes.push({
      id: nid,
      title: cfg.title,
      type,
      plugin_id: pluginSpec ? pluginSpec.plugin_id : undefined,
      plugin_params: pluginSpec ? pluginParams : undefined,
      agent_id: cfg.agent_id,
      tool_preset: cfg.tool_preset,
      allowed_tools: [...(PRESET_TOOLS[cfg.tool_preset] || [])],
      forbidden_actions: [],
      soul_mode: cfg.soul_mode,
      reasoning_effort: "medium",
      prompt: `Bearbeite {{topic}} in Station '${cfg.title}'.`,
      expected_output: "",
      depends_on: prevId ? [prevId] : [],
      require_hitl: cfg.require_hitl,
      max_retries: 1,
      timeout_sec: 300,
      x: newX,
      y: newY,
    });
    if (prevId) getEdgeMeta(prevId, nid);
    _selectedNodeId = nid;
    _selectedEdge = null;
    _dirty = true;
    renderAll();
  }

  function buildEdgesSvgHtml(nodes) {
    const byId = {};
    nodes.forEach((n) => (byId[n.id] = n));
    let paths = "";
    let pills = "";
    nodes.forEach((target) => {
      (target.depends_on || []).forEach((srcId) => {
        const src = byId[srcId];
        if (!src) return;
        const meta = getEdgeMeta(srcId, target.id);
        const isSel = _selectedEdge && _selectedEdge.from === srcId && _selectedEdge.to === target.id;
        const x1 = (src.x || 0) + NODE_W;
        const y1 = (src.y || 0) + NODE_H / 2;
        const x2 = target.x || 0;
        const y2 = (target.y || 0) + NODE_H / 2;
        const dx = Math.max(50, Math.abs(x2 - x1) * 0.45);
        const cx1 = x1 + dx;
        const cx2 = x2 - dx;
        const mx = (x1 + x2) / 2;
        const my = (y1 + y2) / 2;
        const strokeCol = isSel
          ? "#f59e0b"
          : meta.condition === "on_failure"
          ? "#f43f5e"
          : meta.condition === "if_expr"
          ? "#10b981"
          : "rgba(99,102,241,0.75)";
        const pillText = meta.label || EDGE_CONDITION_LABELS[meta.condition] || "bei Erfolg";
        const pillW = Math.max(58, pillText.length * 6.4 + 16);

        paths += `<path d="M ${x1} ${y1} C ${cx1} ${y1}, ${cx2} ${y2}, ${x2} ${y2}" fill="none" stroke="${strokeCol}" stroke-width="${isSel ? 3 : 2.2}" marker-end="url(#wf-ed-arrow)" />`;
        pills += `
          <g class="wf-edge-select cursor-pointer" data-from="${esc(srcId)}" data-to="${esc(target.id)}" style="pointer-events:all;">
            <rect x="${mx - pillW / 2}" y="${my - 10}" width="${pillW}" height="20" rx="10" fill="var(--card)" stroke="${strokeCol}" stroke-width="${isSel ? 2 : 1.2}" />
            <text x="${mx}" y="${my + 3.5}" text-anchor="middle" font-size="10" font-family="monospace" fill="var(--foreground)">${esc(pillText)}</text>
          </g>`;
      });
    });
    return { paths, pills };
  }

  function updateCanvasEdgesDom() {
    const svg = document.getElementById("wf-canvas-svg");
    if (!svg || !_activeTpl) return;
    const { paths, pills } = buildEdgesSvgHtml(_activeTpl.nodes);
    const g = svg.querySelector("#wf-svg-content");
    if (g) g.innerHTML = paths + pills;
    bindEdgeSelectHandlers();
  }

  function bindEdgeSelectHandlers() {
    document.querySelectorAll(".wf-edge-select").forEach((el) => {
      el.onclick = (ev) => {
        ev.stopPropagation();
        _selectedEdge = { from: el.getAttribute("data-from"), to: el.getAttribute("data-to") };
        _selectedNodeId = null;
        renderAll();
      };
    });
  }

  function renderCanvasHtml() {
    if (!_activeTpl) return '<div class="p-6 text-xs text-[var(--muted-foreground)]">Keine Vorlage geladen.</div>';
    ensurePositions(_activeTpl);
    const nodes = _activeTpl.nodes || [];
    const maxX = Math.max(1100, ...nodes.map((n) => (n.x || 0) + NODE_W + 140));
    const maxY = Math.max(520, ...nodes.map((n) => (n.y || 0) + NODE_H + 120));
    const { paths, pills } = buildEdgesSvgHtml(nodes);

    const nodesHtml = nodes
      .map((n) => {
        const isSel = _selectedNodeId === n.id;
        const isSrc = _connectFromId === n.id;
        const plMeta = _nodePlugins.find((x) => x.plugin_id === n.type);
        const badgeCls =
          n.type === "gate"
            ? "bg-amber-500/20 text-amber-300 border-amber-500/40"
            : n.type === "quality_gate"
            ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
            : n.type === "fanout" || n.type === "map" || n.type === "dynamic_fanout"
            ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
            : n.type === "boardroom"
            ? "bg-rose-500/20 text-rose-300 border-rose-500/40"
            : n.type === "research"
            ? "bg-sky-500/20 text-sky-300 border-sky-500/40"
            : plMeta
            ? "bg-cyan-500/20 text-cyan-300 border-cyan-500/40"
            : "bg-indigo-500/20 text-indigo-300 border-indigo-500/40";
        const typeLabel =
          n.type === "gate"
            ? "HITL-Gate"
            : n.type === "quality_gate"
            ? "Anti-Slop QA"
            : n.type === "fanout"
            ? "Parallel"
            : n.type === "map" || n.type === "dynamic_fanout"
            ? "Map-Fanout"
            : n.type === "boardroom"
            ? "Boardroom"
            : n.type === "research"
            ? "Research Lab"
            : plMeta
            ? `${plMeta.icon || "🔌"} ${plMeta.label}`
            : "Agent";
        const liveState = _liveNodeStates[n.id];
        const livePillHtml = liveState
          ? `<span data-wf-live-pill="1" class="absolute -top-2 right-2 px-1.5 py-0.5 rounded-full text-[9px] font-mono font-bold shadow-xs pointer-events-none ${
              liveState.status === "running"
                ? "bg-sky-500 text-white animate-pulse"
                : liveState.status === "completed" || liveState.status === "skipped_cached"
                ? "bg-emerald-600 text-white"
                : liveState.status === "awaiting_gate"
                ? "bg-amber-500 text-black"
                : "bg-rose-600 text-white"
            }">${esc(liveState.quality_score != null ? `${liveState.status} · Q${liveState.quality_score}` : liveState.status)}</span>`
          : "";
        const guardCount = (n.forbidden_actions || []).length;
        const toolCount = (n.allowed_tools || []).length;
        return `
          <div data-wf-card="${esc(n.id)}"
            style="left:${n.x || 40}px;top:${n.y || 40}px;width:${NODE_W}px;height:${NODE_H}px;z-index:10;"
            class="absolute rounded-xl border px-3 py-2 bg-[var(--card)] shadow-sm select-none cursor-grab active:cursor-grabbing flex flex-col justify-between transition-shadow ${
              isSrc
                ? "border-emerald-400 ring-2 ring-emerald-500/50"
                : isSel
                ? "border-indigo-400 ring-2 ring-indigo-500/40"
                : "border-[var(--border)] hover:border-indigo-400/60"
            }">
            <button type="button" data-port-in="${esc(n.id)}" title="Eingangs-Port"
              class="absolute -left-2.5 top-1/2 -translate-y-1/2 w-5 h-5 rounded-full border-2 border-[var(--border)] bg-[var(--page-bg)] hover:border-indigo-400 hover:bg-indigo-500/30 flex items-center justify-center text-[9px] font-mono cursor-crosshair">●</button>
            ${livePillHtml}
            <div class="flex items-center justify-between gap-1 pointer-events-none">
              <span class="text-[9px] font-mono px-1.5 py-0.5 rounded border ${badgeCls}">${typeLabel}</span>
              <span class="text-[10px] font-mono text-[var(--muted-foreground)] truncate">${esc(n.agent_id)}</span>
            </div>
            <div class="text-[11px] font-semibold text-[var(--foreground)] line-clamp-2 leading-tight pointer-events-none">${esc(n.title)}</div>
            <div class="flex items-center justify-between text-[9px] font-mono text-[var(--muted-foreground)] pointer-events-none">
              <span>${toolCount} Tools</span>
              <span>${guardCount ? `${guardCount} Verbote` : "Standard"}</span>
            </div>
            <button type="button" data-port-out="${esc(n.id)}" title="Ausgangs-Port (klicken → Ziel wählen)"
              class="absolute -right-2.5 top-1/2 -translate-y-1/2 w-5 h-5 rounded-full border-2 ${
                isSrc ? "border-emerald-400 bg-emerald-500 text-white" : "border-indigo-400/70 bg-[var(--page-bg)] hover:bg-indigo-500/30"
              } flex items-center justify-center text-[9px] font-mono cursor-crosshair">→</button>
          </div>`;
      })
      .join("");

    return `
      <div id="wf-canvas-scroll" class="relative flex-1 min-h-0 overflow-auto bg-[var(--page-bg)] select-none"
        style="background-image: radial-gradient(var(--border) 1.2px, transparent 1.2px); background-size: 20px 20px; background-attachment: local;">
        <div id="wf-canvas-stage" class="relative" style="width:${maxX}px;height:${maxY}px;">
          <svg id="wf-canvas-svg" width="${maxX}" height="${maxY}" class="absolute inset-0 pointer-events-none" style="z-index:5;">
            <defs>
              <marker id="wf-ed-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 1 L 10 5 L 0 9 z" fill="rgba(99,102,241,0.85)" />
              </marker>
            </defs>
            <g id="wf-svg-content">${paths}${pills}</g>
          </svg>
          ${nodesHtml}
        </div>
      </div>`;
  }

  function renderEdgeInspector(edge) {
    const meta = getEdgeMeta(edge.from, edge.to);
    return `
      <div class="space-y-2.5 text-xs">
        <div class="flex items-center justify-between pb-1 border-b border-[var(--border)]">
          <span class="text-[10px] font-mono uppercase tracking-wider text-amber-300">Verbindung konfigurieren</span>
          <button type="button" id="wf-edge-unlink" class="text-[11px] text-rose-400 hover:underline">Trennen</button>
        </div>
        <div class="text-[11px] font-mono bg-[var(--page-bg)] px-2.5 py-1.5 rounded border border-[var(--border)]">
          ${esc(edge.from)} → ${esc(edge.to)}
        </div>
        <label class="block space-y-1">
          <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Auslöse-Bedingung</span>
          <select id="wf-edge-cond" class="w-full px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--page-bg)]">
            <option value="on_success" ${meta.condition === "on_success" ? "selected" : ""}>Nur bei Erfolg (Standard)</option>
            <option value="always" ${meta.condition === "always" ? "selected" : ""}>Immer nach Abschluss</option>
            <option value="on_failure" ${meta.condition === "on_failure" ? "selected" : ""}>Nur bei Fehler / Fallback</option>
            <option value="if_expr" ${meta.condition === "if_expr" ? "selected" : ""}>Bedingt (Ausdruck / Regel)</option>
          </select>
        </label>
        <label class="block space-y-1">
          <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Datenübergabe an nächste Station</span>
          <select id="wf-edge-data" class="w-full px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--page-bg)]">
            <option value="full_output" ${meta.data_mode === "full_output" ? "selected" : ""}>Vollständiges Ergebnis</option>
            <option value="summary_only" ${meta.data_mode === "summary_only" ? "selected" : ""}>Nur Kurzzusammenfassung</option>
            <option value="artifacts_only" ${meta.data_mode === "artifacts_only" ? "selected" : ""}>Nur erzeugte Dateien / Artefakte</option>
            <option value="context_passthrough" ${meta.data_mode === "context_passthrough" ? "selected" : ""}>Gesamter Workflow-Kontext</option>
          </select>
        </label>
        <label class="block space-y-1">
          <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Beschriftung auf Linie / Regel</span>
          <input id="wf-edge-label" value="${esc(meta.label || "")}" placeholder="z. B. Score ≥ 80% oder QA ok" class="w-full px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--page-bg)]" />
        </label>
      </div>`;
  }

  function renderNodeInspector(node) {
    const agentOpts = Array.from(new Set([..._agents, node.agent_id]));
    const tabBtn = (id, label) => `
      <button type="button" data-ins-tab="${id}" class="flex-1 py-1 rounded text-[10px] font-mono font-semibold transition ${
        _inspectorTab === id ? "bg-indigo-600 text-white" : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
      }">${label}</button>`;

    let tabBody = "";
    if (_inspectorTab === "prompt") {
      tabBody = `
        <div class="space-y-2 text-xs">
          <label class="block space-y-0.5">
            <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Stationstitel</span>
            <input id="wf-ins-title" value="${esc(node.title)}" class="w-full px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--page-bg)]" />
          </label>
          <div class="grid grid-cols-2 gap-2">
            <label class="block space-y-0.5">
              <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Typ</span>
              <select id="wf-ins-type" class="w-full px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--page-bg)]">
                <option value="agent" ${node.type === "agent" ? "selected" : ""}>Agent</option>
                <option value="fanout" ${node.type === "fanout" ? "selected" : ""}>Parallel</option>
                <option value="gate" ${node.type === "gate" ? "selected" : ""}>HITL-Gate</option>
                <option value="boardroom" ${node.type === "boardroom" ? "selected" : ""}>Boardroom-Debatte</option>
                <option value="research" ${node.type === "research" ? "selected" : ""}>Research Lab</option>
                ${_nodePlugins
                  .map(
                    (pl) =>
                      `<option value="${esc(pl.plugin_id)}" ${node.type === pl.plugin_id ? "selected" : ""}>${esc(pl.icon || "🔌")} ${esc(pl.label)}</option>`
                  )
                  .join("")}
              </select>
            </label>
            <label class="block space-y-0.5">
              <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Agent / Profil</span>
              <select id="wf-ins-agent" class="w-full px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--page-bg)] font-mono">
                ${
                  _profiles.length
                    ? `<optgroup label="Meine Agenten-Profile">${_profiles
                        .map((p) => `<option value="${esc(p.id)}" ${node.agent_id === p.id ? "selected" : ""}>${esc(p.label)}</option>`)
                        .join("")}</optgroup>`
                    : ""
                }
                <optgroup label="Standard-Rollen">
                  ${agentOpts
                    .filter((a) => !_profiles.some((p) => p.id === a))
                    .map((a) => `<option value="${esc(a)}" ${node.agent_id === a ? "selected" : ""}>${esc(a)}</option>`)
                    .join("")}
                </optgroup>
              </select>
            </label>
          </div>
          <label class="block space-y-0.5">
            <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Aufgaben-Prompt ({{topic}}, {{channel}})</span>
            <textarea id="wf-ins-prompt" rows="5" class="w-full px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--page-bg)] leading-relaxed">${esc(node.prompt || "")}</textarea>
          </label>
          <label class="block space-y-0.5">
            <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Erwarteter Output (Format / Abnahmekriterium)</span>
            <textarea id="wf-ins-expected" rows="2" placeholder="z. B. Markdown-Report mit 5 belegten Quellen" class="w-full px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--page-bg)]">${esc(node.expected_output || "")}</textarea>
          </label>
          ${(() => {
            const pl = _nodePlugins.find((x) => x.plugin_id === node.type);
            if (!pl || !Array.isArray(pl.params_schema) || !pl.params_schema.length) return "";
            const pvals = node.plugin_params || {};
            const fieldsHtml = pl.params_schema
              .map((ps) => {
                const val = pvals[ps.key] !== undefined ? pvals[ps.key] : (ps.default !== undefined ? ps.default : "");
                if (ps.type === "checkbox") {
                  return `<label class="flex items-center gap-2 text-[11px] cursor-pointer pt-1">
                    <input type="checkbox" data-plugin-param="${esc(ps.key)}" data-param-type="checkbox" ${val ? "checked" : ""} />
                    <span>${esc(ps.label)}</span>
                  </label>`;
                }
                if (ps.type === "select") {
                  return `<label class="block space-y-0.5">
                    <span class="text-[10px] font-mono text-[var(--muted-foreground)]">${esc(ps.label)}</span>
                    <select data-plugin-param="${esc(ps.key)}" data-param-type="select" class="w-full px-2 py-1 rounded border border-[var(--border)] bg-[var(--page-bg)] font-mono text-[11px]">
                      ${(ps.options || []).map((o) => `<option value="${esc(o)}" ${String(val) === String(o) ? "selected" : ""}>${esc(o)}</option>`).join("")}
                    </select>
                  </label>`;
                }
                if (ps.type === "textarea") {
                  return `<label class="block space-y-0.5">
                    <span class="text-[10px] font-mono text-[var(--muted-foreground)]">${esc(ps.label)}</span>
                    <textarea rows="2" data-plugin-param="${esc(ps.key)}" data-param-type="textarea" placeholder="${esc(ps.placeholder || "")}" class="w-full px-2 py-1 rounded border border-[var(--border)] bg-[var(--page-bg)] text-[11px]">${esc(val)}</textarea>
                  </label>`;
                }
                const itype = ps.type === "number" ? "number" : "text";
                return `<label class="block space-y-0.5">
                  <span class="text-[10px] font-mono text-[var(--muted-foreground)]">${esc(ps.label)}</span>
                  <input type="${itype}" ${ps.min !== undefined ? `min="${ps.min}"` : ""} ${ps.max !== undefined ? `max="${ps.max}"` : ""} ${ps.step !== undefined ? `step="${ps.step}"` : ""} data-plugin-param="${esc(ps.key)}" data-param-type="${itype}" value="${esc(val)}" placeholder="${esc(ps.placeholder || "")}" class="w-full px-2 py-1 rounded border border-[var(--border)] bg-[var(--page-bg)] font-mono text-[11px]" />
                </label>`;
              })
              .join("");
            return `<div class="p-2 rounded-lg border border-indigo-500/30 bg-indigo-500/5 space-y-2">
              <div class="flex items-center justify-between">
                <span class="text-[10px] font-mono font-bold text-indigo-300">${esc(pl.icon || "🔌")} ${esc(pl.label)} — Parameter</span>
                <span class="text-[9px] font-mono text-[var(--muted-foreground)]">${esc(pl.adapter || "local")}</span>
              </div>
              ${fieldsHtml}
            </div>`;
          })()}
        </div>`;
    } else if (_inspectorTab === "tools") {
      const allowed = new Set(node.allowed_tools || []);
      tabBody = `
        <div class="space-y-2.5 text-xs">
          <div class="grid grid-cols-2 gap-2">
            <label class="block space-y-0.5">
              <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Tool-Preset</span>
              <select id="wf-ins-tools" class="w-full px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--page-bg)] font-mono">
                ${["research", "coding", "minimal", "full"].map((p) => `<option value="${p}" ${node.tool_preset === p ? "selected" : ""}>${p}</option>`).join("")}
              </select>
            </label>
            <label class="block space-y-0.5">
              <span class="text-[10px] font-mono text-[var(--muted-foreground)]">SOUL-Modus</span>
              <select id="wf-ins-soul" class="w-full px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--page-bg)] font-mono">
                ${["analytical", "creative", "strict", "default"].map((s) => `<option value="${s}" ${node.soul_mode === s ? "selected" : ""}>${s}</option>`).join("")}
              </select>
            </label>
          </div>
          <div class="space-y-1">
            <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Erlaubte Tools dieser Station</span>
            <div class="grid grid-cols-2 gap-1.5 bg-[var(--page-bg)] p-2 rounded border border-[var(--border)]">
              ${ALL_TOOLS.map(
                (t) => `<label class="flex items-center gap-1.5 text-[11px] cursor-pointer">
                  <input type="checkbox" data-tool-chk="${esc(t.id)}" ${allowed.has(t.id) ? "checked" : ""} />
                  <span class="truncate">${esc(t.label)}</span>
                </label>`
              ).join("")}
            </div>
          </div>
          <div class="grid grid-cols-2 gap-2">
            <label class="block space-y-0.5">
              <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Reasoning</span>
              <select id="wf-ins-reasoning" class="w-full px-2 py-1 rounded border border-[var(--border)] bg-[var(--page-bg)] font-mono">
                ${["low", "medium", "high"].map((r) => `<option value="${r}" ${(node.reasoning_effort || "medium") === r ? "selected" : ""}>${r}</option>`).join("")}
              </select>
            </label>
            <label class="block space-y-0.5">
              <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Kosten-Cap ($)</span>
              <input id="wf-ins-cost" type="number" step="0.05" min="0" value="${esc(node.cost_limit_usd ?? "")}" placeholder="z. B. 0.50" class="w-full px-2 py-1 rounded border border-[var(--border)] bg-[var(--page-bg)] font-mono" />
            </label>
          </div>
          <label class="flex items-center gap-2 pt-0.5 cursor-pointer">
            <input type="checkbox" id="wf-ins-hitl" ${node.require_hitl || node.type === "gate" ? "checked" : ""} />
            <span class="text-[11px]">Menschliche Freigabe (HITL) erzwingen</span>
          </label>
        </div>`;
    } else {
      const activeGuards = new Set(node.forbidden_actions || []);
      const customLines = (node.forbidden_actions || []).filter((g) => !STANDARD_GUARDRAILS.includes(g)).join("\n");
      tabBody = `
        <div class="space-y-2.5 text-xs">
          <span class="text-[10px] font-mono text-[var(--muted-foreground)] block">Was diese Station auf keinen Fall tun darf:</span>
          <div class="space-y-1.5 bg-[var(--page-bg)] p-2 rounded border border-[var(--border)]">
            ${STANDARD_GUARDRAILS.map(
              (g, idx) => `<label class="flex items-start gap-1.5 text-[11px] cursor-pointer leading-tight">
                <input type="checkbox" class="mt-0.5" data-guard-chk="${idx}" ${activeGuards.has(g) ? "checked" : ""} />
                <span>${esc(g)}</span>
              </label>`
            ).join("")}
          </div>
          <label class="block space-y-0.5">
            <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Eigene Verbote / Hard Constraints (1 pro Zeile)</span>
            <textarea id="wf-ins-custom-guards" rows="3" placeholder="z. B. Keine Preise unter 500 EUR anbieten" class="w-full px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--page-bg)]">${esc(customLines)}</textarea>
          </label>
        </div>`;
    }

    const live = _liveNodeStates[node.id];
    const liveCockpitHtml = live
      ? `<div class="p-2 rounded-lg border border-sky-500/30 bg-sky-500/5 space-y-1.5 text-[11px]">
          <div class="flex items-center justify-between gap-1">
            <span class="font-mono font-bold text-sky-300">Live: ${esc(live.status)}${live.quality_score != null ? ` · Q${live.quality_score}` : ""}</span>
            <div class="flex items-center gap-1.5">
              ${live.cost_usd != null ? `<span class="font-mono text-[10px] text-emerald-300">$${Number(live.cost_usd).toFixed(4)}</span>` : ""}
              ${_activeRunId ? `<button type="button" data-wf-refresh-run="1" class="px-1.5 py-0.5 rounded border border-[var(--border)] hover:bg-[var(--secondary)] text-[9px] font-mono">Sync</button>` : ""}
            </div>
          </div>
          ${live.deliverable_path ? `<div class="text-[10px] font-mono text-emerald-300 truncate" title="${esc(live.deliverable_path)}">Datei: ${esc(live.deliverable_path)}</div>` : ""}
          ${live.error ? `<div class="text-[10px] font-mono text-rose-400 break-words">${esc(live.error)}</div>` : ""}
          ${live.output_preview ? `<pre class="max-h-28 overflow-y-auto p-1.5 rounded bg-[var(--page-bg)] border border-[var(--border)] text-[10px] font-mono whitespace-pre-wrap break-words">${esc(live.output_preview)}</pre>` : ""}
          ${
            live.status === "awaiting_gate" && _activeRunId
              ? `<div class="flex items-center gap-1.5 pt-1">
                  <button type="button" data-wf-gate-approve="${esc(node.id)}" class="flex-1 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-mono text-[10px] font-bold">Freigeben</button>
                  <button type="button" data-wf-gate-reject="${esc(node.id)}" class="flex-1 py-1 rounded bg-rose-600 hover:bg-rose-500 text-white font-mono text-[10px] font-bold">Ablehnen</button>
                </div>`
              : ""
          }
        </div>`
      : _activeRunId
      ? `<div class="flex items-center justify-between px-2 py-1 rounded border border-[var(--border)] bg-[var(--page-bg)] text-[10px] font-mono text-[var(--muted-foreground)]">
          <span>Run: ${esc(_activeRunId)} (${_activeRunCostUsd ? `$${Number(_activeRunCostUsd).toFixed(4)}` : "aktiv"})</span>
          <button type="button" data-wf-refresh-run="1" class="text-sky-400 hover:underline">Status laden</button>
        </div>`
      : "";

    return `
      <div class="space-y-2.5">
        <div class="flex items-center justify-between">
          <span class="text-[10px] font-mono uppercase tracking-wider text-indigo-300">Station: ${esc(node.id)}</span>
          <button type="button" id="wf-del-node" class="text-[11px] text-rose-400 hover:underline">Entfernen</button>
        </div>
        ${liveCockpitHtml}
        <div class="flex gap-1 p-1 rounded-lg bg-[var(--page-bg)] border border-[var(--border)]">
          ${tabBtn("prompt", "Prompt")}
          ${tabBtn("tools", "Tools")}
          ${tabBtn("guardrails", "Verbote")}
        </div>
        ${tabBody}
      </div>`;
  }

  function renderInspectorHtml() {
    if (!_activeTpl) return "";
    const node = _selectedNodeId ? _activeTpl.nodes.find((n) => n.id === _selectedNodeId) : null;

    return `
      <aside style="width:340px;min-width:300px;flex-shrink:0;" class="border-l border-[var(--border)] bg-[var(--card)] flex flex-col min-h-0 overflow-y-auto p-3 space-y-3">
        <div class="space-y-1.5 pb-2.5 border-b border-[var(--border)]">
          <div class="flex items-center justify-between">
            <span class="text-[10px] font-mono uppercase tracking-wider text-[var(--muted-foreground)]">Ablaufplan</span>
            <div class="flex items-center gap-2">
              ${_dirty ? '<span class="text-[10px] font-mono text-amber-400">Ungespeichert</span>' : ""}
              ${!_activeTpl.builtin ? `<button type="button" id="wf-del-tpl-btn" class="text-[10px] text-rose-400 hover:underline">Löschen</button>` : ""}
            </div>
          </div>
          <input id="wf-meta-title" value="${esc(_activeTpl.title)}" class="w-full px-2.5 py-1.5 rounded border border-[var(--border)] bg-[var(--page-bg)] text-xs font-semibold" placeholder="Workflow-Name" />
          <input id="wf-meta-desc" value="${esc(_activeTpl.description || "")}" class="w-full px-2.5 py-1 rounded border border-[var(--border)] bg-[var(--page-bg)] text-[11px]" placeholder="Kurzbeschreibung" />
        </div>

        ${
          _selectedEdge
            ? renderEdgeInspector(_selectedEdge)
            : node
            ? renderNodeInspector(node)
            : '<div class="text-xs text-[var(--muted-foreground)]">Station oder Verbindungslinie anklicken, um Prompt, Tools, Verbote oder Bedingungen einzustellen.</div>'
        }

        <div class="pt-2.5 border-t border-[var(--border)] space-y-2 mt-auto">
          <button type="button" id="wf-toggle-run-params" class="w-full flex items-center justify-between text-[11px] font-mono text-[var(--muted-foreground)] hover:text-[var(--foreground)]">
            <span>Cron-Zeitplan & Watchdog-Trigger (${_schedules.filter((s) => s.template_id === _activeTpl.id && s.enabled).length} aktiv)</span>
            <span>${_runParamsOpen ? "▾" : "▸"}</span>
          </button>
          ${
            _runParamsOpen
              ? `<div class="space-y-2 text-xs bg-[var(--page-bg)] p-2 rounded-lg border border-[var(--border)]">
                  ${(_activeTpl.inputs || [])
                    .map(
                      (inp) => `<label class="block space-y-0.5">
                        <span class="text-[10px] font-mono text-[var(--muted-foreground)]">${esc(inp.label || inp.key)}</span>
                        <input data-wf-input="${esc(inp.key)}" value="${esc(inp.default || "")}" class="w-full px-2 py-1 rounded border border-[var(--border)] bg-[var(--card)]" />
                      </label>`
                    )
                    .join("")}
                  <label class="block space-y-0.5">
                    <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Auslöser (Trigger)</span>
                    <select id="wf-sched-trigger" class="w-full px-2 py-1 rounded border border-[var(--border)] bg-[var(--card)]">
                      <option value="cron">Nur Cron-Zeitplan</option>
                      <option value="watchdog">Watchdog-Fund (Radar)</option>
                      <option value="inbox">Posteingang (E-Mail / Rechnung / Drop)</option>
                      <option value="research">Research Lab (Neues Ergebnis)</option>
                      <option value="boardroom">AI Boardroom (Neuer Beschluss)</option>
                      <option value="calendar">Kalender (Fälliger Termin / Frist)</option>
                      <option value="approval">Freigaben (HITL / E-Mail-Entscheidung)</option>
                      <option value="cron_and_watchdog">Cron + Watchdog-Fund</option>
                      <option value="any_event">Jedes System-Event (Alle Quellen)</option>
                    </select>
                  </label>
                  <input id="wf-run-cron" value="${esc(_activeTpl.schedule_hint || "")}" placeholder="Cron (z. B. 0 8 * * 1 oder @daily)" class="w-full px-2 py-1 rounded border border-[var(--border)] bg-[var(--card)] font-mono" />
                  <div class="grid grid-cols-2 gap-1.5">
                    <label class="block space-y-0.5">
                      <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Startzeitpunkt</span>
                      <input id="wf-sched-start" type="datetime-local" class="w-full px-1.5 py-1 rounded border border-[var(--border)] bg-[var(--card)] text-[10px]" />
                    </label>
                    <label class="block space-y-0.5">
                      <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Endzeitpunkt</span>
                      <input id="wf-sched-end" type="datetime-local" class="w-full px-1.5 py-1 rounded border border-[var(--border)] bg-[var(--card)] text-[10px]" />
                    </label>
                  </div>
                  <div class="grid grid-cols-2 gap-1.5">
                    <select id="wf-sched-start-cond" class="px-1.5 py-1 rounded border border-[var(--border)] bg-[var(--card)] text-[10px]">
                      <option value="always">Start: Immer</option>
                      <option value="no_active_run">Start: Kein offener Run</option>
                    </select>
                    <select id="wf-sched-end-cond" class="px-1.5 py-1 rounded border border-[var(--border)] bg-[var(--card)] text-[10px]">
                      <option value="none">Ende: Bis Enddatum</option>
                      <option value="max_runs">Ende: Nach N Runs</option>
                      <option value="on_error_stop">Ende: Bei Fehler stoppen</option>
                    </select>
                  </div>
                  <div class="grid grid-cols-2 gap-1.5">
                    <input id="wf-sched-max-runs" type="number" min="1" placeholder="Max. Runs (optional)" class="px-2 py-1 rounded border border-[var(--border)] bg-[var(--card)] font-mono text-[10px]" />
                    <input id="wf-sched-kw" placeholder="Watchdog-Keywords (Komma)" class="px-2 py-1 rounded border border-[var(--border)] bg-[var(--card)] text-[10px]" />
                  </div>
                  <input id="wf-run-n8n" value="${esc(_activeTpl.n8n_webhook_hint || "")}" placeholder="Optionaler n8n-Webhook" class="w-full px-2 py-1 rounded border border-[var(--border)] bg-[var(--card)] font-mono" />
                  <button type="button" id="wf-sched-save-btn" class="w-full px-2.5 py-1.5 rounded bg-emerald-600/25 hover:bg-emerald-600/40 border border-emerald-500/40 text-emerald-200 text-[11px] font-semibold">
                    Automation (Cron / Watchdog) aktivieren
                  </button>
                  ${_schedules
                    .filter((s) => s.template_id === _activeTpl.id)
                    .map(
                      (s) => `<div class="flex items-center justify-between gap-1 px-2 py-1 rounded border border-[var(--border)] bg-[var(--card)] text-[10px] font-mono">
                        <span class="truncate">${s.enabled ? "●" : "○"} ${esc(s.trigger_type)} ${esc(s.cron_expr || s.watchdog_keyword || "auto")} (${s.run_count}x)</span>
                        <button type="button" data-del-sched="${esc(s.id)}" class="text-rose-400 hover:text-rose-300">✕</button>
                      </div>`
                    )
                    .join("")}
                </div>`
              : ""
          }
          <button type="button" id="wf-goto-kanban" class="hidden w-full px-3 py-1.5 rounded-lg border border-[var(--border)] text-xs hover:bg-[var(--secondary)]">Im Kanban / Graph ansehen</button>
        </div>
      </aside>`;
  }

  const PALETTE_CATEGORIES = [
    { id: "standard", label: "Standard", icon: "⚙️" },
    { id: "audio", label: "Musik & Audio", icon: "🎵" },
    { id: "video", label: "Video & Schnitt", icon: "🎬" },
    { id: "design", label: "Bild & Design", icon: "🖼️" },
    { id: "docs", label: "Dokumente & Slides", icon: "📑" },
    { id: "research", label: "Research & Scraping", icon: "🔍" },
    { id: "business", label: "Publishing & Business", icon: "📅" },
  ];

  const STANDARD_PALETTE_ITEMS = [
    { type: "agent", label: "Agent", icon: "🤖", desc: "Einzelner KI-Spezialist mit Prompt & Tools" },
    { type: "fanout", label: "Parallel / Fanout", icon: "⚡", desc: "Parallele Zweige mit Quorum-Zusammenfuehrung" },
    { type: "gate", label: "HITL-Gate", icon: "🛡️", desc: "Menschliche Freigabe vor dem naechsten Schritt" },
    { type: "boardroom", label: "Boardroom", icon: "🏛️", desc: "Multi-Rollen-Debatte im AI Boardroom" },
    { type: "research", label: "Research Lab", icon: "🧪", desc: "Tiefenrecherche mit Quellenbeleg" },
  ];

  function renderBottomPaletteHtml() {
    const tabsHtml = PALETTE_CATEGORIES.map((c) => {
      const active = _paletteTab === c.id;
      return `<button type="button" data-palette-tab="${c.id}"
        style="${active ? "border-bottom:2px solid #6366f1;margin-bottom:-1px;" : ""}"
        class="px-3 py-1.5 rounded-t-lg text-[11px] font-medium whitespace-nowrap flex items-center gap-1.5 transition border border-b-0 ${
          active
            ? "bg-[var(--page-bg)] border-[var(--border)] text-[var(--foreground)] font-semibold"
            : "bg-transparent border-transparent text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--secondary)]/50"
        }">
        <span>${c.icon}</span>
        <span>${esc(c.label)}</span>
      </button>`;
    }).join("");

    let items = [];
    if (_paletteTab === "standard") {
      items = STANDARD_PALETTE_ITEMS;
    } else {
      items = _nodePlugins
        .filter((p) => (p.category || "business") === _paletteTab)
        .map((p) => ({
          type: p.plugin_id,
          label: p.label,
          icon: p.icon || "🔌",
          desc: p.description || "",
          adapter: p.adapter || "local",
        }));
    }

    const itemsHtml = items
      .map(
        (it) => `<div draggable="true" data-palette-type="${esc(it.type)}" data-add-station="${esc(it.type)}"
          title="Auf Matrix ziehen oder klicken"
          style="min-width:190px;max-width:225px;flex:0 0 auto;"
          class="p-2 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:border-indigo-500/60 hover:bg-indigo-500/10 cursor-grab active:cursor-grabbing transition select-none space-y-0.5">
          <div class="flex items-center justify-between gap-1">
            <span class="text-xs font-semibold text-[var(--foreground)] truncate">${esc(it.icon)} ${esc(it.label)}</span>
            ${it.adapter ? `<span class="text-[9px] font-mono px-1 rounded bg-[var(--page-bg)] text-[var(--muted-foreground)]">${esc(it.adapter)}</span>` : ""}
          </div>
          <div class="text-[10px] text-[var(--muted-foreground)] line-clamp-2 leading-snug">${esc(it.desc)}</div>
        </div>`
      )
      .join("");

    const plusCardHtml = `<button type="button" id="wf-palette-plus-btn"
      title="Baustein aus Marktplatz oder per GitHub-URL hinzufügen"
      style="min-width:64px;flex:0 0 auto;"
      class="px-4 py-2 rounded-lg border border-dashed border-indigo-500/50 hover:border-indigo-400 bg-indigo-500/5 hover:bg-indigo-500/15 text-indigo-300 flex flex-col items-center justify-center gap-0.5 transition cursor-pointer">
      <span class="text-lg font-bold leading-none">+</span>
    </button>`;

    return `
      <section style="flex-shrink:0;" class="border-t border-[var(--border)] bg-[var(--card)]/70 flex flex-col">
        <div class="px-3 pt-1.5 border-b border-[var(--border)] flex items-center justify-between gap-2 overflow-x-auto">
          <div class="flex items-end gap-1">${tabsHtml}</div>
          <span class="text-[9px] font-mono text-[var(--muted-foreground)] whitespace-nowrap pb-1 hidden lg:inline">Baustein auf Matrix ziehen oder klicken</span>
        </div>
        <div style="overflow-x:auto;" class="p-2.5 bg-[var(--page-bg)] flex items-stretch gap-2">${itemsHtml}${plusCardHtml}</div>
      </section>`;
  }

  function createBlankWorkflow() {
    return {
      id: "",
      title: "Neuer Workflow",
      category: "Eigene Workflows",
      description: "",
      header_image: "",
      schedule_hint: "",
      n8n_webhook_hint: "",
      inputs: [{ key: "topic", label: "Thema / Ziel", default: "" }],
      builtin: false,
      edges: [],
      nodes: [],
    };
  }

  function rememberActiveTemplateId(id) {
    try {
      if (id) localStorage.setItem("archon_wf_last_active_id", String(id));
    } catch (_) {}
  }

  function renderAll() {
    const mount = document.getElementById("ops-workflow-templates-mount");
    if (!mount) return;

    const connectHint = _connectFromId
      ? `<span class="text-[11px] font-mono text-emerald-300 bg-emerald-500/15 border border-emerald-500/40 px-2 py-0.5 rounded">Verknüpfung ab <b>${esc(_connectFromId)}</b> → Ziel-Station anklicken (Esc = Abbruch)</span>`
      : _connectMode
      ? `<span class="text-[11px] font-mono text-indigo-300 bg-indigo-500/15 border border-indigo-500/40 px-2 py-0.5 rounded">Quell-Station anklicken…</span>`
      : `<span id="wf-run-status" class="text-[11px] font-mono text-[var(--muted-foreground)] truncate">Baustein auf Matrix ziehen · → Port verknüpft</span>`;

    const wfTitle = _activeTpl ? `${_activeTpl.title}${_dirty ? " *" : ""}` : "Kein Workflow geladen";
    const wfDesc = _activeTpl
      ? (_activeTpl.description || "Keine Beschreibung hinterlegt.")
      : "Über '📂 Öffnen' eine Vorlage laden oder mit '+ Neu' starten.";

    mount.innerHTML = `
      <div style="display:flex;flex-direction:column;flex:1;min-height:0;overflow:hidden;">
        <div class="px-3 py-2 border-b border-[var(--border)] bg-[var(--card)] flex items-stretch justify-between gap-4 shrink-0">
          <div class="flex flex-col justify-between gap-1.5 min-w-0">
            <div class="flex flex-wrap items-center gap-1.5">
              <button type="button" id="wf-connect-toggle" class="px-2.5 py-1 rounded-lg border text-xs font-semibold ${
                _connectMode || _connectFromId
                  ? "border-emerald-400 bg-emerald-500/20 text-emerald-200"
                  : "border-[var(--border)] hover:bg-[var(--secondary)]"
              }">Verknüpfen</button>
              <button type="button" id="wf-auto-layout" class="px-2.5 py-1 rounded-lg border border-[var(--border)] hover:bg-[var(--secondary)] text-xs">Auto-Layout</button>
              <span class="mx-1 h-4 w-px bg-[var(--border)]"></span>
              <button type="button" id="wf-blank-btn" class="px-2.5 py-1 rounded-lg border border-indigo-500/40 bg-indigo-500/15 hover:bg-indigo-500/25 text-indigo-200 text-xs font-semibold">+ Neu</button>
              <button type="button" id="wf-open-browser-btn" class="px-2.5 py-1 rounded-lg border border-[var(--border)] hover:bg-[var(--secondary)] text-xs font-semibold">📂 Öffnen</button>
              <button type="button" id="wf-save-dialog-btn" ${_activeTpl ? "" : "disabled"} class="px-2.5 py-1 rounded-lg border border-emerald-500/40 bg-emerald-500/15 hover:bg-emerald-500/25 disabled:opacity-40 text-emerald-200 text-xs font-semibold">💾 Speichern</button>
            </div>
            <div class="min-w-0 flex items-center">${connectHint}</div>
          </div>

          <div class="flex items-stretch gap-3 min-w-0 ml-auto">
            <div class="flex flex-col justify-center text-right min-w-0 max-w-md">
              <div class="text-sm font-bold text-[var(--foreground)] truncate leading-tight">${esc(wfTitle)}</div>
              <div class="text-[11px] text-[var(--muted-foreground)] truncate leading-snug mt-0.5">${esc(wfDesc)}</div>
            </div>
            <button type="button" id="wf-header-start-btn" ${_activeTpl ? "" : "disabled"} title="Workflow starten"
              style="min-width:48px;"
              class="px-3.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-35 disabled:cursor-not-allowed text-white flex items-center justify-center shadow-sm transition cursor-pointer shrink-0">
              <svg viewBox="0 0 24 24" class="w-6 h-6 fill-current"><path d="M8 5v14l11-7z"/></svg>
            </button>
          </div>
        </div>
        <div style="display:flex;flex-direction:row;flex:1;min-height:0;overflow:hidden;">
          <div style="flex:1;min-width:0;min-height:0;display:flex;flex-direction:column;overflow:hidden;">
            ${renderCanvasHtml()}
            ${renderBottomPaletteHtml()}
          </div>
          ${renderInspectorHtml()}
        </div>
      </div>`;

    bindAllEvents(mount);
  }

  function syncGuardsFromDom(mount, node) {
    const chosen = [];
    mount.querySelectorAll("[data-guard-chk]").forEach((chk) => {
      if (chk.checked) chosen.push(STANDARD_GUARDRAILS[Number(chk.getAttribute("data-guard-chk"))]);
    });
    const customText = mount.querySelector("#wf-ins-custom-guards")?.value || "";
    customText
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean)
      .forEach((line) => chosen.push(line));
    node.forbidden_actions = chosen;
    _dirty = true;
  }

  function bindAllEvents(mount) {
    mount.querySelectorAll("[data-wf-select]").forEach((btn) => {
      btn.onclick = () => {
        const found = _templates.find((t) => t.id === btn.getAttribute("data-wf-select"));
        if (!found) return;
        _activeTpl = cloneTpl(found);
        ensurePositions(_activeTpl);
        _selectedNodeId = _activeTpl.nodes[0]?.id || null;
        _selectedEdge = null;
        _connectFromId = null;
        _connectMode = false;
        _dirty = false;
        renderAll();
      };
    });

    const searchEl = mount.querySelector("#wf-tpl-search");
    if (searchEl) {
      searchEl.oninput = () => {
        _tplSearch = searchEl.value;
        renderAll();
        const el = document.getElementById("wf-tpl-search");
        if (el) {
          el.focus();
          el.setSelectionRange(el.value.length, el.value.length);
        }
      };
    }
    const catEl = mount.querySelector("#wf-tpl-cat");
    if (catEl) {
      catEl.onchange = () => {
        _tplCat = catEl.value;
        renderAll();
      };
    }
    const impBtn = mount.querySelector("#wf-import-n8n-btn");
    if (impBtn) {
      impBtn.onclick = async () => {
        const raw = prompt("n8n Workflow-JSON hier einfügen (z. B. Export von n8n.io/workflows):");
        if (!raw || !raw.trim()) return;
        try {
          const parsed = JSON.parse(raw);
          const res = await apiJson("/api/v2/workflows/templates/import-n8n", {
            method: "POST",
            body: JSON.stringify({ workflow: parsed }),
          });
          _tplCat = "all";
          _tplSearch = "";
          await loadTemplates(res.template.id);
        } catch (err) {
          alert(`n8n-Import fehlgeschlagen: ${err.message}`);
        }
      };
    }

    const blankBtn = mount.querySelector("#wf-blank-btn");
    if (blankBtn) {
      blankBtn.onclick = () => {
        _activeTpl = {
          id: "",
          title: "Neuer Prozessablauf",
          category: "Eigene Workflows",
          description: "",
          schedule_hint: "",
          n8n_webhook_hint: "",
          inputs: [{ key: "topic", label: "Thema / Ziel", default: "" }],
          builtin: false,
          edges: [],
          nodes: [
            {
              id: "step_1",
              title: "Start-Recherche: {{topic}}",
              type: "agent",
              agent_id: "research",
              tool_preset: "research",
              allowed_tools: [...PRESET_TOOLS.research],
              forbidden_actions: [],
              soul_mode: "analytical",
              reasoning_effort: "medium",
              prompt: "Starte Analyse zu {{topic}}.",
              expected_output: "",
              depends_on: [],
              require_hitl: false,
              x: 60,
              y: 120,
            },
          ],
        };
        _selectedNodeId = "step_1";
        _selectedEdge = null;
        _connectFromId = null;
        _connectMode = false;
        _dirty = true;
        renderAll();
      };
    }

    mount.querySelectorAll("[data-add-station]").forEach((btn) => {
      btn.onclick = () => addStation(btn.getAttribute("data-add-station"));
    });

    mount.querySelectorAll("[data-palette-tab]").forEach((tab) => {
      tab.onclick = () => {
        _paletteTab = tab.getAttribute("data-palette-tab") || "standard";
        renderAll();
      };
    });

    mount.querySelectorAll("[data-palette-type]").forEach((card) => {
      card.addEventListener("dragstart", (ev) => {
        if (ev.dataTransfer) {
          ev.dataTransfer.setData("text/plain", card.getAttribute("data-palette-type") || "agent");
          ev.dataTransfer.effectAllowed = "copy";
        }
      });
    });

    const canvasScroll = mount.querySelector("#wf-canvas-scroll");
    if (canvasScroll) {
      canvasScroll.addEventListener("dragover", (ev) => {
        ev.preventDefault();
        if (ev.dataTransfer) ev.dataTransfer.dropEffect = "copy";
      });
      canvasScroll.addEventListener("drop", (ev) => {
        ev.preventDefault();
        const ptype = ev.dataTransfer ? ev.dataTransfer.getData("text/plain") : "";
        if (!ptype) return;
        const stage = mount.querySelector("#wf-canvas-stage") || canvasScroll;
        const rect = stage.getBoundingClientRect();
        const x = Math.max(20, ev.clientX - rect.left - NODE_W / 2);
        const y = Math.max(20, ev.clientY - rect.top - NODE_H / 2);
        addStation(ptype, x, y);
      });
    }

    const openBrowserBtn = mount.querySelector("#wf-open-browser-btn");
    if (openBrowserBtn) openBrowserBtn.onclick = () => openPresetBrowserModal();

    const saveDlgBtn = mount.querySelector("#wf-save-dialog-btn");
    if (saveDlgBtn) saveDlgBtn.onclick = () => openSaveWorkflowModal();

    const plusBtn = mount.querySelector("#wf-palette-plus-btn");
    if (plusBtn) plusBtn.onclick = () => openNodeMarketplaceModal(_paletteTab);

    const connToggle = mount.querySelector("#wf-connect-toggle");
    if (connToggle) {
      connToggle.onclick = () => {
        if (_connectFromId || _connectMode) {
          _connectFromId = null;
          _connectMode = false;
        } else {
          _connectMode = true;
        }
        renderAll();
      };
    }

    const layoutBtn = mount.querySelector("#wf-auto-layout");
    if (layoutBtn) {
      layoutBtn.onclick = () => {
        if (!_activeTpl) return;
        autoLayoutNodes(_activeTpl.nodes);
        _dirty = true;
        renderAll();
      };
    }

    mount.querySelectorAll("[data-port-out]").forEach((btn) => {
      btn.onclick = (ev) => {
        ev.stopPropagation();
        const sid = btn.getAttribute("data-port-out");
        _connectFromId = _connectFromId === sid ? null : sid;
        _connectMode = false;
        renderAll();
      };
    });

    mount.querySelectorAll("[data-port-in]").forEach((btn) => {
      btn.onclick = (ev) => {
        ev.stopPropagation();
        const tid = btn.getAttribute("data-port-in");
        if (_connectFromId && _connectFromId !== tid) linkNodes(_connectFromId, tid);
      };
    });

    mount.querySelectorAll("[data-wf-card]").forEach((card) => {
      const nid = card.getAttribute("data-wf-card");
      let startX = 0, startY = 0, origX = 0, origY = 0, moved = false;

      card.onmousedown = (ev) => {
        if (ev.target.closest("[data-port-out]") || ev.target.closest("[data-port-in]")) return;
        if (_connectFromId && _connectFromId !== nid) {
          ev.stopPropagation();
          linkNodes(_connectFromId, nid);
          return;
        }
        if (_connectMode) {
          ev.stopPropagation();
          _connectFromId = nid;
          _connectMode = false;
          renderAll();
          return;
        }

        const node = _activeTpl?.nodes.find((n) => n.id === nid);
        if (!node) return;
        startX = ev.clientX;
        startY = ev.clientY;
        origX = node.x || 40;
        origY = node.y || 40;
        moved = false;

        let _edgesRaf = 0;
        const _scheduleEdges = () => {
          if (_edgesRaf) return;
          _edgesRaf = requestAnimationFrame(() => {
            _edgesRaf = 0;
            updateCanvasEdgesDom();
          });
        };
        const onMove = (mv) => {
          const dx = mv.clientX - startX;
          const dy = mv.clientY - startY;
          if (Math.abs(dx) > 3 || Math.abs(dy) > 3) moved = true;
          if (!moved) return;
          node.x = Math.max(20, origX + dx);
          node.y = Math.max(20, origY + dy);
          card.style.left = node.x + "px";
          card.style.top = node.y + "px";
          _scheduleEdges();
        };

        const onUp = () => {
          window.removeEventListener("mousemove", onMove);
          window.removeEventListener("mouseup", onUp);
          if (_edgesRaf) { cancelAnimationFrame(_edgesRaf); _edgesRaf = 0; }
          if (moved) {
            node.x = snap(node.x);
            node.y = snap(node.y);
            _dirty = true;
            renderAll();
          } else {
            _selectedNodeId = nid;
            _selectedEdge = null;
            renderAll();
          }
        };

        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
      };
    });

    bindEdgeSelectHandlers();

    const metaTitle = mount.querySelector("#wf-meta-title");
    if (metaTitle && _activeTpl) metaTitle.oninput = () => { _activeTpl.title = metaTitle.value; _dirty = true; };
    const metaDesc = mount.querySelector("#wf-meta-desc");
    if (metaDesc && _activeTpl) metaDesc.oninput = () => { _activeTpl.description = metaDesc.value; _dirty = true; };

    // Edge-Inspektor
    if (_selectedEdge) {
      const meta = getEdgeMeta(_selectedEdge.from, _selectedEdge.to);
      const condEl = mount.querySelector("#wf-edge-cond");
      const dataEl = mount.querySelector("#wf-edge-data");
      const lblEl = mount.querySelector("#wf-edge-label");
      const unlinkEl = mount.querySelector("#wf-edge-unlink");
      if (condEl) condEl.onchange = () => { meta.condition = condEl.value; _dirty = true; updateCanvasEdgesDom(); };
      if (dataEl) dataEl.onchange = () => { meta.data_mode = dataEl.value; _dirty = true; };
      if (lblEl) lblEl.oninput = () => { meta.label = lblEl.value; _dirty = true; updateCanvasEdgesDom(); };
      if (unlinkEl) unlinkEl.onclick = () => unlinkNodes(_selectedEdge.from, _selectedEdge.to);
    }

    // Node-Inspektor
    const selNode = _selectedNodeId ? _activeTpl?.nodes.find((n) => n.id === _selectedNodeId) : null;
    if (selNode) {
      mount.querySelectorAll("[data-ins-tab]").forEach((b) => {
        b.onclick = () => {
          _inspectorTab = b.getAttribute("data-ins-tab");
          renderAll();
        };
      });

      const bindVal = (sel, prop, transform, rerender) => {
        const el = mount.querySelector(sel);
        if (!el) return;
        el.oninput = el.onchange = () => {
          selNode[prop] = transform ? transform(el) : el.value;
          _dirty = true;
          if (rerender) renderAll();
        };
      };
      bindVal("#wf-ins-title", "title", null, false);
      bindVal("#wf-ins-type", "type", null, true);
      bindVal("#wf-ins-agent", "agent_id", null, true);
      bindVal("#wf-ins-prompt", "prompt", null, false);
      bindVal("#wf-ins-expected", "expected_output", null, false);
      bindVal("#wf-ins-soul", "soul_mode", null, false);
      bindVal("#wf-ins-reasoning", "reasoning_effort", null, false);
      bindVal("#wf-ins-cost", "cost_limit_usd", (el) => (el.value === "" ? null : Number(el.value)), false);
      bindVal("#wf-ins-hitl", "require_hitl", (el) => el.checked, false);

      mount.querySelectorAll("[data-plugin-param]").forEach((el) => {
        const key = el.getAttribute("data-plugin-param");
        const ptype = el.getAttribute("data-param-type");
        const handler = () => {
          if (!selNode.plugin_params || typeof selNode.plugin_params !== "object") selNode.plugin_params = {};
          if (ptype === "checkbox") selNode.plugin_params[key] = !!el.checked;
          else if (ptype === "number") selNode.plugin_params[key] = el.value === "" ? 0 : Number(el.value);
          else selNode.plugin_params[key] = el.value;
          _dirty = true;
        };
        el.onchange = handler;
        if (ptype !== "checkbox" && ptype !== "select") el.oninput = handler;
      });

      const presetEl = mount.querySelector("#wf-ins-tools");
      if (presetEl) {
        presetEl.onchange = () => {
          selNode.tool_preset = presetEl.value;
          selNode.allowed_tools = [...(PRESET_TOOLS[presetEl.value] || [])];
          _dirty = true;
          renderAll();
        };
      }

      mount.querySelectorAll("[data-tool-chk]").forEach((chk) => {
        chk.onchange = () => {
          const list = [];
          mount.querySelectorAll("[data-tool-chk]").forEach((c) => {
            if (c.checked) list.push(c.getAttribute("data-tool-chk"));
          });
          selNode.allowed_tools = list;
          _dirty = true;
        };
      });

      mount.querySelectorAll("[data-guard-chk]").forEach((chk) => {
        chk.onchange = () => syncGuardsFromDom(mount, selNode);
      });
      const customGuardEl = mount.querySelector("#wf-ins-custom-guards");
      if (customGuardEl) customGuardEl.oninput = () => syncGuardsFromDom(mount, selNode);

      const delNodeBtn = mount.querySelector("#wf-del-node");
      if (delNodeBtn) {
        delNodeBtn.onclick = () => {
          _activeTpl.nodes = _activeTpl.nodes.filter((n) => n.id !== selNode.id);
          _activeTpl.nodes.forEach((n) => {
            if (Array.isArray(n.depends_on)) n.depends_on = n.depends_on.filter((d) => d !== selNode.id);
          });
          _activeTpl.edges = (_activeTpl.edges || []).filter((e) => e.from !== selNode.id && e.to !== selNode.id);
          _selectedNodeId = _activeTpl.nodes[0]?.id || null;
          _dirty = true;
          renderAll();
        };
      }
    }

    const saveBtn = mount.querySelector("#wf-save-btn");
    if (saveBtn && _activeTpl) {
      saveBtn.onclick = async () => {
        const title = (_activeTpl.title || "").trim();
        if (!title) return alert("Bitte einen Namen für den Ablaufplan eingeben.");
        const targetId = _activeTpl.builtin ? `${_activeTpl.id}_custom` : _activeTpl.id || undefined;
        try {
          const res = await apiJson("/api/v2/workflows/templates", {
            method: "POST",
            body: JSON.stringify({
              id: targetId,
              title: _activeTpl.builtin && !title.includes("(Kopie)") ? `${title} (Kopie)` : title,
              category: _activeTpl.builtin ? "Eigene Workflows" : _activeTpl.category || "Eigene Workflows",
              description: _activeTpl.description || "",
              schedule_hint: _activeTpl.schedule_hint || "",
              n8n_webhook_hint: _activeTpl.n8n_webhook_hint || "",
              inputs: _activeTpl.inputs || [{ key: "topic", label: "Thema / Ziel", default: "" }],
              nodes: _activeTpl.nodes,
              edges: _activeTpl.edges || [],
            }),
          });
          _dirty = false;
          await loadTemplates(res.template.id);
        } catch (err) {
          alert(`Fehler beim Speichern: ${err.message}`);
        }
      };
    }

    const delTplBtn = mount.querySelector("#wf-del-tpl-btn");
    if (delTplBtn && _activeTpl && !_activeTpl.builtin) {
      delTplBtn.onclick = async () => {
        if (!confirm(`Workflow-Vorlage '${_activeTpl.title}' löschen?`)) return;
        try {
          await apiJson(`/api/v2/workflows/templates/${encodeURIComponent(_activeTpl.id)}`, { method: "DELETE" });
          _activeTpl = null;
          await loadTemplates();
        } catch (err) {
          alert(err.message);
        }
      };
    }

    const toggleParams = mount.querySelector("#wf-toggle-run-params");
    if (toggleParams) {
      toggleParams.onclick = () => {
        _runParamsOpen = !_runParamsOpen;
        renderAll();
      };
    }

    const schedSaveBtn = mount.querySelector("#wf-sched-save-btn");
    if (schedSaveBtn && _activeTpl) {
      schedSaveBtn.onclick = async () => {
        const inputs = {};
        mount.querySelectorAll("[data-wf-input]").forEach((inp) => {
          inputs[inp.getAttribute("data-wf-input")] = inp.value;
        });
        try {
          await apiJson("/api/v2/workflows/schedules", {
            method: "POST",
            body: JSON.stringify({
              template_id: _activeTpl.id || _activeTpl.title,
              title: _activeTpl.title,
              enabled: true,
              trigger_type: mount.querySelector("#wf-sched-trigger")?.value || "cron",
              cron_expr: mount.querySelector("#wf-run-cron")?.value || "",
              start_at: mount.querySelector("#wf-sched-start")?.value || "",
              end_at: mount.querySelector("#wf-sched-end")?.value || "",
              start_condition: mount.querySelector("#wf-sched-start-cond")?.value || "always",
              end_condition: mount.querySelector("#wf-sched-end-cond")?.value || "none",
              max_runs: mount.querySelector("#wf-sched-max-runs")?.value || null,
              watchdog_keyword: mount.querySelector("#wf-sched-kw")?.value || "",
              n8n_webhook_url: mount.querySelector("#wf-run-n8n")?.value || "",
              inputs,
            }),
          });
          await loadSchedules();
          renderAll();
        } catch (err) {
          alert(`Fehler beim Aktivieren: ${err.message}`);
        }
      };
    }

    mount.querySelectorAll("[data-del-sched]").forEach((btn) => {
      btn.onclick = async () => {
        const sid = btn.getAttribute("data-del-sched");
        try {
          await apiJson(`/api/v2/workflows/schedules/${encodeURIComponent(sid)}`, { method: "DELETE" });
          await loadSchedules();
          renderAll();
        } catch (err) {
          alert(err.message);
        }
      };
    });

    async function syncActiveRunDetails() {
      if (!_activeRunId) return;
      try {
        const detail = await apiJson(`/api/v2/workflows/runs/${encodeURIComponent(_activeRunId)}`);
        const runObj = detail && (detail.run || detail);
        if (!runObj || !runObj.nodes) return;
        _activeRunCostUsd = Number(runObj.total_cost_usd || 0);
        Object.entries(runObj.nodes).forEach(([nid, nst]) => {
          const out = nst.output || {};
          _liveNodeStates[nid] = {
            status: nst.status || "pending",
            quality_score: out.quality_score ?? null,
            deliverable_path: out.deliverable_path || "",
            cost_usd: out.cost_usd ?? null,
            output_preview: String(out.content || out.summary || out.result || "").slice(0, 1200),
            error: out.error || "",
          };
        });
        renderAll();
      } catch (_) {}
    }

    mount.querySelectorAll("[data-wf-refresh-run]").forEach((btn) => {
      btn.onclick = () => syncActiveRunDetails();
    });

    mount.querySelectorAll("[data-wf-gate-approve],[data-wf-gate-reject]").forEach((btn) => {
      btn.onclick = async () => {
        if (!_activeRunId) return;
        const isApprove = btn.hasAttribute("data-wf-gate-approve");
        const nid = btn.getAttribute(isApprove ? "data-wf-gate-approve" : "data-wf-gate-reject");
        btn.disabled = true;
        try {
          await apiJson(`/api/v2/workflows/runs/${encodeURIComponent(_activeRunId)}/resume`, {
            method: "POST",
            body: JSON.stringify({ gate_approvals: { [nid]: isApprove } }),
          });
          await syncActiveRunDetails();
        } catch (err) {
          alert(`Gate-Aktion fehlgeschlagen: ${err.message}`);
          btn.disabled = false;
        }
      };
    });

    async function executeWorkflowRun(inputsObj) {
      const statusEl = mount.querySelector("#wf-run-status");
      const gotoBtn = mount.querySelector("#wf-goto-kanban");
      if (runBtn) runBtn.disabled = true;
      if (statusEl) statusEl.textContent = "Starte Workflow in Operations...";
      try {
        let tplId = _activeTpl.id;
        if (_dirty || !tplId) {
          const saved = await apiJson("/api/v2/workflows/templates", {
            method: "POST",
            body: JSON.stringify({
              id: _activeTpl.builtin ? `${_activeTpl.id}_custom` : _activeTpl.id || undefined,
              title: _activeTpl.title || "Eigener Ablaufplan",
              category: _activeTpl.builtin ? "Eigene Workflows" : _activeTpl.category || "Eigene Workflows",
              description: _activeTpl.description || "",
              header_image: _activeTpl.header_image || "",
              inputs: _activeTpl.inputs || [{ key: "topic", label: "Thema / Ziel", default: "" }],
              nodes: _activeTpl.nodes,
              edges: _activeTpl.edges || [],
            }),
          });
          tplId = saved.template.id;
          rememberActiveTemplateId(tplId);
          _dirty = false;
        }
        const res = await apiJson(`/api/v2/workflows/templates/${encodeURIComponent(tplId)}/run`, {
          method: "POST",
          body: JSON.stringify({
            inputs: inputsObj || {},
            cron_schedule: mount.querySelector("#wf-run-cron")?.value || _activeTpl.schedule_hint || "",
            n8n_webhook_url: mount.querySelector("#wf-run-n8n")?.value || _activeTpl.n8n_webhook_hint || "",
          }),
        });
        _activeRunId = res.run_id || "";
        _activeRunCostUsd = 0;
        _liveNodeStates = {};
        if (statusEl) {
          statusEl.textContent = `Gestartet (${res.run_id}): ${(res.created_tasks || []).length} Stationen & ${(res.created_links || []).length} Verknüpfungen angelegt.`;
        }
        if (gotoBtn) {
          gotoBtn.classList.remove("hidden");
          gotoBtn.onclick = () => {
            if (typeof window.setOperationsTab === "function") window.setOperationsTab("kanban");
            if (typeof window.loadOperationsData === "function") window.loadOperationsData();
          };
        }
        if (typeof window.loadOperationsData === "function") window.loadOperationsData();
        renderAll();
      } catch (err) {
        if (statusEl) statusEl.textContent = `Fehler: ${err.message}`;
      } finally {
        if (runBtn) runBtn.disabled = false;
      }
    }

    function openRunDialogModal() {
      closeModalById("wf-run-dialog-modal");
      const tplInputs = Array.isArray(_activeTpl.inputs) ? _activeTpl.inputs : [];
      const modal = document.createElement("div");
      modal.id = "wf-run-dialog-modal";
      modal.className = "fixed inset-0 z-50 bg-black/70 backdrop-blur-xs flex items-center justify-center p-4";
      modal.innerHTML = `
        <div class="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-2xl p-4 space-y-3">
          <div class="flex items-center justify-between border-b border-[var(--border)] pb-2">
            <h3 class="text-sm font-bold text-[var(--foreground)]">Workflow starten: ${esc(_activeTpl.title || "Ablaufplan")}</h3>
            <button type="button" id="wf-run-dlg-close" class="text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)]">✕</button>
          </div>
          <div class="space-y-2.5 text-xs">
            ${tplInputs
              .map((inp) => {
                const curEl = mount.querySelector(`[data-wf-input="${CSS.escape(inp.key)}"]`);
                const val = curEl ? curEl.value : inp.default || "";
                return `<label class="block space-y-1">
                  <span class="text-[11px] font-mono text-[var(--muted-foreground)]">${esc(inp.label || inp.key)}</span>
                  <input type="text" data-dlg-input="${esc(inp.key)}" value="${esc(val)}" placeholder="${esc(inp.placeholder || "")}" class="w-full px-2.5 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--page-bg)]" />
                </label>`;
              })
              .join("")}
          </div>
          <div class="flex items-center justify-end gap-2 pt-2 border-t border-[var(--border)]">
            <button type="button" id="wf-run-dlg-cancel" class="px-3 py-1.5 rounded-lg border border-[var(--border)] text-xs hover:bg-[var(--secondary)]">Abbrechen</button>
            <button type="button" id="wf-run-dlg-go" class="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold">Jetzt starten</button>
          </div>
        </div>`;
      document.body.appendChild(modal);
      modal.querySelector("#wf-run-dlg-close").onclick = () => closeModalById("wf-run-dialog-modal");
      modal.querySelector("#wf-run-dlg-cancel").onclick = () => closeModalById("wf-run-dialog-modal");
      modal.querySelector("#wf-run-dlg-go").onclick = async () => {
        const inputsObj = {};
        modal.querySelectorAll("[data-dlg-input]").forEach((el) => {
          const k = el.getAttribute("data-dlg-input");
          inputsObj[k] = el.value;
          const mirror = mount.querySelector(`[data-wf-input="${CSS.escape(k)}"]`);
          if (mirror) mirror.value = el.value;
        });
        closeModalById("wf-run-dialog-modal");
        await executeWorkflowRun(inputsObj);
      };
    }

    const runBtn = mount.querySelector("#wf-header-start-btn");
    if (runBtn && _activeTpl) {
      runBtn.onclick = async () => {
        if (Array.isArray(_activeTpl.inputs) && _activeTpl.inputs.length > 0) {
          openRunDialogModal();
          return;
        }
        const inputs = {};
        mount.querySelectorAll("[data-wf-input]").forEach((inp) => {
          inputs[inp.getAttribute("data-wf-input")] = inp.value;
        });
        await executeWorkflowRun(inputs);
      };
    }
  }

  async function loadNodePlugins() {
    try {
      const data = await apiJson("/api/v2/workflows/node-plugins");
      if (Array.isArray(data.plugins)) {
        _nodePlugins = data.plugins;
        if (_activeTpl) renderAll();
      }
    } catch (_) {}
  }

  function closeModalById(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
  }

  function openPresetBrowserModal() {
    closeModalById("wf-preset-browser-modal");
    const modal = document.createElement("div");
    modal.id = "wf-preset-browser-modal";
    modal.className = "fixed inset-0 z-50 bg-black/70 backdrop-blur-xs flex items-center justify-center p-4";
    let previewId = (_activeTpl && _activeTpl.id) || (_templates[0] && _templates[0].id) || "";
    let search = "";
    let catFilter = "all";
    const FOLDER_KEY = "archon_wf_browser_folders";
    let collapsedFolders = {};
    try {
      const savedState = JSON.parse(localStorage.getItem(FOLDER_KEY) || "{}");
      if (savedState && typeof savedState === "object") collapsedFolders = savedState;
    } catch (_) {}

    const saveFolderState = () => {
      try {
        localStorage.setItem(FOLDER_KEY, JSON.stringify(collapsedFolders));
      } catch (_) {}
    };

    const renderModal = () => {
      const q = search.trim().toLowerCase();
      const allCats = Array.from(new Set(_templates.map((t) => (t.category || "Allgemein").trim()))).sort();
      const filtered = _templates.filter((t) => {
        const c = (t.category || "Allgemein").trim();
        if (catFilter !== "all" && c !== catFilter) return false;
        if (!q) return true;
        return `${t.title} ${c} ${t.description}`.toLowerCase().includes(q);
      });
      const groups = {};
      filtered.forEach((t) => {
        const folder = (t.category || "Allgemein").trim();
        if (!groups[folder]) groups[folder] = [];
        groups[folder].push(t);
      });
      const sel = _templates.find((t) => t.id === previewId) || filtered[0] || null;
      if (sel) previewId = sel.id;

      const treeHtml = Object.keys(groups)
        .sort()
        .map((folder) => {
          const isCollapsed = !!collapsedFolders[folder] && !q;
          const itemsHtml = isCollapsed
            ? ""
            : groups[folder]
                .map(
                  (t) => `<button type="button" data-ni-tpl="${esc(t.id)}" class="w-full text-left pl-6 pr-2.5 py-1.5 rounded-lg text-xs transition flex items-center gap-2 ${
                    sel && sel.id === t.id ? "bg-indigo-600 text-white font-semibold" : "hover:bg-[var(--secondary)] text-[var(--foreground)]"
                  }">
                    <span class="truncate">${esc(t.title)}</span>
                  </button>`
                )
                .join("");
          return `<div class="space-y-0.5">
            <button type="button" data-ni-folder="${esc(folder)}" class="w-full flex items-center gap-1.5 px-2 py-1.5 rounded-lg hover:bg-[var(--secondary)]/60 text-left text-[11px] font-mono font-semibold text-indigo-300 transition">
              <span class="text-[10px] w-3 text-center">${isCollapsed ? "▸" : "▾"}</span>
              <span>${isCollapsed ? "📁" : "📂"}</span>
              <span class="truncate">${esc(folder)}</span>
            </button>
            ${itemsHtml}
          </div>`;
        })
        .join("") || `<div class="p-4 text-xs text-[var(--muted-foreground)]">Keine Vorlagen gefunden.</div>`;

      const rightHtml = sel
        ? `<div class="flex-1 flex flex-col min-h-0 overflow-hidden">
            ${
              sel.header_image
                ? `<div class="h-40 w-full bg-black/30 overflow-hidden border-b border-[var(--border)] shrink-0"><img src="${esc(sel.header_image)}" alt="" class="w-full h-full object-cover" /></div>`
                : `<div class="h-28 w-full bg-gradient-to-r from-indigo-950 via-slate-900 to-fuchsia-950 border-b border-[var(--border)] flex items-end p-4 shrink-0">
                    <span class="text-[11px] font-mono uppercase tracking-wider text-indigo-300">${esc(sel.category || "Workflow")}</span>
                  </div>`
            }
            <div style="flex:1 1 auto;min-height:0;overflow-y:auto;" class="p-5 space-y-3">
              <div class="flex items-start justify-between gap-3">
                <div>
                  <h3 class="text-lg font-bold text-[var(--foreground)]">${esc(sel.title)}</h3>
                  <div class="text-[11px] font-mono text-[var(--muted-foreground)]">${esc(sel.category || "Allgemein")} · ${(sel.nodes || []).length} Stationen</div>
                </div>
              </div>
              <p class="text-xs text-[var(--foreground)]/90 leading-relaxed whitespace-pre-wrap">${esc(sel.description || "Keine Beschreibung hinterlegt.")}</p>
              <div class="space-y-1 pt-2 border-t border-[var(--border)]">
                <div class="text-[10px] font-mono uppercase text-[var(--muted-foreground)]">Enthaltene Bausteine</div>
                <div class="flex flex-wrap gap-1.5">
                  ${(sel.nodes || []).map((n) => `<span class="px-2 py-0.5 rounded border border-[var(--border)] bg-[var(--page-bg)] text-[11px] font-mono">${esc(n.type)}: ${esc(n.title)}</span>`).join("")}
                </div>
              </div>
            </div>
            <div class="p-3 border-t border-[var(--border)] flex items-center justify-between gap-2 bg-[var(--card)]">
              ${!sel.builtin ? `<button type="button" id="ni-del-btn" class="px-3 py-1.5 rounded-lg border border-rose-500/40 text-rose-300 hover:bg-rose-500/15 text-xs font-semibold">Löschen</button>` : `<span></span>`}
              <button type="button" id="ni-load-btn" class="px-4 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold">Workflow laden</button>
            </div>
          </div>`
        : `<div class="flex-1 flex items-center justify-center text-xs text-[var(--muted-foreground)]">Bitte links ein Preset auswählen.</div>`;

      modal.innerHTML = `
        <div style="width:min(920px,94vw);height:76vh;display:flex;flex-direction:column;overflow:hidden;" class="rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-2xl">
          <div style="flex-shrink:0;" class="px-4 py-3 border-b border-[var(--border)] flex items-center justify-between gap-2">
            <div class="font-bold text-sm">📂 Workflow öffnen — Preset-Browser</div>
            <div class="flex items-center gap-2">
              <button type="button" id="ni-import-n8n-btn" title="n8n Workflow JSON (z. B. Export von n8n.io/workflows) importieren" class="px-2.5 py-1 rounded-lg border border-amber-500/40 bg-amber-500/15 hover:bg-amber-500/25 text-amber-200 text-xs font-semibold">n8n Import</button>
              <button type="button" id="ni-close-btn" class="px-2 py-1 rounded hover:bg-[var(--secondary)] text-xs">✕</button>
            </div>
          </div>
          <div style="flex:1 1 auto;min-height:0;display:flex;overflow:hidden;">
            <div style="width:280px;flex-shrink:0;display:flex;flex-direction:column;min-height:0;" class="border-r border-[var(--border)] bg-[var(--page-bg)]/50">
              <div style="flex-shrink:0;" class="p-2 border-b border-[var(--border)] space-y-1.5">
                <input id="ni-search" value="${esc(search)}" placeholder="Preset suchen..." class="w-full px-2.5 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--page-bg)] text-xs" />
                <select id="ni-cat-filter" class="w-full px-2.5 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--page-bg)] text-xs">
                  <option value="all" ${catFilter === "all" ? "selected" : ""}>Alle Kategorien (${_templates.length})</option>
                  ${allCats.map((c) => `<option value="${esc(c)}" ${catFilter === c ? "selected" : ""}>${esc(c)}</option>`).join("")}
                </select>
              </div>
              <div style="flex:1 1 auto;min-height:0;overflow-y:auto;" class="p-2 space-y-1">${treeHtml}</div>
            </div>
            ${rightHtml}
          </div>
        </div>`;

      modal.querySelector("#ni-close-btn").onclick = () => modal.remove();
      modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
      const sEl = modal.querySelector("#ni-search");
      sEl.oninput = () => {
        search = sEl.value;
        renderModal();
        const ref = modal.querySelector("#ni-search");
        if (ref) { ref.focus(); ref.setSelectionRange(ref.value.length, ref.value.length); }
      };
      const catEl = modal.querySelector("#ni-cat-filter");
      if (catEl) {
        catEl.onchange = () => {
          catFilter = catEl.value || "all";
          renderModal();
        };
      }
      const impBtn = modal.querySelector("#ni-import-n8n-btn");
      if (impBtn) {
        impBtn.onclick = async () => {
          const raw = prompt("n8n Workflow-JSON hier einfügen (z. B. Export von n8n.io/workflows):");
          if (!raw || !raw.trim()) return;
          try {
            const parsed = JSON.parse(raw);
            const res = await apiJson("/api/v2/workflows/templates/import-n8n", {
              method: "POST",
              body: JSON.stringify({ workflow: parsed }),
            });
            catFilter = "all";
            search = "";
            await loadTemplates(res.template.id);
            previewId = res.template.id;
            renderModal();
          } catch (err) {
            alert(`n8n Import fehlgeschlagen: ${err.message}`);
          }
        };
      }
      modal.querySelectorAll("[data-ni-folder]").forEach((fb) => {
        fb.onclick = () => {
          const f = fb.getAttribute("data-ni-folder");
          collapsedFolders[f] = !collapsedFolders[f];
          saveFolderState();
          renderModal();
        };
      });
      modal.querySelectorAll("[data-ni-tpl]").forEach((b) => {
        b.onclick = () => { previewId = b.getAttribute("data-ni-tpl"); renderModal(); };
        b.ondblclick = () => {
          const found = _templates.find((t) => t.id === b.getAttribute("data-ni-tpl"));
          if (!found) return;
          _activeTpl = cloneTpl(found);
          ensurePositions(_activeTpl);
          _selectedNodeId = _activeTpl.nodes[0]?.id || null;
          _selectedEdge = null;
          _dirty = false;
          rememberActiveTemplateId(_activeTpl.id);
          modal.remove();
          renderAll();
        };
      });
      const loadBtn = modal.querySelector("#ni-load-btn");
      if (loadBtn && sel) {
        loadBtn.onclick = () => {
          _activeTpl = cloneTpl(sel);
          ensurePositions(_activeTpl);
          _selectedNodeId = _activeTpl.nodes[0]?.id || null;
          _selectedEdge = null;
          _dirty = false;
          rememberActiveTemplateId(_activeTpl.id);
          modal.remove();
          renderAll();
        };
      }
      const delBtn = modal.querySelector("#ni-del-btn");
      if (delBtn && sel && !sel.builtin) {
        delBtn.onclick = async () => {
          if (!confirm(`Workflow '${sel.title}' wirklich löschen?`)) return;
          await apiJson(`/api/v2/workflows/templates/${encodeURIComponent(sel.id)}`, { method: "DELETE" });
          await loadTemplates();
          previewId = _templates[0]?.id || "";
          renderModal();
        };
      }
    };
    document.body.appendChild(modal);
    renderModal();
  }

  function openSaveWorkflowModal() {
    if (!_activeTpl) return;
    closeModalById("wf-save-dialog-modal");
    const modal = document.createElement("div");
    modal.id = "wf-save-dialog-modal";
    modal.className = "fixed inset-0 z-50 bg-black/70 backdrop-blur-xs flex items-center justify-center p-4";
    let headerImg = _activeTpl.header_image || "";

    modal.innerHTML = `
      <div class="w-full max-w-xl rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-2xl overflow-hidden">
        <div class="px-4 py-3 border-b border-[var(--border)] flex items-center justify-between">
          <div class="font-bold text-sm">💾 Workflow speichern</div>
          <button type="button" id="wf-sv-close" class="px-2 py-1 rounded hover:bg-[var(--secondary)] text-xs">✕</button>
        </div>
        <div class="p-4 space-y-3 text-xs">
          <label class="block space-y-1">
            <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Titel</span>
            <input id="wf-sv-title" value="${esc(_activeTpl.title || "")}" class="w-full px-2.5 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--page-bg)]" />
          </label>
          <label class="block space-y-1">
            <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Kategorie / Ordner</span>
            <input id="wf-sv-cat" value="${esc(_activeTpl.builtin ? "Eigene Workflows" : _activeTpl.category || "Eigene Workflows")}" class="w-full px-2.5 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--page-bg)]" />
          </label>
          <label class="block space-y-1">
            <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Beschreibung</span>
            <textarea id="wf-sv-desc" rows="3" placeholder="Wofuer ist dieser Workflow gedacht?" class="w-full px-2.5 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--page-bg)]">${esc(_activeTpl.description || "")}</textarea>
          </label>
          <div class="space-y-1.5">
            <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Header-Bild (URL oder Upload)</span>
            <div class="flex gap-2">
              <input id="wf-sv-img-url" value="${esc(headerImg)}" placeholder="https://... oder Bild hochladen" class="flex-1 px-2.5 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--page-bg)] font-mono" />
              <label class="px-3 py-1.5 rounded-lg border border-[var(--border)] hover:bg-[var(--secondary)] cursor-pointer font-semibold shrink-0">
                Bild wählen<input id="wf-sv-img-file" type="file" accept="image/*" class="hidden" />
              </label>
            </div>
            <div id="wf-sv-preview" class="${headerImg ? "" : "hidden"} h-28 rounded-lg overflow-hidden border border-[var(--border)] bg-black/30">
              <img src="${esc(headerImg)}" class="w-full h-full object-cover" />
            </div>
          </div>
          <div id="wf-sv-status" class="text-[11px] font-mono text-rose-400"></div>
        </div>
        <div class="px-4 py-3 border-t border-[var(--border)] flex justify-end gap-2">
          <button type="button" id="wf-sv-cancel" class="px-3 py-1.5 rounded-lg border border-[var(--border)] text-xs">Abbrechen</button>
          <button type="button" id="wf-sv-submit" class="px-4 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold">Speichern</button>
        </div>
      </div>`;

    document.body.appendChild(modal);
    modal.querySelector("#wf-sv-close").onclick = () => modal.remove();
    modal.querySelector("#wf-sv-cancel").onclick = () => modal.remove();
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };

    const imgUrlEl = modal.querySelector("#wf-sv-img-url");
    const previewEl = modal.querySelector("#wf-sv-preview");
    const updatePrev = (src) => {
      headerImg = src || "";
      if (headerImg) {
        previewEl.classList.remove("hidden");
        previewEl.querySelector("img").src = headerImg;
      } else {
        previewEl.classList.add("hidden");
      }
    };
    imgUrlEl.oninput = () => updatePrev(imgUrlEl.value.trim());
    modal.querySelector("#wf-sv-img-file").onchange = (ev) => {
      const file = ev.target.files && ev.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        imgUrlEl.value = String(reader.result || "");
        updatePrev(imgUrlEl.value);
      };
      reader.readAsDataURL(file);
    };

    modal.querySelector("#wf-sv-submit").onclick = async () => {
      const title = modal.querySelector("#wf-sv-title").value.trim();
      const cat = modal.querySelector("#wf-sv-cat").value.trim() || "Eigene Workflows";
      const desc = modal.querySelector("#wf-sv-desc").value.trim();
      if (!title) {
        modal.querySelector("#wf-sv-status").textContent = "Bitte einen Titel eingeben.";
        return;
      }
      try {
        const res = await apiJson("/api/v2/workflows/templates", {
          method: "POST",
          body: JSON.stringify({
            id: _activeTpl.builtin ? `${_activeTpl.id}_custom` : _activeTpl.id || undefined,
            title,
            category: cat,
            description: desc,
            header_image: headerImg,
            inputs: _activeTpl.inputs || [{ key: "topic", label: "Thema / Ziel", default: "" }],
            nodes: _activeTpl.nodes,
            edges: _activeTpl.edges || [],
          }),
        });
        _dirty = false;
        modal.remove();
        await loadTemplates(res.template.id);
      } catch (err) {
        modal.querySelector("#wf-sv-status").textContent = `Fehler: ${err.message}`;
      }
    };
  }

  async function openNodeMarketplaceModal(initialCat = "all") {
    closeModalById("wf-node-marketplace-modal");
    const modal = document.createElement("div");
    modal.id = "wf-node-marketplace-modal";
    modal.className = "fixed inset-0 z-50 bg-black/70 backdrop-blur-xs flex items-center justify-center p-4";
    let activeCat = initialCat && initialCat !== "standard" ? initialCat : "all";
    let search = "";

    const refreshData = async () => {
      try {
        const d = await apiJson("/api/v2/workflows/node-plugins/marketplace");
        _marketplaceItems = Array.isArray(d.items) ? d.items : [];
      } catch (_) {}
    };

    const renderMkt = () => {
      const q = search.trim().toLowerCase();
      const filtered = _marketplaceItems.filter((it) => {
        if (activeCat !== "all" && it.category !== activeCat) return false;
        if (!q) return true;
        return `${it.label} ${it.description} ${it.source_name} ${it.plugin_id}`.toLowerCase().includes(q);
      });
      const catLabel = (cid) => (PALETTE_CATEGORIES.find((c) => c.id === cid)?.label || cid);

      modal.innerHTML = `
        <div style="width:min(1040px,94vw);height:82vh;display:flex;flex-direction:column;overflow:hidden;" class="rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-2xl">
          <div style="flex-shrink:0;" class="px-5 py-3.5 border-b border-[var(--border)] flex items-center justify-between gap-3">
            <div>
              <div class="font-bold text-sm">🧩 Baustein-Marktplatz — 3rd-Party & Media Plugins</div>
              <div class="text-[11px] text-[var(--muted-foreground)]">Installiere externe Audio-, Video-, Bild-, Dokument-, Scraping- & Publishing-Module direkt in deine Workflow-Palette.</div>
            </div>
            <button type="button" id="mkt-close" class="px-2.5 py-1 rounded hover:bg-[var(--secondary)] text-xs">✕</button>
          </div>
          <div style="flex-shrink:0;" class="px-5 py-2.5 border-b border-[var(--border)] flex flex-wrap items-center justify-between gap-2 bg-[var(--page-bg)]/40">
            <div class="flex flex-wrap gap-1">
              <button type="button" data-mkt-cat="all" class="px-2.5 py-1 rounded-lg text-xs font-semibold ${activeCat === "all" ? "bg-indigo-600 text-white" : "border border-[var(--border)] hover:bg-[var(--secondary)]"}">Alle (${_marketplaceItems.length})</button>
              ${PALETTE_CATEGORIES.filter((c) => c.id !== "standard")
                .map(
                  (c) => `<button type="button" data-mkt-cat="${c.id}" class="px-2.5 py-1 rounded-lg text-xs ${
                    activeCat === c.id ? "bg-indigo-600 text-white font-semibold" : "border border-[var(--border)] hover:bg-[var(--secondary)]"
                  }">${c.icon} ${esc(c.label)}</button>`
                )
                .join("")}
            </div>
            <input id="mkt-search" value="${esc(search)}" placeholder="Plugin oder Anbieter suchen..." class="w-60 px-2.5 py-1 rounded-lg border border-[var(--border)] bg-[var(--page-bg)] text-xs" />
          </div>
          <div style="flex:1 1 auto;min-height:0;overflow-y:auto;" class="p-5 space-y-4">
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 content-start">
              ${filtered
                .map(
                  (it) => `<div class="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--page-bg)]/60 flex flex-col justify-between gap-3">
                    <div class="space-y-1.5">
                      <div class="flex items-start justify-between gap-2">
                        <div class="font-bold text-xs text-[var(--foreground)]">${esc(it.icon || "🔌")} ${esc(it.label)}</div>
                        <span class="text-[9px] font-mono px-1.5 py-0.5 rounded border border-[var(--border)] bg-[var(--card)] shrink-0">${esc(catLabel(it.category))}</span>
                      </div>
                      <p class="text-[11px] text-[var(--muted-foreground)] leading-relaxed">${esc(it.description || "")}</p>
                    </div>
                    <div class="pt-2 border-t border-[var(--border)]/60 flex items-center justify-between gap-2 text-[10px]">
                      <div class="font-mono text-[var(--muted-foreground)] truncate">
                        Quelle: ${it.source_url && it.source_url.startsWith("http") ? `<a href="${esc(it.source_url)}" target="_blank" rel="noreferrer" class="underline hover:text-[var(--foreground)]">${esc(it.source_name || it.source_url)}</a>` : esc(it.source_name || "Core")}
                      </div>
                      ${
                        it.core
                          ? `<span class="px-2 py-1 rounded bg-emerald-500/15 text-emerald-300 font-mono font-semibold shrink-0">Core aktiv</span>`
                          : it.installed
                          ? `<button type="button" data-mkt-uninst="${esc(it.plugin_id)}" class="px-2.5 py-1 rounded border border-rose-500/40 text-rose-300 hover:bg-rose-500/15 font-semibold shrink-0">Deinstallieren</button>`
                          : `<button type="button" data-mkt-inst="${esc(it.plugin_id)}" class="px-2.5 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-white font-semibold shrink-0">Installieren</button>`
                      }
                    </div>
                  </div>`
                )
                .join("")}
            </div>
            <div class="p-4 rounded-xl border border-dashed border-indigo-500/40 bg-indigo-500/5 space-y-2.5">
              <div class="text-xs font-bold text-indigo-200">🔌 Eigenes Modul / GitHub-Repository nachrüsten</div>
              <div class="grid grid-cols-1 md:grid-cols-3 gap-2 text-xs">
                <input id="mkt-custom-url" placeholder="GitHub-URL oder Tool-Quelle (z. B. https://github.com/...)" class="px-2.5 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--page-bg)] font-mono" />
                <input id="mkt-custom-name" placeholder="Modul-Name (z. B. Remotion Video)" class="px-2.5 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--page-bg)]" />
                <select id="mkt-custom-cat" class="px-2.5 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--page-bg)]">
                  ${PALETTE_CATEGORIES.filter((c) => c.id !== "standard")
                    .map((c) => `<option value="${c.id}" ${(activeCat !== "all" ? activeCat : "business") === c.id ? "selected" : ""}>${c.icon} ${esc(c.label)}</option>`)
                    .join("")}
                </select>
              </div>
              <div class="flex flex-wrap items-center gap-2 text-xs">
                <input id="mkt-custom-desc" placeholder="Kurze Beschreibung (optional)" class="flex-1 min-w-[220px] px-2.5 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--page-bg)]" />
                <button type="button" id="mkt-custom-add-btn" class="px-3.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold shrink-0">+ Modul hinzufügen & installieren</button>
              </div>
              <div id="mkt-custom-status" class="text-[11px] font-mono text-rose-400"></div>
            </div>
          </div>
        </div>`;

      modal.querySelector("#mkt-close").onclick = () => modal.remove();
      modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
      modal.querySelectorAll("[data-mkt-cat]").forEach((b) => {
        b.onclick = () => { activeCat = b.getAttribute("data-mkt-cat"); renderMkt(); };
      });
      const ms = modal.querySelector("#mkt-search");
      ms.oninput = () => {
        search = ms.value;
        renderMkt();
        const ref = modal.querySelector("#mkt-search");
        if (ref) { ref.focus(); ref.setSelectionRange(ref.value.length, ref.value.length); }
      };
      modal.querySelectorAll("[data-mkt-inst]").forEach((b) => {
        b.onclick = async () => {
          const pid = b.getAttribute("data-mkt-inst");
          b.disabled = true;
          b.textContent = "Installiere...";
          await apiJson(`/api/v2/workflows/node-plugins/marketplace/${encodeURIComponent(pid)}/install`, { method: "POST" });
          await Promise.all([refreshData(), loadNodePlugins()]);
          renderMkt();
        };
      });
      modal.querySelectorAll("[data-mkt-uninst]").forEach((b) => {
        b.onclick = async () => {
          const pid = b.getAttribute("data-mkt-uninst");
          b.disabled = true;
          await apiJson(`/api/v2/workflows/node-plugins/marketplace/${encodeURIComponent(pid)}`, { method: "DELETE" });
          await Promise.all([refreshData(), loadNodePlugins()]);
          renderMkt();
        };
      });
      const customAddBtn = modal.querySelector("#mkt-custom-add-btn");
      if (customAddBtn) {
        customAddBtn.onclick = async () => {
          const sourceUrl = modal.querySelector("#mkt-custom-url")?.value.trim() || "";
          const label = modal.querySelector("#mkt-custom-name")?.value.trim() || "";
          const category = modal.querySelector("#mkt-custom-cat")?.value || "business";
          const description = modal.querySelector("#mkt-custom-desc")?.value.trim() || "";
          const stEl = modal.querySelector("#mkt-custom-status");
          if (!sourceUrl && !label) {
            if (stEl) stEl.textContent = "Bitte mindestens GitHub-URL/Quelle oder Modul-Name eingeben.";
            return;
          }
          customAddBtn.disabled = true;
          try {
            await apiJson("/api/v2/workflows/node-plugins/marketplace/custom", {
              method: "POST",
              body: JSON.stringify({ source_url: sourceUrl, label, category, description }),
            });
            _paletteTab = category;
            await Promise.all([refreshData(), loadNodePlugins()]);
            renderMkt();
          } catch (err) {
            if (stEl) stEl.textContent = `Fehler: ${err.message}`;
            customAddBtn.disabled = false;
          }
        };
      }
    };

    document.body.appendChild(modal);
    modal.innerHTML = `<div class="p-6 rounded-xl bg-[var(--card)] border border-[var(--border)] text-xs">Lade Baustein-Marktplatz...</div>`;
    await refreshData();
    renderMkt();
  }

  async function loadAgentsList() {
    try {
      let list = Array.isArray(window.hermesProfilesData) ? window.hermesProfilesData : null;
      if (!list || !list.length) {
        const data = await apiJson("/api/hermes/profiles");
        list = Array.isArray(data) ? data : data.profiles || [];
      }
      if (Array.isArray(list) && list.length) {
        _profiles = list
          .map((p) => {
            const id = p.id || p.agent_id;
            if (!id) return null;
            const name = p.name || p.display_name || id;
            const role = p.role || p.department || "";
            return { id, label: role ? `${name} (${role})` : name };
          })
          .filter(Boolean);
        _agents = Array.from(new Set([..._profiles.map((p) => p.id), ..._agents]));
        if (_activeTpl) renderAll();
      }
    } catch (_) {}
  }

  function injectTaskModalWorkflowBridge() {
    const presetSel = document.getElementById("ops-task-preset-select");
    if (!presetSel || document.getElementById("ops-task-wf-select")) return;

    const wrap = document.createElement("div");
    wrap.className = "flex items-center gap-1.5 pl-2 border-l border-[var(--border)]";
    wrap.innerHTML = `
      <select id="ops-task-wf-select" class="h-8 px-2.5 rounded-lg border border-indigo-500/40 bg-[var(--background)] text-xs font-mono text-[var(--foreground)] focus:outline-none cursor-pointer" style="max-width: 210px;">
        <option value="">Workflow-DAG starten...</option>
      </select>
      <button type="button" id="ops-task-wf-run" class="h-8 px-2.5 rounded-lg bg-indigo-600/20 hover:bg-indigo-600/35 border border-indigo-500/40 text-xs font-mono font-semibold text-indigo-300 transition cursor-pointer whitespace-nowrap">
        DAG starten
      </button>
    `;
    presetSel.parentNode.appendChild(wrap);

    const fillWfOptions = async () => {
      if (!_templates.length) {
        try {
          const d = await apiJson("/api/v2/workflows/templates");
          _templates = d.templates || [];
        } catch (_) {}
      }
      const sel = document.getElementById("ops-task-wf-select");
      if (!sel) return;
      sel.innerHTML =
        '<option value="">Workflow-DAG starten...</option>' +
        _templates.map((t) => `<option value="${esc(t.id)}">${esc(t.title)} (${(t.nodes || []).length} Steps)</option>`).join("");
    };
    fillWfOptions();

    const runBtn = document.getElementById("ops-task-wf-run");
    if (runBtn) {
      runBtn.onclick = async () => {
        const wfId = document.getElementById("ops-task-wf-select")?.value;
        if (!wfId) return alert("Bitte zuerst einen Workflow auswaehlen.");
        const titleInput = document.getElementById("ops-task-title-input") || document.getElementById("new-task-title");
        const topic = (titleInput?.value || "").trim() || prompt("Thema / Ziel fuer diesen Workflow-DAG eingeben:") || "";
        if (!topic.trim()) return;
        runBtn.disabled = true;
        try {
          const res = await apiJson(`/api/v2/workflows/templates/${encodeURIComponent(wfId)}/run`, {
            method: "POST",
            body: JSON.stringify({ inputs: { topic: topic.trim() } }),
          });
          if (typeof window.closeNewTaskModal === "function") window.closeNewTaskModal();
          if (typeof window.loadOperationsData === "function") window.loadOperationsData();
          alert(`Workflow-DAG gestartet (${res.run_id}): ${(res.created_tasks || []).length} verknuepfte Aufgaben angelegt.`);
        } catch (err) {
          alert(`Fehler: ${err.message}`);
        } finally {
          runBtn.disabled = false;
        }
      };
    }
  }

  async function loadSchedules() {
    try {
      const data = await apiJson("/api/v2/workflows/schedules");
      _schedules = data.schedules || [];
    } catch (_) {}
  }

  async function loadTemplates(selectId) {
    try {
      const [data] = await Promise.all([apiJson("/api/v2/workflows/templates"), loadSchedules()]);
      _templates = data.templates || [];
      let rememberedId = "";
      try {
        rememberedId = localStorage.getItem("archon_wf_last_active_id") || "";
      } catch (_) {}
      const lookupId = selectId || rememberedId;
      const target = lookupId ? _templates.find((t) => t.id === lookupId) || null : null;
      if (target) {
        _activeTpl = cloneTpl(target);
        ensurePositions(_activeTpl);
        _selectedNodeId = _activeTpl.nodes[0]?.id || null;
        _selectedEdge = null;
        rememberActiveTemplateId(target.id);
      } else {
        _activeTpl = createBlankWorkflow();
        _selectedNodeId = null;
        _selectedEdge = null;
      }
      renderAll();
    } catch (err) {
      const mount = document.getElementById("ops-workflow-templates-mount");
      if (mount) mount.innerHTML = `<div class="p-4 text-xs text-rose-400">Fehler beim Laden: ${esc(err.message)}</div>`;
    }
  }

  function ensureWorkflowsTabButton() {
    if (document.getElementById("ops-subtab-workflows")) return;
    const autoBtn = document.getElementById("ops-subtab-automation");
    if (!autoBtn || !autoBtn.parentNode) return;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.id = "ops-subtab-workflows";
    btn.title = "Workflows (Visueller DAG-Editor)";
    btn.className = "ops-header-tile flex flex-col items-center justify-between min-w-[56px] sm:min-w-[62px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-80 hover:opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
    btn.setAttribute("onclick", "setOperationsTab('workflows')");
    btn.innerHTML = `
      <div class="tile-icon-wrap w-11 h-11 sm:w-12 sm:h-12 flex items-center justify-center mb-0.5 relative">
        <img src="/static/img/cadre_icons/workflows.png?v=2026112045" alt="Workflows" class="w-full h-full object-contain drop-shadow-xs pointer-events-none">
      </div>
      <span class="ops-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-[var(--foreground)] font-medium leading-none">Workflows</span>
    `;
    autoBtn.parentNode.insertBefore(btn, autoBtn);
  }

  function injectStudioShell() {
    ensureWorkflowsTabButton();
    const container = document.getElementById("ops-view-workflows");
    if (!container || document.getElementById("ops-workflow-templates-mount")) return;

    const mount = document.createElement("div");
    mount.id = "ops-workflow-templates-mount";
    mount.style.cssText = "flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden;background:var(--card);";
    container.appendChild(mount);

    window.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && (_connectFromId || _connectMode)) {
        _connectFromId = null;
        _connectMode = false;
        renderAll();
      }
    });

    loadAgentsList();
    loadTemplates();
  }

  function ensureEventBusLogTabButton() {
    if (document.getElementById("log-subtab-btn-events")) return;
    const commBtn = document.getElementById("log-subtab-btn-comm");
    if (!commBtn || !commBtn.parentNode) return;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.id = "log-subtab-btn-events";
    btn.title = "Event-Bus Log (Watchdog, Posteingang, Research, Boardroom)";
    btn.className = "logstream-header-tile flex flex-col items-center justify-between min-w-[56px] sm:min-w-[62px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-80 hover:opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
    btn.setAttribute("onclick", "setLogStreamSourceMode('events')");
    btn.innerHTML = `
      <div class="tile-icon-wrap w-11 h-11 sm:w-12 sm:h-12 flex items-center justify-center mb-0.5 relative">
        <img src="/static/img/cadre_icons/telemetry_eventbus.png?v=2026112110" alt="Event-Bus" class="w-10 h-10 sm:w-11 sm:h-11 object-contain drop-shadow-xs pointer-events-none">
      </div>
      <span class="logstream-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-[var(--muted-foreground)] font-medium leading-none">Event-Bus</span>
    `;
    commBtn.parentNode.insertBefore(btn, commBtn);
  }

  let _eventSourceFilter = "all";
  let _eventTabMode = "log"; // "log" | "matrix"
  window.loadWorkflowEventsLog = async function (sourceFilter) {
    ensureEventBusLogTabButton();
    if (sourceFilter !== undefined) _eventSourceFilter = sourceFilter;
    const pane = document.getElementById("logstream-events-console");
    if (!pane) return;

    try {
      if (_eventTabMode === "matrix") {
        const mData = await apiJson("/api/v2/workflows/event-policies");
        const srcs = mData.sources || [];
        const tgts = mData.targets || [];
        const pols = mData.policies || [];
        const byKey = {};
        pols.forEach((p) => (byKey[`${p.source}__${p.target}`] = p));
        const tgtLabels = {
          workflow: "Workflows (Standard)",
          treasury: "Treasury & Zahlungen",
          comms: "E-Mail & Outreach",
          system: "Code & Release",
        };
        const polBtnCls = (pol) =>
          pol === "deny"
            ? "bg-rose-500/20 text-rose-300 border-rose-500/40"
            : pol === "require_hitl"
            ? "bg-amber-500/20 text-amber-300 border-amber-500/40"
            : "bg-emerald-500/20 text-emerald-300 border-emerald-500/40";
        const polLabels = { allow: "Erlaubt", require_hitl: "Nur HITL", deny: "Gesperrt" };

        pane.innerHTML = `
          <div class="p-3 border-b border-[var(--border)] flex flex-wrap items-center justify-between gap-2 shrink-0">
            <div class="flex items-center gap-2">
              <button type="button" id="ev-tab-log" class="px-3 py-1 rounded-lg text-xs font-semibold border border-[var(--border)] hover:bg-[var(--secondary)]">Live Event-Log</button>
              <button type="button" id="ev-tab-matrix" class="px-3 py-1 rounded-lg text-xs font-semibold bg-indigo-600 text-white">Trigger-Matrix (Rechte & Schutz)</button>
            </div>
            <span class="text-[11px] font-mono text-[var(--muted-foreground)]">Klick auf Zelle schaltet: Erlaubt → Nur HITL → Gesperrt</span>
          </div>
          <div class="flex-1 overflow-auto p-3">
            <table class="w-full text-xs border-collapse">
              <thead>
                <tr class="border-b border-[var(--border)] text-left font-mono text-[10px] uppercase text-[var(--muted-foreground)]">
                  <th class="p-2">Ereignis-Quelle</th>
                  ${tgts.map((t) => `<th class="p-2">${esc(tgtLabels[t] || t)}</th>`).join("")}
                  <th class="p-2">Rate-Limit / Min</th>
                </tr>
              </thead>
              <tbody>
                ${srcs
                  .map((s) => {
                    const rowMax = (byKey[`${s}__workflow`] || {}).max_per_min || 20;
                    return `
                      <tr class="border-b border-[var(--border)]/60 hover:bg-[var(--secondary)]/20">
                        <td class="p-2 font-mono font-bold">${esc(s)}</td>
                        ${tgts
                          .map((t) => {
                            const r = byKey[`${s}__${t}`] || { policy: "allow" };
                            return `<td class="p-2">
                              <button type="button" data-pol-src="${esc(s)}" data-pol-tgt="${esc(t)}" data-pol-cur="${esc(r.policy)}"
                                class="px-2.5 py-1 rounded-lg border text-[11px] font-mono font-semibold transition ${polBtnCls(r.policy)}">
                                ${polLabels[r.policy] || r.policy}
                              </button>
                            </td>`;
                          })
                          .join("")}
                        <td class="p-2">
                          <input type="number" min="1" max="500" value="${rowMax}" data-rate-src="${esc(s)}" class="w-20 px-2 py-1 rounded border border-[var(--border)] bg-[var(--page-bg)] font-mono text-xs" />
                        </td>
                      </tr>`;
                  })
                  .join("")}
              </tbody>
            </table>
          </div>`;

        pane.querySelector("#ev-tab-log").onclick = () => {
          _eventTabMode = "log";
          window.loadWorkflowEventsLog();
        };
        pane.querySelectorAll("[data-pol-src]").forEach((btn) => {
          btn.onclick = async () => {
            const cur = btn.getAttribute("data-pol-cur");
            const order = ["allow", "require_hitl", "deny"];
            const next = order[(order.indexOf(cur) + 1) % order.length];
            const src = btn.getAttribute("data-pol-src");
            const tgt = btn.getAttribute("data-pol-tgt");
            const rate = Number(pane.querySelector(`[data-rate-src="${src}"]`)?.value || 20);
            await apiJson("/api/v2/workflows/event-policies", {
              method: "POST",
              body: JSON.stringify({ source: src, target: tgt, policy: next, max_per_min: rate }),
            });
            window.loadWorkflowEventsLog();
          };
        });
        pane.querySelectorAll("[data-rate-src]").forEach((inp) => {
          inp.onchange = async () => {
            const src = inp.getAttribute("data-rate-src");
            const r = byKey[`${src}__workflow`] || { policy: "allow" };
            await apiJson("/api/v2/workflows/event-policies", {
              method: "POST",
              body: JSON.stringify({ source: src, target: "workflow", policy: r.policy, max_per_min: Number(inp.value || 20) }),
            });
          };
        });
        return;
      }

      const qs = _eventSourceFilter && _eventSourceFilter !== "all" ? `&source=${encodeURIComponent(_eventSourceFilter)}` : "";
      const data = await apiJson(`/api/v2/workflows/events?limit=100${qs}`);
      const events = data.events || [];
      const sources = [
        ["all", "Alle Quellen"],
        ["watchdog", "Watchdog"],
        ["inbox", "Posteingang"],
        ["research", "Research Lab"],
        ["boardroom", "AI Boardroom"],
        ["calendar", "Kalender"],
        ["approval", "Freigaben"],
        ["manual", "Manuell"],
      ];
      const badgeCls = (st) =>
        st === "triggered"
          ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
          : st === "blocked_policy" || st === "rate_limited"
          ? "bg-rose-500/20 text-rose-300 border-rose-500/40"
          : st === "skipped_loop"
          ? "bg-amber-500/20 text-amber-300 border-amber-500/40"
          : "bg-[var(--secondary)] text-[var(--muted-foreground)] border-[var(--border)]";

      pane.innerHTML = `
        <div class="p-3 border-b border-[var(--border)] flex flex-wrap items-center justify-between gap-2 shrink-0">
          <div class="flex flex-wrap items-center gap-1.5">
            <button type="button" id="ev-tab-log" class="px-3 py-1 rounded-lg text-xs font-semibold bg-indigo-600 text-white">Live Event-Log</button>
            <button type="button" id="ev-tab-matrix" class="px-3 py-1 rounded-lg text-xs font-semibold border border-[var(--border)] hover:bg-[var(--secondary)]">Trigger-Matrix (Rechte & Schutz)</button>
            <span class="mx-1 text-[var(--border)]">|</span>
            ${sources
              .map(
                ([k, lbl]) => `<button type="button" data-ev-filter="${k}" class="px-2 py-1 rounded-lg text-[11px] font-mono border transition ${
                  _eventSourceFilter === k ? "bg-indigo-600/30 text-indigo-200 border-indigo-500/60" : "border-[var(--border)] hover:bg-[var(--secondary)]"
                }">${lbl}</button>`
              )
              .join("")}
          </div>
          <div class="flex items-center gap-2">
            <button type="button" id="ev-test-emit" class="px-3 py-1 rounded-lg border border-amber-500/40 bg-amber-500/15 hover:bg-amber-500/25 text-amber-300 text-xs font-semibold">Test-Event senden</button>
            <button type="button" id="ev-refresh" class="px-3 py-1 rounded-lg border border-[var(--border)] hover:bg-[var(--secondary)] text-xs">Aktualisieren</button>
          </div>
        </div>
        <div class="flex-1 overflow-y-auto p-3 space-y-2">
          ${
            events.length
              ? events
                  .map(
                    (ev) => `
                  <div class="p-2.5 rounded-xl border border-[var(--border)] bg-[var(--page-bg)] flex flex-wrap items-start justify-between gap-2 text-xs">
                    <div class="min-w-0 flex-1 space-y-1">
                      <div class="flex flex-wrap items-center gap-2">
                        <span class="px-2 py-0.5 rounded border text-[10px] font-mono ${badgeCls(ev.status)}">${esc(ev.status)}</span>
                        <span class="px-2 py-0.5 rounded bg-indigo-500/15 border border-indigo-500/30 text-indigo-300 text-[10px] font-mono">${esc(ev.source)}.${esc(ev.event_type)}</span>
                        <span class="font-semibold text-[var(--foreground)] truncate">${esc(ev.title)}</span>
                      </div>
                      ${ev.summary ? `<div class="text-[11px] text-[var(--muted-foreground)] line-clamp-2">${esc(ev.summary)}</div>` : ""}
                      ${
                        (ev.triggered_run_ids || []).length
                          ? `<div class="text-[10px] font-mono text-emerald-300">Ausgelöste Workflow-Runs: ${esc(ev.triggered_run_ids.join(", "))}</div>`
                          : ""
                      }
                    </div>
                    <div class="flex items-center gap-2 shrink-0">
                      <button type="button" data-ev-replay="${esc(ev.id)}" class="px-2 py-0.5 rounded border border-[var(--border)] hover:bg-[var(--secondary)] text-[10px] font-mono">Replay</button>
                      <span class="text-[10px] font-mono text-[var(--muted-foreground)]">${esc((ev.created_at || "").replace("T", " ").slice(0, 19))}</span>
                    </div>
                  </div>`
                  )
                  .join("")
              : '<div class="p-8 text-center text-xs text-[var(--muted-foreground)]">Noch keine Event-Bus-Einträge protokolliert. Sobald Watchdog, Posteingang, Kalender, Research Lab oder AI Boardroom ein Signal senden, erscheint es hier in Echtzeit.</div>'
          }
        </div>`;

      pane.querySelector("#ev-tab-matrix").onclick = () => {
        _eventTabMode = "matrix";
        window.loadWorkflowEventsLog();
      };
      pane.querySelectorAll("[data-ev-replay]").forEach((b) => {
        b.onclick = async () => {
          await apiJson(`/api/v2/workflows/events/${encodeURIComponent(b.getAttribute("data-ev-replay"))}/replay`, { method: "POST" });
          window.loadWorkflowEventsLog();
        };
      });

      pane.querySelectorAll("[data-ev-filter]").forEach((b) => {
        b.onclick = () => window.loadWorkflowEventsLog(b.getAttribute("data-ev-filter"));
      });
      const refBtn = pane.querySelector("#ev-refresh");
      if (refBtn) refBtn.onclick = () => window.loadWorkflowEventsLog();
      const testBtn = pane.querySelector("#ev-test-emit");
      if (testBtn) {
        testBtn.onclick = async () => {
          await apiJson("/api/v2/workflows/events/emit", {
            method: "POST",
            body: JSON.stringify({
              source: _eventSourceFilter === "all" ? "inbox" : _eventSourceFilter,
              event_type: "test_signal",
              title: "Test-Signal aus Event-Bus Log",
              summary: "Manueller Konnektivitätstest für Workflow-Trigger.",
            }),
          });
          window.loadWorkflowEventsLog();
        };
      }
    } catch (err) {
      pane.innerHTML = `<div class="p-4 text-xs text-rose-400">Event-Bus Log konnte nicht geladen werden: ${esc(err.message)}</div>`;
    }
  };

  let _logRaf = 0;
  const _logObserver = new MutationObserver(() => {
    // Audit v3 2.3: rAF-Gedrosselt statt pro Mutation
    if (_logRaf) return;
    _logRaf = requestAnimationFrame(() => {
      _logRaf = 0;
      if (document.getElementById("log-subtab-btn-comm") && !document.getElementById("log-subtab-btn-events")) {
        ensureEventBusLogTabButton();
      }
    });
  });
  if (document.body) _logObserver.observe(document.body, { childList: true, subtree: true });

  window.openWorkflowTemplatesStudio = function () {
    injectStudioShell();
    if (typeof window.setOperationsTab === "function") window.setOperationsTab("workflows");
  };

  window.startWorkflowDagFromSignal = async function (title, summary, sourceUrl) {
    const topic = [title, summary, sourceUrl].filter(Boolean).join(" — ").slice(0, 500);
    if (!topic) return;
    try {
      const listRes = await apiJson("/api/v2/workflows/templates");
      const tpls = Array.isArray(listRes.templates) ? listRes.templates : [];
      const preferred =
        tpls.find((t) => /content|research|news|media/i.test(String(t.id || t.category || ""))) || tpls[0];
      if (!preferred) {
        alert("Keine Workflow-Vorlage gefunden.");
        return;
      }
      const res = await apiJson(`/api/v2/workflows/templates/${encodeURIComponent(preferred.id)}/run`, {
        method: "POST",
        body: JSON.stringify({ inputs: { topic } }),
      });
      _activeRunId = res.run_id || "";
      _activeRunCostUsd = 0;
      _liveNodeStates = {};
      if (typeof window.showToast === "function") {
        window.showToast(`Workflow-DAG gestartet (${res.run_id}): ${preferred.title}`, "success");
      } else {
        alert(`Workflow-DAG gestartet (${res.run_id}): ${preferred.title}`);
      }
      if (typeof window.loadOperationsData === "function") window.loadOperationsData();
    } catch (err) {
      alert(`Workflow-Start fehlgeschlagen: ${err.message}`);
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      injectStudioShell();
      ensureEventBusLogTabButton();
      injectTaskModalWorkflowBridge();
      loadNodePlugins();
    });
  } else {
    injectStudioShell();
    ensureEventBusLogTabButton();
    injectTaskModalWorkflowBridge();
    loadNodePlugins();
  }
})();
