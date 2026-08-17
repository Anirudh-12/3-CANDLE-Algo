from NorenWebApi import NorenWebApi
from auth import generate_key
import os
import sys
import time
import yaml
import pyotp
import logging

# Add NorenRestApiPy to path
sys.path.append(os.path.join(os.getcwd(), 'NorenRestApiPy'))

from NorenApi import NorenApi
# from NorenWebApi import NorenWebApi as NorenApi
from FLATTRADE import FlatTradeAuth

# Setup basic logging to see what's happening
logging.basicConfig(level=logging.INFO)

def main():
    # Load credentials from flattradecred_data.yaml
    config_path = "flattradecred.yaml"
    token_file = "session_token_ex.txt"
    
    if not os.path.exists(config_path):
        print(f"Error: {config_path} not found.")
        return

    print("Authenticating with FlatTrade...")
    auth = FlatTradeAuth(config_path, token_file)
    # totp = auth.get_totp()
    # totp = auth.totp
    api = NorenWebApi()
    appkey = generate_key(auth.user_id)
    api.login(auth.user_id,auth.password,auth.totp_key,appkey)   



        
        
    # # Initialize NorenApi
    # api = NorenApi(host='https://piconnect.flattrade.in/PiConnectAPI', 
    #                 websocket='wss://piconnect.flattrade.in/PiConnectWSAPI/')
    
    # # Set session using token
    
    # # api.login(auth.user_id,auth.password,totp,f"{auth.user_id}_U",api_secret=auth.api_key,imei="abc1234")
    # token = auth.fetch_session_token()
    
    # if not token:
    #     print("Failed to get session token.")
    #     return
    
    # print(f"Session Token: {token[:10]}...")

    # Initialize NorenApi
    # api = NorenApi()
    
    # # Set session
    # api.set_session(auth.user_id, auth.password, token)
    # api.login(auth.user_id, auth.password,auth.totp_key,auth.api_key)
    
    # Search for UNIONBANK in BSE
    # print("Searching for UNIONBANK in BSE...")
    # search_res = api.searchscrip(exchange='BSE', searchtext='UNIONBANK')
    
    # if not search_res or 'values' not in search_res:
    #     print(f"Could not find UNIONBANK in BSE. Response: {search_res}")
    #     return
    
    # # Find the correct symbol
    # # Usually it's like '532477' (Scrip Code) or 'UNIONBANK'
    # # Let's see the search results
    tsym = "UNIONBANK"
    # for item in search_res['values']:
    #     if item.get('instname') == 'EQUITY' and 'UNIONBANK' in item.get('tsym', ''):
    #         tsym = item.get('tsym')
    #         print(f"Found trading symbol: {tsym}")
    #         break
            
    # if not tsym:
    #     # Fallback to the first equity result
    #     for item in search_res['values']:
    #         if item.get('instname') == 'EQUITY':
    #             tsym = item.get('tsym')
    #             print(f"Using fallback trading symbol: {tsym}")
    #             break
                
    # if not tsym:
    #     print("Could not identify the correct trading symbol.")
    #     return

    # Place Order and Measure Time
    print(f"Placing Buy order for 1 share of {tsym} on BSE...")
    
    start_time = time.perf_counter()
    
    # place_order(self, buy_or_sell, product_type,
    #                exchange, tradingsymbol, quantity, discloseqty,
    #                price_type, price=0.0, trigger_price=None,
    #                retention='DAY', amo=None, remarks=None, ...)
    order_res = api.place_order(
        buy_or_sell='B',
        product_type='I', # Intraday
        exchange='BSE',
        tradingsymbol=tsym,
        quantity=1,
        discloseqty=0,
        price_type='LMT', # Market order
        price=100,
        remarks='Time measurement test'
    )
    
    end_time = time.perf_counter()
    
    elapsed_ms = (end_time - start_time) * 1000
    
    print("-" * 30)
    if order_res and order_res.get('stat') == 'Ok':
        print(f"Order Placed Successfully!")
        print(f"Order Number: {order_res.get('norenordno')}")
    else:
        print(f"Order Placement Failed or Status unknown.")
        print(f"Response: {order_res}")
        
    print(f"Time Taken: {elapsed_ms:.2f} ms")
    print("-" * 30)

if __name__ == "__main__":
    main()
