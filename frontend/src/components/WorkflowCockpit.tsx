'use client';

import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import {
  archonApi,
  DbConsolidationPlan,
  WorkflowRunDetail,
  WorkflowRunSummary,
  WorkflowTemplate,
} from '@/lib/archon-api';
import { useArchonEvents } from '@/lib/useArchonEvents';
import {
  Check,
  Database,
  Play,
  RefreshCw,
  Workflow,
  X,
} from 'lucide-react';

export function WorkflowCockpit() {
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [runs, setRuns] = useState<WorkflowRunSummary[]>([]);
  const [selectedRun, setSelectedRun] = useState<WorkflowRunDetail | null>(null);
  const [dbPlan, setDbPlan] = useState<DbConsolidationPlan | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [tplRes, runRes, planRes] = await Promise.all([
        archonApi.listWorkflowTemplates().catch(() => ({ templates: [] })),
        archonApi.listDagRuns().catch(() => ({ runs: [] })),
        archonApi.getDbConsolidationPlan().catch(() => null),
      ]);
      setTemplates(tplRes.templates || []);
      setRuns(runRes.runs || []);
      setDbPlan(planRes);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Fehler beim Laden der Workflow-Daten');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  // Live-DAG-Status und HITL-Gates über den gemeinsamen SSE-Bus.
  useArchonEvents((event) => {
    // Echte Backend-Typen (broadcast_event): kanban_updated, ticker_update,
    // workflow_node_state, event_bus, delegation_failed, tool_runtime.
    // workflow_node_state ist der echte DAG-Knoten-Event (statt dag_node_completed).
    if (!['kanban_updated', 'ticker_update', 'workflow_node_state', 'event_bus',
          'delegation_failed', 'tool_runtime',
          'gate_reached', 'workflow_completed', 'workflow_failed',
          'dag_node_completed'].includes(event.type)) return;
    archonApi.listDagRuns()
      .then((res) => setRuns(res.runs || []))
      .catch(() => undefined);
  });

  const inspectRun = async (runId: string) => {
    setBusyId(runId);
    try {
      const res = await archonApi.getDagRun(runId);
      setSelectedRun(res.run);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Run-Details nicht ladbar');
    } finally {
      setBusyId(null);
    }
  };

  const handleRunTemplate = async (tplId: string) => {
    setBusyId(tplId);
    setError(null);
    try {
      await archonApi.runWorkflowTemplate(tplId, {});
      await loadAll();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Workflow konnte nicht gestartet werden');
    } finally {
      setBusyId(null);
    }
  };

  const handleGateDecision = async (runId: string, nodeId: string, approved: boolean) => {
    setBusyId(`${runId}:${nodeId}`);
    try {
      await archonApi.resumeDagRun(runId, { [nodeId]: approved });
      await inspectRun(runId);
      await loadAll();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Gate-Entscheidung fehlgeschlagen');
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        <header className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500 to-indigo-600 flex items-center justify-center shadow-lg">
              <Workflow className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-tight">Workflow- &amp; DAG-Cockpit</h1>
              <p className="text-xs text-slate-400 font-mono">
                Multi-Agenten-Orchestrierung · HITL-Gates · SQLite-Konsolidierung (28 &rarr; 3)
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Link
              href="/"
              className="px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-900 hover:bg-slate-800 text-xs font-medium"
            >
              Zurueck zum Cockpit
            </Link>
            <button
              onClick={loadAll}
              disabled={loading}
              className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold flex items-center gap-1.5"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              Aktualisieren
            </button>
          </div>
        </header>

        {error && (
          <div className="p-3 rounded-lg border border-rose-500/40 bg-rose-500/10 text-rose-200 text-xs">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
          {/* Templates */}
          <section className="lg:col-span-5 p-4 rounded-xl border border-slate-800 bg-slate-900/70 space-y-3">
            <h2 className="text-sm font-bold">Workflow-Templates ({templates.length})</h2>
            <div className="space-y-2 max-h-[420px] overflow-y-auto pr-1">
              {templates.map((tpl) => (
                <div
                  key={tpl.id}
                  className="p-3 rounded-lg border border-slate-800 bg-slate-950/70 flex items-center justify-between gap-2"
                >
                  <div className="min-w-0">
                    <div className="text-sm font-semibold truncate">{tpl.title}</div>
                    <div className="text-[11px] text-slate-400 font-mono">
                      {tpl.id} · {(tpl.nodes || []).length} Knoten
                    </div>
                  </div>
                  <button
                    onClick={() => handleRunTemplate(tpl.id)}
                    disabled={busyId === tpl.id}
                    className="px-2.5 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-500 text-xs font-semibold flex items-center gap-1 shrink-0"
                  >
                    <Play className="w-3 h-3" />
                    Starten
                  </button>
                </div>
              ))}
            </div>
          </section>

          {/* Active & Recent DAG Runs */}
          <section className="lg:col-span-7 p-4 rounded-xl border border-slate-800 bg-slate-900/70 space-y-3">
            <h2 className="text-sm font-bold">DAG-Laeufe &amp; HITL-Gates ({runs.length})</h2>
            <div className="space-y-2 max-h-[240px] overflow-y-auto pr-1">
              {runs.map((r) => (
                <button
                  key={r.run_id}
                  onClick={() => inspectRun(r.run_id)}
                  className={`w-full text-left p-2.5 rounded-lg border transition flex items-center justify-between gap-2 ${
                    selectedRun?.run_id === r.run_id
                      ? 'border-indigo-500 bg-indigo-500/10'
                      : 'border-slate-800 bg-slate-950/70 hover:bg-slate-900'
                  }`}
                >
                  <div className="min-w-0">
                    <div className="text-xs font-mono font-semibold truncate">{r.run_id}</div>
                    <div className="text-[11px] text-slate-400 truncate">{r.workflow_id}</div>
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-200">
                    {r.status}
                  </span>
                </button>
              ))}
            </div>

            {selectedRun && (
              <div className="pt-3 border-t border-slate-800 space-y-2">
                <div className="text-xs font-mono text-indigo-300">
                  Knoten-Status fuer {selectedRun.run_id} ({selectedRun.status})
                </div>
                <div className="space-y-1.5">
                  {Object.entries(selectedRun.nodes || {}).map(([nid, info]) => (
                    <div
                      key={nid}
                      className="p-2.5 rounded-lg border border-slate-800 bg-slate-950 flex items-center justify-between gap-2 text-xs"
                    >
                      <div>
                        <span className="font-mono font-semibold">{nid}</span>
                        <span className="ml-2 text-slate-400">[{info.status}]</span>
                      </div>
                      {info.status === 'awaiting_gate' && (
                        <div className="flex items-center gap-1.5">
                          <button
                            onClick={() => handleGateDecision(selectedRun.run_id, nid, true)}
                            disabled={busyId === `${selectedRun.run_id}:${nid}`}
                            className="px-2 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white flex items-center gap-1"
                          >
                            <Check className="w-3 h-3" /> Freigeben
                          </button>
                          <button
                            onClick={() => handleGateDecision(selectedRun.run_id, nid, false)}
                            disabled={busyId === `${selectedRun.run_id}:${nid}`}
                            className="px-2 py-1 rounded bg-rose-600 hover:bg-rose-500 text-white flex items-center gap-1"
                          >
                            <X className="w-3 h-3" /> Ablehnen
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>
        </div>

        {/* DB Consolidation Status */}
        {dbPlan && (
          <section className="p-4 rounded-xl border border-slate-800 bg-slate-900/70 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-bold flex items-center gap-2">
                <Database className="w-4 h-4 text-sky-400" />
                SQLite-Konsolidierung (28 &rarr; 3 Domaenen-DBs)
              </h2>
              <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300">
                {dbPlan.consolidated_active ? 'Aktiv (ops/business/memory.db)' : 'Bereit (Legacy-Modus)'}
              </span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {dbPlan.target_domains.map((dom) => {
                const d = dbPlan.domains[dom];
                return (
                  <div key={dom} className="p-3 rounded-lg border border-slate-800 bg-slate-950/70 space-y-1">
                    <div className="font-mono text-xs font-bold text-sky-300">{dom}</div>
                    <div className="text-xs text-slate-400">
                      Quellen: {d?.source_files?.length ? d.source_files.join(', ') : 'noch leer'}
                    </div>
                    <div className="text-[11px] font-mono text-slate-500">
                      {d?.table_mappings?.length || 0} Tabellen · {d?.total_rows || 0} Zeilen
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
