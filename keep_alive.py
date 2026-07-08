import os
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "LobbyBot is online and active."

def run_web():
    # Use the port assigned by Render, defaulting to 8080
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.daemon = True
    t.start()
