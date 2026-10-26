"""Giao diện nhập mã cho các công cụ chạy bằng cửa sổ dòng lệnh (báo cáo TikTok).

ensure_licensed(tên công cụ) -> True nếu được phép chạy tiếp. Chưa có/hết license: mở hộp thoại Tk để nhập mã
(không có Tk thì hỏi trên dòng lệnh). Đặt biến môi trường NANGCOM_LICENSE_NONINTERACTIVE=1 để không hỏi gì
(chỉ báo trạng thái và trả về False) — dùng khi chạy tự động.
"""
import os

from .client import POLICY_TEXT, ActivationError, default_client

NONINTERACTIVE_ENV = 'NANGCOM_LICENSE_NONINTERACTIVE'


def _say(text):
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode('ascii', 'replace').decode('ascii'), flush=True)


def ensure_licensed(app_name, client=None):
    client = client or default_client()
    st = client.check_license()
    _say(f'[License] {st.message}')
    if st.valid:
        return True
    if os.environ.get(NONINTERACTIVE_ENV):
        _say(f'Mã thiết bị của máy này: {st.device_id or "-"}')
        ok = False
    else:
        try:
            ok = activation_dialog(app_name, client, st)
        except Exception:  # không mở được cửa sổ (không có Tk/màn hình) -> hỏi trên dòng lệnh
            ok = cli_prompt(app_name, client, st)
    if not ok:
        _say('Chưa có license hợp lệ — công cụ không chạy. Dữ liệu và báo cáo cũ vẫn giữ nguyên.')
    return ok


def cli_prompt(app_name, client, status):
    _say(f'\n=== KÍCH HOẠT LICENSE – {app_name} ===')
    if status.state in ('no_public_key', 'device_error'):
        return False
    _say(f'Mã thiết bị của máy này (gửi cho quản trị viên): {client.device_id()}')
    for _ in range(3):
        try:
            code = input('Dán mã kích hoạt rồi bấm Enter (để trống để thoát): ')
        except EOFError:
            return False
        if not code.strip():
            return False
        try:
            st = client.activate(code)
        except ActivationError as e:
            _say(f'(!) {e}')
            continue
        _say(f'[License] {st.message}')
        return True
    return False


def activation_dialog(app_name, client, status):
    import tkinter as tk
    from tkinter import messagebox, ttk

    result = {'ok': False}
    can_activate = status.state not in ('no_public_key', 'device_error')
    root = tk.Tk()
    root.title(f'Kích hoạt license – {app_name}')
    root.resizable(False, False)
    frm = ttk.Frame(root, padding=18)
    frm.grid(sticky='nsew')
    ttk.Label(frm, text=app_name, font=('Segoe UI', 13, 'bold')).grid(row=0, column=0, columnspan=3, sticky='w')
    ttk.Label(frm, text=status.message, wraplength=560, foreground='#B42318', font=('Segoe UI', 10)).grid(
        row=1, column=0, columnspan=3, sticky='w', pady=(6, 12))

    ttk.Label(frm, text='Mã thiết bị của máy này (gửi cho quản trị viên để xin mã):').grid(
        row=2, column=0, columnspan=3, sticky='w')
    dev = tk.StringVar(value=status.device_id if can_activate else '')
    ttk.Entry(frm, textvariable=dev, width=26, font=('Consolas', 12), state='readonly').grid(
        row=3, column=0, sticky='w', pady=(2, 12))

    def copy_dev():
        root.clipboard_clear()
        root.clipboard_append(dev.get())
        info.set('Đã sao chép Mã thiết bị.')

    ttk.Button(frm, text='Sao chép', command=copy_dev, state='normal' if can_activate else 'disabled').grid(
        row=3, column=1, sticky='w', padx=6, pady=(2, 12))

    ttk.Label(frm, text='Mã kích hoạt (dán nguyên mã, bắt đầu bằng NC1-):').grid(row=4, column=0, columnspan=3, sticky='w')
    txt = tk.Text(frm, width=70, height=4, font=('Consolas', 10), wrap='char')
    txt.grid(row=5, column=0, columnspan=3, sticky='we', pady=(2, 4))

    def paste():
        try:
            txt.delete('1.0', 'end')
            txt.insert('1.0', root.clipboard_get())
        except tk.TclError:
            info.set('Bộ nhớ tạm đang trống.')

    info = tk.StringVar()
    ttk.Label(frm, textvariable=info, wraplength=560, foreground='#B42318').grid(row=6, column=0, columnspan=3, sticky='w')

    def do_activate():
        try:
            st = client.activate(txt.get('1.0', 'end'))
        except ActivationError as e:
            info.set(str(e))
            return
        result['ok'] = True
        messagebox.showinfo('Đã kích hoạt', st.message, parent=root)
        root.destroy()

    bar = ttk.Frame(frm)
    bar.grid(row=7, column=0, columnspan=3, sticky='e', pady=(12, 0))
    state = 'normal' if can_activate else 'disabled'
    ttk.Button(bar, text='Dán mã', command=paste, state=state).pack(side='left', padx=4)
    ttk.Button(bar, text='Chính sách offline',
               command=lambda: messagebox.showinfo('Chính sách license', POLICY_TEXT, parent=root)).pack(side='left', padx=4)
    ttk.Button(bar, text='Kích hoạt', command=do_activate, state=state).pack(side='left', padx=4)
    ttk.Button(bar, text='Đóng', command=root.destroy).pack(side='left', padx=4)

    root.attributes('-topmost', True)
    root.after(400, lambda: root.attributes('-topmost', False))
    txt.focus_set()
    root.mainloop()
    return result['ok']
