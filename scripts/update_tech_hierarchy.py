import json
import datetime

path = 'config/org_hierarchy.json'
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)

new_nodes = [
    {
        'id': 'qa_automation_lead',
        'x': 220,
        'y': 1300,
        'tier': 3,
        'team_id': 'team_tech',
        'name': 'QA & Test Automation Lead (Playwright/E2E)',
        'role': '7. Tech, Software & Data',
        'category': '7. Tech, Software & Data',
        'avatar': '/static/avatars/avatar_015.jpg',
        'model': 'omniroute/best-reasoning',
        'active_tasks': 0,
        'status': 'standby',
        'person_name': 'Elena Rostova',
        'provider': 'omniroute'
    },
    {
        'id': 'security_pentest_auditor',
        'x': 220,
        'y': 1460,
        'tier': 3,
        'team_id': 'team_tech',
        'name': 'AppSec & Penetration Testing Auditor',
        'role': '7. Tech, Software & Data',
        'category': '7. Tech, Software & Data',
        'avatar': '/static/avatars/avatar_042.jpg',
        'model': 'omniroute/best-reasoning',
        'active_tasks': 0,
        'status': 'standby',
        'person_name': 'Viktor Frank',
        'provider': 'omniroute'
    },
    {
        'id': 'frontend_design_system_engineer',
        'x': 220,
        'y': 1620,
        'tier': 3,
        'team_id': 'team_tech',
        'name': 'UI/UX & Frontend Design System Engineer',
        'role': '7. Tech, Software & Data',
        'category': '7. Tech, Software & Data',
        'avatar': '/static/avatars/avatar_055.jpg',
        'model': 'auto/best-free',
        'active_tasks': 0,
        'status': 'standby',
        'person_name': 'Maya Lin',
        'provider': 'omniroute'
    },
    {
        'id': 'api_contract_architect',
        'x': 220,
        'y': 1780,
        'tier': 3,
        'team_id': 'team_tech',
        'name': 'API & Integration Contract Architect',
        'role': '7. Tech, Software & Data',
        'category': '7. Tech, Software & Data',
        'avatar': '/static/avatars/avatar_068.jpg',
        'model': 'auto/best-free',
        'active_tasks': 0,
        'status': 'standby',
        'person_name': 'Julian Weimann',
        'provider': 'omniroute'
    },
    {
        'id': 'sre_observability_engineer',
        'x': 220,
        'y': 1940,
        'tier': 3,
        'team_id': 'team_tech',
        'name': 'SRE & Observability Systems Engineer',
        'role': '7. Tech, Software & Data',
        'category': '7. Tech, Software & Data',
        'avatar': '/static/avatars/avatar_080.jpg',
        'model': 'auto/best-free',
        'active_tasks': 0,
        'status': 'standby',
        'person_name': 'Timo Berner',
        'provider': 'omniroute'
    }
]

existing_ids = set(n['id'] for n in data['nodes'])
added_count = 0
for n in new_nodes:
    if n['id'] not in existing_ids:
        data['nodes'].append(n)
        added_count += 1
        data['links'].append({
            'from': 'system_architect_orchestrator',
            'to': n['id']
        })

data['updated_at'] = datetime.datetime.now().isoformat()

with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"Successfully added {added_count} nodes and links. Total nodes: {len(data['nodes'])}")
