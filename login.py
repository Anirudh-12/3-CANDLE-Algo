from collections import UserDict
from NorenWebApi import NorenWebApi


api = NorenWebApi()
userid = ""
password = ""
totp_secret = ""
app_key = ""
api.login(userid=userid, password=password, totp_secret=totp_secret,app_key=app_key)