"""Mã thiết bị (Device ID) của máy Windows.

Device ID = SHA-256("NangCom-Device-v1|" + MachineGuid) lấy 10 byte, hiển thị dạng XXXX-XXXX-XXXX-XXXX.
- MachineGuid do Windows tạo khi cài đặt: giữ nguyên qua khởi động lại, cập nhật Windows, thay RAM/ổ phụ;
  ĐỔI khi cài lại Windows hoặc nhân bản ổ đĩa có sysprep -> cần quản trị viên cấp lại mã.
- Chỉ lưu/gửi giá trị đã băm, không lộ định danh gốc. Người có quyền Administrator có thể sửa MachineGuid
  (giả mạo) — giới hạn đã công bố trong IMPLEMENTATION_DECISIONS.md.
"""
import hashlib
import sys

from .codec import DEVICE_BYTES, format_device_id

_SALT = b'NangCom-Device-v1|'


class DeviceIdError(RuntimeError):
    """Không đọc được định danh máy."""


def machine_guid():
    if sys.platform != 'win32':
        raise DeviceIdError('Chỉ hỗ trợ Windows.')
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography', 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            value, _ = winreg.QueryValueEx(k, 'MachineGuid')
    except OSError as e:
        raise DeviceIdError(f'Không đọc được MachineGuid của Windows: {e}') from None
    value = str(value).strip().lower()
    if not value:
        raise DeviceIdError('MachineGuid của Windows đang trống.')
    return value


def device_id_bytes(guid=None):
    guid = machine_guid() if guid is None else guid.strip().lower()
    return hashlib.sha256(_SALT + guid.encode('utf-8')).digest()[:DEVICE_BYTES]


def get_device_id(guid=None):
    """Device ID của máy này, dạng hiển thị XXXX-XXXX-XXXX-XXXX."""
    return format_device_id(device_id_bytes(guid))
