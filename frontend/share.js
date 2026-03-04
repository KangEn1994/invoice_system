function getTokenFromQuery() {
  const url = new URL(window.location.href);
  return url.searchParams.get('token') || '';
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function setMsg(text) {
  document.getElementById('share-msg').textContent = text;
}

function amountTextToCents(value) {
  const text = String(value ?? '').trim();
  if (!text) return 0;

  const cleaned = text.replace(/[¥￥,]/g, '').trim();
  const match = cleaned.match(/^(\d+)(?:\.(\d{1,2}))?$/);
  if (!match) return 0;

  const intPart = Number(match[1]) || 0;
  const fracRaw = (match[2] || '').padEnd(2, '0').slice(0, 2);
  const fracPart = Number(fracRaw) || 0;
  return intPart * 100 + fracPart;
}

function formatCents(cents) {
  return (cents / 100).toFixed(2);
}

async function loadShare(token) {
  const resp = await fetch(`/s/${encodeURIComponent(token)}`);
  if (!resp.ok) {
    let detail = `${resp.status}`;
    try {
      const body = await resp.json();
      detail = body.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return resp.json();
}

function renderShare(token, data) {
  document.getElementById('share-title').textContent = data.title || '发票分享';
  const totalCents = (data.items || []).reduce((sum, item) => sum + amountTextToCents(item.total_amount), 0);
  document.getElementById('share-total-amount').textContent = `合计金额：${formatCents(totalCents)}`;

  const tbody = document.getElementById('share-items-tbody');
  tbody.innerHTML = (data.items || []).map(item => `
    <tr>
      <td>${item.invoice_id}</td>
      <td>${escapeHtml(item.file_name || '')}</td>
      <td>${escapeHtml(item.company_name || '')}</td>
      <td>${escapeHtml(item.invoice_number || '')}</td>
      <td>${escapeHtml(item.issue_date || '')}</td>
      <td>${escapeHtml(item.total_amount || '')}</td>
      <td><a href="/s/${encodeURIComponent(token)}/file/${item.invoice_id}">下载</a></td>
    </tr>
  `).join('');

  document.getElementById('download-zip-btn').onclick = () => {
    window.location.href = `/s/${encodeURIComponent(token)}/zip`;
  };

  setMsg(`共 ${data.items.length} 条发票，合计 ${formatCents(totalCents)}`);
}

async function init() {
  const token = getTokenFromQuery();
  if (!token) {
    setMsg('链接缺少 token');
    return;
  }

  try {
    const data = await loadShare(token);
    renderShare(token, data);
  } catch (e) {
    setMsg(`加载失败：${e.message}`);
  }
}

init();
