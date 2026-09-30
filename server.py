from flask import Flask, request, jsonify
import os
from flask_cors import CORS
app = Flask(__name__)
CORS(app)
# Hozircha vaqtinchalik xotira.
# Keyingi bosqichda haqiqiy database qo‘shamiz.
users = {}


@app.route("/")
def home():
    return jsonify({
        "service": "TelegramBotHost",
        "status": "online",
        "message": "TelegramBotHost backend ishlayapti"
    })


@app.route("/health")
def health():
    return jsonify({
        "status": "ok"
    })


@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}

    method = data.get("method")
    value = data.get("value", "").strip()

    if method not in ["email", "phone"]:
        return jsonify({
            "success": False,
            "message": "Email yoki telefon usulini tanlang."
        }), 400

    if not value:
        return jsonify({
            "success": False,
            "message": "Email yoki telefon raqamini kiriting."
        }), 400

    if value in users:
        return jsonify({
            "success": False,
            "message": "Bu ma'lumot bilan akkaunt allaqachon mavjud."
        }), 409

    users[value] = {
        "method": method,
        "verified": False
    }

    return jsonify({
        "success": True,
        "message": "Ma'lumot qabul qilindi.",
        "method": method
    })


@app.route("/api/status", methods=["GET"])
def status():
    return jsonify({
        "service": "TelegramBotHost",
        "status": "online",
        "users": len(users)
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=por) 
