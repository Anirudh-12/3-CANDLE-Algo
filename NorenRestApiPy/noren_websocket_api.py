"""
NorenWebsocketApi - WebSocket client for real-time market data.

This module handles all websocket-related functionality including:
- Connection management
- Subscription/unsubscription to instruments
- Message parsing and routing
- Callback handling for market data and order updates
"""

import json
import ssl
import logging
import threading
import websocket
from typing import Optional, Callable, Any, Dict, List, Union, Final
from time import sleep

logger = logging.getLogger(__name__)


def reportmsg(msg: str) -> None:
    """Log debug message."""
    logger.debug(msg)


def reporterror(msg: str) -> None:
    """Log error message."""
    logger.error(msg)


def reportinfo(msg: str) -> None:
    """Log info message."""
    logger.info(msg)


class FeedType:
    """Feed type constants."""
    TOUCHLINE: Final = 1
    SNAPQUOTE: Final = 2


class NorenWebsocketApi:
    """
    WebSocket API client for real-time market data.
    
    This class handles all websocket operations including:
    - Establishing and maintaining websocket connections
    - Subscribing/unsubscribing to market data feeds
    - Parsing and routing websocket messages
    - Managing callbacks for market data and order updates
    """
    
    def __init__(
        self,
        websocket_url: str,
        userid: str,
        susertoken: str,
        accountid: str
    ) -> None:
        """
        Initialize NorenWebsocketApi.
        
        Args:
            host: REST API host (not used, kept for compatibility)
            websocket_url: WebSocket endpoint URL
            userid: User ID from authenticated session
            susertoken: Session token from authenticated session
            accountid: Account ID from authenticated session
        """
        self.__websocket_url = websocket_url
        self.__username = userid
        self.__accountid = accountid
        self.__susertoken = susertoken
        
        self.__websocket: Optional[websocket.WebSocketApp] = None
        self.__websocket_connected = False
        self.__ws_mutex = threading.Lock()
        self.__stop_event: Optional[threading.Event] = None
        self.__ws_thread: Optional[threading.Thread] = None
        
        # Callbacks
        self.__on_error: Optional[Callable[[Any], None]] = None
        self.__on_disconnect: Optional[Callable[[], None]] = None
        self.__on_open: Optional[Callable[[], None]] = None
        self.__subscribe_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self.__order_update_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        
        # Subscription tracking
        self.__subscribers: Dict[str, Any] = {}
        self.__market_status_messages: List[Dict[str, Any]] = []
        self.__exchange_messages: List[Dict[str, Any]] = []

    def __ws_run_forever(self) -> None:
        """Run websocket connection loop with auto-reconnect."""
        if self.__stop_event is None:
            return
        
        while not self.__stop_event.is_set():
            if self.__websocket is None:
                break
                
            try:
                self.__websocket.run_forever(
                    ping_interval=3,
                    ping_payload='{"t":"h"}',
                    sslopt={"cert_reqs": ssl.CERT_NONE}
                )
            except Exception as e:
                logger.warning(f"websocket run forever ended in exception, {e}")
            
            sleep(0.1)  # Sleep for 100ms between reconnection

    def __ws_send(self, *args: Any, **kwargs: Any) -> Any:
        """
        Send message through websocket with connection check.
        
        Args:
            *args: Positional arguments for websocket.send()
            **kwargs: Keyword arguments for websocket.send()
            
        Returns:
            Result of websocket.send()
        """
        while not self.__websocket_connected:
            sleep(0.05)  # Sleep for 50ms if websocket is not connected, wait for reconnection
        
        with self.__ws_mutex:
            if self.__websocket:
                self.__websocket.send(*args, **kwargs)
        return None

    def __on_close_callback(
        self,
        wsapp: Any,
        close_status_code: Any,
        close_msg: Any
    ) -> None:
        """
        Handle websocket close event.
        
        Args:
            wsapp: WebSocketApp instance
            close_status_code: Close status code
            close_msg: Close message
        """
        reportmsg(str(close_status_code))
        reportmsg(str(wsapp))
        
        self.__websocket_connected = False
        if self.__on_disconnect:
            self.__on_disconnect()

    def __on_open_callback(self, ws: Any) -> None:
        """
        Handle websocket open event.
        
        Args:
            ws: WebSocketApp instance (optional for compatibility)
        """
        self.__websocket_connected = True
        
        # Prepare connection data
        values: Dict[str, Any] = {"t": "c"}
        values["uid"] = self.__username
        values["actid"] = self.__username
        values["susertoken"] = self.__susertoken
        values["source"] = 'API'
        
        payload = json.dumps(values)
        reportmsg(payload)
        self.__ws_send(payload)

    def __on_error_callback(
        self,
        ws: Any,
        error: Any
    ) -> None:
        """
        Handle websocket error event.
        
        Args:
            ws: WebSocketApp instance or error object (for compatibility)
            error: Error object (optional)
        """
        # This workaround is to solve the websocket_client's compatibility issue
        # of older versions (e.g., 0.40.0) which is used in upstox.
        # Now this will work in both 0.40.0 & newer version of websocket_client
        if not isinstance(ws, websocket.WebSocketApp):
            error = ws
        
        if self.__on_error and error is not None:
            self.__on_error(error)

    def __on_data_callback(
        self,
        ws: Optional[websocket.WebSocketApp] = None,
        message: Optional[str] = None,
        data_type: Optional[int] = None,
        continue_flag: Optional[bool] = None
    ) -> None:
        """
        Handle incoming websocket data.
        
        Args:
            ws: WebSocketApp instance (optional)
            message: Message string
            data_type: Data type (optional)
            continue_flag: Continue flag (optional)
        """
        if message is None:
            return
        
        try:
            res = json.loads(message)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse websocket message: {message}")
            return
        
        # Route to subscribe callback for market data
        if self.__subscribe_callback is not None:
            if res.get('t') == 'tk' or res.get('t') == 'tf':
                self.__subscribe_callback(res)
                return
            if res.get('t') == 'dk' or res.get('t') == 'df':
                self.__subscribe_callback(res)
                return
        
        # Route to error callback
        if self.__on_error is not None:
            if res.get('t') == 'ck' and res.get('s') != 'OK':
                self.__on_error(res)
                return
        
        # Route to order update callback
        if self.__order_update_callback is not None:
            if res.get('t') == 'om':
                self.__order_update_callback(res)
                return
        
        # Route to open callback
        if self.__on_open:
            if res.get('t') == 'ck' and res.get('s') == 'OK':
                self.__on_open()
                return

    def start_websocket(
        self,
        subscribe_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        order_update_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        socket_open_callback: Optional[Callable[[], None]] = None,
        socket_close_callback: Optional[Callable[[], None]] = None,
        socket_error_callback: Optional[Callable[[Any], None]] = None
    ) -> None:
        """
        Start websocket connection for getting live data.
        
        Args:
            subscribe_callback: Callback for market data updates (tick/snapquote)
            order_update_callback: Callback for order updates
            socket_open_callback: Callback when websocket opens
            socket_close_callback: Callback when websocket closes
            socket_error_callback: Callback for websocket errors
        """
        self.__on_open = socket_open_callback
        self.__on_disconnect = socket_close_callback
        self.__on_error = socket_error_callback
        self.__subscribe_callback = subscribe_callback
        self.__order_update_callback = order_update_callback
        
        self.__stop_event = threading.Event()
        url = self.__websocket_url.format(access_token=self.__susertoken)
        reportmsg(f'connecting to {url}')
        
        self.__websocket = websocket.WebSocketApp(
            url,
            on_data=self.__on_data_callback,
            on_error=self.__on_error_callback,
            on_close=self.__on_close_callback,
            on_open=self.__on_open_callback
        )
        
        self.__ws_thread = threading.Thread(target=self.__ws_run_forever)
        self.__ws_thread.daemon = True
        self.__ws_thread.start()

    def close_websocket(self) -> None:
        """Close websocket connection."""
        if not self.__websocket_connected:
            return
        
        if self.__stop_event:
            self.__stop_event.set()
        
        self.__websocket_connected = False
        
        if self.__websocket:
            self.__websocket.close()
        
        if self.__ws_thread:
            self.__ws_thread.join()

    def subscribe(
        self,
        instrument: Union[str, List[str]],
        feed_type: int = FeedType.TOUCHLINE
    ) -> None:
        """
        Subscribe to market data feed.
        
        Args:
            instrument: Single instrument symbol or list of symbols
            feed_type: Feed type (FeedType.TOUCHLINE or FeedType.SNAPQUOTE)
        """
        values: Dict[str, Any] = {}
        
        if feed_type == FeedType.TOUCHLINE:
            values['t'] = 't'
        elif feed_type == FeedType.SNAPQUOTE:
            values['t'] = 'd'
        else:
            values['t'] = str(feed_type)
        
        if isinstance(instrument, list):
            values['k'] = '#'.join(instrument)
        else:
            values['k'] = instrument
        
        data = json.dumps(values)
        self.__ws_send(data)

    def unsubscribe(
        self,
        instrument: Union[str, List[str]],
        feed_type: int = FeedType.TOUCHLINE
    ) -> None:
        """
        Unsubscribe from market data feed.
        
        Args:
            instrument: Single instrument symbol or list of symbols
            feed_type: Feed type (FeedType.TOUCHLINE or FeedType.SNAPQUOTE)
        """
        values: Dict[str, Any] = {}
        
        if feed_type == FeedType.TOUCHLINE:
            values['t'] = 'u'
        elif feed_type == FeedType.SNAPQUOTE:
            values['t'] = 'ud'
        
        if isinstance(instrument, list):
            values['k'] = '#'.join(instrument)
        else:
            values['k'] = instrument
        
        data = json.dumps(values)
        self.__ws_send(data)

    def subscribe_orders(self) -> None:
        """Subscribe to order updates."""
        values: Dict[str, Any] = {'t': 'o'}
        values['actid'] = self.__accountid
        
        data = json.dumps(values)
        reportmsg(data)
        self.__ws_send(data)

