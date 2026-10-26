"""Chuỗi tin cậy chủ sở hữu > ADMIN (offline).

- Khóa gốc = khóa của chủ sở hữu (PUBLIC_KEY_HEX). Chỉ khóa gốc ký được giấy chứng nhận ADMIN và danh sách gỡ quyền.
- Giấy chứng nhận ADMIN ("NCA1-…"): admin_id(4) + public key ADMIN(32) + chữ ký gốc(64). Không có hạn, không chứa tên.
- Danh sách gỡ quyền: seq(4) + count(1) + admin_id(4 x count) + chữ ký gốc(64). Bản có seq cao hơn thay bản cũ.
- Mã yêu cầu ("NCR1-…"): public key ADMIN(32) + 4 byte kiểm tra (bắt lỗi gõ/chép thiếu). Không bí mật.
Mỗi loại chữ ký có tiền tố phân miền riêng nên chữ ký loại này không dùng được làm loại khác.
"""
import hashlib
import os
import struct
from dataclasses import dataclass

from . import ed25519
from .codec import _CONFUSABLE, _b32, _unb32, group

CERT_DOMAIN = b'NC-ADMIN-CERT-v1|'
REVOKE_DOMAIN = b'NC-REVOKE-v1|'
CERT_PREFIX = 'NCA1'
REQUEST_PREFIX = 'NCR1'
ID_BYTES = 4
CERT_SIZE = ID_BYTES + 32 + 64
MAX_REVOKED = 255
_REV_HEAD = struct.Struct('>IB')


def _clean(text, prefix):
    """Bỏ khoảng trắng, dấu gạch, chữ thường và tiền tố; sửa ký tự dễ nhầm (0/1/8)."""
    s = ''.join(str(text or '').split()).replace('-', '').upper()
    if s.startswith(prefix):
        s = s[len(prefix):]
    return s.translate(_CONFUSABLE)


def _decode(text, prefix, size, what):
    s = _clean(text, prefix)
    try:
        raw = _unb32(s)
    except (ValueError, TypeError):
        raise ValueError(f'{what} chứa ký tự không hợp lệ.') from None
    if len(raw) != size or _b32(raw) != s:
        raise ValueError(f'{what} không đúng định dạng — hãy sao chép đủ cả mã.')
    return raw


def _checksum(public):
    return hashlib.sha256(b'NC-REQ|' + public).digest()[:4]


# ---------------- mã yêu cầu cấp quyền ADMIN ----------------

def request_text(admin_public):
    return f'{REQUEST_PREFIX}-' + group(_b32(bytes(admin_public) + _checksum(bytes(admin_public))))


def parse_request(text):
    """Mã yêu cầu -> public key ADMIN (32 byte). Sai/gõ nhầm -> ValueError."""
    raw = _decode(text, REQUEST_PREFIX, 36, 'Mã yêu cầu')
    public, check = raw[:32], raw[32:]
    if _checksum(public) != check:
        raise ValueError('Mã yêu cầu bị sai hoặc chép thiếu — nhờ người yêu cầu gửi lại.')
    return public


# ---------------- giấy chứng nhận ADMIN ----------------

@dataclass(frozen=True)
class AdminCert:
    admin_id: bytes
    admin_public: bytes
    signature: bytes

    @property
    def admin_id_hex(self):
        return self.admin_id.hex().upper()

    @property
    def raw(self):
        return self.admin_id + self.admin_public + self.signature

    @property
    def text(self):
        return f'{CERT_PREFIX}-' + group(_b32(self.raw))

    def verify(self, root_public):
        return bool(root_public) and ed25519.verify(root_public, CERT_DOMAIN + self.admin_id + self.admin_public,
                                                    self.signature)


def cert_from_raw(raw):
    if len(raw) != CERT_SIZE:
        raise ValueError('Giấy chứng nhận ADMIN không đúng định dạng.')
    return AdminCert(raw[:ID_BYTES], raw[ID_BYTES:ID_BYTES + 32], raw[ID_BYTES + 32:])


def issue_cert(root_signer, admin_public, admin_id=None):
    admin_id = admin_id or os.urandom(ID_BYTES)
    return AdminCert(admin_id, bytes(admin_public), root_signer.sign(CERT_DOMAIN + admin_id + bytes(admin_public)))


def parse_cert(text):
    return cert_from_raw(_decode(text, CERT_PREFIX, CERT_SIZE, 'Giấy chứng nhận ADMIN'))


# ---------------- danh sách gỡ quyền ----------------

@dataclass(frozen=True)
class RevocationList:
    seq: int
    ids: tuple
    signature: bytes

    @property
    def body(self):
        return _REV_HEAD.pack(self.seq, len(self.ids)) + b''.join(self.ids)

    @property
    def raw(self):
        return self.body + self.signature

    @property
    def hex(self):
        return self.raw.hex()

    def verify(self, root_public):
        return bool(root_public) and ed25519.verify(root_public, REVOKE_DOMAIN + self.body, self.signature)

    def contains(self, admin_id):
        return bytes(admin_id or b'') in self.ids


def sign_revocations(root_signer, seq, ids):
    ids = tuple(sorted({bytes(i) for i in ids}))
    if len(ids) > MAX_REVOKED or any(len(i) != ID_BYTES for i in ids):
        raise ValueError('Danh sách gỡ quyền không hợp lệ.')
    body = _REV_HEAD.pack(int(seq), len(ids)) + b''.join(ids)
    return RevocationList(int(seq), ids, root_signer.sign(REVOKE_DOMAIN + body))


def parse_revocations(raw):
    """Đọc 1 danh sách ở đầu `raw` -> (RevocationList chưa xác minh, phần còn lại). Thiếu byte -> ValueError."""
    if len(raw) < _REV_HEAD.size:
        raise ValueError('Danh sách gỡ quyền không đúng định dạng.')
    seq, n = _REV_HEAD.unpack(raw[:_REV_HEAD.size])
    end = _REV_HEAD.size + n * ID_BYTES + 64
    if len(raw) < end:
        raise ValueError('Danh sách gỡ quyền không đúng định dạng.')
    ids = tuple(raw[_REV_HEAD.size + i * ID_BYTES:_REV_HEAD.size + (i + 1) * ID_BYTES] for i in range(n))
    return RevocationList(seq, ids, raw[end - 64:end]), raw[end:]


def revocations_from_hex(value):
    """Hex -> RevocationList (chưa xác minh); rỗng/sai định dạng -> None."""
    try:
        rl, rest = parse_revocations(bytes.fromhex(value or ''))
    except (ValueError, TypeError):
        return None
    return None if rest else rl


def best(root_public, *lists):
    """Bản hợp lệ (đúng chữ ký gốc) có seq cao nhất; không có -> None."""
    valid = [x for x in lists if x is not None and x.verify(root_public)]
    return max(valid, key=lambda x: x.seq) if valid else None
