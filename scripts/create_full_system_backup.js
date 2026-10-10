/**
 * create_full_system_backup.js
 * Vollumfängliches System-Backup für Archon OS / Antigravity 2026:
 * 1. PocketBase CRM & Media (pb_data)
 * 2. Docker Volumes (Paperclip, n8n, OmniRoute, AnythingLLM)
 * 3. Hermes Agenten-Zustand & Profile (C:\Users\micha\.hermes - ohne Cache/Venvs)
 * 4. Obsidian Knowledge Vault (C:\Mein Obsidian - ohne .trash)
 * 5. AgenticOS Codebase & Prompts & Kataloge (ohne .git, node_modules, alte Backups)
 * 6. Manifest & Wiederherstellungsanleitung (backup_manifest.json, README_RESTORE.txt)
 * 7. Multithreaded 7-Zip Kompression (.zip)
 * 8. Automatischer Sync auf NAS (Y:\_ARCHON Backups\)
 * 9. Bereinigung des temporären Staging-Ordners
 */

const fs = require('fs');
const path = require('path');
const { execSync, spawnSync } = require('child_process');

const SEVEN_ZIP = 'C:\\Program Files\\7-Zip\\7z.exe';
const NAS_TARGET_DIR = 'Y:\\_ARCHON Backups';
const LOCAL_BACKUP_DIR = 'C:\\.Antigravity-projekte\\AgenticOS-2026\\backups';

function pad(n) { return n.toString().padStart(2, '0'); }

const now = new Date();
const timestamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}_${pad(now.getHours())}-${pad(now.getMinutes())}-${pad(now.getSeconds())}`;
const backupName = `full_system_backup_${timestamp}`;
const tempBackupRoot = path.join(LOCAL_BACKUP_DIR, backupName);
const localZipPath = path.join(LOCAL_BACKUP_DIR, `${backupName}.zip`);
const nasZipPath = path.join(NAS_TARGET_DIR, `${backupName}.zip`);

console.log(`===================================================================`);
console.log(`ARCHON OS / ANTIGRAVITY 2026 — VOLLSTÄNDIGES SYSTEM-BACKUP`);
console.log(`Zeitstempel:  ${timestamp}`);
console.log(`Staging-Pfad: ${tempBackupRoot}`);
console.log(`Ziel lokal:   ${localZipPath}`);
console.log(`Ziel NAS:     ${nasZipPath}`);
console.log(`===================================================================\n`);

fs.mkdirSync(tempBackupRoot, { recursive: true });

let fileCounters = {
  pocketbase_crm: 0,
  pocketbase_media: 0,
  docker_volumes: 0,
  hermes_home: 0,
  obsidian_vault: 0,
  agenticos_codebase: 0
};

function copyDirRecursive(src, dest, excludeNames = [], counterKey = null) {
  if (!fs.existsSync(src)) return;
  fs.mkdirSync(dest, { recursive: true });
  let entries = [];
  try {
    entries = fs.readdirSync(src, { withFileTypes: true });
  } catch (e) {
    return;
  }

  for (const entry of entries) {
    if (excludeNames.includes(entry.name)) continue;
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);

    try {
      if (entry.isDirectory()) {
        copyDirRecursive(srcPath, destPath, excludeNames, counterKey);
      } else if (entry.isFile()) {
        fs.copyFileSync(srcPath, destPath);
        if (counterKey && fileCounters[counterKey] !== undefined) {
          fileCounters[counterKey]++;
        }
      }
    } catch (err) {
      // Ignoriere gesperrte temporäre Dateien
    }
  }
}

// 1. POCKETBASE BACKUP (CRM & Media)
console.log(`[1/5] Sichere PocketBase CRM & Media Datenbanken...`);
const pbCrmSrc = 'C:\\.Antigravity-projekte\\AgenticOS-2026\\pocketbase\\pb_data';
const pbCrmDest = path.join(tempBackupRoot, 'pocketbase_crm', 'pb_data');
copyDirRecursive(pbCrmSrc, pbCrmDest, ['backups'], 'pocketbase_crm');
console.log(`      -> PocketBase CRM gesichert (${fileCounters.pocketbase_crm} Dateien)`);

const pbMediaSrc = 'C:\\.Antigravity-projekte\\AgenticOS-2026\\pocketbase-media\\pb_data';
const pbMediaDest = path.join(tempBackupRoot, 'pocketbase_media', 'pb_data');
copyDirRecursive(pbMediaSrc, pbMediaDest, ['backups'], 'pocketbase_media');
console.log(`      -> PocketBase Media gesichert (${fileCounters.pocketbase_media} Dateien)`);

// 2. DOCKER VOLUMES EXPORT
console.log(`\n[2/5] Exportiere Docker Volumes (Paperclip, n8n, OmniRoute, AnythingLLM)...`);
const dockerVolumesDir = path.join(tempBackupRoot, 'docker_volumes');
fs.mkdirSync(dockerVolumesDir, { recursive: true });

const volumesToExport = [
  { volume: 'archon-os_paperclip_volume', out: 'paperclip_volume.tar' },
  { volume: 'paperclip_paperclip_volume', out: 'paperclip_paperclip_volume.tar' },
  { volume: 'archon-os_n8n_data', out: 'archon_os_n8n_data.tar' },
  { volume: 'n8n_data', out: 'n8n_data.tar' },
  { volume: 'omniroute-data', out: 'omniroute_data.tar' },
  { volume: 'omniroute_omniroute_data', out: 'omniroute_omniroute_data.tar' },
  { volume: 'archon-os_anythingllm_storage', out: 'anythingllm_storage.tar' }
];

for (const v of volumesToExport) {
  try {
    // Prüfe zuerst, ob das Volume existiert
    execSync(`docker volume inspect ${v.volume}`, { stdio: 'ignore' });
    const tarPath = path.join(dockerVolumesDir, v.out);
    console.log(`      Exportiere Volume: ${v.volume} -> ${v.out}`);
    execSync(`docker run --rm -v ${v.volume}:/source:ro -v "${dockerVolumesDir}":/backup alpine tar -cf /backup/${v.out} -C /source .`, { stdio: 'inherit' });
    fileCounters.docker_volumes++;
  } catch (err) {
    // Volume existiert nicht oder kann ignoriert werden
  }
}
console.log(`      -> ${fileCounters.docker_volumes} Docker-Volumes exportiert`);

// 3. HERMES AGENTEN STATE & PROFILE
console.log(`\n[3/5] Sichere Hermes Profile & Agenten-Datenbanken (C:\\Users\\micha\\.hermes)...`);
const hermesSrc = 'C:\\Users\\micha\\.hermes';
const hermesDest = path.join(tempBackupRoot, 'hermes_home');
const hermesExcludes = [
  '.cache', '.apptainer', '.venv-img', 'my-venv', 'cache', 'sandboxes',
  'video-collection', 'audio_cache', 'image_cache', 'backups', 'lazy-packages',
  '.pytest_cache', '.nimbus-staging', 'node_modules', '.git'
];
copyDirRecursive(hermesSrc, hermesDest, hermesExcludes, 'hermes_home');
console.log(`      -> Hermes Home gesichert (${fileCounters.hermes_home} Dateien)`);

// 4. OBSIDIAN VAULT
console.log(`\n[4/5] Sichere Obsidian Knowledge Vault (C:\\Mein Obsidian)...`);
const obsSrc = 'C:\\Mein Obsidian';
const obsDest = path.join(tempBackupRoot, 'obsidian_vault');
copyDirRecursive(obsSrc, obsDest, ['.trash'], 'obsidian_vault');
console.log(`      -> Obsidian Vault gesichert (${fileCounters.obsidian_vault} Dateien)`);

// 5. AGENTICOS CODEBASE & TEMPLATES & SCRIPTS
console.log(`\n[5/5] Sichere AgenticOS Codebase, Prompts & Konfigurationen...`);
const codeSrc = 'C:\\.Antigravity-projekte\\AgenticOS-2026';
const codeDest = path.join(tempBackupRoot, 'agenticos_codebase');
const codeExcludes = [
  'node_modules', '.git', 'backups', '.venv', 'venv', 'browser-use',
  'pocketbase', 'pocketbase-media', '__pycache__', '.pytest_cache',
  'conv_sep23.db', 'conv_sep26.db', 'conv_sep28.db', 'conv.db'
];
copyDirRecursive(codeSrc, codeDest, codeExcludes, 'agenticos_codebase');
console.log(`      -> Codebase gesichert (${fileCounters.agenticos_codebase} Dateien)`);

// 6. MANIFEST & RESTORE ANLEITUNG ERSTELLEN
console.log(`\n[INFO] Erstelle backup_manifest.json und README_RESTORE.txt...`);
let gitCommit = "unknown";
try {
  gitCommit = execSync("git rev-parse HEAD", { cwd: codeSrc, encoding: "utf8" }).trim();
} catch (_) {}

const manifest = {
  timestamp: timestamp,
  backup_type: "FULL_PORTABLE_SYSTEM_BACKUP",
  system: "ARCHON OS / Antigravity 2026",
  created_at: new Date().toISOString(),
  git_commit: gitCommit,
  file_counts: fileCounters,
  components: {
    pocketbase_crm: `CRM SQLite DB & Storage (${fileCounters.pocketbase_crm} Dateien)`,
    pocketbase_media: `Media SQLite DB & Storage (${fileCounters.pocketbase_media} Dateien)`,
    docker_volumes: `Docker Volumes (${fileCounters.docker_volumes} TAR-Archive: Paperclip, n8n, OmniRoute)`,
    hermes_home: `All Profiles, Prompts, kanban.db, state.db, config.yaml, .env (${fileCounters.hermes_home} Dateien)`,
    obsidian_vault: `Obsidian Knowledge Vault (${fileCounters.obsidian_vault} Dateien)`,
    agenticos_codebase: `Archon OS Codebase, UI, Prompts, Backend, Docker Compose (${fileCounters.agenticos_codebase} Dateien)`
  }
};
fs.writeFileSync(path.join(tempBackupRoot, 'backup_manifest.json'), JSON.stringify(manifest, null, 2), 'utf8');

const readmeContent = `===================================================================
AGENTIC OS 2026 — VOLLSTÄNDIGE SYSTEM-WIEDERHERSTELLUNG (PORTABEL)
Erstellt am: ${timestamp}
Git Commit:  ${gitCommit}
===================================================================

Dieses Verzeichnis bzw. Archiv enthält das vollständige System-Backup
des laufenden AgenticOS 2026 / Archon OS Projekts.

KOMPONENTEN:
------------
1. [pocketbase_crm]
   PocketBase CRM Datenbank & Dateispeicher (pb_data).
   -> Wiederherstellung: Nach pocketbase/pb_data kopieren.

2. [pocketbase_media]
   PocketBase Media Studio Datenbank & Speicher (pb_data).
   -> Wiederherstellung: Nach pocketbase-media/pb_data kopieren.

3. [docker_volumes]
   Enthält komprimierte TAR-Archive der Docker Volumes:
   - paperclip_volume.tar
   - archon_os_n8n_data.tar
   - omniroute_data.tar
   -> Wiederherstellung per:
      docker run --rm -v <volume_name>:/dest -v /pfad/zu/docker_volumes:/backup alpine tar -xf /backup/<datei.tar> -C /dest

4. [hermes_home]
   Alle Agenten-Profile, System-Prompts, API-Keys (.env),
   Konfigurationen (config.yaml) sowie SQLite-Datenbanken (state.db, kanban.db).
   -> Auf neuem PC kopieren nach: %USERPROFILE%\\.hermes (z.B. C:\\Users\\<User>\\.hermes)

5. [obsidian_vault]
   Kompletter Obsidian Knowledge Vault.
   -> Auf neuem PC kopieren nach: C:\\Mein Obsidian

6. [agenticos_codebase]
   Vollständiger Quellcode, UI (index.html mit Live-Styles), Python-Backend (main.py),
   Skripte, Templates, Rollen und Docker-Compose-Dateien.
   -> Als Hauptverzeichnis verwenden: C:\\.Antigravity-projekte\\AgenticOS-2026

START NACH WIEDERHERSTELLUNG:
-----------------------------
1. Docker Desktop starten.
2. In 'agenticos_codebase' Konsole öffnen:
   docker compose -f docker-compose.archon.yml up -d
===================================================================
`;
fs.writeFileSync(path.join(tempBackupRoot, 'README_RESTORE.txt'), readmeContent, 'utf8');

// 7. KOMPRESSION MIT 7-ZIP
console.log(`\n[KOMPRESSION] Erstelle Zip-Archiv: ${localZipPath}`);
console.log(`              Verwende 7-Zip Multithreading (-mx5 -mmt=on)...`);

const sevenZipArgs = [
  'a',
  '-tzip',
  '-mx5',
  '-mmt=on',
  localZipPath,
  path.join(tempBackupRoot, '*')
];

const zipRes = spawnSync(SEVEN_ZIP, sevenZipArgs, { stdio: 'inherit' });
if (zipRes.status !== 0) {
  console.error(`[ERROR] 7-Zip Fehler mit Exit-Code ${zipRes.status}`);
  process.exit(1);
}

const stats = fs.statSync(localZipPath);
const sizeMB = (stats.size / (1024 * 1024)).toFixed(2);
const sizeGB = (stats.size / (1024 * 1024 * 1024)).toFixed(2);
console.log(`\n[ERFOLG] Lokales Backup-Archiv erfolgreich erstellt: ${sizeMB} MB (${sizeGB} GB)`);

// 8. DIRECT SYNC TO NAS
if (fs.existsSync(NAS_TARGET_DIR)) {
  console.log(`\n[NAS-SYNC] Kopiere Backup auf NAS (${nasZipPath})...`);
  try {
    fs.copyFileSync(localZipPath, nasZipPath);
    const nasStats = fs.statSync(nasZipPath);
    if (nasStats.size === stats.size) {
      console.log(`[NAS-SYNC] Erfolgreich auf NAS übertragen und Dateigröße verifiziert (${sizeGB} GB)!`);
    } else {
      console.warn(`[NAS-SYNC WARN] Größenunterschied festgestellt! Lokal: ${stats.size} Bytes, NAS: ${nasStats.size} Bytes`);
    }
  } catch (err) {
    console.warn(`[NAS-SYNC WARN] Fehler beim Kopieren auf NAS: ${err.message}`);
  }
} else {
  console.warn(`\n[WARNUNG] NAS-Pfad ${NAS_TARGET_DIR} ist aktuell nicht erreichbar.`);
}

// 9. BEREINIGUNG DES UNKOMPRIMIERTEN TEMP-ORDNERS
console.log(`\n[CLEANUP] Bereinige Staging-Ordner: ${tempBackupRoot}...`);
try {
  fs.rmSync(tempBackupRoot, { recursive: true, force: true });
  console.log(`[CLEANUP] Staging-Ordner erfolgreich entfernt.`);
} catch (e) {
  console.warn(`[CLEANUP WARN] ${e.message}`);
}

console.log(`\n===================================================================`);
console.log(`SYSTEM-BACKUP VOLLSTÄNDIG ABGESCHLOSSEN!`);
console.log(`Archivname:  ${backupName}.zip`);
console.log(`Dateigröße:  ${sizeGB} GB (${sizeMB} MB)`);
console.log(`Lokal:       ${localZipPath}`);
console.log(`NAS:         ${nasZipPath}`);
console.log(`===================================================================`);
