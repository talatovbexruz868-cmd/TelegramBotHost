from flask import Flask, request, jsonify
import os
import time
import random
from flask_cors import CORS
import resend

app = Flask(__name__)
CORS(app)

# Render Environment Variables ichidagi Resend API Key
resend.api_key = os.environ.get("RESEND_API_KEY")

# Hozircha vaqtinchalik xotira
users = {}
otp_codes = {}


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

    # 6 xonali OTP
    otp = str(random.randint(100000, 999999))

    # Foydalanuvchini saqlash
    users[value] = {
        "method": method,
        "verified": False
    }

    # OTP 60 soniya amal qiladi
    otp_codes[value] = {
        "code": otp,
        "expires_at": time.time() + 60
    }

    # EMAIL
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
                    <div style="font-family: Arial, sans-serif;">
                        <h2>TelegramBotHost</h2>

                        <p>Sizning tasdiqlash kodingiz:</p>

                        <h1 style="font-size: 32px;">
                            {otp}
                        </h1>

                        <p>
                            Ushbu kod 1 daqiqa davomida amal qiladi.
                        </p>

                        <p>
                            Kodni hech kimga bermang.
                        </p>
                    </div>
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

        # Hozircha SMS provayder ulanmagan.
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

    # Telefon SMS hali ulanmagan
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

    # 60 soniyalik muddatni tekshirish
    if time.time() > record["expires_at"]:

        otp_codes.pop(value, None)

        return jsonify({
            "success": False,
            "message": "OTP kodining 1 daqiqalik muddati tugagan."
        }), 400

    # Kodni tekshirish
    if code != record["code"]:
        return jsonify({
            "success": False,
            "message": "OTP kodi noto'g'ri."
        }), 400

    # Akkauntni tasdiqlash
    if value in users:
        users[value]["verified"] = True

    # OTPni o'chirish
    otp_codes.pop(value, None)

    return jsonify({
        "success": True,
        "message": "Akkaunt muvaffaqiyatli tasdiqlandi."
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
    app.run(host="0.0.0.0", port=port)
