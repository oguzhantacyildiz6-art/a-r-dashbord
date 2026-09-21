# -*- coding: utf-8 -*-
import os
import threading
from flask import Flask, jsonify, send_from_directory
from scanner import load_data, run_scan

app = Flask(__name__, static_folder=".")
_lock = threading.Lock()


def safe_scan():
    with _lock:
        try:
            return run_scan()
        except Exception as e:
            data = load_data()
            data["error"] = str(e)
            return data


def loop():
    safe_scan()
    while True:
        try:
            import time
            time.sleep(15 * 60)
            safe_scan()
        except Exception:
            import time
            time.sleep(60)


@app.route("/")
def home():
    return send_from_directory(".", "index.html")


@app.route("/api/feed")
def feed():
    data = load_data()
    empty = not (data.get("news_org") or data.get("news_other") or data.get("news_city") or data.get("social"))
    if empty:
        data = safe_scan()
    return jsonify(data)


@app.route("/api/scan")
def scan_now():
    return jsonify(safe_scan())


threading.Thread(target=loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
