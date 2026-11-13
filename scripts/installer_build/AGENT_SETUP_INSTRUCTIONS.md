# AGENTIC OS 2026 - SETUP MANIFEST FOR AI AGENTS
**TARGET AUDIENCE:** Claude Code, Cursor, Copilot, Antigravity or any autonomous orchestrator.

## SYSTEM ARCHITECTURE (THE 7 PILLARS)
1. **KERNEL & SCHEDULING:** Persistent background daemon on Port 8420.
2. **PROCESS MODEL:** Subagents as first-class asynchronous processes.
3. **DEVICE DRIVER:** MCP Server Ecosystem (Model Context Protocol).
4. **FILESYSTEM & MEMORY:** Persistent state via SQLite (WAL-Mode), transient memory with LRU-K caching.
5. **HARDWARE ABSTRACTION:** Dynamic multi-provider routing (OmniRoute).
6. **GOVERNANCE:** Zero-Trust, HITL, Hash-Chain Auditing.
7. **SELF-EVOLUTION:** Runtime skill management.

## YOUR MISSION (SETUP INSTRUCTIONS)
Human user expects YOU to set this up. Execute strictly in this order:

**PHASE 1: DEPENDENCY CHECK**
1. Check if `docker` and `docker-compose` are installed and running. If not, STOP and instruct the human to install Docker Desktop.
2. Check if `python 3.11+` is available.

**PHASE 2: SECRETS GATHERING**
1. Check if `.env` exists. If not, tell the user to double-click `setup.bat` (or run `python setup_wizard.py`). This will open a browser UI for them to securely enter API keys.
2. WAIT until the `.env` file is generated.

**PHASE 3: DATABASE INITIALIZATION**
1. Run `python core_dispatcher.py --init-db` (or equivalent setup script) to generate the empty SQLite schema (`tasks`, `conversations`, `learnings`, `kv_store`, `user_profile`).

**PHASE 4: BOOT**
1. Run `docker-compose up -d` to start OmniRoute, n8n, and supporting containers.
2. Run the main fastAPI backend/daemon.
3. Verify Port 8420 and 8501 are responding. Report readiness to the human.
