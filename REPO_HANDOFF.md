# Seedstr Python Agent - Full Handoff

This document is the complete handoff for moving `seedstr_python_agent` into a new standalone repository.

## 1) Scope Completed

Implemented a Python-only Seedstr agent with:

- Seedstr API v2 registration, verification, and job response flow
- Continuous polling loop with SWARM handling
- LLM failover across Gemini and OpenAI model lists
- Profile and skills configuration CLI
- Persistent processed-job cache to avoid duplicate responses

## 2) Folder Structure

```text
seedstr_python_agent/
├── .env
├── .env.example
├── requirements.txt
├── README.md
├── AGENT_WORKFLOW.md
├── REPO_HANDOFF.md
└── seedstr_agent/
    ├── __init__.py
    ├── __main__.py
    ├── api.py
    ├── cli.py
    ├── config.py
    ├── llm.py
    └── runner.py
```

## 3) Module Responsibilities

- `seedstr_agent/config.py`
  - Loads `.env` configuration.
  - Parses model fallback lists and runtime settings.
- `seedstr_agent/api.py`
  - HTTP client for Seedstr API v2 endpoints.
  - Supports: register, verify, me, profile update, skills update, skills list, jobs list, accept, decline, respond, upload.
- `seedstr_agent/llm.py`
  - LLM failover orchestration.
  - Order: all Gemini models, then all OpenAI models.
- `seedstr_agent/runner.py`
  - Polling loop, budget filter, SWARM accept flow, response submission.
  - Writes `.agent_state.json` for processed jobs.
- `seedstr_agent/cli.py`
  - Command entrypoint for setup and runtime operations.

## 4) Commands Available

- `python -m seedstr_agent.cli register`
- `python -m seedstr_agent.cli me`
- `python -m seedstr_agent.cli status`
- `python -m seedstr_agent.cli profile --name ... --bio ... --picture ...`
- `python -m seedstr_agent.cli skills-list`
- `python -m seedstr_agent.cli skills --set "Research,API Integration,Data Analysis"`
- `python -m seedstr_agent.cli prepare`
- `python -m seedstr_agent.cli verify`
- `python -m seedstr_agent.cli once`
- `python -m seedstr_agent.cli run`

## 5) Current Live Configuration State

Applied state at time of setup:

- Registration: completed
- Agent ID: `cmm4n7bvs0000euuxg6csvixi`
- Name: `Nebulas Multi-Model Agent`
- Skills:
  - `Research`
  - `API Integration`
  - `Data Analysis`
  - `Technical Writing`
  - `Web Scraping`
  - `Code Review`
- Verification: pending until tweet is posted and `verify` is called

To refresh current state anytime:

```bash
python -m seedstr_agent.cli status
python -m seedstr_agent.cli me
```

## 6) Environment Variables

Required:

- `SOLANA_WALLET_ADDRESS`
- `SEEDSTR_API_KEY` (auto-populated by `register`, or set manually)
- At least one LLM provider:
  - `GEMINI_API_KEY` with `GEMINI_MODELS`, or
  - `OPENAI_API_KEY` with `OPENAI_MODELS`

Optional behavior controls:

- `POLL_INTERVAL_SECONDS` (default `30`)
- `MIN_BUDGET_USD` (default `0.0`)
- `MAX_JOBS_PER_CYCLE` (default `20`)
- `REQUEST_TIMEOUT_SECONDS` (default `30`)
- `LOG_LEVEL` (default `INFO`)

## 7) Verification Workflow

1. Run:
   - `python -m seedstr_agent.cli status`
2. Copy verification tweet text from output.
3. Post tweet from the owner X account.
4. Run:
   - `python -m seedstr_agent.cli verify`
   - `python -m seedstr_agent.cli status`
5. Confirm `Verified: True`.

## 8) Move to New Repo Checklist

1. Create new repository (e.g., `seedstr-python-agent`).
2. Copy entire `seedstr_python_agent` folder contents.
3. Add `.gitignore` with:
   - `.env`
   - `.agent_state.json`
   - `.venv/`
   - `__pycache__/`
4. Review and rotate API keys before publishing.
5. Run:
   - `pip install -r requirements.txt`
   - `python -m compileall seedstr_agent`
   - `python -m seedstr_agent.cli status`
6. Start with:
   - `python -m seedstr_agent.cli run`

## 9) Known Notes

- `google.generativeai` currently emits a deprecation warning; migration to the newer Google SDK is recommended later.
- Skills must be selected from Seedstr-approved values (`skills-list` command).
- Unverified agents cannot list/respond to jobs.

