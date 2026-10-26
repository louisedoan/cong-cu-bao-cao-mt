"""Dòng lệnh license trên máy người dùng.

python -m licensing status          trạng thái + thời gian còn lại
python -m licensing device-id       in Mã thiết bị để gửi quản trị viên
python -m licensing activate <mã>   nhập mã kích hoạt
python -m licensing policy          chính sách license offline
"""
import sys

from .client import POLICY_TEXT, ActivationError, default_client


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    sys.stdout.reconfigure(encoding='utf-8')
    cmd = argv[0] if argv else 'status'
    client = default_client()
    if cmd == 'device-id':
        print(client.device_id())
        return 0
    if cmd == 'policy':
        print(POLICY_TEXT)
        return 0
    if cmd == 'activate':
        code = ' '.join(argv[1:]) or input('Dán mã kích hoạt: ')
        try:
            st = client.activate(code)
        except ActivationError as e:
            print(f'Từ chối ({e.reason}): {e}')
            return 2
        print(st.message)
        return 0
    if cmd == 'status':
        st = client.check_license()
        print(st.message)
        print('Mã thiết bị:', st.device_id or '-')
        if st.license_id:
            d = st.to_dict()
            print('License ID:', st.license_id, '| Phát hành:', d['issued_text'], '| Hết hạn:', d['expires_text'])
        return 0 if st.valid else 1
    print(__doc__)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
