"""Opt-in integration test on a signed-in Windows desktop with Explorer running."""

import ctypes
import http.client
import os
import socket
import subprocess
import sys
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
    def assert_no_console(self, pid):
        # A detached probe can distinguish a windowless process from a hidden console.
        probe = (
            "import ctypes,sys; k=ctypes.WinDLL('kernel32',use_last_error=True); "
            "assert not k.GetConsoleWindow(); "
            "attached=k.AttachConsole(int(sys.argv[1])); "
            "sys.exit(0 if not attached and ctypes.get_last_error()==6 else 1)"
        )
        result = subprocess.run([str(Path(sys.base_prefix) / "python.exe"), "-I", "-c", probe, str(pid)],
                                creationflags=subprocess.DETACHED_PROCESS, timeout=10)
        self.assertEqual(result.returncode, 0, "tray worker is attached to a console")

    def test_signin_shortcut_survives_closing_its_invoking_terminal(self):
        import win32con
        import win32gui
        import win32process
        from win32com.client import Dispatch
        from stockinsight import windows_tray as tray

        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="stock insight ") as scratch:
            root = Path(scratch)
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            link = Dispatch("WScript.Shell").CreateShortcut(str(root / "Stock Insight.lnk"))
            link.TargetPath = str(Path(sys.base_prefix) / "pythonw.exe")
            link.Arguments = subprocess.list2cmdline(["-I", "-B", str(project / "ops/windows/start-tray.pyw"),
                                                       "--root", scratch, "--port", str(port)])
            link.WorkingDirectory = str(project)
            link.Save()
            # Allocate a private console for this test. Only close the handle after
            # its sole attached process identifies itself as the helper we spawned.
            helper = """
import ctypes, os, sys, time
kernel = ctypes.windll.kernel32
kernel.GetConsoleWindow.restype = ctypes.c_void_p
pids = (ctypes.c_ulong * 8)()
assert kernel.GetConsoleProcessList(pids, len(pids)) == 1 and pids[0] == os.getpid()
print(kernel.GetConsoleWindow(), flush=True)
os.startfile(sys.argv[1])
time.sleep(100)
"""
            startup = subprocess.STARTUPINFO()
            startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            with subprocess.Popen([str(Path(sys.base_prefix) / "python.exe"), "-I", "-c", helper,
                                   str(root / "Stock Insight.lnk")], creationflags=subprocess.CREATE_NEW_CONSOLE,
                                  startupinfo=startup, stdout=subprocess.PIPE, text=True) as terminal:
                hwnd = None
                try:
                    console = int(terminal.stdout.readline())
                    for _ in range(200):
                        session = launcher.existing_session(root / "personal", port)
                        if session:
                            break
                        time.sleep(.1)
                    self.assertIsNotNone(session, "sign-in shortcut did not start a desk")
                    hwnd = win32gui.FindWindow(tray.WINDOW_CLASS, f"Stock Insight · {port}")
                    self.assertEqual(win32process.GetWindowThreadProcessId(hwnd)[1], session["pid"])
                    self.assert_no_console(session["pid"])
                    win32gui.PostMessage(console, win32con.WM_CLOSE, 0, 0)
                    terminal.wait(timeout=15)
                    self.assertEqual(launcher.existing_session(root / "personal", port)["pid"], session["pid"])
                    self.assertTrue(icon_rect(hwnd, tray.ICON_ID))
                    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as client:
                        client.request("GET", "/today")
                        self.assertEqual(client.getresponse().status, 401)
                finally:
                    if terminal.poll() is None:
                        terminal.terminate()
                    if hwnd and win32gui.IsWindow(hwnd):
                        win32gui.PostMessage(hwnd, win32con.WM_COMMAND, tray.EXIT, 0)
                        for _ in range(150):
                            if not win32gui.IsWindow(hwnd):
                                break
                            time.sleep(.1)

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
                    self.assert_no_console(session["pid"])
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
