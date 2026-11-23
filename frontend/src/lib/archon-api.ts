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

export async function archonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const cleanPath = path.replace(/^\/+/, '');
  const res = await fetch(`/api/archon/${cleanPath}`, {
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
    ...init,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || data.error || `HTTP ${res.status}`);
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
  listWorkflowTemplates: () =>
    archonFetch<{ status: string; templates: WorkflowTemplate[] }>('api/v2/workflows/templates'),
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
  listDagRuns: () => archonFetch<{ status: string; runs: WorkflowRunSummary[] }>('api/v2/workflows/dag/runs'),
  getDagRun: (runId: string) =>
    archonFetch<{ status: string; run: WorkflowRunDetail }>(`api/v2/workflows/dag/runs/${encodeURIComponent(runId)}`),
  resumeDagRun: (runId: string, gateApprovals: Record<string, boolean>) =>
    archonFetch<{ status: string; run_id: string }>(`api/v2/workflows/dag/runs/${encodeURIComponent(runId)}/resume`, {
      method: 'POST',
      body: JSON.stringify({ gate_approvals: gateApprovals }),
    }),

  // DB Consolidation (28 -> 3)
  getDbConsolidationPlan: () =>
    archonFetch<DbConsolidationPlan>('api/v2/system/db-consolidation/plan'),
  runDbConsolidation: (opts: { dry_run: boolean; activate?: boolean; create_backup?: boolean }) =>
    archonFetch<Record<string, unknown>>('api/v2/system/db-consolidation/run', {
      method: 'POST',
      body: JSON.stringify(opts),
    }),
};
