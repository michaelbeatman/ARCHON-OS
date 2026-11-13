# -*- coding: utf-8 -*-
"""
backend/plugin_manager.py
=========================
Archon OS Standardisiertes Pluginsystem (Meilenstein 5: Funktionserweiterung).

Architektur & Funktionsweise:
1. Manifest-Spezifikation (plugin.json oder manifest.json):
   - id, name, version, description, author, category, permissions, hooks, tools, settings_schema
2. BasePlugin-Klasse:
   - Standardisierte Lifecycle-Hooks: on_load, on_enable, on_disable, on_unload
   - Runtime-Hooks: on_startup, on_shutdown, before_tool_execute, after_tool_execute, on_message_received, on_task_completed
   - LLM-Tool-Export: get_tools(), execute_tool()
3. PluginManager:
   - Discovery im Verzeichnis 'plugins/'
   - Sicheres Laden via importlib (mit Exception-Isolation)
   - Status-Persistenz in data/plugins_state.json
   - Dynamischer Hook-Dispatcher (asynchron, fehlertolerant)
"""

import os
import sys
import json
import inspect
import asyncio
import logging
import importlib.util
from typing import Dict, Any, List, Optional, Callable, Type
from pathlib import Path

logger = logging.getLogger("archon.plugins")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[PluginManager] %(levelname)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGINS_DIR = os.path.join(WORKSPACE_DIR, "plugins")
CONFIGS_DIR = os.path.join(WORKSPACE_DIR, "data", "plugin_configs")
STATE_FILE = os.path.join(WORKSPACE_DIR, "data", "plugins_state.json")

def _schedule_async(coro):
    """Führt eine Coroutine im laufenden Event Loop aus oder startet einen kurzlebigen Loop."""
    try:
        loop = asyncio.get_running_loop()
        return loop.create_task(coro)
    except RuntimeError:
        try:
            return asyncio.run(coro)
        except Exception:
            return None


class BasePlugin:
    """
    Abstrakte Basisklasse für alle Archon OS Plugins.
    Jedes Plugin erbt von dieser Klasse und überschreibt bei Bedarf Lifecycle- oder Event-Hooks.
    """

    def __init__(self, manifest: Dict[str, Any], plugin_dir: str):
        self.manifest = manifest
        self.plugin_dir = plugin_dir
        self.id: str = manifest.get("id", Path(plugin_dir).name)
        self.name: str = manifest.get("name", self.id)
        self.version: str = manifest.get("version", "1.0.0")
        self.description: str = manifest.get("description", "")
        self.author: str = manifest.get("author", "Unknown")
        self.category: str = manifest.get("category", "general")
        self.permissions: List[str] = manifest.get("permissions", [])
        self.declared_hooks: List[str] = manifest.get("hooks", [])
        self.enabled: bool = False
        self.config: Dict[str, Any] = self._load_config()

    def _get_config_path(self) -> str:
        return os.path.join(CONFIGS_DIR, f"{self.id}.json")

    def _load_config(self) -> Dict[str, Any]:
        path = self._get_config_path()
        defaults = self.manifest.get("default_config", {})
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    defaults.update(saved)
            except Exception as e:
                logger.warning(f"Konnte Konfiguration für '{self.id}' nicht laden: {e}")
        return defaults

    def save_config(self, new_config: Dict[str, Any]) -> bool:
        """Speichert geänderte Einstellungen persistent ab."""
        try:
            self.config.update(new_config)
            with open(self._get_config_path(), "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"Fehler beim Speichern der Konfiguration von '{self.id}': {e}")
            return False

    # --- LIFECYCLE HOOKS ---
    async def on_load(self):
        """Wird aufgerufen, sobald das Plugin-Modul ins Gedächtnis geladen wurde."""
        pass

    async def on_enable(self):
        """Wird aufgerufen, wenn das Plugin aktiviert wird."""
        pass

    async def on_disable(self):
        """Wird aufgerufen, wenn das Plugin deaktiviert wird."""
        pass

    async def on_unload(self):
        """Wird aufgerufen, bevor das Modul entladen wird."""
        pass

    # --- SYSTEM & AGENT EVENT HOOKS ---
    async def on_startup(self):
        """Wird beim Start von Archon OS ausgeführt."""
        pass

    async def on_shutdown(self):
        """Wird beim Herunterfahren von Archon OS ausgeführt."""
        pass

    async def before_tool_execute(self, tool_name: str, args: Dict[str, Any], context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Wird vor Ausführung eines LLM-Tools aufgerufen.
        Kann Argumente manipulieren oder per Exception/Rückgabe den Aufruf unterbinden.
        """
        return args

    async def after_tool_execute(self, tool_name: str, result: Any, context: Dict[str, Any]) -> Any:
        """
        Wird nach Ausführung eines LLM-Tools aufgerufen.
        Kann Ergebnisse filtern, anreichern oder auditieren.
        """
        return result

    async def on_message_received(self, message: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Wird vor der Verarbeitung einer Benutzer- oder Agentennachricht aufgerufen.
        """
        return message

    async def on_task_completed(self, task: Dict[str, Any], context: Dict[str, Any]) -> None:
        """Wird aufgerufen, wenn ein Task abgeschlossen wurde."""
        pass

    # --- TOOL EXPORT ---
    def get_tools(self) -> List[Dict[str, Any]]:
        """
        Gibt eine Liste deklarativer Tools im OpenAI/Hermes-Format zurück,
        die Agenten zur Verfügung gestellt werden.
        """
        return self.manifest.get("tools", [])

    async def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        """
        Führt ein vom Plugin bereitgestelltes Tool aus.
        """
        raise NotImplementedError(f"Plugin '{self.id}' stellt Tool '{tool_name}' bereit, hat aber execute_tool nicht implementiert.")

    def to_dict(self) -> Dict[str, Any]:
        """Serialisiert den Plugin-Status für UI und REST-API."""
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "category": self.category,
            "permissions": self.permissions,
            "hooks": self.declared_hooks,
            "tools": self.get_tools(),
            "enabled": self.enabled,
            "has_settings": bool(self.manifest.get("settings_schema")),
            "settings_schema": self.manifest.get("settings_schema", {}),
            "config": self.config,
            "plugin_dir": self.plugin_dir
        }


class PluginManager:
    """
    Zentraler Orchestrator für Plugins in Archon OS.
    """

    def __init__(self, plugins_dir: str = PLUGINS_DIR, state_file: str = STATE_FILE):
        self.plugins_dir = plugins_dir
        self.state_file = state_file
        self.plugins: Dict[str, BasePlugin] = {}
        self.modules: Dict[str, Any] = {}
        self._states: Dict[str, Dict[str, Any]] = self._load_states()

    def _load_states(self) -> Dict[str, Dict[str, Any]]:
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Konnte {self.state_file} nicht lesen: {e}")
        return {}

    def _save_states(self):
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self._states, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Konnte {self.state_file} nicht schreiben: {e}")

    def discover_plugins(self) -> List[str]:
        """
        Durchsucht das plugins/-Verzeichnis nach Unterordnern mit plugin.json oder manifest.json.
        """
        discovered = []
        if not os.path.exists(self.plugins_dir):
            return discovered

        for entry in os.listdir(self.plugins_dir):
            pdir = os.path.join(self.plugins_dir, entry)
            if not os.path.isdir(pdir):
                continue
            manifest_path = os.path.join(pdir, "plugin.json")
            if not os.path.exists(manifest_path):
                manifest_path = os.path.join(pdir, "manifest.json")
            if os.path.exists(manifest_path):
                discovered.append(pdir)
        return discovered

    def load_plugin_from_dir(self, plugin_dir: str) -> Optional[BasePlugin]:
        """
        Lädt ein einzelnes Plugin aus einem Verzeichnis.
        """
        manifest_path = os.path.join(plugin_dir, "plugin.json")
        if not os.path.exists(manifest_path):
            manifest_path = os.path.join(plugin_dir, "manifest.json")
        
        if not os.path.exists(manifest_path):
            logger.warning(f"Kein Manifest in {plugin_dir} gefunden.")
            return None

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as e:
            logger.error(f"Fehler beim Parsen des Manifests in {plugin_dir}: {e}")
            return None

        plugin_id = manifest.get("id", Path(plugin_dir).name)
        entry_point = manifest.get("entry_point", "plugin.py")
        
        # Aufteilung in Datei und Klassenname (z. B. "plugin.py:MyPlugin" oder nur "plugin.py")
        class_name = None
        if ":" in entry_point:
            file_name, class_name = entry_point.split(":", 1)
        else:
            file_name = entry_point

        file_path = os.path.join(plugin_dir, file_name)
        if not os.path.exists(file_path):
            logger.error(f"Einstiegsdatei {file_path} für Plugin '{plugin_id}' existiert nicht.")
            return None

        # Dynamischer Modul-Import
        module_name = f"archon_plugin_{plugin_id.replace('.', '_').replace('-', '_')}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if not spec or not spec.loader:
                logger.error(f"Konnte Import-Spec für {file_path} nicht erstellen.")
                return None
            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)
            self.modules[plugin_id] = mod
        except Exception as e:
            logger.error(f"Laufzeitfehler beim Laden von Modul '{file_path}': {e}", exc_info=True)
            self._set_plugin_error(plugin_id, str(e))
            return None

        # Plugin-Klasse finden
        plugin_class: Optional[Type[BasePlugin]] = None
        if class_name and hasattr(mod, class_name):
            plugin_class = getattr(mod, class_name)
        else:
            # Suche nach Subklasse von BasePlugin
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if isinstance(attr, type) and issubclass(attr, BasePlugin) and attr is not BasePlugin:
                    plugin_class = attr
                    break

        if not plugin_class:
            logger.error(f"Keine von BasePlugin erbende Klasse in {file_path} gefunden.")
            return None

        try:
            plugin_instance = plugin_class(manifest=manifest, plugin_dir=plugin_dir)
            self.plugins[plugin_id] = plugin_instance
            
            # Gespeicherten Aktivierungszustand prüfen (Default: true)
            saved_state = self._states.get(plugin_id, {})
            should_enable = saved_state.get("enabled", manifest.get("default_enabled", True))
            
            # on_load Lifecycle aufrufen
            _schedule_async(self._safe_call_hook(plugin_instance, "on_load"))
            
            if should_enable:
                self.enable_plugin(plugin_id)
            else:
                plugin_instance.enabled = False

            logger.info(f"Plugin '{plugin_id}' (v{plugin_instance.version}) erfolgreich initialisiert. Aktiv: {plugin_instance.enabled}")
            return plugin_instance
        except Exception as e:
            logger.error(f"Fehler bei Instanziierung von Plugin '{plugin_id}': {e}", exc_info=True)
            self._set_plugin_error(plugin_id, str(e))
            return None

    def _set_plugin_error(self, plugin_id: str, err: str):
        if plugin_id not in self._states:
            self._states[plugin_id] = {}
        self._states[plugin_id]["error"] = err
        self._save_states()

    def load_all_plugins(self) -> Dict[str, BasePlugin]:
        """Lädt alle im Ordner plugins/ gefundenen Plugins."""
        discovered = self.discover_plugins()
        for pdir in discovered:
            self.load_plugin_from_dir(pdir)
        return self.plugins

    def enable_plugin(self, plugin_id: str) -> bool:
        """Aktiviert ein Plugin."""
        plugin = self.plugins.get(plugin_id)
        if not plugin:
            return False
        if plugin.enabled:
            return True

        plugin.enabled = True
        if plugin_id not in self._states:
            self._states[plugin_id] = {}
        self._states[plugin_id]["enabled"] = True
        self._states[plugin_id]["error"] = None
        self._save_states()

        _schedule_async(self._safe_call_hook(plugin, "on_enable"))
        logger.info(f"Plugin '{plugin_id}' aktiviert.")
        return True

    def disable_plugin(self, plugin_id: str) -> bool:
        """Deaktiviert ein Plugin."""
        plugin = self.plugins.get(plugin_id)
        if not plugin:
            return False
        if not plugin.enabled:
            return True

        plugin.enabled = False
        if plugin_id not in self._states:
            self._states[plugin_id] = {}
        self._states[plugin_id]["enabled"] = False
        self._save_states()

        _schedule_async(self._safe_call_hook(plugin, "on_disable"))
        logger.info(f"Plugin '{plugin_id}' deaktiviert.")
        return True

    def reload_plugin(self, plugin_id: str) -> bool:
        """Entlädt und lädt ein Plugin zur Laufzeit neu."""
        plugin = self.plugins.get(plugin_id)
        if not plugin:
            return False
        pdir = plugin.plugin_dir
        
        # Unload
        try:
            if inspect.iscoroutinefunction(plugin.on_unload):
                asyncio.create_task(plugin.on_unload())
            else:
                plugin.on_unload()
        except Exception:
            pass

        module_name = f"archon_plugin_{plugin_id.replace('.', '_').replace('-', '_')}"
        if module_name in sys.modules:
            del sys.modules[module_name]
        if plugin_id in self.plugins:
            del self.plugins[plugin_id]

        new_instance = self.load_plugin_from_dir(pdir)
        return new_instance is not None

    async def _safe_call_hook(self, plugin: BasePlugin, hook_name: str, *args, **kwargs) -> Any:
        """Führt einen Hook an einem Plugin sicher aus (fängt Exceptions isoliert ab)."""
        if not hasattr(plugin, hook_name):
            return None
        fn = getattr(plugin, hook_name)
        try:
            if inspect.iscoroutinefunction(fn):
                return await fn(*args, **kwargs)
            else:
                return fn(*args, **kwargs)
        except Exception as e:
            logger.error(f"Fehler in Hook '{hook_name}' von Plugin '{plugin.id}': {e}", exc_info=True)
            return None

    async def trigger_hook(self, hook_name: str, *args, **kwargs) -> List[Any]:
        """
        Löst einen Hook für alle aktivierten Plugins aus, die diesen Hook deklarieren.
        Gibt die Liste der Ergebnisse zurück.
        """
        results = []
        for plugin in list(self.plugins.values()):
            if not plugin.enabled:
                continue
            res = await self._safe_call_hook(plugin, hook_name, *args, **kwargs)
            if res is not None:
                results.append(res)
        return results

    async def trigger_filter_hook(self, hook_name: str, initial_value: Any, context: Dict[str, Any]) -> Any:
        """
        Pipet einen Wert nacheinander durch alle aktivierten Plugins (z. B. before_tool_execute).
        """
        val = initial_value
        for plugin in list(self.plugins.values()):
            if not plugin.enabled:
                continue
            if not hasattr(plugin, hook_name):
                continue
            try:
                fn = getattr(plugin, hook_name)
                if inspect.iscoroutinefunction(fn):
                    new_val = await fn(val, context)
                else:
                    new_val = fn(val, context)
                if new_val is not None:
                    val = new_val
            except PermissionError as pe:
                # Sicherheits-Plugins dürfen Aktionen explizit verweigern!
                logger.warning(f"Aktion durch Plugin '{plugin.id}' blockiert: {pe}")
                raise
            except Exception as e:
                logger.error(f"Unerwarteter Fehler in Filter-Hook '{hook_name}' von Plugin '{plugin.id}': {e}")
        return val

    async def apply_before_tool_execute(self, tool_name: str, args: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Pipet Tool-Argumente vor der Ausführung durch alle aktiven Plugins."""
        ctx = context or {}
        cur_args = dict(args)
        for plugin in list(self.plugins.values()):
            if not plugin.enabled:
                continue
            if not hasattr(plugin, "before_tool_execute"):
                continue
            try:
                fn = getattr(plugin, "before_tool_execute")
                if inspect.iscoroutinefunction(fn):
                    res = await fn(tool_name, cur_args, ctx)
                else:
                    res = fn(tool_name, cur_args, ctx)
                if isinstance(res, dict):
                    cur_args = res
            except PermissionError as pe:
                logger.warning(f"Tool-Aufruf '{tool_name}' durch Plugin '{plugin.id}' verweigert: {pe}")
                raise
            except Exception as e:
                logger.error(f"Fehler in before_tool_execute von Plugin '{plugin.id}': {e}")
                # Z-14: Fail-closed — wenn ein Audit/Security-Plugin crasht, darf das Tool nicht still ausgefuehrt werden
                if "security" in getattr(plugin, "id", "").lower() or "audit" in getattr(plugin, "id", "").lower():
                    raise PermissionError(f"Sicherheitspruefung in Plugin '{plugin.id}' fehlgeschlagen: {e}")
        return cur_args

    async def apply_after_tool_execute(self, tool_name: str, result: Any, context: Optional[Dict[str, Any]] = None) -> Any:
        """Filtert oder auditiert Tool-Ergebnisse nach der Ausführung."""
        ctx = context or {}
        cur_res = result
        for plugin in list(self.plugins.values()):
            if not plugin.enabled:
                continue
            if not hasattr(plugin, "after_tool_execute"):
                continue
            try:
                fn = getattr(plugin, "after_tool_execute")
                if inspect.iscoroutinefunction(fn):
                    res = await fn(tool_name, cur_res, ctx)
                else:
                    res = fn(tool_name, cur_res, ctx)
                if res is not None:
                    cur_res = res
            except Exception as e:
                logger.error(f"Fehler in after_tool_execute von Plugin '{plugin.id}': {e}")
        return cur_res

    def get_all_exported_tools(self) -> List[Dict[str, Any]]:
        """Sammelt alle LLM-Tools aller aktiven Plugins."""
        tools = []
        for plugin in self.plugins.values():
            if not plugin.enabled:
                continue
            for t in plugin.get_tools():
                tool_copy = dict(t)
                tool_copy["_plugin_id"] = plugin.id
                tools.append(tool_copy)
        return tools

    async def execute_plugin_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        """Leitet einen Tool-Aufruf an das entsprechende Plugin weiter."""
        for plugin in self.plugins.values():
            if not plugin.enabled:
                continue
            declared_names = [t.get("name") for t in plugin.get_tools() if "name" in t]
            if tool_name in declared_names:
                return await plugin.execute_tool(tool_name, args)
        raise ValueError(f"Kein aktives Plugin gefunden, das Tool '{tool_name}' anbietet.")

    def list_plugins_summary(self) -> List[Dict[str, Any]]:
        """Gibt Metadaten aller Plugins für die UI-Übersicht zurück."""
        return [p.to_dict() for p in self.plugins.values()]


# Singleton-Instanz
_PLUGIN_MANAGER: Optional[PluginManager] = None

def get_plugin_manager() -> PluginManager:
    global _PLUGIN_MANAGER
    if _PLUGIN_MANAGER is None:
        _PLUGIN_MANAGER = PluginManager()
        _PLUGIN_MANAGER.load_all_plugins()
    return _PLUGIN_MANAGER
