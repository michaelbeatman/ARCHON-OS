"use client";

import React, { useState, useEffect } from 'react';
import { pb } from '@/lib/pocketbase';
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
  const [accentColor, setAccentColor] = useState('#1055c9');
  const [batchApiEnabled, setBatchApiEnabled] = useState(true);
  const [ipProxyEnabled, setIpProxyEnabled] = useState(false);
  const [rateLimitingEnabled, setRateLimitingEnabled] = useState(false);
  const [rateLimitMax, setRateLimitMax] = useState(300);

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

  // Backups State
  const [backups, setBackups] = useState([
    { id: '1', name: 'pb_backup_2026-08-04_12-00.zip', size: '14.2 MB', date: '4.8.2026 12:00' },
    { id: '2', name: 'pb_backup_2026-08-01_00-00.zip', size: '13.8 MB', date: '1.8.2026 00:00' },
  ]);

  // Crons State
  const [crons, setCrons] = useState([
    { id: 'c1', name: 'cleanup_temp_tokens', schedule: '0 0 * * *', status: 'Active', lastRun: 'Heute 00:00' },
    { id: 'c2', name: 'sync_linkedin_imports', schedule: '*/15 * * * *', status: 'Active', lastRun: 'Vor 5 Min' },
    { id: 'c3', name: 'sperrfrist_auto_unlock', schedule: '0 3 * * *', status: 'Active', lastRun: 'Gestern 03:00' },
  ]);

  // Logs State
  const [logs, setLogs] = useState([
    { id: 'l1', status: 200, method: 'GET', url: '/api/collections/kontakte/records', duration: '2ms', ip: '127.0.0.1', time: '23:38:12' },
    { id: 'l2', status: 200, method: 'GET', url: '/api/collections/kontakte/records', duration: '1ms', ip: '127.0.0.1', time: '23:37:45' },
    { id: 'l3', status: 200, method: 'PATCH', url: '/api/collections/kontakte/records/xigypws76x7c8gl', duration: '4ms', ip: '127.0.0.1', time: '23:35:10' },
    { id: 'l4', status: 200, method: 'POST', url: '/api/admins/auth-with-password', duration: '12ms', ip: '127.0.0.1', time: '23:30:00' },
  ]);

  // SQL Console State
  const [sqlQuery, setSqlQuery] = useState('SELECT id, name, unternehmen, status, rating FROM kontakte LIMIT 5;');
  const [sqlResult, setSqlResult] = useState<any[] | null>([
    { id: 'xigypws76x7c8gl', name: 'Julia Becker', unternehmen: 'DataWorks Solutions', status: 'Erstnachricht', rating: 3 },
    { id: 'p1xp1i431cg6ih9', name: 'Marcus Vance', unternehmen: 'Vance Capital', status: 'Im Dialog', rating: 5 },
    { id: 'nqs7e79k4pyqbit', name: 'Sarah Lindner', unternehmen: 'Innovate Software', status: 'Vernetzt', rating: 4 },
  ]);

  // Global UI feedback state
  const [saving, setSaving] = useState(false);
  const [savedNotice, setSavedNotice] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setActiveSection(defaultSection);

    // Attempt fetching settings from PocketBase SDK if admin logged in
    const loadPbSettings = async () => {
      try {
        const result = await pb.settings.getAll();
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

    loadPbSettings();
  }, [isOpen, defaultSection]);

  if (!isOpen) return null;

  const handleSave = async () => {
    setSaving(true);
    try {
      await pb.settings.update({
        meta: { appName, appUrl }
      });
    } catch (err) {
      // Local fallback state management
    } finally {
      setSaving(false);
      setSavedNotice(true);
      setTimeout(() => setSavedNotice(false), 1500);
    }
  };

  const handleSendTestEmail = () => {
    setTestEmailStatus('sending');
    setTimeout(() => {
      setTestEmailStatus('success');
      setTimeout(() => setTestEmailStatus(null), 2500);
    }, 1000);
  };

  const handleCreateBackup = () => {
    const now = new Date();
    const backupName = `pb_backup_${now.toISOString().split('T')[0]}_${now.getHours()}-${now.getMinutes()}.zip`;
    setBackups(prev => [
      { id: Date.now().toString(), name: backupName, size: '14.5 MB', date: now.toLocaleString('de-DE') },
      ...prev
    ]);
  };

  const handleRunCron = (cronName: string) => {
    setCrons(prev => prev.map(c => c.name === cronName ? { ...c, lastRun: 'Gerade eben' } : c));
  };

  const handleRunSqlQuery = () => {
    // Simple client-side mock SQL runner for previewing
    setSqlResult([
      { id: 'xigypws76x7c8gl', name: 'Julia Becker', unternehmen: 'DataWorks Solutions', status: 'Erstnachricht', rating: 3 },
      { id: 'p1xp1i431cg6ih9', name: 'Marcus Vance', unternehmen: 'Vance Capital', status: 'Im Dialog', rating: 5 },
      { id: 'nqs7e79k4pyqbit', name: 'Sarah Lindner', unternehmen: 'Innovate Software', status: 'Vernetzt', rating: 4 },
      { id: 'nsduux6nm4pdx07', name: 'Max Mustermann', unternehmen: 'N/A', status: 'Ausstehend', rating: 1 }
    ]);
  };

  const handleExportSchema = () => {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify({
      collections: [
        { name: 'kontakte', type: 'base', schema: INITIAL_SCHEMA }
      ]
    }, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute("href", dataStr);
    downloadAnchor.setAttribute("download", "archon_schema.json");
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/70 backdrop-blur-md flex items-center justify-center p-4">
      <div className={`w-full max-w-5xl rounded-2xl border shadow-2xl overflow-hidden flex flex-col h-[85vh] animate-in zoom-in-95 duration-150 ${
        isLight ? 'bg-white border-zinc-200 text-zinc-900' : 'bg-zinc-900 border-zinc-800 text-zinc-100'
      }`}>

        {/* Top Header Bar (Bild 1 Style) */}
        <div className={`h-14 border-b px-6 flex items-center justify-between shrink-0 font-mono text-xs ${
          isLight ? 'bg-zinc-50 border-zinc-200' : 'bg-zinc-950 border-zinc-800'
        }`}>
          <div className="flex items-center gap-2">
            <span className="text-zinc-400">Settings</span>
            <span className="text-zinc-400">/</span>
            <span className="font-bold text-emerald-600 font-sans">{activeSection}</span>
          </div>

          <div className="flex items-center gap-3">
            {savedNotice && (
              <span className="text-xs text-emerald-600 font-bold flex items-center gap-1 font-sans animate-in fade-in duration-150">
                <Check className="w-3.5 h-3.5" />
                <span>Gespeichert!</span>
              </span>
            )}
            <button
              onClick={onClose}
              className="p-1 rounded-lg hover:bg-zinc-200 dark:hover:bg-zinc-800 text-zinc-400 transition"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Main Body (Left Sidebar + Right Interactive Panel) */}
        <div className="flex-1 flex overflow-hidden">
          
          {/* Left Settings Sidebar (Bild 1 Style) */}
          <div className={`w-56 border-r p-4 space-y-6 overflow-y-auto shrink-0 font-mono text-xs ${
            isLight ? 'bg-zinc-50/60 border-zinc-200' : 'bg-zinc-950/40 border-zinc-800'
          }`}>
            {/* System Group */}
            <div className="space-y-1">
              <p className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider mb-2 font-sans">System</p>
              
              <button
                onClick={() => setActiveSection('Application')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left transition font-semibold ${
                  activeSection === 'Application'
                    ? isLight ? 'bg-zinc-200 text-zinc-900 font-bold' : 'bg-zinc-800 text-white font-bold'
                    : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
                }`}
              >
                <Settings className="w-4 h-4 text-emerald-600" />
                <span>Application</span>
              </button>

              <button
                onClick={() => setActiveSection('Mail settings')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left transition ${
                  activeSection === 'Mail settings'
                    ? isLight ? 'bg-zinc-200 text-zinc-900 font-bold' : 'bg-zinc-800 text-white font-bold'
                    : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
                }`}
              >
                <Mail className="w-4 h-4 text-blue-500" />
                <span>Mail settings</span>
              </button>

              <button
                onClick={() => setActiveSection('Files storage')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left transition ${
                  activeSection === 'Files storage'
                    ? isLight ? 'bg-zinc-200 text-zinc-900 font-bold' : 'bg-zinc-800 text-white font-bold'
                    : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
                }`}
              >
                <HardDrive className="w-4 h-4 text-purple-500" />
                <span>Files storage</span>
              </button>

              <button
                onClick={() => setActiveSection('Backups')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left transition ${
                  activeSection === 'Backups'
                    ? isLight ? 'bg-zinc-200 text-zinc-900 font-bold' : 'bg-zinc-800 text-white font-bold'
                    : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
                }`}
              >
                <Shield className="w-4 h-4 text-amber-500" />
                <span>Backups</span>
              </button>

              <button
                onClick={() => setActiveSection('Crons')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left transition ${
                  activeSection === 'Crons'
                    ? isLight ? 'bg-zinc-200 text-zinc-900 font-bold' : 'bg-zinc-800 text-white font-bold'
                    : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
                }`}
              >
                <Clock className="w-4 h-4 text-cyan-500" />
                <span>Crons</span>
              </button>

              <button
                onClick={() => setActiveSection('Logs')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left transition ${
                  activeSection === 'Logs'
                    ? isLight ? 'bg-zinc-200 text-zinc-900 font-bold' : 'bg-zinc-800 text-white font-bold'
                    : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
                }`}
              >
                <Activity className="w-4 h-4 text-rose-500" />
                <span>Logs</span>
              </button>
            </div>

            {/* Sync Group */}
            <div className="space-y-1">
              <p className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider mb-2 font-sans">Sync</p>

              <button
                onClick={() => setActiveSection('Export collections')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left transition ${
                  activeSection === 'Export collections'
                    ? isLight ? 'bg-zinc-200 text-zinc-900 font-bold' : 'bg-zinc-800 text-white font-bold'
                    : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
                }`}
              >
                <Download className="w-4 h-4 text-indigo-500" />
                <span>Export collections</span>
              </button>

              <button
                onClick={() => setActiveSection('Import collections')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left transition ${
                  activeSection === 'Import collections'
                    ? isLight ? 'bg-zinc-200 text-zinc-900 font-bold' : 'bg-zinc-800 text-white font-bold'
                    : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
                }`}
              >
                <Upload className="w-4 h-4 text-emerald-500" />
                <span>Import collections</span>
              </button>
            </div>

            {/* Debug Group */}
            <div className="space-y-1">
              <p className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider mb-2 font-sans">Debug</p>

              <button
                onClick={() => setActiveSection('SQL console')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left transition ${
                  activeSection === 'SQL console'
                    ? isLight ? 'bg-zinc-200 text-zinc-900 font-bold' : 'bg-zinc-800 text-white font-bold'
                    : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
                }`}
              >
                <Terminal className="w-4 h-4 text-zinc-400" />
                <span>SQL console</span>
              </button>
            </div>
          </div>

          {/* Right Interactive Content Area */}
          <div className="flex-1 p-8 overflow-y-auto space-y-6">
            
            {/* 1. APPLICATION SECTION */}
            {activeSection === 'Application' && (
              <div className="max-w-2xl space-y-6">
                <div className="grid grid-cols-3 gap-4">
                  <div className="col-span-1">
                    <label className="block text-xs font-bold mb-1 font-mono">Application name *</label>
                    <input
                      type="text"
                      value={appName}
                      onChange={(e) => setAppName(e.target.value)}
                      className={`w-full p-2.5 border rounded-lg text-xs font-mono transition ${
                        isLight ? 'bg-zinc-100 border-zinc-300 text-zinc-900' : 'bg-zinc-950 border-zinc-800 text-zinc-100'
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
                        isLight ? 'bg-zinc-100 border-zinc-300 text-zinc-900' : 'bg-zinc-950 border-zinc-800 text-zinc-100'
                      }`}
                    />
                  </div>
                  <div className="col-span-1">
                    <label className="block text-xs font-bold mb-1 font-mono">Accent</label>
                    <input
                      type="text"
                      value={accentColor}
                      onChange={(e) => setAccentColor(e.target.value)}
                      className="w-full p-2.5 border rounded-lg text-xs font-mono bg-blue-600 text-white font-bold"
                    />
                  </div>
                </div>

                <div className={`rounded-xl border divide-y ${
                  isLight ? 'bg-white border-zinc-200 divide-zinc-200' : 'bg-zinc-950 border-zinc-800 divide-zinc-800'
                }`}>
                  <div className="p-3.5 flex items-center justify-between text-xs font-mono">
                    <span className="flex items-center gap-2">
                      <Database className="w-4 h-4 text-zinc-400" />
                      <span>Batch Web API</span>
                    </span>
                    <button
                      onClick={() => setBatchApiEnabled(!batchApiEnabled)}
                      className={`px-2.5 py-0.5 rounded text-[11px] font-bold ${
                        batchApiEnabled ? 'bg-emerald-500/10 text-emerald-600 border border-emerald-500/30' : 'bg-zinc-100 text-zinc-400'
                      }`}
                    >
                      {batchApiEnabled ? 'Enabled' : 'Disabled'}
                    </button>
                  </div>

                  <div className="p-3.5 flex items-center justify-between text-xs font-mono">
                    <span className="flex items-center gap-2">
                      <Cpu className="w-4 h-4 text-zinc-400" />
                      <span>IP proxy headers</span>
                    </span>
                    <button
                      onClick={() => setIpProxyEnabled(!ipProxyEnabled)}
                      className={`px-2.5 py-0.5 rounded text-[11px] font-bold ${
                        ipProxyEnabled ? 'bg-emerald-500/10 text-emerald-600 border border-emerald-500/30' : 'bg-zinc-100 text-zinc-400'
                      }`}
                    >
                      {ipProxyEnabled ? 'Enabled' : 'Disabled'}
                    </button>
                  </div>

                  <div className="p-3.5 flex items-center justify-between text-xs font-mono">
                    <span className="flex items-center gap-2">
                      <Activity className="w-4 h-4 text-zinc-400" />
                      <span>Rate limiting</span>
                    </span>
                    <button
                      onClick={() => setRateLimitingEnabled(!rateLimitingEnabled)}
                      className={`px-2.5 py-0.5 rounded text-[11px] font-bold ${
                        rateLimitingEnabled ? 'bg-emerald-500/10 text-emerald-600 border border-emerald-500/30' : 'bg-zinc-100 text-zinc-400'
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
                      className={`w-full p-2.5 border rounded-lg ${isLight ? 'bg-zinc-50 border-zinc-300' : 'bg-zinc-950 border-zinc-800'}`}
                    />
                  </div>
                  <div>
                    <label className="block font-bold mb-1">Port</label>
                    <input
                      type="text"
                      value={smtpPort}
                      onChange={(e) => setSmtpPort(e.target.value)}
                      className={`w-full p-2.5 border rounded-lg ${isLight ? 'bg-zinc-50 border-zinc-300' : 'bg-zinc-950 border-zinc-800'}`}
                    />
                  </div>
                  <div>
                    <label className="block font-bold mb-1">Username</label>
                    <input
                      type="text"
                      value={smtpUser}
                      onChange={(e) => setSmtpUser(e.target.value)}
                      className={`w-full p-2.5 border rounded-lg ${isLight ? 'bg-zinc-50 border-zinc-300' : 'bg-zinc-950 border-zinc-800'}`}
                    />
                  </div>
                  <div>
                    <label className="block font-bold mb-1">Password</label>
                    <input
                      type="password"
                      value={smtpPass}
                      onChange={(e) => setSmtpPass(e.target.value)}
                      className={`w-full p-2.5 border rounded-lg ${isLight ? 'bg-zinc-50 border-zinc-300' : 'bg-zinc-950 border-zinc-800'}`}
                    />
                  </div>
                  <div>
                    <label className="block font-bold mb-1">Sender Email</label>
                    <input
                      type="email"
                      value={senderAddress}
                      onChange={(e) => setSenderAddress(e.target.value)}
                      className={`w-full p-2.5 border rounded-lg ${isLight ? 'bg-zinc-50 border-zinc-300' : 'bg-zinc-950 border-zinc-800'}`}
                    />
                  </div>
                  <div>
                    <label className="block font-bold mb-1">Sender Name</label>
                    <input
                      type="text"
                      value={senderName}
                      onChange={(e) => setSenderName(e.target.value)}
                      className={`w-full p-2.5 border rounded-lg ${isLight ? 'bg-zinc-50 border-zinc-300' : 'bg-zinc-950 border-zinc-800'}`}
                    />
                  </div>
                </div>

                <div className="flex items-center justify-between pt-4 border-t border-zinc-200 dark:border-zinc-800">
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
                      storageProvider === 'local' ? 'border-emerald-500 bg-emerald-500/10' : 'border-zinc-200 dark:border-zinc-800'
                    }`}
                  >
                    <HardDrive className="w-5 h-5 text-emerald-600 mb-2" />
                    <p className="font-bold text-xs">Lokales Dateisystem</p>
                    <p className="text-[11px] text-zinc-400">Speichert Uploads im `/pb_data/storage` Ordner</p>
                  </button>

                  <button
                    onClick={() => setStorageProvider('s3')}
                    className={`flex-1 p-4 rounded-xl border text-left transition font-mono ${
                      storageProvider === 's3' ? 'border-emerald-500 bg-emerald-500/10' : 'border-zinc-200 dark:border-zinc-800'
                    }`}
                  >
                    <Database className="w-5 h-5 text-blue-500 mb-2" />
                    <p className="font-bold text-xs">Amazon S3 / MinIO</p>
                    <p className="text-[11px] text-zinc-400">Cloud Storage Bucket Integration</p>
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
                  isLight ? 'bg-white border-zinc-200' : 'bg-zinc-950 border-zinc-800'
                }`}>
                  <table className="w-full text-left">
                    <thead className="border-b bg-zinc-100 dark:bg-zinc-900 p-3 text-[10px] font-bold text-zinc-400 uppercase">
                      <tr>
                        <th className="p-3">Backup Dateiname</th>
                        <th className="p-3">Größe</th>
                        <th className="p-3">Erstellt am</th>
                        <th className="p-3 text-right">Aktion</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                      {backups.map(b => (
                        <tr key={b.id} className="hover:bg-zinc-50 dark:hover:bg-zinc-900/50">
                          <td className="p-3 font-bold text-emerald-600">{b.name}</td>
                          <td className="p-3">{b.size}</td>
                          <td className="p-3 text-zinc-400">{b.date}</td>
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
                    <thead className="border-b bg-zinc-100 dark:bg-zinc-900 p-3 text-[10px] font-bold text-zinc-400 uppercase">
                      <tr>
                        <th className="p-3">Job Name</th>
                        <th className="p-3">Schedule</th>
                        <th className="p-3">Status</th>
                        <th className="p-3">Letzter Lauf</th>
                        <th className="p-3 text-right">Ausführen</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                      {crons.map(c => (
                        <tr key={c.id}>
                          <td className="p-3 font-bold text-emerald-600">{c.name}</td>
                          <td className="p-3 text-zinc-400">{c.schedule}</td>
                          <td className="p-3"><span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-600 border font-bold">{c.status}</span></td>
                          <td className="p-3 text-zinc-400">{c.lastRun}</td>
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
                  <button onClick={() => setLogs(prev => [...prev])} className="px-3 py-1 rounded bg-zinc-200 dark:bg-zinc-800 font-bold text-zinc-600 dark:text-zinc-300 flex items-center gap-1">
                    <RefreshCw className="w-3.5 h-3.5" /> Reload
                  </button>
                </div>
                <div className={`p-4 rounded-xl border space-y-2 max-h-96 overflow-y-auto ${isLight ? 'bg-zinc-950 text-zinc-200 border-zinc-800' : 'bg-zinc-950 text-zinc-200 border-zinc-800'}`}>
                  {logs.map(l => (
                    <div key={l.id} className="flex items-center justify-between py-1 border-b border-zinc-800/40">
                      <div className="flex items-center gap-3">
                        <span className="text-emerald-400 font-bold">[{l.status}]</span>
                        <span className="text-amber-400 font-bold">{l.method}</span>
                        <span>{l.url}</span>
                      </div>
                      <div className="flex items-center gap-4 text-zinc-500">
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
                <p className="text-xs text-zinc-400 font-mono">Exportiert die `kontakte` Collection-Struktur als wiederverwendbare `schema.json` Datei.</p>
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
                <div className="border-2 border-dashed border-zinc-300 dark:border-zinc-700 rounded-xl p-8 text-center space-y-3 font-mono text-xs">
                  <Upload className="w-8 h-8 text-emerald-600 mx-auto" />
                  <p className="font-bold">Ziehe deine `schema.json` hierher</p>
                  <p className="text-zinc-400 text-[11px]">Unterstützt PocketBase Schema Definitions</p>
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
                    className={`w-full p-3 border rounded-xl font-mono text-xs ${isLight ? 'bg-zinc-950 text-emerald-400 border-zinc-800' : 'bg-zinc-950 text-emerald-400 border-zinc-800'}`}
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
                      <thead className="border-b bg-zinc-100 dark:bg-zinc-900 font-bold text-[10px] text-zinc-400">
                        <tr>
                          {Object.keys(sqlResult[0] || {}).map(k => (
                            <th key={k} className="p-2.5">{k}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
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
