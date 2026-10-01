from flask import Flask, request, jsonify
import os
import time
import random
import uuid
import subprocess
import signal
import sys
from flask_cors import CORS
import resend

app = Flask(__name__)
CORS(app)

resend.api_key = os.environ.get("RESEND_API_KEY")

users = {}
otp_codes = {}

# Ishlayotgan botlar
bots = {}


@app.route("/")
def home():
    return jsonify({
        "service": "TelegramBotHost",
        "status": "online",
        "message": "TelegramBotHost backend ishlayapti"
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# ============================================================
# OTP
# ============================================================

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

    otp = str(random.randint(100000, 999999))

    users[value] = {
        "method": method,
        "verified": False
    }

    otp_codes[value] = {
        "code": otp,
        "expires_at": time.time() + 60
    }

    if method == "email":

        if not resend.api_key:
            users.pop(value, None)
            otp_codes.pop(value, None)

            return jsonify({
                "success": False,
                "message": "RESEND_API_KEY Render'da topilmadi."
            }), 500

        try:
            resend.Emails.send({
                "from": "onboarding@resend.dev",
                "to": [value],
                "subject": "TelegramBotHost OTP kodi",
                "html": f"""
                    <h2>TelegramBotHost</h2>
                    <p>Tasdiqlash kodingiz:</p>
                    <h1>{otp}</h1>
                    <p>Kod 1 daqiqa amal qiladi.</p>
                """
            })

        except Exception as e:
            print("RESEND XATOSI:", str(e))

            users.pop(value, None)
            otp_codes.pop(value, None)

            return jsonify({
                "success": False,
                "message": "Email yuborishda xatolik yuz berdi."
            }), 500

        return jsonify({
            "success": True,
            "message": "Tasdiqlash kodi emailingizga yuborildi.",
            "method": "email"
        })

    return jsonify({
        "success": False,
        "message": "SMS tizimi hali ulanmagan."
    }), 501


@app.route("/api/verify", methods=["POST"])
def verify():
    data = request.get_json(silent=True) or {}

    method = data.get("method")
    value = data.get("value", "").strip()
    code = data.get("code", "").strip()

    if method not in ["email", "phone"]:
        return jsonify({
            "success": False,
            "message": "Email yoki telefon usulini tanlang."
        }), 400

    if not value or not code:
        return jsonify({
            "success": False,
            "message": "Ma'lumot va OTP kodini kiriting."
        }), 400

    if method == "phone":
        return jsonify({
            "success": False,
            "message": "SMS OTP tizimi hali ulanmagan."
        }), 501

    record = otp_codes.get(value)

    if not record:
        return jsonify({
            "success": False,
            "message": "OTP kodi topilmadi yoki muddati tugagan."
        }), 400

    if time.time() > record["expires_at"]:
        otp_codes.pop(value, None)

        return jsonify({
            "success": False,
            "message": "OTP kodining 1 daqiqalik muddati tugagan."
        }), 400

    if code != record["code"]:
        return jsonify({
            "success": False,
            "message": "OTP kodi noto'g'ri."
        }), 400

    if value in users:
        users[value]["verified"] = True

    otp_codes.pop(value, None)

    return jsonify({
        "success": True,
        "message": "Akkaunt muvaffaqiyatli tasdiqlandi."
    })


# ============================================================
# TELEGRAM BOT HOST
# ============================================================

@app.route("/api/bot/upload", methods=["POST"])
def upload_bot():

    bot_file = request.files.get("file")
    bot_name = request.form.get("name", "").strip()

    if not bot_file:
        return jsonify({
            "success": False,
            "message": "Bot .py fayli yuborilmadi."
        }), 400

    filename = bot_file.filename or ""

    if not filename.endswith(".py"):
        return jsonify({
            "success": False,
            "message": "Faqat Python .py fayl yuklash mumkin."
        }), 400

    if not bot_name:
        bot_name = filename.rsplit(".", 1)[0]

    bot_id = str(uuid.uuid4())

    bot_dir = os.path.join("/tmp", "telegrambothost", bot_id)
    os.makedirs(bot_dir, exist_ok=True)

    bot_path = os.path.join(bot_dir, "bot.py")

    bot_file.save(bot_path)

    bots[bot_id] = {
        "id": bot_id,
        "name": bot_name,
        "path": bot_path,
        "status": "stopped",
        "process": None
    }

    return jsonify({
        "success": True,
        "message": "Bot kodi muvaffaqiyatli yuklandi.",
        "bot_id": bot_id,
        "name": bot_name,
        "status": "stopped"
    })


@app.route("/api/bot/run", methods=["POST"])
def run_bot():

    data = request.get_json(silent=True) or {}

    bot_id = data.get("bot_id")
    token = data.get("token", "").strip()

    if not bot_id:
        return jsonify({
            "success": False,
            "message": "Bot ID kerak."
        }), 400

    if not token:
        return jsonify({
            "success": False,
            "message": "Telegram Bot Token kerak."
        }), 400

    bot = bots.get(bot_id)

    if not bot:
        return jsonify({
            "success": False,
            "message": "Bot topilmadi."
        }), 404

    old_process = bot.get("process")

    if old_process and old_process.poll() is None:
        return jsonify({
            "success": False,
            "message": "Bot allaqachon ishlayapti."
        }), 409

    env = os.environ.copy()

    # Token bot dasturiga environment variable sifatida beriladi.
    env["BOT_TOKEN"] = token
    env["TELEGRAM_BOT_TOKEN"] = token

    try:
        process = subprocess.Popen(
            [sys.executable, bot["path"]],
            cwd=os.path.dirname(bot["path"]),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        bot["process"] = process
        bot["status"] = "running"

        return jsonify({
            "success": True,
            "message": "Bot ishga tushirildi.",
            "bot_id": bot_id,
            "status": "running"
        })

    except Exception as e:
        print("BOT RUN XATOSI:", str(e))

        return jsonify({
            "success": False,
            "message": "Botni ishga tushirishda xatolik yuz berdi."
        }), 500


@app.route("/api/bot/stop", methods=["POST"])
def stop_bot():

    data = request.get_json(silent=True) or {}
    bot_id = data.get("bot_id")

    bot = bots.get(bot_id)

    if not bot:
        return jsonify({
            "success": False,
            "message": "Bot topilmadi."
        }), 404

    process = bot.get("process")

    if not process or process.poll() is not None:
        bot["status"] = "stopped"

        return jsonify({
            "success": True,
            "message": "Bot allaqachon to'xtagan.",
            "status": "stopped"
        })

    try:
        process.terminate()

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

        bot["process"] = None
        bot["status"] = "stopped"

        return jsonify({
            "success": True,
            "message": "Bot to'xtatildi.",
            "status": "stopped"
        })

    except Exception as e:
        print("BOT STOP XATOSI:", str(e))

        return jsonify({
            "success": False,
            "message": "Botni to'xtatishda xatolik."
        }), 500


@app.route("/api/bot/status", methods=["GET"])
def bot_status():

    bot_id = request.args.get("bot_id")

    bot = bots.get(bot_id)

    if not bot:
        return jsonify({
            "success": False,
            "message": "Bot topilmadi."
        }), 404

    process = bot.get("process")

    if process and process.poll() is not None:
        bot["process"] = None
        bot["status"] = "stopped"

    return jsonify({
        "success": True,
        "bot_id": bot["id"],
        "name": bot["name"],
        "status": bot["status"]
    })


@app.route("/api/bots", methods=["GET"])
def list_bots():

    result = []

    for bot_id, bot in bots.items():

        process = bot.get("process")

        if process and process.poll() is not None:
            bot["process"] = None
            bot["status"] = "stopped"

        result.append({
            "id": bot_id,
            "name": bot["name"],
            "status": bot["status"]
        })

    return jsonify({
        "success": True,
        "bots": result
    })


@app.route("/api/status", methods=["GET"])
def status():

    running = 0

    for bot in bots.values():
        process = bot.get("process")

        if process and process.poll() is None:
            running += 1

    return jsonify({
        "service": "TelegramBotHost",
        "status": "online",
        "users": len(users),
        "bots": len(bots),
        "running_bots": running
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
