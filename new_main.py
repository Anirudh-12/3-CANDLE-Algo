
if __name__ == "__main__":
    import multiprocessing as mp
    try:
        import _strptime
    except ImportError:
        pass
    from new_backend import backend_main
    from new_ui import ui_main
    import sys
    import socket
    mp.freeze_support() # Important for PyInstaller/frozen apps
    mp.set_start_method("spawn", force=True)

    # Find an empty port between 5550 and 5559 for ZeroMQ RPC
    selected_port = None
    for port in range(5550, 5560):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                selected_port = port
                break
            except OSError:
                continue
    
    if selected_port is None:
        print("Error: No free ports found between 5550 and 5559.")
        sys.exit(1)

    rpc_address = f"tcp://127.0.0.1:{selected_port}"

    backend = mp.Process(
        target=backend_main,
        args=(rpc_address,)
    )

    ui = mp.Process(
        target=ui_main,
        args=(rpc_address,)
    )

    backend.start()
    ui.start()

    # Wait for UI to exit
    ui.join()

    # UI died -> backend must die
    if backend.is_alive():
        backend.terminate()
        backend.join()

    # print("App exited cleanly")
    
    # Force exit to ensure no lingering threads keep the process alive in memory
    import os
    os._exit(0)
