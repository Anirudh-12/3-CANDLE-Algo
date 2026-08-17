# uibridge.py
import uuid
import time
import threading
import sys

class UIBridge:
    SHUTDOWN = "__shutdown__"

    def __init__(self, in_q, out_q):
        self.in_q = in_q
        self.out_q = out_q

        self.exposed = {}
        self.pending = {}
        self._running = True

    # -----------------------------
    # EEL-LIKE expose decorator
    # -----------------------------
    def expose(self, fn):
        self.exposed[fn.__name__] = fn
        return fn

    # -----------------------------
    # Explicit call
    # -----------------------------
    def call(self, fn_name, *args, **kwargs):
        call_id = str(uuid.uuid4())

        self.out_q.put({
            "type": "call",
            "id": call_id,
            "fn": fn_name,
            "args": args,
            "kwargs": kwargs
        })

        while call_id not in self.pending:
            time.sleep(0.001)

        return self.pending.pop(call_id)

    # -----------------------------
    # bridge.place_order(...)
    # -----------------------------
    def __getattr__(self, name):
        def proxy(*args, **kwargs):
            return self.call(name, *args, **kwargs)
        return proxy

    # -----------------------------
    # Listener loop
    # -----------------------------
    def listen(self):
        while self._running:
            msg = self.in_q.get()

            if msg["type"] == self.SHUTDOWN:
                self._running = False
                self.on_shutdown()
                break

            elif msg["type"] == "call":
                self._handle_call(msg)

            elif msg["type"] == "response":
                self.pending[msg["id"]] = msg["result"]

    def start_listener(self):
        threading.Thread(target=self.listen, daemon=True).start()

    # -----------------------------
    # Execute exposed function
    # -----------------------------
    def _handle_call(self, msg):
        fn = msg["fn"]
        call_id = msg["id"]

        try:
            if fn not in self.exposed:
                raise Exception(f"Function '{fn}' not exposed")
            result = self.exposed[fn](*msg["args"], **msg["kwargs"])
        except Exception as e:
            result = {"error": str(e)}

        self.out_q.put({
            "type": "response",
            "id": call_id,
            "result": result
        })

    # -----------------------------
    # SHUTDOWN API
    # -----------------------------
    def shutdown(self):
        self.out_q.put({"type": self.SHUTDOWN})

    def on_shutdown(self):
        """Override if needed"""
        pass
