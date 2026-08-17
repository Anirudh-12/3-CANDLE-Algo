# main.py
import multiprocessing as mp
from backend import backend_main
from ui import ui_main
import time
import signal

if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)

    ui_to_backend = mp.Queue()
    backend_to_ui = mp.Queue()

    backend = mp.Process(
        target=backend_main,
        args=(ui_to_backend, backend_to_ui)
    )

    ui = mp.Process(
        target=ui_main,
        args=(backend_to_ui, ui_to_backend)
    )

    backend.start()
    ui.start()

    # Wait for UI to exit
    ui.join()

    # UI died → backend must die
    if backend.is_alive():
        backend.terminate()
        backend.join()

    print("App exited cleanly")
