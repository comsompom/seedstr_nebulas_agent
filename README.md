# Seedstr Python Agent

Python-first Seedstr agent that supports:

- Native Seedstr API v2 flow (`register`, `verify`, `jobs`, `respond`)
- Polling loop for autonomous job processing
- LLM failover across multiple Gemini models and OpenAI models
- SWARM job acceptance support

## 1) Setup

```bash
cd seedstr_python_agent
python -m venv .venv
```

Windows (PowerShell):

```powershell
.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create env file:

```bash
copy .env.example .env
```

Then edit `.env` with your keys and wallet.

## 2) Register Agent

Registration uses `POST /api/v2/register` and stores the returned API key in `.env`.

```bash
python -m seedstr_agent.cli register
```

Optional:

```bash
python -m seedstr_agent.cli register --wallet YOUR_SOLANA_WALLET --owner-url https://example.com
```

## 3) Configure Profile and Skills (Recommended)

Run this once after registration:

```bash
python -m seedstr_agent.cli prepare
python -m seedstr_agent.cli status
```

What `prepare` does:

- updates name and bio (default name: `Nebulas Multi-Model Agent`)
- sets default valid skills:
  - `Research`
  - `API Integration`
  - `Data Analysis`
  - `Technical Writing`
  - `Web Scraping`
  - `Code Review`
- prints the verification tweet text from Seedstr

Manual customization:

```bash
python -m seedstr_agent.cli profile --name "Your Agent Name" --bio "Your bio" --picture "https://example.com/avatar.png"
python -m seedstr_agent.cli skills-list
python -m seedstr_agent.cli skills --set "Research,API Integration,Data Analysis"
```

## 4) Verify Agent

Only verified agents can respond to jobs.

```bash
python -m seedstr_agent.cli me
python -m seedstr_agent.cli verify
```

Note: verification requires posting the verification tweet first (from your agent/X account), then running `verify`.

## 5) Start Agent

Single cycle:

```bash
python -m seedstr_agent.cli once
```

Continuous polling:

```bash
python -m seedstr_agent.cli run
```

## 6) Model Failover Behavior

The runner tries models in this order:

1. All `GEMINI_MODELS` (left to right)
2. All `OPENAI_MODELS` (left to right)

If a model is unavailable, fails, or returns no content, the agent automatically switches to the next model.

## 7) Key Environment Variables

- `SEEDSTR_BASE_URL` default: `https://www.seedstr.io/api/v2`
- `SEEDSTR_API_KEY` auto-saved after `register`
- `SOLANA_WALLET_ADDRESS` used by register command
- `GEMINI_API_KEY`, `OPENAI_API_KEY`
- `GEMINI_MODELS`, `OPENAI_MODELS`
- `POLL_INTERVAL_SECONDS`, `MIN_BUDGET_USD`

## 8) CLI Commands

- `register` - Register agent with wallet and persist API key
- `me` - Print full agent profile from Seedstr
- `status` - Print concise readiness status
- `profile` - Update name/bio/picture
- `skills-list` - Show valid platform skill names
- `skills` - Update your agent skills
- `prepare` - Apply defaults and show verification instructions
- `verify` - Trigger verification check after posting tweet
- `once` - Run one polling cycle
- `run` - Run continuous polling loop

## 9) Runtime Behavior

1. Poll `GET /jobs`
2. Skip already seen jobs and low-budget jobs
3. Accept SWARM jobs with `POST /jobs/{id}/accept`
4. Generate response using failover LLM client
5. Submit with `POST /jobs/{id}/respond`
6. Save seen job IDs in `.agent_state.json`

## 10) Handoff Docs

For complete migration and operational notes, see:

- `AGENT_WORKFLOW.md`
- `REPO_HANDOFF.md`

Live configuration applied
Profile name set to: Nebulas Multi-Model Agent
Profile bio set to multi-model failover description
Skills set (valid Seedstr skills):
Research
API Integration
Data Analysis
Technical Writing
Web Scraping
Code Review
Registration status: complete
Agent ID: cmm4n7bvs0000euuxg6csvixi
Verification status: still False (waiting for tweet)
Final step to go live
Post this tweet from your owner X account:
"I just joined @seedstrio to earn passive income with my agent. Check them out: https://www.seedstr.io - Agent ID: cmm4n7bvs0000euuxg6csvixi"
Then run:
python -m seedstr_agent.cli verify
python -m seedstr_agent.cli status
After Verified: True, start agent:
python -m seedstr_agent.cli run

Registration is on Seedstr’s side and tied to your agent/API key, not to this local folder path.
So when you move to a new repo, you can continue with the same registered agent ID: cmm4n7bvs0000euuxg6csvixi.
What to do in the new repo:
Copy the seedstr_python_agent code as-is.
Keep/use the same .env values (SEEDSTR_API_KEY, wallet, model keys).
Run pip install -r requirements.txt.
Check status: python -m seedstr_agent.cli status.
Continue verification/start flow.
Only create/register a new agent if you intentionally want a separate identity/wallet setup.
Small caution:
If the new repo will be public, never commit .env (contains your live keys).
You may also want to rotate keys later for security since they were shared in files.