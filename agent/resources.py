"""Cheap cached host observations; unavailable readings remain explicitly unknown."""
import ctypes
import os
import time


class ResourceProbe:
    def __init__(self, interval=5, clock=time.monotonic):
        self.interval = max(1, interval)
        self.clock = clock
        self._checked = -float('inf')
        self._previous = None
        self._value = {'status': 'unknown', 'free_ram_mb': None, 'cpu_percent': None}

    def snapshot(self):
        now = self.clock()
        if now - self._checked < self.interval:
            return dict(self._value)
        self._checked = now
        try:
            if os.name != 'nt':
                return dict(self._value)
            from ctypes import wintypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD)] + [
                    (name, ctypes.c_ulonglong) for name in (
                        'total', 'available', 'total_page', 'available_page',
                        'total_virtual', 'available_virtual', 'extended')]

            memory = MemoryStatus()
            memory.length = ctypes.sizeof(memory)
            kernel = ctypes.windll.kernel32
            idle, system, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
            if not kernel.GlobalMemoryStatusEx(ctypes.byref(memory)) or not kernel.GetSystemTimes(
                    ctypes.byref(idle), ctypes.byref(system), ctypes.byref(user)):
                raise OSError('resource_probe')
            values = tuple((v.dwHighDateTime << 32) | v.dwLowDateTime for v in (idle, system, user))
            cpu = None
            if self._previous is not None:
                delta = tuple(v - p for v, p in zip(values, self._previous))
                total = delta[1] + delta[2]
                if total > 0 and 0 <= delta[0] <= total:
                    cpu = 100 * (total - delta[0]) / total
            self._previous = values
            self._value = {'status': 'measured', 'free_ram_mb': memory.available / 1048576,
                           'cpu_percent': cpu}
        except (OSError, AttributeError, TypeError, ValueError):
            self._value = {'status': 'unknown', 'free_ram_mb': None, 'cpu_percent': None}
        return dict(self._value)
