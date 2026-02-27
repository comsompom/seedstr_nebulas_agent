Here is your step-by-step solution to run your agent 24/7 for free, **no credit card required**.

---

### Phase 1: Modify Your Code (Make it "Cloud Ready")

Render expects a Web Server (like a website), but you have a Background Script. We need to trick Render by running both.

1.  **Install Flask:**
    In your terminal, inside your project folder:
    ```bash
    pip install flask
    ```

2.  **Update `requirements.txt`:**
    Make sure your file looks like this (add flask):
    ```text
    requests
    google-generative-ai
    python-dotenv
    flask
    ```

3.  **Create a new file named `main.py`:**
    This will be the entry point. It runs your Agent in a background thread and a fake Web Server in the main thread.

    *(Copy this code exactly)*:
    ```python
    import threading
    import os
    from flask import Flask
    # Import your actual agent loop function
    # Assuming your agent file is named 'agent.py' and the function is 'run_agent'
    from agent import run_agent 

    app = Flask(__name__)

    @app.route('/')
    def health_check():
        # This is the URL the pinger will hit to keep us alive
        return "Agent is running!", 200

    def start_background_agent():
        try:
            print("Starting Agent Loop...")
            run_agent()
        except Exception as e:
            print(f"Agent crashed: {e}")

    if __name__ == "__main__":
        # 1. Start the Agent in a separate thread
        agent_thread = threading.Thread(target=start_background_agent)
        agent_thread.daemon = True # Kills thread if main program exits
        agent_thread.start()

        # 2. Start the Fake Web Server (This listens to the internet)
        port = int(os.environ.get("PORT", 5000))
        app.run(host='0.0.0.0', port=port)
    ```

4.  **Push these changes to GitHub.**

---

### Phase 2: Deploy to Render (The Free Server)

1.  Go to [dashboard.render.com](https://dashboard.render.com/) and Sign Up (Use your GitHub account). **No credit card needed.**
2.  Click **"New +"** -> **"Web Service"**.
3.  Select **"Build and deploy from a Git repository"**.
4.  Connect your **Seedstr/Agent repository**.
5.  **Configure the Service:**
    *   **Name:** `my-seedstr-agent`
    *   **Region:** Frankfurt (closest to Lithuania) or defaults.
    *   **Branch:** `main` or `master`.
    *   **Runtime:** Python 3.
    *   **Build Command:** `pip install -r requirements.txt`
    *   **Start Command:** `python main.py`
    *   **Instance Type:** **Free** (Scroll down to find the free option).
6.  **Environment Variables (Crucial):**
    *   Scroll down to "Environment Variables".
    *   Add your keys here (do NOT put them in GitHub):
        *   `SEEDSTR_API_KEY`: `your_key`
        *   `GEMINI_API_KEY`: `your_key`
        *   `SEEDSTR_BASE_URL`: `https://api.seedstr.io` (or whatever the endpoint is).
7.  Click **"Deploy Web Service"**.

*Wait about 2-3 minutes. You should see logs saying "Starting Agent Loop..." and "Running on http://0.0.0.0:xxxx".*

---

### Phase 3: Keep It Alive (The "Infinite Run" Trick)

Right now, Render will shut down your agent if no one visits the website for 15 minutes. We will use a free monitoring tool to visit the website for you automatically.

1.  **Get your URL:**
    *   On the Render dashboard, look at the top left under your project name. It will look like: `https://my-seedstr-agent.onrender.com`. Copy this.
2.  **Go to [UptimeRobot.com](https://uptimerobot.com/).**
3.  **Register for free** (No card needed).
4.  **Add New Monitor:**
    *   **Monitor Type:** HTTP(s)
    *   **Friendly Name:** Seedstr Agent
    *   **URL (or IP):** Paste your Render URL (`https://...onrender.com`).
    *   **Monitoring Interval:** **5 minutes** (Important! This keeps it awake).
5.  Click **Create Monitor**.

### Summary of what happens now:
1.  **Render** hosts your code.
2.  **Main Thread:** Runs a tiny Flask website.
3.  **Background Thread:** Runs your Python/Gemini Agent loop.
4.  **UptimeRobot:** Hits the Flask website every 5 minutes.
5.  **Result:** Render sees "traffic" and keeps the server running 24/7 without charging you a cent.

This is the standard, battle-tested method for winning hackathons without spending money.

