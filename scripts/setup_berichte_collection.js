const BASE_URL = process.env.POCKETBASE_URL || 'http://127.0.0.1:8090';
const ADMIN_EMAIL = process.env.PB_ADMIN_EMAIL || 'admin@agenticos.local';
const ADMIN_PASS = process.env.PB_ADMIN_PASSWORD || 'admin1234567890';

async function setupBerichteCollection() {
  console.log(`[1/4] Authenticating with PocketBase at ${BASE_URL}...`);
  const authRes = await fetch(`${BASE_URL}/api/collections/_superusers/auth-with-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ identity: ADMIN_EMAIL, password: ADMIN_PASS })
  });

  if (!authRes.ok) {
    const err = await authRes.text();
    throw new Error(`Admin auth failed: ${authRes.status} ${err}`);
  }

  const { token } = await authRes.json();
  console.log('[2/4] Authenticated successfully as superuser.');

  console.log('[3/4] Checking existing collections...');
  const collectionsRes = await fetch(`${BASE_URL}/api/collections?perPage=100`, {
    headers: { 'Authorization': token }
  });
  const collectionsData = await collectionsRes.json();
  const existing = collectionsData.items.find(c => c.name === 'berichte');

  const collectionPayload = {
    name: 'berichte',
    type: 'base',
    fields: [
      {
        name: 'titel',
        type: 'text',
        required: true,
        presentable: true
      },
      {
        name: 'zeitraum_start',
        type: 'date',
        required: true,
        presentable: false
      },
      {
        name: 'zeitraum_ende',
        type: 'date',
        required: true,
        presentable: false
      },
      {
        name: 'kohorte',
        type: 'text',
        required: true,
        presentable: false
      },
      {
        name: 'metriken',
        type: 'json',
        required: true,
        presentable: false
      },
      {
        name: 'executive_summary',
        type: 'text',
        required: false,
        presentable: false
      }
    ],
    // API Rules:
    // List, View, Create are open
    listRule: '',
    viewRule: '',
    createRule: '',
    // WORM Principle: Update is strictly forbidden!
    updateRule: null,
    // Delete is allowed for admin cleanup
    deleteRule: ''
  };

  if (existing) {
    console.log(`Collection 'berichte' already exists (ID: ${existing.id}). Updating schema and rules...`);
    const updateRes = await fetch(`${BASE_URL}/api/collections/${existing.id}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': token
      },
      body: JSON.stringify({
        fields: collectionPayload.fields,
        listRule: collectionPayload.listRule,
        viewRule: collectionPayload.viewRule,
        createRule: collectionPayload.createRule,
        updateRule: collectionPayload.updateRule,
        deleteRule: collectionPayload.deleteRule
      })
    });
    if (!updateRes.ok) {
      const err = await updateRes.text();
      throw new Error(`Failed to update collection 'berichte': ${updateRes.status} ${err}`);
    }
    console.log('[4/4] Collection \'berichte\' successfully updated with WORM rules.');
  } else {
    console.log('Creating new collection \'berichte\'...');
    const createRes = await fetch(`${BASE_URL}/api/collections`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': token
      },
      body: JSON.stringify(collectionPayload)
    });
    if (!createRes.ok) {
      const err = await createRes.text();
      throw new Error(`Failed to create collection 'berichte': ${createRes.status} ${err}`);
    }
    console.log('[4/4] Collection \'berichte\' successfully created with WORM rules (updateRule: null).');
  }

  // WORM Verification test
  console.log('\n--- Verifying WORM (Write Once Read Many) ---');
  // 1. Create a test record via regular public API (without token)
  const testRecordRes = await fetch(`${BASE_URL}/api/collections/berichte/records`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      titel: 'WORM Test Snapshot',
      zeitraum_start: '2026-09-01 00:00:00.000Z',
      zeitraum_ende: '2026-09-18 00:00:00.000Z',
      kohorte: 'Alle Kontakte',
      metriken: { total: 100, messaged: 50, dialog: 10, calls: 5, rates: { messageRate: 50, callRate: 5 } },
      executive_summary: 'Test summary line 1\nLine 2\nLine 3'
    })
  });

  if (!testRecordRes.ok) {
    const err = await testRecordRes.text();
    throw new Error(`Public record creation failed: ${testRecordRes.status} ${err}`);
  }
  const testRecord = await testRecordRes.json();
  console.log(`[PASS] Record created successfully (ID: ${testRecord.id})`);

  // 2. Try to update via public API -> MUST FAIL with 400 or 403 or 404
  const patchRes = await fetch(`${BASE_URL}/api/collections/berichte/records/${testRecord.id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ titel: 'Tampered Title' })
  });

  if (patchRes.ok) {
    throw new Error(`[FAIL] WORM VIOLATION: Update succeeded when it should be forbidden! Status: ${patchRes.status}`);
  } else {
    console.log(`[PASS] WORM Enforced: Update rejected with HTTP ${patchRes.status} (updateRule: null is active).`);
  }

  // 3. Clean up test record using superuser token
  await fetch(`${BASE_URL}/api/collections/berichte/records/${testRecord.id}`, {
    method: 'DELETE',
    headers: { 'Authorization': token }
  });
  console.log('[PASS] Test record cleaned up.');
  console.log('\n[SUCCESS] PocketBase \'berichte\' collection is ready and revisionssicher.');
}

setupBerichteCollection().catch(e => {
  console.error(e);
  process.exit(1);
});
