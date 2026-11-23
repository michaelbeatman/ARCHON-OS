"""P0 API-Validierung Etappe 2f: execution (11), gateway (4), resilience (3),
system (2), swarm (1) = 21 Endpunkte."""

import os
import sys

import pytest
from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archon.routers import execution, gateway, resilience, swarm, system  # noqa: E402


def test_execution_models_validate_types():
    with pytest.raises(ValidationError):
        execution.DurableCheckpointRequest(total_steps="viele")
    with pytest.raises(ValidationError):
        execution.QueueEnqueueRequest(priority="hoch")


def test_execution_checkpoint_keeps_state_dict():
    model = execution.DurableCheckpointRequest(state={"step": 1}, completed_steps=["a"])
    dumped = model.model_dump()
    assert dumped["state"] == {"step": 1}
    assert dumped["completed_steps"] == ["a"]


def test_gateway_models_validate_profile_and_timeout():
    with pytest.raises(ValidationError):
        gateway.GatewayStartRequest(profile_id=123)
    with pytest.raises(ValidationError):
        gateway.GatewayConfigRequest(idle_timeout_minutes="foo")


def test_resilience_and_swarm_models_validate():
    with pytest.raises(ValidationError):
        resilience.TraceForkRequest(from_step="eins")
    with pytest.raises(ValidationError):
        swarm.SwarmSpawnRequest(execute_dag="vielleicht")


def test_system_models_validate():
    with pytest.raises(ValidationError):
        system.WriteBatcherEnqueueRequest(event_type=["x"])
