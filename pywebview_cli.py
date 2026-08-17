import sys
import webview

if len(sys.argv) < 4:
    print("Usage: pywebview_cli.py <URL> <width> <height>")
    sys.exit(1)

url = sys.argv[1]
width = int(sys.argv[2])
height = int(sys.argv[3])
window_title = "PyWebView Browser"

webview.create_window(window_title, url, width=width, height=height, on_top=True)
webview.start(gui="edgechromium")
