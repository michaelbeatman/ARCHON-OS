'use client';

/**
 * M70/M74 — „Braucht mich“: einheitliches Panel für Missions-, Policy- und
 * MCP-HITL-Gates, Agentenrückfragen und unsichere Abbrüche.
 *
 * Die Ansicht ist bewusst READ-ONLY in Bezug auf Freigaben: es gibt hier
 * KEINE Freigabe-/Ablehnungsschaltfläche. Aktionen starten nur die
 * Auto-Review-Runde (Belege/Prüfsummen) oder prüfen das M95-Eskalationsziel.
 * Verdrahtung in ExecutiveCockpit.tsx erfolgt separat per Snippet.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { AlertCircle, CheckCircle2, Clock, RefreshCw, ShieldCheck, User } from 'lucide-react';
import { archonFetch } from '@/lib/archon-api';
import { useArchonEvents } from '@/lib/useArchonEvents';

export const NEEDS_ME_SSE_EVENT = 'needs_me_updated';

export interface NeedsMeEvidence {
  kind: string;
  reference: string;
  checksum: string;
  captured_at: string;
}

export interface NeedsMeEscalation {
  owner: string;
  resolved: boolean;
  target: string | null;
  status: string;
  reason: string;
}

export interface NeedsMeItem {
  id: string;
  kind: 'mission' | 'policy' | 'mcp_hitl' | 'agent_question' | 'unsafe_abort';
  title: string;
  domain: string;
  tenant_id: string;
  source: string;
  reference_id: string;
  status: string;
  requested_by: string;
  assigned_to: string;
  created_at: string;
  timeout_at: string;
  overdue: boolean;
  risk: 'low' | 'medium' | 'high';
  required_fields: string[];
  missing_fields: string[];
  decision_fields: string[];
  evidence_required: boolean;
  evidence: NeedsMeEvidence[];
  evidence_complete: boolean;
  escalation: NeedsMeEscalation;
  requires_four_eyes: boolean;
  needs_you: boolean;
  may_decide: boolean;
  blocking_reasons: string[];
  auto_approval: false;
}

export interface NeedsMeBundle {
  actor: string;
  tenant: string;
  actor_is_human: boolean;
  generated_at: string;
  items: NeedsMeItem[];
  counts: Record<string, number>;
  total: number;
  requires_action: number;
  timeout_policy_hours: number;
  invariants: Record<string, boolean>;
}

interface NeedsMePanelProps {
  tenant?: string;
  limit?: number;
}

const KIND_LABEL: Record<NeedsMeItem['kind'], string> = {
  mission: 'Mission',
  policy: 'Policy',
  mcp_hitl: 'MCP-HITL',
  agent_question: 'Rückfrage',
  unsafe_abort: 'Unsicherer Abbruch',
};

function asText(value: unknown): string {
  return typeof value === 'string' ? value : value == null ? '' : String(value);
}

function formatDeadline(value: string): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' });
}

export function NeedsMePanel({ tenant = 'default', limit = 20 }: NeedsMePanelProps) {
  const [bundle, setBundle] = useState<NeedsMeBundle | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await archonFetch<{ status: string; bundle: NeedsMeBundle }>(
        `api/needs-me?tenant=${encodeURIComponent(tenant)}`
      );
      setBundle(res.bundle ?? null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Bedienfeld nicht verfügbar');
    } finally {
      setLoading(false);
    }
  }, [tenant]);

  useEffect(() => {
    void load();
  }, [load]);

  // Einheitliches SSE-Event des Backends aktualisiert das Panel.
  useArchonEvents((event) => {
    if (event.type === NEEDS_ME_SSE_EVENT) void load();
  });

  const runAction = async (item: NeedsMeItem, action: 'review' | 'escalation') => {
    setBusyId(item.id);
    setError(null);
    try {
      if (action === 'review') {
        await archonFetch<{ status: string }>('api/needs-me/auto-review', {
          method: 'POST',
          body: JSON.stringify({
            request_id: item.reference_id || item.id,
            reference_id: item.reference_id,
            domain: item.domain,
            title: item.title,
            requester_id: item.requested_by,
            tenant_id: item.tenant_id || tenant,
            status: item.status,
            risk: item.risk,
            requires_four_eyes: item.requires_four_eyes,
            payload: {},
          }),
        });
      } else {
        await archonFetch<{ status: string }>(
          `api/needs-me/${encodeURIComponent(item.id)}/escalation-preview`,
          {
            method: 'POST',
            body: JSON.stringify({
              owner: item.assigned_to || 'admin',
              domain: item.domain,
              requester_id: item.requested_by,
            }),
          }
        );
      }
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Aktion fehlgeschlagen');
    } finally {
      setBusyId(null);
    }
  };

  const items = (bundle?.items ?? []).slice(0, limit);
  const actionable = items.filter((item) => item.needs_you && item.may_decide);

  return (
    <section
      aria-label="Braucht mich"
      className="rounded-xl border border-slate-800 bg-slate-900/60 p-4"
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-amber-400" aria-hidden="true" />
          <h2 className="text-sm font-bold text-slate-100">Braucht mich</h2>
          <span className="rounded-full border border-slate-700 px-2 py-0.5 text-[11px] text-slate-300">
            {bundle?.requires_action ?? 0} offen
          </span>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-md border border-slate-700 px-2.5 py-1.5 text-xs text-slate-200 transition hover:border-slate-500 disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />
          Aktualisieren
        </button>
      </div>

      <div className="mb-3 flex flex-wrap gap-2 text-[11px] text-slate-400">
        <span className="rounded-md bg-slate-800/70 px-2 py-1">Gesamt {bundle?.total ?? 0}</span>
        {Object.entries(bundle?.counts ?? {})
          .filter(([, count]) => count > 0)
          .map(([kind, count]) => (
            <span key={kind} className="rounded-md bg-slate-800/70 px-2 py-1">
              {KIND_LABEL[kind as NeedsMeItem['kind']] ?? kind}: {count}
            </span>
          ))}
      </div>

      {error ? (
        <p role="status" className="mb-3 flex items-center gap-2 text-xs text-rose-300">
          <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" /> {error}
        </p>
      ) : null}

      {loading && !bundle ? (
        <p className="text-xs text-slate-400">Lade offene Gates …</p>
      ) : items.length === 0 ? (
        <p className="flex items-center gap-2 text-xs text-emerald-300">
          <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" /> Keine offenen Gates.
        </p>
      ) : (
        <ul className="space-y-2">
          {items.map((item) => {
            const busy = busyId === item.id;
            return (
              <li
                key={item.id}
                className="rounded-lg border border-slate-800 bg-slate-950/50 p-3"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-100" title={item.title}>
                      {item.title}
                    </p>
                    <p className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
                      <span className="rounded border border-slate-700 px-1.5 py-0.5">
                        {KIND_LABEL[item.kind] ?? item.kind}
                      </span>
                      <span>{item.domain}</span>
                      {item.requires_four_eyes ? <span>4-Augen</span> : null}
                      {item.risk === 'high' ? (
                        <span className="text-amber-300">hohes Risiko</span>
                      ) : null}
                    </p>
                  </div>
                  <span
                    className={`inline-flex items-center gap-1 text-[11px] ${
                      item.overdue ? 'text-rose-300' : 'text-slate-400'
                    }`}
                  >
                    <Clock className="h-3 w-3" aria-hidden="true" />
                    {formatDeadline(item.timeout_at)}
                  </span>
                </div>

                {(item.blocking_reasons ?? []).length > 0 ? (
                  <ul className="mt-2 space-y-1 text-[11px] text-amber-200">
                    {item.blocking_reasons.map((reason) => (
                      <li key={reason}>• {reason}</li>
                    ))}
                  </ul>
                ) : null}

                <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-slate-400">
                  <span className="inline-flex items-center gap-1">
                    <User className="h-3 w-3" aria-hidden="true" />
                    {asText(item.assigned_to) || 'nicht zugewiesen'}
                  </span>
                  {item.escalation?.target ? (
                    <span>Vertretung: {asText(item.escalation.target)}</span>
                  ) : null}
                  {item.evidence_required ? (
                    <span className={item.evidence_complete ? 'text-emerald-300' : 'text-amber-300'}>
                      Belege {item.evidence.length}/{item.evidence_required ? 'pflicht' : ''}
                    </span>
                  ) : null}
                </div>

                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={busy || !item.reference_id}
                    onClick={() => void runAction(item, 'review')}
                    className="rounded-md border border-slate-700 px-2 py-1 text-[11px] text-slate-200 transition hover:border-slate-500 disabled:opacity-40"
                  >
                    Auto-Review starten
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void runAction(item, 'escalation')}
                    className="rounded-md border border-slate-700 px-2 py-1 text-[11px] text-slate-200 transition hover:border-slate-500 disabled:opacity-40"
                  >
                    Vertretung prüfen
                  </button>
                  {!item.may_decide ? (
                    <span className="self-center text-[11px] text-slate-500">
                      Keine Entscheidung möglich
                    </span>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <p className="mt-3 text-[11px] text-slate-500">
        Entscheidungen erfolgen ausschließlich über die dafür zuständigen Freigabe-Endpunkte – dieses
        Panel erteilt keine Freigaben. {actionable.length} Element(e) wären entscheidbar.
      </p>
    </section>
  );
}

export default NeedsMePanel;
