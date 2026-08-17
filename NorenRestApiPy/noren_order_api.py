"""
NorenOrderApi - REST API client for order and market data operations.

This module provides a clean separation of REST/order functionality
from websocket functionality. All order placement, position queries,
and market data REST calls are handled here.
"""

import json
import logging
import hashlib
import time
import urllib.parse
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, date, timedelta
import requests
import dataclasses
from dataclasses import dataclass
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

@dataclass
class ProductType:
    """Product type constants."""
    Delivery = 'C'
    Intraday = 'I'
    Normal = 'M'
    CF = 'M'


class PriceType:
    """Price type constants."""
    Market = 'MKT'
    Limit = 'LMT'
    StopLossLimit = 'SL-LMT'
    StopLossMarket = 'SL-MKT'


class BuyorSell:
    """Buy/Sell constants."""
    Buy = 'B'
    Sell = 'S'


class NorenOrderApi:
    """
    REST API client for order operations and market data queries.
    
    This class handles all REST-based operations including:
    - Authentication and session management
    - Order placement, modification, cancellation
    - Position and order book queries
    - Market data queries (quotes, historical data, option chains)
    - Account information (holdings, limits)
    - Watchlist operations
    """
    
    

    def __init__(self, host: str, websocket: str) -> None:
        """
        Initialize NorenOrderApi.
        
        Args:
            host: REST API host URL
            websocket: Websocket endpoint URL (stored but not used here)
        """
        self.service_config: Dict[str, Any] = {
        'host': 'https://piconnect.flattrade.in/PiConnectAPI',
        'routes': {
            'authorize': '/QuickAuth',
            'logout': '/Logout',
            'forgot_password': '/ForgotPassword',
            'change_password': '/Changepwd',
            'watchlist_names': '/MWList',
            'watchlist': '/MarketWatch',
            'watchlist_add': '/AddMultiScripsToMW',
            'watchlist_delete': '/DeleteMultiMWScrips',
            'placeorder': '/PlaceOrder',
            'modifyorder': '/ModifyOrder',
            'cancelorder': '/CancelOrder',
            'exitorder': '/ExitSNOOrder',
            'product_conversion': '/ProductConversion',
            'orderbook': '/OrderBook',
            'tradebook': '/TradeBook',
            'singleorderhistory': '/SingleOrdHist',
            'searchscrip': '/SearchScrip',
            'TPSeries': '/TPSeries',
            'optionchain': '/GetOptionChain',
            'holdings': '/Holdings',
            'limits': '/Limits',
            'positions': '/PositionBook',
            'scripinfo': '/GetSecurityInfo',
            'getquotes': '/GetQuotes',
            'span_calculator': '/SpanCalc',
            'option_greek': '/GetOptionGreek',
            'get_daily_price_series': '/EODChartData',
        },
        }
        # self.product_type = ProductType.Delivery
        self.service_config['host'] = host
        # self.service_config['websocket_endpoint'] = websocket
        
        # Session state
        self.username: Optional[str] = None
        self.accountid: Optional[str] = None
        self.password: Optional[str] = None
        self.susertoken: Optional[str] = None

    def login(self, userid, password, twoFA, vendor_code, api_secret, imei):
        config = self.service_config

        #prepare the uri
        url = f"{config['host']}{config['routes']['authorize']}" 
        reportmsg(url)

        #Convert to SHA 256 for password and app key
        pwd = hashlib.sha256(password.encode('utf-8')).hexdigest()
        u_app_key = '{0}|{1}'.format(userid, api_secret)
        app_key=hashlib.sha256(u_app_key.encode('utf-8')).hexdigest()
        #prepare the data
        values              = { "source": "API" , "apkversion": "1.0.0"}
        values["uid"]       = userid
        values["pwd"]       = pwd
        values["factor2"]   = twoFA
        values["vc"]        = vendor_code
        values["appkey"]    = app_key        
        values["imei"]      = imei        

        payload = 'jData=' + json.dumps(values)
        reportmsg("Req:" + payload)

        res = requests.post(url, data=payload)
        reportmsg("Reply:" + res.text)

        resDict = json.loads(res.text)
        if resDict['stat'] != 'Ok':            
            return None
        
        self.username   = userid
        self.accountid  = userid
        self.password   = password
        self.susertoken = resDict['susertoken']
        #reportmsg(self.susertoken)

        return resDict


    def set_session(self, userid: str, password: str, usertoken: str) -> bool:
        """
        Set session using existing token.
        
        Args:
            userid: User ID
            password: Password
            usertoken: Session token
            
        Returns:
            True on success
        """
        self.username = userid
        self.accountid = userid
        self.password = password
        self.susertoken = usertoken
        
        reportmsg(f'{userid} session set to : {self.susertoken}')
        return True

    def get_userid(self) -> Optional[str]:
        """Get current user ID."""
        return self.username

    def get_accountid(self) -> Optional[str]:
        """Get current account ID."""
        return self.accountid

    def get_token(self) -> Optional[str]:
        """Get current session token."""
        return self.susertoken

    def forgot_password(self, userid: str, pan: str, dob: str) -> Optional[Dict[str, Any]]:
        """
        Request password reset.
        
        Args:
            userid: User ID
            pan: PAN number
            dob: Date of birth
            
        Returns:
            Response dictionary or None on error
        """
        config = self.service_config
        
        url = f"{config['host']}{config['routes']['forgot_password']}"
        reportmsg(url)
        
        values: Dict[str, Any] = {"source": "API"}
        values["uid"] = userid
        values["pan"] = pan
        values["dob"] = dob
        
        payload = 'jData=' + json.dumps(values)
        reportmsg("Req:" + payload)
        
        res = requests.post(url, data=payload)
        reportmsg("Reply:" + res.text)
        
        resDict = json.loads(res.text)
        if resDict['stat'] != 'Ok':
            return None
        
        return resDict

    def logout(self) -> Optional[Dict[str, Any]]:
        """
        Logout and invalidate session.
        
        Returns:
            Response dictionary or None on error
        """
        config = self.service_config
        
        url = f"{config['host']}{config['routes']['logout']}"
        reportmsg(url)
        
        values: Dict[str, Any] = {'ordersource': 'API'}
        values["uid"] = self.username
        
        payload = 'jData=' + json.dumps(values) + f'&jKey={self.susertoken}'
        reportmsg(payload)
        
        res = requests.post(url, data=payload)
        reportmsg(res.text)
        
        resDict = json.loads(res.text)
        if resDict['stat'] != 'Ok':
            return None
        
        self.username = None
        self.accountid = None
        self.password = None
        self.susertoken = None
        
        return resDict

    def get_watch_list_names(self) -> Optional[Dict[str, Any]]:
        """
        Get list of watchlist names.
        
        Returns:
            Dictionary with watchlist names or None on error
        """
        config = self.service_config
        
        url = f"{config['host']}{config['routes']['watchlist_names']}"
        reportmsg(url)
        
        values: Dict[str, Any] = {'ordersource': 'API'}
        values["uid"] = self.username
        
        payload = 'jData=' + json.dumps(values) + f'&jKey={self.susertoken}'
        reportmsg(payload)
        
        res = requests.post(url, data=payload)
        reportmsg(res.text)
        
        resDict = json.loads(res.text)
        if resDict['stat'] != 'Ok':
            return None
        
        return resDict

    def get_watch_list(self, wlname: str) -> Optional[Dict[str, Any]]:
        """
        Get instruments in a watchlist.
        
        Args:
            wlname: Watchlist name
            
        Returns:
            Dictionary with watchlist instruments or None on error
        """
        config = self.service_config
        
        url = f"{config['host']}{config['routes']['watchlist']}"
        reportmsg(url)
        
        values: Dict[str, Any] = {'ordersource': 'API'}
        values["uid"] = self.username
        values["wlname"] = wlname
        
        payload = 'jData=' + json.dumps(values) + f'&jKey={self.susertoken}'
        reportmsg(payload)
        
        res = requests.post(url, data=payload)
        reportmsg(res.text)
        
        resDict = json.loads(res.text)
        if resDict['stat'] != 'Ok':
            return None
        
        return resDict

    def add_watch_list_scrip(
        self,
        wlname: str,
        instrument: Union[str, List[str]]
    ) -> Optional[Dict[str, Any]]:
        """
        Add instruments to watchlist.
        
        Args:
            wlname: Watchlist name
            instrument: Single instrument symbol or list of symbols
            
        Returns:
            Response dictionary or None on error
        """
        config = self.service_config
        
        url = f"{config['host']}{config['routes']['watchlist_add']}"
        reportmsg(url)
        
        values: Dict[str, Any] = {'ordersource': 'API'}
        values["uid"] = self.username
        values["wlname"] = wlname
        
        if isinstance(instrument, list):
            values['scrips'] = '#'.join(instrument)
        else:
            values['scrips'] = instrument
        
        payload = 'jData=' + json.dumps(values) + f'&jKey={self.susertoken}'
        reportmsg(payload)
        
        res = requests.post(url, data=payload)
        reportmsg(res.text)
        
        resDict = json.loads(res.text)
        if resDict['stat'] != 'Ok':
            return None
        
        return resDict

    def delete_watch_list_scrip(
        self,
        wlname: str,
        instrument: Union[str, List[str]]
    ) -> Optional[Dict[str, Any]]:
        """
        Remove instruments from watchlist.
        
        Args:
            wlname: Watchlist name
            instrument: Single instrument symbol or list of symbols
            
        Returns:
            Response dictionary or None on error
        """
        config = self.service_config
        
        url = f"{config['host']}{config['routes']['watchlist_delete']}"
        reportmsg(url)
        
        values: Dict[str, Any] = {'ordersource': 'API'}
        values["uid"] = self.username
        values["wlname"] = wlname
        
        if isinstance(instrument, list):
            values['scrips'] = '#'.join(instrument)
        else:
            values['scrips'] = instrument
        
        payload = 'jData=' + json.dumps(values) + f'&jKey={self.susertoken}'
        reportmsg(payload)
        
        res = requests.post(url, data=payload)
        reportmsg(res.text)
        
        resDict = json.loads(res.text)
        if resDict['stat'] != 'Ok':
            return None
        
        return resDict

    def place_order(
        self,
        buy_or_sell: str,
        product_type: str,
        exchange: str,
        tradingsymbol: str,
        quantity: int,
        discloseqty: int,
        price_type: str,
        price: float = 0.0,
        trigger_price: Optional[float] = None,
        retention: str = 'DAY',
        amo: Optional[str] = None,
        remarks: Optional[str] = None,
        bookloss_price: float = 0.0,
        bookprofit_price: float = 0.0,
        trail_price: float = 0.0
    ) -> Optional[Dict[str, Any]]:
        """
        Place an order.
        
        Args:
            buy_or_sell: 'B' for Buy, 'S' for Sell
            product_type: Product type (M, I, C, H, B)
            exchange: Exchange code
            tradingsymbol: Trading symbol
            quantity: Order quantity
            discloseqty: Disclosed quantity
            price_type: Price type (MKT, LMT, SL-LMT, SL-MKT)
            price: Order price (for limit orders)
            trigger_price: Trigger price (for SL orders)
            retention: Retention type (DAY, IOC, etc.)
            amo: After market order flag
            remarks: Order remarks
            bookloss_price: Book loss price (for bracket/cover orders)
            bookprofit_price: Book profit price (for bracket orders)
            trail_price: Trailing price
            
        Returns:
            Order response dictionary or None on error
        """
        config = self.service_config
        
        url = f"{config['host']}{config['routes']['placeorder']}"
        reportmsg(url)
        
        values: Dict[str, Any] = {'ordersource': 'API'}
        values["uid"] = self.username
        values["actid"] = self.accountid
        values["trantype"] = buy_or_sell
        values["prd"] = product_type
        values["exch"] = exchange
        values["tsym"] = urllib.parse.quote_plus(tradingsymbol)
        values["qty"] = str(quantity)
        values["dscqty"] = str(discloseqty)
        values["prctyp"] = price_type
        values["prc"] = str(price)
        values["trgprc"] = str(trigger_price) if trigger_price is not None else ""
        values["ret"] = retention
        values["remarks"] = remarks
        
        if amo is not None:
            values["amo"] = amo
        
        # Cover order or high leverage order
        if product_type == 'H':
            values["blprc"] = str(bookloss_price)
            if trail_price != 0.0:
                values["trailprc"] = str(trail_price)
        
        # Bracket order
        if product_type == 'B':
            values["blprc"] = str(bookloss_price)
            values["bpprc"] = str(bookprofit_price)
            if trail_price != 0.0:
                values["trailprc"] = str(trail_price)
        
        payload = 'jData=' + json.dumps(values) + f'&jKey={self.susertoken}'
        reportmsg(payload)
        
        res = requests.post(url, data=payload)
        reportmsg(res.text)
        
        resDict = json.loads(res.text)
        if resDict['stat'] != 'Ok':
            return None
        
        return resDict

    def modify_order(
        self,
        orderno: Union[str, int],
        exchange: str,
        tradingsymbol: str,
        newquantity: int,
        newprice_type: str,
        newprice: float = 0.0,
        newtrigger_price: Optional[float] = None,
        bookloss_price: float = 0.0,
        bookprofit_price: float = 0.0,
        trail_price: float = 0.0
    ) -> Optional[Dict[str, Any]]:
        """
        Modify an existing order.
        
        Args:
            orderno: Order number
            exchange: Exchange code
            tradingsymbol: Trading symbol
            newquantity: New quantity
            newprice_type: New price type
            newprice: New price
            newtrigger_price: New trigger price (for SL orders)
            bookloss_price: Book loss price
            bookprofit_price: Book profit price
            trail_price: Trailing price
            
        Returns:
            Response dictionary or None on error
        """
        config = self.service_config
        
        url = f"{config['host']}{config['routes']['modifyorder']}"
        reportmsg(url)
        
        values: Dict[str, Any] = {'ordersource': 'API'}
        values["uid"] = self.username
        values["actid"] = self.accountid
        values["norenordno"] = str(orderno)
        values["exch"] = exchange
        values["tsym"] = urllib.parse.quote_plus(tradingsymbol)
        values["qty"] = str(newquantity)
        values["prctyp"] = newprice_type
        values["prc"] = str(newprice)
        
        if (newprice_type == 'SL-LMT') or (newprice_type == 'SL-MKT'):
            if newtrigger_price is not None:
                values["trgprc"] = str(newtrigger_price)
            else:
                reporterror('trigger price is missing')
                return None
        
        if bookloss_price != 0.0:
            values["blprc"] = str(bookloss_price)
        
        if trail_price != 0.0:
            values["trailprc"] = str(trail_price)
        
        if bookprofit_price != 0.0:
            values["bpprc"] = str(bookprofit_price)
        
        payload = 'jData=' + json.dumps(values) + f'&jKey={self.susertoken}'
        reportmsg(payload)
        
        res = requests.post(url, data=payload)
        reportmsg(res.text)
        
        resDict = json.loads(res.text)
        if resDict['stat'] != 'Ok':
            return None
        
        return resDict

    def cancel_order(self, orderno: Union[str, int]) -> Optional[Dict[str, Any]]:
        """
        Cancel an order.
        
        Args:
            orderno: Order number
            
        Returns:
            Response dictionary or None on error
        """
        config = self.service_config
        
        url = f"{config['host']}{config['routes']['cancelorder']}"
        reportmsg(url)
        
        values: Dict[str, Any] = {'ordersource': 'API'}
        values["uid"] = self.username
        values["norenordno"] = str(orderno)
        
        payload = 'jData=' + json.dumps(values) + f'&jKey={self.susertoken}'
        reportmsg(payload)
        
        res = requests.post(url, data=payload)
        reportmsg(res.text)
        
        resDict = json.loads(res.text)
        if resDict['stat'] != 'Ok':
            return None
        
        return resDict

    def exit_order(
        self,
        orderno: Union[str, int],
        product_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        Exit a bracket/cover order.
        
        Args:
            orderno: Order number
            product_type: Product type
            
        Returns:
            Response dictionary or None on error
        """
        config = self.service_config
        
        url = f"{config['host']}{config['routes']['exitorder']}"
        reportmsg(url)
        
        values: Dict[str, Any] = {'ordersource': 'API'}
        values["uid"] = self.username
        values["norenordno"] = orderno
        values["prd"] = product_type
        
        payload = 'jData=' + json.dumps(values) + f'&jKey={self.susertoken}'
        reportmsg(payload)
        
        res = requests.post(url, data=payload)
        reportmsg(res.text)
        
        resDict = json.loads(res.text)
        if resDict['stat'] != 'Ok':
            return None
        
        return resDict

    def position_product_conversion(
        self,
        exchange: str,
        tradingsymbol: str,
        quantity: int,
        new_product_type: str,
        previous_product_type: str,
        buy_or_sell: str,
        day_or_cf: str
    ) -> Optional[Dict[str, Any]]:
        """
        Convert position from one product type to another.
        
        Args:
            exchange: Exchange code
            tradingsymbol: Trading symbol
            quantity: Quantity to convert
            new_product_type: Target product type
            previous_product_type: Current product type
            buy_or_sell: 'B' or 'S'
            day_or_cf: 'Day' or 'CF'
            
        Returns:
            Response dictionary or None on error
        """
        config = self.service_config
        
        url = f"{config['host']}{config['routes']['product_conversion']}"
        reportmsg(url)
        
        values: Dict[str, Any] = {'ordersource': 'API'}
        values["uid"] = self.username
        values["actid"] = self.accountid
        values["exch"] = exchange
        values["tsym"] = urllib.parse.quote_plus(tradingsymbol)
        values["qty"] = str(quantity)
        values["prd"] = new_product_type
        values["prevprd"] = previous_product_type
        values["trantype"] = buy_or_sell
        values["postype"] = day_or_cf
        
        payload = 'jData=' + json.dumps(values) + f'&jKey={self.susertoken}'
        reportmsg(payload)
        
        res = requests.post(url, data=payload)
        reportmsg(res.text)
        
        resDict = json.loads(res.text)
        if resDict['stat'] != 'Ok':
            return None
        
        return resDict

    def single_order_history(
        self,
        orderno: Union[str, int]
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get history for a single order.
        
        Args:
            orderno: Order number
            
        Returns:
            List of order history records or None on error
        """
        config = self.service_config
        
        url = f"{config['host']}{config['routes']['singleorderhistory']}"
        reportmsg(url)
        
        values: Dict[str, Any] = {'ordersource': 'API'}
        values["uid"] = self.username
        values["norenordno"] = orderno
        
        payload = 'jData=' + json.dumps(values) + f'&jKey={self.susertoken}'
        reportmsg(payload)
        
        res = requests.post(url, data=payload)
        reportmsg(res.text)
        
        resDict = json.loads(res.text)
        if not isinstance(resDict, list):
            return None
        
        return resDict

    def get_order_book(self) -> Optional[List[Dict[str, Any]]]:
        """
        Get order book (all orders).
        
        Returns:
            List of orders or None on error
        """
        config = self.service_config
        
        url = f"{config['host']}{config['routes']['orderbook']}"
        reportmsg(url)
        
        values: Dict[str, Any] = {'ordersource': 'API'}
        values["uid"] = self.username
        
        payload = 'jData=' + json.dumps(values) + f'&jKey={self.susertoken}'
        reportmsg(payload)
        
        res = requests.post(url, data=payload)
        reportmsg(res.text)
        
        resDict = json.loads(res.text)
        if not isinstance(resDict, list):
            return None
        
        return resDict

    def get_trade_book(self) -> Optional[List[Dict[str, Any]]]:
        """
        Get trade book (executed trades).
        
        Returns:
            List of trades or None on error
        """
        config = self.service_config
        
        url = f"{config['host']}{config['routes']['tradebook']}"
        reportmsg(url)
        
        values: Dict[str, Any] = {'ordersource': 'API'}
        values["uid"] = self.username
        values["actid"] = self.accountid
        
        payload = 'jData=' + json.dumps(values) + f'&jKey={self.susertoken}'
        reportmsg(payload)
        
        res = requests.post(url, data=payload)
        reportmsg(res.text)
        
        resDict = json.loads(res.text)
        if not isinstance(resDict, list):
            return None
        
        return resDict

    def searchscrip(
        self,
        exchange: str,
        searchtext: str
    ) -> Optional[Dict[str, Any]]:
        """
        Search for instruments.
        
        Args:
            exchange: Exchange code
            searchtext: Search text
            
        Returns:
            Search results dictionary or None on error
        """
        config = self.service_config
        
        url = f"{config['host']}{config['routes']['searchscrip']}"
        reportmsg(url)
        
        if searchtext is None:
            reporterror('search text cannot be null')
            return None
        
        values: Dict[str, Any] = {}
        values["uid"] = self.username
        values["exch"] = exchange
        values["stext"] = urllib.parse.quote_plus(searchtext)
        
        payload = 'jData=' + json.dumps(values) + f'&jKey={self.susertoken}'
        reportmsg(payload)
        
        res = requests.post(url, data=payload)
        reportmsg(res.text)
        
        resDict = json.loads(res.text)
        if resDict['stat'] != 'Ok':
            return None
        
        return resDict

    def get_option_chain(
        self,
        exchange: str,
        tradingsymbol: str,
        strikeprice: Union[int, float],
        count: int = 2
    ) -> Optional[Dict[str, Any]]:
        """
        Get option chain data.
        
        Args:
            exchange: Exchange code
            tradingsymbol: Trading symbol
            strikeprice: Strike price
            count: Number of strikes on each side
            
        Returns:
            Option chain dictionary or None on error
        """
        config = self.service_config
        
        url = f"{config['host']}{config['routes']['optionchain']}"
        reportmsg(url)
        
        values: Dict[str, Any] = {}
        values["uid"] = self.username
        values["exch"] = exchange
        values["tsym"] = urllib.parse.quote_plus(tradingsymbol)
        values["strprc"] = str(strikeprice)
        values["cnt"] = str(count)
        
        payload = 'jData=' + json.dumps(values) + f'&jKey={self.susertoken}'
        reportmsg(payload)
        
        res = requests.post(url, data=payload)
        reportmsg(res.text)
        
        resDict = json.loads(res.text)
        if resDict['stat'] != 'Ok':
            return None
        
        return resDict

    def get_security_info(
        self,
        exchange: str,
        token: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get security information.
        
        Args:
            exchange: Exchange code
            token: Instrument token
            
        Returns:
            Security info dictionary or None on error
        """
        config = self.service_config
        
        url = f"{config['host']}{config['routes']['scripinfo']}"
        reportmsg(url)
        
        values: Dict[str, Any] = {}
        values["uid"] = self.username
        values["exch"] = exchange
        values["token"] = token
        
        payload = 'jData=' + json.dumps(values) + f'&jKey={self.susertoken}'
        reportmsg(payload)
        
        res = requests.post(url, data=payload)
        reportmsg(res.text)
        
        resDict = json.loads(res.text)
        if resDict['stat'] != 'Ok':
            return None
        
        return resDict

    def get_quotes(
        self,
        exchange: str,
        token: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get quote for an instrument.
        
        Args:
            exchange: Exchange code
            token: Instrument token
            
        Returns:
            Quote dictionary or None on error
        """
        config = self.service_config
        
        url = f"{config['host']}{config['routes']['getquotes']}"
        reportmsg(url)
        
        values: Dict[str, Any] = {}
        values["uid"] = self.username
        values["exch"] = exchange
        values["token"] = token
        
        payload = 'jData=' + json.dumps(values) + f'&jKey={self.susertoken}'
        reportmsg(payload)
        
        res = requests.post(url, data=payload)
        reportmsg(res.text)
        
        resDict = json.loads(res.text)
        if resDict['stat'] != 'Ok':
            return None
        
        return resDict

    def get_time_price_series(
        self,
        exchange: str,
        token: str,
        starttime: Optional[float] = None,
        endtime: Optional[float] = None,
        interval: Optional[int] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get time-price series (candlestick data).
        
        Args:
            exchange: Exchange code
            token: Instrument token
            starttime: Start timestamp (defaults to today 00:00:00)
            endtime: End timestamp
            interval: Interval in minutes (1, 3, 5, 10, 15, 30, 60, 120, 240)
            
        Returns:
            List of candle data or None on error
        """
        config = self.service_config
        
        url = f"{config['host']}{config['routes']['TPSeries']}"
        reportmsg(url)
        
        if starttime is None:
            timestring = time.strftime('%d-%m-%Y') + ' 00:00:00'
            timeobj = time.strptime(timestring, '%d-%m-%Y %H:%M:%S')
            starttime = time.mktime(timeobj)
        
        values: Dict[str, Any] = {'ordersource': 'API'}
        values["uid"] = self.username
        values["exch"] = exchange
        values["token"] = token
        values["st"] = str(starttime)
        
        if endtime is not None:
            values["et"] = str(endtime)
        if interval is not None:
            values["intrv"] = str(interval)
        
        payload = 'jData=' + json.dumps(values) + f'&jKey={self.susertoken}'
        reportmsg(payload)
        
        res = requests.post(url, data=payload)
        reportmsg(res.text)
        
        resDict = json.loads(res.text)
        if not isinstance(resDict, list):
            return None
        
        return resDict

    def get_daily_price_series(
        self,
        exchange: str,
        tradingsymbol: str,
        startdate: Optional[float] = None,
        enddate: Optional[float] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get daily price series (EOD data).
        
        Args:
            exchange: Exchange code
            tradingsymbol: Trading symbol
            startdate: Start date timestamp (defaults to 7 days ago)
            enddate: End date timestamp (defaults to now)
            
        Returns:
            List of daily price data or None on error
        """
        config = self.service_config
        
        url = f"{config['host']}{config['routes']['get_daily_price_series']}"
        reportmsg(url)
        
        if startdate is None:
            week_ago = date.today() - timedelta(days=7)
            startdate = datetime.combine(week_ago, datetime.min.time()).timestamp()
        
        if enddate is None:
            enddate = datetime.now().timestamp()
        
        values: Dict[str, Any] = {}
        values["uid"] = self.username
        values["sym"] = f'{exchange}:{tradingsymbol}'
        values["from"] = str(startdate)
        values["to"] = str(enddate)
        
        payload = 'jData=' + json.dumps(values) + f'&jKey={self.susertoken}'
        reportmsg(payload)
        
        headers = {"Content-Type": "application/json; charset=utf-8"}
        res = requests.post(url, data=payload, headers=headers)
        reportmsg(str(res))
        
        if res.status_code != 200:
            return None
        
        if len(res.text) == 0:
            return None
        
        resDict = json.loads(res.text)
        if not isinstance(resDict, list):
            return None
        
        return resDict

    # def get_holdings(
    #     self,
    #     product_type: Optional[str] = None
    # ) -> Optional[List[Dict[str, Any]]]:
    #     """
    #     Get holdings.
        
    #     Args:
    #         product_type: Product type (defaults to Delivery)
            
    #     Returns:
    #         List of holdings or None on error
    #     """
    #     config = self.service_config
        
    #     url = f"{config['host']}{config['routes']['holdings']}"
    #     reportmsg(url)
        
    #     if product_type is None:
    #         product_type = self.product_type.Delivery
        
    #     values: Dict[str, Any] = {}
    #     values["uid"] = self.username
    #     values["actid"] = self.accountid
    #     values["prd"] = product_type
        
    #     payload = 'jData=' + json.dumps(values) + f'&jKey={self.susertoken}'
    #     reportmsg(payload)
        
    #     res = requests.post(url, data=payload)
    #     reportmsg(res.text)
        
    #     resDict = json.loads(res.text)
    #     if not isinstance(resDict, list):
    #         return None
        
    #     return resDict

    def get_limits(
        self,
        product_type: Optional[str] = None,
        segment: Optional[str] = None,
        exchange: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get account limits.
        
        Args:
            product_type: Product type filter
            segment: Segment filter
            exchange: Exchange filter
            
        Returns:
            Limits dictionary
        """
        config = self.service_config
        
        url = f"{config['host']}{config['routes']['limits']}"
        reportmsg(url)
        
        values: Dict[str, Any] = {}
        values["uid"] = self.username
        values["actid"] = self.accountid
        
        if product_type is not None:
            values["prd"] = product_type
        
        if segment is not None:
            values["seg"] = segment
        
        if exchange is not None:
            values["exch"] = exchange
        
        payload = 'jData=' + json.dumps(values) + f'&jKey={self.susertoken}'
        reportmsg(payload)
        
        res = requests.post(url, data=payload)
        reportmsg(res.text)
        
        resDict = json.loads(res.text)
        return resDict

    def get_positions(self) -> Optional[List[Dict[str, Any]]]:
        """
        Get positions.
        
        Returns:
            List of positions or None on error
        """
        config = self.service_config
        
        url = f"{config['host']}{config['routes']['positions']}"
        reportmsg(url)
        
        values: Dict[str, Any] = {}
        values["uid"] = self.username
        values["actid"] = self.accountid
        
        payload = 'jData=' + json.dumps(values) + f'&jKey={self.susertoken}'
        reportmsg(payload)
        
        res = requests.post(url, data=payload)
        reportmsg(res.text)
        
        resDict = json.loads(res.text)
        if not isinstance(resDict, list):
            return None
        
        return resDict

    def span_calculator(
        self,
        actid: str,
        positions: List[Any]
    ) -> Dict[str, Any]:
        """
        Calculate SPAN margin.
        
        Args:
            actid: Account ID
            positions: List of position objects
            
        Returns:
            SPAN calculation result
        """
        config = self.service_config
        
        url = f"{config['host']}{config['routes']['span_calculator']}"
        reportmsg(url)
        
        senddata: Dict[str, Any] = {}
        senddata['actid'] = self.accountid
        senddata['pos'] = positions
        
        payload = 'jData=' + json.dumps(senddata, default=lambda o: o.encode()) + f'&jKey={self.susertoken}'
        reportmsg(payload)
        
        res = requests.post(url, data=payload)
        reportmsg(res.text)
        
        resDict = json.loads(res.text)
        return resDict

    def option_greek(
        self,
        expiredate: str,
        StrikePrice: Union[int, float],
        SpotPrice: Union[int, float],
        InterestRate: Union[int, float],
        Volatility: Union[int, float],
        OptionType: str
    ) -> Dict[str, Any]:
        """
        Calculate option Greeks.
        
        Args:
            expiredate: Expiry date
            StrikePrice: Strike price
            SpotPrice: Spot price
            InterestRate: Interest rate
            Volatility: Volatility
            OptionType: Option type (CE/PE)
            
        Returns:
            Greeks calculation result
        """
        config = self.service_config
        
        url = f"{config['host']}{config['routes']['option_greek']}"
        reportmsg(url)
        
        values: Dict[str, Any] = {"source": "API"}
        values["actid"] = self.accountid
        values["exd"] = expiredate
        values["strprc"] = StrikePrice
        values["sptprc"] = SpotPrice
        values["int_rate"] = InterestRate
        values["volatility"] = Volatility
        values["optt"] = OptionType
        
        payload = 'jData=' + json.dumps(values) + f'&jKey={self.susertoken}'
        reportmsg(payload)
        
        res = requests.post(url, data=payload)
        reportmsg(res.text)
        
        resDict = json.loads(res.text)
        return resDict

