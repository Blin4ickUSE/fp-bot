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

async function request(method, path, body = null) {
  const opts = { method, headers: getHeaders() };
  if (body) opts.body = JSON.stringify(body);
  
  try {
    const res = await fetch(`${BASE_URL}${path}`, opts);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      const msg = err.detail || err.message || `HTTP ${res.status}: ${res.statusText}`;
      console.error(`[API] ${method} ${path} failed:`, msg);
      throw new Error(msg);
    }
    return res.json();
  } catch (e) {
    if (e instanceof TypeError && e.message.includes('fetch')) {
      throw new Error('Не удалось подключиться к серверу. Проверьте подключение.');
    }
    throw e;
  }
}

// --- Orders ---
export const getOrders = (status) =>
  request('GET', `/orders${status ? `?status=${status}` : ''}`);

export const getOrder = (id) => request('GET', `/orders/${id}`);

export const orderAction = (id, action) =>
  request('POST', `/orders/${id}/action`, { action });

// --- Lots ---
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
