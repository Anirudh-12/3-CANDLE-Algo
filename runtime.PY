# pyi_rth_realtime.py
import logging
logging.disable(logging.CRITICAL)

import sys
# Commented out so you can actually see terminal logs in your EXE!
sys.stderr = open("nul", "w")
sys.stdout = open("nul", "w")

import ctypes
try:
    ctypes.windll.winmm.timeBeginPeriod(1)
except Exception:
    pass

import os
os.environ.setdefault("PYTHONUNBUFFERED", "1")

# Reduce Windows background throttling hints
try:
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000002)
except Exception:
    pass

# --- Fix SSL for requests/API in PyInstaller ---
import ssl
try:
    import certifi
    os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
    os.environ["SSL_CERT_FILE"] = certifi.where()
    ssl._create_default_https_context = ssl._create_unverified_context
except ImportError:
    pass

# --- Fix threading issue with datetime.strptime in PyInstaller ---
try:
    import _strptime  
except ImportError:
    pass
