"""Show one fenced private notice in the current Windows user's interactive desktop."""

from __future__ import annotations

import ctypes
import os
import sqlite3
import sys
import webbrowser
from contextlib import closing
from ctypes import wintypes
from pathlib import Path

from . import delivery
from .db import now, write


def _function(dll, name, restype, *args):
    fn = getattr(dll, name)
    fn.restype = restype
    fn.argtypes = list(args)
    return fn


def _desktop():
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = wintypes.HANDLE
    dword = wintypes.DWORD
    current_thread = _function(kernel, "GetCurrentThreadId", dword)()
    current = _function(user, "GetThreadDesktop", handle, dword)(current_thread)
    input_desktop = _function(
        user, "OpenInputDesktop", handle, dword, wintypes.BOOL, dword
    )(0, False, 1)
    if not current or not input_desktop:
        return False
    try:
        info = _function(
            user,
            "GetUserObjectInformationW",
            wintypes.BOOL,
            handle,
            ctypes.c_int,
            wintypes.LPVOID,
            dword,
            ctypes.POINTER(dword),
        )

        def name(h):
            buf = ctypes.create_unicode_buffer(256)
            size = dword()
            return (
                buf.value
                if info(h, 2, buf, ctypes.sizeof(buf), ctypes.byref(size))
                else ""
            )

        station = _function(user, "GetProcessWindowStation", handle)()
        return (
            name(station).lower() == "winsta0"
            and name(current).lower() == name(input_desktop).lower() == "default"
        )
    finally:
        _function(user, "CloseDesktop", wintypes.BOOL, handle)(input_desktop)


def observe(hwnd, expected_pid):
    """Confirm own mapped window, current desktop, bounds and unobscured centre point."""
    if os.name != "nt" or not _desktop():
        return None
    api = ctypes.WinDLL("user32", use_last_error=True)
    root = _function(api, "GetAncestor", wintypes.HWND, wintypes.HWND, wintypes.UINT)
    hwnd = root(hwnd, 2)
    pid = wintypes.DWORD()
    _function(
        api,
        "GetWindowThreadProcessId",
        wintypes.DWORD,
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    )(hwnd, ctypes.byref(pid))
    rect = wintypes.RECT()
    if (
        not hwnd
        or pid.value != expected_pid
        or not _function(api, "IsWindowVisible", wintypes.BOOL, wintypes.HWND)(hwnd)
        or not _function(
            api,
            "GetWindowRect",
            wintypes.BOOL,
            wintypes.HWND,
            ctypes.POINTER(wintypes.RECT),
        )(hwnd, ctypes.byref(rect))
    ):
        return None
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width < 100 or height < 60:
        return None
    point = wintypes.POINT(rect.left + width // 2, rect.top + height // 2)
    hit = _function(api, "WindowFromPoint", wintypes.HWND, wintypes.POINT)(point)
    if not hit or root(hit, 2) != hwnd:
        return None
    return {
        "channel": "windows_user_session",
        "hwnd": hwnd,
        "pid": expected_pid,
        "width": width,
        "height": height,
        "input_desktop": True,
        "centre_visible": True,
    }


def show(path, attempt, port):
    import tkinter as tk
    from tkinter import ttk

    # URI mode=rw prevents accidental creation of an empty database after a move.
    with closing(
        sqlite3.connect(
            Path(path).resolve().as_uri() + "?mode=rw", uri=True, isolation_level=None
        )
    ) as db:
        db.row_factory = sqlite3.Row
        notice = db.execute(
            """SELECT n.* FROM delivery_notices n JOIN delivery_attempts a ON a.id=n.active_attempt
                               WHERE a.id=? AND a.channel='windows' AND a.outcome='sending' AND n.state='sending'
                               AND a.deadline>? AND n.expires_at>? AND (SELECT enabled FROM delivery_settings)=1""",
            (attempt, now(), now()),
        ).fetchone()
        if not notice:
            return
        if not _desktop():
            delivery._finish(
                db,
                attempt,
                "failed",
                "No unlocked interactive Windows desktop was available.",
            )
            return
        root = None
        visible_started = False
        try:
            root = tk.Tk()
            root.withdraw()
            root.title("Stock Insight — Research update")
            root.attributes("-topmost", True)
            root.attributes("-toolwindow", True)
            root.resizable(False, False)
            frame = ttk.Frame(root, padding=(18, 14))
            frame.pack(fill="both", expand=True)
            labeled = notice["notice_key"].startswith("assistant:") and notice["title"].startswith(("Historical replay ·","Live integration test"))
            ttk.Label(
                frame, text=notice["title"] if labeled else delivery.GENERIC_TITLE, font=("Segoe UI", 13, "bold")
            ).pack(anchor="w")
            ttk.Label(frame, text=notice["message"] if labeled else delivery.GENERIC_MESSAGE, wraplength=415 if labeled else 0, font=("Segoe UI", 10)).pack(
                anchor="w", pady=(4, 12)
            )
            buttons = ttk.Frame(frame)
            buttons.pack(anchor="e")

            def open_report():
                target = notice["report_path"]
                if delivery._REPORT.fullmatch(target) and 1024 <= port <= 65535:
                    with write(db):
                        db.execute(
                            """UPDATE delivery_notices SET open_requested_at=coalesce(open_requested_at,?)
                                      WHERE id=? AND active_attempt=? AND state='shown'""",
                            (now(), notice["id"], attempt),
                        )
                    webbrowser.open(f"http://127.0.0.1:{port}{target}")
                root.destroy()

            ttk.Button(buttons, text="Dismiss", command=root.destroy).pack(
                side="left", padx=(0, 6)
            )
            ttk.Button(buttons, text="Open report", command=open_report).pack(
                side="left"
            )
            root.update_idletasks()
            width, height = root.winfo_reqwidth(), root.winfo_reqheight()
            root.geometry(
                f"+{max(0, root.winfo_screenwidth() - width - 34)}+{max(0, root.winfo_screenheight() - height - 110)}"
            )
            root.deiconify()
            visible_started = True
            root.lift()
            root.update()
            receipt = observe(root.winfo_id(), os.getpid())
            if not receipt:
                delivery._finish(
                    db,
                    attempt,
                    "uncertain",
                    "Could not confirm an unobscured Windows notice on the active desktop.",
                )
                return
            if delivery._finish(
                db,
                attempt,
                "shown",
                "Windows confirmed a visible private notice on the active input desktop.",
                observation=receipt,
            ):
                root.after(35_000, root.destroy)
                root.mainloop()
        except (tk.TclError, OSError):
            delivery._finish(
                db,
                attempt,
                "uncertain" if visible_started else "failed",
                "Windows notification surface unavailable or no longer active.",
            )
        finally:
            if root:
                try:
                    root.destroy()
                except tk.TclError:
                    pass


if __name__ == "__main__":
    show(sys.argv[1], sys.argv[2], int(sys.argv[3]))
