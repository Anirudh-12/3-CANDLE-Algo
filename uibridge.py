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
        # print(f"[UIBRIDGE] Init. In_Q: {id(self.in_q)}, Out_Q: {id(self.out_q)}")

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
    # Explicit call (Blocking)
    # -----------------------------
    def call(self, fn_name, *args, **kwargs):
        call_id = str(uuid.uuid4())
        # print(f"[UIBRIDGE] Sending CALL: {fn_name} (ID: {call_id})")

        self.out_q.put({
            "type": "call",
            "id": call_id,
            "fn": fn_name,
            "args": args,
            "kwargs": kwargs
        })

        while call_id not in self.pending:
            time.sleep(0.001)

        result = self.pending.pop(call_id)
        # print(f"[UIBRIDGE] Received RESPONSE for: {fn_name} (ID: {call_id})")
        return result

    # -----------------------------
    # Notification (Non-blocking)
    # -----------------------------
    def notify(self, fn_name, *args, **kwargs):
        # print(f"[UIBRIDGE] Sending NOTIFY: {fn_name}")
        self.out_q.put({
            "type": "notify",
            "fn": fn_name,
            "args": args,
            "kwargs": kwargs
        })

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
        # print(f"[UIBRIDGE] Listener Loop Started. Reading from Q: {id(self.in_q)}")
        try:
            while self._running:
                try:
                    msg = self.in_q.get(timeout=2.0)
                except Exception: # Empty queue
                    # print(f"[UIBRIDGE] Listener Idle on Q: {id(self.in_q)}")
                    continue
                
                # print(f"[UIBRIDGE] Received MSG type: {msg.get('type')} fn: {msg.get('fn')}")

                if msg["type"] == self.SHUTDOWN:
                    # print("[UIBRIDGE] Received SHUTDOWN")
                    self._running = False
                    self.on_shutdown()
                    break

                elif msg["type"] == "call":
                    # print(f"[UIBRIDGE] Handling CALL: {msg['fn']}")
                    self._handle_call(msg)

                elif msg["type"] == "notify":
                    # print(f"[UIBRIDGE] Handling NOTIFY: {msg['fn']}")
                    self._handle_notify(msg)

                elif msg["type"] == "response":
                    # print(f"[UIBRIDGE] Handling RESPONSE for ID: {msg.get('id')}")
                    self.pending[msg["id"]] = msg["result"]
        except Exception as e:
            # print(f"[UIBRIDGE] LISTENER MSG LOOP CRASHED: {e}")
            import traceback
            traceback.print_exc()

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

    def _handle_notify(self, msg):
        fn = msg["fn"]
        # No ID, no response needed
        try:
            if fn in self.exposed:
                 self.exposed[fn](*msg["args"], **msg["kwargs"])
            else:
                pass
                #  print(f"[UIBRIDGE] ERROR: Function '{fn}' not exposed")
        except Exception as e:
            # print(f"[UIBRIDGE] ERROR handling notification '{fn}': {e}")
            import traceback
            traceback.print_exc()

    # -----------------------------
    # SHUTDOWN API
    # -----------------------------
    def shutdown(self):
        self.out_q.put({"type": self.SHUTDOWN})

    def on_shutdown(self):
        """Override if needed"""
        pass
