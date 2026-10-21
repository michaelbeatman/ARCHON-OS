"""
oracle_news_radar.py - Automatisierter Trend-, Modell- und Markt-Radar für Archon OS
Sammelt kontinuierlich Signale aus HackerNews, Hugging Face Hub, GitHub Trending und RSS,
synthetisiert diese in Obsidian Vaults und speist sie in die Archon-Inbox/Dashboard ein.
"""

import os
import sys
import json
import time
import datetime
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Dict, Any, Optional

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SEEN_FILE = DATA_DIR / "oracle_seen_ids.json"
FEED_FILE = DATA_DIR / "oracle_feed.json"

AI_KEYWORDS = [
    "ai", "llm", "agent", "agentic", "model", "rag", "mcp", "transformer",
    "gpt", "claude", "hermes", "qwen", "mistral", "deepseek", "reasoning",
    "prompt", "diffusion", "quantiz", "gguf", "llama", "worktree", "automation"
]

def resolve_vault_path() -> Path:
    env_path = os.environ.get("OBSIDIAN_VAULT_PATH")
    if env_path and os.path.exists(env_path):
        return Path(env_path)
    candidates = [
        Path("/opt/data/obsidian"),
        Path("/app/data/obsidian"),
        BASE_DIR / "obsidian_vault",
        Path("C:/Mein Obsidian"),
        Path("C:/.Mein Obsidian")
    ]
    for c in candidates:
        if c.exists() and c.is_dir():
            return c
    fallback = BASE_DIR / "obsidian_vault"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


class OracleNewsRadar:
    def __init__(self):
        self.seen_ids = self._load_seen_ids()

    def _load_seen_ids(self) -> set:
        if SEEN_FILE.exists():
            try:
                with open(SEEN_FILE, "r", encoding="utf-8") as f:
                    return set(json.load(f))
            except Exception:
                return set()
        return set()

    def _save_seen_ids(self):
        try:
            with open(SEEN_FILE, "w", encoding="utf-8") as f:
                json.dump(list(self.seen_ids)[-1000:], f, indent=2)
        except Exception as e:
            print(f"[ORACLE] Fehler beim Speichern von seen_ids: {e}", file=sys.stderr)

    def _fetch_url(self, url: str, timeout: int = 12) -> Optional[Any]:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Archon-OracleNewsRadar/1.0 (AgenticOS-2026; autonomous intelligence bot)"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                return json.loads(data.decode("utf-8"))
        except Exception as e:
            print(f"[ORACLE] Fetch error for {url}: {e}", file=sys.stderr)
            return None

    def fetch_hacker_news(self, limit: int = 25) -> List[Dict[str, Any]]:
        """Liest aktuelle Hacker News Top-Stories und filtert nach AI/Agenten/Tech."""
        items = []
        top_ids = self._fetch_url("https://hacker-news.firebaseio.com/v0/topstories.json")
        if not top_ids or not isinstance(top_ids, list):
            return items

        for item_id in top_ids[:limit]:
            id_str = f"hn_{item_id}"
            if id_str in self.seen_ids:
                continue

            story = self._fetch_url(f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json")
            if not story or story.get("type") != "story":
                continue

            title = story.get("title", "")
            title_lower = title.lower()

            # Relevanzfilter
            if any(k in title_lower for k in AI_KEYWORDS) or story.get("score", 0) > 150:
                items.append({
                    "id": id_str,
                    "source": "HackerNews",
                    "title": title,
                    "url": story.get("url", f"https://news.ycombinator.com/item?id={item_id}"),
                    "score": story.get("score", 0),
                    "comments": story.get("descendants", 0),
                    "created_at": datetime.datetime.fromtimestamp(story.get("time", time.time())).isoformat(),
                    "category": "Industry Tech",
                    "summary": f"Diskussion auf HackerNews mit {story.get('score', 0)} Punkten und {story.get('descendants', 0)} Kommentaren."
                })
                self.seen_ids.add(id_str)
        return items

    def fetch_huggingface_trending(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Liest trending Modelle von Hugging Face Hub."""
        items = []
        models = self._fetch_url(f"https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit={limit}")
        if not models or not isinstance(models, list):
            return items

        for m in models:
            model_id = m.get("id", "")
            id_str = f"hf_{model_id}"
            if id_str in self.seen_ids:
                continue

            pipeline = m.get("pipeline_tag", "llm / weights")
            downloads = m.get("downloads", 0)
            likes = m.get("likes", 0)

            items.append({
                "id": id_str,
                "source": "Hugging Face",
                "title": f"Neues Trend-Modell: {model_id}",
                "url": f"https://huggingface.co/{model_id}",
                "score": likes,
                "downloads": downloads,
                "created_at": datetime.datetime.now().isoformat(),
                "category": "AI Models & GGUF",
                "summary": f"Pipeline: {pipeline} | Downloads: {downloads:,} | Likes: {likes}"
            })
            self.seen_ids.add(id_str)
        return items

    def fetch_github_trending(self, limit: int = 8) -> List[Dict[str, Any]]:
        """Liest stark wachsende GitHub Repositories im Agentic- und LLM-Bereich."""
        items = []
        url = "https://api.github.com/search/repositories?q=agentic+OR+llm+pushed:>2026-10-01&sort=stars&order=desc&per_page=12"
        data = self._fetch_url(url)
        if not data or "items" not in data:
            return items

        for repo in data["items"][:limit]:
            full_name = repo.get("full_name", "")
            id_str = f"gh_{full_name}"
            if id_str in self.seen_ids:
                continue

            stars = repo.get("stargazers_count", 0)
            desc = repo.get("description", "Keine Beschreibung vorhanden.")
            lang = repo.get("language", "Code")

            items.append({
                "id": id_str,
                "source": "GitHub Trending",
                "title": f"Repo: {full_name} ({stars:,} ★)",
                "url": repo.get("html_url", ""),
                "score": stars,
                "language": lang,
                "created_at": datetime.datetime.now().isoformat(),
                "category": "Open-Source Agents",
                "summary": f"{desc} [Sprache: {lang}]"
            })
            self.seen_ids.add(id_str)
        return items

    def run_radar_cycle(self) -> Dict[str, Any]:
        """Führt einen kompletten Aggregationszyklus durch und persistiert die Ergebnisse."""
        print(f"[ORACLE] Starte Radar-Suchlauf um {datetime.datetime.now().strftime('%H:%M:%S')}...")
        all_signals = []

        all_signals.extend(self.fetch_hacker_news(limit=25))
        all_signals.extend(self.fetch_huggingface_trending(limit=10))
        all_signals.extend(self.fetch_github_trending(limit=8))

        self._save_seen_ids()

        # Vorhandenen Feed laden oder initialisieren
        current_feed = []
        if FEED_FILE.exists():
            try:
                with open(FEED_FILE, "r", encoding="utf-8") as f:
                    current_feed = json.load(f)
            except Exception:
                current_feed = []

        # Neue Signale voranstellen (neueste oben)
        updated_feed = all_signals + current_feed
        # Begrenzung auf die letzten 100 Signale
        updated_feed = updated_feed[:100]

        with open(FEED_FILE, "w", encoding="utf-8") as f:
            json.dump(updated_feed, f, indent=2, ensure_ascii=False)

        # In Obsidian synthetisieren
        vault_note_path = self.synthesize_to_obsidian(all_signals)

        return {
            "status": "success",
            "new_signals_count": len(all_signals),
            "total_feed_count": len(updated_feed),
            "obsidian_note": str(vault_note_path) if vault_note_path else None,
            "timestamp": datetime.datetime.now().isoformat()
        }

    def synthesize_to_obsidian(self, new_signals: List[Dict[str, Any]]) -> Optional[Path]:
        """Schreibt ein tägliches Intelligence-Dossier direkt in den Obsidian Vault."""
        vault = resolve_vault_path()
        radar_dir = vault / "04_Radar"
        radar_dir.mkdir(parents=True, exist_ok=True)

        today_str = datetime.date.today().isoformat()
        note_file = radar_dir / f"Oracle_Radar_{today_str}.md"

        now_time = datetime.datetime.now().strftime("%H:%M:%S")

        lines = []
        if not note_file.exists():
            lines.append(f"# 🛰️ Oracle News Radar – {today_str}\n")
            lines.append(f"> **Archon OS Automated Intelligence Stream** | Tags: #oracle #radar #market-intel\n\n")
            lines.append("## 📌 Übersicht der erfassten Marktsignale\n\n")

        if new_signals:
            lines.append(f"### Update: {now_time} Uhr ({len(new_signals)} neue Signale)\n\n")
            for s in new_signals:
                lines.append(f"- **[{s['source']}]** [{s['title']}]({s['url']})")
                lines.append(f"  - **Kategorie:** `{s['category']}` | **Score / Metrik:** {s.get('score', 0)}")
                lines.append(f"  - **Summary:** {s.get('summary', '')}")
                lines.append(f"  - **Triage-Option:** `Archon Task anlegen für Evaluierung`\n")
        else:
            if not note_file.exists():
                lines.append("*Bislang keine neuen ungesehenen Signale im aktuellen Zeitfenster.*\n")

        with open(note_file, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        return note_file

    def get_feed(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Liest den aktuellen Feed aus dem Cache."""
        if FEED_FILE.exists():
            try:
                with open(FEED_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)[:limit]
            except Exception:
                return []
        return []

    def triage_to_task(self, signal_id: str) -> Dict[str, Any]:
        """Wandelt ein Signal aus dem Feed direkt in eine Aufgabe für Archon OS um."""
        feed = self.get_feed(100)
        target = next((item for item in feed if item.get("id") == signal_id), None)
        if not target:
            return {"status": "error", "message": f"Signal mit ID {signal_id} nicht gefunden"}

        # Task in kanban_data.json einhängen
        kanban_file = BASE_DIR / "agent_workspace" / "kanban_data.json"
        if not kanban_file.exists():
            kanban_file = BASE_DIR / "data" / "kanban_data.json"

        task_entry = {
            "id": f"task_oracle_{int(time.time())}",
            "title": f"[ORACLE] {target['title'][:70]}",
            "description": f"Quelle: {target['source']}\nURL: {target['url']}\n\n{target.get('summary', '')}\n\nZiel: Evaluieren und ggf. in Archon OS / Wissensbasis integrieren.",
            "status": "todo",
            "priority": "medium",
            "category": "Research & Tech",
            "created_at": datetime.datetime.now().isoformat()
        }

        tasks = []
        if kanban_file.exists():
            try:
                with open(kanban_file, "r", encoding="utf-8") as f:
                    tasks = json.load(f)
            except Exception:
                tasks = []

        tasks.append(task_entry)
        try:
            with open(kanban_file, "w", encoding="utf-8") as f:
                json.dump(tasks, f, indent=2, ensure_ascii=False)
            return {"status": "success", "task_id": task_entry["id"], "task": task_entry}
        except Exception as e:
            return {"status": "error", "message": f"Fehler beim Erstellen des Tasks: {e}"}


if __name__ == "__main__":
    radar = OracleNewsRadar()
    result = radar.run_radar_cycle()
    print(json.dumps(result, indent=2))
