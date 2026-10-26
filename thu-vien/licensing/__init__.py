"""Cấp phép (license) offline 20 ngày cho bộ công cụ Nàng Cơm.

Bản chuẩn nằm ở <repo>/licensing; mỗi công cụ có một bản sao trong thư mục "thu-vien" của nó
(đồng bộ bằng "python -m license_admin sync" trong repo quản trị riêng). Đừng sửa trực tiếp bản trong "thu-vien".
"""
from .client import (POLICY_TEXT, ActivationError, LicenseClient, LicenseRequired, LicenseStatus, activate,
                     check_license, default_client, format_remaining, format_time, remaining_time)
from .device import DeviceIdError, get_device_id
from .ui import ensure_licensed

__all__ = ['POLICY_TEXT', 'ActivationError', 'DeviceIdError', 'LicenseClient', 'LicenseRequired', 'LicenseStatus',
           'activate', 'check_license', 'default_client', 'ensure_licensed', 'format_remaining', 'format_time',
           'get_device_id', 'remaining_time']
