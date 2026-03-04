const ACCESS_KEY = 'invoice_access_token';
const REFRESH_KEY = 'invoice_refresh_token';
const SYSTEM_BASE_URL_KEY = 'invoice_system_base_url';

const state = {
  tags: [],
  invoices: [],
  selected: new Set(),
  editingInvoiceId: null,
};

function getAccessToken() {
  return localStorage.getItem(ACCESS_KEY);
}

function getRefreshToken() {
  return localStorage.getItem(REFRESH_KEY);
}

function saveTokens(access, refresh) {
  localStorage.setItem(ACCESS_KEY, access);
  localStorage.setItem(REFRESH_KEY, refresh);
}

function clearTokens() {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function normalizeBaseUrlInput(raw) {
  const text = (raw || '').trim();
  if (!text) return location.origin;
  return text.replace(/\/+$/, '');
}

function getSystemBaseUrl() {
  return normalizeBaseUrlInput(localStorage.getItem(SYSTEM_BASE_URL_KEY) || location.origin);
}

function saveSystemBaseUrl(value) {
  const normalized = normalizeBaseUrlInput(value);
  localStorage.setItem(SYSTEM_BASE_URL_KEY, normalized);
  const input = document.getElementById('system-base-url');
  if (input) input.value = normalized;
  return normalized;
}

function buildShareUrlByToken(token) {
  return `${getSystemBaseUrl()}/share.html?token=${encodeURIComponent(token)}`;
}

function setLoggedIn(loggedIn) {
  document.getElementById('login-section').classList.toggle('hidden', loggedIn);
  document.getElementById('app-section').classList.toggle('hidden', !loggedIn);
}

function updateSelectedCount() {
  setText('selected-count', `已选择 ${state.selected.size} 条`);
}

async function refreshToken() {
  const refresh = getRefreshToken();
  if (!refresh) return false;

  const resp = await fetch('/api/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refresh }),
  });

  if (!resp.ok) {
    clearTokens();
    return false;
  }

  const data = await resp.json();
  saveTokens(data.access_token, data.refresh_token);
  return true;
}

async function apiFetch(url, options = {}, retry = true) {
  const headers = new Headers(options.headers || {});
  const token = getAccessToken();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const resp = await fetch(url, { ...options, headers });
  if (resp.status === 401 && retry && getRefreshToken()) {
    const ok = await refreshToken();
    if (ok) return apiFetch(url, options, false);
  }

  if (!resp.ok) {
    let detail = `${resp.status}`;
    try {
      const body = await resp.json();
      detail = body.detail || JSON.stringify(body);
    } catch (_) {
      const text = await resp.text();
      if (text) detail = text;
    }
    throw new Error(detail);
  }
  return resp;
}

async function login(username, password) {
  const resp = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail || '登录失败');
  }

  const data = await resp.json();
  saveTokens(data.access_token, data.refresh_token);
}

async function logout() {
  const refresh = getRefreshToken();
  if (refresh) {
    await fetch('/api/auth/logout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refresh }),
    }).catch(() => {});
  }
  clearTokens();
  setLoggedIn(false);
}

async function loadMe() {
  const resp = await apiFetch('/api/auth/me');
  const me = await resp.json();
  setText('me-label', `当前用户：${me.username}`);
}

function getFilterValues() {
  return {
    q: document.getElementById('filter-q').value.trim(),
    company_name: document.getElementById('filter-company').value.trim(),
    invoice_number: document.getElementById('filter-number').value.trim(),
    date_from: document.getElementById('filter-date-from').value,
    date_to: document.getElementById('filter-date-to').value,
    amount_min: document.getElementById('filter-amount-min').value,
    amount_max: document.getElementById('filter-amount-max').value,
    ocr_status: document.getElementById('filter-ocr-status').value,
    tag_ids: document.getElementById('filter-tag-id').value,
    sort_by: document.getElementById('filter-sort-by').value,
    sort_order: document.getElementById('filter-sort-order').value,
  };
}

function collectFilterParams() {
  const values = getFilterValues();
  const params = new URLSearchParams();

  if (values.q) params.set('q', values.q);
  if (values.company_name) params.set('company_name', values.company_name);
  if (values.invoice_number) params.set('invoice_number', values.invoice_number);
  if (values.date_from) params.set('date_from', values.date_from);
  if (values.date_to) params.set('date_to', values.date_to);
  if (values.amount_min) params.set('amount_min', values.amount_min);
  if (values.amount_max) params.set('amount_max', values.amount_max);
  if (values.ocr_status) params.set('ocr_status', values.ocr_status);
  if (values.tag_ids) params.set('tag_ids', values.tag_ids);

  params.set('sort_by', values.sort_by || 'created_at');
  params.set('sort_order', values.sort_order || 'desc');
  params.set('page', '1');
  params.set('page_size', '100');
  return params;
}

function buildShareFilterPayload(title) {
  const values = getFilterValues();
  const payload = { title };

  ['q', 'company_name', 'invoice_number', 'date_from', 'date_to', 'ocr_status'].forEach(k => {
    if (values[k]) payload[k] = values[k];
  });

  if (values.amount_min) payload.amount_min = values.amount_min;
  if (values.amount_max) payload.amount_max = values.amount_max;
  if (values.tag_ids) payload.tag_ids = [Number(values.tag_ids)];

  return payload;
}

function invoiceTagsToText(tags) {
  return (tags || []).map(t => t.name).join(', ');
}

function getOcrError(inv) {
  const raw = inv && inv.ocr_raw ? inv.ocr_raw : null;
  if (!raw) return '';
  return raw.error || raw.engine_init_error || '';
}

function parseIdListInput(raw) {
  const text = (raw || '').trim();
  if (!text) return [];
  return text.split(',').map(part => Number(part.trim())).filter(x => Number.isInteger(x) && x > 0);
}

async function loadTags() {
  const resp = await apiFetch('/api/tags');
  state.tags = await resp.json();
  renderTagOptions();
}

function renderTagOptions() {
  const uploadSelect = document.getElementById('upload-tag-ids');
  const filterSelect = document.getElementById('filter-tag-id');
  const batchSelect = document.getElementById('batch-tag-ids');
  const batchSetBtn = document.getElementById('batch-set-tags-btn');

  const optionsHtml = state.tags.map(tag => `<option value="${tag.id}">${escapeHtml(tag.name)} (#${tag.id})</option>`).join('');

  uploadSelect.innerHTML = optionsHtml || '<option value="" disabled>暂无标签</option>';
  batchSelect.innerHTML = optionsHtml || '<option value="" disabled>暂无标签，先新增标签</option>';
  filterSelect.innerHTML = '<option value="">全部标签</option>' + optionsHtml;
  if (batchSetBtn) {
    batchSetBtn.disabled = state.tags.length === 0;
  }

  const tagList = document.getElementById('tag-list');
  tagList.innerHTML = state.tags.map(tag => `
    <span class="tag-chip">
      ${escapeHtml(tag.name)} (#${tag.id})
      <button data-del-tag="${tag.id}" class="small danger" type="button">删</button>
    </span>
  `).join('');

  document.querySelectorAll('[data-del-tag]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-del-tag');
      if (!confirm('确认删除该标签？')) return;
      try {
        await apiFetch(`/api/tags/${id}`, { method: 'DELETE' });
        await loadTags();
        await loadInvoices();
      } catch (e) {
        alert(`删除失败：${e.message}`);
      }
    });
  });
}

async function downloadInvoiceFile(id, fileName) {
  const resp = await apiFetch(`/api/invoices/${id}/file`);
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName || `invoice_${id}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

async function rerunOCR(id) {
  await apiFetch(`/api/invoices/${id}/ocr`, { method: 'POST' });
  await loadInvoices();
}

async function deleteInvoice(id) {
  await apiFetch(`/api/invoices/${id}`, { method: 'DELETE' });
  state.selected.delete(id);
  updateSelectedCount();
  await loadInvoices();
}

function normalizeAmountInput(raw) {
  const text = (raw || '').trim();
  if (!text) return null;
  const cleaned = text.replace(/[¥￥,元]/g, '').trim();
  if (!/^\d+(?:\.\d{1,2})?$/.test(cleaned)) {
    throw new Error('金额格式错误，应为数字或两位小数');
  }
  return cleaned;
}

function openEditForm(inv) {
  state.editingInvoiceId = inv.id;
  document.getElementById('edit-id').value = String(inv.id);
  document.getElementById('edit-company-name').value = inv.company_name || '';
  document.getElementById('edit-tax-id').value = inv.tax_id || '';
  document.getElementById('edit-invoice-number').value = inv.invoice_number || '';
  document.getElementById('edit-issue-date').value = inv.issue_date || '';
  document.getElementById('edit-item-name').value = inv.item_name || '';
  document.getElementById('edit-total-amount').value = inv.total_amount || '';
  setText('edit-msg', '');
  document.getElementById('edit-panel').classList.remove('hidden');
}

function closeEditForm() {
  state.editingInvoiceId = null;
  document.getElementById('edit-form').reset();
  document.getElementById('edit-panel').classList.add('hidden');
  setText('edit-msg', '');
}

function collectEditPayload() {
  const issueDateRaw = document.getElementById('edit-issue-date').value.trim();
  const amountRaw = document.getElementById('edit-total-amount').value;
  return {
    company_name: document.getElementById('edit-company-name').value.trim() || null,
    tax_id: document.getElementById('edit-tax-id').value.trim().toUpperCase() || null,
    invoice_number: document.getElementById('edit-invoice-number').value.trim() || null,
    issue_date: issueDateRaw || null,
    item_name: document.getElementById('edit-item-name').value.trim() || null,
    total_amount: normalizeAmountInput(amountRaw),
  };
}

async function submitEditForm(evt) {
  evt.preventDefault();
  if (!state.editingInvoiceId) return;
  const payload = collectEditPayload();
  await apiFetch(`/api/invoices/${state.editingInvoiceId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  closeEditForm();
  await loadInvoices();
}

async function editInvoiceTags(inv) {
  const currentIds = (inv.tags || []).map(t => t.id);
  const raw = prompt(
    `输入标签ID，逗号分隔。可用标签：${state.tags.map(t => `${t.id}:${t.name}`).join(' | ')}`,
    currentIds.join(','),
  );
  if (raw === null) return;

  const tagIds = parseIdListInput(raw);
  await apiFetch(`/api/invoices/${inv.id}/tags`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tag_ids: tagIds }),
  });

  await loadInvoices();
}

function renderInvoices() {
  const tbody = document.getElementById('invoice-tbody');
  tbody.innerHTML = state.invoices.map(inv => {
    const checked = state.selected.has(inv.id) ? 'checked' : '';
    const ocrError = getOcrError(inv);
    const ocrCell = inv.ocr_status === 'failed'
      ? `${escapeHtml(inv.ocr_status || '')}${ocrError ? ` <button class="small danger" data-ocr-error-id="${inv.id}" type="button">原因</button>` : ''}`
      : escapeHtml(inv.ocr_status || '');
    return `
      <tr>
        <td><input type="checkbox" data-invoice-id="${inv.id}" ${checked} /></td>
        <td>${inv.id}</td>
        <td>${escapeHtml(inv.company_name || '')}</td>
        <td>${escapeHtml(inv.tax_id || '')}</td>
        <td>${escapeHtml(inv.invoice_number || '')}</td>
        <td>${escapeHtml(inv.issue_date || '')}</td>
        <td>${escapeHtml(inv.item_name || '')}</td>
        <td>${escapeHtml(inv.total_amount || '')}</td>
        <td>${escapeHtml(invoiceTagsToText(inv.tags))}</td>
        <td>${ocrCell}</td>
        <td>
          <button class="small" data-download-id="${inv.id}" type="button">下载</button>
          <button class="small" data-ocr-id="${inv.id}" type="button">重识别</button>
          <button class="small" data-edit-id="${inv.id}" type="button">编辑</button>
          <button class="small" data-tag-id="${inv.id}" type="button">标签</button>
          <button class="small danger" data-del-id="${inv.id}" type="button">删除</button>
        </td>
      </tr>
    `;
  }).join('');

  document.querySelectorAll('[data-invoice-id]').forEach(el => {
    el.addEventListener('change', () => {
      const id = Number(el.getAttribute('data-invoice-id'));
      if (el.checked) state.selected.add(id);
      else state.selected.delete(id);
      updateSelectedCount();
    });
  });

  document.querySelectorAll('[data-download-id]').forEach(el => {
    el.addEventListener('click', async () => {
      const id = Number(el.getAttribute('data-download-id'));
      const inv = state.invoices.find(x => x.id === id);
      try {
        await downloadInvoiceFile(id, inv?.file_name);
      } catch (e) {
        alert(`下载失败：${e.message}`);
      }
    });
  });

  document.querySelectorAll('[data-ocr-id]').forEach(el => {
    el.addEventListener('click', async () => {
      const id = Number(el.getAttribute('data-ocr-id'));
      try {
        await rerunOCR(id);
      } catch (e) {
        alert(`重识别失败：${e.message}`);
      }
    });
  });

  document.querySelectorAll('[data-ocr-error-id]').forEach(el => {
    el.addEventListener('click', () => {
      const id = Number(el.getAttribute('data-ocr-error-id'));
      const inv = state.invoices.find(x => x.id === id);
      const reason = getOcrError(inv);
      alert(reason || '未记录具体错误，请查看后端日志');
    });
  });

  document.querySelectorAll('[data-edit-id]').forEach(el => {
    el.addEventListener('click', () => {
      const id = Number(el.getAttribute('data-edit-id'));
      const inv = state.invoices.find(x => x.id === id);
      if (!inv) return;
      openEditForm(inv);
    });
  });

  document.querySelectorAll('[data-tag-id]').forEach(el => {
    el.addEventListener('click', async () => {
      const id = Number(el.getAttribute('data-tag-id'));
      const inv = state.invoices.find(x => x.id === id);
      if (!inv) return;
      try {
        await editInvoiceTags(inv);
      } catch (e) {
        alert(`设置标签失败：${e.message}`);
      }
    });
  });

  document.querySelectorAll('[data-del-id]').forEach(el => {
    el.addEventListener('click', async () => {
      const id = Number(el.getAttribute('data-del-id'));
      if (!confirm(`确认删除发票 #${id}？`)) return;
      try {
        await deleteInvoice(id);
      } catch (e) {
        alert(`删除失败：${e.message}`);
      }
    });
  });
}

async function loadInvoices() {
  const params = collectFilterParams();
  const resp = await apiFetch(`/api/invoices?${params.toString()}`);
  const data = await resp.json();
  state.invoices = data.items;
  renderInvoices();
  setText('invoice-msg', `共 ${data.total} 条，当前展示 ${data.items.length} 条`);
}

function getShareTitle() {
  const titleInput = document.getElementById('share-title');
  return titleInput.value.trim() || `发票分享_${new Date().toISOString().slice(0, 10)}`;
}

async function createShareFromSelected() {
  const ids = Array.from(state.selected);
  if (ids.length === 0) {
    alert('请先选择至少一条发票');
    return;
  }

  const title = getShareTitle();
  const resp = await apiFetch('/api/shares', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, invoice_ids: ids }),
  });

  const data = await resp.json();
  alert(`分享已创建：${buildShareUrlByToken(data.token)}`);
  await loadShares();
}

async function createShareFromFilters() {
  const title = getShareTitle();
  const payload = buildShareFilterPayload(title);

  const resp = await apiFetch('/api/shares/from-filters', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  const data = await resp.json();
  alert(`筛选分享已创建：${buildShareUrlByToken(data.token)}`);
  await loadShares();
}

async function revokeShare(id) {
  await apiFetch(`/api/shares/${id}/revoke`, { method: 'POST' });
  await loadShares();
}

async function deleteShare(id) {
  await apiFetch(`/api/shares/${id}`, { method: 'DELETE' });
  await loadShares();
  await loadShareLogs();
}

function renderShares(shares) {
  const tbody = document.getElementById('share-tbody');
  tbody.innerHTML = shares.map(item => {
    const shareUrl = buildShareUrlByToken(item.token);
    return `
      <tr>
        <td>${item.id}</td>
        <td>${escapeHtml(item.title)}</td>
        <td>${escapeHtml(item.status)}</td>
        <td>${item.item_count}</td>
        <td><a href="${shareUrl}" target="_blank">打开分享页</a></td>
        <td>
          ${item.status === 'active' ? `<button data-revoke-id="${item.id}" class="small danger" type="button">失效</button>` : ''}
          <button data-delete-share-id="${item.id}" class="small danger" type="button">删除</button>
        </td>
      </tr>
    `;
  }).join('');

  document.querySelectorAll('[data-revoke-id]').forEach(el => {
    el.addEventListener('click', async () => {
      const id = Number(el.getAttribute('data-revoke-id'));
      if (!confirm('确认让该分享链接失效？')) return;
      try {
        await revokeShare(id);
      } catch (e) {
        alert(`操作失败：${e.message}`);
      }
    });
  });

  document.querySelectorAll('[data-delete-share-id]').forEach(el => {
    el.addEventListener('click', async () => {
      const id = Number(el.getAttribute('data-delete-share-id'));
      if (!confirm('确认删除该分享？删除后链接不可恢复。')) return;
      try {
        await deleteShare(id);
      } catch (e) {
        alert(`删除失败：${e.message}`);
      }
    });
  });
}

async function loadShares() {
  const resp = await apiFetch('/api/shares?page=1&page_size=100');
  const data = await resp.json();
  renderShares(data.items || []);
}

function renderLogs(items) {
  const tbody = document.getElementById('log-tbody');
  tbody.innerHTML = (items || []).map(item => `
    <tr>
      <td>${escapeHtml(item.created_at || '')}</td>
      <td>${item.share_id}</td>
      <td>${item.invoice_id || ''}</td>
      <td>${escapeHtml(item.action || '')}</td>
      <td>${item.status_code}</td>
      <td>${escapeHtml(item.ip || '')}</td>
      <td>${escapeHtml(item.user_agent || '')}</td>
    </tr>
  `).join('');
}

async function loadShareLogs() {
  const shareId = document.getElementById('log-share-id').value.trim();
  const action = document.getElementById('log-action').value;
  const params = new URLSearchParams({ page: '1', page_size: '100' });
  if (shareId) params.set('share_id', shareId);
  if (action) params.set('action', action);

  const resp = await apiFetch(`/api/share-logs?${params.toString()}`);
  const data = await resp.json();
  renderLogs(data.items || []);
}

async function handleUpload(evt) {
  evt.preventDefault();
  const fileInput = document.getElementById('file');
  if (!fileInput.files || fileInput.files.length === 0) {
    setText('upload-msg', '请选择文件');
    return;
  }

  const formData = new FormData();
  formData.append('file', fileInput.files[0]);
  formData.append('auto_ocr', document.getElementById('auto-ocr').checked ? 'true' : 'false');

  const selectedTagIds = Array.from(document.getElementById('upload-tag-ids').selectedOptions).map(opt => opt.value);
  if (selectedTagIds.length > 0) {
    formData.append('tag_ids', selectedTagIds.join(','));
  }

  try {
    await apiFetch('/api/invoices', { method: 'POST', body: formData });
    setText('upload-msg', '上传成功');
    fileInput.value = '';
    await loadInvoices();
  } catch (e) {
    setText('upload-msg', `上传失败：${e.message}`);
  }
}

async function batchSetTags() {
  const invoiceIds = Array.from(state.selected);
  if (invoiceIds.length === 0) {
    alert('请先选择发票');
    return;
  }

  const tagIds = Array.from(document.getElementById('batch-tag-ids').selectedOptions)
    .map(opt => Number(opt.value))
    .filter(id => Number.isInteger(id) && id > 0);
  await apiFetch('/api/invoices/batch/tags', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ invoice_ids: invoiceIds, tag_ids: tagIds }),
  });

  await loadInvoices();
}

async function initEvents() {
  const systemBaseUrlInput = document.getElementById('system-base-url');
  if (systemBaseUrlInput) {
    systemBaseUrlInput.value = getSystemBaseUrl();
    systemBaseUrlInput.addEventListener('change', () => {
      saveSystemBaseUrl(systemBaseUrlInput.value);
      loadShares().catch(() => {});
    });
    systemBaseUrlInput.addEventListener('blur', () => {
      saveSystemBaseUrl(systemBaseUrlInput.value);
    });
  }

  document.getElementById('login-form').addEventListener('submit', async evt => {
    evt.preventDefault();
    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value;
    try {
      await login(username, password);
      setText('login-msg', '登录成功');
      await bootstrapAfterLogin();
    } catch (e) {
      setText('login-msg', `登录失败：${e.message}`);
    }
  });

  document.getElementById('logout-btn').addEventListener('click', logout);
  document.getElementById('upload-form').addEventListener('submit', handleUpload);
  document.getElementById('edit-form').addEventListener('submit', async evt => {
    try {
      await submitEditForm(evt);
    } catch (e) {
      setText('edit-msg', `保存失败：${e.message}`);
    }
  });
  document.getElementById('edit-cancel-btn').addEventListener('click', closeEditForm);

  document.getElementById('tag-form').addEventListener('submit', async evt => {
    evt.preventDefault();
    const input = document.getElementById('new-tag-name');
    const name = input.value.trim();
    if (!name) return;
    try {
      await apiFetch('/api/tags', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      input.value = '';
      await loadTags();
    } catch (e) {
      alert(`新增标签失败：${e.message}`);
    }
  });

  document.getElementById('filter-form').addEventListener('submit', async evt => {
    evt.preventDefault();
    await loadInvoices();
  });

  document.getElementById('reset-filter').addEventListener('click', async () => {
    ['filter-q', 'filter-company', 'filter-number', 'filter-date-from', 'filter-date-to', 'filter-amount-min', 'filter-amount-max']
      .forEach(id => { document.getElementById(id).value = ''; });
    document.getElementById('filter-tag-id').value = '';
    document.getElementById('filter-ocr-status').value = '';
    document.getElementById('filter-sort-by').value = 'created_at';
    document.getElementById('filter-sort-order').value = 'desc';
    await loadInvoices();
  });

  document.getElementById('reload-btn').addEventListener('click', loadInvoices);

  document.getElementById('select-all-btn').addEventListener('click', () => {
    state.invoices.forEach(inv => state.selected.add(inv.id));
    renderInvoices();
    updateSelectedCount();
  });

  document.getElementById('clear-select-btn').addEventListener('click', () => {
    state.selected.clear();
    renderInvoices();
    updateSelectedCount();
  });

  document.getElementById('batch-set-tags-btn').addEventListener('click', async () => {
    try {
      await batchSetTags();
      alert('批量标签已更新');
    } catch (e) {
      alert(`批量标签失败：${e.message}`);
    }
  });

  document.getElementById('create-share-btn').addEventListener('click', async () => {
    try {
      await createShareFromSelected();
    } catch (e) {
      alert(`创建分享失败：${e.message}`);
    }
  });

  document.getElementById('create-share-from-filter-btn').addEventListener('click', async () => {
    try {
      await createShareFromFilters();
    } catch (e) {
      alert(`按筛选创建分享失败：${e.message}`);
    }
  });

  document.getElementById('load-logs-btn').addEventListener('click', async () => {
    try {
      await loadShareLogs();
    } catch (e) {
      alert(`加载日志失败：${e.message}`);
    }
  });
}

async function bootstrapAfterLogin() {
  setLoggedIn(true);
  updateSelectedCount();
  await loadMe();
  await loadTags();
  await loadInvoices();
  await loadShares();
  await loadShareLogs();
}

async function init() {
  await initEvents();

  const hasToken = !!getAccessToken() || !!getRefreshToken();
  if (!hasToken) {
    setLoggedIn(false);
    return;
  }

  try {
    if (!getAccessToken()) {
      const ok = await refreshToken();
      if (!ok) throw new Error('refresh failed');
    }
    await bootstrapAfterLogin();
  } catch (_) {
    clearTokens();
    setLoggedIn(false);
  }
}

init();
