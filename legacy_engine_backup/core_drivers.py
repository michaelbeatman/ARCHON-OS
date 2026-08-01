import os
import re
import shutil
from typing import Dict, Any, List, Callable, Optional

# --- MCP Tool Manager mit dynamischem Parser ---
class MCPTool:
    def __init__(self, name: str, description: str, param_schemas: Dict[str, str]):
        """
        name: Name des Tools, z.B. mcp__filesystem__write_file
        description: Beschreibung des Tools
        param_schemas: Map von Parameternamen auf Regex-Muster zur Validierung
        """
        self.name = name
        self.description = description
        self.param_schemas = param_schemas

    def validate_args(self, args: Dict[str, Any]) -> bool:
        """
        Validiert die übergebenen Argumente gegen die Regex-Muster.
        Hebt einen ValueError bei Fehlern.
        """
        for param, pattern in self.param_schemas.items():
            if param not in args:
                raise ValueError(f"Missing required parameter '{param}' for tool '{self.name}'.")
            
            val = str(args[param])
            if not re.match(pattern, val, re.DOTALL):
                raise ValueError(
                    f"Parameter '{param}' with value '{val}' does not match the required format: {pattern}"
                )
        return True


class MCPRegistry:
    def __init__(self):
        self.tools: Dict[str, MCPTool] = {}
        self.callbacks: Dict[str, Callable] = {}

    def register_tool(self, tool: MCPTool, callback: Callable):
        self.tools[tool.name] = tool
        self.callbacks[tool.name] = callback
        print(f"[MCP Driver] Registered tool '{tool.name}'")

    def load_from_manifest(self, manifest_content: str, server_name: str) -> List[str]:
        """
        Parst dynamisch eine SERVER.md Struktur und registriert die Tools.
        """
        registered = []
        # Finde Tool-Blöcke (z.B. ## Tool: name)
        tool_blocks = manifest_content.split("## Tool: ")
        # Der erste Split ist Header-Info vor dem ersten Tool
        for block in tool_blocks[1:]:
            lines = block.strip().split("\n")
            if not lines:
                continue
            
            tool_name = lines[0].strip()
            # Falls der Name nicht voll qualifiziert ist, ergänze das Schema
            if not tool_name.startswith("mcp__"):
                tool_name = f"mcp__{server_name}__{tool_name}"

            description = ""
            param_schemas = {}
            
            in_params = False
            for line in lines[1:]:
                line = line.strip()
                if line.startswith("Description:"):
                    description = line.replace("Description:", "").strip()
                elif line.startswith("Parameters:"):
                    in_params = True
                elif in_params and line.startswith("-"):
                    # Parameter-Zeile, z.B.: "- path: Regex: `^[a-zA-Z0-9_\-\.\/\\:]+$`"
                    line_content = line.lstrip("- ").strip()
                    if ":" in line_content:
                        p_name, rest = line_content.split(":", 1)
                        p_name = p_name.strip()
                        if "Regex:" in rest:
                            # Extrahiere das Regex-Muster zwischen Backticks
                            regex_match = re.search(r"`(.*)`", rest)
                            if regex_match:
                                pattern = regex_match.group(1)
                                param_schemas[p_name] = pattern
                            else:
                                param_schemas[p_name] = ".*"
                        else:
                            param_schemas[p_name] = ".*"

            tool = MCPTool(tool_name, description, param_schemas)
            # Standard-Dummy-Callback falls nicht explizit überschrieben
            def make_dummy(name):
                return lambda **kwargs: {"status": "success", "tool": name, "args": kwargs}
                
            self.register_tool(tool, make_dummy(tool_name))
            registered.append(tool_name)
            
        return registered

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        if tool_name not in self.tools:
            raise KeyError(f"Tool '{tool_name}' ist nicht registriert.")
            
        tool = self.tools[tool_name]
        # Regex Validierung ausführen
        tool.validate_args(args)
        
        callback = self.callbacks[tool_name]
        return callback(**args)


# --- BranchFS (Copy-on-Write Sandboxing) ---
class BranchFS:
    def __init__(self, base_dir: str, branch_id: str):
        self.base_dir = os.path.abspath(base_dir)
        self.branch_id = branch_id
        # Der Delta-Layer-Pfad
        self.delta_dir = os.path.abspath(
            os.path.join(self.base_dir, "agent_workspace", "sandbox", f"branch_{branch_id}")
        )
        os.makedirs(self.delta_dir, exist_ok=True)

    def _get_base_path(self, relative_path: str) -> str:
        return os.path.abspath(os.path.join(self.base_dir, relative_path))

    def _get_delta_path(self, relative_path: str) -> str:
        return os.path.abspath(os.path.join(self.delta_dir, relative_path))

    def read_file(self, relative_path: str) -> str:
        """
        Liest eine Datei aus. Priorisiert den Delta-Layer, fällt sonst auf das Basisverzeichnis zurück.
        """
        delta_path = self._get_delta_path(relative_path)
        base_path = self._get_base_path(relative_path)

        # Sicherheitscheck gegen Path Traversal
        if not delta_path.startswith(self.delta_dir):
            raise PermissionError("Path traversal attack detected.")
            
        if os.path.exists(delta_path):
            with open(delta_path, "r", encoding="utf-8") as f:
                return f.read()
        elif os.path.exists(base_path):
            with open(base_path, "r", encoding="utf-8") as f:
                return f.read()
        else:
            raise FileNotFoundError(f"Datei '{relative_path}' konnte weder im Sandbox- noch im Hauptordner gefunden werden.")

    def write_file(self, relative_path: str, content: str):
        """
        Schreibt Änderungen ausschließlich in den Delta-Layer der Sandbox.
        """
        delta_path = self._get_delta_path(relative_path)
        if not delta_path.startswith(self.delta_dir):
            raise PermissionError("Path traversal attack detected.")

        # Stelle sicher, dass die Subverzeichnisse im Delta-Layer existieren
        os.makedirs(os.path.dirname(delta_path), exist_ok=True)
        with open(delta_path, "w", encoding="utf-8") as f:
            f.write(content)

    def exists(self, relative_path: str) -> bool:
        delta_path = self._get_delta_path(relative_path)
        base_path = self._get_base_path(relative_path)
        return os.path.exists(delta_path) or os.path.exists(base_path)

    def commit(self):
        """
        Überträgt alle Änderungen aus dem Delta-Layer atomar in das Hauptverzeichnis und räumt auf.
        """
        if not os.path.exists(self.delta_dir):
            return

        # Durchsuche alle Dateien im Delta-Layer und kopiere sie ins Basisverzeichnis
        for root, _, files in os.walk(self.delta_dir):
            for file in files:
                delta_file_path = os.path.join(root, file)
                rel_path = os.path.relpath(delta_file_path, self.delta_dir)
                base_file_path = self._get_base_path(rel_path)

                os.makedirs(os.path.dirname(base_file_path), exist_ok=True)
                shutil.copy2(delta_file_path, base_file_path)

        self.abort()  # Delta-Layer nach Commit löschen

    def abort(self):
        """
        Verwirft alle Änderungen des Delta-Layers und löscht die Sandbox.
        """
        if os.path.exists(self.delta_dir):
            shutil.rmtree(self.delta_dir)
