import logging
from collections import deque
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Setup Logger (Debug Level as Requested)
# ---------------------------------------------------------------------------
logger = logging.getLogger("OneMinDataHandler")
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)

# ---------------------------------------------------------------------------
# 1-Minute Data Handler Module
# ---------------------------------------------------------------------------
class OneMinDataHandler:
    """
    Parallel, independent module to fetch, build, and maintain a rolling window
    of 1-minute candles for the Donchian channel calculation.
    """
    
    def __init__(self, api, exchange, token, donchian_period=20):
        """
        Initializes the 1-minute candle pipeline.
        
        :param api: API instance to fetch historical data (assumes NorenApi style `get_time_price_series`).
        :param exchange: Exchange segment (e.g., "NSE" or "NFO").
        :param token: The instrument token (e.g., Nifty Spot or Future token).
        :param donchian_period: The number of closed 1-minute candles needed for the Donchian calculation.
        """
        self.api = api
        self.exchange = exchange
        self.token = token
        self.donchian_period = donchian_period
        
        # Deque for fixed size, O(1) appends, strict rolling window of 100 CLOSED candles
        self.one_min_candles = deque(maxlen=100)
        
        # State variables for building the live 1-minute candle
        self.current_candle = None
        self.current_minute_bucket = 0
        
        logger.debug("[INIT] OneMinDataHandler initialized.")


    def load_historical_data(self):
        """
        Fetches historical 1-minute candles from the broker API.
        Attempts to load at least 50 candles for safety and fills the deque.
        """
        now = datetime.now()
        # Fetching roughly 100 minutes of historical data (safe margin)
        start_time = now - timedelta(minutes=100)
        
        try:
            # Assuming api interface from previous strategy context: get_time_price_series
            candles = self.api.get_time_price_series(
                exchange=self.exchange,
                token=self.token,
                starttime=start_time.timestamp(),
                endtime=now.timestamp(),
                interval=1  # 1-minute interval
            )
            
            if candles:
                # The API usually returns newest candles first; reverse to chronological order
                candles_sorted = candles[::-1]
                
                # Determine the current incomplete 1-minute bucket to avoid appending it as closed
                current_bucket = int(now.timestamp()) // 60
                
                loaded_count = 0
                for c in candles_sorted:
                    t_str = c.get('time')
                    try:
                        dt = datetime.strptime(t_str, "%d-%m-%Y %H:%M:%S")
                    except ValueError:
                        try:
                            dt = datetime.strptime(t_str, "%d/%m/%Y %H:%M:%S")
                        except ValueError:
                            continue  # Skip unparseable dates
                    
                    c_ts = int(dt.timestamp())
                    bucket = c_ts // 60
                    
                    # Only append strictly historic (completed) candles
                    if bucket < current_bucket:
                        candle_obj = {
                            "time": c_ts,       # Actual candle start timestamp
                            "open": float(c.get('into')),
                            "high": float(c.get('inth')),
                            "low": float(c.get('intl')),
                            "close": float(c.get('intc')),
                            "volume": int(c.get('intv', 0))
                        }
                        
                        # Only append if the deque is empty or the candle is strictly newer than the last buffered
                        if not self.one_min_candles or bucket > (self.one_min_candles[-1]['time'] // 60):
                            self.one_min_candles.append(candle_obj)
                            loaded_count += 1
                
                logger.debug(f"[INIT] Loaded {loaded_count} historical 1-min candles")
            else:
                logger.debug("[INIT] API returned no historical 1-min candles.")
                
        except Exception as e:
            logger.error(f"[INIT] Error fetching historical data: {e}")


    def on_tick(self, ltt_timestamp, ltp):
        """
        Process a new tick to update or finalize the live 1-minute candle.
        This must be called alongside your 5-min tick processor.
        
        :param ltt_timestamp: Timestamp of the tick (int/float seconds from epoch).
        :param ltp: Last traded price.
        """
        if not ltp or not ltt_timestamp:
            return

        # Determine structural bucket
        tick_bucket = int(ltt_timestamp) // 60
        
        # 1. No active candle? Initialize the first one
        if self.current_candle is None:
            self._start_new_candle(tick_bucket, ltp)
            return

        # 2. Continues in the SAME minute bucket
        if tick_bucket == self.current_minute_bucket:
            self.current_candle["high"] = max(self.current_candle["high"], ltp)
            self.current_candle["low"] = min(self.current_candle["low"], ltp)
            self.current_candle["close"] = ltp
            logger.debug(f"[TICK] Updating current 1-min candle (Bucket {tick_bucket})")

        # 3. Time crossed into a NEW minute boundary: finalize the old candle
        elif tick_bucket > self.current_minute_bucket:
            # Append completely closed candle to the rolling history
            self.one_min_candles.append(self.current_candle.copy())
            
            # Formatted log for verification
            closed_dt = datetime.fromtimestamp(self.current_candle["time"]).strftime('%H:%M:%S')
            logger.debug(f"[NEW CANDLE] 1-min candle closed at {closed_dt} | Close: {self.current_candle['close']:.2f}")
            
            # Start fresh bucket for the incoming tick
            self._start_new_candle(tick_bucket, ltp)

        # 4. Out-of-order / Delayed tick from the past (Discard to maintain strict data integrity)
        else:
            pass


    def _start_new_candle(self, bucket, price):
        """Internal helper to initialize a new live candle state."""
        self.current_minute_bucket = bucket
        candle_start_ts = bucket * 60
        
        self.current_candle = {
            "time": candle_start_ts,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 0
        }


    def get_donchian_values(self):
        """
        Exposed integration function to get the Donchian channel.
        Strictly calculates using the required number of *closed* 1-minute candles.
        
        :return: Tuple (upper, lower, range_). Returns (0, 0, 0) if insufficient payload.
        """
        # Data Safety: Verify we have enough closed candles
        if len(self.one_min_candles) < self.donchian_period:
            logger.debug(f"[DONCHIAN] Insufficient completed candles ({len(self.one_min_candles)}/{self.donchian_period})")
            return 0, 0, 0
            
        # O(1) slice of the end of the deque using standard list cast
        window_candles = list(self.one_min_candles)[-self.donchian_period:]
        
        highs = [c["high"] for c in window_candles]
        lows = [c["low"] for c in window_candles]
        
        upper = max(highs)
        lower = min(lows)
        range_ = upper - lower
        
        return upper, lower, range_
