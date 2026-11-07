"use client";

import React, { useState } from "react";
import {
  Bot,
  MessageSquare,
  Wrench,
  FileText,
  Sliders,
  Play,
  ExternalLink,
  CheckCircle2,
  Cpu,
  RefreshCw,
  Send,
  Database,
  Layers
} from "lucide-react";

interface AgentItem {
  id: string;
  name: string;
  role: string;
  status?: string;
  skills?: string[];
  port?: number;
  url?: string;
}

const REGISTERED_AGENTS: AgentItem[] = [
  {
    id: "hermes",
    name: "Hermes Agent v0.20",
    role: "Strategie, Memory & System-Steuerung",
    status: "online",
    skills: ["Obsidian_MCP", "PocketBase_CRM_MCP", "FileSystem_MCP", "Groq_Whisper_STT"],
    port: 8787,
    url: "http://127.0.0.1:8787"
  },
  {
    id: "gpt-researcher",
    name: "GPT Researcher",
    role: "Tiefen-Recherche & Web Scraping",
    status: "online",
    skills: ["Google_Search", "Arxiv_Reader", "PDF_Parser"],
    port: 8000
  },
  {
    id: "openhands",
    name: "OpenHands Coder",
    role: "Entwicklung, Docker & Code-Refactoring",
    status: "ready",
    skills: ["Bash_Terminal", "Git_Worktree", "Node_Runner"],
    port: 3000
  },
  {
    id: "pocketbase-mcp",
    name: "PocketBase CRM Agent",
    role: "Kontakte, Verläufe & CSV-Import",
    status: "online",
    skills: ["PocketBase_DB", "Gmail_Sender", "LinkedIn_Scraper"],
    port: 8090,
    url: "http://127.0.0.1:8090"
  }
];

interface UnifiedAgentControlPanelProps {
  initialAgentId?: string;
}

export const UnifiedAgentControlPanel: React.FC<UnifiedAgentControlPanelProps> = ({
  initialAgentId = "hermes"
}) => {
  const [selectedAgentId, setSelectedAgentId] = useState(initialAgentId);
  const [activeTab, setActiveTab] = useState<"chat" | "skills" | "memory" | "logs">("chat");

  const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8501";

  // Chat state
  const [promptInput, setPromptInput] = useState("");
  const [messages, setMessages] = useState<Array<{ role: "user" | "agent"; text: string }>>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [sessionLoaded, setSessionLoaded] = useState(false);

  const activeAgent = REGISTERED_AGENTS.find((a) => a.id === selectedAgentId) || REGISTERED_AGENTS[0];

  // Load persistent session from backend when profile changes
  const loadSession = async (profileId: string) => {
    setSessionLoaded(false);
    try {
      const res = await fetch(`${API_BASE}/api/v1/quickchat/session/${profileId}`);
      if (res.ok) {
        const data = await res.json();
        const history = (data.messages || []).map((m: any) => ({
          role: m.role as "user" | "agent",
          text: m.text,
        }));
        if (history.length === 0) {
          setMessages([{
            role: "agent",
            text: `Hallo! Ich bin ${activeAgent.name}. Wie kann ich dir helfen?`
          }]);
        } else {
          setMessages(history);
        }
      }
    } catch {
      setMessages([{ role: "agent", text: "Hallo! Wie kann ich dir helfen?" }]);
    } finally {
      setSessionLoaded(true);
    }
  };

  // Load session on mount and on profile switch
  React.useEffect(() => {
    loadSession(selectedAgentId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAgentId]);

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!promptInput.trim() || isLoading) return;

    const userText = promptInput.trim();
    setMessages((prev) => [...prev, { role: "user", text: userText }]);
    setPromptInput("");
    setIsLoading(true);

    try {
      const res = await fetch(`${API_BASE}/api/v1/quickchat/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile_id: selectedAgentId, message: userText }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setMessages((prev) => [...prev, { role: "agent", text: data.reply }]);
    } catch (err: any) {
      setMessages((prev) => [
        ...prev,
        { role: "agent", text: `⚠ Verbindungsfehler: ${err.message}` },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-[#0b0f19] text-slate-100 font-sans">
      {/* Top Agent Selector Bar */}
      <div className="px-5 py-3 border-b border-slate-800 bg-slate-950/80 flex items-center justify-between gap-4">
        <div className="flex items-center gap-2 overflow-x-auto py-1">
          <span className="text-xs font-bold text-slate-500 font-mono uppercase mr-2">
            AGENTEN-AUSWAHL:
          </span>
          {REGISTERED_AGENTS.map((agent) => (
            <button
              key={agent.id}
              onClick={() => setSelectedAgentId(agent.id)}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition shrink-0 ${
                selectedAgentId === agent.id
                  ? "bg-indigo-600 text-white shadow-lg shadow-indigo-600/30 border border-indigo-500/40"
                  : "bg-slate-900/80 text-slate-400 border border-slate-800 hover:text-slate-200 hover:bg-slate-800"
              }`}
            >
              <Bot className="w-3.5 h-3.5" />
              <span>{agent.name}</span>
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  agent.status === "online" ? "bg-emerald-400 animate-pulse" : "bg-amber-400"
                }`}
              />
            </button>
          ))}
        </div>

        {/* External WebUI Link */}
        {activeAgent.url && (
          <a
            href={activeAgent.url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-900 hover:bg-slate-800 border border-slate-800 rounded-lg text-xs text-slate-300 transition shrink-0 font-mono"
          >
            <ExternalLink className="w-3.5 h-3.5 text-indigo-400" />
            <span>WebUI (:8787)</span>
          </a>
        )}
      </div>

      {/* Agent Info Banner */}
      <div className="px-6 py-3 border-b border-slate-800/80 bg-slate-950/40 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-bold text-slate-100 flex items-center gap-2">
            <Bot className="w-4 h-4 text-indigo-400" />
            <span>{activeAgent.name}</span>
            <span className="text-[10px] bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 px-2 py-0.5 rounded font-mono uppercase">
              {activeAgent.role}
            </span>
          </h2>
        </div>

        {/* Sub-Tabs */}
        <div className="flex items-center gap-1 bg-slate-900 p-1 rounded-lg border border-slate-800 text-xs font-semibold">
          <button
            onClick={() => setActiveTab("chat")}
            className={`flex items-center gap-1.5 px-3 py-1 rounded transition ${
              activeTab === "chat"
                ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <MessageSquare className="w-3.5 h-3.5" />
            <span>Chat & Live UI</span>
          </button>
          <button
            onClick={() => setActiveTab("skills")}
            className={`flex items-center gap-1.5 px-3 py-1 rounded transition ${
              activeTab === "skills"
                ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <Wrench className="w-3.5 h-3.5" />
            <span>Skills ({activeAgent.skills?.length || 0})</span>
          </button>
          <button
            onClick={() => setActiveTab("memory")}
            className={`flex items-center gap-1.5 px-3 py-1 rounded transition ${
              activeTab === "memory"
                ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <FileText className="w-3.5 h-3.5" />
            <span>Obsidian Memory</span>
          </button>
        </div>
      </div>

      {/* Main Tab View Content */}
      <div className="flex-1 overflow-hidden p-5">
        {activeTab === "chat" && (
          <div className="flex flex-col h-full bg-slate-950 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
            {/* Embed Frame or Integrated Chat */}
            {activeAgent.id === "hermes" ? (
              <iframe
                src="http://127.0.0.1:8787"
                title="Hermes WebUI"
                className="w-full h-full border-none bg-slate-950"
              />
            ) : (
              <div className="flex flex-col h-full">
                {/* Chat Messages Log */}
                <div className="flex-1 overflow-y-auto p-4 space-y-3 font-sans">
                  {messages.map((m, idx) => (
                    <div
                      key={idx}
                      className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
                    >
                      <div
                        className={`max-w-xl p-3 rounded-xl text-xs leading-relaxed ${
                          m.role === "user"
                            ? "bg-indigo-600 text-white font-medium shadow-md"
                            : "bg-slate-900 border border-slate-800 text-slate-200"
                        }`}
                      >
                        {m.text}
                      </div>
                    </div>
                  ))}
                </div>

                {/* Chat Prompt Input */}
                <form
                  onSubmit={handleSendMessage}
                  className="p-3 border-t border-slate-800 bg-slate-900/60 flex items-center gap-2"
                >
                  <input
                    type="text"
                    value={promptInput}
                    onChange={(e) => setPromptInput(e.target.value)}
                    disabled={isLoading}
                    placeholder={isLoading ? "Warte auf Antwort..." : `Nachricht an ${activeAgent.name}...`}
                    className="flex-1 px-4 py-2 bg-slate-950 border border-slate-800 rounded-xl text-xs text-slate-100 outline-none focus:border-indigo-500 font-sans disabled:opacity-50"
                  />
                  <button
                    type="submit"
                    disabled={isLoading || !promptInput.trim()}
                    className="p-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl shadow-lg shadow-indigo-600/30 transition disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isLoading ? (
                      <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                      </svg>
                    ) : (
                      <Send className="w-4 h-4" />
                    )}
                  </button>
                </form>
              </div>
            )}
          </div>
        )}

        {activeTab === "skills" && (
          <div className="p-6 bg-slate-950 border border-slate-800 rounded-2xl h-full overflow-y-auto space-y-4">
            <h3 className="text-xs font-bold text-slate-400 font-mono uppercase tracking-wider">
              Aktivierte MCP-Server & Skills für {activeAgent.name}
            </h3>

            <div className="grid grid-cols-2 gap-3">
              {activeAgent.skills?.map((sk, idx) => (
                <div
                  key={idx}
                  className="p-4 bg-slate-900 border border-slate-800 rounded-xl flex items-center justify-between"
                >
                  <div className="flex items-center gap-3">
                    <div className="p-2 rounded-lg bg-indigo-600/20 text-indigo-400 border border-indigo-500/30">
                      <Cpu className="w-4 h-4" />
                    </div>
                    <div>
                      <span className="text-xs font-bold text-slate-200">{sk}</span>
                      <p className="text-[10px] text-slate-400 font-mono">Status: Aktiv (Model-Connected)</p>
                    </div>
                  </div>
                  <span className="text-[10px] bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 px-2 py-0.5 rounded font-mono">
                    ONLINE
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {activeTab === "memory" && (
          <div className="p-6 bg-slate-950 border border-slate-800 rounded-2xl h-full overflow-y-auto space-y-4 font-sans">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-xs font-bold text-slate-200 font-mono uppercase flex items-center gap-2">
                <FileText className="w-4 h-4 text-purple-400" />
                <span>Obsidian Vault Binding (C:\Mein Obsidian)</span>
              </h3>
              <span className="text-[10px] text-purple-400 font-mono">SYNCHRONISIERT</span>
            </div>

            <div className="space-y-3 font-mono text-xs">
              <div className="p-3 bg-slate-900 border border-slate-800 rounded-xl space-y-1">
                <span className="font-bold text-slate-200">📄 bewerbungs-tracking-daten.md</span>
                <p className="text-[11px] text-slate-400">Automatische Erfassung aller Bewerbungsphasen.</p>
              </div>
              <div className="p-3 bg-slate-900 border border-slate-800 rounded-xl space-y-1">
                <span className="font-bold text-slate-200">📄 Bewerbungsprotokoll.md</span>
                <p className="text-[11px] text-slate-400">Protokolle & Notizen für Vorstellungsgespräche.</p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
