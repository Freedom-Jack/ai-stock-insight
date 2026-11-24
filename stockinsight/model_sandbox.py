"""Run the pinned local CPU binary in a Windows capability-free AppContainer."""

from __future__ import annotations

import ctypes as c
import os
import subprocess
import tempfile
import uuid
from contextlib import ExitStack
from ctypes import wintypes as wt
from pathlib import Path


class _Startup(c.Structure):
    _fields_ = [
        ("cb", wt.DWORD),
        ("reserved", wt.LPWSTR),
        ("desktop", wt.LPWSTR),
        ("title", wt.LPWSTR),
        *[
            (name, wt.DWORD)
            for name in ("x", "y", "width", "height", "cols", "rows", "fill", "flags")
        ],
        ("show", wt.WORD),
        ("cb_reserved", wt.WORD),
        ("reserved2", wt.LPVOID),
        ("stdin", wt.HANDLE),
        ("stdout", wt.HANDLE),
        ("stderr", wt.HANDLE),
        ("attributes", wt.LPVOID),
    ]


class _Process(c.Structure):
    _fields_ = [
        ("process", wt.HANDLE),
        ("thread", wt.HANDLE),
        ("pid", wt.DWORD),
        ("tid", wt.DWORD),
    ]


class _Capabilities(c.Structure):
    _fields_ = [
        ("sid", wt.LPVOID),
        ("list", wt.LPVOID),
        ("count", wt.DWORD),
        ("reserved", wt.DWORD),
    ]


def _fn(lib, name, result, *args):
    fn = getattr(lib, name)
    fn.restype = result
    fn.argtypes = list(args)
    return fn


def _ok(success):
    if not success:
        raise c.WinError(c.get_last_error())


def run(command, *, cwd, env, timeout=60):
    """The caller owns a fresh scratch directory containing only admitted inputs."""
    import msvcrt

    k = c.WinDLL("kernel32", use_last_error=True)
    sec = c.WinDLL("advapi32", use_last_error=True)
    user = c.WinDLL("userenv", use_last_error=True)
    ptr = wt.LPVOID
    size = c.c_size_t
    # A unique identity and empty capability list prevent grants from other
    # concurrent runs (and internet/private-network capability inheritance).
    moniker = "StockInsight.Inference." + uuid.uuid4().hex
    sid = ptr()
    create = _fn(
        user,
        "CreateAppContainerProfile",
        c.c_long,
        wt.LPCWSTR,
        wt.LPCWSTR,
        wt.LPCWSTR,
        ptr,
        wt.DWORD,
        c.POINTER(ptr),
    )
    hr = create(
        moniker,
        "Stock Insight inference",
        "Transient restricted CPU selector",
        None,
        0,
        c.byref(sid),
    )
    if hr != 0:
        raise OSError(
            f"Could not create the isolated model identity (HRESULT 0x{hr & 0xFFFFFFFF:08x})."
        )
    with ExitStack() as cleanup:
        cleanup.callback(
            _fn(user, "DeleteAppContainerProfile", c.c_long, wt.LPCWSTR), moniker
        )
        cleanup.callback(_fn(sec, "FreeSid", ptr, ptr), sid)
        sid_string = wt.LPWSTR()
        _ok(
            _fn(sec, "ConvertSidToStringSidW", wt.BOOL, ptr, c.POINTER(wt.LPWSTR))(
                sid, c.byref(sid_string)
            )
        )
        cleanup.callback(_fn(k, "LocalFree", ptr, ptr), c.cast(sid_string, ptr))
        grant = subprocess.run(
            [
                str(Path(env["SystemRoot"]) / "System32" / "icacls.exe"),
                str(cwd),
                "/grant:r",
                "*" + sid_string.value + ":(OI)(CI)(RX)",
            ],
            shell=False,
            check=False,
            capture_output=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if grant.returncode:
            raise OSError(
                "Could not grant the isolated process access to its own scratch directory."
            )
        # Only these three handles are inherited. The input files and verified
        # model are read-only; stdout/stderr go to host-owned temporary handles.
        stdin = cleanup.enter_context(open(os.devnull, "rb"))
        stdout = cleanup.enter_context(tempfile.TemporaryFile())
        stderr = cleanup.enter_context(tempfile.TemporaryFile())
        handles = (wt.HANDLE * 3)(
            *(msvcrt.get_osfhandle(f.fileno()) for f in (stdin, stdout, stderr))
        )
        for fd in (stdin, stdout, stderr):
            os.set_handle_inheritable(msvcrt.get_osfhandle(fd.fileno()), True)
        attributes_size = size()
        init = _fn(
            k,
            "InitializeProcThreadAttributeList",
            wt.BOOL,
            ptr,
            wt.DWORD,
            wt.DWORD,
            c.POINTER(size),
        )
        init(None, 2, 0, c.byref(attributes_size))
        attributes = c.create_string_buffer(attributes_size.value)
        _ok(init(attributes, 2, 0, c.byref(attributes_size)))
        cleanup.callback(_fn(k, "DeleteProcThreadAttributeList", None, ptr), attributes)
        update = _fn(
            k,
            "UpdateProcThreadAttribute",
            wt.BOOL,
            ptr,
            wt.DWORD,
            size,
            ptr,
            size,
            ptr,
            ptr,
        )
        caps = _Capabilities(sid, None, 0, 0)
        for key, value in ((0x20009, caps), (0x20002, handles)):
            _ok(update(attributes, 0, key, c.byref(value), c.sizeof(value), None, None))
        info = _Startup()
        info.cb = c.sizeof(info)
        info.flags = 0x100
        info.stdin, info.stdout, info.stderr = handles
        info.attributes = c.cast(attributes, ptr)
        proc = _Process()
        cmd = c.create_unicode_buffer(subprocess.list2cmdline(command))
        # Userenv needs the profile roots to build its AppContainer-specific
        # environment. Credentials and arbitrary parent variables stay absent.
        base = {
            key: os.environ[key]
            for key in (
                "USERPROFILE",
                "LOCALAPPDATA",
                "APPDATA",
                "SystemDrive",
                "ProgramData",
                "ProgramFiles",
                "WINDIR",
            )
            if key in os.environ
        }
        base.update(env)
        block = c.create_unicode_buffer(
            "\0".join(
                f"{key}={value}"
                for key, value in sorted(
                    base.items(), key=lambda item: item[0].casefold()
                )
            )
            + "\0\0"
        )
        spawn = _fn(
            k,
            "CreateProcessW",
            wt.BOOL,
            wt.LPCWSTR,
            wt.LPWSTR,
            ptr,
            ptr,
            wt.BOOL,
            wt.DWORD,
            ptr,
            wt.LPCWSTR,
            c.POINTER(_Startup),
            c.POINTER(_Process),
        )
        flags = 0x00080000 | 0x00000400 | 0x00000004 | subprocess.CREATE_NO_WINDOW
        _ok(
            spawn(
                str(command[0]),
                cmd,
                None,
                None,
                True,
                flags,
                block,
                str(cwd),
                c.byref(info),
                c.byref(proc),
            )
        )
        close = _fn(k, "CloseHandle", wt.BOOL, wt.HANDLE)
        cleanup.callback(close, proc.process)
        cleanup.callback(close, proc.thread)
        # Attest the effective token before allowing the model's first thread to run.
        token = wt.HANDLE()
        terminate = _fn(k, "TerminateProcess", wt.BOOL, wt.HANDLE, wt.UINT)
        try:
            _ok(
                _fn(
                    sec,
                    "OpenProcessToken",
                    wt.BOOL,
                    wt.HANDLE,
                    wt.DWORD,
                    c.POINTER(wt.HANDLE),
                )(proc.process, 0x0008, c.byref(token))
            )
            cleanup.callback(close, token)
            get = _fn(
                sec,
                "GetTokenInformation",
                wt.BOOL,
                wt.HANDLE,
                c.c_int,
                ptr,
                wt.DWORD,
                c.POINTER(wt.DWORD),
            )
            actual = wt.DWORD()
            returned = wt.DWORD()
            _ok(
                get(token, 29, c.byref(actual), c.sizeof(actual), c.byref(returned))
            )  # TokenIsAppContainer
            groups = c.create_string_buffer(64)
            _ok(
                get(token, 30, groups, c.sizeof(groups), c.byref(returned))
            )  # TokenCapabilities
            if actual.value != 1 or wt.DWORD.from_buffer(groups).value != 0:
                raise OSError(
                    "The model process lacked its required capability-free AppContainer token."
                )
            _ok(_fn(k, "ResumeThread", wt.DWORD, wt.HANDLE)(proc.thread) != 0xFFFFFFFF)
        except BaseException:
            terminate(proc.process, 1)
            raise
        wait = _fn(k, "WaitForSingleObject", wt.DWORD, wt.HANDLE, wt.DWORD)
        if wait(proc.process, int(timeout * 1000)) != 0:
            terminate(proc.process, 1)
            wait(proc.process, 5000)
            raise subprocess.TimeoutExpired(command[0], timeout)
        code = wt.DWORD()
        _ok(
            _fn(k, "GetExitCodeProcess", wt.BOOL, wt.HANDLE, c.POINTER(wt.DWORD))(
                proc.process, c.byref(code)
            )
        )
        stdout.seek(0)
        stderr.seek(0)
        return subprocess.CompletedProcess(
            command, code.value, stdout.read(8192), stderr.read(8192)
        )
