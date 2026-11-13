const postgres = require('/app/node_modules/.pnpm/postgres@3.4.9/node_modules/postgres');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const PGPORT = process.env.PAPERCLIP_PG_PORT || process.env.PGPORT || '54329';
const sql = postgres(`postgresql://paperclip:paperclip@127.0.0.1:${PGPORT}/paperclip`);

async function getCompanyId() {
  const companies = await sql`SELECT id, name FROM companies LIMIT 1`;
  if (!companies || companies.length === 0) {
    throw new Error('No company found in Paperclip');
  }
  return companies[0].id;
}

async function hireAgent(agentPayload) {
  try {
    const companyId = await getCompanyId();

    const profileId = agentPayload.id || '';
    const agentUuid = crypto.randomUUID();
    const name = agentPayload.person_name || agentPayload.name || 'Agent';
    const role = (agentPayload.role || agentPayload.name || 'Specialist').toLowerCase().replace(/[^a-z0-9_]/g, '_');
    const title = agentPayload.name || agentPayload.role || 'Agent';
    const description = agentPayload.description || '';
    const soulPrompt = agentPayload.prompt || '';
    const rawSkills = Array.isArray(agentPayload.skills) ? agentPayload.skills.join(', ') : '';
    const rawTools = Array.isArray(agentPayload.tools) ? agentPayload.tools.join(', ') : '';

    // Check existing
    const existing = await sql`SELECT id FROM agents WHERE company_id = ${companyId} AND (name = ${name} OR title = ${title} OR (adapter_config->>'hermesProfileId') = ${profileId})`;
    const targetAgentId = existing && existing.length > 0 ? existing[0].id : agentUuid;

    // Instructions folder path inside Paperclip
    const agentInstructionsDir = `/paperclip/instances/default/companies/${companyId}/agents/${targetAgentId}/instructions`;
    fs.mkdirSync(agentInstructionsDir, { recursive: true });

    // Write instructions files: AGENTS.md, SOUL.md, HEARTBEAT.md, TOOLS.md
    const agentsMdContent = `# Role: ${name}\n\n**Titel:** ${title}\n**Hermes Profile ID:** \`${profileId}\`\n\n# System-Identität & Aufgaben\n${description}\n\n# Verknüpfte Skills\n${rawSkills}\n`;
    const soulMdContent = soulPrompt ? soulPrompt : `# SOUL.md -- ${title}\n\nYou are ${name}, ${title}.\n`;
    const heartbeatMdContent = `# HEARTBEAT.md\n\n- GET /api/agents/me\n- Prüfe zugewiesene Issues in Paperclip\n- Führe Aufgaben über Hermes Gateway aus und aktualisiere den Status.\n`;
    const toolsMdContent = `# Tools\n\nVerfügbare Tools: ${rawTools}\nVerknüpft mit Hermes Multi-Profile Gateway (\`${profileId}\`).\n`;

    fs.writeFileSync(path.join(agentInstructionsDir, 'AGENTS.md'), agentsMdContent, 'utf-8');
    fs.writeFileSync(path.join(agentInstructionsDir, 'SOUL.md'), soulMdContent, 'utf-8');
    fs.writeFileSync(path.join(agentInstructionsDir, 'HEARTBEAT.md'), heartbeatMdContent, 'utf-8');
    fs.writeFileSync(path.join(agentInstructionsDir, 'TOOLS.md'), toolsMdContent, 'utf-8');

    const adapterConfig = {
      apiBaseUrl: "http://hermes-agent:8642",
      apiKey: "5580d778a1a194c3db1202e5977e5f4749f5ea285d96506f5a107d877007d15f",
      paperclipApiUrl: "http://paperclip-orchestrator:3100",
      hermesProfileId: profileId,
      profile: profileId,
      env: {
        HERMES_HOME: `/opt/data/profiles/${profileId}`,
        HERMES_PROFILE: profileId
      },
      sessionKeyStrategy: "issue",
      timeoutSec: 300,
      dangerouslyAllowInsecureRemoteHttp: true,
      instructionsFilePath: path.join(agentInstructionsDir, 'AGENTS.md'),
      instructionsRootPath: agentInstructionsDir,
      instructionsEntryFile: 'AGENTS.md',
      instructionsBundleMode: 'managed'
    };

    const runtimeConfig = {
      heartbeat: {
        enabled: true,
        intervalSec: 300,
        cooldownSec: 10,
        wakeOnDemand: true,
        maxConcurrentRuns: 5,
        skipTimerWhenNoActionableWork: true
      }
    };

    const permissions = {
      canCreateAgents: true,
      canCreateSkills: true
    };

    if (existing && existing.length > 0) {
      await sql`
        UPDATE agents SET
          role = ${role},
          title = ${title},
          status = 'idle',
          capabilities = ${description},
          adapter_type = 'hermes_gateway',
          adapter_config = ${sql.json(adapterConfig)},
          runtime_config = ${sql.json(runtimeConfig)},
          permissions = ${sql.json(permissions)},
          error_reason = null,
          updated_at = NOW()
        WHERE id = ${targetAgentId}
      `;
      console.log(JSON.stringify({ status: 'updated', agentId: targetAgentId, name, title, profileId }));
    } else {
      await sql`
        INSERT INTO agents (
          id,
          company_id,
          name,
          role,
          title,
          status,
          capabilities,
          adapter_type,
          adapter_config,
          runtime_config,
          permissions,
          budget_monthly_cents,
          spent_monthly_cents,
          created_at,
          updated_at
        ) VALUES (
          ${targetAgentId},
          ${companyId},
          ${name},
          ${role},
          ${title},
          'idle',
          ${description},
          'hermes_gateway',
          ${sql.json(adapterConfig)},
          ${sql.json(runtimeConfig)},
          ${sql.json(permissions)},
          0,
          0,
          NOW(),
          NOW()
        )
      `;
      console.log(JSON.stringify({ status: 'hired', agentId: targetAgentId, name, title, profileId }));
    }
  } catch (err) {
    console.error(JSON.stringify({ error: err.message }));
    process.exit(1);
  } finally {
    await sql.end();
    process.exit(0);
  }
}

async function fireAgent(agentPayload) {
  try {
    const companyId = await getCompanyId();
    const profileId = agentPayload.id || '';
    const name = agentPayload.person_name || agentPayload.name || '';
    const title = agentPayload.name || '';

    // Find agent by profileId or name
    const existing = await sql`
      SELECT id, name FROM agents 
      WHERE company_id = ${companyId} 
        AND ((adapter_config->>'hermesProfileId') = ${profileId} OR (adapter_config->>'profile') = ${profileId} OR name = ${name} OR title = ${title})
    `;

    if (!existing || existing.length === 0) {
      console.log(JSON.stringify({ status: 'not_found', profileId }));
      return;
    }

    for (const agent of existing) {
      // Remove instructions folder if present
      const agentDir = `/paperclip/instances/default/companies/${companyId}/agents/${agent.id}`;
      try {
        if (fs.existsSync(agentDir)) {
          fs.rmSync(agentDir, { recursive: true, force: true });
        }
      } catch (e) {}

      // Delete from dependent tables first (foreign key cascades)
      try { await sql`DELETE FROM agent_runtime_state WHERE agent_id = ${agent.id}`; } catch (e) {}
      try { await sql`DELETE FROM agent_wake_events WHERE agent_id = ${agent.id}`; } catch (e) {}
      try { await sql`DELETE FROM agent_wakeup_requests WHERE agent_id = ${agent.id}`; } catch (e) {}
      try { await sql`DELETE FROM agent_api_keys WHERE agent_id = ${agent.id}`; } catch (e) {}
      try { await sql`DELETE FROM agent_tasks WHERE agent_id = ${agent.id}`; } catch (e) {}
      try { await sql`DELETE FROM heartbeat_runs WHERE agent_id = ${agent.id}`; } catch (e) {}
      try { await sql`DELETE FROM activity_log WHERE agent_id = ${agent.id}`; } catch (e) {}
      try { await sql`UPDATE issues SET assignee_id = NULL WHERE assignee_id = ${agent.id}`; } catch (e) {}

      // Delete from database
      await sql`DELETE FROM agents WHERE id = ${agent.id}`;
    }

    console.log(JSON.stringify({ status: 'fired', profileId, count: existing.length }));
  } catch (err) {
    console.error(JSON.stringify({ error: err.message }));
    process.exit(1);
  } finally {
    await sql.end();
    process.exit(0);
  }
}

async function listTasks() {
  try {
    const issues = await sql`
      SELECT i.id, i.identifier, i.title, i.description, i.status, i.created_at, i.updated_at,
             a.name as agent_name, (a.adapter_config->>'hermesProfileId') as agent_id
      FROM issues i
      LEFT JOIN agents a ON i.assignee_agent_id = a.id
      ORDER BY i.updated_at DESC
      LIMIT 50
    `;
    console.log(JSON.stringify({ status: 'success', issues }));
  } catch (err) {
    console.error(JSON.stringify({ error: err.message }));
    process.exit(1);
  } finally {
    await sql.end();
    process.exit(0);
  }
}

async function listAgents() {
  try {
    const agents = await sql`
      SELECT id, name, role, title, status, adapter_type, adapter_config->>'hermesProfileId' as profile_id, adapter_config->>'profile' as legacy_profile
      FROM agents
    `;
    console.log(JSON.stringify({ status: 'success', agents }));
  } catch (err) {
    console.error(JSON.stringify({ error: err.message }));
    process.exit(1);
  } finally {
    await sql.end();
    process.exit(0);
  }
}

async function createTask(taskPayload) {
  try {
    const companyId = await getCompanyId();
    const title = taskPayload.title || 'Neuer Task';
    const description = taskPayload.description || taskPayload.prompt || '';
    const agentProfileId = taskPayload.agent_id || '';

    // Finde passenden Agenten oder nimm den ersten verfügbaren
    let agentId = null;
    if (agentProfileId) {
      const matched = await sql`
        SELECT id FROM agents 
        WHERE company_id = ${companyId} 
          AND ((adapter_config->>'hermesProfileId') = ${agentProfileId} OR (adapter_config->>'profile') = ${agentProfileId} OR name = ${agentProfileId})
        LIMIT 1
      `;
      if (matched && matched.length > 0) {
        agentId = matched[0].id;
      }
    }
    if (!agentId) {
      const anyAgent = await sql`SELECT id FROM agents WHERE company_id = ${companyId} LIMIT 1`;
      if (anyAgent && anyAgent.length > 0) {
        agentId = anyAgent[0].id;
      }
    }

    const maxNum = await sql`SELECT COALESCE(MAX(issue_number), 0) + 1 as next_num FROM issues WHERE company_id = ${companyId}`;
    const issueNum = maxNum[0].next_num;
    const identifier = `ISSUE-${issueNum}`;

    const created = await sql`
      INSERT INTO issues (
        company_id,
        title,
        description,
        status,
        priority,
        assignee_agent_id,
        created_by_agent_id,
        issue_number,
        identifier,
        created_at,
        updated_at
      ) VALUES (
        ${companyId},
        ${title},
        ${description},
        'todo',
        'medium',
        ${agentId},
        ${agentId},
        ${issueNum},
        ${identifier},
        NOW(),
        NOW()
      )
      RETURNING id, title, identifier, status, assignee_agent_id;
    `;

    console.log(JSON.stringify({ status: 'created', issue: created[0] }));
  } catch (err) {
    console.error(JSON.stringify({ error: err.message }));
    process.exit(1);
  } finally {
    await sql.end();
    process.exit(0);
  }
}

const action = process.argv[2];
let payloadStr = process.argv[3] || '';

// If payloadStr starts with @file:, read from file, or if empty/stdin, read stdin
if (payloadStr.startsWith('@file:')) {
  try {
    const filePath = payloadStr.slice(6);
    payloadStr = fs.readFileSync(filePath, 'utf-8');
    try { fs.unlinkSync(filePath); } catch (e) {}
  } catch (e) {
    payloadStr = '{}';
  }
} else if (!payloadStr && !process.stdin.isTTY) {
  try {
    payloadStr = fs.readFileSync(0, 'utf-8');
  } catch (e) {
    payloadStr = '{}';
  }
}

let payload = {};
try { payload = JSON.parse(payloadStr || '{}'); } catch (e) {}

if (action === 'fire' || action === 'remove') {
  fireAgent(payload);
} else if (action === 'list') {
  listAgents();
} else if (action === 'list_tasks' || action === 'tasks') {
  listTasks();
} else if (action === 'create_task' || action === 'create-task' || action === 'issue') {
  createTask(payload);
} else if (action === 'hire' || action === 'add') {
  hireAgent(payload);
} else {
  // default backward compatibility: hire
  hireAgent(payload);
}
