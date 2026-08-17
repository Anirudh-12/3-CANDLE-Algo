
import threading
from threading import Lock,Thread
from concurrent.futures import ProcessPoolExecutor
from time import time, sleep
from datetime import datetime, timedelta
from position_manager import PositionManager
import numpy as np
import sys
import os
from Get_Instruments import InstrumentHelper
import traceback
import pandas as pd
from collections import deque
import math
from one_min_data_handler import OneMinDataHandler
#     filename='app.log',
#     level=logging.CRITICAL,
#     format='%(asctime)s - %(levelname)s - %(message)s',
#     filemode='a'
# )




class BreakoutStrategy:
    def __init__(self, api, option_handler, instrument_helper, position_manager: PositionManager, position_update_callback=None):
        self.api = api
        self.option_handler = option_handler
        self.position_manager = position_manager
        self.instrument_helper = instrument_helper
        self.position_update_callback = position_update_callback
        
        
        # self.executor = ProcessPoolExecutor(max_workers=1, initializer=worker_init)
        # self.candle_thread = threading.Thread(target=self.update_candle_loop, daemon=True)
        # self.candle_thread.start()
        
        # Token Mappings
        self.ce_strike_to_token = instrument_helper.ce_strike_to_token("NIFTY", option_handler.expiry)
        self.pe_strike_to_token = instrument_helper.pe_strike_to_token("NIFTY", option_handler.expiry)   
        self.nifty_token = option_handler.index_tokens["NIFTY"]["token"]
        self.day_first_candle: dict[str, float|int] | None = None
        self.day_second_candle: dict[str, float|int] | None = None
        self.exchange = option_handler.index_tokens["NIFTY"]["exchange"]
        self.lot_size = instrument_helper.get_lot_size("NIFTY")
        
        # --- Strategy Settings (Defaults) ---
        self.initial_quantity = 65        # First Entry Qty
        self.add_on_quantity = 65         # Scaling Add-on Qty
        self.exit_quantity = 65           # Partial Exit Qty
        self.max_lots = 900               # Max total qty
        self.entry_interval = 30          # Seconds between scale-ins
        
        self.target_x = 20                # Points for Target 1
        self.target_y = 50                # Points for Target 2
        self.target_option_premium = 160  # Premium to select strike
        
        self.oi_filter_enabled = True     # Required: Call OI < Put OI for Long (can be toggled from UI)
        self.direction_filter = "BOTH"    # LONG, SHORT, BOTH

        # --- Behaviour Toggles / Advanced Settings ---
        self.trailing_sl_active = False        # Trailing SL enabled only after first full target hit
        self.continue_after_sl = False          # If True, continue looking for entries after SL hit
        self.continue_after_target2 = True     # If True, continue after full-target (Target-2) hit
        self.continue_after_sl = False          # If True, continue looking for entries after SL hit
        self.continue_after_target2 = True     # If True, continue after full-target (Target-2) hit
        self.reentry_gap_points = 2            # Gap (in points) below partial-exit price for re-entry
        
        # --- Reentry / Accumulation Settings ---
        self.reentry_qty = 65
        self.reentry_add_qty = 65
        self.reentry_max_lots = 900
        self.accumulate_on_reentry = True
        
        # --- State Management ---
        self.is_running = False
        self.state = "IDLE" # IDLE, ACCUMULATING, PARTIAL_EXIT_DONE, STOPPED
        
        # --- Live Data ---
        self.last_2_candles: list[dict[str, float|int]] = []          # List of dicts: {high, low, close, time}
        self.last_candle_update_time = 0
        self.current_ltp = self.option_handler.index_ltp
        
        # --- Fixed Option State ---
        self.fixed_strike = None
        self.fixed_symbol = None
        self.fixed_token = None
        self.ce_stk = 0
        self.pe_stk = 0
        
        # --- Position Tracking ---
        self.current_position = None
        self.position_type = None # 'CE' or 'PE'
        self.total_quantity = 0
        self.average_entry_price = 0.0
        self.last_entry_time = 0
        self.addition_count = 0
        
        # --- Targets & Stops ---
        self.current_target_1 = 0.0
        self.current_target_2 = 0.0
        self.sl_price = 0.0               # Based on Candle Logic (Future Price)
        self.partial_exit_price = 0.0     # Future price of partial exit (for re-entry logic)
        
        # --- Continuous Accumulation State ---
        self.initial_entry_qty = 0
        self.partial_exit_done = False
        self.full_target_hit_once = False
        self.has_reentered = False
        self.reentry_reference_price = 0.0
        self.reentry_accumulated_qty = 0
        
        # --- Rolling storage for last 3 completed candles ---
        self.prev_candles: deque[dict[str, float|int]] = deque(maxlen=3)
        
        # --- Donchian Filter State ---
        self.pending_setup = None
        self.pending_direction = None
        self.pending_start_time = None
        self.entry_lock = False
        self.last_pending_log_time = 0
        self.candle: dict[str, float|int] = {"time": 0, "high": 0, "low": 0, "close": 0}
        self.candle2: dict[str, float|int] = {"time": 0, "high": 0, "low": 0, "close": 0}
        self.last_candle_time: int = 0
        self.lock = Lock()
        self.is_montioring = False
        
        # Live Candle Construction
        self.running_candle:dict[str, float|int] = {"time": 0, "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0}  # {time, open, high, low, close, volume}
        self.last_tick_minute:int = 0
        self.startup_skip_minute:int = 0 # To track the partial minute we skip

        
        # Initial data fetch for SL/Entry logic
        self.one_min_handler = OneMinDataHandler(
            api=self.api, 
            exchange=self.exchange, 
            token=self.nifty_token, 
            donchian_period=20
        )
        try:
            self._update_candles()
            self.one_min_handler.load_historical_data()
            self._update_daily_candles(self.nifty_token)
            self.last_donchian_print_time = 0 
        except Exception as e:
            pass

    def start_monitoring(self):
        """Start the strategy monitoring"""
        with self.lock:
            if self.is_running:
                pass
                return {'success': False, 'message': 'Already Running'}
            
            # Wait until 9:18 if started before that time
            current_time = datetime.now()
            target_time = current_time.replace(hour=9, minute=18, second=0, microsecond=0)
            
            if current_time < target_time:
                wait_seconds = (target_time - current_time).total_seconds()
                sleep(wait_seconds)
            
            # Ensure we have fresh candles immediately upon start
            self._update_candles()
                
            self.is_montioring = True
            self.option_handler.register_strategy_callback(self.on_tick_update)
            self._notify_position_update()
            return {'success': True}
    def start_strategy(self):
        self.is_running = True
        self.full_target_hit_once = False  # Reset reentry flag on fresh start
        self._notify_position_update()
        return {'success': True}
        
    def stop_monitoring(self):
        """Stop the strategy monitoring"""
        self.is_running = False
        self.option_handler.unregister_strategy_callback(self.on_tick_update)
        self._reset_to_idle()
        self._notify_position_update()
        return {'success': True}
    def stop_strategy(self):
        self.is_running = False
        self._notify_position_update()
        return {'success': True}
    
    def _reset_to_idle(self):
        """Reset internal state to IDLE"""
        self.state = "IDLE"
        self.entry_lock = False
        if hasattr(self, 'clear_pending'):
            self.clear_pending()
        self.current_position = None
        self.position_type = None
        self.total_quantity = 0
        self.average_entry_price = 0.0
        self.last_entry_time = 0
        self.addition_count = 0
        self.current_target_1 = 0.0
        self.current_target_2 = 0.0
        self.sl_price = 0.0
        self.sl_price = 0.0
        # Reset Fixed Option Logic? Usually yes on full stop.
        self.fixed_strike = None
        self.fixed_symbol = None
        self.fixed_token = None
        self.last_2_candles = []
        self.partial_exit_done = False
        self.full_target_hit_once = False
        self.has_reentered = False
        self.reentry_reference_price = 0.0
        self.reentry_accumulated_qty = 0
        self.trailing_sl_active = False
        
        self.initial_entry_qty = 0
        
        # Note: day_first_candle, day_second_candle, and prev_candles persist for the trading day
    
    def panic_exit(self, reason="PANIC", stop_strategy=True):
        """HARD STOP: Exit ALL open positions immediately."""
        if stop_strategy:
            self.stop_strategy()
        self._exit_full_position(reason)
        # Stop strategy after panic exit
       

    def set_settings(self, initial_qty, add_on_qty, exit_qty, max_lots, premium, target_x, target_y,
                     interval, direction_filter="BOTH",
                     continue_after_target2=None, continue_after_sl=None, reentry_gap_points=None,
                     reentry_qty=65, reentry_add_qty=65, reentry_max_lots=900, accumulate_on_reentry=True):
        """Update settings dynamically"""
        try:
            self.initial_quantity = int(initial_qty)
            self.add_on_quantity = int(add_on_qty)
            self.exit_quantity = int(exit_qty)
            self.max_lots = int(max_lots)
            self.target_option_premium = float(premium)
            self.direction_filter = direction_filter
            
            # Reentry params
            self.reentry_qty = int(reentry_qty)
            self.reentry_add_qty = int(reentry_add_qty)
            self.reentry_max_lots = int(reentry_max_lots)
            self.accumulate_on_reentry = bool(accumulate_on_reentry)

            new_target_x = float(target_x)
            new_target_y = float(target_y)

            if self.total_quantity > 0:
                # Update targets relative to change to preserve "locked" targets
                self.current_target_1 = self.current_target_1 - self.target_x + new_target_x
                self.current_target_2 = self.current_target_2 - self.target_y + new_target_y
            else:
                self.current_target_1 = 0.0
                self.current_target_2 = 0.0

            self.target_x = new_target_x
            self.target_y = new_target_y
            self.entry_interval = int(interval)

            # Optional advanced settings (preserve previous values if not provided)
            if continue_after_target2 is not None:
                self.continue_after_target2 = bool(continue_after_target2)
            
            if reentry_gap_points is not None:
                try:
                    self.reentry_gap_points = int(reentry_gap_points)
                except Exception:
                    pass
            
            self._notify_position_update()
            return {'success': True}
        except Exception as e:
            pass
            return {'success': False, 'message': str(e)}

    def add_quantity(self, quantity=None):
        """Manually adjust quantity for the current breakout position.

        Direction filter is enforced even for manual scaling. The optional
        quantity parameter is currently ignored and kept for future use.
        """
        if self.position_type == "CE" and self.direction_filter == "SHORT":
            pass
            return {'success': False, 'message': 'Direction filter disallows CE add quantity'}
        if self.position_type == "PE" and self.direction_filter == "LONG":
            pass
            return {'success': False, 'message': 'Direction filter disallows PE add quantity'}

        self.total_quantity += self.add_on_quantity
        return {'success': True}

    def is_donchian_valid(self, price, direction, quiet=False):
        upper, lower, range_ = self.one_min_handler.get_donchian_values()
        if not quiet:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] DONCHIAN INFO | Upper: {upper:.2f}, Lower: {lower:.2f}, Range: {range_:.2f}")

        if range_ == 0:
            if not quiet:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] DONCHIAN VALID | Failed: Range is 0 or insufficient candles")
            return False

        if direction == "PE":  # Short
            threshold = lower + 0.3 * range_
            is_valid = price >= threshold
            if not quiet:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] DONCHIAN VALID | SHORT | Price: {price:.2f}, Threshold(Top 70%): {threshold:.2f}, Valid: {is_valid}")
            return is_valid

        elif direction == "CE":  # Long
            threshold = lower + 0.7 * range_
            is_valid = price <= threshold
            if not quiet:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] DONCHIAN VALID | LONG | Price: {price:.2f}, Threshold(Bottom 70%): {threshold:.2f}, Valid: {is_valid}")
            return is_valid

        return False

    def handle_breakout_event(self, direction, current_price):
        if self.entry_lock:
            return
            
        if self.pending_setup:
            return

        print(f"[{datetime.now().strftime('%H:%M:%S')}] BREAK DETECTED | Direction: {direction} | Price: {current_price:.2f}")
        if self.is_donchian_valid(current_price, direction, quiet=False):
            print(f"[{datetime.now().strftime('%H:%M:%S')}] DONCHIAN VALID → EXECUTED {direction}")
            self._execute_entry(direction)
            self.entry_lock = True
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] DONCHIAN FAIL → WAITING 60s for {direction}")
            self.pending_setup = True
            self.pending_direction = direction
            self.pending_start_time = time()
            self.last_pending_log_time = time()

    def check_pending_setup(self, current_price):
        if not self.pending_setup:
            return

        current_t = time()
        elapsed = current_t - self.pending_start_time

        # Throttle spam logs (every 5 seconds)
        quiet_check = True
        if not hasattr(self, 'last_pending_log_time'):
            self.last_pending_log_time = 0
            
        if current_t - self.last_pending_log_time >= 5:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] CHECKING PENDING | Elapsed: {int(elapsed)}/60s | Price: {current_price:.2f}")
            quiet_check = False
            self.last_pending_log_time = current_t

        if self.is_donchian_valid(current_price, self.pending_direction, quiet=quiet_check):
            print(f"[{datetime.now().strftime('%H:%M:%S')}] PENDING valid! DONCHIAN VALID → EXECUTED {self.pending_direction}")
            self._execute_entry(self.pending_direction)
            self.clear_pending()
            self.entry_lock = True
        elif elapsed >= 60:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] TIMEOUT → 60s EXPIRED, SETUP RESET")
            self.clear_pending()

    def clear_pending(self):
        if self.pending_setup:
             print(f"[{datetime.now().strftime('%H:%M:%S')}] CLEAR PENDING | State reset.")
        self.pending_setup = None
        self.pending_direction = None
        self.pending_start_time = None

    # =========================================================================
    #  CORE LOGIC & TICK UPDATE
    # =========================================================================

    def _update_candles(self):
        """Fetch last 3 completed 5-min candles using NorenApi"""
        try:
            # Fetch 5-minute history to populate prev_candles and initialize state
            now = datetime.now()
            # Calculate current 5-min block start
            snapped_minute = (now.minute // 5) * 5
            current_block_start = now.replace(minute=snapped_minute, second=0, microsecond=0)
            current_block_ts = int(current_block_start.timestamp())

            end_time = now
            start_time = end_time - timedelta(minutes=60) # Fetch 1 hour for safe 5-min aggregation
            
            candles = self.api.get_time_price_series(
                exchange=self.exchange,
                token=self.nifty_token,
                starttime=start_time.timestamp(),
                endtime=end_time.timestamp(),
                interval=5 # 5-minute interval
            )
            
            if candles:
                # Reverse to get [Oldest, ..., Newest]
                candles_sorted = candles[::-1]
                
                temp_prev = []
                latest_historical_partial = None

                for c in candles_sorted:
                    t_str = c.get('time')
                    try:
                        dt = datetime.strptime(t_str, "%d-%m-%Y %H:%M:%S")
                    except:
                        try:
                             dt = datetime.strptime(t_str, "%d/%m/%Y %H:%M:%S")
                        except:
                             continue

                    c_ts = int(dt.timestamp())
                    candle_obj = {
                        "time": c_ts,
                        "open": float(c.get('into')),
                        "high": float(c.get('inth')),
                        "low": float(c.get('intl')),
                        "close": float(c.get('intc')),
                        "volume": int(c.get('intv', 0))
                    }

                    if c_ts < current_block_ts:
                        temp_prev.append(candle_obj)
                    elif c_ts == current_block_ts:
                        latest_historical_partial = candle_obj
                
                # Update prev_candles with strictly older (completed) candles
                for c in temp_prev:
                    if not self.prev_candles or c['time'] > self.prev_candles[-1]['time']:
                         self.prev_candles.append(c)
                
                if len(self.prev_candles) >= 3:
                     self.candle = self.prev_candles[-1] # Last Completed 5-min
                     self.candle2 = self.prev_candles[-2]
                     self.last_candle_time = self.candle.get('time')
                     
                # Initialize state for live aggregation
                self.last_tick_minute = current_block_ts
                if latest_historical_partial:
                    # Start building from the latest partial data in history
                    self.running_candle = latest_historical_partial
                else:
                    # Start fresh if history doesn't have the current block yet
                    base_price = self.candle['close'] if self.candle else 0
                    self.running_candle = {
                        "time": current_block_ts,
                        "open": base_price,
                        "high": base_price,
                        "low": base_price,
                        "close": base_price,
                        "volume": 0
                    }

        except Exception as e:
            pass

    # update_candle_loop removed as we use live LTT/LTP stream now.

    
    def _update_daily_candles(self, token):
        """
        Fetch candles from 09:15 to 09:18 internally
        Freeze ONLY 09:15 and 09:16 candles
        """
        try:
            now = datetime.now()
            # Define fetch window (09:15–09:18)
            start_dt = now.replace(hour=9,minute=15,second=0)
            end_dt = now.replace(hour=9,minute=18,second=0)

            candles = self.api.get_time_price_series(
                exchange=self.exchange,
                token=token,
                starttime=start_dt.timestamp(),
                endtime=end_dt.timestamp(),
                interval=1
            )

            if not candles:
                pass
                return

            for candle in candles:
                candle_dt = datetime.strptime(
                    candle['time'], "%d-%m-%Y %H:%M:%S"
                )
                candle_time = candle_dt.time()

                candle_data = {
                    'time': candle_dt.timestamp(),
                    'open': float(candle['into']),
                    'high': float(candle['inth']),
                    'low': float(candle['intl']),
                    'close': float(candle['intc']),
                    'volume': int(candle.get('intv', 0))
                }

                # Freeze 09:15 candle
                if candle_time.hour == 9 and candle_time.minute == 15:
                    if self.day_first_candle is None:
                        self.day_first_candle = candle_data.copy()

                # Freeze 09:16 candle
                elif candle_time.hour == 9 and candle_time.minute == 16:
                    if self.day_second_candle is None:
                        self.day_second_candle = candle_data.copy()
        except Exception as e:
            pass

    def on_tick_update(self, index_ltp:float, index_ltt=None, index_ap=0.0):
        """Main Strategy Loop Triggered on Tick"""
        if not index_ltp:
            return

        try:
            self.current_ltp = index_ltp
            
            # --- 1-Minute Candle Update ---
            self.one_min_handler.on_tick(datetime.now().timestamp(), index_ltp)
            
            # Periodic Donchian Print (once per minute)
            current_t = time()
            if current_t - self.last_donchian_print_time >= 60:
                u, l, r = self.one_min_handler.get_donchian_values()
                if r > 0:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] PERIODIC DONCHIAN | Upper: {u:.2f}, Lower: {l:.2f}, Range: {r:.2f}, LTP: {index_ltp:.2f}")
                self.last_donchian_print_time = current_t
            
            # --- Live 5-Minute Candle Construction ---
            try:
                ltt_dt = datetime.now()
                # Snap to the start of the current 5-minute block
                snapped_minute = (ltt_dt.minute // 5) * 5
                candle_start_time = ltt_dt.replace(minute=snapped_minute, second=0, microsecond=0)
                candle_start_ts = int(candle_start_time.timestamp())
                
                # Check for 5-minute transition
                if self.last_tick_minute and candle_start_ts > self.last_tick_minute:
                    # Previous 5-minute candle is now COMPLETE
                    if self.running_candle:
                        self.prev_candles.append(self.running_candle)
                        self.candle = self.prev_candles[-1]
                        self.candle2 = self.prev_candles[-2]
                        self.last_candle_time = self.candle['time']
                        # logger.info(f"5-MIN CANDLE COMPLETED: {self.candle}")
                    
                    # Reset Running Candle for new 5-min block
                    self.running_candle = {
                        "time": candle_start_ts,
                        "open": index_ltp,
                        "high": index_ltp,
                        "low": index_ltp,
                        "close": index_ltp,
                        "volume": 0
                    }
                
                self.last_tick_minute = candle_start_ts
                
                # Update/Create Running Candle
                if self.running_candle is None:
                    self.running_candle = {
                        "time": candle_start_ts,
                        "open": index_ltp,
                        "high": index_ltp,
                        "low": index_ltp,
                        "close": index_ltp,
                        "volume": 0 
                    }
                else:
                    # Update Existing Running Candle
                    self.running_candle["high"] = max(self.running_candle["high"], index_ltp)
                    self.running_candle["low"] = min(self.running_candle["low"], index_ltp)
                    self.running_candle["close"] = index_ltp
                    self.running_candle["time"] = candle_start_ts
            except Exception as e:
                pass
                pass
            # Initialize strikes to ATM if not set
            if (self.ce_stk == 0 or self.pe_stk == 0) and index_ltp > 0:
                step = self.instrument_helper.get_step_size("NIFTY")
                atm = int(round(index_ltp / step) * step)
                self.ce_stk = atm
                self.pe_stk = atm
            
            if not self.is_running:
                return
            
            # Continuous condition check
            if self.state == "ACCUMULATING":
                self._check_stops_and_exits(index_ltp)

            # Check Entries
            if not self.is_running:
                return
                
            self.check_pending_setup(index_ltp)
            self._check_entry_conditions(index_ltp)
            
            # Update Trailing SL whenever a position is held
            if self.position_type:
                self._update_trailing_stop_loss(self.position_type)
                    
        except Exception as e:
            pass

    # =========================================================================
    #  ENTRY LOGIC
    # =========================================================================

    def _check_entry_conditions(self, index_ltp):
        """Check Breakout with 2-point Margin + OI + Time"""
        try:
            # Get the last completed 5-min candle
            prev_candle = self.candle
            if not prev_candle or prev_candle.get('time', 0) == 0:
                return

            # Max Lots Check
            if self.total_quantity >= self.max_lots:
                return

            # Timer Check - Skip for first entry (IDLE) and first addition (addition_count == 0)
            if self.state != "IDLE":
                if self.addition_count >= 1:
                    if time() - self.last_entry_time < self.entry_interval:
                        return
            
            if self.state =="ACCUMULATING":
                # Direction filter also applies to scaling / accumulation
                if self.position_type == "CE" and self.direction_filter == "SHORT":
                    return
                if self.position_type == "PE" and self.direction_filter == "LONG":
                    return

                opt_ltp = self.option_handler.get_option_ltp(self.fixed_strike,self.position_type)
                ref_price = self.reentry_reference_price if self.full_target_hit_once and self.reentry_reference_price > 0 else self.average_entry_price

                if opt_ltp <= (ref_price - self.reentry_gap_points):
                    self._execute_entry(self.position_type)
                
                return

            # --- OI Logic ---
            ce_oi = 0
            pe_oi = 0
            if self.oi_filter_enabled:
                oi_data = self.option_handler.calculate_total_oi()
                if not oi_data:
                    return
                ce_oi = oi_data["oi_change"]["CE"]
                pe_oi = oi_data["oi_change"]["PE"]

            entry_signal = None
            
            # --- LONG (CE) ---
            # 1. Break Previous High + 2 point margin
            # 2. Call OI < Put OI (if OI filter enabled)
            if index_ltp > (prev_candle['high'] + 2.0):
                if not self.oi_filter_enabled or (pe_oi > ce_oi):
                    entry_signal = "CE"
                    # print(f"CE SIGNAL: LTP {index_ltp} > High {prev_candle['high']} + 2, OI CE: {ce_oi}, PE: {pe_oi}")
                else:
                    return
            # --- SHORT (PE) ---
            # 1. Break Previous Low - 2 point margin
            # 2. Put OI < Call OI (if OI filter enabled)
            if entry_signal is None:
                if index_ltp < (prev_candle['low'] - 2.0):
                    if not self.oi_filter_enabled or (ce_oi > pe_oi):
                        entry_signal = "PE"
                        # print(f"PE SIGNAL: LTP {index_ltp} < Low {prev_candle['low']} - 2, OI CE: {ce_oi}, PE: {pe_oi}")
                    else:
                        return

            if entry_signal:
                # --- Direction Filter Check (applies to auto entries) ---
                if self.direction_filter == "LONG" and entry_signal == "PE":
                    return
                if self.direction_filter == "SHORT" and entry_signal == "CE":
                    return
            
            if not entry_signal:
                return  # No signal

            # --- Position Congruence Check ---
            if self.state != "IDLE" and self.position_type:
                if entry_signal != self.position_type:
                    return

            # Execute Entry via Donchian Pipeline
            self.handle_breakout_event(entry_signal, index_ltp)

        except Exception as e:
            pass

        except Exception as e:
            pass

    def force_entry(self, direction):
        """Manual Force Entry - ALWAYS EXECUTES (bypasses all conditions)"""
        try:
            pass

            # --- Direction Filter Check ---
            if self.direction_filter == "LONG" and direction == "PE":
                pass
                return {'success': False, 'message': 'Direction mismatch with filter (LONG)'}
            if self.direction_filter == "SHORT" and direction == "CE":
                pass
                return {'success': False, 'message': 'Direction mismatch with filter (SHORT)'}
            
            if not self.is_montioring:
                self._update_candles()
            
            # If already has a position of opposite direction, block it? 
            # Or if it's the same direction, allow scaling.
            if self.position_type and direction != self.position_type:
                 pass
                 return {'success': False, 'message': f'Cannot force {direction} while holding {self.position_type}'}

            # Execute Entry exactly once
            self._execute_entry(direction, is_force=True)
            
            # Ensure strategy is running
            if not self.is_running:
                self.start_strategy()
            
            return {'success': True}
        except Exception as e:
            pass
            return {'success': False, 'message': str(e)}

    def _execute_entry(self, direction, is_force=False):
        """Execute Trade"""
        try:
            # 1. Option Selection
            strike = 0
            option_symbol = ""
            
            if self.fixed_symbol:
                option_symbol = self.fixed_symbol
                strike = self.fixed_strike
            else:
                # Find Best Strike
                strike = self._get_strike_near_premium(self.target_option_premium,direction)
                option_symbol = self._get_option_symbol(strike, direction)
                if not option_symbol:
                    pass
                    return
                # Fix it
                self.fixed_strike = strike
                self.fixed_symbol = option_symbol
                # logger.info(f"Selected Fixed Option: {option_symbol}")

            # 2. Quantity Determination
            qty = 0
            current_max_lots = self.max_lots

            if self.full_target_hit_once:
                # print(f"DEBUG: Reentry Mode Active. Qty={self.reentry_qty}, Add={self.reentry_add_qty}")
                # --- Reentry / Post-Target Logic ---
                current_max_lots = self.reentry_max_lots
                
                if self.total_quantity == 0:
                    # Fresh Reentry
                    qty = self.reentry_qty
                else:
                    # Accumulation during Reentry Phase
                    if not self.accumulate_on_reentry:
                        # logger.info("ACCUMULATION BLOCKED: Reentry accumulation disabled in UI.")
                        return 
                    qty = self.reentry_add_qty
            else:
                # --- Normal Logic ---
                if self.total_quantity == 0:
                    qty = self.initial_quantity
                else:
                    qty = self.add_on_quantity
            
            # Check limits
            if self.total_quantity + qty > current_max_lots:
                qty = current_max_lots - self.total_quantity
            
            if qty <= 0: return
            # logger.info(f"EXECUTING ENTRY: {option_symbol}, qty={qty}, direction={direction}, is_force={is_force}")

            # 3. Place Order
            order = self.position_manager.place_order(
                tradingsymbol=option_symbol,
                quantity=qty,
                buy_or_sell='B',
                exchange="NFO",
                product_type='M',
                price_type='MKT'
            )

            # 4. Update State & Targets
            # Assume Fill Price (Need real feedback in prod)
            # Fetch LTP of option for calculation
            # TODO: Get real fill price
            # if order.get('status') =="REJECTED":
            #     if self.total_quantity == 0:
            #         self.stop_monitoring()
            #         logger.info(f"ORDER REJECTED: {order}")
            #     else:
            #         self.max_lots = self.total_quantity
            #         eel.max_lots_update_from_backend(self.max_lots)
            #         return
            #     logger.info(f"ORDER REJECTED: {order}")
            #     return
            opt_ltp = order.get('price')
            if opt_ltp is None: opt_ltp = 0.0

            # Determine if this is the first fresh reentry after Target 2
            is_first_reentry = self.full_target_hit_once and not getattr(self, 'has_reentered', False)
            
            if is_first_reentry:
                self.has_reentered = True

            # logger.info(f"Option LTP: {opt_ltp}")
            # Recalculate Average
            old_cost = self.average_entry_price * self.total_quantity
            new_cost = opt_ltp * qty
            new_total_qty = self.total_quantity + qty
            if new_total_qty > 0:
                new_avg_price = (old_cost + new_cost) / new_total_qty
            else:
                new_avg_price = float(opt_ltp)
            
            if is_first_reentry:
                self.reentry_reference_price = float(opt_ltp)
                self.reentry_accumulated_qty = qty
            elif self.full_target_hit_once and getattr(self, 'has_reentered', False):
                old_reentry_cost = self.reentry_reference_price * self.reentry_accumulated_qty
                new_reentry_cost = float(opt_ltp) * qty
                self.reentry_accumulated_qty += qty
                if self.reentry_accumulated_qty > 0:
                    self.reentry_reference_price = (old_reentry_cost + new_reentry_cost) / self.reentry_accumulated_qty
                else:
                    self.reentry_reference_price = float(opt_ltp)
            # logger.info(f"New Average Price: {new_avg_price}")
            # Target Recalculation Rule:
            # "Recalculate targets if average entry price DECREASES"
            # "If average price increases, targets do NOT change"
            if self.total_quantity == 0:
                # First Entry
                self.initial_entry_qty = qty
                self.average_entry_price = new_avg_price
                self.current_target_1 = new_avg_price + self.target_x
                self.current_target_2 = new_avg_price + self.target_y
                self.full_target_hit_once = False # Reset if it was a new fresh entry signal
                self.addition_count = 0  # Reset addition count on fresh entry
                self._calculate_stop_loss(direction) # Calculate SL once
                # logger.info(f"First Entry: Targets Set to {self.current_target_1:.2f} / {self.current_target_2:.2f}, Qty={qty}")
            else:
                self.addition_count += 1  # Track additions after initial entry
                if new_avg_price < self.average_entry_price:
                    # logger.info(f"Avg Price Decreased ({self.average_entry_price:.2f} -> {new_avg_price:.2f}). Recalculating Targets.")
                    self.current_target_1 = new_avg_price + self.target_x
                    self.current_target_2 = new_avg_price + self.target_y
                    
                else:
                    # logger.info(f"Avg Price Increased/Same ({self.average_entry_price:.2f} -> {new_avg_price:.2f}). Keeping Targets Locked.")
                    pass
                # Always update average price
                self.average_entry_price = new_avg_price

            self.total_quantity = new_total_qty
            self.position_type = direction
            self.state = "ACCUMULATING"
            self.last_entry_time = time()
            
            if not self.current_position:
                self.current_position = {'symbol': option_symbol, 'type': direction} # Basic tracking
            
            self.current_position['quantity'] = self.total_quantity
            self._notify_position_update()
            self.partial_exit_done = False
        except Exception as e:
            pass

    def _calculate_stop_loss(self, direction):
        """
        Stop Loss Logic:
        1) If entry price is inside FIRST candle range:
        SL = max adverse level from (first candle + previous 2 candles)
        2) Else:
        SL = combined range of previous 2 candles
        3) AFTER first full target:
        Initial SL logic is disabled. Trailing SL handles everything.
        """

        try:
            if self.full_target_hit_once:
                # Initial SL calculation is disabled after first full target
                return

            entry_price = self.current_ltp
            c1 = self.day_first_candle
            prev = list(self.prev_candles)


            # Default fallback if logic fails or data is missing
            self.sl_price = entry_price-15 if direction == "CE" else entry_price+15
            
            # Check for data availability
            if c1 is None:
                pass
                return

            if len(prev) < 3:
                pass
                return

            p1, p2 = self.candle, self.candle2

            

            # RULE 1: Entry inside FIRST candle (removed)

            # RULE 2: Entry outside FIRST candle
            if direction == "CE":
                self.sl_price = p1['low'] - 2.0
            else:
                self.sl_price = p1['high'] + 2.0
            
            # Print SL for verification
            print(f"[{datetime.now().strftime('%H:%M:%S')}] INITIAL SL SET: {self.sl_price:.2f} (p1 extreme +/- 2.0)")

        except Exception as e:
            pass

    def _update_trailing_sl(self, direction):
        """Update trailing SL based on previous two completed candles.

        Called on every completed candle AFTER first full target hit.
        Uses self.prev_candles (previous two completed candles only) and
        obeys the one-way SL movement rule:
        - CE: SL can only move up
        - PE: SL can only move down
        """
        try:
            if not self.candle:
                return

            p1 = self.candle 
            updated = False
            
            if direction == "CE":
                new_sl = p1['low'] - 2.0
                if self.sl_price == 0.0 or new_sl > self.sl_price:
                    self.sl_price = new_sl
                    updated = True
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] SL TRAILED UP | Candle Low: {p1['low']:.2f} | New SL: {self.sl_price:.2f} (2pt Margin)")
            else:
                new_sl = p1['high'] + 2.0
                if self.sl_price == 0.0 or new_sl < self.sl_price:
                    self.sl_price = new_sl
                    updated = True
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] SL TRAILED DOWN | Candle High: {p1['high']:.2f} | New SL: {self.sl_price:.2f} (2pt Margin)")
            
            if updated:
                self._notify_position_update()

        except Exception as e:
            pass

    def _update_trailing_stop_loss(self, direction):
        """Backwards-compatible wrapper for existing callers."""
        self._update_trailing_sl(direction)


    # =========================================================================
    #  EXIT LOGIC
    # =========================================================================

    def _check_stops_and_exits(self, index_ltp):
        if not self.current_position or self.total_quantity == 0: return

        try:

            # 2. SL Hit (Future Price)
            sl_hit = False
            if self.position_type == "CE":
                if index_ltp <= self.sl_price:
                    sl_hit = True
            else:
                if index_ltp >= self.sl_price:
                    sl_hit = True

            if sl_hit:
                with self.lock:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] SL HIT → resetting system")
                    self.panic_exit("SL Hit", stop_strategy=False)
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] STATE → IDLE")
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] scanning resumed")
                return

            # 3. Targets (Option Price)
            # Need Option LTP
            if not self.fixed_symbol: return
            
            opt_ltp = self.option_handler.get_option_ltp(self.fixed_strike,self.position_type)
            # logger.info(f"Option LTP: {opt_ltp}")
            # logger.info(f"Current Target 1: {self.current_target_1}")
            # logger.info(f"Current Target 2: {self.current_target_2}")
            
            # Target 2 (Full Target / Recalculation Base)
            if opt_ltp >= self.current_target_2:
                pass

                if not self.continue_after_target2:
                    with self.lock:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] TARGET 2 HIT → resetting system")
                        self.panic_exit("Target 2 Hit", stop_strategy=False)
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] STATE → IDLE")
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] scanning resumed")
                    return
                
                # Exit quantity logic
                qty_to_exit = 0
                lot = self.lot_size if self.lot_size and self.lot_size > 0 else 65
                
                if self.total_quantity > self.reentry_qty:
                    # Exit the excess quantity
                    qty_to_exit = self.total_quantity - self.reentry_qty
                else:
                    # Quantity is less than or equal to re-entry qty
                    if self.total_quantity <= lot:
                        # Minimum possible quantity: do not exit, continue as per strategy
                        qty_to_exit = 0
                    else:
                        # Exit 50% of the lots
                        qty_to_exit = math.ceil((self.total_quantity / lot) / 2) * lot

                if qty_to_exit > 0:
                    with self.lock:
                        pass
                        self.position_manager.place_order(
                            tradingsymbol=self.fixed_symbol,
                            quantity=qty_to_exit,
                            buy_or_sell='S',
                            exchange="NFO",
                            product_type='M',
                            price_type='MKT'
                        )
                        self.total_quantity -= qty_to_exit
                        if self.current_position:
                            self.current_position['quantity'] = self.total_quantity
                
                # Record state and enable trailing SL from this point onward
                self.full_target_hit_once = True
                self.has_reentered = False
                self.reentry_reference_price = float(opt_ltp)
                self.reentry_accumulated_qty = 0
                self.addition_count = 0


                # Recalculate targets using Option LTP as new base
                self.current_target_1 = opt_ltp + self.target_x
                self.current_target_2 = opt_ltp + self.target_y
                # self.state = "RUNNING"
                # Reset partial exit for new targets
                self.partial_exit_done = False
                
                self._notify_position_update()
                return
            
            # Target 1 (Partial Exit)
            if not self.partial_exit_done and opt_ltp >= self.current_target_1:
                with self.lock:
                    self._execute_partial_exit()

        except Exception as e:
             pass

    def _execute_partial_exit(self, quantity=None):
        try:
            # If explicit quantity is provided (from UI), use it,
            # otherwise fall back to the default "half position rounded to lot" logic
            if quantity is None:
                # Use self.lot_size instead of hardcoded 65
                lot = self.lot_size if self.lot_size and self.lot_size > 0 else 65
                if self.total_quantity <= lot:
                    self.partial_exit_done = True
                    return
                qty_to_exit = math.ceil((self.total_quantity / lot)/2) * lot
            else:
                qty_to_exit = int(quantity)

            if qty_to_exit >= self.total_quantity:
                self.panic_exit("Partial Exit")
                return
                # qty_to_exit = self.total_quantity # Full exit really
            
            if qty_to_exit <= 0: return

            order = self.position_manager.place_order(
                tradingsymbol=self.fixed_symbol,
                quantity=qty_to_exit,
                buy_or_sell='S', # Sell to exit
                exchange="NFO",
                product_type='M',
                price_type='MKT'
            )
            # Store the price at which partial exit happened (if available)
            if isinstance(order, dict):
                self.partial_exit_price = order.get("price", self.partial_exit_price)
            
            self.total_quantity -= qty_to_exit
            self.partial_exit_done = True
            # self.state = "PARTIAL_EXIT_DONE"
            if self.current_position:
                self.current_position['quantity'] = self.total_quantity
            
            if self.total_quantity == 0:
                self._reset_to_idle()

            self._notify_position_update()

        except Exception as e:
            pass

    def _exit_full_position(self, reason):
        try:
            if self.total_quantity > 0 and self.fixed_symbol:
                 pass
                 self.position_manager.place_order(
                    tradingsymbol=self.fixed_symbol,
                    quantity=self.total_quantity,
                    buy_or_sell='S',
                    exchange="NFO",
                    product_type='M',
                    price_type='MKT'
                )
            self._reset_to_idle()
            # self.state = "STOPPED"  # Automatically IDLE now from _reset_to_idle
            self._notify_position_update()
        except Exception as e:
            pass
    
    def _find_best_strike(self, direction):
        # ... logic to find strike closest to target_option_premium ...
        # Simplified reuse of old logic
        try:
             chain = self.option_handler.get_option_chain()
             if not chain: return 0, None
             target = self.target_option_premium
             best_diff = 99999
             best_strk = 0
             best_sym = None
             
             for item in chain.get('strikes', []):
                 strk = item['strike']
                 sym = self.option_handler.get_option_symbol(strk, direction)
                 if not sym: continue
                 
                 # Hack: Approximate price or fetch
                 # Ideally use efficient lookup
                 q = self.api.get_quotes("NFO", self.instrument_helper.get_token(sym))
                 ltp = float(q.get('lp', 0)) if q else 0
                 
                 if abs(ltp - target) < best_diff:
                     best_diff = abs(ltp - target)
                     best_strk = strk
                     best_sym = sym
             return best_strk, best_sym
        except:
             return 0, None
    
    def _get_strike_near_premium(self, target_premium, option_type):
        """Get strike closest to premium"""
        try:
            if not hasattr(self.option_handler, 'option_chain_cache'):
                return None
            options = {}
            for token, info in self.option_handler.option_chain_cache.items():
                if info.get('type') == option_type:
                    strike = info.get('strike')
                    ltp = float(info.get('ltp', 0))
                    if strike and ltp > 0:
                        options[strike] = ltp
            if not options:
                return None
            return min(options.keys(), key=lambda s: abs(options[s] - target_premium))
        except Exception:
            return None

    def _get_option_symbol(self, strike, option_type):
        """Get symbol from handler"""
        return self.option_handler.get_option_symbol(strike, option_type)
    
    

    def _notify_position_update(self):
        if self.position_update_callback:
            has_position = self.total_quantity > 0 and self.fixed_symbol is not None
            data = {
                'is_running': self.is_running,
                'state': self.state,
                'total_qty': self.total_quantity,
                'avg_price': self.average_entry_price,
                'target1': self.current_target_1,
                'target2': self.current_target_2,  # Show T2
                'sl': self.sl_price,               # Show Future SL
                'ltp': self.current_ltp,
                'oi_filter_enabled': self.oi_filter_enabled,
                'direction_filter': self.direction_filter,
                'continue_after_sl': self.continue_after_sl,
                'continue_after_target2': self.continue_after_target2,
                'reentry_gap_points': self.reentry_gap_points,
                'trailing_sl_active': self.trailing_sl_active,
                'has_position': has_position
            }
            self.position_update_callback(data)

    def toggle_oi_filter(self, enabled):
        self.oi_filter_enabled = enabled
        self._notify_position_update()
        return {'success': True}

    def partial_exit(self, quantity=None):
        """
        Public partial exit entry point.
        - If quantity is provided (from UI), that quantity will be exited.
        - If quantity is None, default strategy-defined partial-exit logic is used.
        """
        self._execute_partial_exit(quantity)
        return {'success': True}

    def partial_exit_percent(self, percent):
        """
        Public partial exit by percentage.
        Calculation: qty = math.ceil((total_qty / lot_size) * (percent / 100)) * lot_size
        """
        with self.lock:
            if self.total_quantity <= 0:
                return {'success': False, 'message': 'No position to exit'}
            
            qty = math.ceil((self.total_quantity / self.lot_size) * (percent / 100)) * self.lot_size
            if qty <= 0:
                return {'success': False, 'message': 'Calculated quantity is zero'}
                
            self._execute_partial_exit(qty)
        return {'success': True}

    def modify_stop_loss(self, sl):
        self.sl_price = sl
        self._notify_position_update()
        return {'success': True}
