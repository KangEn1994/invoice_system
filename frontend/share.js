function getTokenFromQuery() {
  const url = new URL(window.location.href);
  return url.searchParams.get('token') || '';
}

function escapeHtml(str) {
  return (str || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function setMsg(text) {
  document.getElementById('share-msg').textContent = text;
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

  setMsg(`共 ${data.items.length} 条发票`);
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
