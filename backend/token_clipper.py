"""
backend/token_clipper.py
Dynamischer Token-Clipper für Low-Context-Modelle (Pillar 5 / Routing).
Schützt kleine oder lokale Modelle mit begrenztem Kontext vor Überläufen,
indem Kerninformationen erhalten und unkritische Zwischenschritte gestrafft werden.
"""

from typing import List, Dict, Tuple

def clip_messages_to_limit(messages: List[Dict], max_tokens: int = 8000) -> Tuple[List[Dict], bool, int, int]:
    """
    Kürzt eine Konversationshistorie intelligent auf das gegebene Token-Limit.
    Berücksichtigt den Schalter token_clipper_enabled in settings.json.
    Gibt (bereinigte_messages, wurde_gekürzt, originale_tokens, neue_tokens) zurück.
    """
    if not messages:
        return messages, False, 0, 0

    def _calc_tokens(msgs):
        return sum(len(str(m.get("content", ""))) // 4 for m in msgs)

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

    sys_msg = dict(messages[0])
    last_turn = dict(messages[-1])
    
    max_last_turn_tokens = max(50, max_tokens - (_calc_tokens([sys_msg])))
    last_content = str(last_turn.get("content", ""))
    if len(last_content) // 4 > max_last_turn_tokens:
        char_cutoff = max_last_turn_tokens * 4
        last_turn["content"] = last_content[:char_cutoff] + " ... [Token-Clipper: Nachricht gestrafft]"

    middle_msgs = messages[1:-1]
    remaining_tokens = max(0, max_tokens - _calc_tokens([sys_msg, last_turn]))

    kept_middle = []
    acc = 0
    for m in reversed(middle_msgs):
        m_tok = len(str(m.get("content", ""))) // 4
        if acc + m_tok <= remaining_tokens:
            kept_middle.insert(0, m)
            acc += m_tok
        else:
            break

    clipped = [sys_msg] + kept_middle + [last_turn]
    new_tokens = _calc_tokens(clipped)

    return clipped, True, orig_tokens, new_tokens
