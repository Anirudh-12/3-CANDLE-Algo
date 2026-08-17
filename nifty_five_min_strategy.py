import threading
from threading import Lock
from datetime import datetime, time as dtime
from collections import deque
import os

def log_debug(msg):
    try:
        with open("exe_debug_log.txt", "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass

class NiftyFiveMinStrategy:
    def __init__(self, api, option_handler, instrument_helper, position_manager, bridge, notify_func=None):
        log_debug("NiftyFiveMinStrategy initialized!")
        self.api = api
        self.option_handler = option_handler
        self.instrument_helper = instrument_helper
        self.position_manager = position_manager
        self.bridge = bridge
        self.notify_func = notify_func
        self.lock = Lock()

        # --- Config (set via start_nifty_strategy) ---
        self.trig_min = 25
        self.trig_max = 45
        self.break_buffer = 2.0
        self.trail_points = 12.0
        self.t1_pct = 0.5
        self.t2_pct = 1.0
        self.t3_mult = 2
        self.pm_limit = 100
        self.initial_qty = 25
        self.t1_qty = 25
        self.start_time_str = "09:35"
        self.stop_time_str = "10:45"
        self.t2_qty = 0
        self.strike_ce = 0
        self.strike_pe = 0
        self.direction = "CE"
        self.direction_filter = "BOTH"  # BOTH | LONG | SHORT

        # --- State ---
        self.state = "IDLE"
        self.is_running = False
        self.premarket_ok = False
        self.premarket_checked = False
        self.startup_validation_done = True

        # --- Day tracking ---
        self.prev_day_close = 0.0
        self.day_high = 0.0
        self.day_low = float('inf')
        self.day_initialized = False

        # --- Futures candles ---
        self.futures_candles = []
        self.running_fut_candle = None
        self.last_fut_candle_ts = 0

        # --- Option candles (keyed by open_time ts) ---
        self.option_candles = {"CE": {}, "PE": {}}
        self.running_opt_candle = {"CE": None, "PE": None}
        self.last_opt_candle_ts = {"CE": 0, "PE": 0}
        self.opt_ltp = 0.0
        self.index_ltp = 0.0

        # --- 3-Candle Bin State ---
        self.candle_bin = []              # Rolling bin of last 3 closed candles (>= 9:25 only)
        self.long_setup_armed = False
        self.short_setup_armed = False
        self.long_trigger_candle = None   # 3rd candle in bin when long setup is armed
        self.short_trigger_candle = None  # 3rd candle in bin when short setup is armed
        self.trigger_candle = None        # The trigger candle used for the active trade

        # --- Safety Mechanism State ---
        self.safety_state = None          # None | "WAIT_CANDLE_CLOSE"
        self.safety_wait_candle_ts = 0    # Timestamp of candle during which SL was hit
        self.sl_hit_index_price = 0.0     # Index (futures) price at the moment SL was hit
        self.last_failed_direction = None  # "CE" or "PE" — direction of the last failed trade

        # --- Trade / Position tracking
        self.direction = None
        self.entry_price_opt = 0.0
        self.opt_candle_size = 0.0
        self.option_high_since_entry = 0.0  # Tracks highest option price since entry (for continuous SL trailing)
        self.t1_target = 0.0
        self.t2_target = 0.0
        self.t3_target = 0.0
        self.current_sl = 0.0
        self.trailing_sl = 0.0
        self.t1_hit = False
        self.t2_hit = False
        self.remaining_qty = 0

        # --- Option subscription ---
        self.active_opt_strike = 0
        self.active_opt_type = "CE"
        self.active_trade_candles = {}
        self.running_active_trade_candle = None
        self.last_active_trade_candle_ts = 0

    def _parse_time(self, time_str):
        try:
            parts = time_str.split(":")
            if len(parts) == 2:
                return dtime(int(parts[0]), int(parts[1]))
        except Exception:
            pass
        return None

    def _notify_user_message(self, message, title="Nifty Strategy"):
        if self.bridge:
            try:
                self.bridge.notify("showNotification", {"title": title, "message": message})
            except Exception as e:
                pass

    # =========================================================================
    # CONFIGURE & START/STOP
    # =========================================================================

    def configure(self, initial_qty, t1_qty, t2_qty, strike_ce, strike_pe,
                  trig_min, trig_max, break_buffer, t1_pct, t2_pct, t3_mult,
                  direction_filter="BOTH", pm_limit=100, start_time="09:35", stop_time="10:45", trail_points=12.0):
        self.initial_qty = int(initial_qty)
        self.t1_qty = int(t1_qty)
        self.t2_qty = int(t2_qty)
        self.start_time_str = str(start_time)
        self.stop_time_str = str(stop_time)
        self.trail_points = float(trail_points)
        
        new_strike_ce = int(strike_ce) if strike_ce else 0
        self.strike_ce = new_strike_ce
        
        new_strike_pe = int(strike_pe) if strike_pe else 0
        self.strike_pe = new_strike_pe
        self.direction_filter = str(direction_filter).upper() if direction_filter else "BOTH"
        self.trig_min = int(trig_min)
        self.trig_max = int(trig_max)
        self.break_buffer = float(break_buffer)
        self.t1_pct = float(t1_pct)
        self.t2_pct = float(t2_pct)
        self.t3_mult = int(t3_mult)
        self.pm_limit = int(pm_limit)
        
        # If strike changed, ALWAYS fetch historical option candles for the new strike
        # We explicitly clear existing candles to pause trading until new option data is ready
        if self.is_running:
            strike_changed = False
            if new_strike_ce > 0 and new_strike_ce != getattr(self, '_last_configured_strike_ce', 0):
                with self.lock:
                    self.option_candles["CE"].clear()
                    self.running_opt_candle["CE"] = None
                    self.last_opt_candle_ts["CE"] = 0
                self._fetch_historical_option_candles("CE", new_strike_ce)
                strike_changed = True
            if new_strike_pe > 0 and new_strike_pe != getattr(self, '_last_configured_strike_pe', 0):
                with self.lock:
                    self.option_candles["PE"].clear()
                    self.running_opt_candle["PE"] = None
                    self.last_opt_candle_ts["PE"] = 0
                self._fetch_historical_option_candles("PE", new_strike_pe)
                strike_changed = True
            if strike_changed:
                self._notify()
                
        self._last_configured_strike_ce = new_strike_ce
        self._last_configured_strike_pe = new_strike_pe
        
        # Dynamically update targets if we are currently in a trade
        if self.state in ("IN_TRADE", "TRAILING"):
            ep = self.entry_price_opt
            cs = self.opt_candle_size if self.opt_candle_size > 0 else ep * 0.1
            self.t1_target = ep + cs * self.t1_pct
            self.t2_target = ep + cs * self.t2_pct
            self.t3_target = ep + cs * self.t3_mult
            # Pre-T1 SL is option_high - candle_size, not affected by config params

    def start(self):
        should_notify_idle = False
        msg = ""
        with self.lock:
            if self.is_running:
                return
            self.is_running = True
            
            # Clear bin and safety state for fresh start
            self.candle_bin = []
            self.long_setup_armed = False
            self.short_setup_armed = False
            self.long_trigger_candle = None
            self.short_trigger_candle = None
            self.startup_validation_done = False
            self._clear_safety_state()
            self.pending_option_breakout = None
            self.premarket_ok = False
            self.premarket_checked = False
            self.futures_candles = []
            self.running_fut_candle = None
            self.last_fut_candle_ts = 0
            self.day_initialized = False
            self.prev_day_close = 0.0
            self.day_high = 0.0
            self.day_low = float('inf')
            # Check time limits to set initial state
            now_time = datetime.now().time()
            start_t = self._parse_time(self.start_time_str) or dtime(9, 35)
            stop_t = self._parse_time(self.stop_time_str) or dtime(10, 45)
            
            if now_time < start_t:
                self.state = "WAITING_TIME"
                print(f"[TIME] Current time {now_time.strftime('%H:%M:%S')} is before start time {self.start_time_str}. Waiting...")
            elif now_time >= stop_t:
                self.state = "IDLE"
                self.is_running = False
                msg = f"Cannot start strategy: Current time is after the stop time {self.stop_time_str}."
                print(f"[TIME] {msg}")
                should_notify_idle = True
            else:
                self.state = "SCANNING"
                
            if not should_notify_idle:
                self._fetch_prev_close()
                self._fetch_and_replay_historical_candles()
                self.option_handler.register_strategy_callback(self._on_tick)
        
        if should_notify_idle:
            self._notify_user_message(msg)
            self._notify()
        else:
            self._notify()

    def stop(self):
        with self.lock:
            self.is_running = False
            self._panic_exit_internal()
            self.state = "IDLE"
            self._reset_trade_state()
            self._clear_safety_state()
            self.candle_bin = []
            self.long_setup_armed = False
            self.short_setup_armed = False
            self.long_trigger_candle = None
            self.short_trigger_candle = None
            self.pending_option_breakout = None
        try:
            self.option_handler.unregister_strategy_callback(self._on_tick)
        except Exception:
            pass
        self._notify()

    def panic_exit(self):
        with self.lock:
            self._panic_exit_internal()
            self.state = "IDLE"
            self._reset_trade_state()
            self._clear_safety_state()
        self._notify()

    def force_entry(self, direction):
        with self.lock:
            if direction == "CE":
                tc = self.long_trigger_candle
            else:
                tc = self.short_trigger_candle
            if tc is None and self.trigger_candle:
                tc = self.trigger_candle
            if tc is None and self.futures_candles:
                tc = self.futures_candles[-1]
            self._enter_trade(direction, tc or {}, force=True)

    # =========================================================================
    # TICK HANDLER
    # =========================================================================

    def _on_tick(self, index_ltp, index_ltt=None, index_ap=0.0):
        if not self.is_running or not index_ltp:
            return
        try:
            now = datetime.now()
            ltp = float(index_ltp)
            self.index_ltp = ltp

            if not getattr(self, 'startup_validation_done', True):
                self.startup_validation_done = True
                
                # LONG setup validation
                if self.long_setup_armed and self.long_trigger_candle:
                    opt_tc_high = self._get_option_trigger_candle_high("CE", self.long_trigger_candle)
                    ce_ltp = self.option_handler.get_option_ltp(self.strike_ce, "CE") if self.strike_ce > 0 else 0
                    if ltp > self.long_trigger_candle['high'] or (opt_tc_high is not None and ce_ltp > opt_tc_high):
                        print(f"[STARTUP] LONG setup invalidated: price already above trigger.")
                        self.long_setup_armed = False
                        self.long_trigger_candle = None

                # SHORT setup validation
                if self.short_setup_armed and self.short_trigger_candle:
                    opt_tc_high = self._get_option_trigger_candle_high("PE", self.short_trigger_candle)
                    pe_ltp = self.option_handler.get_option_ltp(self.strike_pe, "PE") if self.strike_pe > 0 else 0
                    if ltp < self.short_trigger_candle['low'] or (opt_tc_high is not None and pe_ltp > opt_tc_high):
                        print(f"[STARTUP] SHORT setup invalidated: price already below trigger.")
                        self.short_setup_armed = False
                        self.short_trigger_candle = None

            self._update_day_range(ltp)
            
            self._update_fut_candle(ltp, now)
            self._check_premarket(ltp, now)
            
            # Check time limits and handle transitions
            if self._check_time_limits_on_tick(now):
                return
            
            # Continuously update BOTH option candles so history is ready when breakout happens
            try:
                if self.strike_ce > 0:
                    ce_ltp = self.option_handler.get_option_ltp(self.strike_ce, "CE")
                    if ce_ltp > 0:
                        self._update_opt_candle(ce_ltp, now, "CE")
                if self.strike_pe > 0:
                    pe_ltp = self.option_handler.get_option_ltp(self.strike_pe, "PE")
                    if pe_ltp > 0:
                        self._update_opt_candle(pe_ltp, now, "PE")
                # Update current active opt_ltp and trade candle if in trade
                if self.state in ("IN_TRADE", "TRAILING"):
                    trade_ltp = self.option_handler.get_option_ltp(self.active_opt_strike, self.active_opt_type)
                    if trade_ltp > 0:
                        self._update_active_trade_candle(trade_ltp, now)
                        # Track option high and continuously trail SL (pre-T1)
                        if trade_ltp > self.option_high_since_entry:
                            self.option_high_since_entry = trade_ltp
                        if not self.t1_hit:
                            proposed_sl = self.option_high_since_entry - self.opt_candle_size
                            if proposed_sl != self.current_sl:
                                self.current_sl = proposed_sl
                    self.opt_ltp = trade_ltp
                else:
                    self.opt_ltp = self.option_handler.get_option_ltp(self.active_opt_strike, self.active_opt_type)
            except Exception:
                pass

            if self.state not in ("PREMARKET_FAIL", "IDLE"):
                self._check_breakout(ltp, now)
                self._check_trade(ltp, now)
            self._notify()
        except Exception:
            pass


    def _check_time_limits_on_tick(self, now):
        start_t = self._parse_time(self.start_time_str) or dtime(9, 35)
        stop_t = self._parse_time(self.stop_time_str) or dtime(10, 45)
        now_time = now.time()

        if now_time < start_t:
            if self.state != "WAITING_TIME":
                print(f"[TIME] Current time {now_time.strftime('%H:%M:%S')} is before start time {self.start_time_str}. Waiting...")
                self.state = "WAITING_TIME"
                self._notify()
            return True

        if self.state == "WAITING_TIME" and now_time >= start_t and now_time < stop_t:
            print(f"[TIME] Start time {self.start_time_str} reached. Transitioning to SCANNING.")
            self.state = "SCANNING"
            self._notify()
            msg = f"Nifty Strategy started scanning at {now_time.strftime('%H:%M:%S')} (Start time: {self.start_time_str})."
            self._notify_user_message(msg)

        if now_time >= stop_t:
            has_position = self.remaining_qty > 0 and self.state in ("IN_TRADE", "TRAILING")
            if not has_position:
                print(f"[TIME] Stop time {self.stop_time_str} reached. Stopping strategy.")
                self.stop()
                msg = f"Nifty Strategy stopped at {now_time.strftime('%H:%M:%S')} as stop time {self.stop_time_str} was reached and no active positions exist."
                self._notify_user_message(msg)
                return True
        return False

    # =========================================================================
    # DAY RANGE
    # =========================================================================

    def _fetch_prev_close(self):
        try:
            nifty_token = self.option_handler.index_tokens.get("NIFTY", {}).get("token")
            exchange = self.option_handler.index_tokens.get("NIFTY", {}).get("exchange", "NFO")
            if not nifty_token:
                return
            quotes = self.api.get_quotes(exchange, nifty_token)
            if quotes:
                # Shoonya/Noren API: 'c' = previous day close, 'lp' = current LTP
                prev_close = quotes.get('c') or quotes.get('pc') or quotes.get('lp', 0)
                self.prev_day_close = float(prev_close or 0)
                
                current_lp = float(quotes.get('lp', 0) or 0)
                if current_lp > 0 and self.index_ltp == 0.0:
                    self.index_ltp = current_lp
                    
                # Seed day high/low from quotes so range is correct even if started mid-day
                day_high = float(quotes.get('h', 0) or 0)
                day_low = float(quotes.get('l', 0) or 0)
                if day_high > 0 and day_low > 0:
                    self.day_high = day_high
                    self.day_low = day_low
                    self.day_initialized = True
        except Exception:
            pass

    def _fetch_and_replay_historical_candles(self):
        """Fetch today's completed 5-min candles and replay through bin scanner.

        Allows the strategy to build the correct bin state even if started
        late, so setups formed before startup are detected.
        """
        try:
            nifty_token = self.option_handler.index_tokens.get("NIFTY", {}).get("token")
            exchange    = self.option_handler.index_tokens.get("NIFTY", {}).get("exchange", "NFO")
            if not nifty_token:
                return

            now = datetime.now()
            start_dt = now.replace(hour=9, minute=15, second=0, microsecond=0)
            snapped_minute  = (now.minute // 5) * 5
            current_block_ts = int(now.replace(minute=snapped_minute, second=0, microsecond=0).timestamp())

            raw = self.api.get_time_price_series(
                exchange=exchange,
                token=nifty_token,
                starttime=start_dt.timestamp(),
                endtime=now.timestamp(),
                interval=5
            )
            if not raw:
                return

            # API returns newest-first → reverse for chronological replay
            raw_sorted = raw[::-1]

            for c in raw_sorted:
                t_str = c.get('time', '')
                try:
                    dt = datetime.strptime(t_str, "%d-%m-%Y %H:%M:%S")
                except Exception:
                    try:
                        dt = datetime.strptime(t_str, "%d/%m/%Y %H:%M:%S")
                    except Exception:
                        continue

                c_ts = int(dt.timestamp())
                if c_ts >= current_block_ts:
                    continue  # Skip the still-forming (partial) current candle

                hi  = float(c.get('inth', 0) or 0)
                lo  = float(c.get('intl', 0) or 0)
                cl  = float(c.get('intc', 0) or 0)

                candle_obj = {
                    "time":  c_ts,
                    "open":  float(c.get('into', 0) or 0),
                    "high":  hi,
                    "low":   lo,
                    "close": cl,
                    "size":  hi - lo,
                }

                self.futures_candles.append(candle_obj)

                # Add to bin (filters for >= 9:25 internally)
                self._add_to_bin(candle_obj)

            # Evaluate premarket gate from replayed data if not yet checked
            if not self.premarket_checked:
                move = 0
                day_range = 0
                if self.prev_day_close > 0:
                    app_high, app_low = self._get_applicable_high_low(now)
                    if app_high is not None and app_low is not None:
                        move = max(abs(app_high - self.prev_day_close), abs(app_low - self.prev_day_close))
                        day_range = app_high - app_low
                        if move >= self.pm_limit or day_range >= self.pm_limit:
                            self.premarket_ok = True
                if now.time() >= dtime(9, 45):
                    self.premarket_checked = True
                    if not self.premarket_ok:
                        self.state = "PREMARKET_FAIL"

            log_debug(f"[API_DEBUG] Reached end of futures fetch. self.strike_ce={self.strike_ce}, self.strike_pe={self.strike_pe}")
            # Fetch historical option candles for current strikes
            if self.strike_ce > 0:
                self._fetch_historical_option_candles("CE", self.strike_ce)
            if self.strike_pe > 0:
                self._fetch_historical_option_candles("PE", self.strike_pe)

        except Exception as e:
            log_debug(f"[API_DEBUG] Exception in _fetch_historical_futures_candles: {e}")
            import traceback
            log_debug(traceback.format_exc())

    def _fetch_historical_option_candles(self, opt_type, strike):
        if strike <= 0:
            return
        token_info = self.option_handler._get_option_token("NIFTY", opt_type, strike)
        if not token_info:
            log_debug(f"[API_DEBUG] token_info is None for NIFTY {opt_type} {strike}")
            return
            
        exchange = token_info.get("exchange", "NFO")
        token = token_info.get("token")
        if not token:
            log_debug(f"[API_DEBUG] token is empty in token_info: {token_info}")
            return
            
        def fetch_task():
            import time
            time.sleep(0.5) # Wait a bit to ensure subscriptions settle
            try:
                now = datetime.now()
                start_dt = now.replace(hour=9, minute=15, second=0, microsecond=0)
                snapped_minute = (now.minute // 5) * 5
                current_block_ts = int(now.replace(minute=snapped_minute, second=0, microsecond=0).timestamp())

                raw = self.api.get_time_price_series(
                    exchange=exchange,
                    token=token,
                    starttime=start_dt.timestamp(),
                    endtime=now.timestamp(),
                    interval=5
                )
                if not raw:
                    log_debug(f"[API_DEBUG] raw is None! exchange={exchange}, token={token}, start={start_dt}, end={now}")
                    return

                raw_sorted = raw[::-1]
                valid_candles = []

                for c in raw_sorted:
                    t_str = c.get('time', '')
                    try:
                        dt = datetime.strptime(t_str, "%d-%m-%Y %H:%M:%S")
                    except Exception as e1:
                        try:
                            dt = datetime.strptime(t_str, "%d/%m/%Y %H:%M:%S")
                        except Exception as e2:
                            log_debug(f"[API_DEBUG] Date parsing failed for {t_str}: {e1} | {e2}")
                            continue

                    c_ts = int(dt.timestamp())
                    if c_ts >= current_block_ts:
                        continue  # Skip partial current candle

                    hi  = float(c.get('inth', 0) or 0)
                    lo  = float(c.get('intl', 0) or 0)
                    cl  = float(c.get('intc', 0) or 0)

                    valid_candles.append((c_ts, {
                        "time":  c_ts,
                        "open":  float(c.get('into', 0) or 0),
                        "high":  hi,
                        "low":   lo,
                        "close": cl,
                        "size":  hi - lo,
                    }))

                # Only keep the last 5 option candles
                valid_candles = valid_candles[-5:]
                new_candles = dict(valid_candles)

                with self.lock:
                    # Ensure the strike we fetched is STILL the currently configured strike
                    # Otherwise, discard this data (another thread is handling the newer strike)
                    current_strike = self.strike_ce if opt_type == "CE" else self.strike_pe
                    if strike != current_strike:
                        log_debug(f"[API] Discarding fetched historical candles for {opt_type} {strike} because current strike is {current_strike}")
                        return
                    
                    self.option_candles[opt_type].clear()
                    self.option_candles[opt_type].update(new_candles)
                self._notify()
                log_debug(f"[API] Fetched {len(new_candles)} historical option candles for {opt_type} {strike}")

            except Exception as e:
                log_debug(f"Error fetching historical options candles for {opt_type} {strike}: {e}")

        try:
            import threading
            threading.Thread(target=fetch_task, daemon=True).start()
        except Exception as e:
            log_debug(f"[API_DEBUG] Thread creation failed for {opt_type} {strike}: {e}")

    def _update_day_range(self, ltp):
        if not self.day_initialized:
            # Fallback: init from first tick if quotes didn't provide h/l
            self.day_high = ltp
            self.day_low = ltp
            self.day_initialized = True
        if self.day_initialized:
            if ltp > self.day_high:
                self.day_high = ltp
            if ltp < self.day_low:
                self.day_low = ltp


    # =========================================================================
    # CANDLE BUILDERS
    # =========================================================================

    def _async_replace_candle(self, exchange, token, target_ts, candle_dict, label="futures"):
        """Fetches official API candle asynchronously and updates local tick-built dictionary in-place."""
        if not token or not exchange:
            return
            
        def fetch_task():
            import time
            max_retries = 8
            for attempt in range(max_retries):
                time.sleep(0.2)  # poll delay
                try:
                    now = datetime.now()
                    raw = self.api.get_time_price_series(
                        exchange=exchange,
                        token=token,
                        starttime=target_ts,
                        endtime=now.timestamp(),
                        interval=5
                    )
                    if not raw:
                        continue
                    
                    # Search for target_ts
                    found = False
                    for c in raw:
                        t_str = c.get('time', '')
                        try:
                            dt = datetime.strptime(t_str, "%d-%m-%Y %H:%M:%S")
                        except Exception:
                            try:
                                dt = datetime.strptime(t_str, "%d/%m/%Y %H:%M:%S")
                            except Exception:
                                continue
                        
                        c_ts = int(dt.timestamp())
                        if c_ts == target_ts:
                            hi  = float(c.get('inth', 0) or 0)
                            lo  = float(c.get('intl', 0) or 0)
                            cl  = float(c.get('intc', 0) or 0)
                            op  = float(c.get('into', 0) or 0)
                            
                            with self.lock:
                                candle_dict["open"] = op
                                candle_dict["high"] = hi
                                candle_dict["low"] = lo
                                candle_dict["close"] = cl
                                candle_dict["size"] = hi - lo
                                
                                if label == "CE Option":
                                    self.option_candles["CE"][target_ts] = candle_dict
                                elif label == "PE Option":
                                    self.option_candles["PE"][target_ts] = candle_dict
                            print(f"[API_OVERRIDE] Successfully updated {label} candle {target_ts} for {token} after {attempt + 1} polls")
                            # NOTE: Do NOT call _evaluate_bin() here.
                            # The bin was already evaluated at candle-close time using the tick-built data.
                            # Re-evaluating with API-corrected data can cause stale setups to arm
                            # *after* the candle closed, leading to spurious entries on the very
                            # next tick even when conditions were not met at close time.

                            # BREAKOUT PRE-VALIDATION: After the async option candle data arrives,
                            # check if the current option LTP is ALREADY above the trigger high.
                            # If so, disarm the setup — the price was never witnessed *crossing*
                            # the threshold during live monitoring (data just arrived late and
                            # found price already there). This prevents spurious "instant entries".
                            if hi > 0:
                                if label == "CE Option":
                                    with self.lock:
                                        if (self.long_setup_armed and self.long_trigger_candle and
                                                self.long_trigger_candle.get("time", 0) == target_ts):
                                            ce_ltp = self.option_handler.get_option_ltp(self.strike_ce, "CE")
                                            if ce_ltp > 0 and ce_ltp > hi + self.break_buffer:
                                                print(f"[SETUP] LONG setup INVALIDATED on data arrival: "
                                                      f"CE LTP {ce_ltp:.2f} already > opt trigger high "
                                                      f"{hi:.2f} + buffer {self.break_buffer}. No breakout occurred.")
                                                self.long_setup_armed = False
                                                self.long_trigger_candle = None

                                elif label == "PE Option":
                                    with self.lock:
                                        if (self.short_setup_armed and self.short_trigger_candle and
                                                self.short_trigger_candle.get("time", 0) == target_ts):
                                            pe_ltp = self.option_handler.get_option_ltp(self.strike_pe, "PE")
                                            if pe_ltp > 0 and pe_ltp > hi + self.break_buffer:
                                                print(f"[SETUP] SHORT setup INVALIDATED on data arrival: "
                                                      f"PE LTP {pe_ltp:.2f} already > opt trigger high "
                                                      f"{hi:.2f} + buffer {self.break_buffer}. No breakout occurred.")
                                                self.short_setup_armed = False
                                                self.short_trigger_candle = None

                            self._notify()
                            found = True
                            break
                    
                    if found:
                        break
                except Exception as e:
                    log_debug(f"[API_OVERRIDE] Error fetching override for {token}: {e}")
                    
        try:
            import threading
            threading.Thread(target=fetch_task, daemon=True).start()
        except Exception as e:
            log_debug(f"[API_DEBUG] Thread creation failed for async replacement: {e}")

    def _snap5(self, dt):
        snapped = (dt.minute // 5) * 5
        return int(dt.replace(minute=snapped, second=0, microsecond=0).timestamp())

    def _update_fut_candle(self, ltp, now):
        ts = self._snap5(now)
        if self.running_fut_candle is None:
            self.running_fut_candle = {"time": ts, "open": ltp, "high": ltp, "low": ltp, "close": ltp, "vol": 0}
            self.last_fut_candle_ts = ts
        elif ts > self.last_fut_candle_ts:
            completed = dict(self.running_fut_candle)
            completed["size"] = completed["high"] - completed["low"]
            self.futures_candles.append(completed)
            
            # Spawn override fetch
            nifty_token = self.option_handler.index_tokens.get("NIFTY", {}).get("token")
            exchange = self.option_handler.index_tokens.get("NIFTY", {}).get("exchange", "NFO")
            if nifty_token and exchange:
                self._async_replace_candle(exchange, nifty_token, self.last_fut_candle_ts, completed, label="futures")
                
            self.running_fut_candle = {"time": ts, "open": ltp, "high": ltp, "low": ltp, "close": ltp, "vol": 0}
            self.last_fut_candle_ts = ts
            self._on_candle_close(completed, "futures")
        else:
            c = self.running_fut_candle
            c["high"] = max(c["high"], ltp)
            c["low"] = min(c["low"], ltp)
            c["close"] = ltp

    def _update_opt_candle(self, ltp, now, opt_type):
        if ltp <= 0:
            return
        ts = self._snap5(now)
        if self.running_opt_candle[opt_type] is None:
            self.running_opt_candle[opt_type] = {"time": ts, "open": ltp, "high": ltp, "low": ltp, "close": ltp}
            self.last_opt_candle_ts[opt_type] = ts
        elif ts > self.last_opt_candle_ts[opt_type]:
            completed = dict(self.running_opt_candle[opt_type])
            completed["size"] = completed["high"] - completed["low"]
            self.option_candles[opt_type][self.last_opt_candle_ts[opt_type]] = completed
            
            self.running_opt_candle[opt_type] = {"time": ts, "open": ltp, "high": ltp, "low": ltp, "close": ltp}
            self.last_opt_candle_ts[opt_type] = ts
            self._on_candle_close(completed, "option")
        else:
            c = self.running_opt_candle[opt_type]
            c["high"] = max(c["high"], ltp)
            c["low"] = min(c["low"], ltp)
            c["close"] = ltp

    def _update_active_trade_candle(self, ltp, now):
        ts = self._snap5(now)
        if self.running_active_trade_candle is None:
            self.running_active_trade_candle = {"time": ts, "open": ltp, "high": ltp, "low": ltp, "close": ltp}
            self.last_active_trade_candle_ts = ts
        elif ts > self.last_active_trade_candle_ts:
            completed = dict(self.running_active_trade_candle)
            completed["size"] = completed["high"] - completed["low"]
            self.active_trade_candles[self.last_active_trade_candle_ts] = completed
            
            # Spawn override fetch
            if self.active_opt_strike > 0 and self.active_opt_type:
                token_info = self.option_handler._get_option_token("NIFTY", self.active_opt_type, self.active_opt_strike)
                if token_info:
                    self._async_replace_candle(token_info.get("exchange", "NFO"), token_info.get("token"), self.last_active_trade_candle_ts, completed, label=f"{self.active_opt_type} Option")
                    
            self.running_active_trade_candle = {"time": ts, "open": ltp, "high": ltp, "low": ltp, "close": ltp}
            self.last_active_trade_candle_ts = ts
        else:
            c = self.running_active_trade_candle
            c["high"] = max(c["high"], ltp)
            c["low"] = min(c["low"], ltp)
            c["close"] = ltp

    # =========================================================================
    # PRE-MARKET CHECK
    # =========================================================================

    def _get_applicable_high_low(self, now):
        t = now.time()
        start_t = self._parse_time(self.start_time_str) or dtime(9, 35)
        if t < start_t:
            if self.day_initialized:
                return self.day_high, self.day_low
            return None, None
        else:
            highs = []
            lows = []
            for c in self.futures_candles:
                try:
                    ct = datetime.fromtimestamp(c["time"]).time()
                    if dtime(9, 15) <= ct < start_t:
                        highs.append(c["high"])
                        lows.append(c["low"])
                except Exception:
                    pass
            if self.running_fut_candle:
                try:
                    ct = datetime.fromtimestamp(self.running_fut_candle["time"]).time()
                    if dtime(9, 15) <= ct < start_t:
                        highs.append(self.running_fut_candle["high"])
                        lows.append(self.running_fut_candle["low"])
                except Exception:
                    pass

            if highs and lows:
                return max(highs), min(lows)
            if self.day_initialized:
                return self.day_high, self.day_low
            return None, None

    def _check_premarket(self, ltp, now):
        if self.premarket_checked:
            return
        # Evaluate conditions first (regardless of time)
        move = 0
        day_range = 0
        if self.prev_day_close > 0:
            app_high, app_low = self._get_applicable_high_low(now)
            if app_high is not None and app_low is not None:
                move = max(abs(app_high - self.prev_day_close), abs(app_low - self.prev_day_close))
                day_range = app_high - app_low
                if move >= self.pm_limit or day_range >= self.pm_limit:
                    self.premarket_ok = True

        # Then enforce the 9:45 deadline
        t = now.time()
        if t >= dtime(9, 45):
            print(f"[PREMARKET] 9:45 reached. Move: {move:.2f} (Limit: {self.pm_limit}), Range: {day_range:.2f} (Limit: {self.pm_limit}), premarket_ok: {self.premarket_ok}")
            if not self.premarket_ok:
                if self.state not in ("IN_TRADE", "TRAILING"):
                    print(f"[PREMARKET] Changing state to PREMARKET_FAIL")
                    self.state = "PREMARKET_FAIL"
                else:
                    print(f"[PREMARKET] Skipping PREMARKET_FAIL because state is {self.state}")
            self.premarket_checked = True

    # =========================================================================
    # CANDLE CLOSE EVENT
    # =========================================================================

    def _on_candle_close(self, candle, candle_type):
        if candle_type == "futures":
            try:
                ts_str = datetime.fromtimestamp(candle["time"]).strftime('%H:%M:%S')
                print(f"\n[SCAN] --- Future Candle Closed @ {ts_str} ---")
                print(f"[SCAN] O:{candle['open']} H:{candle['high']} L:{candle['low']} C:{candle['close']} Size:{candle.get('size', 0):.2f}")
            except Exception:
                pass
            
            # Add to bin (filters for >= 9:25 internally) and evaluate setup
            self._add_to_bin(candle)
            
            # Handle safety state transitions on candle close
            self._handle_safety_on_candle_close(candle)
            
            if self.state in ("IN_TRADE", "TRAILING"):
                self._update_sl_on_candle_close()

    # =========================================================================
    # 3-CANDLE BIN LOGIC
    # =========================================================================

    def _add_to_bin(self, candle):
        """Add a candle to the rolling 3-candle bin if its timestamp is >= 9:25."""
        try:
            candle_time = datetime.fromtimestamp(candle["time"]).time()
            if candle_time < dtime(9, 25):
                return
        except Exception:
            return
        
        self.candle_bin.append(candle)
        if len(self.candle_bin) > 3:
            self.candle_bin = self.candle_bin[-3:]
        
        self._evaluate_bin()

    def _evaluate_bin(self):
        """Evaluate the current 3-candle bin for long and short setups.
        
        SHORT setup: last 2 candles don't break the LOW of the first candle. 
                     If they do break the low, their CLOSE must be at or above the CLOSE of the first candle.
                     Entry when the trigger candle's (3rd) LOW is broken.
        LONG setup:  last 2 candles don't break the HIGH of the first candle.
                     If they do break the high, their CLOSE must be at or below the CLOSE of the first candle.
                     Entry when the trigger candle's (3rd) HIGH is broken.
        Both setups can coexist. Whichever triggers first invalidates the other.
        """
        if len(self.candle_bin) < 3:
            self.long_setup_armed = False
            self.short_setup_armed = False
            self.long_trigger_candle = None
            self.short_trigger_candle = None
            return

        first, second, third = self.candle_bin[0], self.candle_bin[1], self.candle_bin[2]

        try:
            first_ts = datetime.fromtimestamp(first["time"]).strftime('%H:%M')
            third_ts = datetime.fromtimestamp(third["time"]).strftime('%H:%M')
        except Exception:
            first_ts = "???"
            third_ts = "???"

        # SHORT: last 2 candles must either not break first's LOW, OR close at/above first's CLOSE
        second_short_ok = (second["low"] >= first["low"]) or (second["close"] >= first["close"])
        third_short_ok = (third["low"] >= first["low"]) or (third["close"] >= first["close"])
        short_valid = second_short_ok and third_short_ok

        # LONG: last 2 candles must either not break first's HIGH, OR close at/below first's CLOSE
        second_long_ok = (second["high"] <= first["high"]) or (second["close"] <= first["close"])
        third_long_ok = (third["high"] <= first["high"]) or (third["close"] <= first["close"])
        long_valid = second_long_ok and third_long_ok

        # Size constraint check
        size = third["high"] - third["low"]
        size_ok = (self.trig_min <= size <= self.trig_max)
        if not size_ok:
            short_valid = False
            long_valid = False

        # Apply direction filter
        if self.direction_filter == "LONG":
            short_valid = False
        elif self.direction_filter == "SHORT":
            long_valid = False

        self.short_setup_armed = short_valid
        self.short_trigger_candle = third if short_valid else None
        self.long_setup_armed = long_valid
        self.long_trigger_candle = third if long_valid else None

        tc_time = third["time"] if third else 0
        if long_valid and self.strike_ce > 0 and tc_time > 0:
            if tc_time not in self.option_candles["CE"]:
                self.option_candles["CE"][tc_time] = {"time": tc_time, "open": 0, "high": 0, "low": 0, "close": 0, "size": 0}
            opt_candle = self.option_candles["CE"][tc_time]
            token_info = self.option_handler._get_option_token("NIFTY", "CE", self.strike_ce)
            if token_info:
                self._async_replace_candle(token_info.get("exchange", "NFO"), token_info.get("token"), tc_time, opt_candle, label="CE Option")
                
        if short_valid and self.strike_pe > 0 and tc_time > 0:
            if tc_time not in self.option_candles["PE"]:
                self.option_candles["PE"][tc_time] = {"time": tc_time, "open": 0, "high": 0, "low": 0, "close": 0, "size": 0}
            opt_candle = self.option_candles["PE"][tc_time]
            token_info = self.option_handler._get_option_token("NIFTY", "PE", self.strike_pe)
            if token_info:
                self._async_replace_candle(token_info.get("exchange", "NFO"), token_info.get("token"), tc_time, opt_candle, label="PE Option")

        if long_valid and short_valid:
            print(f"[SETUP] Bin [{first_ts} -> {third_ts}]: BOTH L/S setups ARMED. Trigger size: {size:.2f}")
        elif long_valid:
            print(f"[SETUP] Bin [{first_ts} -> {third_ts}]: LONG setup ARMED. Trigger high: {third['high']:.2f}, size: {size:.2f}")
            log_debug(f"[DEBUG] LONG SETUP DETECTED. Currently have {len(self.option_candles['CE'])} CE option candles and {len(self.option_candles['PE'])} PE option candles. strike_ce={self.strike_ce}")
        elif short_valid:
            print(f"[SETUP] Bin [{first_ts} -> {third_ts}]: SHORT setup ARMED. Trigger low: {third['low']:.2f}, size: {size:.2f}")
            log_debug(f"[DEBUG] SHORT SETUP DETECTED. Currently have {len(self.option_candles['CE'])} CE option candles and {len(self.option_candles['PE'])} PE option candles. strike_pe={self.strike_pe}")
        else:
            if not size_ok and (second_short_ok and third_short_ok or second_long_ok and third_long_ok):
                print(f"[SETUP] Bin [{first_ts} -> {third_ts}]: Setup detected but trigger size {size:.2f} out of limits [{self.trig_min}, {self.trig_max}].")
            else:
                print(f"[SETUP] Bin [{first_ts} -> {third_ts}]: No setup detected.")
        
        self._notify()

    # =========================================================================
    # SAFETY MECHANISM
    # =========================================================================

    def _handle_safety_on_candle_close(self, candle):
        """Handle safety mechanism transitions when a futures candle closes."""
        if self.safety_state == "WAIT_CANDLE_CLOSE":
            # The candle during which SL was hit has closed — resume scanning for all directions
            if candle["time"] >= self.safety_wait_candle_ts:
                print(f"[SAFETY] WAIT_CANDLE_CLOSE: Candle closed. Resuming normal scanning.")
                self.safety_state = None
                self.safety_wait_candle_ts = 0
                self._notify()

    def _clear_safety_state(self):
        """Clear all safety mechanism state."""
        self.safety_state = None
        self.safety_wait_candle_ts = 0
        self.sl_hit_index_price = 0.0

    def _attempt_immediate_opposite_entry(self):
        """After SL hit, check if an opposite-direction setup is armed and the
        opposite option price qualifies for immediate entry.
        
        Returns True if a trade was entered, False otherwise.
        """
        failed_dir = self.last_failed_direction  # "CE" or "PE"
        
        if not failed_dir:
            return False

        if failed_dir == "CE":
            # Failed long → look for SHORT setup
            if not (self.short_setup_armed and self.short_trigger_candle):
                return False
            tc = self.short_trigger_candle
            size = tc["high"] - tc["low"]
            if not (self.trig_min <= size <= self.trig_max):
                print(f"[SAFETY] Opposite SHORT trigger candle size {size:.2f} out of limits. Skipping.")
                return False
            
            opt_tc_high = self._get_option_trigger_candle_high("PE", tc)
            if opt_tc_high is None:
                print(f"[SAFETY] No option trigger candle available for PE. Skipping.")
                return False
                
            pe_ltp = self.option_handler.get_option_ltp(self.strike_pe, "PE")
            if pe_ltp > opt_tc_high + self.break_buffer:
                print(f"[SAFETY] Immediate opposite SHORT entry! PE LTP {pe_ltp:.2f} > {opt_tc_high:.2f} + {self.break_buffer}")
                self.active_opt_strike = self.strike_pe
                self.active_opt_type = "PE"
                self.opt_ltp = pe_ltp
                self.short_setup_armed = False
                self.short_trigger_candle = None
                self._clear_safety_state()
                self._enter_trade("PE", tc)
                return True

        elif failed_dir == "PE":
            # Failed short → look for LONG setup
            if not (self.long_setup_armed and self.long_trigger_candle):
                return False
            tc = self.long_trigger_candle
            size = tc["high"] - tc["low"]
            if not (self.trig_min <= size <= self.trig_max):
                print(f"[SAFETY] Opposite LONG trigger candle size {size:.2f} out of limits. Skipping.")
                return False
            
            opt_tc_high = self._get_option_trigger_candle_high("CE", tc)
            if opt_tc_high is None:
                print(f"[SAFETY] No option trigger candle available for CE. Skipping.")
                return False
                
            ce_ltp = self.option_handler.get_option_ltp(self.strike_ce, "CE")
            if ce_ltp > opt_tc_high + self.break_buffer:
                print(f"[SAFETY] Immediate opposite LONG entry! CE LTP {ce_ltp:.2f} > {opt_tc_high:.2f} + {self.break_buffer}")
                self.active_opt_strike = self.strike_ce
                self.active_opt_type = "CE"
                self.opt_ltp = ce_ltp
                self.long_setup_armed = False
                self.long_trigger_candle = None
                self._clear_safety_state()
                self._enter_trade("CE", tc)
                return True

        return False

    # =========================================================================
    # BREAKOUT DETECTION
    # =========================================================================

    def _check_breakout(self, ltp, now):
        # Allow during SCANNING (normal) and IN_TRADE/TRAILING (for opposite-direction flip detection)
        if self.state not in ("SCANNING", "IN_TRADE", "TRAILING"):
            return
        
        # Safety gate: do not check for new breakouts during safety wait periods,
        # EXCEPT: during WAIT_CANDLE_CLOSE, keep polling for an opposite-direction entry.
        if self.safety_state is not None:
            if self.safety_state == "WAIT_CANDLE_CLOSE" and self.last_failed_direction:
                self._attempt_immediate_opposite_entry()
            return
            
        # Extra safety check against start/stop time boundaries
        start_t = self._parse_time(self.start_time_str) or dtime(9, 35)
        stop_t = self._parse_time(self.stop_time_str) or dtime(10, 45)
        if now.time() < start_t or now.time() >= stop_t:
            return
            
        # Premarket condition gate: do not enter trade if condition not met yet before 9:45
        if now.time() < dtime(9, 45) and not self.premarket_ok:
            return
        
        in_trade = self.state in ("IN_TRADE", "TRAILING")
        
        # LONG breakout: option trigger candle HIGH broken (futures check completely bypassed)
        if self.long_setup_armed and self.long_trigger_candle:
            if in_trade and self.direction == "CE":
                pass
            else:
                tc = self.long_trigger_candle
                opt_type = "CE"
                strike = self.strike_ce
                opt_tc_high = self._get_option_trigger_candle_high(opt_type, tc)
                if opt_tc_high is not None:
                    ce_ltp = self.option_handler.get_option_ltp(strike, opt_type)
                    if ce_ltp > opt_tc_high + self.break_buffer:
                        print(f"[ENTRY] LONG option breakout confirmed! CE LTP {ce_ltp:.2f} > {opt_tc_high:.2f} + {self.break_buffer}")
                        if in_trade:
                            old_dir = self.direction
                            print(f"[FLIP] Exiting {old_dir} trade to flip into CE trade")
                            self._exit_all("FLIP_TO_NEW_SETUP")
                        
                        self.active_opt_strike = strike
                        self.active_opt_type = opt_type
                        self.opt_ltp = ce_ltp
                        self.long_setup_armed = False
                        self.long_trigger_candle = None
                        self._enter_trade("CE", tc)
                        return

        # SHORT breakout: option trigger candle HIGH broken (futures check completely bypassed)
        if self.short_setup_armed and self.short_trigger_candle:
            if in_trade and self.direction == "PE":
                pass
            else:
                tc = self.short_trigger_candle
                opt_type = "PE"
                strike = self.strike_pe
                opt_tc_high = self._get_option_trigger_candle_high(opt_type, tc)
                if opt_tc_high is not None:
                    pe_ltp = self.option_handler.get_option_ltp(strike, opt_type)
                    if pe_ltp > opt_tc_high + self.break_buffer:
                        print(f"[ENTRY] SHORT option breakout confirmed! PE LTP {pe_ltp:.2f} > {opt_tc_high:.2f} + {self.break_buffer}")
                        if in_trade:
                            old_dir = self.direction
                            print(f"[FLIP] Exiting {old_dir} trade to flip into PE trade")
                            self._exit_all("FLIP_TO_NEW_SETUP")
                        
                        self.active_opt_strike = strike
                        self.active_opt_type = opt_type
                        self.opt_ltp = pe_ltp
                        self.short_setup_armed = False
                        self.short_trigger_candle = None
                        self._enter_trade("PE", tc)
                        return

    def _get_option_trigger_candle_high(self, opt_type, futures_tc):
        """Get the HIGH of the option trigger candle coincident with the futures trigger candle.

        STRICT: Only an exact tc_time match is used (or the running candle if its
        timestamp matches tc_time).  The old "fallback to latest completed option candle"
        has been intentionally removed because it used a *different* (older) candle's high
        as the breakout threshold, causing entries when the actual trigger candle's high
        had never been broken.

        Returns None if no valid option candle at tc_time is available yet.
        Returning None blocks the breakout check and the async fetch will fill the candle.
        """
        tc_time = futures_tc.get("time", 0)
        if not tc_time:
            return None

        opt_history = self.option_candles[opt_type]

        # Primary: exact timestamp match in completed option candle history
        opt_candle = opt_history.get(tc_time)

        # Secondary: use the currently-running option candle only if it is for the
        # same 5-min block as the trigger candle (i.e., we are still inside that block)
        if not opt_candle and self.running_opt_candle.get(opt_type):
            rc = self.running_opt_candle[opt_type]
            if rc.get("time") == tc_time:
                opt_candle = rc

        # No fallback to older candles — return None and let async fetch complete.
        if opt_candle and opt_candle.get("high", 0) > 0:
            return opt_candle["high"]

        return None

    # =========================================================================
    # ENTRY
    # =========================================================================

    def _enter_trade(self, opt_type, trigger_candle, force=False):
        tc_time = trigger_candle.get("time", 0)
        opt_history = self.option_candles[opt_type]
        opt_candle = opt_history.get(tc_time)

        # Fallback to the currently running option candle if it corresponds to the trigger timestamp
        if not opt_candle and self.running_opt_candle.get(opt_type):
            rc = self.running_opt_candle[opt_type]
            if rc.get("time") == tc_time:
                opt_candle = rc

        # NOTE: No fallback to "latest completed option candle" here — that could pick
        # an unrelated older candle whose size doesn't represent the current setup.
        # If the exact tc_time candle is unavailable, fall through to the futures size below.

        if opt_candle and (opt_candle["high"] - opt_candle["low"]) > 0:
            self.opt_candle_size = opt_candle["high"] - opt_candle["low"]
        else:
            # Fallback: use futures trigger candle size when no matching option candle is available
            fut_size = trigger_candle.get("high", 0) - trigger_candle.get("low", 0)
            self.opt_candle_size = fut_size

        self.entry_price_opt = self.option_handler.get_option_ltp(
            self.strike_ce if opt_type == "CE" else self.strike_pe, opt_type)
        if self.entry_price_opt <= 0:
            return

        ep = self.entry_price_opt
        cs = self.opt_candle_size if self.opt_candle_size > 0 else ep * 0.1

        # Option high starts at entry price — will be continuously tracked
        self.option_high_since_entry = ep

        # Initial SL: trigger candle size (in option) away from option high
        self.current_sl = ep - cs

        # Targets (same as existing)
        self.t1_target = ep + cs * self.t1_pct
        self.t2_target = ep + cs * self.t2_pct
        self.t3_target = ep + cs * self.t3_mult

        self.t1_hit = False
        self.t2_hit = False
        self.remaining_qty = self.initial_qty
        self.direction = opt_type  # Set the current active trade direction

        # Clear only the setup for the direction we entered
        if opt_type == "CE":
            self.long_setup_armed = False
            self.long_trigger_candle = None
        elif opt_type == "PE":
            self.short_setup_armed = False
            self.short_trigger_candle = None

        # Clear safety state on new trade
        self._clear_safety_state()
        
        self.active_trade_candles = dict(self.option_candles[opt_type])
        self.running_active_trade_candle = dict(self.running_opt_candle[opt_type]) if self.running_opt_candle[opt_type] else None
        self.last_active_trade_candle_ts = self.last_opt_candle_ts[opt_type]
        
        self.state = "IN_TRADE"
        self.trigger_candle = trigger_candle
        self._notify()

        # Place the ACTUAL entry order with the broker
        strike = self.strike_ce if opt_type == "CE" else self.strike_pe
        symbol = self.option_handler.get_option_symbol(strike, opt_type)
        if symbol:
            try:
                print(f"[ENTRY] Placing BUY order for {self.initial_qty} qty of {symbol} at Market.")
                self.position_manager.place_order(
                    tradingsymbol=symbol, quantity=self.initial_qty,
                    buy_or_sell='B', exchange="NFO", product_type='M', price_type='MKT'
                )
            except Exception as e:
                print(f"[ERROR] Failed to place entry order: {e}")

    # =========================================================================
    # IN-TRADE MANAGEMENT
    # =========================================================================

    def _check_trade(self, ltp, now):
        if self.state not in ("IN_TRADE", "TRAILING"):
            return
        opt_ltp = self.opt_ltp
        if opt_ltp <= 0:
            return
        direction = self.direction

        # Both CE and PE are bought options — profit when option price rises
        self._check_trade_long(opt_ltp)

    def _check_trade_long(self, opt_ltp):
        if not self.t1_hit:
            # Until target one hits, maintain SL exactly opt_candle_size from high price
            proposed_sl = self.option_high_since_entry - self.opt_candle_size
        else:
            # After target one hits, trail exactly by trail_points from max_price
            proposed_sl = self.option_high_since_entry - self.trail_points
                
        if proposed_sl != self.current_sl:
            self.current_sl = proposed_sl
            self.trailing_sl = proposed_sl
            self._notify()

        if not self.t1_hit:
            if opt_ltp >= self.t1_target:
                self._exit_partial(self.t1_qty, "T1")
                self.t1_hit = True
                # After T1: transition to trailing max_price
                self.current_sl = max(self.current_sl, self.option_high_since_entry - self.trail_points)
                if self.remaining_qty <= 0:
                    exited_dir = self.direction
                    print("[EXIT] Zero quantity remaining after T1 exit. Returning to SCANNING.")
                    self._reset_trade_state()
                    self.state = "SCANNING"
                    # Wait for the running candle to close before scanning same direction again
                    curr_candle_ts = self.running_fut_candle["time"] if self.running_fut_candle else 0
                    if curr_candle_ts > 0 and exited_dir:
                        self.last_failed_direction = exited_dir
                        self.safety_state = "WAIT_CANDLE_CLOSE"
                        self.safety_wait_candle_ts = curr_candle_ts
                        print(f"[SAFETY] T1 full exit. Waiting for candle to close before scanning {exited_dir} again.")
                self._notify()
                return

        if self.t1_hit and not self.t2_hit:
            if opt_ltp >= self.t2_target:
                self._exit_partial(self.t2_qty, "T2")
                self.t2_hit = True
                self.state = "TRAILING"
                # Cap the trailing Stop Loss distance from max_price
                self.trailing_sl = max(self.current_sl, self.option_high_since_entry - self.trail_points)
                self.current_sl = self.trailing_sl
                if self.remaining_qty <= 0:
                    exited_dir = self.direction
                    print("[EXIT] Zero quantity remaining after T2 exit. Returning to SCANNING.")
                    self._reset_trade_state()
                    self.state = "SCANNING"
                    # Wait for the running candle to close before scanning same direction again
                    curr_candle_ts = self.running_fut_candle["time"] if self.running_fut_candle else 0
                    if curr_candle_ts > 0 and exited_dir:
                        self.last_failed_direction = exited_dir
                        self.safety_state = "WAIT_CANDLE_CLOSE"
                        self.safety_wait_candle_ts = curr_candle_ts
                        print(f"[SAFETY] T2 full exit. Waiting for candle to close before scanning {exited_dir} again.")
                self._notify()
                return

        if self.state == "TRAILING":
            # Only trigger T3 if t3_target is strictly greater than t2_target
            if self.t3_target > self.t2_target and opt_ltp >= self.t3_target:
                self._exit_all("T3")
                return

        if opt_ltp <= self.current_sl:
            failed_dir = self.direction
            self.last_failed_direction = failed_dir
            self.sl_hit_index_price = self.index_ltp  # Capture index price at SL hit
            self._exit_all("SL")
            
            # Attempt immediate opposite-direction entry if a valid setup exists
            if self._attempt_immediate_opposite_entry():
                return  # Successfully entered opposite trade, no safety wait needed
            
            # No valid opposite entry — wait for the SL candle to close before scanning same direction
            # Opposite direction will keep being polled every tick via _check_breakout
            curr_candle_ts = self.running_fut_candle["time"] if self.running_fut_candle else 0
            self.safety_state = "WAIT_CANDLE_CLOSE"
            self.safety_wait_candle_ts = curr_candle_ts
            print(f"[SAFETY] SL hit. Waiting for candle {curr_candle_ts} to close. Opposite direction still active.")
            self._notify()

    def _update_sl_on_candle_close(self):
        if not self.futures_candles:
            return
        lc = self.futures_candles[-1]
        ots = lc.get("time", 0)
        oc = self.active_trade_candles.get(ots)
        if not oc:
            return

        # Both CE and PE are long options — trailing SL tracks option candle LOW, capped to at most trail_points below option candle HIGH
        if self.t1_hit and not self.t2_hit:
            proposed_sl = max(self.entry_price_opt, oc["low"])
            proposed_sl = max(proposed_sl, oc["high"] - self.trail_points)
            self.current_sl = max(self.current_sl, proposed_sl)
        self._notify()



    # =========================================================================
    # EXITS
    # =========================================================================

    def _exit_partial(self, qty, reason):
        if qty <= 0 or self.remaining_qty <= 0:
            return
        qty = min(qty, self.remaining_qty)
        print(f"[EXIT] Executing {reason} exit for {qty} qty at market.")
        opt_type = self.active_opt_type
        strike = self.active_opt_strike
        symbol = self.option_handler.get_option_symbol(strike, opt_type)
        if symbol:
            try:
                self.position_manager.place_order(
                    tradingsymbol=symbol, quantity=qty,
                    buy_or_sell='S', exchange="NFO", product_type='M', price_type='MKT')
            except Exception:
                pass
        self.remaining_qty -= qty

    def _exit_all(self, reason):
        print(f"[EXIT] Executing ALL remaining qty ({self.remaining_qty}) for reason: {reason}")
        exited_dir = self.direction  # capture before _reset_trade_state clears trade state
        self._exit_partial(self.remaining_qty, reason)
        self._reset_trade_state()
        self.state = "SCANNING"

        # For target exits (T3, etc.), wait for the running candle to close before
        # scanning the same direction again.  SL already sets its own safety state
        # after this call; FLIP immediately enters a new trade; PANIC is a hard stop.
        if reason not in ("SL", "FLIP_TO_NEW_SETUP", "PANIC") and exited_dir:
            curr_candle_ts = self.running_fut_candle["time"] if self.running_fut_candle else 0
            if curr_candle_ts > 0:
                self.last_failed_direction = exited_dir
                self.safety_state = "WAIT_CANDLE_CLOSE"
                self.safety_wait_candle_ts = curr_candle_ts
                print(f"[SAFETY] Trade closed ({reason}). Waiting for current candle to close before scanning {exited_dir} again.")

        self._notify()

    def _panic_exit_internal(self):
        if self.remaining_qty > 0 and self.state in ("IN_TRADE", "TRAILING"):
            self._exit_partial(self.remaining_qty, "PANIC")
        self._reset_trade_state()

    def _reset_trade_state(self):
        self.entry_price_opt = 0.0
        self.opt_candle_size = 0.0
        self.option_high_since_entry = 0.0
        self.t1_target = 0.0
        self.t2_target = 0.0
        self.t3_target = 0.0
        self.current_sl = 0.0
        self.trailing_sl = 0.0
        self.t1_hit = False
        self.t2_hit = False
        self.remaining_qty = 0
        self.trigger_candle = None
        # NOTE: We do NOT clear candle_bin, setup state, or safety state here.
        # The bin persists so setups can immediately form after a trade.
        # Safety state persists to enforce the wait mechanisms.

    # =========================================================================
    # NOTIFICATION
    # =========================================================================

    def _notify(self):
        try:
            # Suppress setup display during safety wait periods (no stale "TRIGGERED" in UI)
            if self.safety_state is not None:
                is_long = False
                is_short = False
            else:
                is_long = self.long_setup_armed
                is_short = self.short_setup_armed
            
            if is_long and is_short:
                setup_signal = "L/S"
                tc = self.short_trigger_candle
            elif is_long:
                setup_signal = "LONG"
                tc = self.long_trigger_candle
            elif is_short:
                setup_signal = "SHORT"
                tc = self.short_trigger_candle
            else:
                setup_signal = None
                tc = None

            tc_ts = ""
            if tc:
                try:
                    tc_ts = datetime.fromtimestamp(tc.get("time", 0)).strftime("%H:%M")
                except Exception:
                    tc_ts = ""

            def get_opt_candle_dict(opt_type, fut_tc):
                if not fut_tc:
                    return {}
                tc_time = fut_tc.get("time", 0)
                opt_history = self.option_candles.get(opt_type, {})
                opt_candle = opt_history.get(tc_time)
                if not opt_candle and opt_history:
                    last_key = max(opt_history.keys())
                    opt_candle = opt_history[last_key]
                if opt_candle:
                    try:
                        ts_str = datetime.fromtimestamp(opt_candle.get("time", 0)).strftime("%H:%M")
                    except Exception:
                        ts_str = ""
                    return {
                        "open_time": ts_str,
                        "high": opt_candle.get("high", 0),
                        "low": opt_candle.get("low", 0),
                    }
                return {}

            ce_candle_data = get_opt_candle_dict("CE", tc) if is_long else {}
            pe_candle_data = get_opt_candle_dict("PE", tc) if is_short else {}
            
            display_move = 0
            display_range = 0
            if self.prev_day_close > 0:
                app_high, app_low = self._get_applicable_high_low(datetime.now())
                if app_high is not None and app_low is not None:
                    display_move = max(abs(app_high - self.prev_day_close), abs(app_low - self.prev_day_close))
                    display_range = app_high - app_low
                    
            data = {
                "state": self.state,
                "setup_signal": setup_signal,
                "trigger_candle": {
                    "open_time": tc_ts,
                    "high": tc.get("high", 0) if tc else 0,
                    "low": tc.get("low", 0) if tc else 0,
                    "size": round((tc.get("high", 0) - tc.get("low", 0)), 2) if tc else 0
                } if tc else {},
                "ce_candle": ce_candle_data,
                "pe_candle": pe_candle_data,
                "entry_price_opt": self.entry_price_opt,
                "current_sl": self.current_sl,
                "t1_target": self.t1_target,
                "t1_hit": self.t1_hit,
                "t2_target": self.t2_target,
                "t2_hit": self.t2_hit,
                "t3_target": self.t3_target,
                "trailing_sl": self.trailing_sl,
                "remaining_qty": self.remaining_qty,
                "premarket_ok": self.premarket_ok,
                "prev_close": self.prev_day_close,
                "day_range": round(display_range, 2),
                "premarket_move": round(display_move, 2),
                "opt_ltp": self.opt_ltp,
                "opt_candle_size": round(self.opt_candle_size, 2),
                "safety_state": self.safety_state,
            }
            if self.bridge:
                self.bridge.notify("updateNiftyState", data)
        except Exception:
            pass

    def get_state_dict(self):
        self._notify()
        return {
            "state": self.state,
            "premarket_ok": self.premarket_ok,
            "prev_close": self.prev_day_close,
            "remaining_qty": self.remaining_qty,
        }
