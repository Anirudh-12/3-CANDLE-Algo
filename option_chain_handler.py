from __future__ import annotations


import time
from datetime import datetime, timedelta
from typing import (
    Dict, List, Tuple, Optional, Any, Callable, Literal, TypedDict, Final,
    Mapping, Iterable, Union, cast
)
from NorenRestApiPy.NorenApi import NorenApi, FeedType
from Get_Instruments import InstrumentHelper
import traceback
import math
import pandas as pd
from position_manager import PositionManager


# Type definitions
OptionType = Literal["CE", "PE"]
IndexType = Literal["NIFTY","NIFTY_SPOT", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX", "VIX"]
SectionName = Literal["section2", "section3", "section4", "section5", "section6"]

class OptionInfo(TypedDict, total=False):
    token: str
    symbol: str
    type: OptionType
    strike: float
    exchange: str
    ltp: float
    ap: float
    last_update: float

class StrikeLTPCache(TypedDict):
    CE: float
    PE: float

class StrikeOIData(TypedDict):
    oi: int
    poi: int

class StrikeOICache(TypedDict):
    CE: StrikeOIData
    PE: StrikeOIData

class TokenInfo(TypedDict, total=False):
    exchange: str
    token: str
    section: SectionName
    type: OptionType
    strike: float
    name: IndexType
    symbol: str

class IndexTokenData(TypedDict):
    exchange: str
    token: str

class OptionChainData(TypedDict, total=False):
    atm_strike: int
    spot_price: float
    strikes: List[int]
    options: Dict[str, OptionInfo]

class TotalOIData(TypedDict):
    CE: int
    PE: int

class OIChangeResult(TypedDict):
    total_oi: TotalOIData
    total_poi: TotalOIData
    oi_change: TotalOIData
    atm_strike: int
    strike_range: Dict[str, int]

class MarketDataMessage(TypedDict, total=False):
    t: str
    tk: str
    lp: str
    ap: str
    oi: str
    poi: str
    pc: str
    ltt: str # Last Trade Time
    ft: str  # Feed Time

StrategyCallback = Callable[[float], None]
PositionUpdateCallback = Callable[[], None]

class OptionChainHandler:
    def __init__(
        self,
        api: NorenApi,
        position_manager: PositionManager,
        position_update_func: Optional[PositionUpdateCallback] = None,
        market_data_update_func: Optional[Callable[[Dict], None]] = None
    ) -> None:
        self.api: NorenApi = api
        self.position_update_func: Optional[PositionUpdateCallback] = position_update_func
        self.market_data_update_func = market_data_update_func
        self.is_running: bool = False
        self.position_manager: PositionManager = position_manager
        self.subscribed_options: Dict[SectionName, List[TokenInfo]] = {}
        self.current_strikes: Dict[SectionName, int] = {
            "section2": 0, 
            "section3": 0,
            "section4": 0,
            "section5": 0,
            "section6": 0,
        }
        self.current_token_mapping: Dict[SectionName, Dict[OptionType, Optional[str]]] = {
            "section2": {"CE": None, "PE": None},
            "section3": {"CE": None, "PE": None},
            "section4": {"CE": None, "PE": None},
            "section5": {"CE": None, "PE": None},
            "section6": {"CE": None, "PE": None},
        }
          # New reverse mapping
        self.current_ltp_data: Dict[str, float] = {}
        self.strike_ltp_cache: Dict[int, StrikeLTPCache] = {}  # {strike: {"CE": ltp, "PE": ltp}}
        self.strike_oi_cache: Dict[int, StrikeOICache] = {}  # {strike: {"CE": {"oi": 0, "poi": 0}, "PE": {"oi": 0, "poi": 0}}}
        self.total_oi: TotalOIData = {"CE": 0, "PE": 0}  # Total OI for CE and PE
        self.total_poi: TotalOIData = {"CE": 0, "PE": 0}  # Total previous day OI for CE and PE
        self.index: IndexType = "NIFTY"
        self.exchange: str = "NFO"
        self.expiry: Optional[str] = None
        
        # Throttling for position updates
        self.last_position_update_time: float = 0.0
        self.POSITION_UPDATE_INTERVAL: Final[int] = 1  # Seconds
        #startdate = timestamp
        
        # Initialize the InstrumentHelper
        try:
            self.instrument_helper: Optional[InstrumentHelper] = InstrumentHelper()
        except Exception as e:
            pass
            self.instrument_helper = None
        
        # Index information
        self.index_tokens: Dict[IndexType, IndexTokenData] = {
            "VIX": {"exchange": "NSE", "token": "26017"}
        }
        tok: Optional[str] = None
        if self.instrument_helper:
            tok = self.instrument_helper.get_nifty_fut_token()
        if tok:
            self.index_tokens["NIFTY"] = {"exchange": "NFO", "token": str(tok)}
        self.index_tokens["NIFTY_SPOT"] = {"exchange": "NSE", "token": "26000"}
        self.index_ltp: float = 0.0
        self.index_ap: float = 0.0
        
        self.spot_ltp: float = 0.0  # Separate spot LTP for OI calculation
        # Map of token to symbol info for lookup
        self.token_to_symbol: Dict[str, TokenInfo] = {}
        
        # Cache for option chain data
        self.option_chain_cache: Dict[str, OptionInfo] = {}
        self.option_chain_last_update: float = 0.0
        
        # Strategy callbacks
        self.strategy_callbacks: List[StrategyCallback] = []
        self.token_symbol_dict: Dict[str, str] = {}
        self.atm_strike: int = 0
        
        # OI calculation throttling
        self._last_oi_calculation_time: float = 0.0
    
    def register_strategy_callback(self, callback: StrategyCallback) -> bool:
        """Register a callback function for strategy integration"""
        if callback not in self.strategy_callbacks:
            self.strategy_callbacks.append(callback)
            return True
        return False
        
    def unregister_strategy_callback(self, callback: StrategyCallback) -> bool:
        """Unregister a callback function"""
        if callback in self.strategy_callbacks:
            self.strategy_callbacks.remove(callback)
            return True
        return False
        
    def set_expiry(self, expiry: str) -> None:
        try:
            """Set the current expiry date"""
            if self.instrument_helper:
                self.token_symbol_dict = self.instrument_helper.get_token_symbol_dict(expiry)
            self.expiry = expiry
            # Clear the option chain cache when expiry changes
            self.option_chain_cache = {}
            self.option_chain_last_update = 0
            
            # Ensure future data is available for the new expiry immediately
            
        except Exception as e:
            pass
            # traceback.print_exc()
    def set_index(self, index: IndexType) -> None:
        """Set the current index"""
        self.index = index
        # Clear the option chain cache when index changes
        self.option_chain_cache = {}
        self.option_chain_last_update = 0.0
        
    def update_strike(self, section: SectionName, strike_value: Union[int, float, str]) -> None:
        """Update the strike price for a specific section"""
        strike_value = int(strike_value)
        
        
        # Remove old strike mapping
        
        
        # Update strike
        self.current_strikes[section] = strike_value
        self.current_token_mapping[section] = {"CE": None, "PE": None}
        # Update reverse mapping
        
        
        # If this is our first time setting up strikes, or if we haven't subscribed at all yet
        if not self.subscribed_options or len(self.subscribed_options) == 0:
            # Need to subscribe to everything
            self._subscribe_to_options()
            return
        
        # For existing options, just update the UI with the current values for this strike
        section_num = section.replace("section", "")
        
            # Get LTP values for this strike from our cache
        if strike_value in self.strike_ltp_cache:
            ce_ltp = self.strike_ltp_cache[strike_value].get("CE", 0)
            pe_ltp = self.strike_ltp_cache[strike_value].get("PE", 0)
            combined_ltp = ce_ltp + pe_ltp
            
            # Update UI with current values for the new strike
            # Store token mapping for this section-strike association
            # This lets us identify which section to update when we get LTP updates
            self._update_token_mapping_for_section(section, strike_value)
        else:
            # We don't have this strike in our cache, need to add it
            # Check if we need to subscribe to new tokens
            if not self._is_strike_subscribed(strike_value):
                # If it's a new strike and we're not subscribed to it yet, subscribe just to this strike
                self._subscribe_to_strike(strike_value)
            else:
                # Just update UI with placeholder values until we get real data
                placeholder = 0.01
                self._update_ui(section_num, placeholder, placeholder, placeholder * 2)
                
            # Update token mapping for the new strike
            self._update_token_mapping_for_section(section, strike_value)
            
        # Log the current section to token mappings for diagnostic purposes
        
    
    def get_available_expiry_dates(self, index: IndexType = "NIFTY") -> List[str]:
        """
        Get the available expiry dates for the given index using InstrumentHelper.
        Returns a list of expiry dates as provided by InstrumentHelper (dd-MMM-YYYY format).
        """
        
        if self.instrument_helper is None:
            pass
            try:
                self.instrument_helper = InstrumentHelper()
            except Exception as e:
                pass
                return []
        
        try:
            # Get expiry dates from InstrumentHelper
            expiry_dict = self.instrument_helper.get_expirys_dict([index])
            
            if index not in expiry_dict:
                pass
                return []
                
            # Get expiry dates - use them directly without formatting
            expiry_dates = expiry_dict[index]
            
            # Sort the dates chronologically
            # Convert to datetime objects for proper chronological sorting
            def parse_date(date_str: str) -> datetime:
                try:
                    return datetime.strptime(date_str, "%d-%b-%Y")
                except Exception as e:
                    pass
                    return datetime.max  # Return far future date for parsing errors
            
            sorted_dates = sorted(expiry_dates, key=parse_date)
            
            return sorted_dates
        except Exception as e:
            pass
            return []
    
    def get_option_chain(self, force_refresh: bool = False) -> Optional[OptionChainData]:
        
        
        # Check if we need to refresh the cache
        if force_refresh:
            if not self.expiry:
                pass
                return None
                
            if not self.instrument_helper:
                pass
                return None
                
            
            try:
                # Get the current spot price of the index
                spot_data = self.api.get_quotes(self.index_tokens[self.index]["exchange"], 
                                               self.index_tokens[self.index]["token"])
                
                if not spot_data or 'lp' not in spot_data:
                    pass
                    return None
                    
                spot_price = float(spot_data.get('lp', 0))
                if spot_price <= 0:
                    pass
                    return None
                
                # Get step size for this index
                step_size = self.instrument_helper.get_step_size(self.index)
                self.instrument_helper.step_size = step_size
                # Round to nearest strike based on step size
                atm_strike = round(spot_price / step_size) * step_size
                atm_strike = int(atm_strike)  # Ensure it's an integer
                # Use the expiry directly - assuming it's already in dd-MMM-YYYY format
                formatted_expiry = self.expiry
                
                # Get a sample trading symbol for the index and expiry to fetch the option chain
                # We can use any CE/PE symbol for the given index and expiry from InstrumentHelper
                sample_symbols = self.instrument_helper.ce_strike_to_symbol(self.index, formatted_expiry)
                if not sample_symbols:
                    # fallback to PE if CE is not available
                    sample_symbols = self.instrument_helper.pe_strike_to_symbol(self.index, formatted_expiry)
                
                if not sample_symbols:
                    pass
                    return None
                
                # Use the first available symbol as a reference to get the entire chain
                sample_symbol = list(sample_symbols.values())[0]
                
                # Get option strikes from Broker API instead of InstrumentHelper
                chain_res = self.api.get_option_chain(
                    exchange=self.exchange,
                    tradingsymbol=sample_symbol,
                    strikeprice=atm_strike,
                    count=15  # Get 30 strikes total (15 above, 15 below)
                )
                
                if not chain_res or chain_res.get('stat') != 'Ok' or 'values' not in chain_res:
                    pass
                    return None
                
                option_strikes = chain_res['values']
                # print(f"Fetched {len(option_strikes)} option strikes from broker for {self.index} with ATM strike {atm_strike}")
                
                # Process and cache the option chain
                self.option_chain_cache = self._process_option_chain_from_api(option_strikes)
                
                
                # Return all available strikes from the option chain
                available_strikes = sorted(list(set([int(float(option['strike'])) for option in self.option_chain_cache.values()
                    if 'strike' in option])))
                
                return {
                    "atm_strike": atm_strike,
                    "spot_price": spot_price,
                    "strikes": available_strikes,
                    "options": self.option_chain_cache
                }
            except Exception as e:
                pass
                return None
        else:
            # Return cached data
            available_strikes = sorted([int(option['strike']) for option in self.option_chain_cache.values()
                if 'strike' in option])
            
            return {
                "atm_strike": self._get_atm_strike_from_cache(),
                "spot_price": self._get_spot_price_from_cache(),
                "strikes": available_strikes,
                "options": self.option_chain_cache
            }
    
    def _process_option_chain_from_api(self, option_strikes: List[Dict[str, Any]]) -> Dict[str, OptionInfo]:
        """Process option chain data from Broker API into a usable format"""
        option_chain: Dict[str, OptionInfo] = {}
        
        for option in option_strikes:
            try:
                # API uses lowercase 'token', 'tsym' (trading symbol), 'optt' (option type), 'strprc' (strike price)
                if 'token' not in option or 'tsym' not in option:
                    continue
                    
                token = option['token']
                symbol = option['tsym']
                
                # Get option type
                option_type = option['optt']  # CE or PE
                
                # Extract strike price 
                strike = float(option['strprc'])
                
                # Store option information
                option_info: OptionInfo = {
                    "token": str(token),
                    "symbol": symbol,
                    "type": cast(OptionType, option_type),  # Cast from external data
                    "strike": strike,
                    "exchange": self.exchange,
                    "ltp": 0.0,  # Initialize with 0, will be updated via market data
                    "ap": 0.0,   # Initialize average price with 0
                    "last_update": time.time()
                }
                
                option_chain[token] = option_info
                
                # Add to token mapping
                self.token_to_symbol[token] = {
                    "type": option_type,
                    "strike": strike,
                    "symbol": symbol
                }
                
            except Exception as e:
                pass
                
        return option_chain
    
    def _get_atm_strike_from_cache(self) -> int:
        """Get the ATM strike from the cache"""
        if not self.option_chain_cache:
            return 0
            
        # Get unique strikes
        strikes = set([
            option['strike'] for option in self.option_chain_cache.values()
            if 'strike' in option
        ])
        
        if not strikes:
            return 0
            
        # Get spot price (average of closest strikes)
        sorted_strikes = sorted([int(s) for s in strikes])
        middle_index = len(sorted_strikes) // 2
        return sorted_strikes[middle_index]
    
    def _get_spot_price_from_cache(self) -> float:
        """Estimate spot price from the cache"""
        atm_strike = self._get_atm_strike_from_cache()
        if atm_strike == 0:
            return 0.0
            
        # Find CE and PE options at ATM strike
        ce_option = next((option for option in self.option_chain_cache.values()
                         if option.get('strike') == atm_strike and option.get('type') == 'CE'), None)
        pe_option = next((option for option in self.option_chain_cache.values()
                         if option.get('strike') == atm_strike and option.get('type') == 'PE'), None)
                         
        if not ce_option or not pe_option:
            return atm_strike
            
        # Use put-call parity to estimate spot price
        # S = K + C - P (simplified)
        spot_estimate = atm_strike + ce_option.get('ltp', 0) - pe_option.get('ltp', 0)
        return spot_estimate
    
    def _get_option_token(self, symbol: IndexType, option_type: OptionType, strike: int) -> Dict[str, str]:
        """Get the exchange and token for an option based on symbol, option type and strike"""
        # First check if we have it in the cache
        for token, option in self.option_chain_cache.items():
            if (option.get('strike') == strike and option.get('type') == option_type):
                return {"exchange": self.exchange, "token": token}
        
        # If not in cache and we have InstrumentHelper, use it to find the token
        if self.instrument_helper and self.expiry:
            try:
                # Use expiry directly - assume it's already in dd-MMM-YYYY format
                formatted_expiry = self.expiry
                
                # Get the token map
                if option_type == "CE":
                    token_map = self.instrument_helper.ce_strike_to_token(symbol, formatted_expiry)
                else:
                    token_map = self.instrument_helper.pe_strike_to_token(symbol, formatted_expiry)
                
                # Find the token for this strike
                if strike in token_map:
                    token = token_map[strike]
                    return {"exchange": self.exchange, "token": token}
            except Exception as e:
                pass
        
        # If still not found, use the default format
        return {"exchange": self.exchange, "token": f"{strike}{option_type}"}
    
    def _subscribe_to_indices(self) -> None:
        """Subscribe to index data (NIFTY and VIX)"""
        index_instruments: List[str] = []
        
        # Format: exchange|token
        for index, data in self.index_tokens.items():
            exchange = data["exchange"]
            token = data["token"]
            subscription = f"{exchange}|{token}"
            index_instruments.append(subscription)
            
            # Store mapping for later lookup
            self.token_to_symbol[token] = {"name": index, "exchange": exchange}
            
        self.api.subscribe(index_instruments, FeedType.TOUCHLINE)
    
    def _subscribe_to_options(self) -> None:
        """Subscribe to the options based on current strikes"""
        # First time setup - subscribe to everything we need
        
        # Clear previous subscriptions and mappings
        self.subscribed_options = {}
        self.token_to_symbol = {}
        
        # Subscribe to indices first
        self._subscribe_to_indices()
        
        # Make sure we have the option chain
        self.get_option_chain(force_refresh=True)
        
        # Subscribe to the entire option chain and populate our cache
        self._subscribe_to_all_options()
        
        # Set up token mappings for the current strikes
        for section, strike in self.current_strikes.items():
            if strike <= 0:
                continue
                
            self._update_token_mapping_for_section(section, strike)
            
        # Update the UI with initial values for all sections
        self._update_all_sections_ui()
    
    def _subscribe_to_all_options(self) -> None:
        """Subscribe to all options in the option chain and populate the strike LTP cache"""
        if not self.option_chain_cache:
            pass
            return
            
        subscription_list: List[str] = []
        
        # Build subscription list and initialize strike cache
        for token, option in self.option_chain_cache.items():
            subscription = f"{self.exchange}|{token}"
            subscription_list.append(subscription)
            
            # Initialize strike LTP cache
            strike_raw = option.get('strike')
            option_type_raw = option.get('type')
            
            if strike_raw is not None and option_type_raw:
                strike = int(strike_raw)
                option_type: OptionType = cast(OptionType, option_type_raw)
                if strike not in self.strike_ltp_cache:
                    self.strike_ltp_cache[strike] = {"CE": 0.0, "PE": 0.0}
            
                # Initialize strike OI cache
                if strike not in self.strike_oi_cache:
                    self.strike_oi_cache[strike] = {
                        "CE": {"oi": 0, "poi": 0},
                        "PE": {"oi": 0, "poi": 0}
                    }
            
                # Use existing LTP if available
                ltp = option.get('ltp', 0.0)
                if ltp > 0:
                    self.strike_ltp_cache[strike][option_type] = float(ltp)
        
        if subscription_list:
            # Subscribe in batches to avoid overwhelming the API
            batch_size = 50
            for i in range(0, len(subscription_list), batch_size):
                batch = subscription_list[i:i+batch_size]
                try:
                    self.api.subscribe(batch, FeedType.TOUCHLINE)
                    time.sleep(0.5)  # Small delay between batches
                except Exception as e:
                    pass
                    
    
    def _update_all_sections_ui(self) -> None:
        """Update the UI with initial values for all sections"""
        # Use small non-zero values (0.01) for initialization to avoid showing zeros
        placeholder_value: float = 0.01
        
        # Update all sections with small placeholder values
        for section_name in self.current_strikes.keys():
            section_num = section_name.replace("section", "")
            self._update_ui(section_num, placeholder_value, placeholder_value, placeholder_value * 2)
        
        # Also initialize sections 2, 3, 4, and 5 with placeholder values
        self._update_ui("2", placeholder_value, placeholder_value, placeholder_value * 2)
        self._update_ui("3", placeholder_value, placeholder_value, placeholder_value * 2)
        self._update_ui("4", placeholder_value, placeholder_value, placeholder_value * 2)
        self._update_ui("5", placeholder_value, placeholder_value, placeholder_value * 2)
    
    def option_update_callback(self, message: Dict[str, Any]) -> None:
        """Callback for option chain updates, includes throttled position refresh."""
        processed: bool = False  # Keep track if specific message was used by cache
        
        try:
            # Update option chain cache first
            processed = self._update_option_chain_cache(message)
            # self._monitor_strategies() # Strategy monitoring if needed

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Error in option_update_callback: {e}")
        self._monitor_strategies()

        # --- Time-based position update throttling --- 
        # Triggered by ANY relevant tick message, but limited by time interval
        current_time = time.time()
        
        
       
        
        # --------------------------------------------

        if self.position_update_func:
            self.position_update_func()  # Call the function passed during init
        self.last_position_update_time = current_time  # Reset timer
        
        # Calculate total OI periodically (every 5 seconds to avoid overhead)
        if current_time - self._last_oi_calculation_time >= 5:
            self.calculate_total_oi()
            self._last_oi_calculation_time = current_time
            
        # else:
            # if not self.position_update_func:
            #     logger.warning("position_update_func not set in OptionChainHandler.")
            # logger.debug("Skipping position update due to throttling or missing function.")
    
    def _monitor_strategies(self) -> None:
        """Monitor all registered strategies"""
        try:
            # Get current option chain data
            
                
            # Monitor section 4 strategy if it exists
           
           
            for strategy in self.strategy_callbacks:
                try:
                    if self.index_ltp == 0:
                        continue
                    # Call strategy with ltp, and pass ap as keyword argument
                    strategy(self.index_ltp, index_ap=self.index_ap)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    print(f"Error calling strategy: {e}")
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Error in _monitor_strategies: {e}")
            
    def register_strategy(self, strategy_name: str, strategy_instance: Any) -> None:
        """Register a strategy for monitoring"""
        try:
            setattr(self, strategy_name, strategy_instance)
        except Exception as e:
            pass
            
    def unregister_strategy(self, strategy_name: str) -> None:
        """Unregister a strategy from monitoring"""
        try:
            if hasattr(self, strategy_name):
                delattr(self, strategy_name)
        except Exception as e:
            pass
    
    def _update_option_chain_cache(self, message: Dict[str, Any]) -> bool:
        """Update the option chain cache based on the received message"""
        try:
            if message.get('t') not in ['tf', 'tk']:
                return False
                
            # Extract token and exchange from the message
            token_str = str(message.get('tk', ''))
            token = token_str.split('|')[-1] if '|' in token_str else token_str
            ltp = float(message.get('lp', 0))
            
            # Get average price if available
            ap = float(message.get('ap', 0))
            
            # Extract OI data from message
            oi = int(message.get('oi', 0))  # Current Open Interest
            poi = int(message.get('poi', 0))  # Previous day Open Interest
            
            # Don't process zero LTPs
            if ltp <= 0:
                return False
            
            # Update position manager LTP (wrapped in try-except to not block strike cache update)
            symbol = self.token_symbol_dict.get(token)
            if symbol:
                try:
                    self.position_manager.update_ltp(symbol, ltp)
                except Exception as ltp_err:
                    import traceback
                    traceback.print_exc()
                    print(f"Error updating position manager LTP: {ltp_err}")
            else:
                pass
            # Update index value if this is an index token
            for index, data in self.index_tokens.items():
                if token == data["token"]:
                    # This is an index update
                    if index == "NIFTY":
                        # Extract ltp, pc, ap
                        nifty_ltp = float(message.get('lp', 0))
                        nifty_pc = float(message.get('pc', 0))
                        nifty_ap = float(message.get('ap', 0))
                        
                        if nifty_ap > 0:
                            self.index_ap = nifty_ap
                        
                        # Extract LTT
                        

                        
                        # Send LTP if valid
                        if nifty_ltp > 0:
                            self.index_ltp = ltp
                            update_data: Dict[str, str] = {"nifty_ltp": str(nifty_ltp)}
                            
                            # Calculate and send Change
                            if not math.isnan(nifty_pc):
                                # Change = (PC * LTP) / (100 + PC)
                                # Denominator check to avoid div by zero (unlikely for index)
                                if (100 + nifty_pc) != 0:
                                    change = (nifty_pc * nifty_ltp) / (100 + nifty_pc)
                                    update_data["nifty_change"] = "{:.2f}".format(change)
                            
                            if self.market_data_update_func:
                                self.market_data_update_func(update_data)  # type: ignore[attr-defined]
                            
                        # Send PC if valid
                        if not math.isnan(nifty_pc):
                             if self.market_data_update_func:
                                self.market_data_update_func({"nifty_pc": str(nifty_pc)})
                            
                            
                     # type: ignore[attr-defined]
                    elif index == "NIFTY_SPOT":
                        # Store spot LTP for OI calculation only
                        spot_ltp = float(message.get('lp', 0))
                        if spot_ltp > 0:
                            self.spot_ltp = spot_ltp
                    return True
            
            # Update the option chain cache if this token exists there
            if token in self.option_chain_cache:
                option_info = self.option_chain_cache[token]
                option_info['ltp'] = ltp
                
                # Update average price if available
                # if ap > 0:
                #     option_info['ap'] = ap
                
                option_info['last_update'] = time.time()
                
                # Update strike LTP cache
                strike_raw = option_info.get('strike')
                option_type_raw = option_info.get('type')
                
                if strike_raw is not None and option_type_raw:
                    strike = int(strike_raw)
                    option_type: OptionType = cast(OptionType, option_type_raw)
                    # Initialize strike entry if not exists
                    if strike not in self.strike_ltp_cache:
                        self.strike_ltp_cache[strike] = {"CE": 0.0, "PE": 0.0}
            
                    # Update the LTP for this strike and type
                    self.strike_ltp_cache[strike][option_type] = ltp
                    
                    # Initialize and update strike OI cache
                    if strike not in self.strike_oi_cache:
                        self.strike_oi_cache[strike] = {
                            "CE": {"oi": 0, "poi": 0},
                            "PE": {"oi": 0, "poi": 0}
                        }
                    
                    # Update OI and POI for this strike and type
                    if oi > 0:
                        self.strike_oi_cache[strike][option_type]["oi"] = oi
                    if poi > 0:
                        self.strike_oi_cache[strike][option_type]["poi"] = poi
                    
                    # Send live OI change update
                    self._send_live_oi_change()
                    
                    # Calculate combined LTP for this strike
                    
                    # Use strike_to_sections mapping to find all sections using this strike
                    
                    # Update UI for all sections using this strike
                    
            # For option tokens, process if this token is directly mapped to a section
            return True
            
        except Exception as e:
            pass
            return False
    
    
    def calculate_total_oi(self) -> Optional[OIChangeResult]:
        """Calculate OI change (OI - POI) for CE and PE options around ATM"""
        try:
            # Reset totals
            self.total_oi = {"CE": 0, "PE": 0}
            self.total_poi = {"CE": 0, "PE": 0}
            oi_change: TotalOIData = {"CE": 0, "PE": 0}
            
            # Get ATM strike from current spot LTP (not futures)
            atm_strike: int = 0
            if self.spot_ltp > 0:
                # Get step size for this index
                step_size: float = 50.0  # Default for NIFTY
                if self.instrument_helper:
                    step_size = self.instrument_helper.get_step_size(self.index)
                
                # Round to nearest strike
                atm_strike = int(round(self.spot_ltp / step_size) * step_size)
            
            # If we don't have spot_ltp yet, try to get ATM from cache
            if atm_strike == 0:
                atm_strike = self._get_atm_strike_from_cache()
            
            # Calculate strike range: ATM-10 to ATM+10 strikes
            # For NIFTY with 50 step size: ATM-500 to ATM+500
            # Reuse step_size from above or get it again
            if self.instrument_helper:
                step_size = self.instrument_helper.get_step_size(self.index)
            else:
                step_size = 50.0  # Default for NIFTY
            
            strike_range: int = 10  # Number of strikes above and below ATM
            min_strike: int = int(atm_strike - (strike_range * step_size))
            max_strike: int = int(atm_strike + (strike_range * step_size))
            
            # Sum up OI and POI for strikes within the range
            strikes_counted: int = 0
            for strike, oi_data in self.strike_oi_cache.items():
                # Apply strike filter: ATM-10 to ATM+10
                if min_strike <= strike <= max_strike:
                    self.total_oi["CE"] += oi_data["CE"]["oi"]
                    self.total_oi["PE"] += oi_data["PE"]["oi"]
                    self.total_poi["CE"] += oi_data["CE"]["poi"]
                    self.total_poi["PE"] += oi_data["PE"]["poi"]
                    strikes_counted += 1
            
            # Calculate OI change (OI - POI)
            oi_change["CE"] = self.total_oi["CE"] - self.total_poi["CE"]
            oi_change["PE"] = self.total_oi["PE"] - self.total_poi["PE"]
            
            
            # Send OI change data to frontend
            try:
                if self.market_data_update_func:
                    self.market_data_update_func({  
                        "ce_change_oi": oi_change["CE"],
                        "pe_change_oi": oi_change["PE"]
                        }
                    )
                
            except Exception as eel_error:
                pass
            
            return {
                "total_oi": self.total_oi,
                "total_poi": self.total_poi,
                "oi_change": oi_change,
                "atm_strike": atm_strike,
                "strike_range": {"min": min_strike, "max": max_strike}
            }
        except Exception as e:
            pass
            return None
    
    def _send_live_oi_change(self) -> None:
        """Send live OI change updates to frontend (lightweight version)"""
        try:
            # Get ATM strike using spot LTP (not futures)
            atm_strike: int = 0
            step_size: float = 50.0  # Default for NIFTY
            if self.spot_ltp > 0:
                if self.instrument_helper:
                    step_size = self.instrument_helper.get_step_size(self.index)
                atm_strike = int(round(self.spot_ltp / step_size) * step_size)
            
            if atm_strike == 0:
                atm_strike = self._get_atm_strike_from_cache()
                if atm_strike == 0:
                    return  # Can't calculate without ATM
            
            # Calculate strike range: ATM-10 to ATM+10
            # Reuse step_size from above or get it again if needed
            if self.instrument_helper:
                step_size = self.instrument_helper.get_step_size(self.index)
            else:
                step_size = 50.0
            
            strike_range: int = 10
            min_strike: int = int(atm_strike - (strike_range * step_size))
            max_strike: int = int(atm_strike + (strike_range * step_size))
            
            # Calculate OI change for the range
            ce_oi: int = 0
            ce_poi: int = 0
            pe_oi: int = 0
            pe_poi: int = 0
            
            for strike, oi_data in self.strike_oi_cache.items():
                if min_strike <= strike <= max_strike:
                    ce_oi += oi_data["CE"]["oi"]
                    ce_poi += oi_data["CE"]["poi"]
                    pe_oi += oi_data["PE"]["oi"]
                    pe_poi += oi_data["PE"]["poi"]
            
            # Calculate changes
            ce_change = ce_oi - ce_poi
            pe_change = pe_oi - pe_poi
            
            if self.market_data_update_func:
                self.market_data_update_func({  # type: ignore[attr-defined]
                    "ce_change_oi": ce_change,
                    "pe_change_oi": pe_change
                }
                )
            # Send to frontend
           
            
        except Exception as e:
            pass
    
    def get_strike_oi(self, strike: int) -> StrikeOICache:
        """Get OI data for a specific strike"""
        return self.strike_oi_cache.get(strike, {
            "CE": {"oi": 0, "poi": 0},
            "PE": {"oi": 0, "poi": 0}
        })
    
    def get_option_ltp(self, strike: int, option_type: OptionType) -> float:
        """Get the latest LTP for a specific option"""
        if strike in self.strike_ltp_cache:
            return self.strike_ltp_cache[strike].get(option_type, 0.0)
        return 0.0
    # def get_option_ap(self, strike: int, option_type: OptionType) -> float:
    #     """Get the latest AP for a specific option"""
    #     for token, option in self.option_chain_cache.items():
    #         if option.get('strike') == strike and option.get('type') == option_type:
    #             return option.get('ap', 0.0)
    #     return 0.0
    
    def get_option_oi(self, strike: int, option_type: OptionType) -> int:
        """Get the latest OI for a specific option"""
        if strike in self.strike_oi_cache:
            return self.strike_oi_cache[strike][option_type]["oi"]
        return 0
    
    def get_option_poi(self, strike: int, option_type: OptionType) -> int:
        """Get the previous day OI for a specific option"""
        if strike in self.strike_oi_cache:
            return self.strike_oi_cache[strike][option_type]["poi"]
        return 0

    def get_strikes_near_price(self, price: float, count: int = 5) -> List[int]:
        """Get strike prices near a given price"""
        if not self.option_chain_cache:
            return []
            
        # Get unique strikes
        strikes = set([
            option['strike'] for option in self.option_chain_cache.values()
            if 'strike' in option
        ])
        
        if not strikes:
            return []
            
        # Sort strikes and find those near the given price
        sorted_strikes = sorted([int(s) for s in strikes])
        
        # Find closest strike
        closest_strike = min(sorted_strikes, key=lambda x: abs(x - price))
        closest_index = sorted_strikes.index(closest_strike)
        
        # Get strikes around the closest
        start_index = max(0, closest_index - count // 2)
        end_index = min(len(sorted_strikes), start_index + count)
        
        return sorted_strikes[start_index:end_index]
    
    def start_monitoring(self) -> None:
        """Start monitoring option chain data"""
        if self.is_running:
            return
            
        self.is_running = True
        
        # Subscribe to options if we haven't done so yet
        if not self.subscribed_options or len(self.strike_ltp_cache) == 0:
            self._subscribe_to_options()
        
        # Create a monitoring thread to periodically refresh the option chain
        
        
    
    
        
    
    
    def stop_monitoring(self) -> None:
        """Stop monitoring option chain data"""
        self.is_running = False
        
        # Wait for monitoring thread to finish
        
        
        # Unsubscribe from all options
        for section, tokens in self.subscribed_options.items():
            if tokens:
                unsubscribe_list = []
                for token_info in tokens:
                    unsubscribe_list.append(f"{token_info['exchange']}|{token_info['token']}")
                
                if unsubscribe_list:
                    try:
                        self.api.unsubscribe(unsubscribe_list, FeedType.TOUCHLINE)
                    except Exception as e:
                        pass
        
        # Unsubscribe from indices
        index_unsubscribe = []
        for index, data in self.index_tokens.items():
            index_unsubscribe.append(f"{data['exchange']}|{data['token']}")
        
        if index_unsubscribe:
            try:
                self.api.unsubscribe(index_unsubscribe, FeedType.TOUCHLINE)
            except Exception as e:
                pass
        
        self.subscribed_options = {}
        self.token_to_symbol = {}

    def _is_strike_subscribed(self, strike: int) -> bool:
        """Check if we're already subscribed to a particular strike"""
        return strike in self.strike_ltp_cache
    
    def _update_token_mapping_for_section(self, section: SectionName, strike_value: int) -> None:
        """Update the token mapping for a specific section and strike"""
        # First, remove any existing token mappings for this section to avoid duplicate updates
        
        
        # Find CE and PE tokens for this strike
        ce_token = None
        pe_token = None
        
        for token, option in self.option_chain_cache.items():
            if option.get('strike') == strike_value:
                if option.get('type') == 'CE':
                    ce_token = token
                elif option.get('type') == 'PE':
                    pe_token = token
                self.current_token_mapping[section] = {
                    "CE": ce_token,
                    "PE": pe_token,
                }
        if ce_token and pe_token:
            # Store mapping for later lookup
            self.token_to_symbol[ce_token] = {
                "section": section,
                "type": "CE",
                "strike": strike_value,
                "exchange": self.exchange
            }
            
            self.token_to_symbol[pe_token] = {
                "section": section,
                "type": "PE",
                "strike": strike_value,
                "exchange": self.exchange
            }
            
            # Store token info for this section
            self.subscribed_options[section] = [
                {"exchange": self.exchange, "token": ce_token},
                {"exchange": self.exchange, "token": pe_token}
            ]
            
            
   
    def _subscribe_to_strike(self, strike_value: int) -> bool:
        """Subscribe to a specific strike price"""
        # Make sure we have the option chain
        if len(self.option_chain_cache) == 0:
            self.get_option_chain(force_refresh=True)
            
        # Find CE and PE tokens for this strike
        ce_token: Optional[str] = None
        pe_token: Optional[str] = None
        
        for token, option in self.option_chain_cache.items():
            if option.get('strike') == strike_value:
                if option.get('type') == 'CE':
                    ce_token = token
                elif option.get('type') == 'PE':
                    pe_token = token
                    
        if not ce_token or not pe_token:
            # Try using the token retrieval method
            ce_token_info = self._get_option_token(self.index, "CE", strike_value)
            pe_token_info = self._get_option_token(self.index, "PE", strike_value)
            
            ce_token = ce_token_info['token']
            pe_token = pe_token_info['token']
            
        # If we found tokens, subscribe
        if ce_token and pe_token:
            # Initialize strike in cache (will be updated with real values on market data updates)
            if strike_value not in self.strike_ltp_cache:
                self.strike_ltp_cache[strike_value] = {"CE": 0.0, "PE": 0.0}
                
            # Subscribe to these tokens
            subscription_list = [
                f"{self.exchange}|{ce_token}",
                f"{self.exchange}|{pe_token}"
            ]
            
            try:
                pass
                self.api.subscribe(subscription_list, FeedType.TOUCHLINE)
            except Exception as e:
                pass
                
            return True
        else:
            pass
            return False

    def _log_section_mappings(self) -> None:
        """Log the current section to token mappings for diagnostic purposes"""
        for section, strike in self.current_strikes.items():
            pass
            
        for token, info in self.token_to_symbol.items():
            if 'section' in info:
                section_raw = info.get('section')
                mapped_section: SectionName = section_raw if isinstance(section_raw, str) and section_raw in ["section2", "section3", "section4", "section5", "section6"] else "section2"  # type: ignore[assignment]
                strike_raw = info.get('strike', 0)
                mapped_strike: int = int(strike_raw) if isinstance(strike_raw, (int, float)) else 0
                option_type = info.get('type', '')

    def _update_ui(self, section_num: str, ce_ltp: float, pe_ltp: float, combined_ltp: float) -> None:
        """Update UI with option values for a section"""
        # This method is called to update the UI but implementation may be handled elsewhere
        # Adding type hints for completeness
        pass
  
    def get_option_symbol(self, strike: int, option_type: OptionType) -> Optional[str]:
        """
        Get the option symbol for the given strike and option type
        
        Args:
            strike (int): Strike price
            option_type (str): Option type (CE or PE)
            
        Returns:
            str: Option symbol or None if not found
        """
        try:
            # Check if option_handler is initialized
            
            
            # Get expiry and index
            expiry = self.expiry
            index = self.index
            
            if not expiry:
                pass
                return None
                
            # Defensive check (mypy knows index is always truthy as IndexType, but kept for runtime safety)
            if not index:  # type: ignore[unreachable]
                return None
            
            
            # Priority 1: Check the option_chain_cache
            
            for token, option_info in self.option_chain_cache.items():
                if (option_info.get('strike') == strike and 
                    option_info.get('type') == option_type):
                    symbol = option_info.get('symbol')
                    if symbol:
                        pass
                        return symbol
                    else:
                        pass

            # Priority 2: Try to get the symbol from the strike_symbols dictionary if available (Fallback)
            # (Keeping this section as a potential fallback, but cache should be primary)
            
            
           
            # Final Fallback: Construct the symbol manually (Least reliable)
            parts = expiry.split('-')
            if len(parts) != 3:
                pass
                return None
                
            day = parts[0]
            month = parts[1].upper()[:3]  # First 3 chars of month in uppercase
            year = parts[2][-2:]  # Last 2 digits of year
            option_symbol = f"{index}{year}{month}{strike}{option_type}"
            return option_symbol
            
        except Exception as e:
            pass
            return None

