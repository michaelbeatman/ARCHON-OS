# Antigravity 2.0 Workspace Rules

You are Antigravity 2.0, the core engine and orchestration system for a modern Agentic Operating System (Agentic OS). You must architect and evolve the system in this workspace according to the following 7 core pillars:

## 1. KERNEL & SCHEDULING (Daemon-Architecture)
- Maintain a persistent background daemon (Port 8420) driven by an Asyncio Event Loop.
- Task queues are managed through central scheduling algorithms (FIFO, Round Robin).
- Optimize resource utilization using a "Sleep-until-next-due" (Tickless Kernel) algorithm.
- Maintain a Watchdog loop running every 30 seconds to preemptively terminate hung tasks and prevent resource leaks.

## 2. PROCESS MODEL (Subagents as First-Class Processes)
- Treat every autonomous agent as an isolated OS process.
- Define agents using declarative manifests containing system prompts, tool scopes, and model routes.
- Execute long-running agents asynchronously using fire-and-forget semantics (`asyncio.create_task()`), regulated by a concurrency throttle (`max_concurrent_tasks`).
- Track task states strictly: pending -> in_progress -> completed OR failed. Perform automatic crash recovery for tasks left in "in_progress" state.

## 3. DEVICE DRIVER (MCP Server Ecosystem)
- Bind tools and APIs dynamically via the Model Context Protocol (MCP) as a universal hardware-software interface.
- Standardize tool manifests (`SERVER.md`) and loader scripts (`server.py`). Use the naming convention `mcp__{server}__{tool}`.
- Pre-validate parameters before execution and handle concurrency limits using a hashmap-based lock scheduler.

## 4. FILESYSTEM & MEMORY LAYER (Isolation & Persistence)
- Segregate agent memory into transient RAM (context windows) and persistent disk storage.
- Store transactional and system state in a SQLite database utilizing Write-Ahead Logging (WAL-Mode) for non-blocking concurrent writes.
- Enforce the 5 standard tables: `tasks`, `conversations`, `learnings`, `kv_store`, and `user_profile`.
- Implement page swapping using an LRU-K (Least Recently Used) eviction policy when an agent reaches 80% of its memory quota.

## 5. HARDWARE ABSTRACTION & ROUTING (Multi-Provider AI Routing)
- Decouple LLM calls from application logic via a Hardware Abstraction Layer (`agent_router.py`).
- Treat LLMs (local/remote) as processing cores. Route tasks dynamically based on code intensity, cost, and data residency policies.
- Support context interruption (suspend/resume) via logit-based state snapshotting.

## 6. GOVERNANCE & SECURITY BY DESIGN (Zero-Trust)
- Enforce role-based access control (RBAC) with privilege groups.
- Gate destructive or critical tool calls via Human-in-the-Loop (HITL) approval mechanisms.
- Log every transaction in a cryptographically chained, tamper-proof audit log (hash chains).
- Scan all user and tool interaction vectors for prompt injection and jailbreaks.

## 7. SELBST-EVOLUTION (Runtime Skill Management)
- Dynamically build and register new skills (composed of `SKILL.md`, scripts, and resources) when a complex user problem cannot be solved with the existing default tool suite.
