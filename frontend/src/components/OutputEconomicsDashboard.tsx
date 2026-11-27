'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { Activity, BarChart3, Database, Layers, RefreshCw } from 'lucide-react';
import { archonFetch } from '@/lib/archon-api';

type GroupBy = 'project' | 'agent_profile' | 'period' | 'output_type';
type Period = 'day' | 'week' | 'month';

interface EconomicsSummary {
  task_count: number;
  tokens: number;
  estimated_cost_eur: number;
  actual_cost_eur: number;
  cost_delta_eur: number;
  deliverable_count: number;
  general_count: number;
  models: string[];
}

interface EconomicsGroup {
  key?: string;
  project?: string;
  agent_profile?: string;
  period?: string;
  output_type?: string;
  task_count: number;
  tokens: number;
  estimated_cost_eur: number;
  actual_cost_eur: number;
  cost_delta_eur: number;
  models: string[];
}

interface TimeSeriesPoint {
  output_type: string;
  period: string;
  task_count: number;
  tokens: number;
  estimated_cost_eur: number;
  actual_cost_eur: number;
  cost_delta_eur: number;
}

interface EconomicsResponse {
  status: string;
  summary: EconomicsSummary;
  groups: EconomicsGroup[];
  time_series: TimeSeriesPoint[];
  meta: {
    group_by: string;
    period: string;
    filters: Record<string, string | null>;
    task_count_scanned: number;
    sources: { memory_db_path: string; tables: Record<string, boolean>; kanban_meta_tasks: number };
    warnings: string[];
  };
}

const GROUP_LABELS: Record<GroupBy, string> = {
  project: 'Projekt',
  agent_profile: 'Agenten-Profil',
  period: 'Zeitraum',
  output_type: 'Output-Typ',
};

function formatEur(value: number): string {
  return `${value.toFixed(4)} EUR`;
}

function deltaClass(value: number): string {
  if (value > 0) return 'text-rose-300';
  if (value < 0) return 'text-emerald-300';
  return 'text-slate-300';
}

/** M100: schlanke KPI-Ansicht der Output-Wirtschaftlichkeit (rein lesend). */
export function OutputEconomicsDashboard() {
  const [groupBy, setGroupBy] = useState<GroupBy>('project');
  const [period, setPeriod] = useState<Period>('day');
  const [project, setProject] = useState('');
  const [agent, setAgent] = useState('');
  const [outputType, setOutputType] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [data, setData] = useState<EconomicsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({ group_by: groupBy, period });
    if (project.trim()) params.set('project', project.trim());
    if (agent.trim()) params.set('agent', agent.trim());
    if (outputType.trim()) params.set('output_type', outputType.trim());
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    try {
      const res = await archonFetch<EconomicsResponse>(
        `api/operations/kpi/output-economics?${params.toString()}`
      );
      setData(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'KPI-Daten konnten nicht geladen werden');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [groupBy, period, project, agent, outputType, dateFrom, dateTo]);

  useEffect(() => {
    void load();
  }, [load]);

  const summary = data?.summary;
  const groups = data?.groups ?? [];
  const series = data?.time_series ?? [];
  const maxTokens = Math.max(1, ...groups.map((g) => g.tokens));
  const maxActual = Math.max(0.0001, ...series.map((p) => p.actual_cost_eur));
  const pointsByType = series.reduce<Record<string, TimeSeriesPoint[]>>((acc, point) => {
    (acc[point.output_type] ||= []).push(point);
    return acc;
  }, {});
  const groupLabel = GROUP_LABELS[groupBy];

  return (
    <section className="space-y-4">
      <div className="p-3.5 rounded-xl border border-slate-800 bg-slate-900/70 flex flex-wrap items-center gap-2">
        <BarChart3 className="w-4 h-4 text-sky-400" />
        <span className="text-xs font-semibold mr-2">Output-Wirtschaftlichkeit (M100)</span>
        <select
          value={groupBy}
          onChange={(e) => setGroupBy(e.target.value as GroupBy)}
          className="px-2 py-1 rounded bg-slate-950 border border-slate-700 text-xs"
          aria-label="Gruppierung"
        >
          {(Object.keys(GROUP_LABELS) as GroupBy[]).map((key) => (
            <option key={key} value={key}>{GROUP_LABELS[key]}</option>
          ))}
        </select>
        <select
          value={period}
          onChange={(e) => setPeriod(e.target.value as Period)}
          className="px-2 py-1 rounded bg-slate-950 border border-slate-700 text-xs"
          aria-label="Zeitraum"
        >
          <option value="day">Tag</option>
          <option value="week">Woche</option>
          <option value="month">Monat</option>
        </select>
        <input
          value={project}
          onChange={(e) => setProject(e.target.value)}
          placeholder="Projekt"
          className="px-2 py-1 rounded bg-slate-950 border border-slate-700 text-xs w-28"
          aria-label="Projekt"
        />
        <input
          value={agent}
          onChange={(e) => setAgent(e.target.value)}
          placeholder="Agent"
          className="px-2 py-1 rounded bg-slate-950 border border-slate-700 text-xs w-28"
          aria-label="Agent"
        />
        <input
          value={outputType}
          onChange={(e) => setOutputType(e.target.value)}
          placeholder="Output-Typ"
          className="px-2 py-1 rounded bg-slate-950 border border-slate-700 text-xs w-28"
          aria-label="Output-Typ"
        />
        <input
          type="date"
          value={dateFrom}
          onChange={(e) => setDateFrom(e.target.value)}
          className="px-2 py-1 rounded bg-slate-950 border border-slate-700 text-xs"
          aria-label="Von"
        />
        <input
          type="date"
          value={dateTo}
          onChange={(e) => setDateTo(e.target.value)}
          className="px-2 py-1 rounded bg-slate-950 border border-slate-700 text-xs"
          aria-label="Bis"
        />
        <button
          onClick={() => void load()}
          disabled={loading}
          className="px-2.5 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold flex items-center gap-1.5 ml-auto"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          Neu laden
        </button>
      </div>

      {error && (
        <div className="p-3 rounded-lg border border-rose-500/40 bg-rose-500/10 text-rose-200 text-xs">
          {error}
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="p-3.5 rounded-xl border border-slate-800 bg-slate-900/70">
          <div className="text-[11px] font-mono uppercase text-slate-400 flex items-center gap-1">
            <Activity className="w-3.5 h-3.5 text-emerald-400" /> Tasks (done)
          </div>
          <div className="text-lg font-bold mt-1">{summary?.task_count ?? 0}</div>
          <div className="text-[10px] text-slate-400 mt-0.5">
            {summary?.deliverable_count ?? 0} mit Deliverable · {summary?.general_count ?? 0} General
          </div>
        </div>
        <div className="p-3.5 rounded-xl border border-slate-800 bg-slate-900/70">
          <div className="text-[11px] font-mono uppercase text-slate-400 flex items-center gap-1">
            <Layers className="w-3.5 h-3.5 text-sky-400" /> Tokens
          </div>
          <div className="text-lg font-bold mt-1">{(summary?.tokens ?? 0).toLocaleString('de-DE')}</div>
        </div>
        <div className="p-3.5 rounded-xl border border-slate-800 bg-slate-900/70">
          <div className="text-[11px] font-mono uppercase text-slate-400 flex items-center gap-1">
            <Database className="w-3.5 h-3.5 text-indigo-400" /> Geschätzt
          </div>
          <div className="text-lg font-bold mt-1">{formatEur(summary?.estimated_cost_eur ?? 0)}</div>
        </div>
        <div className="p-3.5 rounded-xl border border-slate-800 bg-slate-900/70">
          <div className="text-[11px] font-mono uppercase text-slate-400 flex items-center gap-1">
            <Activity className="w-3.5 h-3.5 text-amber-400" /> Tatsächlich / Delta
          </div>
          <div className="text-lg font-bold mt-1">{formatEur(summary?.actual_cost_eur ?? 0)}</div>
          <div className={`text-[11px] font-mono mt-0.5 ${deltaClass(summary?.cost_delta_eur ?? 0)}`}>
            Delta {formatEur(summary?.cost_delta_eur ?? 0)}
          </div>
        </div>
      </div>

      <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/70 space-y-3">
        <h2 className="text-sm font-bold">Rollup nach {groupLabel}</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="text-left text-[11px] font-mono uppercase text-slate-400 border-b border-slate-800">
                <th className="py-1.5 pr-3">{groupLabel}</th>
                <th className="py-1.5 pr-3 text-right">Tasks</th>
                <th className="py-1.5 pr-3 text-right">Tokens</th>
                <th className="py-1.5 pr-3 text-right">Est. EUR</th>
                <th className="py-1.5 pr-3 text-right">Actual EUR</th>
                <th className="py-1.5 text-right">Delta</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((group, idx) => {
                const key = group.key ?? group.project ?? group.agent_profile ?? group.period ?? group.output_type ?? idx;
                return (
                  <tr key={String(key)} className="border-b border-slate-800/60 align-middle">
                    <td className="py-2 pr-3">
                      <div className="font-semibold">{String(key)}</div>
                      <div className="h-1 mt-1 rounded bg-slate-800 w-full max-w-[160px]">
                        <div
                          className="h-1 rounded bg-sky-500"
                          style={{ width: `${Math.max(2, (group.tokens / maxTokens) * 100)}%` }}
                        />
                      </div>
                    </td>
                    <td className="py-2 pr-3 text-right">{group.task_count}</td>
                    <td className="py-2 pr-3 text-right font-mono">{group.tokens.toLocaleString('de-DE')}</td>
                    <td className="py-2 pr-3 text-right font-mono">{group.estimated_cost_eur.toFixed(4)}</td>
                    <td className="py-2 pr-3 text-right font-mono">{group.actual_cost_eur.toFixed(4)}</td>
                    <td className={`py-2 text-right font-mono ${deltaClass(group.cost_delta_eur)}`}>
                      {group.cost_delta_eur.toFixed(4)}
                    </td>
                  </tr>
                );
              })}
              {groups.length === 0 && (
                <tr>
                  <td colSpan={6} className="py-6 text-center text-slate-400">
                    Keine abgeschlossenen Tasks mit den gewaehlten Filtern.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/70 space-y-3">
        <h2 className="text-sm font-bold">Zeitreihe je Output-Typ</h2>
        <p className="text-[11px] text-slate-400">
          Balken zeigen tatsächliche Kosten je Periode. Eine Nutzenbewertung erfolgt bewusst manuell.
        </p>
        {Object.keys(pointsByType).length === 0 && (
          <p className="text-xs text-slate-400 py-4 text-center">Keine Zeitreihe vorhanden.</p>
        )}
        {Object.entries(pointsByType).map(([type, points]) => (
          <div key={type} className="space-y-1.5">
            <div className="text-[11px] font-mono uppercase text-slate-300">{type}</div>
            {points.map((point) => (
              <div key={`${type}-${point.period}`} className="flex items-center gap-2 text-[11px]">
                <span className="w-24 shrink-0 font-mono text-slate-400">{point.period}</span>
                <div className="h-2 flex-1 rounded bg-slate-800">
                  <div
                    className="h-2 rounded bg-emerald-500/80"
                    style={{ width: `${Math.max(2, (point.actual_cost_eur / maxActual) * 100)}%` }}
                  />
                </div>
                <span className="w-20 text-right font-mono">{formatEur(point.actual_cost_eur)}</span>
                <span className={`w-20 text-right font-mono ${deltaClass(point.cost_delta_eur)}`}>
                  {point.cost_delta_eur.toFixed(4)}
                </span>
              </div>
            ))}
          </div>
        ))}
      </div>

      {data && data.meta.warnings.length > 0 && (
        <div className="p-3 rounded-lg border border-amber-500/30 bg-amber-500/5 text-amber-200 text-[11px] space-y-1">
          {data.meta.warnings.map((warning, idx) => (
            <div key={idx}>{warning}</div>
          ))}
        </div>
      )}
    </section>
  );
}
