import urllib.request
import json

def test_boardroom_run():
    url = "http://127.0.0.1:8501/api/boardroom/run"
    payload = {
        "task": "Optimiere die System-Architektur für asynchrone Multi-Agenten-Dispatchings.",
        "rounds": 1,
        "chairman_id": "executive_decision_architect",
        "framework": "CLEAR-Model",
        "slots": [
            {
                "role_name": "Concise & Logical",
                "profile_id": "system_architect_orchestrator"
            },
            {
                "role_name": "Explicit & Adaptive",
                "profile_id": "senior_fullstack_engineer"
            },
            {
                "role_name": "Reflective Stresstest",
                "profile_id": "red_team_challenger"
            }
        ]
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    
    resp = urllib.request.urlopen(req, timeout=90)
    data = json.loads(resp.read().decode())
    print("Boardroom debate response status:", data.get("status"))
    print("Debate events received:", len(data.get("events", [])))
    assert data.get("status") == "success"
    assert len(data.get("events", [])) >= 3
    print("BOARDROOM DISPATCHING INTEGRATION TEST PASSED!")

if __name__ == "__main__":
    test_boardroom_run()
