
import threading
import uuid
import time
import zmq
import os
class RpcHandler:
    """
    Bidirectional RPC handler using ZeroMQ (DEALER-DEALER pattern).
    Allows exposing functions via @rpc.expose and calling remote functions via rpc.remote_func().
    """
    def __init__(self, address, role, name="RPC"):
        """
        address: str, e.g., "tcp://127.0.0.1:5555"
        role: str, "server" (bind) or "client" (connect)
        """
        self.address = address
        self.role = role
        self.name = name
        self.exposed = {}
        self.pending_results = {}
        self.running = True
        # self.logger = logging.getLogger(f"RPC.{name}")
        # if not self.logger.handlers:
        #     ch = logging.StreamHandler()
        #     ch.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        #     self.logger.addHandler(ch)
        #     self.logger.setLevel(logging.CRITICAL)

        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.DEALER)
        # Set linger to 0 to avoid hanging on close if peers are gone
        self.socket.setsockopt(zmq.LINGER, 0)
        
        if self.role == "server":
            self.socket.bind(self.address)
            # self.logger.info(f"Bound to {self.address}")
        else:
            self.socket.connect(self.address)
            # self.logger.info(f"Connected to {self.address}")

        self._lock = threading.Lock() # For pending_results map
        self._send_lock = threading.Lock() # For socket access (socket is not thread safe)

    def expose(self, func_or_name=None):
        """
        Decorator to expose a function.
        Usage:
        @rpc.expose
        def my_func(): ...
        
        Or:
        @rpc.expose("alias")
        def my_func(): ...
        """
        def decorator(func):
            name = func.__name__
            if isinstance(func_or_name, str):
                name = func_or_name
            self.exposed[name] = func
            return func

        if callable(func_or_name):
            name = func_or_name.__name__
            self.exposed[name] = func_or_name
            return func_or_name
        
        return decorator

    def start(self):
        """Start the listener thread"""
        t = threading.Thread(target=self._listen_loop, daemon=True, name=f"RpcListener-{self.name}")
        t.start()

    def _listen_loop(self):
        # self.logger.info("Listener started.")
        while self.running:
            try:
                # Poll with timeout to allow checking self.running
                if self.socket.poll(500):
                    msg = self.socket.recv_pyobj()
                else:
                    continue
            except zmq.ZMQError as e:
                # self.logger.error(f"ZMQ Error: {e}")
                if not self.running: break
                continue
            except Exception as e:
                # self.logger.error(f"Queue get error: {e}")
                continue

            try:
                mtype = msg.get('type')
                if mtype == 'call':
                    # Process in a separate thread to avoid blocking the listener
                    threading.Thread(target=self._handle_call, args=(msg,), daemon=True).start()
                elif mtype == 'return':
                    self._handle_return(msg)
                elif mtype == 'shutdown':
                    self.running = False
                    self.on_shutdown()
                    break
            except Exception as e:
                # self.logger.error(f"Error processing message: {e}")
                pass

    def _handle_call(self, msg):
        call_id = msg.get('id')
        func_name = msg.get('func')
        args = msg.get('args', [])
        kwargs = msg.get('kwargs', {})

        response = {
            'type': 'return',
            'id': call_id,
            'status': 'error',
            'result': None
        }

        if func_name in self.exposed:
            try:
                func = self.exposed[func_name]
                res = func(*args, **kwargs)
                response['status'] = 'ok'
                response['result'] = res
            except Exception as e:
                # self.logger.error(f"Error executing {func_name}: {e}")
                response['result'] = str(e)
                os._exit(1)
        else:
            msg_err = f"Function '{func_name}' not found on {self.name}"
            # self.logger.warning(msg_err)
            response['result'] = msg_err

        # Send response if it was a call (has ID)
        if call_id:
            try:
                with self._send_lock:
                    self.socket.send_pyobj(response)
            except Exception as e:
                # self.logger.error(f"Failed to send response: {e}")
                pass

    def _handle_return(self, msg):
        call_id = msg.get('id')
        with self._lock:
            if call_id in self.pending_results:
                self.pending_results[call_id] = msg

    def __getattr__(self, name):
        """
        Dynamically handle remote function calls.
        rpc.my_remote_func(arg1, arg2)
        """
        def proxy(*args, **kwargs):
            return self.call(name, *args, **kwargs)
        return proxy

    def call(self, func_name, *args, **kwargs):
        """
        Blocking call to remote function.
        Returns the result or raises Exception on error.
        """
        call_id = str(uuid.uuid4())
        msg = {
            'type': 'call',
            'id': call_id,
            'func': func_name,
            'args': args,
            'kwargs': kwargs
        }

        with self._lock:
            self.pending_results[call_id] = None # Marker that we are waiting

        try:
            with self._send_lock:
                self.socket.send_pyobj(msg)
        except Exception as e:
            with self._lock:
                del self.pending_results[call_id]
            raise e

        # Wait for result
        while True:
            with self._lock:
                res = self.pending_results.get(call_id)
                if res is not None:
                    del self.pending_results[call_id]
                    if res['status'] == 'ok':
                        return res['result']
                    else:
                        raise Exception(f"RPC Error: {res['result']}")
            
            # If shutdown
            if not self.running:
                raise Exception("RPC Shutdown")
            
            time.sleep(0.005) # fast poll

    def notify(self, func_name, *args, **kwargs):
        """
        Fire-and-forget call (no return value expected).
        """
        msg = {
            'type': 'call',
            'id': None, # No ID means no return expected
            'func': func_name,
            'args': args,
            'kwargs': kwargs
        }
        with self._send_lock:
            self.socket.send_pyobj(msg)

    def on_shutdown(self):
        pass

    def shutdown(self):
        self.running = False
        try:
            with self._send_lock:
                self.socket.send_pyobj({'type': 'shutdown'})
        except:
            pass
        finally:
             if self.socket:
                 self.socket.close()
             if self.context:
                 self.context.term()
