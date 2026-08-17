import os
import ssl
try:
    import certifi
    os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
    os.environ["SSL_CERT_FILE"] = certifi.where()
    ssl._create_default_https_context = ssl._create_unverified_context
except ImportError:
    pass

try:
    import _strptime  # Fix for threading issue with datetime.strptime in PyInstaller
except ImportError:
    pass

from bi_rpc import RpcHandler
import yaml
from datetime import datetime
import traceback
import sys
# import math
import time
from threading import Thread
from multiprocessing import freeze_support
# from NorenRestApiPy.NorenApi import NorenApi as NorenDataApi
from FLATTRADE import FlatTradeAuth
from check_for_empty_port import check_for_empty_port
from option_chain_handler import OptionChainHandler
from Get_Instruments import InstrumentHelper
from nifty_five_min_strategy import NiftyFiveMinStrategy
from position_manager import PositionManager
# from NorenWebApi import NorenWebApi
from NorenRestApiPy.NorenApi import NorenApi
from NorenWebApi import NorenWebApi
# Setup Logging
# logging.basicConfig(level=logging.CRITICAL,
#                     format='%(asctime)s %(levelname)s %(message)s')

# ... (skip to notification function)
import logging
# logging.disable(logging.CRITICAL)
from auth import generate_key



# Global State
api = None
option_handler = None
futures_data_manager = None
nifty_strategy = None
trading_active = False
config_path = "flattradecred.yaml"
config_path2 = "flattradecred2.yaml"
config_path_data = "flattradecred_data.yaml"
token_file = "session_token3.txt"
token_file2 = "session_token2.txt"
token_file_data = "session_token_data.txt"
position_manager = None
try:
    instrument_helper = InstrumentHelper()
    with open("exe_debug_log.txt", "a", encoding="utf-8") as f:
        f.write("[BACKEND] InstrumentHelper initialized successfully!\n")
except Exception as e:
    with open("exe_debug_log.txt", "a", encoding="utf-8") as f:
        f.write(f"[BACKEND_ERROR] InstrumentHelper failed to init: {e}\n")
    instrument_helper = None

# UI Strike Tracking
ui_selected_ce_strike = 0
ui_selected_pe_strike = 0

bridge = None  # Will be initialized in backend_main

# --- Helper Functions ---

def format_expiry_date(expiry_date):
    """Return default expiry date in dd-MMM-YYYY format if none provided"""
    if not expiry_date:
        return "24-Jul-2024"  # Example format
    return expiry_date

def save_credentials(credentials):
    """Save credentials to YAML file with the correct key format"""
    with open(config_path, "w") as f:
        yaml.dump({
            "user_id": credentials["user_id"],
            "password": credentials["password"],
            "factor2": credentials["factor2"],
            "api_key": credentials["api_key"],
            "api_secret": credentials["api_secret"]
        }, f)
    pass

def convert_credential_format():
    """Convert credentials to the format expected by FlatTradeAuth if needed"""
    if os.path.exists(config_path):
        try:
            with open(config_path) as f:
                cred = yaml.load(f, Loader=yaml.FullLoader)
            
            if "user" in cred and "user_id" not in cred:
                pass
                with open(config_path, "w") as f:
                    yaml.dump({
                        "user_id": cred.get("user_id", ""),
                        "password": cred.get("password", ""),
                        "factor2": cred.get("factor2", ""),
                        "api_key": cred.get("api_key", ""),
                        "api_secret": cred.get("api_secret", "")
                    }, f)
                pass
        except Exception as e:
            pass

def update_ui_connection_status(success=False):
    """Update the UI connection status"""
    if bridge:
        bridge.call("updateConnectionStatus", success)

def fetch_and_update_frontend_positions():
    """Fetches positions with calculated PNL and pushes them to the frontend."""
    try:
        positions_data = get_positions_internal() # Call the internal version
        if positions_data is not None:
            pass
            if bridge:
                bridge.notify("updatePositions", positions_data)
        else:
            pass
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error in fetch_and_update_frontend_positions: {e}")

def order_update_callback(message):
    """Handle order updates from websocket"""
    try:
        pass
        if not message or 't' not in message:
            return

        if message['t'] == 'om':  # Order message
            pass
            order_data = {
                'order_no': message.get('norenordno', ''),
                'symbol': message.get('tsym', ''),
                'type': message.get('trantype', ''),
                'qty': int(message.get('qty', 0)),
                'price': float(message.get('prc', 0)),
                'status': message.get('status', '')
            }

            pass
            if bridge:
                bridge.notify("handleOrderUpdate", order_data)

            order_status = message.get('status', '').upper()
            if order_status == 'COMPLETE' or order_status == 'FILLED':
                pass
                fetch_and_update_frontend_positions()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error in order_update_callback: {e}")

def notify_nifty_state_update(data=None):
    """Push nifty strategy state to UI"""
    try:
        if bridge and nifty_strategy:
            nifty_strategy._notify()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error in notify_nifty_state_update: {e}")

def notify_market_data_update(data):
    pass
    
    # Add UI-selected strike prices if available
    if ui_selected_ce_strike and option_handler:
        data['ce_strike_price'] = option_handler.get_option_ltp(ui_selected_ce_strike, "CE")
    if ui_selected_pe_strike and option_handler:
        data['pe_strike_price'] = option_handler.get_option_ltp(ui_selected_pe_strike, "PE")
        
    if bridge:
        bridge.notify("updateMarketData", data)

def get_positions_internal():
    """Internal function to get positions used by both exposed and internal logic"""
    pass
    try:
        if not api:
            pass
            return None

        raw_positions = position_manager.get_positions()
        if not raw_positions:
            pass
            return {}

        formatted_positions = {}
        total_calculated_pnl = 0 

        for pos in raw_positions:
            symbol = pos.get('tsym')
            if not symbol:
                continue

            try:
                position_pnl = float(pos.get('urmtom', 0)) + float(pos.get('rpnl', 0))
                total_calculated_pnl += position_pnl

                formatted_positions[symbol] = {
                    'symbol': symbol,
                    'qty': int(pos.get('netqty', 0)),
                    'avg_price': float(pos.get('netavgprc', 0)),
                    'ltp': float(pos.get('lp', 0)),
                    'pnl': position_pnl
                }
            except Exception as inner_e:
                import traceback
                traceback.print_exc()
                print(f"Error in get_positions_internal loop: {inner_e}")

        pass
        return formatted_positions
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error in get_positions_internal: {e}")
        return None




def backend_main(rpc_address):
    global bridge, api, option_handler, futures_data_manager, nifty_strategy, position_manager, instrument_helper
    freeze_support()
    bridge = RpcHandler(rpc_address, "server", name="BACKEND")

    @bridge.expose
    def connect_to_api(credentials=None):
        global api, option_handler
        global position_manager, instrument_helper, futures_data_manager
        
        try:
            if credentials:
                save_credentials(credentials)
            else:
                convert_credential_format()
            
            logging.info(f"Initializing FlatTradeAuth with config={config_path}, token_file={token_file}")
            # auth = FlatTradeAuth(config_path, token_file)
            # logging.info("Fetching session token...")
            # token = auth.fetch_session_token()
            # logging.info(f"Session token obtained: {token}")
            # print(token)
            # api = NorenApi(host="https://piconnect.flattrade.in/PiConnectAPI", websocket="wss://piconnect.flattrade.in/PiConnectWSAPI/")
            # api.set_session(auth.user_id,auth.password,token)
            # api.login(auth.user_id, auth.password, auth.get_totp(), f"{auth.user_id}_U", api_secret=auth.api_key, imei="abc1234")
            # auth2 = FlatTradeAuth(config_path2, token_file2)
            auth2 = FlatTradeAuth(config_path_data, token_file_data)
            api = NorenWebApi()
            appkey = generate_key(auth2.user_id)

            # api2 = NorenWebApi()
            api.login(auth2.user_id,auth2.password,auth2.totp_key,appkey)
            # api = NorenDataApi(host='https://api.shoonya.com/NorenWClientTP/', 
            #            websocket='wss://api.shoonya.com/NorenWSTP/')
        
        # # Set session using token
        #     # Shoonya Data API Login
        #     login_res = api.login(
        #         data_auth.user_id, 
        #         data_auth.password, 
        #         data_auth.get_totp(), 
        #         f"{data_auth.user_id}_U", 
        #         api_secret=data_auth.api_key, 
        #         imei="abc1234"
        #     )
            
            # if not login_res or login_res.get('stat') != 'Ok':
            #     raise Exception(f"Shoonya Data API login failed: {login_res}")

            # api.login(auth.user_id, auth.password, auth.totp_key, auth.api_key)
            # api2.login(auth2.user_id, auth2.password, auth2.totp_key, auth2.api_key)
            position_manager = PositionManager((api,))
            # position_manager2 = PositionManager((api2,))
            
            option_handler = OptionChainHandler(
                api, 
                position_manager,
                position_update_func=fetch_and_update_frontend_positions,
                market_data_update_func=notify_market_data_update
            )

            nifty_strategy = NiftyFiveMinStrategy(
                api,
                option_handler,
                instrument_helper,
                position_manager,
                bridge
            )

            api.start_websocket(subscribe_callback=option_handler.option_update_callback,
                                order_update_callback=order_update_callback,
                                socket_open_callback=option_handler._subscribe_to_options)
            
            initial_expiry_set = False
            try:
                index = "NIFTY"
                option_handler.set_index(index)
                
                expiry_dict = instrument_helper.get_expirys_dict([index])
                if index in expiry_dict:
                    expiry_dates = expiry_dict[index]
                    if expiry_dates:
                        def parse_date(date_str):
                            try:
                                return datetime.strptime(date_str, "%d-%b-%Y")
                            except Exception:
                                return datetime.max
                        
                        expiry_dates = sorted(expiry_dates, key=parse_date)
                        pass
                        bridge.call("updateExpiryDates", expiry_dates)
                        
                        if len(expiry_dates) > 0:
                            option_handler.set_expiry(expiry_dates[0])
                            # futures_data_manager.set_active_expiry(expiry_dates[0]) # if managed
                            initial_expiry_set = True
                    else:
                        option_handler.set_expiry("24-Jul-2024")
                        initial_expiry_set = True
                else:
                    option_handler.set_expiry("24-Jul-2024")
                    initial_expiry_set = True
            except Exception as e:
                pass
                option_handler.set_expiry("24-Jul-2024")
                initial_expiry_set = True

            update_ui_connection_status(True)

            if initial_expiry_set:
                bridge.call("initializePositionsAndOrders")

            
            return {"success": True, "message": "Connected successfully"}
            
        except Exception as e:
            update_ui_connection_status(False)
            return {"success": False, "message": f"Connection error: {e}"}

    @bridge.expose
    def auto_connect():
        return connect_to_api()

    @bridge.expose
    def get_option_chain():
        if not option_handler:
            return {"success": False, "message": "Option handler not initialized"}
        try:
            chain_data = option_handler.get_option_chain()
            if not chain_data:
                return {"success": False, "message": "Failed to get option chain data"}
            
            result = {
                "success": True,
                "atm_strike": chain_data.get("atm_strike", 0),
                "spot_price": chain_data.get("spot_price", 0),
                "strikes": chain_data.get("strikes", []),
                "timestamp": datetime.now().isoformat()
            }
            return result
        except Exception as e:
            return {"success": False, "message": f"Error: {e}"}

    @bridge.expose
    def get_saved_credentials():
        try:
            if os.path.exists(config_path):
                with open(config_path) as f:
                    cred = yaml.load(f, Loader=yaml.FullLoader)
                    return {
                        "user_id": cred.get("user_id", cred.get("user", "")),
                        "password": cred.get("password", cred.get("pwd", "")),
                        "factor2": cred.get("factor2", ""),
                        "api_key": cred.get("apikey", cred.get("api_key", "")),
                        "api_secret": cred.get("apisecret", cred.get("api_secret", ""))
                    }
            return {}
        except Exception as e:
            return {}

    @bridge.expose
    def start_trading():
        global trading_active
        if not api or not option_handler:
            return {"success": False, "message": "Not connected to trading API"}
        try:
            trading_active = True
            if not option_handler.expiry:
                option_handler.set_expiry(format_expiry_date(None))
            if hasattr(option_handler, 'start_monitoring'):
                option_handler.start_monitoring()
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}

    @bridge.expose
    def stop_trading():
        global trading_active
        try:
            if nifty_strategy and nifty_strategy.is_running:
                nifty_strategy.stop()
            if option_handler and hasattr(option_handler, 'stop_monitoring'):
                option_handler.stop_monitoring()
            trading_active = False
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": f"Error: {e}"}

    @bridge.expose
    def update_strike_price(section, strike_value):
        if not option_handler:
            return {"success": False, "message": "Option handler not initialized"}
        try:
            section_key = f"section{section}"
            option_handler.update_strike(section_key, strike_value)
            return {"success": True}
        except Exception as e:
            return {"success": False}

    @bridge.expose
    def update_ui_strikes(ce_strike, pe_strike):
        global ui_selected_ce_strike, ui_selected_pe_strike
        try:
            ui_selected_ce_strike = int(ce_strike)
            ui_selected_pe_strike = int(pe_strike)
            pass
            
            # Immediately notify UI with new strike LTPs
            if option_handler:
                if not option_handler._is_strike_subscribed(ui_selected_ce_strike):
                    option_handler._subscribe_to_strike(ui_selected_ce_strike)
                if not option_handler._is_strike_subscribed(ui_selected_pe_strike):
                    option_handler._subscribe_to_strike(ui_selected_pe_strike)
                
                notify_market_data_update({})
                
            return {"success": True}
        except Exception as e:
            return {"success": False}

    @bridge.expose
    def set_expiry(expiry):
        if not option_handler:
            return {"success": False, "message": "Option handler not initialized"}
        try:
            pass
            option_handler.set_expiry(expiry)
            try:
                chain_data = option_handler.get_option_chain(force_refresh=True)
                if chain_data and "atm_strike" in chain_data:
                    return {"success": True, "atm_strike": chain_data["atm_strike"]}
            except Exception as e:
                pass
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": f"Error: {e}"}

    @bridge.expose
    def get_positions():
        """Get current positions with PNL calculated from urmtom + rpnl."""
        return get_positions_internal()

    # ... Add other exposed functions (get_orders, start_breakout_strategy, etc) ...
    # For brevity, I will add the key ones needed for the UI demo.

    @bridge.expose
    def start_nifty_strategy(initial_qty, t1_qty, t2_qty, strike_ce, strike_pe,
                             direction_filter, trig_min=25, trig_max=45,
                             break_buffer=2.0, t1_pct=0.5, t2_pct=1.0, t3_mult=2,
                             pm_limit=100, start_time="09:35", stop_time="10:45", trail_points=12.0):
        global nifty_strategy
        try:
            if not api or not option_handler or not position_manager:
                return {"success": False, "message": "API not connected"}
            if not nifty_strategy:
                nifty_strategy = NiftyFiveMinStrategy(
                    api, option_handler, instrument_helper, position_manager, bridge)
            # Always re-configure so UI changes (strikes, params) take effect immediately
            nifty_strategy.configure(
                initial_qty, t1_qty, t2_qty, strike_ce, strike_pe,
                trig_min, trig_max, break_buffer, t1_pct, t2_pct, t3_mult,
                direction_filter=direction_filter, pm_limit=pm_limit,
                start_time=start_time, stop_time=stop_time, trail_points=trail_points)
            if not nifty_strategy.is_running:
                nifty_strategy.start()
            else:
                nifty_strategy._notify()  # push updated config to UI
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}

    @bridge.expose
    def update_nifty_config(initial_qty, t1_qty, t2_qty, strike_ce, strike_pe,
                            direction_filter, trig_min=25, trig_max=45,
                            break_buffer=2.0, t1_pct=0.5, t2_pct=1.0, t3_mult=2,
                            pm_limit=100, start_time="09:35", stop_time="10:45", trail_points=12.0):
        """Update strategy params in real-time without stopping/starting."""
        global nifty_strategy
        try:
            if not nifty_strategy or not nifty_strategy.is_running:
                return {"success": False, "message": "Strategy not running"}
            nifty_strategy.configure(
                initial_qty, t1_qty, t2_qty, strike_ce, strike_pe,
                trig_min, trig_max, break_buffer, t1_pct, t2_pct, t3_mult,
                direction_filter=direction_filter, pm_limit=pm_limit,
                start_time=start_time, stop_time=stop_time, trail_points=trail_points)
            nifty_strategy._notify()
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}

    @bridge.expose
    def stop_nifty_strategy():
        global nifty_strategy
        try:
            if not nifty_strategy:
                return {"success": False, "message": "Strategy not initialized"}
            nifty_strategy.stop()
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}

    @bridge.expose
    def force_nifty_entry(direction):
        global nifty_strategy
        try:
            if not nifty_strategy:
                return {"success": False, "message": "Strategy not initialized"}
            nifty_strategy.force_entry(direction)
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}

    @bridge.expose
    def get_nifty_state():
        global nifty_strategy
        if nifty_strategy:
            return nifty_strategy.get_state_dict()
        return {"state": "IDLE"}

    @bridge.expose
    def oi_toggle(enabled):
        return {"success": True}

    @bridge.expose
    def execute_ce_trade(strike_price, action, quantity):
        global option_handler
        if not option_handler: return {"success": False, "message": "Not initialized"}
        try:
            strike_price = int(strike_price)
            quantity = int(quantity)
            ce_symbol = option_handler.get_option_symbol(strike_price, option_type='CE')
            if not ce_symbol: return {"success": False, "message": "Symbol not found"}
            
            order_result = position_manager.place_order(
                tradingsymbol=ce_symbol, quantity=quantity, buy_or_sell=action,
                exchange="NFO", product_type='M', discloseqty=0, price_type="MKT"
            )
            if order_result and 'norenordno' in order_result:
                return {"success": True, "message": "Placed", "order_id": order_result['norenordno']}
            else:
                return {"success": False, "message": "Failed"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    @bridge.expose
    def execute_pe_trade(strike_price, action, quantity):
        global option_handler
        if not option_handler: return {"success": False, "message": "Not initialized"}
        try:
            strike_price = int(strike_price)
            quantity = int(quantity)
            pe_symbol = option_handler.get_option_symbol(strike_price, option_type='PE')
            if not pe_symbol: return {"success": False, "message": "Symbol not found"}
            
            order_result = position_manager.place_order(
                tradingsymbol=pe_symbol, quantity=quantity, buy_or_sell=action,
                exchange="NFO", product_type='M', discloseqty=0, price_type="MKT"
            )
            if order_result and 'norenordno' in order_result:
                return {"success": True, "message": "Placed", "order_id": order_result['norenordno']}
            else:
                return {"success": False, "message": "Failed"}
        except Exception as e:
            return {"success": False, "message": str(e)}
            
    @bridge.expose
    def toggle_oi_filter(enabled):
        return {"success": True}

    @bridge.expose
    def toggle_virtual(enabled=None): # Handle optional arg if any
        # Note: Frontend might send enabled status or just toggle
        pass
        global position_manager
        if position_manager:
            position_manager.toggle_virtual()
            return {"success": True}
        return {"success": False, "message": "Position manager not initialized"}

    @bridge.expose
    def get_orders():
        """Get current ordered (formatted for UI)"""
        try:
            if not position_manager:
                return []
            orders = position_manager.get_order_book()
            formatted_orders = []
            if orders:
                for order in orders:
                    formatted_orders.append({
                        'order_no': order.get('norenordno', ''),
                        'symbol': order.get('tsym', ''),
                        'type': order.get('trantype', ''),
                        'qty': int(order.get('qty', 0)),
                        'price': float(order.get('prc', 0)),
                        'status': order.get('status', '')
                    })
            return formatted_orders
        except Exception as e:
            pass
            return []

    @bridge.expose
    def get_atm_strike():
        global option_handler
        if option_handler:
            chain = option_handler.get_option_chain()
            if chain:
                return chain.get('atm_strike', 0)
        return 0

    @bridge.expose
    def get_lot_size(symbol="NIFTY"):
        try:
            if instrument_helper:
                return {"success": True, "lot_size": instrument_helper.get_lot_size(symbol)}
            return {"success": True, "lot_size": 25}
        except Exception as e:
            return {"success": False, "message": str(e)}



    @bridge.expose
    def initializePositionsAndOrders():
        # This was called from frontend in app.js, so here we trigger updates
        fetch_and_update_frontend_positions()
        # Also push orders
        orders = get_orders() # Call the exposed version internally
        if bridge and orders:
             for o in orders:
                 bridge.call("handleOrderUpdate", o)

    # Start Listener
    bridge.on_shutdown = lambda: sys.exit(0)
    # print(f"[BACKEND] Exposed functions: {list(bridge.exposed.keys())}")
    bridge.start()
    
    # Process Loop
    # print("[BACKEND] Running...")
    while True:
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            break
