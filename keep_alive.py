from flask import Flask
from threading import Thread
import logging
from datetime import datetime

# Disable default web request logs to keep your console perfectly clean for frog logs
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask('')

@app.route('/')
def home():
    """Main health-check dashboard for your hosting platform."""
    return "🐸 Froggy Mainframe Status: OPERATIONAL"

@app.route('/cron-tick')
def cron_tick():
    """Target this endpoint with your automated external cronjob (UptimeRobot, etc.)"""
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"🟢 Froggy Lilypad Pinged Successfully at {current_time} UTC"

def run():
    try:
        # Port 8080 is the standard for Render/Replit web server detection
        app.run(host='0.0.0.0', port=8080)
    except Exception as e:
        print(f"⚠️ Froggy Web Server Error: {e}")

def keep_alive():
    """Launches the Flask web server in a background thread so the bot can run."""
    t = Thread(target=run)
    t.daemon = True  # Thread dies cleanly if the main bot script stops
    t.start()
    print("🌐 Froggy Web Server Engine Initialized: Monitoring Port 8080")
