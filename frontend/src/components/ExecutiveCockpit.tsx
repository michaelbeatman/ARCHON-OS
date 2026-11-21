'use client';

import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import {
  archonApi,
  ContentOverview,
  DbConsolidationPlan,
  WorkflowRunSummary,
} from '@/lib/archon-api';
import {
  Activity,
  CheckCircle2,
  Clapperboard,
  Database,
  LayoutDashboard,
  RefreshCw,
  ShieldCheck,
  Users,
  Workflow,
  XCircle,
} from 'lucide-react';

interface KanbanTask {
  id: string;
  title?: string;
  status?: string;
  assignee?: string;
  block_kind?: string;
  priority?: number;
}

interface CrmContact {
  id: string;
  name?: string;
  unternehmen?: string;
  status?: string;
  rolle?: string;
}

export function ExecutiveCockpit() {
  const [health, setHealth] = useState<{
    status: string;
    services: Record<string, { status: string; latency_ms?: number }>;
  } | null>(null);
  const [tasks, setTasks] = useState<KanbanTask[]>([]);
  const [contacts, setContacts] = useState<CrmContact[]>([]);
  const [runs, setRuns] = useState<WorkflowRunSummary[]>([]);
  const [content, setContent] = useState<ContentOverview | null>(null);
  const [dbPlan, setDbPlan] = useState<DbConsolidationPlan | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [hRes, tRes, cRes, rRes, cmRes, dbRes] = await Promise.all([
        archonApi.getSystemHealth().catch(() => null),
        archonApi.listKanbanTasks().catch(() => ({ tasks: [] })),
        archonApi.listCrmContacts(15).catch(() => ({ contacts: [] })),
        archonApi.listDagRuns().catch(() => ({ runs: [] })),
        archonApi.getContentOverview().catch(() => null),
        archonApi.getDbConsolidationPlan().catch(() => null),
      ]);
      setHealth(hRes);
      setTasks(((tRes.tasks || tRes.items || []) as unknown) as KanbanTask[]);
      setContacts(((cRes.contacts || cRes.items || []) as unknown) as CrmContact[]);
      setRuns(rRes.runs || []);
      setContent(cmRes);
      setDbPlan(dbRes);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Cockpit-Daten konnten nicht geladen werden');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const handleTaskMove = async (taskId: string, nextStatus: string) => {
    setBusyId(taskId);
    try {
      await archonApi.moveKanbanTask(taskId, nextStatus);
      await loadAll();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Status-Wechsel fehlgeschlagen');
    } finally {
      setBusyId(null);
    }
  };

  const openHitlTasks = tasks.filter(
    (t) => t.status === 'review' || t.status === 'blocked' || Boolean(t.block_kind)
  );
  const activeTasks = tasks.filter((t) => t.status === 'in_progress' || t.status === 'todo');

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        <header className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-sky-500 to-indigo-600 flex items-center justify-center shadow-lg">
              <LayoutDashboard className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-tight">Archon Executive Cockpit</h1>
              <p className="text-xs text-slate-400 font-mono">
                Direkt auf Archon FastAPI (Port 8420) · Ohne PocketBase · Operations, HITL, Content &amp; CRM
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href="/content-studio"
              className="px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-900 hover:bg-slate-800 text-xs font-medium flex items-center gap-1.5"
            >
              <Clapperboard className="w-3.5 h-3.5 text-fuchsia-400" />
              Content-Maschine
            </Link>
            <Link
              href="/workflows"
              className="px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-900 hover:bg-slate-800 text-xs font-medium flex items-center gap-1.5"
            >
              <Workflow className="w-3.5 h-3.5 text-emerald-400" />
              Workflow-Cockpit
            </Link>
            <Link
              href="/"
              className="px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-900 hover:bg-slate-800 text-xs font-medium"
            >
              Legacy CRM
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

        {/* Top KPIs */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <div className="p-3.5 rounded-xl border border-slate-800 bg-slate-900/70">
            <div className="text-[11px] font-mono uppercase text-slate-400 flex items-center gap-1">
              <Activity className="w-3.5 h-3.5 text-emerald-400" /> System-Status
            </div>
            <div className="text-lg font-bold mt-1">{health?.status || 'unbekannt'}</div>
          </div>
          <div className="p-3.5 rounded-xl border border-slate-800 bg-slate-900/70">
            <div className="text-[11px] font-mono uppercase text-slate-400 flex items-center gap-1">
              <ShieldCheck className="w-3.5 h-3.5 text-amber-400" /> Offene HITL / Review
            </div>
            <div className="text-lg font-bold mt-1">{openHitlTasks.length}</div>
          </div>
          <div className="p-3.5 rounded-xl border border-slate-800 bg-slate-900/70">
            <div className="text-[11px] font-mono uppercase text-slate-400 flex items-center gap-1">
              <Workflow className="w-3.5 h-3.5 text-indigo-400" /> DAG-Laeufe
            </div>
            <div className="text-lg font-bold mt-1">{runs.length}</div>
          </div>
          <div className="p-3.5 rounded-xl border border-slate-800 bg-slate-900/70">
            <div className="text-[11px] font-mono uppercase text-slate-400 flex items-center gap-1">
              <Clapperboard className="w-3.5 h-3.5 text-fuchsia-400" /> Content-Assets
            </div>
            <div className="text-lg font-bold mt-1">{content?.assets?.length || 0}</div>
          </div>
          <div className="p-3.5 rounded-xl border border-slate-800 bg-slate-900/70">
            <div className="text-[11px] font-mono uppercase text-slate-400 flex items-center gap-1">
              <Database className="w-3.5 h-3.5 text-sky-400" /> DB-Modus
            </div>
            <div className="text-sm font-bold mt-1">
              {dbPlan?.consolidated_active ? '3 DBs (WAL)' : 'Legacy-Compat'}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
          {/* Kanban & HITL */}
          <section className="lg:col-span-7 p-4 rounded-xl border border-slate-800 bg-slate-900/70 space-y-3">
            <h2 className="text-sm font-bold">
              Aktive Kanban- &amp; HITL-Tasks ({openHitlTasks.length} Review/Blocked · {activeTasks.length} Aktiv)
            </h2>
            <div className="space-y-2 max-h-[380px] overflow-y-auto pr-1">
              {[...openHitlTasks, ...activeTasks].slice(0, 20).map((t) => (
                <div
                  key={t.id}
                  className="p-3 rounded-lg border border-slate-800 bg-slate-950/70 flex flex-wrap items-center justify-between gap-2 text-xs"
                >
                  <div className="min-w-0 flex-1">
                    <div className="font-semibold truncate">{t.title || t.id}</div>
                    <div className="text-[11px] text-slate-400 font-mono">
                      {t.id} · @{t.assignee || 'unassigned'} · {t.status}
                      {t.block_kind ? ` (${t.block_kind})` : ''}
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    {t.status !== 'done' && (
                      <button
                        onClick={() => handleTaskMove(t.id, 'done')}
                        disabled={busyId === t.id}
                        className="px-2 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white flex items-center gap-1"
                      >
                        <CheckCircle2 className="w-3 h-3" /> Done
                      </button>
                    )}
                    {t.status !== 'blocked' && (
                      <button
                        onClick={() => handleTaskMove(t.id, 'blocked')}
                        disabled={busyId === t.id}
                        className="px-2 py-1 rounded border border-rose-500/40 text-rose-300 hover:bg-rose-500/10 flex items-center gap-1"
                      >
                        <XCircle className="w-3 h-3" /> Block
                      </button>
                    )}
                  </div>
                </div>
              ))}
              {tasks.length === 0 && (
                <p className="text-xs text-slate-400 py-6 text-center">Keine Kanban-Tasks geladen.</p>
              )}
            </div>
          </section>

          {/* CRM Contacts directly via FastAPI */}
          <section className="lg:col-span-5 p-4 rounded-xl border border-slate-800 bg-slate-900/70 space-y-3">
            <h2 className="text-sm font-bold flex items-center gap-2">
              <Users className="w-4 h-4 text-teal-400" />
              CRM-Kontakte via FastAPI ({contacts.length})
            </h2>
            <div className="space-y-2 max-h-[380px] overflow-y-auto pr-1">
              {contacts.map((c) => (
                <div
                  key={c.id}
                  className="p-2.5 rounded-lg border border-slate-800 bg-slate-950/70 flex items-center justify-between gap-2 text-xs"
                >
                  <div className="min-w-0">
                    <div className="font-semibold truncate">{c.name || c.id}</div>
                    <div className="text-[11px] text-slate-400 truncate">
                      {c.unternehmen || '—'} {c.rolle ? `· ${c.rolle}` : ''}
                    </div>
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300 shrink-0">
                    {c.status || 'aktiv'}
                  </span>
                </div>
              ))}
              {contacts.length === 0 && (
                <p className="text-xs text-slate-400 py-6 text-center">Keine CRM-Kontakte verfuegbar.</p>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
