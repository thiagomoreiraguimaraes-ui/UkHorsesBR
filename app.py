from flask import Flask, jsonify, request
from flask_cors import CORS
import requests

app = Flask(__name__)
CORS(app)

RAPIDAPI_KEY = "b0a81a06admshd71d02f2ad89712p172226jsn5019ae4e8612"
HEADERS = {
    "x-rapidapi-host": "horse-racing.p.rapidapi.com",
    "x-rapidapi-key": RAPIDAPI_KEY,
}

@app.route("/racecards")
def racecards():
    date = request.args.get("date", "")
    r = requests.get(
        "https://horse-racing.p.rapidapi.com/racecards",
        headers=HEADERS,
        params={"date": date},
        timeout=10
    )
    data = r.json()
    corridas = list(data.values()) if isinstance(data, dict) else data
    return jsonify(corridas)

if __name__ == "__main__":
    app.run()
