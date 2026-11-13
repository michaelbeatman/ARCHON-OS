#!/usr/bin/env python3
"""
==============================================================================
Archon OS 2026 - Fine-Tuning Dataset Preparation Pipeline
==============================================================================
Extracts supervised fine-tuning (SFT) samples from:
1. Human Feedback & Corrections (data/agentic_memory.db -> human_feedback)
2. Agent Learnings & Rules (data/agentic_memory.db -> learnings)
3. Verified High-Quality Agent Conversations

Outputs format-compliant datasets for Unsloth, Hugging Face TRL (SFTTrainer),
and Axolotl, split into train.jsonl and eval.jsonl.
"""

import os
import sys
import json
import re
import random
import sqlite3
import argparse
from pathlib import Path

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "agentic_memory.db")
DEFAULT_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "finetuning")

SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{24,}", re.IGNORECASE),
    re.compile(r"ghp_[a-zA-Z0-9]{30,}", re.IGNORECASE),
    re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{20,}", re.IGNORECASE),
    re.compile(r"password\s*[:=]\s*['\"][^'\"]+['\"]", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
]

SYSTEM_PROMPT_DEFAULT = "Du bist Archon OS, ein hochkompetenter, autonomer Agent für Systemarchitektur, Code-Audit und Betriebsführung."

def sanitize_text(text: str) -> str:
    """Removes sensitive tokens, credentials, and API keys."""
    if not text:
        return ""
    sanitized = text
    for pattern in SECRET_PATTERNS:
        sanitized = pattern.sub("[REDACTED_SECRET]", sanitized)
    return sanitized.strip()

def extract_from_feedback(db_path: str, min_score: int = 1):
    """Extracts pairs where human either approved or explicitly corrected the output."""
    samples = []
    if not os.path.exists(db_path):
        return samples

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Query feedback table
    try:
        rows = cur.execute("""
            SELECT f.id, f.task_id, f.agent_id, f.score, f.comment, f.corrected_text,
                   t.title, t.result
            FROM human_feedback f
            LEFT JOIN tasks t ON f.task_id = t.id
            WHERE f.score >= ? OR f.corrected_text IS NOT NULL
        """, (min_score,)).fetchall()

        for row in rows:
            f_id, task_id, agent_id, score, comment, corrected_text, title, result = row
            
            instruction = title or f"Aufgabe {task_id} von Agent {agent_id}"
            
            # Target output is corrected text if provided, otherwise the approved result
            target_output = corrected_text if corrected_text else result
            if not target_output:
                if comment and score >= 1:
                    target_output = f"Positives Feedback: {comment}"
                else:
                    continue

            samples.append({
                "source": "human_feedback",
                "instruction": sanitize_text(instruction),
                "input": f"Kontext: Task ID {task_id}" if task_id else "",
                "output": sanitize_text(target_output),
                "agent_id": agent_id or "archon"
            })
    except Exception as e:
        print(f"Warning: Failed to extract feedback data: {e}", file=sys.stderr)
    finally:
        conn.close()

    return samples

def extract_from_learnings(db_path: str):
    """Extracts distilled architectural learnings and guidelines."""
    samples = []
    if not os.path.exists(db_path):
        return samples

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    try:
        rows = cur.execute("""
            SELECT category, summary, obsidian_link, importance
            FROM learnings
            WHERE summary IS NOT NULL AND length(summary) > 10
        """).fetchall()

        for category, summary, link, importance in rows:
            instruction = f"Erläutere die Leitlinie für {category or 'Systembetrieb'} in Archon OS."
            samples.append({
                "source": "learnings",
                "instruction": sanitize_text(instruction),
                "input": f"Thema: {category}",
                "output": sanitize_text(summary),
                "agent_id": "archon_core"
            })
    except Exception as e:
        print(f"Warning: Failed to extract learnings: {e}", file=sys.stderr)
    finally:
        conn.close()

    return samples

def format_sample(sample: dict, fmt: str) -> dict:
    """Converts a raw sample into the desired format."""
    inst = sample["instruction"]
    inp = sample.get("input", "")
    out = sample["output"]

    if fmt == "alpaca":
        return {
            "instruction": inst,
            "input": inp,
            "output": out
        }
    elif fmt == "sharegpt":
        human_val = f"{inst}\n\n{inp}".strip() if inp else inst
        return {
            "conversations": [
                {"from": "system", "value": SYSTEM_PROMPT_DEFAULT},
                {"from": "human", "value": human_val},
                {"from": "gpt", "value": out}
            ]
        }
    else:  # "chat" (OpenAI / TRL standard)
        user_content = f"{inst}\n\n{inp}".strip() if inp else inst
        return {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT_DEFAULT},
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": out}
            ]
        }

def prepare_dataset(
    db_path: str = DEFAULT_DB_PATH,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    fmt: str = "chat",
    min_score: int = 0,
    include_learnings: bool = True,
    split_ratio: float = 0.9,
    seed: int = 42
) -> dict:
    """Prepares training and evaluation JSONL files."""
    os.makedirs(output_dir, exist_ok=True)
    random.seed(seed)

    all_raw_samples = []
    
    # 1. Feedback samples
    feedback_samples = extract_from_feedback(db_path, min_score=min_score)
    all_raw_samples.extend(feedback_samples)

    # 2. Distilled learnings
    if include_learnings:
        learnings_samples = extract_from_learnings(db_path)
        all_raw_samples.extend(learnings_samples)

    # Add routine synthetic bootstrap samples if database is young
    if len(all_raw_samples) < 5:
        bootstrap_cases = [
            ("Klassifiziere die folgende Systemmeldung: [CRITICAL] OOM-Killed", "Triage-Priorität: SEV-1. Sofortige Speicheranalyse und Container-Neustart erforderlich."),
            ("Führe ein Routing für diese Anfrage durch: 'Schreibe einen SQL-Report für Q3-Umsätze'", "Route an Agent: Financial Analyst (cs-financial-analyst) mit Tool-Scope: sql-database-assistant."),
            ("Prüfe die Freigaberichtlinie für E-Mail-Versand an externe Kunden.", "Human-in-the-Loop Erfordernis: E-Mail-Entwurf muss vor dem Versand in die Freigabe-Queue zur Überprüfung eingestellt werden.")
        ]
        for inst, out in bootstrap_cases:
            all_raw_samples.append({
                "source": "bootstrap_routine",
                "instruction": inst,
                "input": "",
                "output": out,
                "agent_id": "archon"
            })

    # Format samples
    formatted_samples = [format_sample(s, fmt) for s in all_raw_samples]
    random.shuffle(formatted_samples)

    # Split
    split_index = int(len(formatted_samples) * split_ratio)
    train_data = formatted_samples[:split_index]
    eval_data = formatted_samples[split_index:] if split_index < len(formatted_samples) else formatted_samples[-1:]

    train_path = os.path.join(output_dir, f"train_{fmt}.jsonl")
    eval_path = os.path.join(output_dir, f"eval_{fmt}.jsonl")

    with open(train_path, "w", encoding="utf-8") as f:
        for item in train_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    with open(eval_path, "w", encoding="utf-8") as f:
        for item in eval_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    summary = {
        "status": "success",
        "total_samples": len(formatted_samples),
        "train_samples": len(train_data),
        "eval_samples": len(eval_data),
        "format": fmt,
        "train_file": str(train_path),
        "eval_file": str(eval_path),
        "sources": {
            "human_feedback": len(feedback_samples),
            "learnings": len(all_raw_samples) - len(feedback_samples)
        }
    }
    return summary

def main():
    parser = argparse.ArgumentParser(description="Prepare SFT Dataset for Archon OS Model Fine-Tuning")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to agentic_memory.db")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Destination directory for jsonl datasets")
    parser.add_argument("--format", choices=["chat", "alpaca", "sharegpt"], default="chat", help="Dataset schema format")
    parser.add_argument("--min-score", type=int, default=0, help="Minimum human feedback score (default: 0)")
    parser.add_argument("--no-learnings", action="store_true", help="Exclude system learnings table")
    parser.add_argument("--split", type=float, default=0.9, help="Train/eval split ratio (default: 0.9)")

    args = parser.parse_args()
    summary = prepare_dataset(
        db_path=args.db,
        output_dir=args.output_dir,
        fmt=args.format,
        min_score=args.min_score,
        include_learnings=not args.no_learnings,
        split_ratio=args.split
    )

    print(json.dumps(summary, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
