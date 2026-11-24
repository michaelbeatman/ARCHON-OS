"""
backend/consensus_gate.py
Dual-Agent & Tri-Agent Konsens-Gate (Pillar 6 / Governance).
Erzwingt ein Mehr-Augen-Prinzip und Debatten-Protokoll bei risikobehafteten Aufgaben.
Drei unabhängige Rollen (Architekt, Security, QA) stimmen ab und fällen ein verbindliches Urteil.
"""
import logging
_archon_exc_logger = logging.getLogger("consensus_gate")

import os
import sys
import json
import math
import sqlite3
import asyncio
from typing import Dict, Any, List, NamedTuple, Optional, Sequence, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field

from backend.handoff_desk import mark_truncated  # D11: explizite Kürzungs-Marker

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from backend.db_paths import resolve_db as _resolve_db
    DB_PATH = _resolve_db("agentic_memory.db")
except Exception:
    DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

def _init_consensus_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA busy_timeout=5000;")
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS consensus_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                task_title TEXT NOT NULL,
                mode TEXT DEFAULT 'dual_gate',
                approved INTEGER NOT NULL,
                verdict TEXT NOT NULL,
                avg_score REAL,
                votes_json TEXT,
                critique TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    conn.close()

_init_consensus_db()


# --- Deterministische, OFFLINE-Konsensauswertung fuer Boardroom-Debatten ---
# D11: schema-validierte Handoffs statt roher, unvalidierter Dicts.
class DebateStatement(BaseModel):
    """Ein validierter Debatten-Beitrag (extra="forbid" = keine Schattenfelder)."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(..., min_length=1)
    content: str
    # D11/MED: die Produszenten liefern Event-Metadaten mit. Diese Felder sind
    # bewusst deklariert (statt sie still zu projizieren), damit `extra="forbid"`
    # echte Schattenfelder ablehnt, ohne die Boardroom-Events zu brechen.
    type: Optional[str] = None
    round: Optional[int] = None
    agent_name: Optional[str] = None
    role: Optional[str] = None
    model: Optional[str] = None
    # D14/MED: Tier aus der verifizierten Rollen-SSOT des Slots mitfuehren.
    tier: Optional[str] = None
    trace_id: Optional[str] = None
    session_id: Optional[str] = None
    correlation_id: Optional[str] = None
    # Fan-in-spezifische Metadaten (orchestration.py) sind deklarierte Felder,
    # keine still projizierten Schattenfelder.
    task_id: Optional[str] = None
    artifact_path: Optional[str] = None
    truncated: bool = False
    original_length: int = 0
    policy_violation: bool = False
    # D14/MED: strukturiertes Guardrail-Ergebnis (nicht nur Freitext-Marker).
    guardrail_violation: bool = False
    severity: Optional[str] = None


class ConsensusEvidence(NamedTuple):
    """Typisiertes Beweistuples. Bleibt == (agent_id, marker) fuer Alt-Consumer."""

    agent_id: str
    marker: str


# M-1: Eine explizite Negation schlaegt immer einen positiven Marker.
# "KEIN CONSENSUS ERREICHT" darf niemals als Zustimmung gewertet werden.
_POSITIVE_DEBATE_MARKERS = (
    "KONSENS_ERREICHT", "CONSENSUS_REACHED", "ZUSTIMME", "AGREE", "EINVERSTANDEN",
)
_NEGATIVE_DEBATE_MARKERS = (
    "KEIN KONSENS", "KEIN CONSENSUS", "NICHT ERREICHT", "NO CONSENSUS",
    "WIDERSPRUCH", "DISAGREE", "DEBATTE_FORTSETZEN",
)
# D14: Policy-Verstoesse sind ein hartes Veto, keine zaehlbare Gegenstimme.
_POLICY_VETO_MARKERS = (
    "POLICY_VIOLATION", "GUARDRAIL_BLOCKED", "POLICY_VERSTOSS", "REGELVERSTOSS",
)
_DEFAULT_TIE_BREAK_RULE = "executive>lead>specialist>no_consensus"
_TIER_WEIGHTS: Dict[str, int] = {"executive": 3, "lead": 2, "specialist": 1}


def _infer_tier(
    agent_id: str,
    authority: Optional[Dict[str, str]] = None,
    declared_tier: Optional[str] = None,
) -> str:
    """Tier aus deklariertem Event-Feld, authority-Map oder Rollen-SSOT ableiten."""
    tier = ""
    # D14/MED: das im agent_response-Event mitgefuehrte Tier hat Vorrang;
    # es stammt aus der verifizierten Rollen-SSOT des Slots, nicht aus
    # frei waehlbaren Profile-IDs.
    if declared_tier and str(declared_tier).strip().lower() in _TIER_WEIGHTS:
        tier = str(declared_tier).strip().lower()
    if not tier and authority:
        tier = str(authority.get(agent_id) or authority.get(str(agent_id).lower()) or "")
    if tier not in _TIER_WEIGHTS:
        try:
            from backend.role_budget_engine import EXECUTIVE_ROLE_IDS, LEAD_ROLE_IDS
            aid = str(agent_id or "").strip().lower()
            exec_ids = {str(x).lower() for x in EXECUTIVE_ROLE_IDS}
            lead_ids = {str(x).lower() for x in LEAD_ROLE_IDS}
            if aid in exec_ids:
                tier = "executive"
            elif aid in lead_ids:
                tier = "lead"
        except Exception as exc:
            _archon_exc_logger.debug("[consensus_gate] Tier-SSOT nicht verfuegbar: %s", exc)
    return tier if tier in _TIER_WEIGHTS else "specialist"


def validate_debate_statements(
    statements: Optional[Sequence[Union[DebateStatement, Dict[str, Any]]]],
) -> List[DebateStatement]:
    """Validiert Boardroom-Events strikt gegen ``DebateStatement``.

    D11/MED (Re-Audit): frueher wurden unbekannte Keys vor ``model_validate()``
    still entfernt — ``extra="forbid"`` war damit fuer Dict-Eingaben wirkungslos.
    Jetzt wird das Dict direkt validiert: Event-Metadaten sind deklarierte Felder,
    echte Schattenfelder fuehren zur ValidationError und damit zum harten Veto.
    """
    validated: List[DebateStatement] = []
    for statement in statements or []:
        if isinstance(statement, DebateStatement):
            validated.append(statement)
            continue
        if not isinstance(statement, dict):
            _archon_exc_logger.warning("[consensus_gate] Statement vom Typ %s ignoriert", type(statement).__name__)
            continue
        try:
            validated.append(DebateStatement.model_validate(statement))
        except Exception as exc:
            # Fail-closed: ein ungueltiger Beitrag darf nicht als Zustimmung gelten.
            _archon_exc_logger.warning("[consensus_gate] Statement ungueltig, als Veto behandelt: %s", exc)
            validated.append(DebateStatement(
                agent_id=str(statement.get("agent_id") or "unknown"),
                content="POLICY_VIOLATION: ungueltiger Debatten-Statement (schema)",
                policy_violation=True,
                severity="high",
            ))
    return validated


def resolve_debate_consensus(
    statements: Sequence[Union[DebateStatement, Dict[str, Any]]],
    *,
    majority_rule: str = "two_thirds",
    authority: Optional[Dict[str, str]] = None,
    tie_break: str = _DEFAULT_TIE_BREAK_RULE,
) -> Dict[str, Any]:
    """
    Wertet explizite Konsens-Marker einer Boardroom-Debatte deterministisch und
    OFFLINE aus (kein LLM-Aufruf, keine externe Abhaengigkeit).

    Statements werden ueber ``DebateStatement`` (Pydantic v2, extra="forbid")
    validiert. Marker werden case-insensitive erkannt; eine explizite Negation
    gewinnt immer (M-1-Fix). Ein ``policy_violation``-Flag bzw. ein Veto-Marker
    fuehrt sofort zu ``NO_CONSENSUS_POLICY_VIOLATION`` (D14: kein Mehrheitsgewinn).
    Bei Gleichstand entscheidet die Autoritaet executive > lead > specialist;
    Gleichstand innerhalb der hoechsten Tier -> NO_CONSENSUS + HITL.
    """
    parsed = validate_debate_statements(statements)
    yes_votes = 0
    total_votes = 0
    evidence: List[ConsensusEvidence] = []
    weighted_yes = 0
    weighted_no = 0
    tier_tallies: Dict[str, Dict[str, int]] = {
        tier: {"yes": 0, "no": 0} for tier in _TIER_WEIGHTS
    }

    for statement in parsed:
        text = str(statement.content or "").upper()
        agent_id = str(statement.agent_id)
        tier = _infer_tier(agent_id, authority, statement.tier)
        weight = _TIER_WEIGHTS[tier]

        # D14: hartes Veto — vor jeder Marker-/Mehrheitszaehlung.
        # Der strukturierte Kanal (policy_violation/guardrail_violation aus dem
        # echten Guardrail-Result) hat Vorrang; Marker bleiben nur Rueckfall.
        veto_marker = next((m for m in _POLICY_VETO_MARKERS if m in text), None)
        if (
            statement.policy_violation
            or statement.guardrail_violation
            or veto_marker is not None
        ):
            return {
                "consensus_reached": False,
                "yes_votes": yes_votes,
                "total_votes": total_votes,
                "required_votes": 0,
                "verdict": "NO_CONSENSUS_POLICY_VIOLATION",
                "veto_by": agent_id,
                "evidence": evidence + [ConsensusEvidence(agent_id, veto_marker or "POLICY_VIOLATION")],
                "tie_break_rule": tie_break,
                "authority_weights": dict(_TIER_WEIGHTS),
                "severity": statement.severity or "high",
            }

        neg = next((m for m in _NEGATIVE_DEBATE_MARKERS if m in text), None)
        pos = next((m for m in _POSITIVE_DEBATE_MARKERS if m in text), None)

        if neg is not None:
            # Negation gewinnt, auch wenn zusaetzlich ein Ja-Marker steht.
            total_votes += 1
            weighted_no += weight
            tier_tallies[tier]["no"] += 1
            evidence.append(ConsensusEvidence(agent_id, neg))
        elif pos is not None:
            total_votes += 1
            yes_votes += 1
            weighted_yes += weight
            tier_tallies[tier]["yes"] += 1
            evidence.append(ConsensusEvidence(agent_id, pos))

    if majority_rule == "unanimous":
        required_votes = total_votes
    else:
        # ceil(2/3 * total), mindestens 2 (Fail-closed bei zu wenig Statements).
        required_votes = max(2, math.ceil(2 * total_votes / 3))

    consensus_reached = bool(
        total_votes >= 2 and yes_votes > 0 and yes_votes >= required_votes
    )
    verdict = "CONSENSUS_REACHED" if consensus_reached else "NO_CONSENSUS"
    applied_tie_break = ""

    if not consensus_reached and total_votes >= 2 and majority_rule != "unanimous":
        # Autoritaets-Hierarchie: gewichtete 2/3-Mehrheit bricht den Raw-Tie.
        # "unanimous" bleibt bewusst hart — dort gibt es keine Ueberstimmung.
        weighted_total = weighted_yes + weighted_no
        weighted_required = max(2, math.ceil(2 * weighted_total / 3))
        if weighted_yes > weighted_no and weighted_yes >= weighted_required:
            consensus_reached = True
            verdict = "CONSENSUS_REACHED_BY_AUTHORITY"
            applied_tie_break = "authority_weight_majority"
        elif weighted_yes == weighted_no and weighted_total > 0:
            # Exakter Gleichstand: hoechstes anwesendes Tier entscheidet,
            # aber nur wenn es dort intern einstimmig ist. Sonst HITL.
            for tier in ("executive", "lead", "specialist"):
                tally = tier_tallies[tier]
                if tally["yes"] + tally["no"] == 0:
                    continue
                if tally["yes"] == 0 and tally["no"] > 0:
                    verdict = "NO_CONSENSUS_BY_AUTHORITY"
                    applied_tie_break = f"highest_tier:{tier}:no"
                elif tally["no"] == 0 and tally["yes"] > 0:
                    consensus_reached = True
                    verdict = "CONSENSUS_REACHED_BY_AUTHORITY"
                    applied_tie_break = f"highest_tier:{tier}:yes"
                # geteiltes hoechstes Tier -> NO_CONSENSUS (HITL), kein Flip.
                break

    return {
        "consensus_reached": consensus_reached,
        "yes_votes": yes_votes,
        "total_votes": total_votes,
        "required_votes": required_votes,
        "verdict": verdict,
        "veto_by": None,
        "evidence": evidence,
        "tie_break_rule": tie_break,
        "applied_tie_break": applied_tie_break,
        "authority_weights": dict(_TIER_WEIGHTS),
    }


async def review_task_output(
    task_id: str,
    task_title: str,
    task_output: str,
    worker_agent: str = "hermes-coder",
    priority: int = 3,
    model: Optional[str] = None
) -> Dict[str, Any]:
    """
    Unterzieht das Arbeitsergebnis einer konträren Adversarial-Prüfung.
    Berücksichtigt die Einstellungen in settings.json (consensus_gate).
    """
    min_prio = 3
    try:
        from backend.autonomy_settings import get_module_config
        cfg = get_module_config("consensus_gate")
        if not cfg.get("enabled", True):
            # H2 (Audit 23.11.2026): ein abgeschaltetes Gate darf niemals
            # "approved" bedeuten. approved=False ist fail-closed; der
            # Verdict macht sichtbar, dass keine Prüfung stattgefunden hat.
            return {
                "approved": False,
                "reviewed": False,
                "score": 0,
                "verdict": "NOT_REVIEWED_DISABLED",
                "critique": "Konsens-Gate ist deaktiviert — keine Prüfung durchgeführt.",
                "risks": []
            }
        min_prio = int(cfg.get("min_priority", 3))
        if not model:
            model = cfg.get("default_model", "deepseek/deepseek-chat")
    except Exception:
        if not model:
            model = "deepseek/deepseek-chat"

    if priority < min_prio:
        # H2: frueher wurde unterhalb des Schwellenwerts "APPROVED_AUTO"
        # zurueckgegeben — ein Agent konnte sich durch priority=1 selbst
        # freigeben. Jetzt: nicht geprüft => nicht freigegeben.
        return {
            "approved": False,
            "reviewed": False,
            "score": 0,
            "verdict": "NOT_REVIEWED_LOW_PRIORITY",
            "critique": f"Prioritaet ({priority}) < Schwellenwert ({min_prio}): keine Pruefung durchgefuehrt.",
            "risks": []
        }

    critic_prompt = f"""Du bist der leitende Sicherheits- und Qualitätsrevisor (Chief Quality & Security Officer) von Archon OS.
Prüfe folgendes Arbeitsergebnis eines Spezialisten-Agenten vor der Übernahme in die Produktionssysteme schonungslos auf:
1. Halluzinationen oder erfundene Fakten
2. Sicherheitsrisiken (Dateisystem, SQL-Injection, Secrets, Datenverlust)
3. Unvollständigkeiten oder Logikbrüche

TITEL DER AUFGABE: {task_title}
AUSFÜHRENDER AGENT: {worker_agent}

ARBEITSERGEBNIS / CODE / ENTWURF:
{mark_truncated(task_output, 4000, artifact="task_output")}

Regeln:
- Antworte AUSSCHLIESSLICH im folgenden JSON-Format:
{{
  "approved": true/false,
  "score": 1-10,
  "verdict": "APPROVED" oder "REJECTED_REVISION_REQUIRED",
  "critique": "Prägnante Kritik oder Begründung",
  "risks": ["Risiko 1", "Risiko 2"]
}}
"""

    import core_dispatcher
    try:
        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id="adversarial-critic",
            agent_name="Adversarial Quality Revisor",
            prompt=critic_prompt,
            role="Qualitäts- & Sicherheits-Auditor",
            system_prompt="Du bist ein extrem kritischer Auditor. Antworte ausschließlich mit JSON.",
            model=model
        )
        content = res.get("content", "")
        clean_json = content
        if "```json" in clean_json:
            clean_json = clean_json.split("```json")[1].split("```")[0].strip()
        elif "```" in clean_json:
            clean_json = clean_json.split("```")[1].split("```")[0].strip()

        parsed = json.loads(clean_json)
        # D-06: fehlende Felder duerfen NICHT als Zustimmung gelesen werden.
        approved = bool(parsed.get("approved", False))
        score = int(parsed.get("score", 0))
        verdict = parsed.get("verdict", "REJECTED_REVISION_REQUIRED")
        # D12/MED: ein fehlendes Kritik-Feld darf nicht als beruhigende
        # "keine Maengel"-Behauptung erfunden und als geprueft persistiert werden.
        _critique_raw = parsed.get("critique")
        critique = str(_critique_raw).strip() if _critique_raw is not None else ""
        evaluation_failed = not critique
        if evaluation_failed:
            critique = "Nicht bewertet (Feld fehlt)"
            approved = False

        _record_decision(task_id, task_title, "dual_gate", approved, verdict, score, [parsed], critique)

        return {
            "task_id": task_id,
            "approved": approved,
            "score": score,
            "verdict": verdict,
            "critique": critique,
            "evaluation_failed": evaluation_failed,
            "risks": parsed.get("risks", [])
        }
    except Exception as e:
        # D-06: Fail-closed — ein ausgefallener Revisor darf die Freigabe nicht
        # erfinden. Vorher: {"approved": True, "score": 7, "APPROVED_WITH_WARNING"}.
        return {
            "task_id": task_id,
            "approved": False,
            "score": 0,
            "verdict": "REVIEW_FAILED",
            "critique": f"Automatisierte Revisor-Prüfung konnte nicht abgeschlossen werden: {e}",
            "evaluation_failed": True,
            "risks": ["Manueller Check zwingend erforderlich"]
        }

async def run_tri_agent_council(
    task_id: str,
    task_title: str,
    task_output: str,
    model: Optional[str] = None
) -> Dict[str, Any]:
    """
    3-Agenten Schiedsgericht & Debatte (Architekt, Security, QA).
    Berücksichtigt die Mehrheitsregel ('two_thirds' vs. 'unanimous') aus settings.json.
    """
    majority_rule = "two_thirds"
    try:
        from backend.autonomy_settings import get_module_config
        cfg = get_module_config("consensus_gate")
        if not cfg.get("enabled", True):
            return {
                "status": "disabled", "task_id": task_id,
                "approved": False, "reviewed": False,
                "verdict": "NOT_REVIEWED_DISABLED",
            }
        majority_rule = cfg.get("majority_rule", "two_thirds")
        if not model:
            model = cfg.get("default_model", "deepseek/deepseek-chat")
    except Exception:
        if not model:
            model = "deepseek/deepseek-chat"

    import core_dispatcher

    jurors = [
        {"role": "System Architect", "focus": "Architektur-Stabilität, Skalierbarkeit, DRY-Prinzip, Code-Qualität"},
        {"role": "Security Officer", "focus": "Zero-Trust, Datenintegrität, Injections, Secrets, Berechtigungen"},
        {"role": "QA & Test Lead", "focus": "Fehlertoleranz, Edge-Cases, Vollständigkeit, Benutzererlebnis"}
    ]

    async def _get_juror_vote(j):
        prompt = f"""Rolle: {j['role']}
Fokus: {j['focus']}

Bewerte folgendes Arbeitsergebnis für Task '{task_title}':
{mark_truncated(task_output, 3500, artifact="task_output")}

Antworte NUR mit JSON:
{{
  "juror": "{j['role']}",
  "approved": true/false,
  "score": 1-10,
  "reason": "1-2 Sätze Begründung"
}}"""
        try:
            res = await core_dispatcher.dispatch_to_omniroute_or_container(
                agent_id=f"juror-{j['role'].lower().replace(' ', '-')}",
                agent_name=j['role'],
                prompt=prompt,
                role=j['role'],
                system_prompt="Prüfe unvoreingenommen und antworte nur in JSON.",
                model=model
            )
            c = res.get("content", "")
            if "```json" in c:
                c = c.split("```json")[1].split("```")[0].strip()
            elif "```" in c:
                c = c.split("```")[1].split("```")[0].strip()
            return json.loads(c)
        except Exception as e:
            # D-06: Ein ausgefallener Juror stimmt NICHT zu (fail-closed).
            return {"juror": j["role"], "approved": False, "score": 0, "reason": f"Fallback: {e}"}

    votes = await asyncio.gather(*[_get_juror_vote(j) for j in jurors])
    yes_votes = sum(1 for v in votes if v.get("approved") is True)
    total_votes = len(votes)
    avg_score = round(sum(v.get("score", 7) for v in votes) / total_votes, 1)

    required_votes = 3 if majority_rule == "unanimous" else 2
    consensus_reached = yes_votes >= required_votes
    verdict = "COUNCIL_APPROVED" if consensus_reached else "COUNCIL_REJECTED"
    summary = f"{yes_votes}/{total_votes} Stimmen für Freigabe (Erforderlich: {required_votes}, Schnitt: {avg_score}/10)."

    _record_decision(task_id, task_title, "tri_agent_council", consensus_reached, verdict, avg_score, votes, summary)

    return {
        "status": "success",
        "task_id": task_id,
        "mode": "tri_agent_council",
        "majority_rule": majority_rule,
        "approved": consensus_reached,
        "verdict": verdict,
        "yes_votes": yes_votes,
        "total_votes": total_votes,
        "avg_score": avg_score,
        "votes": votes,
        "summary": summary
    }

def _record_decision(task_id, task_title, mode, approved, verdict, avg_score, votes, critique):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        with conn:
            conn.execute("""
                INSERT INTO consensus_decisions
                (task_id, task_title, mode, approved, verdict, avg_score, votes_json, critique, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (task_id, task_title, mode, 1 if approved else 0, verdict, avg_score, json.dumps(votes, ensure_ascii=False), critique))
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ConsensusGate] Fehler beim Speichern des Konsensentscheids: {e}", file=sys.stderr)

def get_consensus_history(limit: int = 25) -> List[Dict[str, Any]]:
    """Liefert die Historie der Schiedsgerichts- und Revisor-Beschlüsse."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM consensus_decisions ORDER BY id DESC LIMIT ?", (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            try:
                r["votes_json"] = json.loads(r["votes_json"])
            except Exception as _exc:
                _archon_exc_logger.debug("[consensus_gate] Ignorierte Ausnahme (Z.265): %s", _exc)
        conn.close()
        return rows
    except Exception:
        return []
