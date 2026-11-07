"use client";

import React, { useState } from "react";
import { 
  Bot, 
  MessageSquare, 
  Users, 
  Terminal, 
  Settings, 
  LayoutGrid, 
  Cpu, 
  Boxes,
  Compass,
  Clapperboard,
  Settings2,
  Radar
} from "lucide-react";
import { GatewayManagerModal } from "./GatewayManagerModal";
import { WatchdogModal } from "./WatchdogModal";

interface SidebarNavProps {
  currentView: string;
  onSelectView: (view: string) => void;
  agentsList: Array<{ id: string; name: string; role: string }>;
}

export const SidebarNav: React.FC<SidebarNavProps> = ({
  currentView,
  onSelectView,
  agentsList
}) => {
  const [gatewayManagerOpen, setGatewayManagerOpen] = useState(false);
  const [watchdogModalOpen, setWatchdogModalOpen] = useState(false);
  const [runningGatewayCount, setRunningGatewayCount] = useState<number | null>(null);

  // Fetch running gateway count on mount (non-blocking, best-effort)
  React.useEffect(() => {
    const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8501";
    fetch(`${apiBase}/api/v1/gateway/list`)
      .then((r) => r.json())
      .then((d) => {
        const count = (d.profiles || []).filter((p: any) => p.status === "running").length;
        setRunningGatewayCount(count);
      })
      .catch(() => {});
  }, []);

  return (
    <>
      <GatewayManagerModal
        isOpen={gatewayManagerOpen}
        onClose={() => { setGatewayManagerOpen(false); }}
      />
      <WatchdogModal
        isOpen={watchdogModalOpen}
        onClose={() => { setWatchdogModalOpen(false); }}
      />

      <aside className="w-64 border-r border-slate-800 bg-slate-950 flex flex-col h-screen shrink-0">
      {/* Brand Header */}
      <div className="p-4 border-b border-slate-800 flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-emerald-500 flex items-center justify-center font-bold text-white shadow-lg shadow-indigo-500/20">
          🏛️
        </div>
        <div>
          <h2 className="text-sm font-bold tracking-tight text-slate-100 font-mono">ARCHON OS</h2>
          <p className="text-[10px] text-slate-400 font-mono">Agentic Operating System</p>
        </div>
      </div>

      {/* Nav Content */}
      <div className="flex-1 overflow-y-auto p-3 space-y-6 text-xs">
        {/* 1. WORKSPACE */}
        <div>
          <div className="text-[10px] font-bold text-slate-500 tracking-wider font-mono mb-2 px-2 uppercase">
            1. WORKSPACE
          </div>
          <button
            onClick={() => onSelectView("Mission Control")}
            className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-md font-medium transition ${
              currentView === "Mission Control"
                ? "bg-indigo-600/20 text-indigo-400 border border-indigo-500/30"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-900"
            }`}
          >
            <Compass className="w-4 h-4" />
            <span>Mission Control</span>
          </button>
        </div>

        {/* 2. ARRANGEMENT */}
        <div>
          <div className="text-[10px] font-bold text-slate-500 tracking-wider font-mono mb-2 px-2 uppercase">
            2. ARRANGEMENT
          </div>
          <div className="space-y-1">
            <button
              onClick={() => onSelectView("💬 Master Chat")}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-md font-medium transition ${
                currentView === "💬 Master Chat"
                  ? "bg-indigo-600/20 text-indigo-400 border border-indigo-500/30"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-900"
              }`}
            >
              <MessageSquare className="w-4 h-4 text-sky-400" />
              <span>💬 Master Chat</span>
            </button>

            <button
              onClick={() => onSelectView("📇 PocketBase CRM")}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-md font-medium transition ${
                currentView === "📇 PocketBase CRM"
                  ? "bg-indigo-600/20 text-indigo-400 border border-indigo-500/30"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-900"
              }`}
            >
              <Users className="w-4 h-4 text-teal-400" />
              <span className="font-semibold text-slate-100">📇 PocketBase CRM</span>
              <span className="ml-auto text-[9px] bg-teal-500/20 text-teal-300 border border-teal-500/30 px-1.5 py-0.5 rounded font-mono">CRM</span>
            </button>

            <button
              onClick={() => onSelectView("Paperclip Orchestrator")}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-md font-medium transition ${
                currentView === "Paperclip Orchestrator"
                  ? "bg-indigo-600/20 text-indigo-400 border border-indigo-500/30"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-900"
              }`}
            >
              <Boxes className="w-4 h-4 text-purple-400" />
              <span>Paperclip Orchestrator</span>
            </button>

            <button
              onClick={() => onSelectView("Content Studio")}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-md font-medium transition ${
                currentView === "Content Studio"
                  ? "bg-slate-800 text-slate-100 border border-slate-700 font-bold"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-900"
              }`}
            >
              <Clapperboard className="w-4 h-4 text-slate-400" />
              <span>Content Studio</span>
            </button>
          </div>
        </div>

        {/* 3. AGENTS */}
        <div>
          <div className="text-[10px] font-bold text-slate-500 tracking-wider font-mono mb-2 px-2 uppercase flex items-center justify-between">
            <span>3. REGISTERED AGENTS</span>
            <span className="text-[9px] text-emerald-400">{agentsList.length} LIVE</span>
          </div>
          <div className="space-y-1.5">
            {agentsList.slice(0, 6).map((ag) => (
              <div
                key={ag.id}
                className="p-2 rounded bg-slate-900/60 border border-slate-800/80 hover:border-slate-700 transition"
              >
                <div className="flex items-center justify-between text-slate-200 font-semibold text-[11px]">
                  <span className="flex items-center gap-1.5">
                    <Bot className="w-3.5 h-3.5 text-indigo-400" />
                    {ag.name}
                  </span>
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                </div>
                <div className="text-[10px] text-slate-400 truncate mt-0.5 pl-5">
                  {ag.role}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="p-3 border-t border-slate-800 text-[10px] text-slate-500 font-mono flex items-center justify-between">
        <span>Archon OS v2.0</span>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setWatchdogModalOpen(true)}
            title="Internet-Watchdog (Autonomer Web-Radar)"
            className="p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-cyan-400 transition"
          >
            <Radar className="w-3.5 h-3.5 text-cyan-400" />
          </button>
          <button
            onClick={() => setGatewayManagerOpen(true)}
            title="Gateway Manager"
            className="p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-indigo-400 transition"
          >
            <Settings2 className="w-3.5 h-3.5" />
          </button>
          <span className="text-emerald-400">
            ● {runningGatewayCount !== null ? `${runningGatewayCount} GW` : "aktiv"}
          </span>
        </div>
      </div>
    </aside>
    </>
  );
};
