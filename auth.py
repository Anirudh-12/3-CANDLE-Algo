import hashlib
import requests
import pyotp
import json
import uuid

# ================= CONFIG =================

BASE_URL = "https://web.flattrade.in"   # change if different
ENDPOINT = "/NorenWClientWeb/QuickAuth"

USER_ID = "FT059783"
PASSWORD = "Navi@12"                  # plain password
TOTP_SECRET = "56442K76DXFWWQZ2GWZA2I26743F624M"  # base32 secret
APP_KEY = "0e4ea33ec90b93778f351bb2a997e061bd340d127509b8b5473e920d06c79fe8"
APK_VERSION = "20240711"

def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


# def quick_auth():
#     totp = pyotp.TOTP(TOTP_SECRET).now()

#     jdata_obj = {
#         "uid": USER_ID,
#         "pwd": sha256(PASSWORD),
#         "factor2": totp,
#         "vc": "NOREN_WEB",
#         "appkey": APP_KEY,
#         "apkversion": APK_VERSION,
#         "imei": str(uuid.uuid4()),
#         "source": "WEB"
#     }

#     # 🚨 IMPORTANT: compact JSON (no spaces)
#     jdata = json.dumps(jdata_obj, separators=(",", ":"))

#     payload = f"jData={jdata}"

#     headers = {
#         "Content-Type": "application/x-www-form-urlencoded",
#         "Accept": "application/json",
#         "User-Agent": "Mozilla/5.0"
#     }

#     r = requests.post(
#         BASE_URL + ENDPOINT,
#         headers=headers,
#         data=payload,
#         timeout=10
#     )

#     print("Status:", r.status_code)
#     print("Response:", r.text)
import hashlib
import base64

def generate_app_key(user_id):
    # Original byte array
    base_bytes = [83, 50, 97, 114, 110, 46, 27, 93]

    # Simulate Uint8Array + index addition
    transformed_chars = []
    for i, b in enumerate(base_bytes):
        transformed_chars.append(chr((b + i) % 256))

    # Build string
    j = user_id + "|"

    # Hash (very likely SHA256)
    hash_bytes = hashlib.sha256(j.encode()).digest()

    # Final encoding (likely base64 or hex)
    final_key = base64.b64encode(hash_bytes).decode()

    return final_key
import hashlib
import base64
import hmac

def try_match(user_id, given_key):
    base_bytes = [83, 50, 97, 114, 110, 46, 27, 93]

    # Generate transformed secret variants
    raw_secret = bytes(base_bytes)
    index_added_secret = bytes((b + i) % 256 for i, b in enumerate(base_bytes))

    secret_variants = [
        raw_secret,
        index_added_secret,
        raw_secret.hex().encode(),
        index_added_secret.hex().encode(),
    ]

    # Different base string patterns
    base_patterns = [
        user_id,
        user_id + "|",
        "|" + user_id,
    ]

    matches = []

    for secret in secret_variants:
        for base in base_patterns:
            candidates = [
                base.encode(),
                base.encode() + secret,
                secret + base.encode(),
                base.encode() + b"|" + secret,
                base.encode() + secret + b"|",
            ]

            for data in candidates:

                # Try plain hashes
                for algo in ["md5", "sha1", "sha256", "sha512"]:
                    h = hashlib.new(algo)
                    h.update(data)
                    digest_hex = h.hexdigest()
                    digest_b64 = base64.b64encode(h.digest()).decode()

                    if digest_hex == given_key:
                        matches.append(f"{algo} hex match with data={data}")
                    if digest_b64 == given_key:
                        matches.append(f"{algo} base64 match with data={data}")

                # Try HMAC variants
                for algo in ["md5", "sha1", "sha256", "sha512"]:
                    hm = hmac.new(secret, data, algo)
                    digest_hex = hm.hexdigest()
                    digest_b64 = base64.b64encode(hm.digest()).decode()

                    if digest_hex == given_key:
                        matches.append(f"HMAC-{algo} hex match with data={data}")
                    if digest_b64 == given_key:
                        matches.append(f"HMAC-{algo} base64 match with data={data}")

    if matches:
        print("MATCH FOUND:")
        for m in matches:
            print(m)
    else:
        print("No matches found with common methods.")

    return matches

def generate_key(user_id: str) -> str:
    secret = "S3cur3!d"
    data = f"{user_id}|{secret}"
    
    sha = hashlib.sha256()
    sha.update(data.encode("utf-8"))
    
    return sha.hexdigest()

if __name__ == "__main__":
    # quick_auth()
    # print(sha256(USER_ID+"|"))
    print(generate_key(USER_ID))
