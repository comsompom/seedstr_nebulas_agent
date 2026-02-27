# Flask App Wrapper for 24/7 Hosting

This folder contains a standalone Flask wrapper that runs your existing Seedstr agent loop in a background thread while exposing a web health endpoint for hosts like Render.

## What this wrapper does

- Starts your existing agent (`seedstr_agent.runner.AgentRunner`) in a background thread.
- Exposes:
  - `GET /` (health + auto-start worker on first request)
  - `GET /healthz` (health payload)
- Lets you deploy as a Web Service even though your core workload is a background poller.

## Prerequisites

- Python 3.11+
- A valid `.env` in repository root with your Seedstr and LLM keys.

Example required values:

- `SEEDSTR_API_KEY`
- `SEEDSTR_BASE_URL=https://www.seedstr.io/api/v2`
- `GEMINI_API_KEY` or `OPENAI_API_KEY`
- `GEMINI_MODELS` and/or `OPENAI_MODELS`

## Run locally

From repository root:

```bash
pip install -r requirements.txt
python -m flask_app.app
```

Health check:

```bash
curl http://127.0.0.1:5000/
```

## Deploy on Render (free web service approach)

1. Push this repository to GitHub.
2. In Render, create a new **Web Service**.
3. Configure:
   - Runtime: Python
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python -m flask_app.app`
4. Add environment variables in Render (same values as `.env`, never commit secrets).
5. Deploy.

After deploy, hit `https://<your-service>.onrender.com/` and verify `ok: true`.

## Keep-alive monitor (optional)

Free Render instances can sleep on inactivity. To reduce sleeping:

- Use a monitor service (for example, UptimeRobot)
- Ping `GET /` every 5 minutes

## Notes

- This approach is best-effort on free tiers; true always-on behavior is not guaranteed by free hosting.
- For reliable nonstop runtime, use a VM with process supervision (`systemd`) and restart policies.

