import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core_dispatcher
import main

def test_mastermind():
    # 1. Check prompt syntax & placeholders across all 55 frameworks
    fws = core_dispatcher.CATEGORIZED_FRAMEWORKS
    assert len(fws) == 9, f"Expected 9 categories, got {len(fws)}"
    total = sum(len(v) for v in fws.values())
    assert total == 55, f"Expected 55 frameworks, got {total}"

    for cat, items in fws.items():
        for name, prompt in items.items():
            assert not "[Symptom präzise beschreiben]" in prompt, f"Placeholder found in {name}"
            # Test subagent prompt compilation
            p_sub = core_dispatcher.build_final_system_prompt(name, "Base prompt", "Focus role", False)
            assert "[UNIVERSAL METHODOLOGY ENGINE HEADER]" in p_sub
            assert "[PROFILE_BASE_SOUL (FACHWISSEN & PERSONA)]" in p_sub
            assert "[SLOT_ROLE_DIMENSION (SPEZIFISCHER FOKUS)]" in p_sub
            # Test chair prompt compilation
            p_chair = core_dispatcher.build_final_system_prompt(name, "Base prompt", "", True)
            assert "[CHAIRMAN_MODERATION_DIRECTIVE]" in p_chair

    # 2. Check export file
    export_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mastermind_audit_export.md")
    with open(export_path, "r", encoding="utf-8") as f:
        export_content = f.read()

    assert export_content.count("```text") == 55, f"Expected 55 ```text fences, got {export_content.count('```text')}"
    assert "[Symptom präzise beschreiben]" not in export_content

    print("ALL TESTS PASSED: 55 Frameworks, Prompt-Hierarchie, Subagent-Slots und Markdown-Fences sind fehlerfrei!")

if __name__ == "__main__":
    test_mastermind()
