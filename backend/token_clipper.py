"""
backend/token_clipper.py
Dynamischer Token-Clipper für Low-Context-Modelle (Pillar 5 / Routing).

Schützt kleine oder lokale Modelle mit begrenztem Kontext vor Überläufen.

Präzisionsregeln (nach Audit 05.11.2026):
1. ALLE führenden System-Nachrichten bleiben erhalten — dazu gehört auch der
   Block "[KONSOLIDIERTER GESPRÄCHS- & ENTSCHEIDUNGSKONTEXT]" aus der
   Kontextkompression. Vorher konnte genau dieser Block wegfallen.
2. Die letzte Nachricht bleibt erhalten (ggf. gekürzt).
3. Wird Verlauf ausgelassen, wird das EXPLIZIT als Systemhinweis markiert.
   Kein stilles Verschwinden von Kontext mehr — das Modell weiß, dass ältere
   Turns fehlen, und kann gezielt nachfragen.
"""

from typing import List, Dict, Tuple


def _calc_tokens(msgs: List[Dict]) -> int:
    return sum(len(str(m.get("content", ""))) // 4 for m in msgs)


def clip_messages_to_limit(messages: List[Dict], max_tokens: int = 8000) -> Tuple[List[Dict], bool, int, int]:
    """
    Kürzt eine Konversationshistorie auf das Token-Limit.
    Gibt (bereinigte_messages, wurde_gekürzt, originale_tokens, neue_tokens) zurück.
    """
    if not messages:
        return messages, False, 0, 0

    orig_tokens = _calc_tokens(messages)

    try:
        from backend.autonomy_settings import get_module_config
        cfg = get_module_config("circuit_breaker")
        if not cfg.get("token_clipper_enabled", True):
            return messages, False, orig_tokens, orig_tokens
    except Exception:
        pass

    if orig_tokens <= max_tokens:
        return messages, False, orig_tokens, orig_tokens

    rest = [dict(m) for m in messages]

    # 1) Führende System-Nachrichten unangetastet übernehmen
    leading_system: List[Dict] = []
    while rest and rest[0].get("role") == "system":
        leading_system.append(rest.pop(0))

    # Erste Nutzernachricht = Aufgabenstellung/Kontextanker: immer schützen
    pinned_first = None
    if len(rest) > 1:
        pinned_first = rest.pop(0)

    last_turn = rest.pop() if rest else None
    middle = rest

    budget = max_tokens - _calc_tokens(leading_system)
    if pinned_first is not None:
        budget -= _calc_tokens([pinned_first])

    # 2) Letzte Nachricht kappen, wenn sie allein zu groß ist
    if last_turn is not None:
        last_content = str(last_turn.get("content", ""))
        max_last_tokens = max(50, budget)
        if len(last_content) // 4 > max_last_tokens:
            last_turn = dict(last_turn)
            last_turn["content"] = last_content[: max_last_tokens * 4] + " ... [Token-Clipper: Nachricht gestrafft]"

    remaining = budget - (_calc_tokens([last_turn]) if last_turn else 0)

    # 3) Verlauf von hinten auffüllen
    kept_middle: List[Dict] = []
    acc = 0
    for m in reversed(middle):
        m_tok = len(str(m.get("content", ""))) // 4
        if acc + m_tok <= remaining:
            kept_middle.insert(0, m)
            acc += m_tok
        else:
            break

    dropped = len(middle) - len(kept_middle)
    clipped_messages: List[Dict] = list(leading_system)
    if pinned_first is not None:
        clipped_messages.append(pinned_first)
    if dropped > 0:
        clipped_messages.append({
            "role": "system",
            "content": (
                f"[Token-Clipper: {dropped} ältere Nachricht(en) ausgelassen, um das Kontextlimit "
                f"von {max_tokens} Tokens zu halten. Wenn Details daraus benötigt werden, frage gezielt nach.]"
            ),
        })
    clipped_messages.extend(kept_middle)
    if last_turn is not None:
        clipped_messages.append(last_turn)

    new_tokens = _calc_tokens(clipped_messages)
    return clipped_messages, True, orig_tokens, new_tokens
