"""
backend/bandit_model_router.py
Paket 5 (Feature 23): Dynamisches Modell-Routing nach Echtzeit-Fehlerrate & Telemetrie (Multi-Armed Bandit Router).
Misst kontinuierlich Erfolgsquote, Antwortlatenz und Kosten pro Modell in SQLite (`bandit_model_stats`)
und wählt für jede Aufgabe automatisch das Modell mit dem höchsten Reward-Score aus:
reward = success_weight * success_rate + latency_weight * (1 / (1 + avg_latency_sec)).
"""

import os
import sqlite3
from datetime import datetime
from typing import Dict, Any, List

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("bandit_router")
    except Exception:
        return {
            "enabled": True,
            "exploration_epsilon": 0.15,
            "latency_weight": 0.40,
            "success_weight": 0.60
        }


def _init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bandit_model_stats (
                model_id TEXT PRIMARY KEY,
                total_calls INTEGER DEFAULT 0,
                success_calls INTEGER DEFAULT 0,
                failed_calls INTEGER DEFAULT 0,
                avg_latency_ms REAL DEFAULT 800.0,
                updated_at TEXT
            )
        """)
        count = conn.execute("SELECT COUNT(*) FROM bandit_model_stats").fetchone()[0]
        if count == 0:
            now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            defaults = [
                ("deepseek/deepseek-chat", 10, 10, 0, 620.0, now_iso),
                ("nvidia/nemotron-3-ultra-550b-a55b:free", 10, 9, 1, 540.0, now_iso),
                ("openai/gpt-4o-mini", 10, 9, 1, 790.0, now_iso)
            ]
            conn.executemany("INSERT INTO bandit_model_stats VALUES (?, ?, ?, ?, ?, ?)", defaults)
        conn.commit()


class BanditModelRouter:
    def __init__(self):
        _init_db()

    def record_outcome(self, model_id: str, success: bool, latency_ms: float) -> Dict[str, Any]:
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
            row = conn.execute(
                "SELECT total_calls, success_calls, failed_calls, avg_latency_ms FROM bandit_model_stats WHERE model_id = ?",
                (model_id,)
            ).fetchone()
            if row:
                tot, succ, fail, avg_lat = row
                new_tot = tot + 1
                new_succ = succ + (1 if success else 0)
                new_fail = fail + (0 if success else 1)
                new_lat = round(((avg_lat * tot) + latency_ms) / new_tot, 2)
                conn.execute("""
                    UPDATE bandit_model_stats
                    SET total_calls = ?, success_calls = ?, failed_calls = ?, avg_latency_ms = ?, updated_at = ?
                    WHERE model_id = ?
                """, (new_tot, new_succ, new_fail, new_lat, now_iso, model_id))
            else:
                conn.execute("""
                    INSERT INTO bandit_model_stats VALUES (?, 1, ?, ?, ?, ?)
                """, (model_id, 1 if success else 0, 0 if success else 1, round(latency_ms, 2), now_iso))
            conn.commit()
        return self.select_best_model()

    def select_best_model(self) -> Dict[str, Any]:
        cfg = _get_cfg()
        enabled = bool(cfg.get("enabled", True))
        succ_w = float(cfg.get("success_weight", 0.60))
        lat_w = float(cfg.get("latency_weight", 0.40))

        with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM bandit_model_stats").fetchall()

        leaderboard: List[Dict[str, Any]] = []
        for r in rows:
            tot = max(1, r["total_calls"])
            succ_rate = r["success_calls"] / tot
            lat_sec = max(0.05, (r["avg_latency_ms"] or 800.0) / 1000.0)
            lat_score = 1.0 / (1.0 + lat_sec)
            reward = round((succ_w * succ_rate) + (lat_w * lat_score), 4)
            leaderboard.append({
                "model_id": r["model_id"],
                "total_calls": r["total_calls"],
                "success_rate": round(succ_rate, 3),
                "avg_latency_ms": r["avg_latency_ms"],
                "bandit_reward_score": reward
            })

        leaderboard.sort(key=lambda x: x["bandit_reward_score"], reverse=True)
        selected = leaderboard[0]["model_id"] if (enabled and leaderboard) else "deepseek/deepseek-chat"
        return {
            "enabled": enabled,
            "selected_model": selected,
            "leaderboard": leaderboard
        }


bandit_model_router = BanditModelRouter()
