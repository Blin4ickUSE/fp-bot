/**
 * API клиент для мини-приложения.
 * Использует Telegram WebApp initData для авторизации.
 */

const BASE_URL = '/api';

function getHeaders() {
  const headers = { 'Content-Type': 'application/json' };
  // Telegram WebApp initData
  if (window.Telegram?.WebApp?.initData) {
    headers['X-Init-Data'] = window.Telegram.WebApp.initData;
  }
  return headers;
}

const RETRY_STATUSES = [502, 503, 504];
const RETRY_MAX = 2;
const RETRY_DELAY_MS = 1200;

async function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function request(method, path, body = null) {
  const opts = { method, headers: getHeaders() };
  if (body) opts.body = JSON.stringify(body);
  let lastError;

  for (let attempt = 0; attempt <= RETRY_MAX; attempt++) {
    try {
      const res = await fetch(`${BASE_URL}${path}`, opts);
      if (res.ok) return res.json();

      const retryable = RETRY_STATUSES.includes(res.status);
      if (retryable && attempt < RETRY_MAX) {
        await sleep(RETRY_DELAY_MS);
        continue;
      }

      const err = await res.json().catch(() => ({ detail: res.statusText }));
      const msg = err.detail || err.message || `HTTP ${res.status}: ${res.statusText}`;
      console.error(`[API] ${method} ${path} failed:`, msg);
      throw new Error(msg);
    } catch (e) {
      lastError = e;
      const isNetwork = e instanceof TypeError && (e.message.includes('fetch') || e.message.includes('Failed'));
      const isAbort = e.name === 'AbortError';
      if ((isNetwork || isAbort) && attempt < RETRY_MAX) {
        await sleep(RETRY_DELAY_MS);
        continue;
      }
      if (isNetwork) throw new Error('Не удалось подключиться к серверу. Проверьте подключение.');
      throw e;
    }
  }
  throw lastError;
}

// --- Orders ---
export const getOrders = (status) =>
  request('GET', `/orders${status ? `?status=${status}` : ''}`);

export const getOrder = (id) => request('GET', `/orders/${id}`);

export const orderAction = (id, action) =>
  request('POST', `/orders/${id}/action`, { action });

// --- Lots ---
export const getFunpayLots = (refresh = false) =>
  request('GET', `/funpay-lots${refresh ? '?refresh=1' : ''}`);
export const getLots = () => request('GET', '/lots');
export const createLot = (data) => request('POST', '/lots', data);
export const updateLot = (id, data) => request('PUT', `/lots/${id}`, data);
export const deleteLot = (id) => request('DELETE', `/lots/${id}`);

// --- Automation ---
export const getAutomation = () => request('GET', '/automation');
export const updateAutomation = (data) => request('PUT', '/automation', data);

// --- Stats ---
export const getStats = () => request('GET', '/stats');
export const getChartData = (hours = 24) =>
  request('GET', `/stats/chart?hours=${hours}`);

// --- Script types ---
export const getScriptTypes = () => request('GET', '/script-types');
export const getScriptMessageKeys = (scriptType) =>
  request('GET', `/script-message-keys?script_type=${encodeURIComponent(scriptType)}`);
