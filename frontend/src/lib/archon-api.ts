/**
 * Direkter Archon FastAPI Client fuer Next.js 16 (ohne PocketBase-Abhaengigkeit).
 * Routet ueber den Same-Origin-Proxy `/api/archon/*` direkt an Archon OS (Port 8501).
 */

export interface WorkflowTemplate {
  id: string;
  title: string;
  description?: string;
  category?: string;
  nodes: Array<{ id: string; title?: string; type?: string; agent_id?: string; depends_on?: string[] }>;
}

export interface WorkflowRunSummary {
  run_id: string;
  workflow_id: string;
  status: string;
  created_at: number;
  updated_at: number;
}

export interface WorkflowRunDetail extends WorkflowRunSummary {
  nodes: Record<
    string,
    {
      status: string;
      fingerprint: string;
      output: Record<string, unknown>;
      updated_at: number;
    }
  >;
}

export interface DbConsolidationPlan {
  consolidated_active: boolean;
  target_dir: string;
  legacy_files_found: number;
  legacy_files_with_tables: number;
  target_domains: string[];
  domains: Record<
    string,
    {
      target_path: string;
      source_files: string[];
      total_rows: number;
      collisions_resolved: Array<Record<string, string>>;
      table_mappings: Array<{
        source_file: string;
        source_table: string;
        target_table: string;
        row_count: number;
      }>;
    }
  >;
}

const ZERO_TRACE_ID = /^0{32}$/;
const ZERO_SPAN_ID = /^0{16}$/;

function randomHex(byteLength: number): string {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

/**
 * D16 / R-B6: W3C-Root-Kontext im Browser erzeugen.
 * 128-Bit trace_id + 64-Bit span_id via crypto.getRandomValues, lowercase Hex,
 * niemals die Null-ID. Format: 00-<32hex>-<16hex>-01 (sampled).
 */
export function createTraceparent(): string {
  let traceId = randomHex(16);
  while (ZERO_TRACE_ID.test(traceId)) traceId = randomHex(16);
  let spanId = randomHex(8);
  while (ZERO_SPAN_ID.test(spanId)) spanId = randomHex(8);
  return `00-${traceId}-${spanId}-01`;
}

let activeTracestate: string | null = null;

/** Tracestate aus einer Antwort uebernehmen, damit Folge-Requests sie fortfuehren. */
export function setArchonTracestate(value: string | null | undefined): void {
  const raw = (value || '').trim();
  activeTracestate = raw || null;
}

export function getArchonTracestate(): string | null {
  return activeTracestate;
}

/**
 * Zentraler Fetch-Wrapper: injiziert traceparent (+ tracestate, falls vorhanden),
 * ohne bereits gesetzte Header zu ueberschreiben. Ein vom Aufrufer mitgegebener
 * traceparent gewinnt immer (existierender Kontext darf nicht gekappt werden).
 */
export function withTraceHeaders(init?: RequestInit): RequestInit {
  const headers = new Headers(init?.headers);
  if (!headers.has('traceparent')) headers.set('traceparent', createTraceparent());
  const tracestate = getArchonTracestate();
  if (tracestate && !headers.has('tracestate')) headers.set('tracestate', tracestate);
  return { ...init, headers };
}

/** D08/S-8.5: lifecycle-gebundene Requests koennen ein AbortSignal durchreichen. */
function withSignal(init: RequestInit | undefined, signal?: AbortSignal): RequestInit | undefined {
  if (!signal) return init;
  return { ...(init || {}), signal };
}

/**
 * D16/R-B6: zentraler Fetch-Wrapper fuer ALLE Browser-Requests (auch die,
 * die nicht ueber `archonFetch` laufen). Injiziert traceparent/tracestate,
 * ohne vom Aufrufer gesetzte Header zu ueberschreiben.
 */
export async function tracedFetch(url: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(url, withTraceHeaders(init));
  // Der Proxy gibt den fortgefuehrten Kontext zurueck -> naechster Hop erbt ihn.
  setArchonTracestate(res.headers.get('tracestate'));
  return res;
}

export async function archonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const cleanPath = path.replace(/^\/+/, '');
  const headers = new Headers(init?.headers);
  if (!headers.has('content-type')) headers.set('content-type', 'application/json');
  const res = await tracedFetch(`/api/archon/${cleanPath}`, {
    ...init,
    credentials: init?.credentials || 'same-origin',
    headers,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || data.error || data.message || `HTTP ${res.status}`);
  }
  return data as T;
}

export const archonApi = {
  // Executive Cockpit & Operations (ohne PocketBase)
  getSystemHealth: () =>
    archonFetch<{
      status: string;
      services: Record<string, { status: string; latency_ms?: number }>;
    }>('api/system/health'),
  listKanbanTasks: (statusFilter?: string) =>
    archonFetch<{ tasks?: Array<Record<string, unknown>>; items?: Array<Record<string, unknown>> }>(
      `api/operations/kanban/tasks${statusFilter ? `?status=${encodeURIComponent(statusFilter)}` : ''}`
    ),
  moveKanbanTask: (taskId: string, status: string) =>
    archonFetch<Record<string, unknown>>(`api/operations/kanban/tasks/${encodeURIComponent(taskId)}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    }),
  decideHitl: (decisionId: string, decision: 'approve' | 'reject', note = '') =>
    archonFetch<Record<string, unknown>>('api/decisions/decide', {
      method: 'POST',
      // Der Endpoint erwartet task_id (nicht decision_id) — sonst 400.
      body: JSON.stringify({ task_id: decisionId, decision, note }),
    }),
  listCrmContacts: (limit = 25) =>
    archonFetch<{ contacts?: Array<Record<string, unknown>>; items?: Array<Record<string, unknown>> }>(
      `api/crm/contacts?limit=${limit}`
    ),

  // Workflow & DAG Engine
  listWorkflowTemplates: (signal?: AbortSignal) =>
    archonFetch<{ status: string; templates: WorkflowTemplate[] }>(
      'api/v2/workflows/templates', withSignal(undefined, signal)
    ),
  runWorkflowTemplate: (tplId: string, inputs: Record<string, string> = {}) =>
    archonFetch<{ status: string; run_id: string }>(`api/v2/workflows/templates/${encodeURIComponent(tplId)}/run`, {
      method: 'POST',
      body: JSON.stringify({ inputs }),
    }),
  saveWorkflowTemplate: (template: Record<string, unknown>) =>
    archonFetch<{ status: string; id?: string; template?: WorkflowTemplate }>('api/v2/workflows/templates', {
      method: 'POST',
      body: JSON.stringify(template),
    }),
  listDagRuns: (signal?: AbortSignal) =>
    archonFetch<{ status: string; runs: WorkflowRunSummary[] }>(
      'api/v2/workflows/dag/runs', withSignal(undefined, signal)
    ),
  getDagRun: (runId: string, signal?: AbortSignal) =>
    archonFetch<{ status: string; run: WorkflowRunDetail }>(
      `api/v2/workflows/dag/runs/${encodeURIComponent(runId)}`, withSignal(undefined, signal)
    ),
  resumeDagRun: (runId: string, gateApprovals: Record<string, boolean>) =>
    archonFetch<{ status: string; run_id: string }>(`api/v2/workflows/dag/runs/${encodeURIComponent(runId)}/resume`, {
      method: 'POST',
      body: JSON.stringify({ gate_approvals: gateApprovals }),
    }),

  // DB Consolidation (28 -> 3)
  getDbConsolidationPlan: (signal?: AbortSignal) =>
    archonFetch<DbConsolidationPlan>(
      'api/v2/system/db-consolidation/plan', withSignal(undefined, signal)
    ),
  runDbConsolidation: (opts: { dry_run: boolean; activate?: boolean; create_backup?: boolean }) =>
    archonFetch<Record<string, unknown>>('api/v2/system/db-consolidation/run', {
      method: 'POST',
      body: JSON.stringify(opts),
    }),
};
