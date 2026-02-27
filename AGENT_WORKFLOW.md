# Agent Workflow (Python Version)

This document describes expected runtime behavior for the Python agent.

## Core Loop

1. Load config from `.env`
2. Pull available jobs from Seedstr API v2
3. For each new job:
   - evaluate effective budget (`budgetPerAgent` for SWARM, else `budget`)
   - accept SWARM slots when needed
   - call LLM with automatic provider/model fallback
   - submit final text response
4. Persist processed jobs to avoid duplicate responses
5. Sleep for configured interval and repeat

## Failover Policy

Failover is deterministic and ordered:

1. Gemini model list (`GEMINI_MODELS`)
2. OpenAI model list (`OPENAI_MODELS`)

On any model exception (quota, outage, timeout, invalid response), the agent tries the next model.

## Registration and Verification

- Registration: `POST /register` with Solana wallet returns `apiKey`
- Verification: `POST /verify` after posting verification tweet
- `GET /me` used to inspect current account and verification status

## Reliability Notes

- API errors are handled and logged; polling continues on next cycle
- Job IDs are cached in `.agent_state.json` to prevent duplicate submits
- If acceptance fails for SWARM jobs, job is skipped safely

