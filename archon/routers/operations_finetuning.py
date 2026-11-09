"""Sub-Router fuer Fine-Tuning Pipeline (t-56ff9d).

Ausgelagert aus backend/operations_api.py.
"""

import os
import sqlite3
from typing import Any, Dict
from fastapi import APIRouter, Body, HTTPException

from archon.core.paths import OPT_DATA_DIR, STATE_DB_PATH

router = APIRouter()


def _query_feedback_and_learnings_counts(db_path: str) -> tuple[int, int]:
    """Liest Feedback- und Learnings-Zähler aus der SQLite-Datenbank aus."""
    feedback_count = 0
    learnings_count = 0
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        try:
            feedback_count = conn.execute("SELECT COUNT(*) FROM human_feedback").fetchone()[0]
        except Exception:
            pass
        try:
            learnings_count = conn.execute("SELECT COUNT(*) FROM learnings").fetchone()[0]
        except Exception:
            pass
        finally:
            conn.close()
    return feedback_count, learnings_count


@router.get("/finetuning/status")
def api_finetuning_status():
    """Gibt Status- und Metrik-Informationen über den Feintuning-Datensatz zurück."""
    try:
        from scripts.prepare_finetuning_dataset import DEFAULT_DB_PATH, DEFAULT_OUTPUT_DIR

        opt_agentic_db = os.path.join(OPT_DATA_DIR, "agentic_memory.db")
        db_path = opt_agentic_db if os.path.exists(opt_agentic_db) else DEFAULT_DB_PATH
        feedback_count, learnings_count = _query_feedback_and_learnings_counts(db_path)

        files_info = []
        out_dir = os.path.join(OPT_DATA_DIR, "finetuning") if os.path.exists(OPT_DATA_DIR) else DEFAULT_OUTPUT_DIR
        if os.path.exists(out_dir):
            for f in os.listdir(out_dir):
                if f.endswith(".jsonl"):
                    f_path = os.path.join(out_dir, f)
                    with open(f_path, "r", encoding="utf-8") as fp:
                        lines = len(fp.readlines())
                    files_info.append({"filename": f, "lines": lines, "size_bytes": os.path.getsize(f_path)})

        return {
            "status": "success",
            "db_path": db_path,
            "feedback_samples": feedback_count,
            "learnings_samples": learnings_count,
            "generated_datasets": files_info,
            "config_template": "config/finetuning/lora_config.yml",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/finetuning/prepare-dataset")
def api_finetuning_prepare(req: Dict[str, Any] = Body(...)):
    """Extrahiert Datensätze aus Feedback & Learnings für das Modell-Feintuning."""
    try:
        from scripts.prepare_finetuning_dataset import DEFAULT_DB_PATH, DEFAULT_OUTPUT_DIR, prepare_dataset

        opt_agentic_db = os.path.join(OPT_DATA_DIR, "agentic_memory.db")
        db_path = opt_agentic_db if os.path.exists(opt_agentic_db) else DEFAULT_DB_PATH
        out_dir = os.path.join(OPT_DATA_DIR, "finetuning") if os.path.exists(OPT_DATA_DIR) else DEFAULT_OUTPUT_DIR

        fmt = req.get("format", "chat")
        min_score = int(req.get("min_score", 0))
        include_learnings = bool(req.get("include_learnings", True))
        split_ratio = float(req.get("split_ratio", 0.9))

        res = prepare_dataset(
            db_path=db_path,
            output_dir=out_dir,
            fmt=fmt,
            min_score=min_score,
            include_learnings=include_learnings,
            split_ratio=split_ratio,
        )
        return {"status": "success", "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
