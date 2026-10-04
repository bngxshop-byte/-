from flask import Flask, request, jsonify
import json, os, aiohttp, asyncio, requests, binascii
from datetime import datetime
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToJson
import like_pb2, like_count_pb2, uid_generator_pb2
from google.protobuf.message import DecodeError

app = Flask(__name__)

# رابط جلب التوكنات الخارجي
TOKENS_URL = "https://auto-token-dldo.onrender.com/api/get_jwt"


# ------------------- جلب التوكنات من الرابط الخارجي -------------------
async def fetch_tokens_from_api(session):
    """جلب التوكنات من الرابط الخارجي"""
    try:
        async with session.get(TOKENS_URL, timeout=30) as res:
            if res.status == 200:
                data = await res.json()
                # الهيكل: {"tokens": {"uid": "jwt_token", ...}, ...}
                tokens_dict = data.get("tokens", {})
                return list(tokens_dict.values())
    except Exception as e:
        print(f"[ERROR] Failed to fetch tokens: {e}")
    return []


async def get_tokens_live():
    """جلب كل التوكنات الصالحة"""
    async with aiohttp.ClientSession() as session:
        tokens = await fetch_tokens_from_api(session)
    return tokens


# ------------------- تشفير -------------------
def encrypt_message(plaintext):
    key = b'Yg&tc%DEuh6%Zc^8'
    iv = b'6oyZDr22E3ychjM%'
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return binascii.hexlify(cipher.encrypt(pad(plaintext, AES.block_size))).decode()


# ------------------- Protobuf Builders -------------------
def create_uid_proto(uid):
    pb = uid_generator_pb2.uid_generator()
    pb.saturn_ = int(uid)
    pb.garena = 1
    return pb.SerializeToString()


def create_like_proto(uid):
    pb = like_pb2.like()
    pb.uid = int(uid)
    return pb.SerializeToString()


def decode_protobuf(binary):
    try:
        pb = like_count_pb2.Info()
        pb.ParseFromString(binary)
        return pb
    except DecodeError:
        return None


# ------------------- طلب معلومات اللاعب -------------------
def make_request(enc_uid, token):
    url = "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow"
    headers = {
        'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        'Connection': "Keep-Alive",
        'Accept-Encoding': "gzip",
        'Authorization': f"Bearer {token}",
        'Content-Type': "application/x-www-form-urlencoded",
        'Expect': "100-continue",
        'X-Unity-Version': "2018.4.11f1",
        'X-GA': "v1 1",
        'ReleaseVersion': "OB55"
    }
    try:
        res = requests.post(url, data=bytes.fromhex(enc_uid), headers=headers, verify=False, timeout=10)
        return decode_protobuf(res.content)
    except Exception as e:
        print(f"[ERROR] make_request: {e}")
        return None


# ------------------- إرسال لايك -------------------
async def send_request(enc_uid, token):
    url = "https://clientbp.ggpolarbear.com/LikeProfile"
    headers = {
        'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        'Connection': "Keep-Alive",
        'Accept-Encoding': "gzip",
        'Authorization': f"Bearer {token}",
        'Content-Type': "application/x-www-form-urlencoded",
        'Expect': "100-continue",
        'X-Unity-Version': "2018.4.11f1",
        'X-GA': "v1 1",
        'ReleaseVersion': "OB55"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=bytes.fromhex(enc_uid), headers=headers, ssl=False, timeout=10) as r:
                return r.status
    except Exception as e:
        print(f"[ERROR] send_request: {e}")
        return None


async def send_likes(uid, tokens):
    enc_uid = encrypt_message(create_like_proto(uid))
    tasks = [send_request(enc_uid, token) for token in tokens]
    return await asyncio.gather(*tasks)


# ------------------- Endpoints -------------------
@app.route('/like', methods=['GET'])
def like_handler():
    uid = request.args.get("uid")
    if not uid:
        return jsonify({"error": "Missing UID"}), 400

    try:
        # 1) جلب التوكنات من الرابط الخارجي
        tokens = asyncio.run(get_tokens_live())
        if not tokens:
            return jsonify({"error": "No valid tokens available"}), 401

        # 2) جلب معلومات اللاعب قبل
        enc_uid = encrypt_message(create_uid_proto(uid))
        before = make_request(enc_uid, tokens[0])
        if not before:
            return jsonify({"error": "Failed to retrieve player info"}), 500

        before_data = json.loads(MessageToJson(before))
        likes_before = int(before_data.get("AccountInfo", {}).get("Likes", 0))
        nickname = before_data.get("AccountInfo", {}).get("PlayerNickname", "Unknown")

        # 3) إرسال اللايكات
        responses = asyncio.run(send_likes(uid, tokens))
        success_count = sum(1 for r in responses if r == 200)

        # 4) جلب معلومات اللاعب بعد
        after = make_request(enc_uid, tokens[0])
        likes_after = likes_before
        if after:
            after_data = json.loads(MessageToJson(after))
            likes_after = int(after_data.get("AccountInfo", {}).get("Likes", 0))

        return jsonify({
            "PlayerNickname": nickname,
            "UID": uid,
            "LikesBefore": likes_before,
            "LikesAfter": likes_after,
            "LikesGivenByAPI": likes_after - likes_before,
            "SuccessfulRequests": success_count,
            "TotalRequests": len(tokens),
            "status": 1 if likes_after > likes_before else 2
        })

    except Exception as e:
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "message": "Like API is running 🚀",
        "tokens_source": TOKENS_URL
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)