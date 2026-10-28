# -*- coding: utf-8 -*-
"""
plugins/system_metrics/plugin.py
================================
Plugin zur Bereitstellung von System- und Docker-Telemetrie für Agenten und das Dashboard.
"""

import os
import sys
import datetime
from typing import Dict, Any, List
from backend.plugin_manager import BasePlugin

try:
    import psutil
except ImportError:
    psutil = None

try:
    import docker
except ImportError:
    docker = None


class SystemMetricsPlugin(BasePlugin):
    def __init__(self, manifest: Dict[str, Any], plugin_dir: str):
        super().__init__(manifest, plugin_dir)
        self.docker_client = None

    async def on_load(self):
        self._init_docker()

    async def on_enable(self):
        self._init_docker()

    def _init_docker(self):
        if docker is None:
            return
        for target in [
            os.getenv("DOCKER_HOST"),
            "unix:///var/run/docker.sock",
            "tcp://docker-socket-proxy:2375",
            "tcp://127.0.0.1:2375",
            None
        ]:
            try:
                client = docker.DockerClient(base_url=target, timeout=3) if target else docker.from_env(timeout=3)
                client.ping()
                self.docker_client = client
                break
            except Exception:
                continue

    async def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        if tool_name == "get_system_telemetry":
            return self._get_telemetry(include_containers=args.get("include_containers", True))
        raise ValueError(f"Unbekanntes Tool: {tool_name}")

    def _get_telemetry(self, include_containers: bool = True) -> Dict[str, Any]:
        if psutil:
            vm = psutil.virtual_memory()
            disk = psutil.disk_usage(os.path.abspath(os.sep))
            cpu_percent = psutil.cpu_percent(interval=0.1)
            mem_data = {
                "total_gb": round(vm.total / (1024**3), 2),
                "used_gb": round(vm.used / (1024**3), 2),
                "free_gb": round(vm.available / (1024**3), 2),
                "percent": vm.percent,
                "warning": vm.percent >= self.config.get("warning_threshold_ram_percent", 85.0)
            }
            disk_data = {
                "total_gb": round(disk.total / (1024**3), 2),
                "used_gb": round(disk.used / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "percent": disk.percent
            }
        else:
            cpu_percent = 0.0
            mem_data = {"total_gb": 0, "used_gb": 0, "free_gb": 0, "percent": 0.0, "warning": False}
            disk_data = {"total_gb": 0, "used_gb": 0, "free_gb": 0, "percent": 0.0}

        result = {
            "status": "success",
            "timestamp": datetime.datetime.now().isoformat(),
            "cpu_percent": cpu_percent,
            "memory": mem_data,
            "disk": disk_data
        }

        if include_containers and self.docker_client:
            containers = []
            try:
                for c in self.docker_client.containers.list(all=True):
                    containers.append({
                        "name": c.name,
                        "status": c.status,
                        "image": c.image.tags[0] if c.image.tags else c.image.short_id
                    })
                result["containers"] = containers
                result["container_count"] = len(containers)
            except Exception as e:
                result["container_error"] = str(e)

        return result
