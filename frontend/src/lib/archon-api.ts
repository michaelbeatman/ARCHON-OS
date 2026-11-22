/**
 * Direkter Archon FastAPI Client fuer Next.js 16 (ohne PocketBase-Abhaengigkeit).
 * Routet ueber den Same-Origin-Proxy `/api/archon/*` direkt an Archon OS (Port 8420).
 */

export interface ChannelSpec {
  id: string;
  label: string;
  format: string;
  aspect_ratio: string;
  max_chars?: number;
  target_duration_sec?: number;
  recommended_agent: string;
  best_practices: string[];
}

export interface ContentCampaign {
  id: string;
  title: string;
  topic: string;
  target_audience: string;
  brand_voice: string;
  pillar: string;
  source_url: string;
  source_notes: string;
  channels: string[];
  status: string;
  workflow_run_id: string;
  created_at: string;
  updated_at: string;
}

export interface ContentAssetQualityReport {
  score: number;
  passed: boolean;
  slop_hits: string[];
  issues: string[];
  suggestions: string[];
}

export interface ContentAsset {
  id: string;
  campaign_id: string;
  channel: string;
  format_type: string;
  title: string;
  hook: string;
  body: string;
  visual_brief: string;
  hashtags: string[];
  cta: string;
  duration_sec: number;
  status: 'draft' | 'review' | 'approved' | 'scheduled' | 'published' | 'rejected';
  scheduled_at: string;
  published_at: string;
  external_url: string;
  decision_id: string;
  agent_id: string;
  quality_score?: number;
  quality_report?: ContentAssetQualityReport;
  created_at: string;
  updated_at: string;
}

export interface ContentOverview {
  channels: ChannelSpec[];
  campaigns: ContentCampaign[];
  assets: ContentAsset[];
  status_counts: Record<string, number>;
  analytics: {
    by_channel: Array<{ channel: string; assets: number; published: number; ready: number }>;
    metrics_by_channel: Array<{
      channel: string;
      views: number;
      likes: number;
      comments: number;
      shares: number;
      saves: number;
      avg_ctr: number;
      conversions: number;
    }>;
    top_assets: Array<{
      id: string;
      title: string;
      channel: string;
      hook: string;
      views: number;
      likes: number;
      shares: number;
      ctr_pct: number;
    }>;
  };
}

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

async function archonFetch<T>(path: string, init?: RequestInit): Promise<T> {
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
  // Content Machine v1
  getContentOverview: () => archonFetch<ContentOverview>('api/v2/content-machine/overview'),
  createCampaign: (payload: {
    title: string;
    topic: string;
    target_audience?: string;
    brand_voice?: string;
    pillar?: string;
    source_notes?: string;
    channels: string[];
  }) =>
    archonFetch<{ status: string; campaign: ContentCampaign }>('api/v2/content-machine/campaigns', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  deleteCampaign: (campaignId: string) =>
    archonFetch<{ status: string; deleted: string }>(`api/v2/content-machine/campaigns/${encodeURIComponent(campaignId)}`, {
      method: 'DELETE',
    }),
  generateCampaignAssets: (
    campaignId: string,
    opts?: { dry_run?: boolean; require_hitl_gate?: boolean; background?: boolean }
  ) =>
    archonFetch<{
      status: string;
      workflow_run_id?: string;
      dag_status?: string;
      assets_created?: ContentAsset[];
    }>(`api/v2/content-machine/campaigns/${encodeURIComponent(campaignId)}/generate`, {
      method: 'POST',
      body: JSON.stringify(opts || {}),
    }),
  updateAsset: (assetId: string, patch: Partial<ContentAsset>) =>
    archonFetch<{ status: string; asset: ContentAsset }>(`api/v2/content-machine/assets/${encodeURIComponent(assetId)}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  approveAsset: (assetId: string, scheduledAt = '') =>
    archonFetch<{ status: string; asset: ContentAsset }>(
      `api/v2/content-machine/assets/${encodeURIComponent(assetId)}/approve`,
      {
        method: 'POST',
        body: JSON.stringify({ scheduled_at: scheduledAt }),
      }
    ),
  publishAsset: (assetId: string, externalUrl = '') =>
    archonFetch<{ status: string; asset: ContentAsset }>(
      `api/v2/content-machine/assets/${encodeURIComponent(assetId)}/publish`,
      {
        method: 'POST',
        body: JSON.stringify({ external_url: externalUrl }),
      }
    ),
  recordAssetMetrics: (
    assetId: string,
    metrics: { views: number; likes: number; comments: number; shares: number; saves: number; ctr_pct: number }
  ) =>
    archonFetch<{ status: string; metrics: Record<string, unknown> }>(
      `api/v2/content-machine/assets/${encodeURIComponent(assetId)}/metrics`,
      {
        method: 'POST',
        body: JSON.stringify(metrics),
      }
    ),
  ingestSource: (payload: {
    source_type: 'url' | 'obsidian' | 'transcript';
    title?: string;
    source_url?: string;
    obsidian_path?: string;
    transcript?: string;
    channels?: string[];
  }) =>
    archonFetch<{ status: string; campaign: ContentCampaign; ingested_chars: number }>(
      'api/v2/content-machine/ingest',
      {
        method: 'POST',
        body: JSON.stringify(payload),
      }
    ),
  generateClipMatrix: (
    campaignId: string,
    opts?: { source_asset_id?: string; clip_count?: number; dry_run?: boolean }
  ) =>
    archonFetch<{ status: string; count: number; clips_created: ContentAsset[] }>(
      `api/v2/content-machine/campaigns/${encodeURIComponent(campaignId)}/clip-matrix`,
      {
        method: 'POST',
        body: JSON.stringify(opts || {}),
      }
    ),
  publishDueAssets: (opts?: { webhook_url?: string; dry_run?: boolean }) =>
    archonFetch<{ status: string; due_count: number; published?: string[] }>(
      'api/v2/content-machine/publish-due',
      {
        method: 'POST',
        body: JSON.stringify(opts || {}),
      }
    ),

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
