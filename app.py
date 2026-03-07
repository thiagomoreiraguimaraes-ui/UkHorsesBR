from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import os
import time
from datetime import datetime
import pytz

app = Flask(__name__)
CORS(app)

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")
HEADERS = {
    "x-rapidapi-host": "horse-racing.p.rapidapi.com",
    "x-rapidapi-key": RAPIDAPI_KEY,
}

UK_TZ = pytz.timezone("Europe/London")
_cache = {}

def deve_atualizar(date_str):
    if date_str not in _cache:
        return True
    _, saved_at = _cache[date_str]
    saved_dt = datetime.fromtimestamp(saved_at, UK_TZ)
    now_uk = datetime.now(UK_TZ)
    return saved_dt.date() != now_uk.date()

def buscar_e_salvar(date_str):
    try:
        r = requests.get(
            "https://horse-racing.p.rapidapi.com/racecards",
            headers=HEADERS,
            params={"date": date_str},
            timeout=10
        )
        r.raise_for_status()
        data = r.json()
        corridas = list(data.values()) if isinstance(data, dict) else data
        _cache[date_str] = (corridas, time.time())
        return corridas
    except Exception as e:
        if date_str in _cache:
            return _cache[date_str][0]
        return []

@app.route("/racecards")
def racecards():
    date = request.args.get("date", "")
    if not date:
        date = datetime.now(UK_TZ).strftime("%Y-%m-%d")
    if deve_atualizar(date):
        corridas = buscar_e_salvar(date)
    else:
        corridas, _ = _cache[date]
    return jsonify(corridas)

@app.route("/status")
def status():
    info = {}
    for d, (corridas, ts) in _cache.items():
        info[d] = {
            "corridas": len(corridas),
            "salvo_em": datetime.fromtimestamp(ts, UK_TZ).strftime("%Y-%m-%d %H:%M UK")
        }
    return jsonify(info)

if __name__ == "__main__":
    app.run()
