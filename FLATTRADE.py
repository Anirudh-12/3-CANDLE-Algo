import logging
import httpx
import pyotp
import hashlib
from urllib.parse import urlparse, parse_qs
import yaml
import certifi
# location of ssl certificates
httpx._default_ssl_context = certifi.where()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logging.info("SSL certificates loaded from: %s", certifi.where())

class FlatTradeAuth:
    def __init__(self, config_path="flattradecred.yaml", token_file="session_token.txt"):
        with open(config_path) as f:
            cred = yaml.load(f, Loader=yaml.FullLoader)
        self.user_id = cred["user_id"]
        self.password = cred["password"]
        self.totp_key = cred["factor2"]
        self.api_key = cred["api_key"]
        self.api_secret = cred["api_secret"]
        self.token_file = token_file

        self.host = "https://auth.flattrade.in"
        self.api_host = "https://authapi.flattrade.in"

        self.routes = {
            "session": f"{self.api_host}/auth/session",
            "ftauth": f"{self.api_host}/ftauth",
            "apitoken": f"{self.api_host}/trade/apitoken",
        }

        self.headers = {
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.5",
            "Host": urlparse(self.api_host).netloc,
            "Origin": f"{self.host}",
            "Referer": f"{self.host}/",
        }

    def encode_item(self, item):
        return hashlib.sha256(item.encode()).hexdigest()

    def get_authcode(self):
        try:
            logging.info(f"Connecting to auth endpoint: {self.routes['session']}")
            with httpx.Client(headers=self.headers) as client:
                response = client.post(self.routes["session"])
                logging.info(f"Session response status: {response.status_code}")
                
                if response.status_code == 200:
                    sid = response.text
                    logging.info(f"Got session ID: {sid}")
                    
                    totp_code = pyotp.TOTP(self.totp_key).now()
                    logging.info(f"Generated TOTP code: {totp_code}")
                    
                    auth_payload = {
                        "UserName": self.user_id,
                        "Password": self.encode_item(self.password),
                        "App": "",
                        "ClientID": "",
                        "Key": "",
                        "APIKey": self.api_key,
                        "PAN_DOB": totp_code,
                        "Sid": sid,
                        "Override": "",
                    }
                    
                    logging.info(f"Sending auth request to: {self.routes['ftauth']}")
                    response = client.post(
                        self.routes["ftauth"],
                        json=auth_payload,
                    )
                    
                    logging.info(f"Auth response status: {response.status_code}")

                    if response.status_code == 200:
                        response_data = response.json()
                        logging.info(f"Auth response data: {response_data}")
                        if response_data.get("emsg") == "DUPLICATE":
                            logging.info("Duplicate session detected. Overriding...")
                            
                            auth_payload["Override"] = "Y"
                            response = client.post(
                                self.routes["ftauth"],
                                json=auth_payload,
                                timeout=15
                            )
                            
                            if response.status_code == 200:
                                response_data = response.json()
                                logging.info("Override successful")
                            else:
                                logging.error(f"Override failed: {response.status_code}, {response.text}")
                                return None

                        redirect_url = response_data.get("RedirectURL", "")
                        logging.info(f"Got redirect URL: {redirect_url}")
                        
                        query_params = parse_qs(urlparse(redirect_url).query)
                        if "code" in query_params:
                            code = query_params["code"][0]
                            logging.info(f"Successfully extracted auth code: {code[:5]}...{code[::-5]}")
                            return code
                        else:
                            pass
                            logging.error(f"No code found in redirect URL: {redirect_url}")
                    else:
                        pass
                        logging.error(f"Auth request failed: {response.status_code}, {response.text}")
                else:
                    pass
                    logging.error(f"Session request failed: {response.status_code}, {response.text}")
                    
            return None
        
        except Exception as e:
            logging.error(f"Exception in get_authcode: {str(e)}")
            return None

    def get_apitoken(self, code):
        try:
            print(f"Getting API token with auth code: {code[:5]}...")

            api_secret = self.encode_item(f"{self.api_key}{code}{self.api_secret}")
            print("Generated API secret hash successfully")
            print(api_secret)
            
            with httpx.Client() as client:
                logging.info(f"Sending API token request to: {self.routes['apitoken']}")
                response = client.post(
                    self.routes["apitoken"],
                    json={
                        "api_key": self.api_key,
                        "request_code": code,
                        "api_secret": api_secret,
                    },
                )
                
                logging.info(f"API token response status: {response.status_code}")

                if response.status_code == 200:
                    response_json = response.json()
                    token = response_json.get("token", "")
                    if token:
                        print(f"Successfully retrieved API token: {token[:10]}...")
                        return token
                    else:
                        # pass
                        print("API token not found in response: ", response_json)
                        logging.error(f"API token not found in response: {response_json}")
                else:
                    # pass
                    print("API token request failed: ", response.status_code, response.text)
                    logging.error(f"API token request failed: {response.status_code}, {response.text}")
                
                return None
                
        except Exception as e:
            logging.error(f"Exception in get_apitoken: {str(e)}")
            print("Exception in get_apitoken",e)
            return None

    def fetch_session_token(self):
        logging.info("Fetching a new session token...")
        try:
            code = self.get_authcode()
            if code:
                logging.info(f"Successfully obtained auth code: {code[:5]}...")
                token = self.get_apitoken(code)
                if token:
                    logging.info("New session token obtained and stored.")
                    with open(self.token_file, "w") as f:
                        f.write(token)
                    return token
                else:
                    # pass
                    print("Failed to get API token from auth code",token)
                    logging.error("Failed to get API token from auth code")
            else:
                # pass
                print("Failed to get auth code",code)
                logging.error("Failed to get auth code")
            
            logging.error("Failed to fetch session token.")
            print("Failed to fetch session token.")
            return None
        except Exception as e:
            logging.error(f"Exception during authentication: {str(e)}")
            print("Exception during authentication",e)
            return None

    def get_totp(self):
        try:
            totp_code = pyotp.TOTP(self.totp_key).now()
            logging.info(f"Generated TOTP code: {totp_code}")
            return totp_code
        except Exception as e:
            logging.error(f"Exception in get_totp_code: {str(e)}")
            
            return None

# Usage example
if __name__ == "__main__":
    auth = FlatTradeAuth()
    token = auth.fetch_session_token()
    print(f"SESSION_TOKEN :: {token}")
