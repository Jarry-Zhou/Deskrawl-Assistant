"""Steam launch and normal Windows close, independent of memory connection."""
from __future__ import annotations

import os
import threading
import time

STEAM_APP_ID = 4623570


class WindowsGameProcess:
    def instances(self):
        from .native_memory import game_pids
        result = []
        for pid in game_pids():
            try:
                with self._identity(pid) as instance:
                    result.append(instance[1])
            except OSError as exc:
                if getattr(exc,'winerror',None) in (6,87,1168):
                    continue  # Exited between enumeration and opening.
                raise  # Access denial is an unknown state, never "not running".
        return result

    @staticmethod
    def _identity(pid):
        import ctypes as C
        from ctypes import wintypes as W
        from contextlib import contextmanager
        from pathlib import Path
        from .native_memory import K

        @contextmanager
        def opened():
            handle = K.OpenProcess(0x1000, False, pid)
            if not handle: raise C.WinError(C.get_last_error())
            try:
                size = W.DWORD(32768)
                path = C.create_unicode_buffer(size.value)
                if not K.QueryFullProcessImageNameW(handle, 0, path, C.byref(size)):
                    raise C.WinError(C.get_last_error())
                if Path(path.value).name.casefold() != 'deskrawl.exe':
                    raise ValueError('目标进程已变化，请刷新游戏状态。')
                created, exited, kernel, user = (W.FILETIME() for _ in range(4))
                K.GetProcessTimes.argtypes = (W.HANDLE, *(C.POINTER(W.FILETIME),)*4)
                K.GetProcessTimes.restype = W.BOOL
                if not K.GetProcessTimes(handle, C.byref(created), C.byref(exited), C.byref(kernel), C.byref(user)):
                    raise C.WinError(C.get_last_error())
                stamp = (created.dwHighDateTime << 32) | created.dwLowDateTime
                yield handle, {'pid':pid, 'instance':f'{pid}:{stamp}'}
            finally:
                K.CloseHandle(handle)
        return opened()

    def launch(self):
        os.startfile(f'steam://rungameid/{STEAM_APP_ID}')

    def close(self, expected):
        import ctypes as C
        from ctypes import wintypes as W
        from .native_memory import K
        pid = expected.get('pid')
        if type(pid) is not int or pid <= 0: raise ValueError('游戏进程未确认。')
        with self._identity(pid) as (handle, identity):
            if identity != expected: raise ValueError('游戏进程已变化，请重新确认关闭。')
            code = W.DWORD()
            if not K.GetExitCodeProcess(handle, C.byref(code)) or code.value != 259:
                return
            user = C.WinDLL('user32', use_last_error=True)
            callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
            user.EnumWindows.argtypes = (callback_type, W.LPARAM)
            user.GetWindowThreadProcessId.argtypes = (W.HWND, C.POINTER(W.DWORD))
            user.GetClassNameW.argtypes = (W.HWND, W.LPWSTR, C.c_int)
            user.IsWindowVisible.argtypes = (W.HWND,)
            user.PostMessageW.argtypes = (W.HWND, W.UINT, W.WPARAM, W.LPARAM)
            user.PostMessageW.restype = W.BOOL
            windows = []

            @callback_type
            def visit(hwnd, _):
                owner = W.DWORD()
                user.GetWindowThreadProcessId(hwnd, C.byref(owner))
                name = C.create_unicode_buffer(256)
                user.GetClassNameW(hwnd, name, len(name))
                if owner.value == pid and name.value == 'UnityWndClass' and user.IsWindowVisible(hwnd):
                    windows.append(hwnd)
                return True

            user.EnumWindows(visit, 0)
            if len(windows) != 1:
                raise ValueError('尚未找到唯一的游戏窗口，请等待游戏载入后重试。')
            # Hold the process handle through the message: Windows cannot reuse
            # this PID for a different process while we still own its handle.
            if not user.PostMessageW(windows[0], 0x10, 0, 0):  # WM_CLOSE, normal save/quit path
                raise C.WinError(C.get_last_error())


class GameLifecycle:
    def __init__(self, backend=None, clock=time.monotonic):
        self.backend = backend or WindowsGameProcess()
        self.clock = clock
        self.guard = threading.RLock()
        self.cached = None
        self.checked = -float('inf')
        self.pending = None
        self.deadline = 0
        self.error = ''

    def state(self, *, fresh=False):
        with self.guard:
            now = self.clock()
            if not fresh and self.cached is not None and now-self.checked < 1:
                return dict(self.cached)
            try:
                instances = self.backend.instances()
            except (OSError, ValueError, ImportError) as exc:
                return {'status':'unknown','running':False,'can_start':False,'can_close':False,'error':str(exc)}
            running = bool(instances)
            if self.pending == 'starting' and running or self.pending == 'closing' and not running:
                self.pending = None
                self.error = ''
            if self.pending and now >= self.deadline:
                self.error = 'Steam 启动尚未完成，请检查 Steam 后重试。' if self.pending=='starting' else '游戏尚未退出，请检查游戏窗口后重试。'
                self.pending = None
            self.cached = {'status':self.pending or ('running' if running else 'stopped'), 'running':running,
                'can_start':not running and not self.pending, 'can_close':len(instances)==1 and not self.pending,
                'target':instances[0] if len(instances)==1 else None, 'count':len(instances), 'error':self.error}
            self.checked = now
            return dict(self.cached)

    def start(self):
        with self.guard:
            state = self.state(fresh=True)
            if not state['can_start']: raise ValueError('游戏已运行、正在启动或运行状态未确认。')
            self.backend.launch()
            self.pending, self.deadline, self.error = 'starting', self.clock()+60, ''
            return self.state(fresh=True)

    def close(self, target):
        with self.guard:
            state = self.state(fresh=True)
            if not state['can_close'] or target != state['target']:
                raise ValueError('游戏状态已变化，请刷新后重新确认关闭。')
            self.backend.close(target)
            self.pending, self.deadline, self.error = 'closing', self.clock()+20, ''
            return self.state(fresh=True)
