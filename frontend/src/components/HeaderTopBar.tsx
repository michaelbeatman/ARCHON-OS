"use client";

import React from "react";
import { Server, Activity, Cpu, Layers } from "lucide-react";

interface HeaderTopBarProps {
  title?: string;
  activeView?: string;
}

export const HeaderTopBar: React.FC<HeaderTopBarProps> = ({
  title = "👥 Teambildung & Agenten-Choreografie",
  activeView = "Teambildung"
}) => {
  return (
    <header className="h-14 border-b border-zinc-800 bg-zinc-950/80 backdrop-blur px-5 flex items-center justify-between sticky top-0 z-50">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <Layers className="w-5 h-5 text-indigo-400" />
          <h1 className="text-sm font-bold tracking-tight text-zinc-100 font-mono">
            {title}
          </h1>
        </div>
        <span className="text-[11px] px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 font-mono">
          v2.0 Next.js Engine
        </span>
      </div>

      <div className="flex items-center gap-4 text-xs font-mono">
        <div className="flex items-center gap-1.5 text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-1 rounded">
          <Activity className="w-3.5 h-3.5 animate-pulse" />
          <span>Docker: Active</span>
        </div>

        <div className="flex items-center gap-1.5 text-zinc-400 bg-zinc-900 border border-zinc-800 px-2.5 py-1 rounded">
          <Server className="w-3.5 h-3.5 text-indigo-400" />
          <span>API: Port 8000 / 3000</span>
        </div>
      </div>
    </header>
  );
};
