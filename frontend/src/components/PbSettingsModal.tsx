"use client";

import React, { useState, useEffect } from 'react';
import { pb } from '@/lib/pocketbase';
import { archonFetch } from '@/lib/archon-api';
import {
  X, Settings, Mail, HardDrive, Shield, Clock, Terminal, Download, Upload,
  Cpu, Check, Activity, Database, Play, RefreshCw, Send, FileCode, CheckCircle2, AlertTriangle, Layers
} from 'lucide-react';

interface PbSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  defaultSection?: string;
  themeMode?: 'light' | 'dark';
}

export function PbSettingsModal({
  isOpen,
  onClose,
  defaultSection = 'Application',
  themeMode = 'light'
}: PbSettingsModalProps) {
  const [activeSection, setActiveSection] = useState<string>(defaultSection);
  const isLight = themeMode === 'light';

  // Application Settings State
  const [appName, setAppName] = useState('Archon OS CRM');
  const [appUrl, setAppUrl] = useState('http://localhost:8090');
  const [accentColor] = useState('#1055c9');
  const [batchApiEnabled] = useState(true);
  const [ipProxyEnabled] = useState(false);
  const [rateLimitingEnabled] = useState(false);
  // D01: accentColor / batchApiEnabled / ipProxyEnabled / rateLimitingEnabled
  // und rateLimitMax haben keinen Backend-Endpunkt. Sie bleiben absichtlich
  // nicht persistsiert und werden deaktiviert statt als "gespeichert" gezeigt.

  // Mail Settings State
  const [smtpHost, setSmtpHost] = useState('smtp.mailtrap.io');
  const [smtpPort, setSmtpPort] = useState('587');
  const [smtpUser, setSmtpUser] = useState('archon_admin');
  const [smtpPass, setSmtpPass] = useState('••••••••••••');
  const [senderAddress, setSenderAddress] = useState('noreply@archon.os');
  const [senderName, setSenderName] = useState('Archon CRM System');
  const [testEmailStatus, setTestEmailStatus] = useState<string | null>(null);

  // Files Storage State
  const [storageProvider, setStorageProvider] = useState<'local' | 's3'>('local');
  const [s3Bucket, setS3Bucket] = useState('archon-crm-files');
  const [s3Region, setS3Region] = useState('eu-central-1');
  const [s3Endpoint, setS3Endpoint] = useState('https://s3.eu-central-1.amazonaws.com');
  const [maxUploadSizeMb, setMaxUploadSizeMb] = useState(52428800); // 50MB

  // W4 (Audit): keine erfundenen Backups/Crons/Logs/Ergebnisse mehr.
  // Die Daten stammen aus echten Endpunkten oder bleiben leer.
  const [backups, setBackups] = useState<Array<{ id: string; name: string; size: string; date: string }>>([]);
  const [crons, setCrons] = useState<Array<{ id: string; name: string; schedule: string; status: string; lastRun: string }>>([]);
  const [logs, setLogs] = useState<Array<{ id: string; status: number; method: string; url: string; duration: string; ip: string; time: string }>>([]);

  // SQL Console State
  const [sqlQuery, setSqlQuery] = useState('SELECT id, name, unternehmen, status, rating FROM kontakte LIMIT 5;');
  const [sqlResult, setSqlResult] = useState<any[] | null>(null);

  // Ehrlicher Hinweis für noch nicht verdrahtete Admin-Funktionen.
  const [featureNotice, setFeatureNotice] = useState<string | null>(null);

  // Global UI feedback state
  const [saving, setSaving] = useState(false);
  const [savedNotice, setSavedNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    setActiveSection(defaultSection);

    // D08: kein State-Update nach Unmount/Schliessen des Modals.
    const controller = new AbortController();

    // Attempt fetching settings from PocketBase SDK if admin logged in
    const loadPbSettings = async () => {
      try {
        const result = await pb.settings.getAll();
        if (controller.signal.aborted) return;
        if (result) {
          if (result.appName) setAppName(result.appName);
          if (result.appUrl) setAppUrl(result.appUrl);
          if (result.smtp) {
            setSmtpHost(result.smtp.host || smtpHost);
            setSmtpPort(result.smtp.port?.toString() || smtpPort);
            setSmtpUser(result.smtp.username || smtpUser);
          }
        }
      } catch (err) {
        // Fallback to managed state if non-admin or restricted
      }
    };

    void loadPbSettings();
    return () => controller.abort();
  }, [isOpen, defaultSection]);

  if (!isOpen) return null;

  const smtpPayload = () => ({
    enabled: true,
    host: smtpHost,
    port: Number(smtpPort),
    username: smtpUser,
    password: smtpPass,
    from_email: senderAddress,
    to_email: senderAddress,
  });

  const handleSave = async () => {
    setSaving(true);
    setFeatureNotice(null);
    setSavedNotice(null);
    try {
      if (activeSection === 'Mail settings') {
        // F-001: SMTP-Felder an den echten, admin-gesicherten Endpunkt senden.
        // Der Endpunkt kann auch bei HTTP 200 `status: "error"` liefern.
        const data = await archonFetch<{ status?: string; message?: string }>(
          'api/v1/settings/smtp',
          { method: 'POST', body: JSON.stringify(smtpPayload()) }
        );
        if (data?.status === 'error') {
          throw new Error(data.message || 'SMTP-Konfiguration vom Backend abgelehnt');
        }
      } else if (activeSection === 'Files storage') {
        // F-001: kein Backend-Endpunkt vorhanden -> ehrlicher Hinweis statt
        // eines grünen "Gespeichert!" ohne Seiteneffekt.
        setFeatureNotice('Storage-Einstellungen sind hier noch nicht verdrahtet — es gibt keinen Backend-Endpunkt. Werte wurden nicht gespeichert.');
        return;
      } else {
        // D01/MED: nur Name und URL werden tatsaechlich persistiert. Die
        // uebrigen Application-Controls sind deaktiviert (siehe Hinweis).
        await pb.settings.update({ meta: { appName, appUrl } });
      }
      setSavedNotice(activeSection === 'Mail settings' ? 'SMTP-Einstellungen gespeichert' : 'Name & URL gespeichert');
      setTimeout(() => setSavedNotice(null), 1500);
    } catch (err) {
      setFeatureNotice(`Speichern fehlgeschlagen: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSaving(false);
    }
  };

  const handleSendTestEmail = async () => {
    setTestEmailStatus('sending');
    try {
      // F-002: der Endpunkt verlangt ein SmtpConfigPayload — ohne Body gibt es
      // dauerhaft HTTP 422. Jetzt alle eingegebenen Felder mitsenden.
      const data = await archonFetch<{ status?: string; message?: string; error?: string }>(
        'api/v1/settings/smtp/test',
        { method: 'POST', body: JSON.stringify(smtpPayload()) }
      );
      if (data?.status === 'success') {
        setTestEmailStatus('success');
      } else {
        setTestEmailStatus('error');
        setFeatureNotice(`SMTP-Test fehlgeschlagen: ${data?.message || data?.error || 'kein Erfolgsstatus'}`);
      }
    } catch (err) {
      setTestEmailStatus('error');
      setFeatureNotice(`SMTP-Test nicht erreichbar: ${err instanceof Error ? err.message : String(err)}`);
    }
    setTimeout(() => setTestEmailStatus(null), 4000);
  };

  const handleReloadLogs = async () => {
    // F-005: kein Fake-Refresh einer leeren Liste.
    setFeatureNotice('Request-Logs sind hier noch nicht verdrahtet — kein Endpunkt abgefragt. Bitte das zentrale Audit-Log verwenden.');
  };

  const handleExportSchema = async () => {
    // F-003: echte Collection-Struktur von PocketBase holen (Admin-Sitzung),
    // keinen hartcodierten lokalen Fallback als "Export" ausgeben.
    try {
      const collections = (pb as any).collections;
      if (!collections || typeof collections.getOne !== 'function') {
        throw new Error('Collection-API nicht verfügbar');
      }
      const collection = await collections.getOne('kontakte');
      const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(
        JSON.stringify({ source: 'pocketbase', collection }, null, 2)
      );
      const downloadAnchor = document.createElement('a');
      downloadAnchor.setAttribute('href', dataStr);
      downloadAnchor.setAttribute('download', 'archon_schema.json');
      document.body.appendChild(downloadAnchor);
      downloadAnchor.click();
      downloadAnchor.remove();
    } catch (err) {
      setFeatureNotice(`Schema-Export fehlgeschlagen: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleImportSchema = async (file: File | undefined) => {
    // F-004: echte Datei -> Validierung -> PocketBase Collection-Update.
    if (!file) return;
    setFeatureNotice(null);
    try {
      const parsed = JSON.parse(await file.text());
      const collection = parsed?.collection ?? parsed;
      if (!collection || typeof collection !== 'object') {
        throw new Error('Ungültiges schema.json Format');
      }
      const collections = (pb as any).collections;
      if (!collections || typeof collections.update !== 'function') {
        throw new Error('Collection-API nicht verfügbar (Admin-Rechte erforderlich)');
      }
      await collections.update('kontakte', collection);
      setFeatureNotice('Schema-Import von PocketBase bestätigt.');
    } catch (err) {
      setFeatureNotice(`Schema-Import fehlgeschlagen: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleCreateBackup = () => {
    // W4: kein Fake-Backup mit hartcodierter "14.5 MB".
    setFeatureNotice('Backup-Erstellung ist hier noch nicht verdrahtet — bitte backup_archon.py oder die PocketBase-Admin-API nutzen.');
  };

  const handleRunCron = (cronName: string) => {
    // W4: kein "Gerade eben", wenn kein Job gestartet wurde.
    setFeatureNotice(`Cron „${cronName}“ kann hier noch nicht gestartet werden — kein Trigger-Endpunkt vorhanden.`);
  };

  const handleRunSqlQuery = () => {
    // W4: die Query wurde früher komplett ignoriert.
    setSqlResult(null);
    setFeatureNotice('SQL-Konsole ist hier nicht verdrahtet — keine Abfrage ausgeführt. Bitte PocketBase-Admin-UI nutzen.');
  };

  return (
    <div className="fixed inset-0 overflow-hidden flex items-center justify-center p-4 archon-modal-layer archon-modal-shade">
      <div className={`w-full max-w-5xl rounded-2xl border shadow-2xl overflow-hidden flex flex-col h-[85vh] animate-in zoom-in-95 duration-150 ${
        isLight ? 'bg-white border-slate-200 text-slate-900' : 'bg-slate-900 border-slate-800 text-slate-100'
      }`}>

        {/* W4: ehrlicher Hinweis statt vorgetäuschtem Erfolg */}
        {featureNotice && (
          <div className="shrink-0 border-b border-amber-500/40 bg-amber-500/10 px-6 py-2 text-xs text-amber-300">
            {featureNotice}
          </div>
        )}

        {/* Top Header Bar (Bild 1 Style) */}
        <div className={`h-14 border-b px-6 flex items-center justify-between shrink-0 font-mono text-xs ${
          isLight ? 'bg-slate-50 border-slate-200' : 'bg-slate-950 border-slate-800'
        }`}>
          <div className="flex items-center gap-2">
            <span className="text-slate-400">Settings</span>
            <span className="text-slate-400">/</span>
            <span className="font-bold text-emerald-600 font-sans">{activeSection}</span>
          </div>

          <div className="flex items-center gap-3">
            {savedNotice && (
              <span className="text-xs text-emerald-600 font-bold flex items-center gap-1 font-sans animate-in fade-in duration-150">
                <Check className="w-3.5 h-3.5" />
                <span>{savedNotice}</span>
              </span>
            )}
            <button
              onClick={onClose}
              className="p-1 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-800 text-slate-400 transition"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Main Body (Left Sidebar + Right Interactive Panel) */}
        <div className="flex-1 flex overflow-hidden">
          
          {/* Left Settings Sidebar (Bild 1 Style) */}
          <div className={`w-56 border-r p-4 space-y-6 overflow-y-auto shrink-0 font-mono text-xs ${
            isLight ? 'bg-slate-50/60 border-slate-200' : 'bg-slate-950/40 border-slate-800'
          }`}>
            {/* System Group */}
            <div className="space-y-1">
              <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2 font-sans">System</p>
              
              <button
                onClick={() => setActiveSection('Application')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left transition font-semibold ${
                  activeSection === 'Application'
                    ? isLight ? 'bg-slate-200 text-slate-900 font-bold' : 'bg-slate-800 text-white font-bold'
                    : 'text-slate-500 hover:text-slate-900 dark:hover:text-slate-200'
                }`}
              >
                <Settings className="w-4 h-4 text-emerald-600" />
                <span>Application</span>
              </button>

              <button
                onClick={() => setActiveSection('Mail settings')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left transition ${
                  activeSection === 'Mail settings'
                    ? isLight ? 'bg-slate-200 text-slate-900 font-bold' : 'bg-slate-800 text-white font-bold'
                    : 'text-slate-500 hover:text-slate-900 dark:hover:text-slate-200'
                }`}
              >
                <Mail className="w-4 h-4 text-blue-500" />
                <span>Mail settings</span>
              </button>

              <button
                onClick={() => setActiveSection('Files storage')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left transition ${
                  activeSection === 'Files storage'
                    ? isLight ? 'bg-slate-200 text-slate-900 font-bold' : 'bg-slate-800 text-white font-bold'
                    : 'text-slate-500 hover:text-slate-900 dark:hover:text-slate-200'
                }`}
              >
                <HardDrive className="w-4 h-4 text-purple-500" />
                <span>Files storage</span>
              </button>

              <button
                onClick={() => setActiveSection('Backups')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left transition ${
                  activeSection === 'Backups'
                    ? isLight ? 'bg-slate-200 text-slate-900 font-bold' : 'bg-slate-800 text-white font-bold'
                    : 'text-slate-500 hover:text-slate-900 dark:hover:text-slate-200'
                }`}
              >
                <Shield className="w-4 h-4 text-amber-500" />
                <span>Backups</span>
              </button>

              <button
                onClick={() => setActiveSection('Crons')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left transition ${
                  activeSection === 'Crons'
                    ? isLight ? 'bg-slate-200 text-slate-900 font-bold' : 'bg-slate-800 text-white font-bold'
                    : 'text-slate-500 hover:text-slate-900 dark:hover:text-slate-200'
                }`}
              >
                <Clock className="w-4 h-4 text-cyan-500" />
                <span>Crons</span>
              </button>

              <button
                onClick={() => setActiveSection('Logs')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left transition ${
                  activeSection === 'Logs'
                    ? isLight ? 'bg-slate-200 text-slate-900 font-bold' : 'bg-slate-800 text-white font-bold'
                    : 'text-slate-500 hover:text-slate-900 dark:hover:text-slate-200'
                }`}
              >
                <Activity className="w-4 h-4 text-rose-500" />
                <span>Logs</span>
              </button>
            </div>

            {/* Sync Group */}
            <div className="space-y-1">
              <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2 font-sans">Sync</p>

              <button
                onClick={() => setActiveSection('Export collections')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left transition ${
                  activeSection === 'Export collections'
                    ? isLight ? 'bg-slate-200 text-slate-900 font-bold' : 'bg-slate-800 text-white font-bold'
                    : 'text-slate-500 hover:text-slate-900 dark:hover:text-slate-200'
                }`}
              >
                <Download className="w-4 h-4 text-indigo-500" />
                <span>Export collections</span>
              </button>

              <button
                onClick={() => setActiveSection('Import collections')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left transition ${
                  activeSection === 'Import collections'
                    ? isLight ? 'bg-slate-200 text-slate-900 font-bold' : 'bg-slate-800 text-white font-bold'
                    : 'text-slate-500 hover:text-slate-900 dark:hover:text-slate-200'
                }`}
              >
                <Upload className="w-4 h-4 text-emerald-500" />
                <span>Import collections</span>
              </button>
            </div>

            {/* Debug Group */}
            <div className="space-y-1">
              <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2 font-sans">Debug</p>

              <button
                onClick={() => setActiveSection('SQL console')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left transition ${
                  activeSection === 'SQL console'
                    ? isLight ? 'bg-slate-200 text-slate-900 font-bold' : 'bg-slate-800 text-white font-bold'
                    : 'text-slate-500 hover:text-slate-900 dark:hover:text-slate-200'
                }`}
              >
                <Terminal className="w-4 h-4 text-slate-400" />
                <span>SQL console</span>
              </button>
            </div>
          </div>

          {/* Right Interactive Content Area */}
          <div className="flex-1 p-8 overflow-y-auto space-y-6">
            
            {/* 1. APPLICATION SECTION */}
            {activeSection === 'Application' && (
              <div className="max-w-2xl space-y-6">
                {/* D01/MED: nur Name/URL haben einen Persistenzpfad. */}
                <p className="text-[11px] font-mono text-amber-400 border border-amber-500/40 bg-amber-500/10 rounded-lg px-3 py-2">
                  Hinweis: Es werden nur Name und URL gespeichert. Akzentfarbe, Batch-Web-API,
                  IP-Proxy, Rate-Limiting und Rate-Limit-Maximum haben keinen Backend-Endpunkt
                  und sind deshalb deaktiviert.
                </p>
                <div className="grid grid-cols-3 gap-4">
                  <div className="col-span-1">
                    <label className="block text-xs font-bold mb-1 font-mono">Application name *</label>
                    <input
                      type="text"
                      value={appName}
                      onChange={(e) => setAppName(e.target.value)}
                      className={`w-full p-2.5 border rounded-lg text-xs font-mono transition ${
                        isLight ? 'bg-slate-100 border-slate-300 text-slate-900' : 'bg-slate-950 border-slate-800 text-slate-100'
                      }`}
                    />
                  </div>
                  <div className="col-span-1">
                    <label className="block text-xs font-bold mb-1 font-mono">Application URL *</label>
                    <input
                      type="text"
                      value={appUrl}
                      onChange={(e) => setAppUrl(e.target.value)}
                      className={`w-full p-2.5 border rounded-lg text-xs font-mono transition ${
                        isLight ? 'bg-slate-100 border-slate-300 text-slate-900' : 'bg-slate-950 border-slate-800 text-slate-100'
                      }`}
                    />
                  </div>
                  <div className="col-span-1">
                    <label className="block text-xs font-bold mb-1 font-mono">Accent</label>
                    <input
                      type="text"
                      value={accentColor}
                      readOnly
                      disabled
                      title="Kein Backend-Endpunkt — nicht speicherbar"
                      aria-label="Akzentfarbe (nicht konfigurierbar)"
                      className="w-full p-2.5 border rounded-lg text-xs font-mono bg-blue-600 text-white font-bold opacity-60 cursor-not-allowed"
                    />
                  </div>
                </div>

                <div className={`rounded-xl border divide-y ${
                  isLight ? 'bg-white border-slate-200 divide-slate-200' : 'bg-slate-950 border-slate-800 divide-slate-800'
                }`}>
                  <div className="p-3.5 flex items-center justify-between text-xs font-mono">
                    <span className="flex items-center gap-2">
                      <Database className="w-4 h-4 text-slate-400" />
                      <span>Batch Web API</span>
                    </span>
                    <button
                      type="button"
                      disabled
                      title="Kein Backend-Endpunkt — nicht speicherbar"
                      aria-label="Batch Web API (nicht konfigurierbar)"
                      className={`px-2.5 py-0.5 rounded text-[11px] font-bold opacity-60 cursor-not-allowed ${
                        batchApiEnabled ? 'bg-emerald-500/10 text-emerald-600 border border-emerald-500/30' : 'bg-slate-100 text-slate-400'
                      }`}
                    >
                      {batchApiEnabled ? 'Enabled' : 'Disabled'}
                    </button>
                  </div>

                  <div className="p-3.5 flex items-center justify-between text-xs font-mono">
                    <span className="flex items-center gap-2">
                      <Cpu className="w-4 h-4 text-slate-400" />
                      <span>IP proxy headers</span>
                    </span>
                    <button
                      type="button"
                      disabled
                      title="Kein Backend-Endpunkt — nicht speicherbar"
                      aria-label="IP-Proxy-Header (nicht konfigurierbar)"
                      className={`px-2.5 py-0.5 rounded text-[11px] font-bold opacity-60 cursor-not-allowed ${
                        ipProxyEnabled ? 'bg-emerald-500/10 text-emerald-600 border border-emerald-500/30' : 'bg-slate-100 text-slate-400'
                      }`}
                    >
                      {ipProxyEnabled ? 'Enabled' : 'Disabled'}
                    </button>
                  </div>

                  <div className="p-3.5 flex items-center justify-between text-xs font-mono">
                    <span className="flex items-center gap-2">
                      <Activity className="w-4 h-4 text-slate-400" />
                      <span>Rate limiting</span>
                    </span>
                    <button
                      type="button"
                      disabled
                      title="Kein Backend-Endpunkt — nicht speicherbar"
                      aria-label="Rate-Limiting (nicht konfigurierbar)"
                      className={`px-2.5 py-0.5 rounded text-[11px] font-bold opacity-60 cursor-not-allowed ${
                        rateLimitingEnabled ? 'bg-emerald-500/10 text-emerald-600 border border-emerald-500/30' : 'bg-slate-100 text-slate-400'
                      }`}
                    >
                      {rateLimitingEnabled ? 'Enabled' : 'Disabled'}
                    </button>
                  </div>
                </div>

                <div className="flex justify-end">
                  <button
                    onClick={handleSave}
                    disabled={saving}
                    className="px-6 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold transition text-xs font-sans shadow-md flex items-center gap-2"
                  >
                    {saving && <RefreshCw className="w-3.5 h-3.5 animate-spin" />}
                    <span>Save changes</span>
                  </button>
                </div>
              </div>
            )}

            {/* 2. MAIL SETTINGS SECTION */}
            {activeSection === 'Mail settings' && (
              <div className="max-w-2xl space-y-6">
                <h3 className="text-sm font-bold font-sans">SMTP Mail Server Konfiguration</h3>
                <div className="grid grid-cols-2 gap-4 text-xs font-mono">
                  <div>
                    <label className="block font-bold mb-1">SMTP Host</label>
                    <input
                      type="text"
                      value={smtpHost}
                      onChange={(e) => setSmtpHost(e.target.value)}
                      className={`w-full p-2.5 border rounded-lg ${isLight ? 'bg-slate-50 border-slate-300' : 'bg-slate-950 border-slate-800'}`}
                    />
                  </div>
                  <div>
                    <label className="block font-bold mb-1">Port</label>
                    <input
                      type="text"
                      value={smtpPort}
                      onChange={(e) => setSmtpPort(e.target.value)}
                      className={`w-full p-2.5 border rounded-lg ${isLight ? 'bg-slate-50 border-slate-300' : 'bg-slate-950 border-slate-800'}`}
                    />
                  </div>
                  <div>
                    <label className="block font-bold mb-1">Username</label>
                    <input
                      type="text"
                      value={smtpUser}
                      onChange={(e) => setSmtpUser(e.target.value)}
                      className={`w-full p-2.5 border rounded-lg ${isLight ? 'bg-slate-50 border-slate-300' : 'bg-slate-950 border-slate-800'}`}
                    />
                  </div>
                  <div>
                    <label className="block font-bold mb-1">Password</label>
                    <input
                      type="password"
                      value={smtpPass}
                      onChange={(e) => setSmtpPass(e.target.value)}
                      className={`w-full p-2.5 border rounded-lg ${isLight ? 'bg-slate-50 border-slate-300' : 'bg-slate-950 border-slate-800'}`}
                    />
                  </div>
                  <div>
                    <label className="block font-bold mb-1">Sender Email</label>
                    <input
                      type="email"
                      value={senderAddress}
                      onChange={(e) => setSenderAddress(e.target.value)}
                      className={`w-full p-2.5 border rounded-lg ${isLight ? 'bg-slate-50 border-slate-300' : 'bg-slate-950 border-slate-800'}`}
                    />
                  </div>
                  <div>
                    <label className="block font-bold mb-1">Sender Name</label>
                    <input
                      type="text"
                      value={senderName}
                      onChange={(e) => setSenderName(e.target.value)}
                      className={`w-full p-2.5 border rounded-lg ${isLight ? 'bg-slate-50 border-slate-300' : 'bg-slate-950 border-slate-800'}`}
                    />
                  </div>
                </div>

                <div className="flex items-center justify-between pt-4 border-t border-slate-200 dark:border-slate-800">
                  <button
                    onClick={handleSendTestEmail}
                    className="px-4 py-2 rounded-lg bg-blue-600 text-white font-bold text-xs hover:bg-blue-500 transition flex items-center gap-1.5"
                  >
                    <Send className="w-3.5 h-3.5" />
                    <span>{testEmailStatus === 'sending' ? 'Sende...' : 'Send Test Email'}</span>
                  </button>

                  {testEmailStatus === 'success' && (
                    <span className="text-xs text-emerald-600 font-bold flex items-center gap-1">
                      <Check className="w-4 h-4" /> Test-E-Mail erfolgreich zugestellt!
                    </span>
                  )}

                  <button
                    onClick={handleSave}
                    className="px-6 py-2.5 rounded-lg bg-emerald-600 text-white font-bold text-xs hover:bg-emerald-500 transition shadow-md"
                  >
                    Save settings
                  </button>
                </div>
              </div>
            )}

            {/* 3. FILES STORAGE SECTION */}
            {activeSection === 'Files storage' && (
              <div className="max-w-2xl space-y-6">
                <h3 className="text-sm font-bold font-sans">Dateispeicher Engine</h3>
                <div className="flex gap-4">
                  <button
                    onClick={() => setStorageProvider('local')}
                    className={`flex-1 p-4 rounded-xl border text-left transition font-mono ${
                      storageProvider === 'local' ? 'border-emerald-500 bg-emerald-500/10' : 'border-slate-200 dark:border-slate-800'
                    }`}
                  >
                    <HardDrive className="w-5 h-5 text-emerald-600 mb-2" />
                    <p className="font-bold text-xs">Lokales Dateisystem</p>
                    <p className="text-[11px] text-slate-400">Speichert Uploads im `/pb_data/storage` Ordner</p>
                  </button>

                  <button
                    onClick={() => setStorageProvider('s3')}
                    className={`flex-1 p-4 rounded-xl border text-left transition font-mono ${
                      storageProvider === 's3' ? 'border-emerald-500 bg-emerald-500/10' : 'border-slate-200 dark:border-slate-800'
                    }`}
                  >
                    <Database className="w-5 h-5 text-blue-500 mb-2" />
                    <p className="font-bold text-xs">Amazon S3 / MinIO</p>
                    <p className="text-[11px] text-slate-400">Cloud Storage Bucket Integration</p>
                  </button>
                </div>

                {storageProvider === 's3' && (
                  <div className="space-y-3 font-mono text-xs border p-4 rounded-xl">
                    <div>
                      <label className="block font-bold mb-1">S3 Bucket</label>
                      <input type="text" value={s3Bucket} onChange={(e) => setS3Bucket(e.target.value)} className="w-full p-2 border rounded" />
                    </div>
                    <div>
                      <label className="block font-bold mb-1">S3 Endpoint</label>
                      <input type="text" value={s3Endpoint} onChange={(e) => setS3Endpoint(e.target.value)} className="w-full p-2 border rounded" />
                    </div>
                  </div>
                )}

                <div className="flex justify-end pt-4 border-t">
                  <button onClick={handleSave} className="px-6 py-2.5 rounded-lg bg-emerald-600 text-white font-bold text-xs">Save Storage Settings</button>
                </div>
              </div>
            )}

            {/* 4. BACKUPS SECTION */}
            {activeSection === 'Backups' && (
              <div className="max-w-2xl space-y-6">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-bold font-sans">PocketBase Datenbank-Backups</h3>
                  <button
                    onClick={handleCreateBackup}
                    className="px-4 py-2 rounded-lg bg-emerald-600 text-white font-bold text-xs hover:bg-emerald-500 transition flex items-center gap-1.5"
                  >
                    <Shield className="w-3.5 h-3.5" />
                    <span>Create Backup Now</span>
                  </button>
                </div>

                <div className={`rounded-xl border font-mono text-xs overflow-hidden ${
                  isLight ? 'bg-white border-slate-200' : 'bg-slate-950 border-slate-800'
                }`}>
                  <table className="w-full text-left">
                    <thead className="border-b bg-slate-100 dark:bg-slate-900 p-3 text-[10px] font-bold text-slate-400 uppercase">
                      <tr>
                        <th className="p-3">Backup Dateiname</th>
                        <th className="p-3">Größe</th>
                        <th className="p-3">Erstellt am</th>
                        <th className="p-3 text-right">Aktion</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                      {backups.map(b => (
                        <tr key={b.id} className="hover:bg-slate-50 dark:hover:bg-slate-900/50">
                          <td className="p-3 font-bold text-emerald-600">{b.name}</td>
                          <td className="p-3">{b.size}</td>
                          <td className="p-3 text-slate-400">{b.date}</td>
                          <td className="p-3 text-right">
                            <button className="text-blue-500 hover:underline font-bold mr-2">Download</button>
                            <button className="text-rose-500 hover:underline font-bold">Löschen</button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* 5. CRONS SECTION */}
            {activeSection === 'Crons' && (
              <div className="max-w-2xl space-y-6 font-mono text-xs">
                <h3 className="text-sm font-bold font-sans">Aktive Cron Tasks</h3>
                <div className="rounded-xl border overflow-hidden">
                  <table className="w-full text-left">
                    <thead className="border-b bg-slate-100 dark:bg-slate-900 p-3 text-[10px] font-bold text-slate-400 uppercase">
                      <tr>
                        <th className="p-3">Job Name</th>
                        <th className="p-3">Schedule</th>
                        <th className="p-3">Status</th>
                        <th className="p-3">Letzter Lauf</th>
                        <th className="p-3 text-right">Ausführen</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                      {crons.map(c => (
                        <tr key={c.id}>
                          <td className="p-3 font-bold text-emerald-600">{c.name}</td>
                          <td className="p-3 text-slate-400">{c.schedule}</td>
                          <td className="p-3"><span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-600 border font-bold">{c.status}</span></td>
                          <td className="p-3 text-slate-400">{c.lastRun}</td>
                          <td className="p-3 text-right">
                            <button onClick={() => handleRunCron(c.name)} className="p-1 rounded text-emerald-600 hover:bg-emerald-500/10"><Play className="w-4 h-4" /></button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* 6. LOGS SECTION */}
            {activeSection === 'Logs' && (
              <div className="space-y-4 font-mono text-xs">
                <div className="flex items-center justify-between">
                  <h3 className="font-bold text-sm font-sans">PocketBase Request Logs</h3>
                  <button onClick={handleReloadLogs} className="px-3 py-1 rounded bg-slate-200 dark:bg-slate-800 font-bold text-slate-600 dark:text-slate-300 flex items-center gap-1">
                    <RefreshCw className="w-3.5 h-3.5" /> Reload
                  </button>
                </div>
                <div className={`p-4 rounded-xl border space-y-2 max-h-96 overflow-y-auto ${isLight ? 'bg-slate-950 text-slate-200 border-slate-800' : 'bg-slate-950 text-slate-200 border-slate-800'}`}>
                  {logs.map(l => (
                    <div key={l.id} className="flex items-center justify-between py-1 border-b border-slate-800/40">
                      <div className="flex items-center gap-3">
                        <span className="text-emerald-400 font-bold">[{l.status}]</span>
                        <span className="text-amber-400 font-bold">{l.method}</span>
                        <span>{l.url}</span>
                      </div>
                      <div className="flex items-center gap-4 text-slate-500">
                        <span>{l.duration}</span>
                        <span>{l.time}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 7. EXPORT COLLECTIONS SECTION */}
            {activeSection === 'Export collections' && (
              <div className="max-w-2xl space-y-6">
                <h3 className="text-sm font-bold font-sans">Collection Schema Export</h3>
                <p className="text-xs text-slate-400 font-mono">Exportiert die `kontakte` Collection-Struktur als wiederverwendbare `schema.json` Datei.</p>
                <button
                  onClick={handleExportSchema}
                  className="px-5 py-2.5 rounded-lg bg-emerald-600 text-white font-bold text-xs hover:bg-emerald-500 transition shadow-md flex items-center gap-2"
                >
                  <Download className="w-4 h-4" />
                  <span>Download schema.json</span>
                </button>
              </div>
            )}

            {/* 8. IMPORT COLLECTIONS SECTION */}
            {activeSection === 'Import collections' && (
              <div className="max-w-2xl space-y-6">
                <h3 className="text-sm font-bold font-sans">Collection Schema Import</h3>
                <div className="border-2 border-dashed border-slate-300 dark:border-slate-700 rounded-xl p-8 text-center space-y-3 font-mono text-xs">
                  <Upload className="w-8 h-8 text-emerald-600 mx-auto" />
                  <p className="font-bold">Ziehe deine `schema.json` hierher</p>
                  <p className="text-slate-400 text-[11px]">Unterstützt PocketBase Schema Definitions</p>
                  {/* F-004: echter Datei-Import statt Dekoration */}
                  <input
                    type="file"
                    accept="application/json,.json"
                    aria-label="schema.json Datei auswählen"
                    className="mx-auto block text-xs"
                    onChange={(event) => void handleImportSchema(event.target.files?.[0])}
                  />
                </div>
              </div>
            )}

            {/* 9. SQL CONSOLE DEBUG SECTION */}
            {activeSection === 'SQL console' && (
              <div className="space-y-4 font-mono text-xs">
                <h3 className="font-bold text-sm font-sans">PocketBase SQLite Console</h3>
                <div className="space-y-2">
                  <textarea
                    rows={3}
                    value={sqlQuery}
                    onChange={(e) => setSqlQuery(e.target.value)}
                    className={`w-full p-3 border rounded-xl font-mono text-xs ${isLight ? 'bg-slate-950 text-emerald-400 border-slate-800' : 'bg-slate-950 text-emerald-400 border-slate-800'}`}
                  />
                  <button
                    onClick={handleRunSqlQuery}
                    className="px-4 py-2 rounded-lg bg-emerald-600 text-white font-bold text-xs hover:bg-emerald-500 transition flex items-center gap-1.5"
                  >
                    <Play className="w-3.5 h-3.5" />
                    <span>Run Query</span>
                  </button>
                </div>

                {sqlResult && (
                  <div className="rounded-xl border overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <thead className="border-b bg-slate-100 dark:bg-slate-900 font-bold text-[10px] text-slate-400">
                        <tr>
                          {Object.keys(sqlResult[0] || {}).map(k => (
                            <th key={k} className="p-2.5">{k}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                        {sqlResult.map((row, idx) => (
                          <tr key={idx}>
                            {Object.values(row).map((v: any, i) => (
                              <td key={i} className="p-2.5">{String(v)}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

          </div>

        </div>

      </div>
    </div>
  );
}

const INITIAL_SCHEMA = [
  { name: 'name', type: 'text', required: true },
  { name: 'unternehmen', type: 'text' },
  { name: 'rolle', type: 'text' },
  { name: 'region', type: 'text' },
  { name: 'vernetzt_am', type: 'date' },
  { name: 'einladung_zurueckgezogen_am', type: 'date' },
  { name: 'status', type: 'select' },
  { name: 'rating', type: 'number' },
  { name: 'naechster_schritt', type: 'text' },
  { name: 'kommentar', type: 'text' },
  { name: 'nachrichtenverlauf', type: 'json' },
  { name: 'profilbild', type: 'file' }
];
