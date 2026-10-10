"use client";

import React, { useState, useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  NodeProps,
  Handle,
  Position
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Search, Code2, Play, Image, Rocket, Layers, Cpu, Wrench, Shield, Check, Copy } from "lucide-react";

import { TriggerManagerModal, PREDEFINED_TRIGGERS, TriggerItem } from "./TriggerManagerModal";

// --- CUSTOM REACT FLOW NODE 0: TRIGGER NODE ---
const TriggerNode: React.FC<NodeProps> = ({ data }) => {
  return (
    <div className="bg-zinc-900 border-2 border-amber-500/80 rounded-xl p-4 w-72 shadow-xl shadow-amber-500/10 font-sans">
      <Handle type="source" position={Position.Right} className="w-3 h-3 bg-amber-500 border-2 border-zinc-950" />
      <div className="flex items-center justify-between border-b border-zinc-800 pb-2 mb-2">
        <div className="flex items-center gap-2">
          <span className="text-base">⚡</span>
          <span className="text-sm font-bold text-zinc-100">{String(data.label || "Trigger")}</span>
        </div>
        <span className="text-[10px] bg-amber-600/80 text-white px-2 py-0.5 rounded font-mono uppercase">
          TRIGGER
        </span>
      </div>

      <p className="text-[11px] text-zinc-400 mb-2">
        <b>Auslöser:</b> {String(data.condition || "Event Listener")}
      </p>
      <div className="text-[10px] text-amber-400 bg-zinc-950/80 p-2 rounded border border-zinc-800 font-mono">
        Status: Aktiv & Lauscht
      </div>
    </div>
  );
};

// --- CUSTOM REACT FLOW NODE 1: TEAM NODE ---
const TeamNode: React.FC<NodeProps> = ({ data }) => {
  return (
    <div className="bg-zinc-900 border-2 border-indigo-500 rounded-xl p-4 w-72 shadow-xl shadow-indigo-500/10 font-sans">
      <Handle type="target" position={Position.Left} className="w-3 h-3 bg-indigo-500 border-2 border-zinc-950" />
      <Handle type="source" position={Position.Right} className="w-3 h-3 bg-indigo-500 border-2 border-zinc-950" />
      <div className="flex items-center justify-between border-b border-zinc-800 pb-2 mb-2">
        <div className="flex items-center gap-2">
          <span className="text-base">👥</span>
          <span className="text-sm font-bold text-zinc-100">{String(data.label || "RoundRobin Team")}</span>
        </div>
        <span className="text-[10px] bg-indigo-600/80 text-white px-2 py-0.5 rounded font-mono uppercase">
          {String(data.typeTag || "team")}
        </span>
      </div>

      <p className="text-[11px] text-zinc-400 mb-3">
        {String(data.description || "RoundRobinGroupChat for active agents.")}
      </p>

      <div className="bg-zinc-950/80 p-2.5 rounded-lg border border-zinc-800 space-y-1">
        <div className="text-[10px] font-bold text-indigo-400 uppercase tracking-wider font-mono">
          CONNECTED AGENTS ({Array.isArray(data.members) ? data.members.length : 0})
        </div>
        <div className="text-xs font-semibold text-zinc-200 truncate">
          {Array.isArray(data.members) && data.members.length > 0
            ? data.members.join(", ")
            : "Hermes, OpenHands, GPT Researcher"}
        </div>
      </div>
    </div>
  );
};

// --- CUSTOM REACT FLOW NODE 2: AGENT NODE ---
const AgentNode: React.FC<NodeProps> = ({ data }) => {
  return (
    <div
      onClick={() => {
        const fn = (data as any).onSelectAgent;
        if (typeof fn === "function") fn((data as any).agentId);
      }}
      className="bg-zinc-900 border-2 border-emerald-500/80 hover:border-emerald-400 cursor-pointer transition rounded-xl p-4 w-72 shadow-xl shadow-emerald-500/10 font-sans group"
    >
      <Handle type="target" position={Position.Left} className="w-3 h-3 bg-emerald-500 border-2 border-zinc-950" />
      <div className="flex items-center justify-between border-b border-zinc-800 pb-2 mb-2">
        <div className="flex items-center gap-2">
          <span className="text-base">🤖</span>
          <span className="text-sm font-bold text-zinc-100 group-hover:text-emerald-400 transition">
            {String(data.label || "Agent")}
          </span>
        </div>
        <span className="text-[10px] bg-emerald-600/80 text-white px-2 py-0.5 rounded font-mono uppercase">
          agent
        </span>
      </div>

      <p className="text-[11px] text-zinc-400 mb-2">
        <b>Rolle:</b> {String(data.role || "Spezialist")}
      </p>

      <div className="space-y-1.5 font-mono">
        <div className="bg-zinc-950/80 px-2.5 py-1 rounded border border-zinc-800 flex items-center justify-between text-[11px]">
          <span className="text-[10px] text-emerald-400">MODEL</span>
          <span className="text-zinc-300 font-semibold">{String(data.model || "OmniRoute Free")}</span>
        </div>

        <div className="bg-zinc-950/80 px-2.5 py-1 rounded border border-zinc-800 flex items-center justify-between text-[11px]">
          <span className="text-[10px] text-rose-400">TOOLS</span>
          <span className="text-zinc-300 truncate max-w-[140px]">
            {Array.isArray(data.tools) ? data.tools.join(", ") : "FileSystem_MCP, Calculator"}
          </span>
        </div>
      </div>
      
      <div className="mt-2 pt-2 border-t border-zinc-800 text-[10px] text-emerald-400 font-mono text-right font-semibold">
        🖱️ Klicken für Agenten-Steuerung &rarr;
      </div>
    </div>
  );
};

const nodeTypes = {
  triggerNode: TriggerNode,
  teamNode: TeamNode,
  agentNode: AgentNode
};

interface Agent {
  id: string;
  name: string;
  role: string;
}

interface TeambildungFlowCanvasProps {
  agents: Agent[];
  onSelectAgentView?: (agentId: string) => void;
}


export const TeambildungFlowCanvas: React.FC<TeambildungFlowCanvasProps> = ({
  agents,
  onSelectAgentView
}) => {
  const [activeTab, setActiveTab] = useState<"builder" | "playground" | "gallery" | "deploy">("builder");
  const [viewJson, setViewJson] = useState(false);
  const [copied, setCopied] = useState(false);

  // Trigger State & Modal
  const [triggers, setTriggers] = useState<TriggerItem[]>(PREDEFINED_TRIGGERS);
  const [isTriggerModalOpen, setIsTriggerModalOpen] = useState(false);

  // Selected state
  const [selectedAgentIds, setSelectedAgentIds] = useState<string[]>(["hermes", "openhands", "gpt-researcher"]);
  const [selectedModel, setSelectedModel] = useState("OmniRoute Free");
  const [teamName, setTeamName] = useState("RoundRobin Team Alpha");
  const [searchFilter, setSearchFilter] = useState("");

  const filteredAgents = useMemo(() => {
    if (!searchFilter.trim()) return agents;
    return agents.filter(
      (a) =>
        a.name.toLowerCase().includes(searchFilter.toLowerCase()) ||
        a.role.toLowerCase().includes(searchFilter.toLowerCase())
    );
  }, [agents, searchFilter]);

  const selectedAgentsList = useMemo(() => {
    return agents.filter((a) => selectedAgentIds.includes(a.id));
  }, [agents, selectedAgentIds]);

  const toggleAgentSelect = (id: string) => {
    setSelectedAgentIds((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    );
  };

  // Dynamically compute React Flow Nodes & Edges
  const initialNodes = useMemo(() => {
    const nodes: any[] = [];

    // 1. Trigger Nodes on Left
    triggers.slice(0, 3).forEach((trig, idx) => {
      nodes.push({
        id: `trig-${trig.id}`,
        type: "triggerNode",
        position: { x: 30, y: 50 + idx * 150 },
        data: {
          label: trig.name,
          condition: trig.condition
        }
      });
    });

    // 2. Team Node in Middle
    nodes.push({
      id: "team-1",
      type: "teamNode",
      position: { x: 380, y: 150 },
      data: {
        label: teamName,
        typeTag: "team",
        description: "RoundRobinGroupChat for active agents.",
        members: selectedAgentsList.map((a) => a.name)
      }
    });

    // 3. Agent Nodes on Right
    selectedAgentsList.forEach((ag, idx) => {
      nodes.push({
        id: `agent-${ag.id}`,
        type: "agentNode",
        position: { x: 750, y: 40 + idx * 170 },
        data: {
          label: ag.name,
          role: ag.role,
          model: selectedModel,
          agentId: ag.id,
          onSelectAgent: onSelectAgentView,
          tools: ["FileSystem_MCP", "Calculator"]
        }
      });
    });

    return nodes;
  }, [teamName, selectedAgentsList, selectedModel, triggers, onSelectAgentView]);

  const initialEdges = useMemo(() => {
    const edges: any[] = [];

    // Connect Triggers to Team Node
    triggers.slice(0, 3).forEach((trig) => {
      edges.push({
        id: `edge-trig-${trig.id}-to-team`,
        source: `trig-${trig.id}`,
        target: "team-1",
        animated: true,
        style: { stroke: "#f59e0b", strokeWidth: 2 }
      });
    });

    // Connect Team Node to Agents
    selectedAgentsList.forEach((ag) => {
      edges.push({
        id: `edge-team-to-${ag.id}`,
        source: "team-1",
        target: `agent-${ag.id}`,
        animated: true,
        style: { stroke: "#10b981", strokeWidth: 2 }
      });
    });

    return edges;
  }, [triggers, selectedAgentsList]);


  // AutoGen Studio 1:1 JSON Schema
  const jsonSchema = useMemo(() => {
    return {
      provider: "autogen_agentchat.teams.RoundRobinGroupChat",
      component_type: "team",
      version: 1,
      label: teamName,
      config: {
        participants: selectedAgentsList.map((ag) => ({
          provider: "autogen_agentchat.agents.AssistantAgent",
          label: ag.name,
          config: {
            name: ag.id,
            role: ag.role,
            model_client: {
              provider: "autogen_ext.models.openai.OpenAIChatCompletionClient",
              config: {
                model: selectedModel.toLowerCase().replace(/\s+/g, "-"),
                base_url: "http://localhost:20128/v1"
              }
            },
            tools: ["FileSystem_MCP", "Calculator"]
          }
        })),
        termination_condition: {
          provider: "autogen_agentchat.conditions.OrTerminationCondition",
          "conditions": [
            { type: "MaxMessageTermination", max_messages: 10 },
            { type: "TextMentionTermination", text: "TERMINATE" }
          ]
        }
      }
    };
  }, [teamName, selectedAgentsList, selectedModel]);

  const handleCopyJson = () => {
    navigator.clipboard.writeText(JSON.stringify(jsonSchema, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="flex flex-col h-[calc(100vh-3.5rem)] bg-[#09090b] text-zinc-100 font-sans">
      {/* Top Header Control Sub-Bar */}
      <div className="px-5 py-2.5 border-b border-zinc-800 bg-zinc-950/60 flex items-center justify-between">
        <div className="flex items-center gap-4">
          {/* Main 4 Tabs */}
          <div className="flex items-center gap-1.5 bg-zinc-900/80 p-1 rounded-lg border border-zinc-800 text-xs font-semibold">
            <button
              onClick={() => setActiveTab("builder")}
              className={`flex items-center gap-1.5 px-3 py-1 rounded transition ${
                activeTab === "builder"
                  ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              🤖 Team Builder
            </button>
            <button
              onClick={() => setActiveTab("playground")}
              className={`flex items-center gap-1.5 px-3 py-1 rounded transition ${
                activeTab === "playground"
                  ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              💬 Playground
            </button>
            <button
              onClick={() => setActiveTab("gallery")}
              className={`flex items-center gap-1.5 px-3 py-1 rounded transition ${
                activeTab === "gallery"
                  ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              🖼️ Gallery
            </button>
            <button
              onClick={() => setActiveTab("deploy")}
              className={`flex items-center gap-1.5 px-3 py-1 rounded transition ${
                activeTab === "deploy"
                  ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              🚀 Deploy
            </button>
          </div>
          <span className="text-xs text-zinc-500 font-mono hidden md:inline">
            Teams &gt; {teamName}
          </span>
        </div>

        {/* View JSON & Trigger Button Right */}
        <div className="flex items-center gap-3">
          <button
            onClick={() => setIsTriggerModalOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1 bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/40 rounded-lg text-xs font-semibold font-mono transition"
          >
            <span>⚡ Trigger-Verwaltung</span>
            <span className="text-[10px] bg-amber-500/30 px-1.5 py-0.2 rounded">
              {triggers.length}
            </span>
          </button>

          <label className="flex items-center gap-2 cursor-pointer text-xs font-mono text-zinc-300">
            <span>View JSON</span>
            <input
              type="checkbox"
              checked={viewJson}
              onChange={(e) => setViewJson(e.target.checked)}
              className="w-4 h-4 rounded accent-indigo-500 cursor-pointer"
            />
          </label>
        </div>
      </div>

      {/* Main Tab Content */}
      {activeTab === "builder" && (
        <div className="flex-1 grid grid-cols-12 overflow-hidden">
          {/* LEFT PANEL: COMPONENT LIBRARY (28% Width = col-span-3) */}
          <div className="col-span-3 border-r border-zinc-800 bg-zinc-950/80 p-3.5 space-y-4 overflow-y-auto">
            <div>
              <h3 className="text-xs font-bold text-zinc-200 font-mono uppercase tracking-wider">
                Component Library
              </h3>
              <p className="text-[10px] text-zinc-400">Drag & Select components for team</p>
            </div>

            {/* Search Input */}
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-zinc-500 absolute left-2.5 top-2.5" />
              <input
                type="text"
                placeholder="Search components..."
                value={searchFilter}
                onChange={(e) => setSearchFilter(e.target.value)}
                className="w-full bg-zinc-900 border border-zinc-800 rounded pl-8 pr-3 py-1.5 text-xs text-zinc-200 focus:outline-none focus:border-indigo-500 font-sans"
              />
            </div>

            {/* Sub-Category 1: Agents */}
            <div className="border border-zinc-800/80 bg-zinc-900/40 rounded-lg p-3 space-y-2">
              <div className="flex items-center justify-between text-xs font-bold text-indigo-400">
                <span className="flex items-center gap-1.5">
                  <Layers className="w-3.5 h-3.5" /> Agents (Archon OS)
                </span>
                <span className="text-[10px] bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 px-1 rounded">
                  LIVE
                </span>
              </div>
              <div className="space-y-1.5 text-xs max-h-48 overflow-y-auto pr-1">
                {filteredAgents.map((ag) => (
                  <label
                    key={ag.id}
                    className="flex items-start gap-2 p-1.5 rounded hover:bg-zinc-900 cursor-pointer transition group"
                  >
                    <input
                      type="checkbox"
                      checked={selectedAgentIds.includes(ag.id)}
                      onChange={() => toggleAgentSelect(ag.id)}
                      className="mt-0.5 rounded accent-indigo-500"
                    />
                    <div>
                      <div className="font-semibold text-zinc-200 group-hover:text-indigo-300">
                        {ag.name}
                      </div>
                      <div className="text-[10px] text-zinc-400">{ag.role}</div>
                    </div>
                  </label>
                ))}
              </div>
            </div>

            {/* Sub-Category 2: Models */}
            <div className="border border-zinc-800/80 bg-zinc-900/40 rounded-lg p-3 space-y-2">
              <div className="text-xs font-bold text-indigo-400 flex items-center gap-1.5">
                <Cpu className="w-3.5 h-3.5" /> Models
              </div>
              <select
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                className="w-full bg-zinc-900 border border-zinc-800 rounded px-2.5 py-1.5 text-xs text-zinc-200 font-mono"
              >
                <option value="OmniRoute Free">OmniRoute / Free-Forever</option>
                <option value="DeepSeek V4 Flash">DeepSeek V4 Flash</option>
                <option value="Claude 3.5 Sonnet">Claude 3.5 Sonnet</option>
              </select>
            </div>

            {/* Sub-Category 3: Tools */}
            <div className="border border-zinc-800/80 bg-zinc-900/40 rounded-lg p-3 space-y-2">
              <div className="text-xs font-bold text-indigo-400 flex items-center gap-1.5">
                <Wrench className="w-3.5 h-3.5" /> Tools & MCP
              </div>
              <div className="space-y-1 text-xs">
                <label className="flex items-center gap-2 text-zinc-300">
                  <input type="checkbox" defaultChecked className="accent-indigo-500" />
                  <span>FileSystem MCP</span>
                </label>
                <label className="flex items-center gap-2 text-zinc-300">
                  <input type="checkbox" defaultChecked className="accent-indigo-500" />
                  <span>Calculator Tool</span>
                </label>
                <label className="flex items-center gap-2 text-zinc-300">
                  <input type="checkbox" className="accent-indigo-500" />
                  <span>WebSurfer Browser</span>
                </label>
              </div>
            </div>

            {/* Sub-Category 4: Terminations */}
            <div className="border border-zinc-800/80 bg-zinc-900/40 rounded-lg p-3 space-y-2">
              <div className="text-xs font-bold text-indigo-400 flex items-center gap-1.5">
                <Shield className="w-3.5 h-3.5" /> Terminations
              </div>
              <div className="space-y-1 text-xs text-zinc-300">
                <label className="flex items-center gap-2">
                  <input type="checkbox" defaultChecked className="accent-indigo-500" />
                  <span>TextMention ('TERMINATE')</span>
                </label>
                <label className="flex items-center gap-2">
                  <input type="checkbox" defaultChecked className="accent-indigo-500" />
                  <span>MaxMessage (10 Messages)</span>
                </label>
              </div>
            </div>
          </div>

          {/* RIGHT PANEL: INTERACTIVE CANVAS OR JSON VIEW (72% Width = col-span-9) */}
          <div className="col-span-9 flex flex-col h-full bg-[#09090b] relative">
            {viewJson ? (
              // 📄 JSON VIEW MODE (1:1 AutoGen Studio Schema)
              <div className="flex-1 p-5 overflow-auto bg-zinc-950 font-mono text-xs text-emerald-400 space-y-4">
                <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
                  <h3 className="text-sm font-bold text-zinc-100 flex items-center gap-2">
                    <Code2 className="w-4 h-4 text-emerald-400" />
                    AutoGen Studio JSON Configuration (1:1 Schema)
                  </h3>
                  <button
                    onClick={handleCopyJson}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs rounded transition"
                  >
                    {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                    <span>{copied ? "Copied!" : "Copy JSON"}</span>
                  </button>
                </div>
                <pre className="p-4 rounded-lg bg-zinc-900 border border-zinc-800 overflow-x-auto leading-relaxed">
                  {JSON.stringify(jsonSchema, null, 2)}
                </pre>
              </div>
            ) : (
              // 🎨 VISUAL BUILDER INTERACTIVE REACT FLOW CANVAS
              <div className="flex-1 relative w-full h-full">
                <ReactFlow
                  nodes={initialNodes}
                  edges={initialEdges}
                  nodeTypes={nodeTypes}
                  fitView
                  colorMode="dark"
                >
                  <Background variant={BackgroundVariant.Dots} gap={20} size={1.5} color="#334155" />
                  <Controls className="bg-zinc-900 border-zinc-800 fill-zinc-200 text-zinc-200" />
                  <MiniMap nodeColor="#6366f1" maskColor="rgba(15, 23, 42, 0.7)" className="bg-zinc-950 border-zinc-800" />
                </ReactFlow>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Other Tabs */}
      {activeTab === "playground" && (
        <div className="p-8 max-w-3xl space-y-4">
          <h2 className="text-lg font-bold text-zinc-100 flex items-center gap-2">
            <Play className="w-5 h-5 text-indigo-400" /> 💬 Team Execution Playground
          </h2>
          <p className="text-xs text-zinc-400">
            Sende Aufgaben an das aktive Team <b>{teamName}</b> ({selectedAgentsList.length} Mitglieder).
          </p>
          <textarea
            placeholder="z.B. Recherchiere die neusten KI-Trends und schreibe ein Python-Skript."
            className="w-full bg-zinc-900 border border-zinc-800 rounded-lg p-3 text-xs text-zinc-200 h-32 focus:outline-none focus:border-indigo-500"
          ></textarea>
          <button className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-xs rounded-lg transition shadow-lg shadow-indigo-600/30">
            ▶️ Aufruf an Team starten
          </button>
        </div>
      )}

      {activeTab === "gallery" && (
        <div className="p-8 max-w-3xl space-y-4">
          <h2 className="text-lg font-bold text-zinc-100 flex items-center gap-2">
            <Image className="w-5 h-5 text-indigo-400" /> 🖼️ Team Gallery & Presets
          </h2>
          <p className="text-xs text-zinc-400">Gespeicherte Team-Vorlagen und AutoGen Presets.</p>
        </div>
      )}

      {activeTab === "deploy" && (
        <div className="p-8 max-w-3xl space-y-4">
          <h2 className="text-lg font-bold text-zinc-100 flex items-center gap-2">
            <Rocket className="w-5 h-5 text-indigo-400" /> 🚀 Deployment & API Export
          </h2>
          <p className="text-xs text-zinc-400">
            Exportiere das Team <b>{teamName}</b> als REST-API Microservice.
          </p>
        </div>
      )}

      {/* Trigger Manager Modal */}
      <TriggerManagerModal
        isOpen={isTriggerModalOpen}
        onClose={() => setIsTriggerModalOpen(false)}
        triggers={triggers}
        onSaveTriggers={(updated) => setTriggers(updated)}
      />
    </div>
  );
};
