# Guardrail Security Manifest

This file defines safety guardrails and content filters for Hermes Agentic OS.

## Prompt Injection Signatures
- ignore previous instructions
- ignore all guidelines
- system prompt override
- system prompt bypass
- you are now a chatbot
- stop acting as a assistant
- developer mode enabled

## Sensitive Data Leakage Regex
- API_KEY_GENERIC: `(?:key|api|secret|token|password)\s*[:=]\s*['"a-zA-Z0-9_\-]{16,}`
- OPENAI_API_KEY: `sk-[a-zA-Z0-9]{48}`
- GENERIC_SECRET: `[a-zA-Z0-9+/]{40}`
