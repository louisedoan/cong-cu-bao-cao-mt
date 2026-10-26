'use strict';
const $ = (s, r = document) => r.querySelector(s);
const el = (h) => { const d = document.createElement('div'); d.innerHTML = h.trim(); return d.firstChild; };
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = (n) => (Number(n) || 0).toLocaleString('vi-VN');

async function api(path, body) {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || ('Lỗi ' + r.status));
  return data;
}
async function getJson(path) { const r = await fetch(path); return r.json(); }
function toast(msg, bad) { const t = el(`<div class="toast ${bad ? 'bad' : ''}">${esc(msg)}</div>`); $('#toasts').appendChild(t); setTimeout(() => t.remove(), 5000); }

let STATE = { tab: 'po', parsed: null, path: '' };

async function refresh() {
  const lic = await getJson('/api/license');
  if (!lic.valid) return licenseScreen(lic);
  mainScreen();
}

function licenseScreen(lic) {
  $('#app').innerHTML = '';
  const box = el(`<div class="card lic"><h2>Kích hoạt công cụ MT</h2>
    <div class="alert ${lic.state === 'expired' ? 'warn' : 'bad'}">${esc(lic.message)}</div>
    <label>Mã thiết bị của máy này — gửi cho quản trị viên để xin mã</label>
    <div class="row"><input id="dev" readonly value="${esc(lic.device_id || '')}"><button id="cpdev">Sao chép</button></div>
    <label>Mã kích hoạt (dán nguyên mã, bắt đầu bằng NC)</label>
    <textarea id="code" rows="4" placeholder="NC…"></textarea>
    <button id="act" class="primary">Kích hoạt</button>
    <p class="muted">Dữ liệu của bạn được giữ nguyên. Hiệu lực 20 ngày tính từ lúc quản trị viên phát hành mã.</p></div>`);
  $('#app').appendChild(box);
  $('#cpdev').onclick = () => { navigator.clipboard.writeText(lic.device_id || ''); toast('Đã sao chép.'); };
  $('#act').onclick = async () => {
    try { await api('/api/license/activate', { code: $('#code').value }); toast('Kích hoạt thành công.'); refresh(); }
    catch (e) { toast(e.message, true); }
  };
}

function mainScreen() {
  $('#app').innerHTML = `
    <header><h1>Công cụ MT — PO → Phiếu Xuất Kho</h1>
      <nav>${[['po', 'Tạo PXK từ PO'], ['dm', 'Danh mục SP'], ['kh', 'Khách / cửa hàng']].map(([k, t]) =>
    `<button data-tab="${k}" class="${STATE.tab === k ? 'active' : ''}">${t}</button>`).join('')}</nav></header>
    <main id="main"></main>`;
  document.querySelectorAll('[data-tab]').forEach(b => b.onclick = () => { STATE.tab = b.dataset.tab; mainScreen(); });
  if (STATE.tab === 'po') poTab();
  else if (STATE.tab === 'dm') catalogTab();
  else customerTab();
}

async function poTab() {
  const { files } = await api('/api/po/list', {});
  $('#main').innerHTML = `<div class="card">
    <label>Chọn file PO (đặt file vào thư mục "Dữ liệu" hoặc thư mục công cụ)</label>
    <div class="row"><select id="pofile">${files.map(f => `<option value="${esc(f)}">${esc(f.split(/[\\/]/).pop())}</option>`).join('') || '<option value="">(chưa có file PO)</option>'}</select>
      <button id="doc" class="primary">Đọc PO</button></div></div>
    <div id="preview"></div>`;
  $('#doc').onclick = async () => {
    const path = $('#pofile').value;
    if (!path) return toast('Chưa có file PO.', true);
    try { STATE.parsed = await api('/api/po/parse', { path }); STATE.path = path; renderPreview(); }
    catch (e) { toast(e.message, true); }
  };
}

function renderPreview() {
  const p = STATE.parsed, h = p.header;
  const hf = (k, label) => `<label>${label}</label><input data-h="${k}" value="${esc(h[k] || '')}">`;
  $('#preview').innerHTML = `<div class="card"><h3>Thông tin nơi nhận (sửa được)</h3>
    <div class="grid2">${hf('don_vi_nhan', 'Đơn vị nhận')}${hf('mst', 'MST')}${hf('nguoi_nhan', 'Người nhận')}
      ${hf('so_po', 'Số PO')}${hf('dia_chi', 'Địa chỉ nhận')}${hf('ly_do', 'Lý do xuất')}</div></div>
    <div class="card"><h3>Hàng hóa (chuỗi: ${esc(p.chain)}) — tải trọng: ${fmt(p.tai_trong)} Kg</h3>
    <table><thead><tr><th>Mã vạch</th><th>Tên</th><th class="n">SL (PO)</th><th>ĐVT</th><th class="n">Số thùng</th><th class="n">Tải trọng</th></tr></thead><tbody>
    ${p.rows.map(r => r.matched
    ? `<tr><td>${esc(r.barcode)}</td><td>${esc(r.ten)}</td><td class="n">${fmt(r.so_luong)}</td><td>${esc(r.dvt_po)}</td><td class="n">${r.so_thung}</td><td class="n">${r.tai_trong_dong}</td></tr>`
    : `<tr class="bad"><td>${esc(r.barcode)}</td><td colspan="5">MÃ LẠ — chưa có trong danh mục. <button class="addbc" data-bc="${esc(r.barcode)}">+ Thêm vào danh mục</button></td></tr>`).join('')}
    </tbody></table>
    ${p.unknown.length ? `<div class="alert warn">Còn ${p.unknown.length} mã lạ — thêm vào danh mục rồi đọc lại, hoặc vẫn tạo PXK cho phần đã khớp.</div>` : ''}
    <button id="makepxk" class="primary">Tạo PXK</button></div>`;
  document.querySelectorAll('.addbc').forEach(b => b.onclick = () => addBarcodeForm(b.dataset.bc));
  $('#makepxk').onclick = async () => {
    const header = {};
    document.querySelectorAll('[data-h]').forEach(i => header[i.dataset.h] = i.value);
    try {
      const res = await api('/api/po/pxk', { path: STATE.path, header });
      toast('Đã tạo PXK: ' + res.file.split(/[\\/]/).pop());
      await api('/api/open', { path: res.file }).catch(() => { });
    } catch (e) { toast(e.message, true); }
  };
}

function addBarcodeForm(bc) {
  const f = ['ten', 'dvt', 'quy_cach', 'gia_chai', 'gia_thung', 'tai_trong'];
  const labels = { ten: 'Tên hàng', dvt: 'ĐVT', quy_cach: 'Quy cách', gia_chai: 'Giá chai', gia_thung: 'Giá thùng (gồm VAT)', tai_trong: 'Tải trọng/thùng' };
  const box = el(`<div class="modal"><div class="card"><h3>Thêm mã ${esc(bc)} vào danh mục</h3>
    ${f.map(k => `<label>${labels[k]}</label><input data-f="${k}">`).join('')}
    <div class="row"><button id="sv" class="primary">Lưu</button><button id="cx">Hủy</button></div></div></div>`);
  document.body.appendChild(box);
  $('#cx', box).onclick = () => box.remove();
  $('#sv', box).onclick = async () => {
    const item = { barcode: bc };
    box.querySelectorAll('[data-f]').forEach(i => item[i.dataset.f] = i.value);
    try {
      await api('/api/catalog/add', { item });
      box.remove();
      toast('Đã thêm. Đọc lại PO.');
      STATE.parsed = await api('/api/po/parse', { path: STATE.path });
      renderPreview();
    } catch (e) { toast(e.message, true); }
  };
}

async function catalogTab() {
  const { items } = await api('/api/catalog/list', {});
  $('#main').innerHTML = `<div class="card"><h3>Danh mục sản phẩm (${items.length})</h3>
    <table><thead><tr><th>Mã vạch</th><th>Tên</th><th>ĐVT</th><th class="n">QC</th><th class="n">Giá thùng</th><th class="n">Tải trọng</th><th></th></tr></thead><tbody>
    ${items.map(p => `<tr><td>${esc(p.barcode)}</td><td>${esc(p.ten)}</td><td>${esc(p.dvt)}</td><td class="n">${p.quy_cach}</td><td class="n">${fmt(p.gia_thung)}</td><td class="n">${p.tai_trong}</td>
      <td><button class="del" data-bc="${esc(p.barcode)}">Xóa</button></td></tr>`).join('')}</tbody></table></div>`;
  document.querySelectorAll('.del').forEach(b => b.onclick = async () => {
    try { await api('/api/catalog/delete', { barcode: b.dataset.bc }); catalogTab(); } catch (e) { toast(e.message, true); }
  });
}

async function customerTab() {
  const { items } = await api('/api/customers/list', {});
  $('#main').innerHTML = `<div class="card"><h3>Khách / cửa hàng (${items.length})</h3>
    <div class="grid2"><input id="c_store" placeholder="Cửa hàng (vd EMART PHI)"><input id="c_ten" placeholder="Tên pháp nhân">
      <input id="c_mst" placeholder="MST"><input id="c_dc" placeholder="Địa chỉ nhận"></div>
    <button id="c_add" class="primary">Thêm / cập nhật</button>
    <table><thead><tr><th>Cửa hàng</th><th>Tên pháp nhân</th><th>MST</th><th>Địa chỉ</th><th></th></tr></thead><tbody>
    ${items.map(c => `<tr><td>${esc(c.store)}</td><td>${esc(c.ten_phap_nhan)}</td><td>${esc(c.mst)}</td><td>${esc(c.dia_chi)}</td>
      <td><button class="del" data-s="${esc(c.store)}">Xóa</button></td></tr>`).join('')}</tbody></table></div>`;
  $('#c_add').onclick = async () => {
    const item = { store: $('#c_store').value, ten_phap_nhan: $('#c_ten').value, mst: $('#c_mst').value, dia_chi: $('#c_dc').value };
    if (!item.store) return toast('Nhập tên cửa hàng.', true);
    try { await api('/api/customers/add', { item }); customerTab(); } catch (e) { toast(e.message, true); }
  };
  document.querySelectorAll('.del').forEach(b => b.onclick = async () => {
    try { await api('/api/customers/delete', { store: b.dataset.s }); customerTab(); } catch (e) { toast(e.message, true); }
  });
}

if (!document.getElementById('toasts')) { const t = document.createElement('div'); t.id = 'toasts'; document.body.appendChild(t); }
refresh();
