import os
import json
import asyncio
from typing import Dict, Any, List, Optional, AsyncIterator
from pydantic import BaseModel, Field
import yaml

# --- 1. Agent Contract Schema ---

class AgentContract(BaseModel):
    agent_id: str
    name: str
    prompt_templates: Dict[str, str] = Field(default_factory=dict) # e.g. {"system": "...", "user": "..."}
    tool_schema_scopes: List[str] = Field(default_factory=list) # e.g. ["mcp__file_manager__read_file"]
    model_routing_policies: Dict[str, Any] = Field(default_factory=dict) # e.g. {"data_residency": "local"}
    token_cost_budgets: Dict[str, Any] = Field(default_factory=dict) # e.g. {"max_tokens": 10000}

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    def to_yaml(self) -> str:
        return yaml.dump(self.model_dump(), sort_keys=False)

    @classmethod
    def from_json(cls, json_str: str) -> "AgentContract":
        return cls(**json.loads(json_str))

    @classmethod
    def from_yaml(cls, yaml_str: str) -> "AgentContract":
        return cls(**yaml.safe_load(yaml_str))


# --- 2. Unified Driver Abstraction Layer ---

class UnifiedDriverTranslation:
    # Standard-Mappings von Framework-Toolnamen zu AOS-MCP-Namen
    TOOL_MAPPING = {
        "read_file": "mcp__file_manager__read_file",
        "write_file": "mcp__file_manager__write_file",
        "delete_file": "mcp__file_manager__delete_file",
        "execute_command": "mcp__terminal__run_command"
    }

    @classmethod
    def translate_anthropic_tool_call(cls, tool_use: Dict[str, Any]) -> Dict[str, Any]:
        """
        Übersetzt Anthropic-Format:
        {"id": "toolu_1", "type": "tool_use", "name": "read_file", "input": {"path": "test.txt"}}
        in AOS-Format:
        {"name": "mcp__file_manager__read_file", "parameters": {"path": "test.txt"}}
        """
        raw_name = tool_use.get("name", "")
        translated_name = cls.TOOL_MAPPING.get(raw_name, f"mcp__unknown__{raw_name}")
        parameters = tool_use.get("input", {})
        
        return {
            "name": translated_name,
            "parameters": parameters
        }

    @classmethod
    def translate_openai_tool_call(cls, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """
        Übersetzt OpenAI-Format:
        {"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": "{\"path\": \"test.txt\"}"}}
        in AOS-Format:
        {"name": "mcp__file_manager__read_file", "parameters": {"path": "test.txt"}}
        """
        func_block = tool_call.get("function", {})
        raw_name = func_block.get("name", "")
        translated_name = cls.TOOL_MAPPING.get(raw_name, f"mcp__unknown__{raw_name}")
        
        args_str = func_block.get("arguments", "{}")
        try:
            parameters = json.loads(args_str) if isinstance(args_str, str) else args_str
        except Exception:
            parameters = {}

        return {
            "name": translated_name,
            "parameters": parameters
        }


# --- 3. Client-API Binder ---

class AOSAgent:
    def __init__(self, contract: AgentContract, storage_path: str):
        self.contract = contract
        self.storage_path = storage_path
        
        # CoreStorage verzögert laden, um Kreis-Importe zu vermeiden
        from core_storage import CoreStorage
        self.storage = CoreStorage(storage_path)

    @classmethod
    def spawn(cls, contract: AgentContract, storage_path: str = "agent_os.db") -> "AOSAgent":
        """
        Startet eine isolierte Agenten-Instanz über den Kernel.
        """
        agent = cls(contract, storage_path)
        
        # Task in DB registrieren, damit Scheduler Loop ihn ausführt
        import time
        task_id = f"task_{contract.agent_id}_{int(time.time())}"
        
        # Konfiguriere Task-Payload
        payload = {
            "prompt": contract.prompt_templates.get("system", "Execute Agent Task"),
            "routing_policy": contract.model_routing_policies,
            "token_budget": contract.token_cost_budgets,
            "duration": 1.0 # 1s Ausführungszeit für Tests
        }
        
        agent.storage.save_task(
            task_id=task_id,
            agent_id=contract.agent_id,
            status="pending",
            payload=payload
        )
        
        print(f"[AOSAgent] Spawned agent instance '{contract.name}' under task '{task_id}'.")
        return agent

    async def stream_results(self, task_id: str) -> AsyncIterator[Dict[str, Any]]:
        """
        Asynchroner Iterator (Generator), der den Status eines ausgeführten Tasks streamt.
        """
        finished = False
        while not finished:
            task_data = self.storage.get_task(task_id)
            if not task_data:
                yield {"status": "not_found", "task_id": task_id}
                break

            status = task_data["status"]
            result = task_data.get("result")
            
            yield {
                "task_id": task_id,
                "status": status,
                "result": result,
                "updated_at": task_data.get("updated_at")
            }

            if status in ("completed", "failed"):
                finished = True
            else:
                await asyncio.sleep(0.2)
