def generate_key(user_id: str) -> str:
    secret = "S3cur3!d"
    data = f"{user_id}|{secret}"
    
    sha = hashlib.sha256()
    sha.update(data.encode("utf-8"))
    
    return sha.hexdigest()