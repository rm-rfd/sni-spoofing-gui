from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os

PROXY_TYPE_DIRECT = 0x00000001
PROXY_TYPE_PROXY = 0x00000002
PROXY_TYPE_AUTO_PROXY_URL = 0x00000004
PROXY_TYPE_AUTO_DETECT = 0x00000008

INTERNET_OPTION_REFRESH = 37
INTERNET_OPTION_SETTINGS_CHANGED = 39
INTERNET_OPTION_PER_CONNECTION_OPTION = 75

INTERNET_PER_CONN_FLAGS = 1
INTERNET_PER_CONN_PROXY_SERVER = 2
INTERNET_PER_CONN_PROXY_BYPASS = 3
INTERNET_PER_CONN_AUTOCONFIG_URL = 4


class _INTERNET_PER_CONN_OPTION_VALUE(ctypes.Union):
    _fields_ = [
        ("dwValue", wintypes.DWORD),
        ("pszValue", wintypes.LPWSTR),
        ("ftValue", wintypes.FILETIME),
    ]


class _INTERNET_PER_CONN_OPTIONW(ctypes.Structure):
    _fields_ = [
        ("dwOption", wintypes.DWORD),
        ("Value", _INTERNET_PER_CONN_OPTION_VALUE),
    ]


class _INTERNET_PER_CONN_OPTION_LISTW(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("pszConnection", wintypes.LPWSTR),
        ("dwOptionCount", wintypes.DWORD),
        ("dwOptionError", wintypes.DWORD),
        ("pOptions", ctypes.POINTER(_INTERNET_PER_CONN_OPTIONW)),
    ]


if os.name == "nt":
    _wininet = ctypes.WinDLL("wininet", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _wininet.InternetQueryOptionW.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _wininet.InternetQueryOptionW.restype = wintypes.BOOL
    _wininet.InternetSetOptionW.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _wininet.InternetSetOptionW.restype = wintypes.BOOL
    _kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalFree.restype = wintypes.HGLOBAL
else:
    _wininet = None
    _kernel32 = None


@dataclass(frozen=True)
class WindowsSystemProxyState:
    flags: int
    proxy_server: str = ""
    proxy_bypass: str = ""
    auto_config_url: str = ""

    @property
    def proxy_enabled(self) -> bool:
        return bool((self.flags & PROXY_TYPE_PROXY) and self.proxy_server.strip())

    @property
    def auto_detect_enabled(self) -> bool:
        return bool(self.flags & PROXY_TYPE_AUTO_DETECT)

    @property
    def auto_config_enabled(self) -> bool:
        return bool((self.flags & PROXY_TYPE_AUTO_PROXY_URL) and self.auto_config_url.strip())

    def is_cleared(self) -> bool:
        return not self.proxy_enabled and not self.auto_detect_enabled and not self.auto_config_enabled

    def to_dict(self) -> dict[str, object]:
        return {
            "flags": self.flags,
            "proxy_server": self.proxy_server,
            "proxy_bypass": self.proxy_bypass,
            "auto_config_url": self.auto_config_url,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> WindowsSystemProxyState:
        flags = payload.get("flags")
        proxy_server = payload.get("proxy_server", "")
        proxy_bypass = payload.get("proxy_bypass", "")
        auto_config_url = payload.get("auto_config_url", "")

        if not isinstance(flags, int):
            raise ValueError("system proxy state flags must be an integer")
        if not isinstance(proxy_server, str):
            raise ValueError("system proxy state proxy_server must be a string")
        if not isinstance(proxy_bypass, str):
            raise ValueError("system proxy state proxy_bypass must be a string")
        if not isinstance(auto_config_url, str):
            raise ValueError("system proxy state auto_config_url must be a string")

        return cls(
            flags=flags,
            proxy_server=proxy_server,
            proxy_bypass=proxy_bypass,
            auto_config_url=auto_config_url,
        )


def get_system_proxy_state() -> WindowsSystemProxyState:
    _require_windows_proxy_support()

    option_codes = (
        INTERNET_PER_CONN_FLAGS,
        INTERNET_PER_CONN_PROXY_SERVER,
        INTERNET_PER_CONN_PROXY_BYPASS,
        INTERNET_PER_CONN_AUTOCONFIG_URL,
    )
    option_array = (_INTERNET_PER_CONN_OPTIONW * len(option_codes))()
    for index, option_code in enumerate(option_codes):
        option_array[index].dwOption = option_code

    option_list = _INTERNET_PER_CONN_OPTION_LISTW()
    option_list.dwSize = ctypes.sizeof(_INTERNET_PER_CONN_OPTION_LISTW)
    option_list.pszConnection = None
    option_list.dwOptionCount = len(option_codes)
    option_list.dwOptionError = 0
    option_list.pOptions = option_array

    buffer_size = wintypes.DWORD(ctypes.sizeof(option_list))
    _call_wininet(
        _wininet.InternetQueryOptionW(
            None,
            INTERNET_OPTION_PER_CONNECTION_OPTION,
            ctypes.byref(option_list),
            ctypes.byref(buffer_size),
        )
    )

    return WindowsSystemProxyState(
        flags=int(option_array[0].Value.dwValue),
        proxy_server=_read_option_string(option_array[1]),
        proxy_bypass=_read_option_string(option_array[2]),
        auto_config_url=_read_option_string(option_array[3]),
    )


def build_clear_system_proxy_state() -> WindowsSystemProxyState:
    return WindowsSystemProxyState(flags=PROXY_TYPE_DIRECT)


def build_local_system_proxy_state(
    local_proxy_port: int,
    *,
    proxy_bypass: str = "",
) -> WindowsSystemProxyState:
    normalized_bypass = proxy_bypass.strip() or "<local>"
    return WindowsSystemProxyState(
        flags=PROXY_TYPE_DIRECT | PROXY_TYPE_PROXY,
        proxy_server=f"127.0.0.1:{local_proxy_port}",
        proxy_bypass=normalized_bypass,
    )


def clear_system_proxy() -> WindowsSystemProxyState:
    cleared_state = build_clear_system_proxy_state()
    apply_system_proxy_state(cleared_state)
    return cleared_state


def set_system_proxy(local_proxy_port: int, *, proxy_bypass: str = "") -> WindowsSystemProxyState:
    local_proxy_state = build_local_system_proxy_state(local_proxy_port, proxy_bypass=proxy_bypass)
    apply_system_proxy_state(local_proxy_state)
    return local_proxy_state


def restore_system_proxy_state(state: WindowsSystemProxyState) -> None:
    apply_system_proxy_state(state)


def apply_system_proxy_state(state: WindowsSystemProxyState) -> None:
    _require_windows_proxy_support()

    option_array = (_INTERNET_PER_CONN_OPTIONW * 4)()
    option_array[0].dwOption = INTERNET_PER_CONN_FLAGS
    option_array[0].Value.dwValue = wintypes.DWORD(state.flags)

    string_buffers: list[object] = []
    _set_option_string(option_array[1], INTERNET_PER_CONN_PROXY_SERVER, state.proxy_server, string_buffers)
    _set_option_string(option_array[2], INTERNET_PER_CONN_PROXY_BYPASS, state.proxy_bypass, string_buffers)
    _set_option_string(option_array[3], INTERNET_PER_CONN_AUTOCONFIG_URL, state.auto_config_url, string_buffers)

    option_list = _INTERNET_PER_CONN_OPTION_LISTW()
    option_list.dwSize = ctypes.sizeof(_INTERNET_PER_CONN_OPTION_LISTW)
    option_list.pszConnection = None
    option_list.dwOptionCount = len(option_array)
    option_list.dwOptionError = 0
    option_list.pOptions = option_array

    _call_wininet(
        _wininet.InternetSetOptionW(
            None,
            INTERNET_OPTION_PER_CONNECTION_OPTION,
            ctypes.byref(option_list),
            ctypes.sizeof(option_list),
        )
    )
    notify_system_proxy_changed()


def notify_system_proxy_changed() -> None:
    _require_windows_proxy_support()
    _call_wininet(_wininet.InternetSetOptionW(None, INTERNET_OPTION_SETTINGS_CHANGED, None, 0))
    _call_wininet(_wininet.InternetSetOptionW(None, INTERNET_OPTION_REFRESH, None, 0))


def _set_option_string(
    option: _INTERNET_PER_CONN_OPTIONW,
    option_code: int,
    value: str,
    buffers: list[object],
) -> None:
    option.dwOption = option_code
    buffer = ctypes.create_unicode_buffer(value)
    buffers.append(buffer)
    option.Value.pszValue = ctypes.cast(buffer, wintypes.LPWSTR)


def _read_option_string(option: _INTERNET_PER_CONN_OPTIONW) -> str:
    pointer = option.Value.pszValue
    if not pointer:
        return ""
    return ctypes.wstring_at(pointer)


def _call_wininet(success: int) -> None:
    if success:
        return
    raise ctypes.WinError(ctypes.get_last_error())


def _require_windows_proxy_support() -> None:
    if os.name != "nt" or _wininet is None or _kernel32 is None:
        raise RuntimeError("Windows system proxy management is only available on Windows")


__all__ = [
    "WindowsSystemProxyState",
    "PROXY_TYPE_DIRECT",
    "PROXY_TYPE_PROXY",
    "PROXY_TYPE_AUTO_PROXY_URL",
    "PROXY_TYPE_AUTO_DETECT",
    "get_system_proxy_state",
    "build_clear_system_proxy_state",
    "build_local_system_proxy_state",
    "clear_system_proxy",
    "set_system_proxy",
    "restore_system_proxy_state",
    "apply_system_proxy_state",
    "notify_system_proxy_changed",
]