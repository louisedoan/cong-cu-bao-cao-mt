"""Lưu trạng thái license trên máy người dùng: %LOCALAPPDATA%\\NangCom\\license\\license.dat

Nội dung (JSON) được mã hóa DPAPI theo tài khoản Windows -> chép sang máy/tài khoản khác hoặc sửa tay đều không đọc
được. File này KHÔNG phải nơi lưu dữ liệu nghiệp vụ; xóa nó chỉ làm máy phải nhập lại mã.
"""
import json
import os
import time
from datetime import datetime
from pathlib import Path

from . import dpapi

_MAGIC_DPAPI = b'NCLS1\n'
_MAGIC_PLAIN = b'NCLS0\n'  # chỉ dùng khi không có DPAPI (không phải Windows)
_ENTROPY = b'NangCom-License-State-v1'


class StoreCorrupt(Exception):
    """File trạng thái tồn tại nhưng không đọc được (hỏng, bị sửa, hoặc của tài khoản/máy khác)."""


def default_path():
    base = os.environ.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
    return Path(base) / 'NangCom' / 'license' / 'license.dat'


class LicenseStore:
    def __init__(self, path=None, protect=None):
        self.path = Path(path) if path else default_path()
        self.protect = dpapi.available() if protect is None else protect

    def mtime(self):
        try:
            return self.path.stat().st_mtime
        except OSError:
            return None

    def load(self):
        """dict trạng thái, None nếu chưa có file; StoreCorrupt nếu không đọc được."""
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as e:
            raise StoreCorrupt(f'Không đọc được file license: {e}') from None
        try:
            if raw.startswith(_MAGIC_DPAPI):
                body = dpapi.unprotect(raw[len(_MAGIC_DPAPI):], _ENTROPY)
            elif raw.startswith(_MAGIC_PLAIN) and not self.protect:
                body = raw[len(_MAGIC_PLAIN):]
            else:
                raise ValueError('sai định dạng')
            state = json.loads(body.decode('utf-8'))
        except (OSError, ValueError, UnicodeDecodeError):
            raise StoreCorrupt('File license bị hỏng, bị sửa hoặc thuộc tài khoản/máy khác.') from None
        if not isinstance(state, dict) or state.get('v') != 1:
            raise StoreCorrupt('File license không đúng phiên bản.')
        return state

    def save(self, state):
        body = json.dumps(dict(state, v=1), ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        data = _MAGIC_DPAPI + dpapi.protect(body, _ENTROPY) if self.protect else _MAGIC_PLAIN + body
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + '.tmp')
        tmp.write_bytes(data)
        for attempt in range(5):  # công cụ khác đang đọc file cùng lúc -> Windows chặn thay thế trong chốc lát
            try:
                os.replace(tmp, self.path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05)

    def quarantine(self):
        """Đổi tên file hỏng (giữ lại để hỗ trợ kiểm tra, không xóa)."""
        if self.path.exists():
            dst = self.path.with_name(f'{self.path.name}.hong-{datetime.now():%Y%m%d-%H%M%S}')
            os.replace(self.path, dst)
            return dst
        return None
