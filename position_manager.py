from typing import List, Dict,Tuple
# from logging import ####logger
from NorenRestApiPy.NorenApi import NorenApi
####logger = ####logger(__name__)
####logger.addHandler(file_handler)
####logger.setLevel(logging.INFO)
import time
import threading
class PositionManager:
    def __init__(self,apis:Tuple[NorenApi]):
        # symbol -> position
        # {
        #   "tsym": str,
        #   "netqty": int,
        #   "netavgprc": float,
        #   "lp": float,
        #   "rpnl": float,
        #   "urmtom": float,
        # }
        self.api = apis[-1]
        self.apis = apis
        self._positions: Dict[str, Dict] = {}
        positions = self.api.get_positions()
        if positions:
            if isinstance(positions, list):
                for position in positions:
                    ####logger.info(f"Position: {position}, type_position: {type(position)}")
                    sanitized_pos = self._sanitize_position_data(position)
                    tsym = sanitized_pos['tsym']
                    self._positions[tsym] = sanitized_pos
        
        
        # order book
        self._order_book: List[Dict] = []
        self._next_order_id: int = 1
        self.is_virtual = False
        # symbol -> latest ltp
        self._ltp_map: Dict[str, float] = {}
        self.lock = threading.Lock()

    # ---------- PUBLIC API ----------

    def place_order(
        self,
        tradingsymbol: str,
        quantity: int,
        buy_or_sell: str,      # "B" or "S"
        exchange: str = "NFO",
        product_type: str = "M",
        discloseqty: int = 0,
        price_type: str = "MKT",
        status: str = "FILLED",
        price=0,
        trigger_price=None,
                retention='DAY',
                remarks='Breakout_CE'
    ) -> Dict:
        """
        Order price = LTP at the time of order (from self._ltp_map).

        You MUST have called update_ltp(tradingsymbol, ltp) at least once
        before placing the first order in that symbol.
        """
        with self.lock:
            if tradingsymbol not in self._ltp_map:
                raise ValueError(
                    f"LTP not available for {tradingsymbol}. "
                    f"Call update_ltp('{tradingsymbol}', ltp) before placing orders."
                )

            tsym = tradingsymbol
            qty = abs(int(quantity))
            trantype = "Buy" if buy_or_sell.upper() == "B" else "Sell"
            # price = float(self._ltp_map[tsym])  # fill price = current LTP

            # Create order id
            order_id = str(self._next_order_id)
            self._next_order_id += 1

            pos_order = {
                "norenordno": order_id,
                "tsym": tsym,
                "trantype": trantype,
                "status": status,

                # extra info (not returned in get_order_book but kept internally)
                "exchange": exchange,
                "product_type": product_type,
                "discloseqty": discloseqty,
                "price_type": price_type,
                "qty": qty,
                "price": price,
            }
            self._order_book.append(pos_order)

            # Update positions only if filled
            if status.upper() == "FILLED":
                if self.is_virtual:
                    price = float(self._ltp_map[tsym])
                    order = {
                        "norenordno": order_id,
                        "tsym": tsym,
                        "trantype": trantype,
                        "status": status,
                        "price": price,
                        "stat":"Ok"
                    }
                    order_status = "FILLED"
                    self._apply_fill(tsym, qty, price, trantype)
                else:
                    # price = float(self._ltp_map[tsym])
                    for api in self.apis:
                        # time_now = time.time()
                        order = api.place_order(tradingsymbol=tradingsymbol,quantity=quantity,buy_or_sell=buy_or_sell,exchange=exchange,product_type=product_type,discloseqty=discloseqty,price_type=price_type,price=0,trigger_price=trigger_price,retention=retention,remarks=remarks)
                        # time_after_order = time.time()
                        # time_taken = time_after_order - time_now
                        # ####logger.info(f"Time taken to place order: {time_taken}")
                    #####logger.info(f"Order placed: {order}")
                    order_id = order['norenordno']
                    order_history = api.single_order_history(order_id)[0]
                    ####logger.info(f"Order history: {order_history}")
                    try:
                        order_status = order_history.get('status','REJECTED')
                        price = float(order_history.get('flprc',order_history.get('avgprc',self._ltp_map[tsym])))
                    except:
                        order_status = 'REJECTED'
                        price = 0
                        price = float(self._ltp_map[tsym])
                    
                    if order_status.upper() != "REJECTED":
                        self._apply_fill(tsym, qty, price, trantype)
                    else:
                        price = float(self._ltp_map[tsym])
                        self._apply_fill(tsym, qty, price, trantype)
                    
                
                
                # API return shape you asked for
                return {
                    "norenordno": order["norenordno"],
                    "status": order_status,
                "stat":order['stat'],
                "price":price
                }
        return {
                "norenordno": order["norenordno"],
                "status": order_status,
            "stat":order['stat'],
            "price":price
            }
    def get_order_book(self) -> List[Dict]:
        """
        Returns list[dict] with keys:
        - "norenordno", "tsym", "trantype", "status"
        """
        return [
            {
                "norenordno": o["norenordno"],
                "tsym": o["tsym"],
                "trantype": o["trantype"],
                "status": o["status"],
            }
            for o in self._order_book
        ]

    def get_positions(self) -> List[Dict]:
        """
        Returns list[dict] with keys:
        - "tsym", "urmtom", "rpnl", "netqty", "netavgprc", "lp"
        """
        ####logger.info(f"Positions: {self._positions}mtype_positions:{type(self._positions)}")
        positions: List[Dict] = []
        for tsym, pos in self._positions.items():
            netqty = pos["netqty"]
            avg = pos["netavgprc"]
            lp = pos["lp"]
            ur = pos["urmtom"]
            

            positions.append(
                {
                    "tsym": tsym,
                    "urmtom": float(ur),
                    "rpnl": float(pos["rpnl"]),
                    "netqty": int(netqty),
                    "netavgprc": float(avg),
                    "lp": float(lp),
                }
            )
            ####logger.info(f"Positions: {positions}mtype_positions:{type(positions)}")
        return positions

    def update_ltp(self, tsym: str, ltp: float) -> None:
        """
        Update LTP for a symbol.
        - Stores symbol->ltp in _ltp_map
        - If a position exists, update its lp and urmtom
        """
        try:
            ltp = float(ltp)
            self._ltp_map[tsym] = ltp

            pos = self._positions.get(tsym)
            if not pos:
                # No open position yet, nothing more to do
                return

            pos["lp"] = ltp

            # Use .get() with defaults to handle broker API positions that may have different keys
            netqty = pos.get("netqty", pos.get("qty", 0))
            avg = pos.get("netavgprc", pos.get("avgprc", pos.get("davgprc", 0.0)))
            
            # Ensure numeric types
            netqty = int(netqty) if netqty else 0
            avg = float(avg) if avg else 0.0

            if netqty == 0:
                pos["urmtom"] = 0.0
            else:
                pos["urmtom"] = (ltp - avg) * netqty
        except Exception as e:
            pass
            ####logger.error(f"Error in update_ltp for {tsym}: {e}")

    def _sanitize_position_data(self, pos: Dict) -> Dict:
        """Ensure all numeric fields are correctly typed."""
        sanitized = pos.copy()
        try:
            # Net Quantity
            qty = pos.get('netqty', pos.get('qty', 0))
            sanitized['netqty'] = int(float(qty)) if qty else 0
            
            # Average Price
            avg = pos.get('netavgprc', pos.get('avgprc', pos.get('davgprc', 0.0)))
            sanitized['netavgprc'] = float(avg) if avg else 0.0
            
            # Last Price
            lp = pos.get('lp', 0.0)
            sanitized['lp'] = float(lp) if lp else 0.0
            
            # Realized PNL
            rpnl = pos.get('rpnl', 0.0)
            sanitized['rpnl'] = float(rpnl) if rpnl else 0.0
            
            # Unrealized MTM
            ur = pos.get('urmtom', 0.0)
            sanitized['urmtom'] = float(ur) if ur else 0.0
            
        except (ValueError, TypeError) as e:
            ####logger.error(f"Error sanitizing position data for {pos.get('tsym')}: {e}")
            pass
        return sanitized

    # ---------- INTERNAL HELPERS ----------
    def toggle_virtual(self):
        self.is_virtual = not self.is_virtual
        if self.is_virtual:
            self._positions = {}
        else:
            positions = self.api.get_positions()
            if positions and isinstance(positions, list):
                for position in positions:
                    ####logger.info(f"Position: {position}, type_position: {type(position)}")
                    sanitized_pos = self._sanitize_position_data(position)
                    tsym = sanitized_pos['tsym']
                    self._positions[tsym] = sanitized_pos
            

    def _get_or_init_position(self, tsym: str) -> Dict:
        if tsym not in self._positions:
            self._positions[tsym] = {
                "tsym": tsym,
                "netqty": 0,
                "netavgprc": 0.0,
                "lp": self._ltp_map.get(tsym, 0.0),
                "rpnl": 0.0,
                "urmtom": 0.0,
            }
        return self._positions[tsym]

    def _apply_fill(self, tsym: str, qty: int, price: float, trantype: str) -> None:
        """
        Update positions for a fully filled order.
        Handles:
        - open new position
        - add to same-side
        - partial/fully close
        - flip (long <-> short)
        """
        pos = self._get_or_init_position(tsym)

        side_mult = 1 if trantype == "Buy" else -1
        trade_qty = side_mult * qty  # signed

        # Ensure numeric types for old values from position dict
        old_netqty = int(float(pos.get("netqty", 0)))
        old_avg = float(pos.get("netavgprc", 0.0))
        old_rpnl = float(pos.get("rpnl", 0.0))

        if old_netqty == 0:
            # New position
            new_netqty = trade_qty
            new_avg = price
            new_rpnl = old_rpnl
        else:
            same_dir = (old_netqty > 0 and trade_qty > 0) or (old_netqty < 0 and trade_qty < 0)

            if same_dir:
                # Increase existing long/short
                new_netqty = old_netqty + trade_qty
                total_qty = abs(old_netqty) + abs(trade_qty)
                new_avg = (old_avg * abs(old_netqty) + price * abs(trade_qty)) / total_qty
                new_rpnl = old_rpnl
            else:
                # Closing or flipping
                close_qty = min(abs(old_netqty), abs(trade_qty))

                if old_netqty > 0:
                    # closing long
                    pnl_close = (price - old_avg) * close_qty
                else:
                    # closing short
                    pnl_close = (old_avg - price) * close_qty

                new_rpnl = old_rpnl + pnl_close
                new_netqty = old_netqty + trade_qty

                if new_netqty == 0:
                    # fully closed
                    new_avg = 0.0
                else:
                    # flipped or partially closed
                    if abs(trade_qty) > abs(old_netqty):
                        # flipped: remaining side opens at current price
                        new_avg = price
                    else:
                        # still same side, keep old avg
                        new_avg = old_avg

        pos["netqty"] = new_netqty
        pos["netavgprc"] = new_avg
        pos["lp"] = price
        pos["rpnl"] = new_rpnl

        # keep urmtom consistent for this symbol
        if new_netqty == 0:
            pos["urmtom"] = 0.0
        else:
            pos["urmtom"] = (pos["lp"] - pos["netavgprc"]) * new_netqty
# if __name__ == "__main__":
#     pm = PositionManager()
#     sym = "NIFTY24DEC24000CE"

#     # 1) feed initial LTP
#     pm.update_ltp(sym, 100.0)

#     # 2) place a Buy at LTP=100
#     pm.place_order(
#         tradingsymbol=sym,
#         quantity=50,
#         buy_or_sell="B",
#         exchange="NFO",
#         product_type="M",
#         discloseqty=0,
#         price_type="MKT",
#     )

#     #     print(pm.get_positions())

#     # 3) market moves to 110
#     pm.update_ltp(sym, 110.0)

#     #     print(pm.get_positions())

#     # 4) market moves down to 90
#     pm.update_ltp(sym, 90.0)

#     #     print(pm.get_positions())
