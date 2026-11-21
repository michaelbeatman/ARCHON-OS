/**
 * static/js/content_machine_studio.js
 * ===================================
 * M107 / M106 — Multi-Channel Content-Maschine 2.0 & SQLite 28->3 Konsolidierungs-Studio
 * fuer das Haupt-Frontend (static/index.html -> Operations -> Content-Studio).
 */
(function () {
  "use strict";

  const CHANNELS = [
    { id: "linkedin", label: "LinkedIn", badge: "LI" },
    { id: "youtube_longform", label: "YouTube Longform", badge: "YT" },
    { id: "youtube_shorts", label: "YouTube Shorts (9:16)", badge: "SHORTS" },
    { id: "tiktok", label: "TikTok (9:16)", badge: "TT" },
    { id: "x_threads", label: "X / Threads", badge: "X" },
  ];

  let _overview = null;
  let _campaigns = [];
  let _assets = [];
  let _dbPlan = null;
  let _selectedCampaignId = "";
  let _channelFilter = "";
  let _statusFilter = "";
  let _busy = false;
  let _bannerMsg = "";

  function esc(val) {
    return String(val == null ? "" : val)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  async function apiJson(url, opts) {
    const res = await fetch(url, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(opts && opts.headers ? opts.headers : {}) },
      ...opts,
    });
    const text = await res.text();
    let data = {};
    try {
      data = text ? JSON.parse(text) : {};
    } catch (_) {
      data = { detail: text };
    }
    if (!res.ok) {
      throw new Error(data.detail || data.message || `HTTP ${res.status}`);
    }
    return data;
  }

  function ensureContentTabButton() {
    if (document.getElementById("ops-subtab-content")) return;
    const anchor =
      document.getElementById("ops-subtab-workflows") ||
      document.getElementById("ops-subtab-automation") ||
      document.getElementById("ops-subtab-org");
    if (!anchor || !anchor.parentNode) return;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.id = "ops-subtab-content";
    btn.title = "Content-Maschine 2.0 (LinkedIn, YouTube, TikTok, 9:16 Clips & Anti-Slop)";
    btn.className =
      "ops-header-tile flex flex-col items-center justify-between min-w-[56px] sm:min-w-[62px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-80 hover:opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
    btn.setAttribute("onclick", "setOperationsTab('content')");
    btn.innerHTML = `
      <div class="tile-icon-wrap w-11 h-11 sm:w-12 sm:h-12 flex items-center justify-center mb-0.5 relative">
        <img src="/static/img/cadre_icons/medien.png?v=3" alt="Content-Studio" class="w-full h-full object-contain drop-shadow-xs pointer-events-none">
      </div>
      <span class="ops-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-[var(--foreground)] font-medium leading-none">Content 2.0</span>
    `;
    anchor.parentNode.insertBefore(btn, anchor.nextSibling);
  }

  async function reloadContentStudioData() {
    try {
      const params = new URLSearchParams();
      if (_selectedCampaignId) params.set("campaign_id", _selectedCampaignId);
      if (_channelFilter) params.set("channel", _channelFilter);
      if (_statusFilter) params.set("status", _statusFilter);

      const [ov, camps, asts, plan] = await Promise.all([
        apiJson("/api/v2/content-machine/overview"),
        apiJson("/api/v2/content-machine/campaigns"),
        apiJson("/api/v2/content-machine/assets" + (params.toString() ? "?" + params.toString() : "")),
        apiJson("/api/v2/system/db-consolidation/plan").catch(() => null),
      ]);
      _overview = ov;
      _campaigns = camps.campaigns || [];
      _assets = asts.assets || [];
      _dbPlan = plan;
      renderContentStudioShell();
    } catch (err) {
      _bannerMsg = "Fehler beim Laden: " + err.message;
      renderContentStudioShell();
    }
  }

  function renderContentStudioShell() {
    ensureContentTabButton();
    const host = document.getElementById("ops-view-content");
    if (!host) return;

    const statusCounts = (_overview && _overview.status_counts) || {};
    const dbActive = _dbPlan && _dbPlan.consolidated_active;

    host.innerHTML = `
      <div class="flex-1 flex flex-col min-h-0 w-full h-full overflow-y-auto p-4 space-y-4 text-xs bg-[var(--card)] text-[var(--foreground)]">
        <!-- HEADER & DB-KONSOLIDIERUNG -->
        <div class="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-[var(--border)]">
          <div>
            <div class="flex items-center gap-2">
              <span class="px-2 py-0.5 rounded bg-red-600/15 text-red-500 font-mono font-bold text-[10px] uppercase">M107 · Content-Maschine 2.0</span>
              <span class="px-2 py-0.5 rounded ${dbActive ? "bg-emerald-500/15 text-emerald-500" : "bg-amber-500/15 text-amber-500"} font-mono font-bold text-[10px]">
                SQLite 28→3: ${dbActive ? "AKTIV (ops.db · business.db · memory.db)" : "BEREIT ZUR MIGRATION"}
              </span>
            </div>
            <h3 class="text-sm font-bold mt-1">Multi-Channel Content-Maschine &amp; Repurposing-DAG (LinkedIn · YouTube · Shorts · TikTok · X)</h3>
          </div>
          <div class="flex items-center gap-2 flex-wrap">
            <button type="button" id="cm-btn-publish-due" class="px-3 py-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 hover:bg-amber-500/20 text-amber-500 font-mono font-bold cursor-pointer">
              Fällige publizieren (${Number(statusCounts.scheduled || 0)})
            </button>
            <button type="button" id="cm-btn-db-consolidate" class="px-3 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--background)] hover:bg-[var(--secondary)] font-mono font-bold cursor-pointer">
              DB 28→3 Konsolidierung prüfen/starten
            </button>
            <button type="button" id="cm-btn-refresh" class="px-3 py-1.5 rounded-lg bg-[var(--primary)] text-[var(--primary-foreground)] font-mono font-bold cursor-pointer">
              Aktualisieren
            </button>
          </div>
        </div>

        ${
          _bannerMsg
            ? `<div class="px-3 py-2 rounded-lg border border-sky-500/40 bg-sky-500/10 text-sky-400 font-mono text-[11px] flex items-center justify-between">
                <span>${esc(_bannerMsg)}</span>
                <button type="button" id="cm-banner-close" class="underline ml-3 cursor-pointer">Schließen</button>
              </div>`
            : ""
        }

        <!-- KPI ZEILE -->
        <div class="grid grid-cols-2 sm:grid-cols-6 gap-2.5">
          <div class="p-2.5 rounded-xl border border-[var(--border)] bg-[var(--background)]">
            <div class="text-[10px] font-mono text-[var(--muted-foreground)] uppercase">Kampagnen</div>
            <div class="text-base font-bold font-mono mt-0.5">${_campaigns.length}</div>
          </div>
          <div class="p-2.5 rounded-xl border border-[var(--border)] bg-[var(--background)]">
            <div class="text-[10px] font-mono text-[var(--muted-foreground)] uppercase">Assets Gesamt</div>
            <div class="text-base font-bold font-mono mt-0.5">${_assets.length}</div>
          </div>
          <div class="p-2.5 rounded-xl border border-[var(--border)] bg-[var(--background)]">
            <div class="text-[10px] font-mono text-amber-500 uppercase">In Review (HITL)</div>
            <div class="text-base font-bold font-mono mt-0.5 text-amber-500">${Number(statusCounts.review || 0)}</div>
          </div>
          <div class="p-2.5 rounded-xl border border-[var(--border)] bg-[var(--background)]">
            <div class="text-[10px] font-mono text-sky-500 uppercase">Freigegeben</div>
            <div class="text-base font-bold font-mono mt-0.5 text-sky-500">${Number(statusCounts.approved || 0)}</div>
          </div>
          <div class="p-2.5 rounded-xl border border-[var(--border)] bg-[var(--background)]">
            <div class="text-[10px] font-mono text-indigo-400 uppercase">Geplant</div>
            <div class="text-base font-bold font-mono mt-0.5 text-indigo-400">${Number(statusCounts.scheduled || 0)}</div>
          </div>
          <div class="p-2.5 rounded-xl border border-[var(--border)] bg-[var(--background)]">
            <div class="text-[10px] font-mono text-emerald-500 uppercase">Publiziert</div>
            <div class="text-base font-bold font-mono mt-0.5 text-emerald-500">${Number(statusCounts.published || 0)}</div>
          </div>
        </div>

        <!-- HAUPTBEREICH: LINKS KAMPAGNE + INGESTION, RECHTS ASSETS & PIPELINE -->
        <div class="grid grid-cols-1 lg:grid-cols-12 gap-4 flex-1 min-h-0">
          <!-- LINKE SPALTE (4 Cols): Neue Kampagne & v2 Quellen-Ingestion -->
          <div class="lg:col-span-4 space-y-3">
            <!-- 1. Neue Kampagne -->
            <div class="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--background)] space-y-2.5">
              <div class="font-mono font-bold text-xs uppercase tracking-wider">1. Neue Multi-Channel-Kampagne</div>
              <input id="cm-new-title" type="text" placeholder="Kampagnen-Titel (z. B. KI-Agenten im Mittelstand)" class="w-full h-8 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--card)] text-xs" />
              <textarea id="cm-new-topic" rows="2" placeholder="Kernthema, These oder Zahlen-Anker..." class="w-full p-2 rounded-lg border border-[var(--border)] bg-[var(--card)] text-xs"></textarea>
              <input id="cm-new-audience" type="text" placeholder="Zielgruppe (z. B. Geschäftsführer & CTOs)" class="w-full h-8 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--card)] text-xs" />
              <div class="flex items-center justify-between gap-2 pt-1">
                <label class="flex items-center gap-1.5 text-[11px] font-mono cursor-pointer">
                  <input id="cm-dry-run" type="checkbox" checked class="accent-red-600" />
                  <span>Dry-Run (Sofort-Vorschau ohne Token)</span>
                </label>
                <button type="button" id="cm-btn-create-camp" class="px-3 py-1.5 rounded-lg bg-red-600 hover:bg-red-500 text-white font-mono font-bold cursor-pointer">
                  + Kampagne &amp; DAG
                </button>
              </div>
            </div>

            <!-- 2. Quellen-Ingestion v2 (URL / Obsidian / Transkript) -->
            <div class="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--background)] space-y-2.5">
              <div class="font-mono font-bold text-xs uppercase tracking-wider text-sky-400">2. Quellen-Ingestion v2 (URL · Obsidian · Transkript)</div>
              <div class="grid grid-cols-3 gap-1.5">
                <select id="cm-ingest-type" class="h-8 px-2 rounded-lg border border-[var(--border)] bg-[var(--card)] text-xs font-mono">
                  <option value="transcript">Transkript</option>
                  <option value="url">Web-URL (SSRF-safe)</option>
                  <option value="obsidian">Obsidian-Notiz</option>
                </select>
                <input id="cm-ingest-title" type="text" placeholder="Optionaler Titel" class="col-span-2 h-8 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--card)] text-xs" />
              </div>
              <input id="cm-ingest-ref" type="text" placeholder="Bei URL: https://... | Bei Obsidian: Relativer Vault-Pfad" class="w-full h-8 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--card)] text-xs font-mono" />
              <textarea id="cm-ingest-text" rows="2" placeholder="Bei Transkript: Rohtext / Podcast-Notizen hier einfügen..." class="w-full p-2 rounded-lg border border-[var(--border)] bg-[var(--card)] text-xs"></textarea>
              <button type="button" id="cm-btn-ingest" class="w-full py-1.5 rounded-lg border border-sky-500/40 bg-sky-500/15 hover:bg-sky-500/25 text-sky-400 font-mono font-bold cursor-pointer">
                Quelle einlesen &amp; als Kampagne anlegen
              </button>
            </div>

            <!-- 3. Kampagnen-Liste -->
            <div class="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--background)] space-y-2">
              <div class="flex items-center justify-between">
                <span class="font-mono font-bold text-xs uppercase tracking-wider">Aktive Kampagnen (${_campaigns.length})</span>
                ${
                  _selectedCampaignId
                    ? `<button type="button" id="cm-clear-camp-filter" class="text-[10px] font-mono underline text-sky-400 cursor-pointer">Alle zeigen</button>`
                    : ""
                }
              </div>
              <div class="space-y-2 max-h-72 overflow-y-auto pr-1">
                ${
                  _campaigns.length === 0
                    ? `<div class="text-[11px] text-[var(--muted-foreground)] py-4 text-center">Noch keine Kampagne angelegt.</div>`
                    : _campaigns
                        .map(
                          (c) => `
                      <div class="p-2.5 rounded-lg border ${
                        _selectedCampaignId === c.id ? "border-red-500 bg-red-500/5" : "border-[var(--border)] bg-[var(--card)]"
                      } space-y-1.5">
                        <div class="flex items-center justify-between gap-2">
                          <button type="button" data-select-camp="${esc(c.id)}" class="font-bold text-left hover:text-red-500 truncate cursor-pointer">
                            ${esc(c.title)}
                          </button>
                          <span class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-[var(--secondary)]">${esc(c.status)}</span>
                        </div>
                        <div class="text-[11px] text-[var(--muted-foreground)] line-clamp-2">${esc(c.topic)}</div>
                        <div class="flex items-center gap-1.5 pt-1 flex-wrap">
                          <button type="button" data-run-dag="${esc(c.id)}" class="px-2 py-1 rounded bg-red-600/15 hover:bg-red-600/25 text-red-400 font-mono text-[10px] font-bold cursor-pointer">
                            5-Kanal-DAG starten
                          </button>
                          <button type="button" data-run-clips="${esc(c.id)}" class="px-2 py-1 rounded bg-purple-500/15 hover:bg-purple-500/25 text-purple-400 font-mono text-[10px] font-bold cursor-pointer">
                            + 9:16 Video-Clips (Shorts/TikTok)
                          </button>
                        </div>
                      </div>`
                        )
                        .join("")
                }
              </div>
            </div>
          </div>

          <!-- RECHTE SPALTE (8 Cols): Asset-Cards mit Anti-Slop Quality Gate, HITL-Freigabe & Metriken -->
          <div class="lg:col-span-8 flex flex-col space-y-3">
            <div class="p-3 rounded-xl border border-[var(--border)] bg-[var(--background)] flex flex-wrap items-center justify-between gap-2">
              <div class="flex items-center gap-1.5 flex-wrap">
                <button type="button" data-ch-filter="" class="px-2.5 py-1 rounded-lg font-mono text-[11px] cursor-pointer ${
                  !_channelFilter ? "bg-red-600 text-white font-bold" : "bg-[var(--card)] border border-[var(--border)]"
                }">Alle Kanäle</button>
                ${CHANNELS.map(
                  (ch) => `
                  <button type="button" data-ch-filter="${esc(ch.id)}" class="px-2.5 py-1 rounded-lg font-mono text-[11px] cursor-pointer ${
                    _channelFilter === ch.id ? "bg-red-600 text-white font-bold" : "bg-[var(--card)] border border-[var(--border)]"
                  }">${esc(ch.label)}</button>`
                ).join("")}
              </div>
              <select id="cm-status-filter" class="h-7 px-2 rounded-lg border border-[var(--border)] bg-[var(--card)] text-[11px] font-mono">
                <option value="" ${!_statusFilter ? "selected" : ""}>Alle Status</option>
                <option value="review" ${_statusFilter === "review" ? "selected" : ""}>In Review (HITL)</option>
                <option value="approved" ${_statusFilter === "approved" ? "selected" : ""}>Freigegeben</option>
                <option value="scheduled" ${_statusFilter === "scheduled" ? "selected" : ""}>Geplant</option>
                <option value="published" ${_statusFilter === "published" ? "selected" : ""}>Publiziert</option>
              </select>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
              ${
                _assets.length === 0
                  ? `<div class="col-span-2 p-8 rounded-xl border border-[var(--border)] bg-[var(--background)] text-center text-[var(--muted-foreground)]">
                      Noch keine Content-Assets für diesen Filter. Starte links eine Kampagne oder den 5-Kanal-Repurposing-DAG.
                    </div>`
                  : _assets
                      .map((a) => {
                        const qScore = Number(a.quality_score || 0);
                        const qRep = a.quality_report || {};
                        const qIssues = qRep.issues || [];
                        const qColor =
                          qScore >= 80
                            ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
                            : qScore >= 65
                            ? "bg-amber-500/15 text-amber-400 border-amber-500/30"
                            : "bg-rose-500/15 text-rose-400 border-rose-500/30";
                        return `
                        <div class="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--background)] flex flex-col justify-between space-y-2.5">
                          <div class="space-y-1.5">
                            <div class="flex items-center justify-between gap-1.5 flex-wrap">
                              <span class="px-2 py-0.5 rounded bg-[var(--secondary)] font-mono font-bold text-[10px] uppercase">${esc(
                                a.channel
                              )} · ${esc(a.format_type)}</span>
                              <div class="flex items-center gap-1.5">
                                <span class="px-2 py-0.5 rounded border font-mono font-bold text-[10px] ${qColor}" title="${esc(
                          qIssues.join(" | ") || "Anti-Slop-Prüfung bestanden"
                        )}">
                                  Anti-Slop Q: ${qScore}/100
                                </span>
                                <span class="px-2 py-0.5 rounded bg-[var(--card)] border border-[var(--border)] font-mono text-[10px]">${esc(
                                  a.status
                                )}</span>
                              </div>
                            </div>
                            <div class="font-bold text-xs">${esc(a.title)}</div>
                            ${
                              a.hook
                                ? `<div class="p-2 rounded-lg bg-[var(--card)] border-l-2 border-red-500 text-[11px] font-medium">
                                    <span class="font-mono text-[10px] text-red-400 uppercase block">Hook (${a.hook.length} Z.):</span>
                                    ${esc(a.hook)}
                                  </div>`
                                : ""
                            }
                            <div class="text-[11px] text-[var(--muted-foreground)] whitespace-pre-line max-h-36 overflow-y-auto">${esc(
                              a.body
                            )}</div>
                            ${
                              a.visual_brief
                                ? `<div class="text-[10px] font-mono text-sky-400">🎬 Visual: ${esc(a.visual_brief)}</div>`
                                : ""
                            }
                            ${
                              qIssues.length
                                ? `<div class="text-[10px] font-mono text-amber-400">⚠ ${esc(qIssues.join(" · "))}</div>`
                                : ""
                            }
                          </div>

                          <div class="pt-2 border-t border-[var(--border)] flex items-center justify-between gap-1.5 flex-wrap">
                            ${
                              a.status === "review" || a.status === "draft"
                                ? `<button type="button" data-approve-asset="${esc(
                                    a.id
                                  )}" class="px-2.5 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-mono text-[10px] font-bold cursor-pointer">
                                    ✓ HITL Freigeben
                                  </button>`
                                : ""
                            }
                            ${
                              a.status === "approved" || a.status === "scheduled"
                                ? `<button type="button" data-publish-asset="${esc(
                                    a.id
                                  )}" class="px-2.5 py-1 rounded bg-sky-600 hover:bg-sky-500 text-white font-mono text-[10px] font-bold cursor-pointer">
                                    🚀 Als publiziert markieren
                                  </button>`
                                : ""
                            }
                            <button type="button" data-metrics-asset="${esc(
                              a.id
                            )}" class="px-2 py-1 rounded border border-[var(--border)] bg-[var(--card)] hover:bg-[var(--secondary)] font-mono text-[10px] cursor-pointer ml-auto">
                              📊 Performance-Feedback
                            </button>
                          </div>
                        </div>`;
                      })
                      .join("")
              }
            </div>
          </div>
        </div>
      </div>
    `;

    bindContentStudioEvents(host);
  }

  function bindContentStudioEvents(host) {
    const closeBtn = host.querySelector("#cm-banner-close");
    if (closeBtn) {
      closeBtn.onclick = () => {
        _bannerMsg = "";
        renderContentStudioShell();
      };
    }

    const refBtn = host.querySelector("#cm-btn-refresh");
    if (refBtn) refBtn.onclick = () => reloadContentStudioData();

    const dueBtn = host.querySelector("#cm-btn-publish-due");
    if (dueBtn) {
      dueBtn.onclick = async () => {
        try {
          const res = await apiJson("/api/v2/content-machine/publish-due", {
            method: "POST",
            body: JSON.stringify({ dry_run: false }),
          });
          _bannerMsg = `Due-Publish-Sweep: ${res.due_count || 0} fällige Assets geprüft, ${(res.published || []).length} publiziert.`;
          await reloadContentStudioData();
        } catch (err) {
          _bannerMsg = "Publish-Due fehlgeschlagen: " + err.message;
          renderContentStudioShell();
        }
      };
    }

    const dbBtn = host.querySelector("#cm-btn-db-consolidate");
    if (dbBtn) {
      dbBtn.onclick = async () => {
        try {
          const res = await apiJson("/api/v2/system/db-consolidation/run", {
            method: "POST",
            body: JSON.stringify({ dry_run: false, create_backup: true, activate: true }),
          });
          _bannerMsg = `SQLite 28→3 Konsolidierung erfolgreich (${res.status}) — ops.db, business.db & memory.db aktiv.`;
          await reloadContentStudioData();
        } catch (err) {
          _bannerMsg = "DB-Konsolidierung: " + err.message;
          renderContentStudioShell();
        }
      };
    }

    const createBtn = host.querySelector("#cm-btn-create-camp");
    if (createBtn) {
      createBtn.onclick = async () => {
        if (_busy) return;
        const title = (host.querySelector("#cm-new-title")?.value || "").trim();
        const topic = (host.querySelector("#cm-new-topic")?.value || "").trim() || title;
        const audience = (host.querySelector("#cm-new-audience")?.value || "").trim();
        const dryRun = !!host.querySelector("#cm-dry-run")?.checked;
        if (!title) {
          _bannerMsg = "Bitte einen Kampagnen-Titel eingeben.";
          renderContentStudioShell();
          return;
        }
        _busy = true;
        try {
          const created = await apiJson("/api/v2/content-machine/campaigns", {
            method: "POST",
            body: JSON.stringify({
              title,
              topic,
              target_audience: audience || "Geschäftsführer, Gründer & Tech-Entscheider",
              channels: CHANNELS.map((c) => c.id),
            }),
          });
          const campId = created.campaign.id;
          _selectedCampaignId = campId;
          const gen = await apiJson(`/api/v2/content-machine/campaigns/${encodeURIComponent(campId)}/generate`, {
            method: "POST",
            body: JSON.stringify({ require_hitl_gate: true, dry_run: dryRun }),
          });
          _bannerMsg = `Kampagne '${title}' erstellt & ${(gen.assets_created || []).length} Kanal-Assets im Status 'review' generiert.`;
          await reloadContentStudioData();
        } catch (err) {
          _bannerMsg = "Kampagnen-Start fehlgeschlagen: " + err.message;
          renderContentStudioShell();
        } finally {
          _busy = false;
        }
      };
    }

    const ingestBtn = host.querySelector("#cm-btn-ingest");
    if (ingestBtn) {
      ingestBtn.onclick = async () => {
        const stype = host.querySelector("#cm-ingest-type")?.value || "transcript";
        const title = (host.querySelector("#cm-ingest-title")?.value || "").trim();
        const ref = (host.querySelector("#cm-ingest-ref")?.value || "").trim();
        const rawText = (host.querySelector("#cm-ingest-text")?.value || "").trim();
        try {
          const payload = { source_type: stype, title };
          if (stype === "url") payload.source_url = ref;
          else if (stype === "obsidian") payload.obsidian_path = ref;
          else payload.transcript = rawText || ref;

          const res = await apiJson("/api/v2/content-machine/ingest", {
            method: "POST",
            body: JSON.stringify(payload),
          });
          _selectedCampaignId = res.campaign.id;
          _bannerMsg = `Quelle (${res.source_type}, ${res.ingested_chars} Zeichen) als Kampagne '${res.campaign.title}' angelegt.`;
          await reloadContentStudioData();
        } catch (err) {
          _bannerMsg = "Quellen-Ingestion fehlgeschlagen: " + err.message;
          renderContentStudioShell();
        }
      };
    }

    const clearCamp = host.querySelector("#cm-clear-camp-filter");
    if (clearCamp) {
      clearCamp.onclick = () => {
        _selectedCampaignId = "";
        reloadContentStudioData();
      };
    }

    host.querySelectorAll("[data-select-camp]").forEach((btn) => {
      btn.onclick = () => {
        _selectedCampaignId = btn.getAttribute("data-select-camp") || "";
        reloadContentStudioData();
      };
    });

    host.querySelectorAll("[data-run-dag]").forEach((btn) => {
      btn.onclick = async () => {
        const cid = btn.getAttribute("data-run-dag");
        const dryRun = !!host.querySelector("#cm-dry-run")?.checked;
        try {
          const res = await apiJson(`/api/v2/content-machine/campaigns/${encodeURIComponent(cid)}/generate`, {
            method: "POST",
            body: JSON.stringify({ require_hitl_gate: true, dry_run: dryRun }),
          });
          _selectedCampaignId = cid;
          _bannerMsg = `Repurposing-DAG ausgeführt: ${(res.assets_created || []).length} Assets erzeugt (DAG-Status: ${res.dag_status}).`;
          await reloadContentStudioData();
        } catch (err) {
          _bannerMsg = "DAG-Lauf fehlgeschlagen: " + err.message;
          renderContentStudioShell();
        }
      };
    });

    host.querySelectorAll("[data-run-clips]").forEach((btn) => {
      btn.onclick = async () => {
        const cid = btn.getAttribute("data-run-clips");
        const dryRun = !!host.querySelector("#cm-dry-run")?.checked;
        try {
          const res = await apiJson(`/api/v2/content-machine/campaigns/${encodeURIComponent(cid)}/clip-matrix`, {
            method: "POST",
            body: JSON.stringify({ clip_count: 3, target_channels: ["youtube_shorts", "tiktok"], dry_run: dryRun }),
          });
          _selectedCampaignId = cid;
          _bannerMsg = `${res.count || 0} vertikale 9:16 Kurzvideo-Clips (YouTube Shorts & TikTok) erstellt.`;
          await reloadContentStudioData();
        } catch (err) {
          _bannerMsg = "9:16 Clip-Matrix fehlgeschlagen: " + err.message;
          renderContentStudioShell();
        }
      };
    });

    host.querySelectorAll("[data-ch-filter]").forEach((btn) => {
      btn.onclick = () => {
        _channelFilter = btn.getAttribute("data-ch-filter") || "";
        reloadContentStudioData();
      };
    });

    const stSel = host.querySelector("#cm-status-filter");
    if (stSel) {
      stSel.onchange = () => {
        _statusFilter = stSel.value || "";
        reloadContentStudioData();
      };
    }

    host.querySelectorAll("[data-approve-asset]").forEach((btn) => {
      btn.onclick = async () => {
        const aid = btn.getAttribute("data-approve-asset");
        try {
          await apiJson(`/api/v2/content-machine/assets/${encodeURIComponent(aid)}/approve`, {
            method: "POST",
            body: JSON.stringify({}),
          });
          _bannerMsg = `Asset ${aid} freigegeben.`;
          await reloadContentStudioData();
        } catch (err) {
          _bannerMsg = "Freigabe fehlgeschlagen: " + err.message;
          renderContentStudioShell();
        }
      };
    });

    host.querySelectorAll("[data-publish-asset]").forEach((btn) => {
      btn.onclick = async () => {
        const aid = btn.getAttribute("data-publish-asset");
        try {
          await apiJson(`/api/v2/content-machine/assets/${encodeURIComponent(aid)}/publish`, {
            method: "POST",
            body: JSON.stringify({}),
          });
          _bannerMsg = `Asset ${aid} als publiziert markiert.`;
          await reloadContentStudioData();
        } catch (err) {
          _bannerMsg = "Publizieren fehlgeschlagen: " + err.message;
          renderContentStudioShell();
        }
      };
    });

    host.querySelectorAll("[data-metrics-asset]").forEach((btn) => {
      btn.onclick = async () => {
        const aid = btn.getAttribute("data-metrics-asset");
        try {
          const res = await apiJson(`/api/v2/content-machine/assets/${encodeURIComponent(aid)}/metrics`, {
            method: "POST",
            body: JSON.stringify({
              views: 3200,
              likes: 210,
              comments: 34,
              shares: 28,
              saves: 55,
              ctr_pct: 4.8,
              write_learning_to_memory: true,
            }),
          });
          _bannerMsg = `Performance erfasst (Engagement-Rate: ${res.engagement_rate_pct}%) & Learning in memory.db gespeichert.`;
          await reloadContentStudioData();
        } catch (err) {
          _bannerMsg = "Metrik-Erfassung fehlgeschlagen: " + err.message;
          renderContentStudioShell();
        }
      };
    });
  }

  window.renderEmbeddedContentMachineStudio = function () {
    ensureContentTabButton();
    reloadContentStudioData();
  };

  window.openContentMachineStudio = function () {
    ensureContentTabButton();
    if (typeof window.setOperationsTab === "function") {
      window.setOperationsTab("content");
    }
    reloadContentStudioData();
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ensureContentTabButton);
  } else {
    ensureContentTabButton();
  }
})();
