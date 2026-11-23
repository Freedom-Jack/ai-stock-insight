"""Opt-in integration test on a signed-in Windows desktop with Explorer running."""

import ctypes
import http.client
import os
import socket
import tempfile
import time
import unittest
from base64 import b64encode
from contextlib import closing
from ctypes import wintypes
from pathlib import Path

from stockinsight import launcher


def icon_rect(hwnd, icon_id):
    class Identifier(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("hwnd", wintypes.HWND),
                    ("id", wintypes.UINT), ("guid", ctypes.c_byte * 16)]

    ident = Identifier(ctypes.sizeof(Identifier), hwnd, icon_id)
    bounds = wintypes.RECT()
    query = ctypes.windll.shell32.Shell_NotifyIconGetRect
    query.argtypes = [ctypes.POINTER(Identifier), ctypes.POINTER(wintypes.RECT)]
    query.restype = ctypes.c_long
    if query(ctypes.byref(ident), ctypes.byref(bounds)) >= 0:
        return (bounds.left, bounds.top, bounds.right, bounds.bottom)
    return None


@unittest.skipUnless(os.name == "nt" and os.getenv("STOCKINSIGHT_TEST_TRAY") == "1",
                     "requires a signed-in Windows desktop and STOCKINSIGHT_TEST_TRAY=1")
class WindowsTrayTest(unittest.TestCase):
    def test_icon_owned_by_listener_duplicate_launch_and_graceful_menu_exit(self):
        import win32api
        import win32con
        import win32event
        import win32gui
        import win32process
        from stockinsight import windows_tray as tray

        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            folder = root / "personal"
            session = launcher.start_tray_desk(folder, port)
            hwnd = win32gui.FindWindow(tray.WINDOW_CLASS, f"Stock Insight · {port}")
            self.assertEqual(win32process.GetWindowThreadProcessId(hwnd)[1], session["pid"])
            with closing(win32api.OpenProcess(win32con.SYNCHRONIZE, False, session["pid"])) as process:
                try:
                    for attempt in range(30):
                        bounds = icon_rect(hwnd, tray.ICON_ID)
                        if bounds and bounds[2] > bounds[0] and bounds[3] > bounds[1]:
                            break
                        time.sleep(.1)
                    else:
                        self.fail(f"Explorer did not report a tray icon rectangle: {bounds}")
                    self.assertEqual(launcher.main(["--root", scratch, "--port", str(port), "--background"]), 0)
                    self.assertEqual(launcher.existing_session(folder, port)["pid"], session["pid"])
                    auth = b64encode(("research:" + session["password"]).encode()).decode()
                    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=8)) as client:
                        client.request("GET", "/status", headers={"Authorization": "Basic " + auth})
                        response = client.getresponse()
                        self.assertEqual(response.status, 200)
                        self.assertNotIn(b"/actions/delivery-test", response.read())
                finally:
                    win32gui.PostMessage(hwnd, win32con.WM_COMMAND, tray.EXIT, 0)
                    self.assertEqual(win32event.WaitForSingleObject(process, 30000), win32event.WAIT_OBJECT_0)
            self.assertIsNone(launcher.existing_session(folder, port))
            self.assertFalse(win32gui.IsWindow(hwnd))
            with socket.socket() as other:
                self.assertNotEqual(other.connect_ex(("127.0.0.1", port)), 0)
