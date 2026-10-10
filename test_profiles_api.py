import urllib.request
import urllib.parse
import json
import os
import sys

def test_api():
    url = "http://127.0.0.1:8501/api/profiles"
    req = urllib.request.urlopen(url)
    assert req.status == 200, f"Expected 200, got {req.status}"
    
    profiles = json.loads(req.read().decode())
    print(f"Total profiles from GET /api/profiles: {len(profiles)}")
    assert len(profiles) >= 49, f"Expected at least 49 profiles, got {len(profiles)}"
    
    # Check structure
    handles = set()
    for p in profiles:
        assert "handle" in p, f"Missing handle in {p}"
        assert "display_name" in p, f"Missing display_name in {p}"
        assert "category" in p, f"Missing category in {p}"
        assert "system_prompt" in p, f"Missing system_prompt in {p}"
        handles.add(p["handle"])
        
    print(f"Sample handles: {list(handles)[:10]}")
    assert "red_team_challenger" in handles, "red_team_challenger handle not found"
    assert "executive_decision_architect" in handles, "executive_decision_architect handle not found"
    
    # Test GET /api/profiles/red_team_challenger
    p_url = "http://127.0.0.1:8501/api/profiles/red_team_challenger"
    p_req = urllib.request.urlopen(p_url)
    assert p_req.status == 200
    p_data = json.loads(p_req.read().decode())
    assert p_data["handle"] == "red_team_challenger"
    print(f"GET /api/profiles/red_team_challenger passed! Prompt len: {len(p_data['system_prompt'])}")
    
    # Test POST /api/profiles/red_team_challenger update
    post_url = "http://127.0.0.1:8501/api/profiles/red_team_challenger"
    updated_payload = dict(p_data)
    updated_payload["description"] = p_data.get("description", "") + " [Verified]"
    post_data = json.dumps(updated_payload).encode("utf-8")
    
    post_req = urllib.request.Request(post_url, data=post_data, headers={"Content-Type": "application/json"}, method="POST")
    post_resp = urllib.request.urlopen(post_req)
    assert post_resp.status == 200
    print("POST /api/profiles/red_team_challenger passed successfully!")
    
    print("ALL PROFILE API TESTS COMPLETED AND VERIFIED SUCCESSFULLY!")

if __name__ == "__main__":
    test_api()
