# backend.py
from uibridge import UIBridge
import sys
import time

def backend_main(ui_to_backend, backend_to_ui):
    bridge = UIBridge(ui_to_backend, backend_to_ui)

    @bridge.expose
    def place_order(symbol, qty):
        print(f"[BACKEND] Order: {symbol} x {qty}")
        return "OK"

    def shutdown_backend():
        print("[BACKEND] UI closed → shutting down backend")
        sys.exit(0)

    bridge.on_shutdown = shutdown_backend
    bridge.start_listener()

    print("[BACKEND] Ready")
    while True:
        time.sleep(1)
