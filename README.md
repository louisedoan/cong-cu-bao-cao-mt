# Công cụ MT — PO → Phiếu Xuất Kho (Nàng Cơm)

Đọc file PO (đơn đặt hàng từ các chuỗi siêu thị, PDF hoặc Excel), tra **DANH MỤC HH KÊNH MT** theo **mã vạch** để
điền **Phiếu Xuất Kho** của Nàng Cơm kèm **tải trọng (Kg)**. Web app cục bộ, chạy offline.

## Chạy
Nhấp đúp `Mo-cong-cu.bat` (hoặc `python app.py`). Lần đầu cần **mã kích hoạt 20 ngày** do quản trị viên cấp
(xem `HUONG-DAN.txt`). Đặt file danh mục + mẫu PXK vào thư mục `Dữ liệu`.

## Lưu ý
- Repo chỉ chứa **mã nguồn**; file Excel/PDF/dữ liệu bị `.gitignore` loại.
- Thư viện `licensing`, `openpyxl`, `pypdf` nằm trong `thu-vien` (vendored).
