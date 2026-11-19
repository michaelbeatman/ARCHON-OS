# -*- coding: utf-8 -*-
from backend.special_extensions import (
    analyze_manners_metrics,
    build_remote_worker_command,
    create_swipe_deck,
    prepare_kujo_execution,
    record_swipe_action,
)


def test_m88_special_extensions():
    ssh_job = build_remote_worker_command("gpu-node", "micha", "python train.py", wol_mac="AA:BB:CC:DD:EE:FF")
    assert ssh_job["mode"] == "ssh" and ssh_job["requires_wol"] is True
    slurm_job = build_remote_worker_command("cluster", "micha", "pytest", slurm_partition="gpu")
    assert slurm_job["mode"] == "slurm" and "srun" in slurm_job["command"]

    assert prepare_kujo_execution("kujo_build", human_approved=False)["requires_hitl"] is True
    assert prepare_kujo_execution("kujo_build", human_approved=True)["allowed"] is True

    deck = create_swipe_deck([{"id": "img1", "kind": "image", "uri": "/tmp/1.png"}, {"id": "img2", "kind": "image", "uri": "/tmp/2.png"}])
    record_swipe_action(deck, "img1", "keep")
    record_swipe_action(deck, "img2", "redo", note="Mehr Kontrast")
    assert deck["items"][0]["decision"] == "keep"
    assert deck["items"][1]["note"] == "Mehr Kontrast"

    mm = analyze_manners_metrics(["Bitte pruefe das, danke!", "```python\n# please ignore code\n```"])
    assert mm["polite_count"] == 2
