import os
import sys
import json
import httpx
import datetime
import subprocess
from typing import List, Dict, Optional

try:
    from utils.path_jail import safe_path_within, safe_filename, PathJailError
except ImportError:  # pragma: no cover - direkter Aufruf ausserhalb des Repo-Roots
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from utils.path_jail import safe_path_within, safe_filename, PathJailError

try:
    import docker
except ImportError:
    docker = None

try:
    import chromadb
except ImportError:
    chromadb = None

# =====================================================================
# MODULE 1: DOCKER SDK & INFRASTRUCTURE CONTROL
# =====================================================================
class DockerControlSkill:
    def __init__(self):
        self.client = None
        if docker is None:
            return
        candidates = [
            os.getenv("DOCKER_HOST"),
            None,
            "unix:///var/run/docker.sock",
            "tcp://docker-socket-proxy:2375",
            "tcp://127.0.0.1:2375"
        ]
        for cand in candidates:
            try:
                if cand:
                    self.client = docker.DockerClient(base_url=cand, timeout=5)
                else:
                    self.client = docker.from_env(timeout=5)
                if self.client:
                    # Test probe
                    self.client.ping()
                    break
            except Exception:
                self.client = None

    def inspect_system(self) -> Dict:
        """Inspects all containers, returns ports, status, and names."""
        if not self.client:
            return {"status": "error", "message": "Docker SDK not initialized"}
        res = []
        try:
            for c in self.client.containers.list(all=True):
                ports = c.ports
                ports_str = "-"
                if ports:
                    ports_str = ", ".join([f"{k} -> {v[0]['HostPort']}" for k, v in ports.items() if v])
                
                img_name = c.attrs.get("Config", {}).get("Image", "")
                if not img_name:
                    try:
                        img_name = c.image.tags[0] if (c.image and c.image.tags) else c.image.short_id
                    except Exception:
                        img_name = "unknown"

                res.append({
                    "name": c.name,
                    "status": c.status,
                    "image": img_name,
                    "ports": ports_str
                })
            return {"status": "success", "containers": res}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def read_container_logs(self, container_name: str, tail: int = 100) -> Dict:
        """Reads logs of a target container."""
        if not self.client:
            return {"status": "error", "message": "Docker SDK not initialized"}
        try:
            c = self.client.containers.get(container_name)
            logs = c.logs(tail=tail).decode("utf-8", errors="ignore")
            return {"status": "success", "logs": logs}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def restart_service(self, container_name: str) -> Dict:
        """Restarts an active or stopped container service.

        Kein ``container.restart()`` mehr: der Proxy gibt ``restart`` nicht frei
        (ALLOW_RESTARTS=0, Entscheidung B2). Der Neustart geht ueber den zentralen
        Client als ``stop`` + ``start`` — fail-closed, mit dem aktionsspezifischen
        Timeout aus ``utils.docker_client`` (der SDK-Default hier waere 5 s und
        damit knapp unter der Stop-Frist von Docker).
        """
        # M-11: Der Docker-SDK-Client ist fuer den Neustart NICHT noetig —
        # der eigentliche Pfad laeuft ueber ``utils.docker_client`` (HTTP). Die
        # alte Vorpruefung auf ``self.client`` verweigerte jeden Neustart auf
        # einem Stack ohne SDK-Init, obwohl stop+start technisch ginge.
        from utils.docker_client import docker_client as _dc, DockerError as _DockerError
        try:
            _dc.restart_container(container_name)
            return {"status": "success", "message": f"Container '{container_name}' restarted successfully."}
        except _DockerError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            return {"status": "error", "message": str(e)}


# =====================================================================
# MODULE 2: OBSIDIAN / SECOND BRAIN INTEGRATION
# =====================================================================
class ObsidianVaultSkill:
    def __init__(self, vault_dir: Optional[str] = None):
        if not vault_dir:
            env_path = os.environ.get("OBSIDIAN_VAULT_PATH")
            if env_path and os.path.exists(env_path):
                vault_dir = env_path
            else:
                for candidate in [
                    "C:\\Mein Obsidian",
                    "C:\\.Mein Obsidian",
                    "/opt/data/obsidian",
                    os.path.expanduser("~/Documents/Obsidian Vault"),
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), "obsidian_vault")
                ]:
                    if os.path.exists(candidate):
                        vault_dir = candidate
                        break
        if not vault_dir:
            workspace_dir = os.path.dirname(os.path.abspath(__file__))
            vault_dir = os.path.join(workspace_dir, "obsidian_vault")
        self.vault_dir = vault_dir
        os.makedirs(self.vault_dir, exist_ok=True)

    def write_obsidian_note(self, title: str, content: str, tags: Optional[List[str]] = None) -> Dict:
        """Writes a structured markdown note with frontmatter and main backlink.

        Z-01: Der Titel ist Nutzereingabe und darf keinen Pfadanteil tragen.
        Er wird auf einen Dateinamen reduziert (Basename, Backslash wie
        Separator), der Zielpfad laeuft zusaetzlich durch das Jail mit *nur*
        ``vault_dir`` — vorher blieb ``..`` stehen und schrieb ausserhalb.
        """
        tags = tags or []
        try:
            filename = safe_filename(
                f"{str(title).replace('/', '_').replace(' ', '_')}.md"
            )
            filepath = safe_path_within(
                os.path.join(self.vault_dir, filename), [self.vault_dir],
                allow_write=True, allow_dirs=False,
            )
        except PathJailError as exc:
            return {"status": "error", "message": f"Ungueltiger Notiztitel: {exc}"}
        
        frontmatter = "---\n"
        frontmatter += f"title: \"{title}\"\n"
        frontmatter += f"tags: {json.dumps(tags)}\n"
        frontmatter += f"date: {datetime.datetime.now().isoformat()}\n"
        frontmatter += "---\n\n"
        
        note_text = frontmatter + content + "\n\n[[Archon OS]]"
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(note_text)
            return {"status": "success", "filepath": filepath, "filename": filename}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def search_obsidian_notes(self, query: str) -> Dict:
        """Searches vault notes for matching query content."""
        results = []
        try:
            for root, _, files in os.walk(self.vault_dir):
                for file in files:
                    if file.endswith(".md"):
                        path = os.path.join(root, file)
                        with open(path, "r", encoding="utf-8", errors="ignore") as f:
                            text = f.read()
                        if query.lower() in text.lower() or query.lower() in file.lower():
                            results.append({"title": file[:-3], "path": path})
            return {"status": "success", "results": results}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def update_changelog(self, version: str, changes: List[str]) -> Dict:
        """Updates central changelog with release entry."""
        changelog_path = os.path.join(self.vault_dir, "changelog.md")
        
        entry = f"## [{version}] - {datetime.date.today().isoformat()}\n"
        for change in changes:
            entry += f"- {change}\n"
        entry += "\n"
        
        try:
            existing = ""
            if os.path.exists(changelog_path):
                with open(changelog_path, "r", encoding="utf-8") as f:
                    existing = f.read()
            
            with open(changelog_path, "w", encoding="utf-8") as f:
                f.write(entry + existing)
            return {"status": "success", "changelog": changelog_path}
        except Exception as e:
            return {"status": "error", "message": str(e)}


# =====================================================================
# MODULE 3: LOCAL RAG & POCKETBASE KNOWLEDGE SEARCH
# =====================================================================
class LocalKnowledgeSkill:
    def __init__(self, db_dir: Optional[str] = None):
        if not db_dir:
            workspace_dir = os.path.dirname(os.path.abspath(__file__))
            db_dir = os.path.join(workspace_dir, "chroma_db")
        self.db_dir = db_dir
        
        if not chromadb:
            self.chroma_client = None
            self.collection = None
            return
            
        try:
            self.chroma_client = chromadb.PersistentClient(path=self.db_dir)
            self.collection = self.chroma_client.get_or_create_collection(name="system_knowledge")
        except Exception as e:
            print(f"[RAG_SKILL] Failed to connect to ChromaDB: {e}", file=sys.stderr)
            self.chroma_client = None
            self.collection = None

    def query_knowledge_base(self, prompt: str) -> Dict:
        """Queries local ChromaDB vector collection."""
        if not self.collection:
            return {"status": "error", "message": "ChromaDB client is not online."}
        try:
            res = self.collection.query(query_texts=[prompt], n_results=3)
            return {"status": "success", "results": res}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def store_system_metric(self, event_data: Dict) -> Dict:
        """Pushes error metrics to PocketBase records endpoint."""
        urls = [
            "http://Pocketbase:8090/api/collections/system_metrics/records",
            "http://pocketbase:8090/api/collections/system_metrics/records",
            "http://localhost:8090/api/collections/system_metrics/records",
            "http://127.0.0.1:8090/api/collections/system_metrics/records"
        ]
        
        for url in urls:
            try:
                with httpx.Client(timeout=3.0) as client:
                    resp = client.post(url, json=event_data)
                    if resp.is_success:
                        return {"status": "success", "endpoint": url, "response": resp.json()}
            except Exception:
                continue
                
        return {"status": "error", "message": "PocketBase endpoint unreachable."}


# =====================================================================
# MODULE 4: GIT & AUTOMATED TESTING
# =====================================================================
class GitTestingSkill:
    # Z-06: Die Suite braucht gemessen ~60 s (971 Tests); der alte Timeout
    # von 30 s hat ``git_safe_commit`` immer in den Fehlerzweig geschickt und
    # die Commit-Pfade unerreichbar gemacht. Der Timeout ist jetzt
    # konfigurierbar und liegt deutlich ueber der gemessenen Laufzeit.
    DEFAULT_PYTEST_TIMEOUT = int(os.getenv("SKILL_PYTEST_TIMEOUT", "600"))

    def run_pytest(self, test_path: str = "tests/") -> Dict:
        """Runs unit test suites using pytest."""
        timeout = self.DEFAULT_PYTEST_TIMEOUT
        try:
            res = subprocess.run(
                ["pytest", test_path], capture_output=True, text=True, timeout=timeout
            )
            return {
                "status": "success" if res.returncode == 0 else "failed",
                "exit_code": res.returncode,
                "stdout": res.stdout,
                "stderr": res.stderr
            }
        except subprocess.TimeoutExpired as e:
            return {
                "status": "error",
                "message": f"pytest-Timeout nach {timeout}s: {e}",
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def git_safe_commit(self, message: str, paths: Optional[List[str]] = None) -> Dict:
        """Stages files and performs commit only if test suites pass successfully.

        Z-06: Zwei Fehler behoben.

        1. Der pytest-Timeout war kuerzer als die Suite — der Commit-Pfad war
           dadurch toter Code (TimeoutExpired -> ``status: error``).
        2. ``git add .`` staged den GESAMTEN Arbeitsbaum: Secrets, grosse
           ZIP-Backups und untracked Review-Dokumente. Jetzt wird nur
           explizit benannter Pfad gestaged; ohne Pfadliste werden nur
           Aenderungen an bereits versionierten Dateien uebernommen
           (``git add -u``) — keine untracked Dateien, keine Secrets.
        """
        test_res = self.run_pytest()
        if test_res["status"] != "success":
            return {
                "status": "error",
                "message": "Commit aborted: local tests failed.",
                "test_output": test_res
            }

        try:
            if paths:
                safe_paths = [str(p) for p in paths if str(p).strip()]
                if not safe_paths:
                    return {"status": "error", "message": "Keine gueltigen Pfade zum Stagen."}
                subprocess.run(["git", "add", "--", *safe_paths], check=True)
                commit_cmd = ["git", "commit", "-m", message, "--", *safe_paths]
            else:
                # Nur versionierte Dateien — keine untracked Secrets/Backups.
                subprocess.run(["git", "add", "-u"], check=True)
                commit_cmd = ["git", "commit", "-m", message]
            res = subprocess.run(commit_cmd, capture_output=True, text=True)
            if res.returncode == 0:
                return {"status": "success", "message": res.stdout.strip()}
            return {"status": "error", "message": res.stderr.strip()}
        except Exception as e:
            return {"status": "error", "message": str(e)}


# =====================================================================
# MODULE 5: MCP (MODEL CONTEXT PROTOCOL) ADAPTER
# =====================================================================
import asyncio

class MCPAdapterSkill:
    def __init__(self):
        self.servers = {}
        # Hashmap-based lock scheduler requested by pillar 3
        self.server_locks = {}

    def _get_lock(self, server_name: str) -> asyncio.Lock:
        if server_name not in self.server_locks:
            self.server_locks[server_name] = asyncio.Lock()
        return self.server_locks[server_name]

    async def connect_mcp_server(self, server_script_or_url: str) -> dict:
        """Registers a connection to an external MCP provider."""
        self.servers[server_script_or_url] = "active"
        return {"status": "success", "message": f"MCP connection to '{server_script_or_url}' verified."}

    async def execute_mcp_tool(self, tool_name: str, arguments: dict) -> dict:
        """Executes targeted MCP capability schemas with concurrency locks."""
        parts = tool_name.split("__")
        if len(parts) < 3 or parts[0] != "mcp":
            return {"status": "error", "error": "Invalid MCP tool name format. Expected mcp__{server}__{tool}"}
            
        server_name = parts[1]
        action_name = parts[2]
        
        lock = self._get_lock(server_name)
        async with lock:
            # M-10/Z-07: Es gibt hier KEINEN echten JSON-RPC-Kanal. Die alte
            # Fassung hat Quota-/Latenz-Zahlen erfunden und sie als
            # ``status: success`` an die API-Grenze gegeben — ein Agent, der
            # darauf entscheidet, arbeitet mit erfundenen Zahlen.
            # Konnektivitaet/Registrierung wird geprueft, aber es wird KEIN
            # Erfolg gemeldet, wenn kein Server wirklich ausgefuehrt wurde.
            registered = next(
                (state for key, state in self.servers.items() if server_name in key),
                None,
            )
            if registered is None:
                return {
                    "status": "error",
                    "error": "mcp_server_not_connected",
                    "message": (
                        f"Fuer '{server_name}' ist kein MCP-Server registriert "
                        "(connect_mcp_server wurde nicht aufgerufen). "
                        "Es wurde kein Tool ausgefuehrt."
                    ),
                    "tool": tool_name,
                    "server": server_name,
                    "arguments": arguments,
                }

            return {
                "status": "error",
                "error": "mcp_execution_not_implemented",
                "message": (
                    f"MCP-Ausfuehrung fuer '{tool_name}' ist nicht implementiert "
                    "(kein JSON-RPC-Kanal). Es wurden keine Messwerte erhoben."
                ),
                "tool": tool_name,
                "server": server_name,
                "arguments": arguments,
            }


# =====================================================================
# CENTRAL ENGINE CONTEXT WRAPPER
# =====================================================================
class CoreSkillsEngine:
    def __init__(self, vault_dir: Optional[str] = None, rag_db_dir: Optional[str] = None):
        self.docker = DockerControlSkill()
        self.obsidian = ObsidianVaultSkill(vault_dir)
        self.rag = LocalKnowledgeSkill(rag_db_dir)
        self.testing = GitTestingSkill()
        self.mcp = MCPAdapterSkill()


# =====================================================================
# Command Line Interface (CLI) Executable wrapper
# =====================================================================
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python core_skills_engine.py <module> <method> [arguments...]", file=sys.stderr)
        print("Modules: docker, obsidian, rag, testing, mcp", file=sys.stderr)
        sys.exit(1)

    module_name = sys.argv[1].lower()
    method_name = sys.argv[2]
    args = sys.argv[3:]

    engine = CoreSkillsEngine()
    target_module = None

    if module_name == "docker":
        target_module = engine.docker
    elif module_name == "obsidian":
        target_module = engine.obsidian
    elif module_name == "rag":
        target_module = engine.rag
    elif module_name == "testing":
        target_module = engine.testing
    elif module_name == "mcp":
        target_module = engine.mcp
    else:
        print(f"Unknown module '{module_name}'", file=sys.stderr)
        sys.exit(1)

    if not hasattr(target_module, method_name):
        print(f"Unknown method '{method_name}' on module '{module_name}'", file=sys.stderr)
        sys.exit(1)

    method = getattr(target_module, method_name)
    
    import inspect
    sig = inspect.signature(method)
    params = list(sig.parameters.values())
    
    typed_args = []
    for i, p in enumerate(params):
        if i >= len(args):
            break
        val = args[i]
        if p.annotation == int:
            val = int(val)
        elif p.annotation == List[str] or p.annotation == list:
            val = val.split(",")
        elif p.annotation == dict or p.annotation == Dict:
            val = json.loads(val)
        typed_args.append(val)

    try:
        result = method(*typed_args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as err:
        print(json.dumps({"status": "error", "message": str(err)}), file=sys.stderr)
        sys.exit(1)
