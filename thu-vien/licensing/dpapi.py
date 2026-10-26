"""Mã hóa dữ liệu bằng Windows DPAPI (CryptProtectData) theo tài khoản Windows hiện tại.

Dữ liệu đã mã hóa chỉ giải mã được bởi đúng tài khoản Windows trên đúng máy (và đúng `entropy`);
DPAPI có kiểm tra toàn vẹn nên dữ liệu bị sửa sẽ không giải mã được.
"""
import ctypes
import sys

_UI_FORBIDDEN = 0x1


class DpapiError(OSError):
    pass


def available():
    return sys.platform == 'win32'


if available():
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    _kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    _sig = [ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(_Blob)]
    _crypt32.CryptProtectData.argtypes = _sig
    _crypt32.CryptProtectData.restype = wintypes.BOOL
    _crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(_Blob), ctypes.POINTER(wintypes.LPWSTR)] + _sig[2:]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p


def _blob(data):
    buf = ctypes.create_string_buffer(bytes(data), max(1, len(data)))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _call(fn, data, entropy, *mid):
    if not available():
        raise DpapiError('DPAPI chỉ có trên Windows.')
    blob_in, keep_in = _blob(data)
    ent, keep_ent = _blob(entropy or b'')
    out = _Blob()
    ok = fn(ctypes.byref(blob_in), *mid, ctypes.byref(ent) if entropy else None, None, None, _UI_FORBIDDEN,
            ctypes.byref(out))
    if not ok:
        raise DpapiError(ctypes.get_last_error(), 'DPAPI không xử lý được dữ liệu (sai tài khoản/máy hoặc dữ liệu bị sửa).')
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        _kernel32.LocalFree(out.pbData)


def protect(data, entropy=b''):
    return _call(_crypt32.CryptProtectData, data, entropy, None)


def unprotect(data, entropy=b''):
    return _call(_crypt32.CryptUnprotectData, data, entropy, None)
