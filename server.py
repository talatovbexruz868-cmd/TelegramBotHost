from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import time
import random
import subprocess
import signal
import sys
import tempfile
import resend

app = Flask(__name__)
CORS(app)

# =========================================================
# ENVIRONMENT
# =========================================================

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
HOST_ADMIN_KEY = os.environ.get("HOST_ADMIN_KEY")

if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY


# =========================================================
# VAQTINCHALIK MA'LUMOTLAR
# =========================================================

users = {}

otp_codes = {}

bot_process = None
bot_info = {
    "name": "",
    "file": "",
    "running": False
}

bot_file_path = None
bot_token = None


# =========================================================
# ADMIN TEKSHIRUVI
# =========================================================

def check_admin():

    if not HOST_ADMIN_KEY:
        return False

    provided_key = request.headers.get("X-Admin-Key", "")

    return provided_key == HOST_ADMIN_KEY


def admin_required():

    if not check_admin():
        return jsonify({
            "success": False,
            "message": "Ruxsat berilmadi."
        }), 401

    return None


# =========================================================
# ASOSIY ROUTE
# =========================================================

@app.route("/")
def home():

    return jsonify({
        "service": "TelegramBotHost",
        "status": "online",
        "message": "TelegramBotHost backend ishlayapti"
    })


# =========================================================
# HEALTH
# =========================================================

@app.route("/health")
def health():

    return jsonify({
        "status": "ok"
    })


# =========================================================
# REGISTER / OTP
# =========================================================

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

    # EMAIL
    if method == "email":

        if not RESEND_API_KEY:

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
                <p>Sizning tasdiqlash kodingiz:</p>
                <h1>{otp}</h1>
                <p>Ushbu kod 1 daqiqa davomida amal qiladi.</p>
                <p>Kodni hech kimga bermang.</p>
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

    # TELEFON
    if method == "phone":

        return jsonify({
            "success": False,
            "message": "SMS tizimi hali ulanmagan."
        }), 501


# =========================================================
# VERIFY
# =========================================================

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


# =========================================================
# BOT UPLOAD
# =========================================================

@app.route("/api/bot/upload", methods=["POST"])
def upload_bot():

    error = admin_required()

    if error:
        return error

    global bot_file_path
    global bot_token
    global bot_info

    name = request.form.get("name", "").strip()
    token = request.form.get("token", "").strip()
    file = request.files.get("file")

    if not name:

        return jsonify({
            "success": False,
            "message": "Bot nomi kiritilmagan."
        }), 400

    if not token:

        return jsonify({
            "success": False,
            "message": "Telegram Bot Token kiritilmagan."
        }), 400

    if not file:

        return jsonify({
            "success": False,
            "message": "Python fayl yuklanmagan."
        }), 400

    filename = file.filename or ""

    if not filename.lower().endswith(".py"):

        return jsonify({
            "success": False,
            "message": "Faqat .py fayl yuklash mumkin."
        }), 400

    # Agar eski bot ishlayotgan bo'lsa, avval to'xtatamiz
    if bot_process is not None and bot_process.poll() is None:

        try:
            bot_process.terminate()
            bot_process.wait(timeout=5)

        except Exception:
            try:
                bot_process.kill()
            except Exception:
                pass

    # Vaqtinchalik papka
    bot_dir = tempfile.mkdtemp(prefix="telegrambothost_")

    safe_filename = os.path.basename(filename)

    bot_file_path = os.path.join(
        bot_dir,
        safe_filename
    )

    file.save(bot_file_path)

    bot_token = token

    bot_info = {
        "name": name,
        "file": safe_filename,
        "running": False
    }

    return jsonify({
        "success": True,
        "message": "Bot muvaffaqiyatli yuklandi.",
        "name": name,
        "file": safe_filename
    })


# =========================================================
# BOT RUN
# =========================================================

@app.route("/api/bot/run", methods=["POST"])
def run_bot():

    error = admin_required()

    if error:
        return error

    global bot_process
    global bot_info

    if not bot_file_path:

        return jsonify({
            "success": False,
            "message": "Avval bot faylini yuklang."
        }), 400

    if not bot_token:

        return jsonify({
            "success": False,
            "message": "Bot Token topilmadi."
        }), 400

    # Allaqachon ishlayotgan bo'lsa
    if bot_process is not None and bot_process.poll() is None:

        bot_info["running"] = True

        return jsonify({
            "success": True,
            "message": "Bot allaqachon ishlayapti."
        })

    try:

        # Faqat botga kerakli environment beriladi.
        # HOST_ADMIN_KEY va RESEND_API_KEY botga berilmaydi.
        bot_environment = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "PYTHONUNBUFFERED": "1",
            "BOT_TOKEN": bot_token
        }

        bot_process = subprocess.Popen(
            [
                sys.executable,
                bot_file_path
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=bot_environment
        )

        time.sleep(1)

        if bot_process.poll() is not None:

            bot_info["running"] = False

            return jsonify({
                "success": False,
                "message": "Bot ishga tushmadi. Python kodini tekshiring."
            }), 500

        bot_info["running"] = True

        return jsonify({
            "success": True,
            "message": "Bot muvaffaqiyatli ishga tushdi."
        })

    except Exception as e:

        print("BOT RUN XATOSI:", str(e))

        bot_info["running"] = False

        return jsonify({
            "success": False,
            "message": "Botni ishga tushirishda xatolik."
        }), 500


# =========================================================
# BOT STOP
# =========================================================

@app.route("/api/bot/stop", methods=["POST"])
def stop_bot():

    error = admin_required()

    if error:
        return error

    global bot_process
    global bot_info

    if bot_process is None:

        bot_info["running"] = False

        return jsonify({
            "success": True,
            "message": "Bot ishlamayapti."
        })

    if bot_process.poll() is not None:

        bot_info["running"] = False

        return jsonify({
            "success": True,
            "message": "Bot allaqachon to'xtagan."
        })

    try:

        bot_process.terminate()

        try:
            bot_process.wait(timeout=5)

        except subprocess.TimeoutExpired:

            bot_process.kill()
            bot_process.wait(timeout=2)

        bot_info["running"] = False

        return jsonify({
            "success": True,
            "message": "Bot to'xtatildi."
        })

    except Exception as e:

        print("BOT STOP XATOSI:", str(e))

        return jsonify({
            "success": False,
            "message": "Botni to'xtatishda xatolik."
        }), 500


# =========================================================
# BOT STATUS
# =========================================================

@app.route("/api/bot/status", methods=["GET"])
def bot_status():

    error = admin_required()

    if error:
        return error

    global bot_process
    global bot_info

    if bot_process is not None:

        if bot_process.poll() is None:
            bot_info["running"] = True
        else:
            bot_info["running"] = False

    return jsonify({
        "success": True,
        "name": bot_info.get("name", ""),
        "file": bot_info.get("file", ""),
        "running": bot_info.get("running", False)
    })


# =========================================================
# UMUMIY STATUS
# =========================================================

@app.route("/api/status", methods=["GET"])
def status():

    running = False

    if bot_process is not None:
        running = bot_process.poll() is None

    return jsonify({
        "service": "TelegramBotHost",
        "status": "online",
        "users": len(users),
        "bot_running": running
    })


# =========================================================
# SERVER
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get("PORT", 10000)
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
