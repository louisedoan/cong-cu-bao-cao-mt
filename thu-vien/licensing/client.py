"""Kiểm tra license trên máy người dùng — hoạt động hoàn toàn OFFLINE, không có kết nối mạng.

API nội bộ:
    client = LicenseClient()
    client.activate(code)      -> LicenseStatus (lỗi -> ActivationError có .reason)
    client.check_license()     -> LicenseStatus (.valid, .message, .remaining_seconds, ...)
    client.remaining_time()    -> timedelta | None
    @client.require            -> bọc hàm cần license (chưa hợp lệ -> LicenseRequired)

Mô hình (xem IMPLEMENTATION_DECISIONS.md): mã do quản trị viên ký sẵn, gắn Device ID, hiệu lực 20 ngày
kể từ THỜI ĐIỂM PHÁT HÀNH. Module này không đọc, ghi hay xóa dữ liệu nghiệp vụ nào.
"""
import functools
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from . import chain, codec
from .codec import CodeFormatError, LICENSE_SECONDS
from .device import DeviceIdError, get_device_id
from .storage import LicenseStore, StoreCorrupt

ROLLBACK_TOLERANCE = 5 * 60  # đồng hồ lùi quá mức này so với lần dùng trước -> nghi chỉnh giờ
ISSUE_SKEW = 10 * 60         # cho phép đồng hồ máy chậm hơn máy quản trị tối đa 10 phút
PERSIST_EVERY = 5 * 60       # ghi mốc thời gian đã thấy tối đa 5 phút/lần
MAX_USED = 500
MAX_LOG = 50

POLICY_TEXT = '\n'.join([
    'CHÍNH SÁCH LICENSE OFFLINE – CÔNG CỤ NÀNG CƠM',
    '',
    '• Mỗi mã kích hoạt do quản trị viên cấp cho ĐÚNG MỘT máy (theo Mã thiết bị) và chỉ dùng MỘT lần.',
    '• Mã có hiệu lực 20 ngày liên tục, tính từ LÚC QUẢN TRỊ VIÊN PHÁT HÀNH MÃ (không phải lúc nhập mã).',
    '  Hãy nhập mã ngay khi nhận được.',
    '• Trong 20 ngày đó công cụ chạy hoàn toàn offline; đóng/mở lại không cần nhập lại mã.',
    '• Hết hạn: các chức năng của công cụ bị khóa cho tới khi nhập mã mới. Dữ liệu, cấu hình, file báo cáo',
    '  và sao lưu được GIỮ NGUYÊN — license không đọc, sửa hay xóa dữ liệu của bạn.',
    '• Không gia hạn mã cũ. Nhập lại mã đã dùng sẽ bị từ chối.',
    '• Đồng hồ Windows phải đúng giờ (nên bật "Đặt giờ tự động"). Lùi đồng hồ sẽ làm license bị khóa.',
    '• Cài lại Windows hoặc đổi máy làm Mã thiết bị thay đổi: gửi Mã thiết bị mới cho quản trị viên để được cấp lại.',
    '• Quyền riêng tư: Mã thiết bị là giá trị băm một chiều từ định danh cài đặt Windows. Công cụ không thu thập',
    '  tên, tài khoản, nội dung file và không gửi gì qua mạng.',
    '• Thu hồi mã từ phía quản trị viên không có hiệu lực ngay trên máy đang offline; mã vẫn chạy tới khi hết hạn.',
    '• Mã do quản trị viên đã bị gỡ quyền sẽ hết tác dụng khi máy nhận được thông tin gỡ quyền (qua mã mới',
    '  hoặc bản cập nhật công cụ).',
])

_MESSAGES = {
    'active': 'License đang hoạt động — còn {remaining} (hết hạn {expires}).',
    'not_activated': 'Máy này chưa được cấp phép. Vui lòng nhập mã kích hoạt (Activation Code) do quản trị viên cấp.',
    'expired': 'License đã hết hạn (lúc {expires}), vui lòng nhập mã kích hoạt mới.',
    'clock_error': 'Đồng hồ Windows đang lùi so với lần dùng trước ({last_seen}). Hãy bật "Đặt giờ tự động" '
                   'trong cài đặt Windows rồi mở lại công cụ.',
    'corrupt': 'Dữ liệu license trên máy không đọc được (bị hỏng hoặc bị sửa). Vui lòng nhập lại mã kích hoạt.',
    'invalid': 'License đã lưu không hợp lệ (chữ ký không khớp). Vui lòng nhập mã kích hoạt mới.',
    'device_mismatch': 'License đã lưu không thuộc máy này (có thể do cài lại Windows hoặc chép từ máy khác). '
                       'Gửi Mã thiết bị của máy này cho quản trị viên để được cấp mã mới.',
    'no_public_key': 'Bản cài đặt này chưa được cấu hình khóa xác thực license. Liên hệ quản trị viên.',
    'device_error': 'Không xác định được Mã thiết bị của máy này: {detail}',
    'revoked': 'Mã kích hoạt này không còn hiệu lực. Liên hệ quản trị viên để nhận mã mới.',
}


def format_time(ts, tz=None):
    """Giờ địa phương (hoặc múi giờ `tz`) dạng 'dd/mm/yyyy HH:MM (GMT+7)'."""
    if ts is None:
        return ''
    dt = datetime.fromtimestamp(ts, tz) if tz else datetime.fromtimestamp(ts).astimezone()
    off = int(dt.utcoffset().total_seconds() // 60)
    sign, off = ('+' if off >= 0 else '-'), abs(off)
    zone = f'GMT{sign}{off // 60}' + (f':{off % 60:02d}' if off % 60 else '')
    return f'{dt:%d/%m/%Y %H:%M} ({zone})'


def format_remaining(seconds):
    seconds = max(0, int(seconds))
    if seconds < 60:
        return 'dưới 1 phút' if seconds else '0 phút'
    d, rem = divmod(seconds // 60, 1440)
    h, m = divmod(rem, 60)
    if d:
        return f'{d} ngày {h:02d} giờ'
    return f'{h} giờ {m:02d} phút' if h else f'{m} phút'


class ActivationError(Exception):
    """Mã bị từ chối. `reason`: format, signature, product, duration, device, used, expired, not_yet_valid,
    clock, no_public_key, device_error, storage, revoked."""

    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


class LicenseRequired(Exception):
    """Gọi chức năng cần license khi license không hợp lệ."""

    def __init__(self, status):
        super().__init__(status.message)
        self.status = status


@dataclass
class LicenseStatus:
    state: str
    message: str
    device_id: str = ''
    license_id: str = ''
    issued_at: int = None
    expires_at: int = None
    remaining_seconds: int = 0
    checked_at: int = 0

    @property
    def valid(self):
        return self.state == 'active'

    def to_dict(self):
        d = asdict(self)
        d.update(valid=self.valid, issued_text=format_time(self.issued_at), expires_text=format_time(self.expires_at),
                 remaining_text=format_remaining(self.remaining_seconds) if self.valid else '',
                 can_activate=self.state not in ('no_public_key', 'device_error'))
        return d


def _load_public_key(value):
    if value is None:
        from .public_key import PUBLIC_KEY_HEX
        value = PUBLIC_KEY_HEX
    if not value:
        return None
    key = bytes.fromhex(value) if isinstance(value, str) else bytes(value)
    if len(key) != 32:
        raise ValueError('Public key Ed25519 phải dài 32 byte.')
    return key


def _load_revocations(value):
    if value is None:
        from .thu_hoi import REVOCATION_HEX
        value = REVOCATION_HEX
    return chain.revocations_from_hex(value)


class LicenseClient:
    def __init__(self, public_key=None, store=None, device_id=None, clock=None, revocations_hex=None):
        self.public_key = _load_public_key(public_key)
        self._file_revocations = _load_revocations(revocations_hex)  # đi kèm bản cài đặt (licensing/thu_hoi.py)
        self.store = store or LicenseStore()
        self._device_id = codec.format_device_id(codec.parse_device_id(device_id)) if device_id else None
        self.clock = clock or time.time
        self._verified = {}
        self._lock = threading.RLock()  # máy chủ web gọi từ nhiều luồng

    # ---------- tiện ích ----------
    def device_id(self):
        if self._device_id is None:
            self._device_id = get_device_id()
        return self._device_id

    def _status(self, state, tok=None, now=0, **fmt):
        exp = tok.expires_at if tok else None
        remaining = max(0, exp - now) if exp and state == 'active' else 0
        fmt.setdefault('expires', format_time(exp))
        fmt.setdefault('remaining', format_remaining(remaining))
        dev = self._device_id or ''
        return LicenseStatus(state, _MESSAGES[state].format(**fmt), dev, tok.license_id_hex if tok else '',
                             tok.issued_at if tok else None, exp, remaining, now)

    def _token(self, code):
        """Tách + xác minh chữ ký (có cache vì xác minh Python thuần tốn vài ms)."""
        tok = codec.decode_code(code)
        key = tok.raw  # NC2: gồm cả giấy chứng nhận + danh sách gỡ quyền (đều nằm trong phần được ký)
        if key not in self._verified:
            if not tok.verify(self.public_key):
                raise ActivationError('signature', 'Mã kích hoạt không hợp lệ: không do quản trị viên phát hành '
                                                   'hoặc đã bị sửa nội dung.')
            self._verified[key] = True
        return tok

    @staticmethod
    def _check_terms(tok):
        if tok.version != tok.fmt or tok.product != codec.PRODUCT_NANGCOM:
            raise ActivationError('product', 'Mã kích hoạt không dành cho bộ công cụ Nàng Cơm phiên bản này.')
        if tok.expires_at - tok.issued_at != LICENSE_SECONDS:
            raise ActivationError('duration', 'Mã kích hoạt có thời hạn khác 20 ngày — không được chấp nhận.')

    def known_revocations(self, state=None):
        """Danh sách gỡ quyền mới nhất máy này biết (bản cài đặt hoặc nhận qua mã đã nhập); None = chưa có."""
        if state is None:
            try:
                state = self.store.load() or {}
            except StoreCorrupt:
                state = {}
        return chain.best(self.public_key, self._file_revocations, chain.revocations_from_hex(state.get('revocations')))

    @staticmethod
    def _revoked(tok, known):
        return bool(tok.issuer_id and known and known.contains(tok.issuer_id))

    def _high_water(self, state):
        return max(int(state.get('last_seen') or 0), int(self.store.mtime() or 0))

    def _save(self, state):
        try:
            self.store.save(state)
        except OSError as e:
            raise ActivationError('storage', f'Không lưu được trạng thái license: {e}') from None

    # ---------- API ----------
    def check_license(self):
        with self._lock:
            return self._check_license()

    def _check_license(self):
        now = int(self.clock())
        if not self.public_key:
            return self._status('no_public_key', now=now)
        try:
            self.device_id()
        except DeviceIdError as e:
            return self._status('device_error', now=now, detail=e)
        try:
            state = self.store.load()
        except StoreCorrupt:
            return self._status('corrupt', now=now)
        if not state or not state.get('code'):
            return self._status('not_activated', now=now)
        try:
            tok = self._token(state['code'])
            self._check_terms(tok)
        except (CodeFormatError, ActivationError):
            return self._status('invalid', now=now)
        if tok.device_id_text != self._device_id:
            return self._status('device_mismatch', tok, now)
        if self._revoked(tok, self.known_revocations(state)):
            return self._status('revoked', tok, now)
        high = self._high_water(state)
        if now < high - ROLLBACK_TOLERANCE or now < tok.issued_at - ISSUE_SKEW:
            return self._status('clock_error', tok, now, last_seen=format_time(max(high, tok.issued_at)))
        if now - int(state.get('last_seen') or 0) >= PERSIST_EVERY:
            state['last_seen'] = now
            try:
                self.store.save(state)
            except OSError:
                pass  # không ghi được mốc thời gian thì vẫn kiểm tra bình thường
        if now >= tok.expires_at:
            return self._status('expired', tok, now)
        return self._status('active', tok, now)

    def activate(self, code):
        with self._lock:
            return self._activate(code)

    def _activate(self, code):
        now = int(self.clock())
        if not self.public_key:
            raise ActivationError('no_public_key', _MESSAGES['no_public_key'])
        try:
            tok = self._token(code)
        except CodeFormatError as e:
            raise ActivationError('format', str(e)) from None
        self._check_terms(tok)
        try:
            dev = self.device_id()
        except DeviceIdError as e:
            raise ActivationError('device_error', _MESSAGES['device_error'].format(detail=e)) from None
        if tok.device_id_text != dev:
            raise ActivationError('device', f'Mã này được cấp cho thiết bị khác ({tok.device_id_text}), không dùng được '
                                            f'trên máy này. Mã thiết bị của máy này: {dev}.')
        try:
            state = self.store.load() or {}
        except StoreCorrupt:
            try:
                self.store.quarantine()
            except OSError:
                pass  # không đổi tên được thì ghi đè khi lưu
            state = {}
        stored = chain.revocations_from_hex(state.get('revocations'))
        known = chain.best(self.public_key, self._file_revocations, stored, tok.revocations)
        if known and known is not stored and (stored is None or known.seq > stored.seq):
            state['revocations'] = known.hex  # nhớ thông tin gỡ quyền (kể cả khi mã này bị từ chối)
            if self._revoked(tok, known) or state.get('code'):
                self._save(state)
        if self._revoked(tok, known):
            raise ActivationError('revoked', _MESSAGES['revoked'])
        lid = tok.license_id_hex
        used = list(state.get('used') or [])
        if lid in used:
            current = state.get('code')
            if current and codec.decode_code(current).license_id_hex == lid and now < tok.expires_at:
                return self.check_license()  # đang dùng đúng mã này: không đổi gì, không gia hạn
            self._log(state, now, lid, 'tu-choi:used')
            raise ActivationError('used', 'Mã này đã được sử dụng trên máy này. Mỗi mã chỉ dùng một lần — '
                                          'liên hệ quản trị viên để nhận mã mới.')
        if now >= tok.expires_at:
            self._log(state, now, lid, 'tu-choi:expired')
            raise ActivationError('expired', f'Mã đã hết hạn lúc {format_time(tok.expires_at)} (20 ngày kể từ khi phát '
                                             f'hành {format_time(tok.issued_at)}). Liên hệ quản trị viên để nhận mã mới.')
        if now < tok.issued_at - ISSUE_SKEW:
            raise ActivationError('not_yet_valid', f'Đồng hồ máy đang sớm hơn thời điểm phát hành mã '
                                                   f'({format_time(tok.issued_at)}). Hãy bật "Đặt giờ tự động" trong '
                                                   'Windows rồi thử lại.')
        high = self._high_water(state)
        if now < high - ROLLBACK_TOLERANCE:
            raise ActivationError('clock', f'Đồng hồ Windows đang lùi so với lần dùng trước ({format_time(high)}). '
                                           'Hãy chỉnh đúng giờ rồi thử lại.')
        used.append(lid)
        state.update(code=tok.code, activated_at=now, used=used[-MAX_USED:],
                     last_seen=max(now, int(state.get('last_seen') or 0)))
        state['log'] = (list(state.get('log') or []) + [{'t': now, 'id': lid, 'su_kien': 'kich-hoat'}])[-MAX_LOG:]
        self._save(state)
        return self.check_license()

    def _log(self, state, now, lid, event):
        """Ghi lần kích hoạt bị từ chối vào nhật ký cục bộ (không lưu mã)."""
        if not state.get('code') and not state.get('used'):
            return  # chưa có trạng thái thì không tạo file chỉ để ghi nhật ký
        state['log'] = (list(state.get('log') or []) + [{'t': now, 'id': lid, 'su_kien': event}])[-MAX_LOG:]
        try:
            self.store.save(state)
        except OSError:
            pass

    def remaining_time(self):
        st = self.check_license()
        return timedelta(seconds=st.remaining_seconds) if st.valid else None

    def is_valid(self):
        return self.check_license().valid

    def require(self, func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            st = self.check_license()
            if not st.valid:
                raise LicenseRequired(st)
            return func(*args, **kwargs)
        return wrapper


_default = None


def default_client():
    global _default
    if _default is None:
        _default = LicenseClient()
    return _default


def activate(code):
    return default_client().activate(code)


def check_license():
    return default_client().check_license()


def remaining_time():
    return default_client().remaining_time()
