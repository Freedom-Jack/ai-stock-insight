"""The personal desk's Windows notification-area icon, owned by the server process."""

import threading
import time
import webbrowser
from concurrent.futures import Future
from contextlib import contextmanager, suppress
from pathlib import Path

import win32api
import win32con as con
import win32gui as gui


WINDOW_CLASS = "StockInsight.Tray"
ICON_ID = 1
CALLBACK = con.WM_APP + 1
OPEN, LOGIN, EXIT = 1, 2, 3


def _message_loop(port, code, request_stop, ready):
    title = f"Stock Insight · {port}"
    url = f"http://127.0.0.1:{port}/today"
    instance = win32api.GetModuleHandle(None)
    hwnd = icon = menu = None
    registered = False

    def add_icon():
        flags = gui.NIF_ICON | gui.NIF_MESSAGE | gui.NIF_TIP
        # Explorer can still be starting when the sign-in shortcut runs.
        for attempt in range(30):
            try:
                gui.Shell_NotifyIcon(gui.NIM_ADD, (hwnd, ICON_ID, flags, CALLBACK, icon, "Stock Insight · 运行中"))
                return
            except gui.error:
                if attempt == 29:
                    raise
                time.sleep(1)

    def restart(window, message, wparam, lparam):
        try:
            add_icon()
        except gui.error:
            request_stop()
        return 0

    def command(window, message, wparam, lparam):
        choice = win32api.LOWORD(wparam)
        if choice == EXIT:
            request_stop()
        elif choice == OPEN:
            webbrowser.open(url)
        elif choice == LOGIN:
            gui.MessageBox(window, f"用户名  research\n密码  {code}", "Stock Insight · 工作台登录信息", con.MB_OK)
        return 0

    def click(window, message, wparam, lparam):
        if lparam == con.WM_LBUTTONUP:
            command(window, message, OPEN, 0)
        elif lparam in (con.WM_RBUTTONUP, con.WM_CONTEXTMENU):
            x, y = gui.GetCursorPos()
            gui.SetForegroundWindow(window)
            gui.TrackPopupMenu(menu, con.TPM_RIGHTBUTTON, x, y, 0, window, None)
            gui.PostMessage(window, con.WM_NULL, 0, 0)
        return 0

    def destroyed(window, message, wparam, lparam):
        with suppress(gui.error):
            gui.Shell_NotifyIcon(gui.NIM_DELETE, (window, ICON_ID))
        gui.PostQuitMessage(0)
        return 0

    try:
        wc = gui.WNDCLASS()
        wc.hInstance = instance
        wc.lpszClassName = WINDOW_CLASS
        wc.lpfnWndProc = {gui.RegisterWindowMessage("TaskbarCreated"): restart, CALLBACK: click,
                          con.WM_COMMAND: command, con.WM_DESTROY: destroyed}
        gui.RegisterClass(wc)
        registered = True
        hwnd = gui.CreateWindow(WINDOW_CLASS, title, 0, 0, 0, 0, 0, 0, 0, instance, None)
        icon = gui.LoadImage(0, str(Path(__file__).with_name("stock-insight.ico")), con.IMAGE_ICON,
                             win32api.GetSystemMetrics(con.SM_CXSMICON), win32api.GetSystemMetrics(con.SM_CYSMICON),
                             con.LR_LOADFROMFILE)
        menu = gui.CreatePopupMenu()
        gui.AppendMenu(menu, con.MF_STRING, OPEN, "打开工作台")
        gui.AppendMenu(menu, con.MF_STRING, LOGIN, "查看登录信息")
        gui.AppendMenu(menu, con.MF_SEPARATOR, 0, "")
        gui.AppendMenu(menu, con.MF_STRING, EXIT, "退出 Stock Insight")
        add_icon()
        ready.set_result(hwnd)
        gui.PumpMessages()
    except Exception as exc:
        if not ready.done():
            ready.set_exception(exc)
    finally:
        request_stop()
        if hwnd and gui.IsWindow(hwnd):
            gui.DestroyWindow(hwnd)
        if menu:
            gui.DestroyMenu(menu)
        if icon:
            gui.DestroyIcon(icon)
        if registered:
            gui.UnregisterClass(WINDOW_CLASS, instance)


@contextmanager
def running(port, code, request_stop):
    ready = Future()
    thread = threading.Thread(target=_message_loop, args=(port, code, request_stop, ready), name="Stock Insight tray")
    thread.start()
    try:
        hwnd = ready.result()
        yield hwnd
    finally:
        if ready.done() and not ready.exception() and gui.IsWindow(ready.result()):
            gui.PostMessage(ready.result(), con.WM_CLOSE, 0, 0)
        thread.join()
