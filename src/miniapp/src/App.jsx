import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  LayoutDashboard, Package, Zap, Settings, User, CheckCircle,
  AlertTriangle, Activity, Search, RefreshCw, Key, TrendingUp,
  Clock, Wallet, BellRing, Lock, ChevronLeft, ShoppingBag,
  ExternalLink, ArrowUpCircle, Clock3, ListOrdered, MessageSquareText,
  Timer, FileCode, Languages, Ban, XCircle, ChevronRight, Info,
  Plus, Trash2, Eye, EyeOff, Play, RotateCcw, Loader2
} from 'lucide-react';
import * as api from './api';

// --- UI Kit ---

const Badge = ({ children, variant = 'gray' }) => {
  const styles = {
    gray: 'bg-zinc-800 text-zinc-400',
    green: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20',
    blue: 'bg-blue-500/10 text-blue-400 border border-blue-500/20',
    amber: 'bg-amber-500/10 text-amber-400 border border-amber-500/20',
    red: 'bg-red-500/10 text-red-400 border border-red-500/20',
    white: 'bg-white text-black',
  };
  return (
    <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${styles[variant] || styles.gray}`}>
      {children}
    </span>
  );
};

const NavButton = ({ active, icon: Icon, label, onClick }) => (
  <button
    onClick={onClick}
    className={`flex flex-col items-center gap-1 transition-all duration-300 relative ${active ? 'text-white scale-110' : 'text-zinc-600 hover:text-zinc-400'}`}
  >
    <Icon size={20} strokeWidth={active ? 2.5 : 2} />
    <span className={`text-[9px] font-black uppercase tracking-tighter ${active ? 'opacity-100' : 'opacity-0'}`}>
      {label}
    </span>
    {active && <div className="absolute -bottom-2 w-1 h-1 bg-white rounded-full shadow-[0_0_8px_white]"></div>}
  </button>
);

const Toggle = ({ enabled, onClick }) => (
  <button
    onClick={onClick}
    className={`w-12 h-6 rounded-full p-1 transition-all duration-300 ${enabled ? 'bg-white shadow-[0_0_15px_rgba(255,255,255,0.3)]' : 'bg-zinc-800'}`}
  >
    <div className={`w-4 h-4 rounded-full transition-all duration-300 ${enabled ? 'bg-black translate-x-6' : 'bg-zinc-600 translate-x-0'}`}></div>
  </button>
);

const LoadingSpinner = () => (
  <div className="flex items-center justify-center py-20">
    <Loader2 size={32} className="animate-spin text-zinc-500" />
  </div>
);

const statusConfig = {
  waiting_data: { label: 'Сбор данных', emoji: '⏳', variant: 'amber' },
  data_collected: { label: 'Данные собраны', emoji: '📥', variant: 'blue' },
  in_progress: { label: 'Выполнение', emoji: '🔄', variant: 'blue' },
  completed: { label: 'Выполнен', emoji: '✅', variant: 'green' },
  confirmed: { label: 'Подтверждён', emoji: '☑️', variant: 'green' },
  refunded: { label: 'Возврат', emoji: '↩️', variant: 'red' },
  dispute: { label: 'Спор', emoji: '⚠️', variant: 'red' },
};

// --- Main App ---

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [settingsView, setSettingsView] = useState('main');
  const [selectedOrder, setSelectedOrder] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Data
  const [stats, setStats] = useState(null);
  const [chartData, setChartData] = useState([]);
  const [orders, setOrders] = useState([]);
  const [lots, setLots] = useState([]);
  const [scriptTypes, setScriptTypes] = useState([]);
  const [automation, setAutomation] = useState({});
  const [searchQuery, setSearchQuery] = useState('');
  const [hoverIndex, setHoverIndex] = useState(null);

  // Lot editor
  const [editingLot, setEditingLot] = useState(null);
  const [newLotPattern, setNewLotPattern] = useState('');
  const [newLotScript, setNewLotScript] = useState('none');

  // Telegram WebApp
  useEffect(() => {
    if (window.Telegram?.WebApp) {
      window.Telegram.WebApp.ready();
      window.Telegram.WebApp.expand();
      window.Telegram.WebApp.setHeaderColor('#000000');
      window.Telegram.WebApp.setBackgroundColor('#000000');
    }
  }, []);

  // Load data on tab change
  useEffect(() => {
    if (activeTab === 'dashboard') loadDashboard();
    if (activeTab === 'orders') loadOrders();
    if (activeTab === 'automation') loadAutomation();
    if (activeTab === 'settings') { loadLots(); loadScriptTypes(); }
  }, [activeTab]);

  const loadDashboard = async () => {
    try {
      setLoading(true);
      const [s, c] = await Promise.all([api.getStats(), api.getChartData()]);
      setStats(s);
      setChartData(c);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  const loadOrders = async () => {
    try {
      setLoading(true);
      const data = await api.getOrders();
      setOrders(data);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  const loadLots = async () => {
    try {
      const data = await api.getLots();
      setLots(data);
    } catch (e) { setError(e.message); }
  };

  const loadScriptTypes = async () => {
    try {
      const data = await api.getScriptTypes();
      setScriptTypes(data);
    } catch (e) { /* ignore */ }
  };

  const loadAutomation = async () => {
    try {
      setLoading(true);
      const data = await api.getAutomation();
      setAutomation(data);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  const handleOrderAction = async (orderId, action) => {
    try {
      setLoading(true);
      await api.orderAction(orderId, action);
      await loadOrders();
      setSelectedOrder(null);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  const handleAutomationChange = async (field, value) => {
    const updated = { ...automation, [field]: value };
    setAutomation(updated);
    try {
      await api.updateAutomation({ [field]: value });
    } catch (e) { setError(e.message); }
  };

  const handleAddLot = async () => {
    if (!newLotPattern.trim()) return;
    try {
      await api.createLot({ lot_name_pattern: newLotPattern, script_type: newLotScript });
      setNewLotPattern('');
      setNewLotScript('none');
      await loadLots();
    } catch (e) { setError(e.message); }
  };

  const handleDeleteLot = async (id) => {
    try {
      await api.deleteLot(id);
      await loadLots();
    } catch (e) { setError(e.message); }
  };

  const handleUpdateLot = async (id, data) => {
    try {
      await api.updateLot(id, data);
      await loadLots();
      setEditingLot(null);
    } catch (e) { setError(e.message); }
  };

  // SVG chart path
  const svgPath = useMemo(() => {
    if (!chartData.length) return '';
    const maxOrders = Math.max(...chartData.map(d => d.orders), 1);
    return chartData.map((d, i) => {
      const x = (i / (chartData.length - 1 || 1)) * 100;
      const y = 100 - (d.orders / maxOrders) * 100;
      return `${i === 0 ? 'M' : 'L'} ${x} ${y}`;
    }).join(' ');
  }, [chartData]);

  // Error toast
  useEffect(() => {
    if (error) {
      const t = setTimeout(() => setError(null), 4000);
      return () => clearTimeout(t);
    }
  }, [error]);

  // --- Screens ---

  const renderDashboard = () => {
    if (loading && !stats) return <LoadingSpinner />;
    const statsCards = [
      { label: 'Баланс', value: stats?.balance || '—', sub: 'Общий баланс', icon: Wallet, color: 'text-emerald-400' },
      { label: 'Заказов', value: String(stats?.total_orders || 0), sub: 'За всё время', icon: TrendingUp, color: 'text-blue-400' },
      { label: 'Активных', value: String(stats?.active_orders || 0), sub: 'В обработке', icon: Clock, color: 'text-amber-400' },
      { label: 'Статус', value: stats?.bot_status || 'OFFLINE', sub: 'Бот', icon: Activity, color: stats?.bot_status === 'ONLINE' ? 'text-white' : 'text-red-400' },
    ];

    return (
      <div className="space-y-6 animate-slide-up">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-black text-white tracking-tighter uppercase italic">FunPay <span className="text-zinc-500">Manager</span></h1>
            <p className="text-[10px] text-zinc-500 font-bold uppercase tracking-widest mt-0.5">С возвращением, Администратор</p>
          </div>
          <button onClick={loadDashboard} className="p-2 text-zinc-500 hover:text-white transition-colors">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>

        <div className="grid grid-cols-2 gap-3">
          {statsCards.map((stat, i) => (
            <div key={i} className="bg-zinc-900/50 border border-zinc-800/50 p-4 rounded-2xl hover:border-zinc-700 transition-colors group">
              <div className="flex justify-between items-start mb-2">
                <stat.icon size={18} className={`${stat.color} group-hover:scale-110 transition-transform`} />
                <div className="w-1.5 h-1.5 rounded-full bg-zinc-800"></div>
              </div>
              <p className="text-2xl font-black text-white tracking-tight">{stat.value}</p>
              <p className="text-[9px] text-zinc-500 font-bold uppercase tracking-widest mt-1">{stat.label}</p>
              <div className="mt-2 text-[9px] text-zinc-400 font-medium">{stat.sub}</div>
            </div>
          ))}
        </div>

        {chartData.length > 0 && (
          <div className="space-y-3">
            <h2 className="text-[10px] font-black text-zinc-500 uppercase tracking-[0.2em] px-1">Активность заказов</h2>
            <div className="bg-zinc-900 border border-zinc-800/50 rounded-3xl p-0 relative overflow-hidden group h-48 flex flex-col justify-end">
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-20">
                <div className={`text-center transition-all duration-300 ${hoverIndex !== null ? 'opacity-100 scale-100' : 'opacity-40 scale-95'}`}>
                  <p className="text-5xl font-black text-white tracking-tighter leading-none">
                    {hoverIndex !== null ? chartData[hoverIndex]?.orders : stats?.active_orders || 0}
                  </p>
                  <p className="text-[10px] font-black text-zinc-500 uppercase tracking-[0.2em] mt-2">
                    {hoverIndex !== null ? `Заказов в ${chartData[hoverIndex]?.time}` : 'Активных'}
                  </p>
                </div>
              </div>

              <div className="relative w-full h-full pt-10 px-0">
                <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="w-full h-full overflow-visible">
                  <path d={`${svgPath} L 100 100 L 0 100 Z`} className="fill-white/[0.03] transition-all duration-700" />
                  <path d={svgPath} fill="none" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="opacity-40" />
                  {hoverIndex !== null && (
                    <line x1={(hoverIndex / (chartData.length - 1 || 1)) * 100} y1="0" x2={(hoverIndex / (chartData.length - 1 || 1)) * 100} y2="100" stroke="white" strokeWidth="0.5" strokeDasharray="2,2" className="opacity-30" />
                  )}
                </svg>
                <div className="absolute inset-0 flex z-30">
                  {chartData.map((_, i) => (
                    <div key={i} className="flex-1 h-full cursor-crosshair" onMouseEnter={() => setHoverIndex(i)} onMouseLeave={() => setHoverIndex(null)} />
                  ))}
                </div>
              </div>
              <div className="flex justify-between px-6 pb-4 relative z-10 pointer-events-none">
                {chartData.filter((_, i) => i % 3 === 0).map((item, i) => (
                  <span key={i} className="text-[8px] font-bold uppercase text-zinc-700">{item.time}</span>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    );
  };

  const renderOrderDetail = () => {
    if (!selectedOrder) return null;
    const sc = statusConfig[selectedOrder.status] || statusConfig.waiting_data;
    const data = selectedOrder.collected_data || {};
    const hasData = Object.keys(data).length > 0;

    return (
      <div className="space-y-6 animate-slide-right">
        <div className="flex items-center gap-4">
          <button onClick={() => setSelectedOrder(null)} className="p-2 bg-zinc-900 rounded-xl border border-zinc-800 text-white active:scale-90 transition-all">
            <ChevronLeft size={18} />
          </button>
          <div>
            <h1 className="text-xl font-black text-white tracking-tighter uppercase italic">#{selectedOrder.funpay_order_id}</h1>
            <p className="text-[9px] text-zinc-500 font-bold uppercase tracking-widest">Управление заказом</p>
          </div>
        </div>

        <div className="bg-zinc-900 border border-zinc-800/50 rounded-3xl p-6 space-y-6">
          <div className="flex justify-between items-start">
            <div>
              <p className="text-[8px] font-black text-zinc-500 uppercase tracking-widest">Покупатель</p>
              <h3 className="text-lg font-black text-white">{selectedOrder.buyer_username}</h3>
            </div>
            <Badge variant={sc.variant}>{sc.emoji} {sc.label}</Badge>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="p-3 bg-black/40 rounded-xl border border-zinc-800/50">
              <p className="text-[8px] font-black text-zinc-600 uppercase tracking-widest">Товар</p>
              <p className="text-[11px] font-bold text-white mt-1">{selectedOrder.item_name}</p>
            </div>
            <div className="p-3 bg-black/40 rounded-xl border border-zinc-800/50">
              <p className="text-[8px] font-black text-zinc-600 uppercase tracking-widest">Цена</p>
              <p className="text-[11px] font-bold text-white mt-1">{selectedOrder.price} {selectedOrder.currency}</p>
            </div>
          </div>

          {hasData && (
            <div className="p-4 bg-black/40 rounded-2xl border border-amber-500/20 space-y-3">
              <div className="flex items-center gap-2 text-amber-400">
                <Info size={14} />
                <span className="text-[10px] font-black uppercase tracking-widest">Собранные данные</span>
              </div>
              <div className="space-y-1">
                {Object.entries(data).map(([k, v]) => (
                  <p key={k} className="text-[11px] font-medium text-zinc-400">
                    <span className="text-zinc-600">{k}:</span> {v}
                  </p>
                ))}
              </div>
            </div>
          )}

          <div className="space-y-3 pt-4">
            {(selectedOrder.status === 'data_collected' || selectedOrder.status === 'waiting_data') && (
              <button
                onClick={() => handleOrderAction(selectedOrder.id, 'start')}
                disabled={loading}
                className="w-full py-4 bg-white text-black rounded-2xl text-xs font-black uppercase tracking-[0.15em] active:scale-95 transition-all flex items-center justify-center gap-2 disabled:opacity-50"
              >
                {loading ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} fill="black" />} Начать выполнение
              </button>
            )}

            {selectedOrder.status === 'in_progress' && (
              <button
                onClick={() => handleOrderAction(selectedOrder.id, 'complete')}
                disabled={loading}
                className="w-full py-4 bg-emerald-500 text-white rounded-2xl text-xs font-black uppercase tracking-[0.15em] active:scale-95 transition-all flex items-center justify-center gap-2 disabled:opacity-50"
              >
                {loading ? <Loader2 size={16} className="animate-spin" /> : <CheckCircle size={16} />} Я выполнил
              </button>
            )}

            {!['completed', 'confirmed', 'refunded'].includes(selectedOrder.status) && (
              <button
                onClick={() => handleOrderAction(selectedOrder.id, 'refund')}
                disabled={loading}
                className="w-full py-4 bg-zinc-800 text-zinc-400 rounded-2xl text-xs font-black uppercase tracking-[0.15em] active:scale-95 transition-all flex items-center justify-center gap-2 disabled:opacity-50"
              >
                {loading ? <Loader2 size={16} className="animate-spin" /> : <RotateCcw size={16} />} Возврат средств
              </button>
            )}
          </div>
        </div>
      </div>
    );
  };

  const renderOrders = () => {
    if (selectedOrder) return renderOrderDetail();
    if (loading && !orders.length) return <LoadingSpinner />;

    const activeOrders = orders.filter(o => !['completed', 'confirmed', 'refunded'].includes(o.status));
    const completedOrders = orders.filter(o => ['completed', 'confirmed', 'refunded'].includes(o.status));

    return (
      <div className="space-y-6 animate-slide-up">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-black text-white tracking-tighter uppercase italic">Заказы</h1>
          <button onClick={loadOrders} className="p-2 text-zinc-500 hover:text-white transition-colors">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>

        {activeOrders.length > 0 && (
          <div className="space-y-2">
            <h2 className="text-[10px] font-black text-zinc-500 uppercase tracking-[0.2em] px-1">Активные</h2>
            {activeOrders.map((order) => {
              const sc = statusConfig[order.status] || statusConfig.waiting_data;
              const hasData = order.collected_data && Object.keys(order.collected_data).length > 0;
              return (
                <div
                  key={order.id}
                  onClick={() => setSelectedOrder(order)}
                  className={`bg-zinc-900/50 border rounded-xl p-3 flex items-center justify-between transition-all group relative overflow-hidden cursor-pointer
                    ${hasData ? 'border-amber-500/30 hover:border-amber-500/60' : 'border-zinc-800/40 hover:border-zinc-700'}`}
                >
                  {hasData && <div className="absolute inset-0 bg-amber-500/5 pointer-events-none"></div>}
                  <div className="flex flex-col relative z-10">
                    <div className="flex items-center gap-2">
                      <span className="text-[8px] font-black text-zinc-600 uppercase tracking-widest">#{order.funpay_order_id}</span>
                      {hasData && <Badge variant="amber">ДАННЫЕ</Badge>}
                    </div>
                    <h3 className="text-[11px] font-black text-white uppercase tracking-tight">{order.item_name}</h3>
                    <p className="text-[9px] text-zinc-500 font-bold uppercase mt-0.5 italic">{order.buyer_username}</p>
                  </div>
                  <div className="text-right flex flex-col items-end relative z-10">
                    <span className="text-xs font-black text-white">{order.price} {order.currency}</span>
                    <div className="mt-1 flex items-center gap-1">
                      <Badge variant={sc.variant}>{sc.emoji} {sc.label}</Badge>
                    </div>
                  </div>
                  <div className="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <ChevronRight size={14} className="text-zinc-500" />
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {completedOrders.length > 0 && (
          <div className="space-y-2">
            <h2 className="text-[10px] font-black text-zinc-500 uppercase tracking-[0.2em] px-1">Завершённые</h2>
            {completedOrders.slice(0, 20).map((order) => {
              const sc = statusConfig[order.status] || statusConfig.completed;
              return (
                <div
                  key={order.id}
                  onClick={() => setSelectedOrder(order)}
                  className="bg-zinc-900/30 border border-zinc-800/30 rounded-xl p-3 flex items-center justify-between transition-all cursor-pointer hover:border-zinc-700"
                >
                  <div className="flex flex-col">
                    <span className="text-[8px] font-black text-zinc-700 uppercase tracking-widest">#{order.funpay_order_id}</span>
                    <h3 className="text-[11px] font-bold text-zinc-400 uppercase tracking-tight">{order.item_name}</h3>
                    <p className="text-[9px] text-zinc-600 font-bold uppercase mt-0.5 italic">{order.buyer_username}</p>
                  </div>
                  <div className="text-right flex flex-col items-end">
                    <span className="text-xs font-bold text-zinc-500">{order.price} {order.currency}</span>
                    <Badge variant={sc.variant}>{sc.emoji} {sc.label}</Badge>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {orders.length === 0 && !loading && (
          <div className="py-20 flex flex-col items-center text-center">
            <ShoppingBag size={40} className="text-zinc-800 mb-4" />
            <h3 className="text-sm font-black text-zinc-500 uppercase tracking-widest">Нет заказов</h3>
            <p className="text-[10px] text-zinc-600 font-bold mt-2">Заказы появятся здесь после покупки на FunPay</p>
          </div>
        )}
      </div>
    );
  };

  const renderAutomation = () => {
    if (loading && !Object.keys(automation).length) return <LoadingSpinner />;

    return (
      <div className="space-y-6 animate-slide-up">
        <h1 className="text-2xl font-black text-white tracking-tighter uppercase italic">Автоматизация</h1>
        <div className="space-y-3">
          {/* Вечный онлайн */}
          <div className="bg-zinc-900 border border-zinc-800/50 rounded-2xl p-5 flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="w-10 h-10 rounded-xl bg-emerald-500/10 flex items-center justify-center text-emerald-500"><Activity size={20} /></div>
              <div>
                <p className="text-xs font-black text-white uppercase tracking-tight">Вечный онлайн</p>
                <p className="text-[10px] text-zinc-500 font-bold uppercase tracking-tighter mt-0.5">Всегда в топе списка</p>
              </div>
            </div>
            <Toggle enabled={automation.eternal_online} onClick={() => handleAutomationChange('eternal_online', !automation.eternal_online)} />
          </div>

          {/* Автоподнятие */}
          <div className="bg-zinc-900 border border-zinc-800/50 rounded-2xl p-5 flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="w-10 h-10 rounded-xl bg-white/10 flex items-center justify-center text-white"><ArrowUpCircle size={20} /></div>
              <div>
                <p className="text-xs font-black text-white uppercase tracking-tight">Автоподнятие лотов</p>
                <p className="text-[10px] text-zinc-500 font-bold uppercase tracking-tighter mt-0.5">Раз в 4 часа (по КД FunPay)</p>
              </div>
            </div>
            <Toggle enabled={automation.auto_bump} onClick={() => handleAutomationChange('auto_bump', !automation.auto_bump)} />
          </div>

          {/* Авто-подтверждение */}
          <div className={`bg-zinc-900 border transition-all duration-300 rounded-2xl overflow-hidden ${automation.auto_confirm ? 'border-blue-500/50' : 'border-zinc-800/50'}`}>
            <div className="p-5 flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="w-10 h-10 rounded-xl bg-blue-500/10 flex items-center justify-center text-blue-500"><CheckCircle size={20} /></div>
                <div>
                  <p className="text-xs font-black text-white uppercase tracking-tight">Авто-подтверждение</p>
                  <p className="text-[10px] text-zinc-500 font-bold uppercase tracking-tighter mt-0.5">Писать в поддержку</p>
                </div>
              </div>
              <Toggle enabled={automation.auto_confirm} onClick={() => handleAutomationChange('auto_confirm', !automation.auto_confirm)} />
            </div>
            {automation.auto_confirm && (
              <div className="px-5 pb-5 pt-2 space-y-4 animate-fade-in">
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-2">
                    <label className="flex items-center gap-2 text-[9px] font-black text-zinc-500 uppercase tracking-widest px-1">
                      <Clock3 size={10} /> Время (МСК)
                    </label>
                    <input
                      type="time"
                      value={automation.auto_confirm_time || '12:00'}
                      onChange={(e) => handleAutomationChange('auto_confirm_time', e.target.value)}
                      className="w-full bg-black border border-zinc-800 rounded-xl py-2 px-3 text-xs font-bold text-white focus:outline-none focus:border-blue-500 transition-colors"
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="flex items-center gap-2 text-[9px] font-black text-zinc-500 uppercase tracking-widest px-1">
                      <ListOrdered size={10} /> Лимит
                    </label>
                    <input
                      type="number"
                      value={automation.auto_confirm_max_orders || 5}
                      onChange={(e) => handleAutomationChange('auto_confirm_max_orders', parseInt(e.target.value) || 5)}
                      className="w-full bg-black border border-zinc-800 rounded-xl py-2 px-3 text-xs font-bold text-white focus:outline-none focus:border-blue-500 transition-colors"
                    />
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Напоминание об отзыве */}
          <div className={`bg-zinc-900 border transition-all duration-300 rounded-2xl overflow-hidden ${automation.review_reminder ? 'border-amber-500/50 shadow-[0_0_20px_rgba(245,158,11,0.1)]' : 'border-zinc-800/50'}`}>
            <div className="p-5 flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="w-10 h-10 rounded-xl bg-amber-500/10 flex items-center justify-center text-amber-500"><BellRing size={20} /></div>
                <div>
                  <p className="text-xs font-black text-white uppercase tracking-tight">Напоминание об отзыве</p>
                  <p className="text-[10px] text-zinc-500 font-bold uppercase tracking-tighter mt-0.5">Авто-сообщение после покупки</p>
                </div>
              </div>
              <Toggle enabled={automation.review_reminder} onClick={() => handleAutomationChange('review_reminder', !automation.review_reminder)} />
            </div>
            {automation.review_reminder && (
              <div className="px-5 pb-5 pt-2 space-y-5 animate-fade-in">
                <div className="space-y-2">
                  <label className="flex items-center gap-2 text-[9px] font-black text-zinc-500 uppercase tracking-widest px-1">
                    <Timer size={10} /> Задержка (в минутах)
                  </label>
                  <input
                    type="number"
                    value={automation.review_delay_minutes || 1440}
                    onChange={(e) => handleAutomationChange('review_delay_minutes', parseInt(e.target.value) || 1440)}
                    placeholder="Напр: 1440 (24ч)"
                    className="w-full bg-black border border-zinc-800 rounded-xl py-3 px-4 text-xs font-bold text-white focus:outline-none focus:border-amber-500 transition-colors"
                  />
                </div>
                <div className="space-y-2">
                  <label className="flex items-center gap-2 text-[9px] font-black text-zinc-500 uppercase tracking-widest px-1">
                    <MessageSquareText size={10} /> Текст (RU)
                  </label>
                  <textarea
                    value={automation.review_message_ru || ''}
                    onChange={(e) => handleAutomationChange('review_message_ru', e.target.value)}
                    rows={3}
                    className="w-full bg-black border border-zinc-800 rounded-xl py-3 px-4 text-[11px] font-medium text-white placeholder:text-zinc-800 focus:outline-none focus:border-amber-500 transition-all resize-none leading-relaxed"
                  />
                </div>
                <div className="space-y-2">
                  <label className="flex items-center gap-2 text-[9px] font-black text-zinc-500 uppercase tracking-widest px-1">
                    <MessageSquareText size={10} /> Text (EN)
                  </label>
                  <textarea
                    value={automation.review_message_en || ''}
                    onChange={(e) => handleAutomationChange('review_message_en', e.target.value)}
                    rows={3}
                    className="w-full bg-black border border-zinc-800 rounded-xl py-3 px-4 text-[11px] font-medium text-white placeholder:text-zinc-800 focus:outline-none focus:border-amber-500 transition-all resize-none leading-relaxed"
                  />
                </div>
                <div className="bg-amber-500/5 border border-amber-500/10 p-3 rounded-xl">
                  <p className="text-[9px] font-bold text-amber-400/80 leading-relaxed uppercase tracking-tighter italic">
                    Сообщение будет отправлено через {automation.review_delay_minutes || 1440} мин. после подтверждения заказа.
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  };

  const renderLotsSubView = () => (
    <div className="space-y-6 animate-slide-right">
      <div className="flex items-center gap-4">
        <button onClick={() => setSettingsView('main')} className="p-2 bg-zinc-900 rounded-xl border border-zinc-800 text-white active:scale-90 transition-all">
          <ChevronLeft size={18} />
        </button>
        <h1 className="text-xl font-black text-white tracking-tighter uppercase italic">Конфигурация лотов</h1>
      </div>

      {/* Добавить новый */}
      <div className="bg-zinc-900 border border-zinc-800/50 rounded-2xl p-4 space-y-3">
        <h3 className="text-[10px] font-black text-zinc-500 uppercase tracking-widest flex items-center gap-2">
          <Plus size={12} /> Добавить привязку
        </h3>
        <input
          type="text"
          placeholder="Подстрока в названии лота (напр: Spotify Premium)"
          className="w-full bg-black border border-zinc-800 rounded-xl py-3 px-4 text-xs font-bold text-white placeholder:text-zinc-700 focus:outline-none focus:border-zinc-600 transition-all"
          value={newLotPattern}
          onChange={(e) => setNewLotPattern(e.target.value)}
        />
        <select
          value={newLotScript}
          onChange={(e) => setNewLotScript(e.target.value)}
          className="w-full bg-black border border-zinc-800 rounded-xl py-3 px-4 text-xs font-bold text-white focus:outline-none focus:border-zinc-600 transition-all"
        >
          {scriptTypes.map(st => (
            <option key={st.value} value={st.value}>{st.label}</option>
          ))}
        </select>
        <button
          onClick={handleAddLot}
          className="w-full py-3 bg-white text-black rounded-xl text-[10px] font-black uppercase tracking-widest active:scale-95 transition-all"
        >
          Добавить
        </button>
      </div>

      {/* Список */}
      <div className="space-y-3">
        {lots.map(lot => (
          <div key={lot.id} className="bg-zinc-900 border border-zinc-800/50 rounded-2xl p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-xs font-black text-white uppercase tracking-tight">{lot.lot_name_pattern}</h3>
                <Badge variant={lot.script_type !== 'none' ? 'white' : 'gray'}>
                  {lot.script_type.replace('_', ' ')}
                </Badge>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => handleDeleteLot(lot.id)}
                  className="p-2 text-zinc-600 hover:text-red-400 transition-colors"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
            {editingLot === lot.id ? (
              <div className="space-y-2 animate-fade-in">
                <select
                  defaultValue={lot.script_type}
                  onChange={(e) => handleUpdateLot(lot.id, { script_type: e.target.value })}
                  className="w-full bg-black border border-zinc-800 rounded-xl py-2 px-3 text-xs font-bold text-white focus:outline-none"
                >
                  {scriptTypes.map(st => (
                    <option key={st.value} value={st.value}>{st.label}</option>
                  ))}
                </select>
              </div>
            ) : (
              <button
                onClick={() => setEditingLot(lot.id)}
                className="w-full py-2.5 bg-zinc-800 hover:bg-zinc-700 text-white rounded-xl text-[10px] font-black uppercase tracking-widest transition-all flex items-center justify-center gap-2"
              >
                <Zap size={12} /> Изменить скрипт
              </button>
            )}
          </div>
        ))}
        {lots.length === 0 && (
          <div className="py-10 text-center">
            <Package size={32} className="text-zinc-800 mx-auto mb-3" />
            <p className="text-[10px] text-zinc-600 font-bold uppercase">Нет привязок. Добавьте первую выше.</p>
          </div>
        )}
      </div>
    </div>
  );

  const renderSettings = () => {
    if (settingsView === 'lots') return renderLotsSubView();

    return (
      <div className="space-y-6 animate-slide-up">
        <h1 className="text-2xl font-black text-white tracking-tighter uppercase italic">Настройки</h1>

        <div className="bg-zinc-900 border border-zinc-800/50 rounded-3xl p-6 space-y-8">
          <div className="space-y-4">
            <div className="flex items-center gap-2 px-1">
              <Package size={14} className="text-zinc-500" />
              <h2 className="text-[10px] font-black text-zinc-500 uppercase tracking-[0.2em]">Управление товарами</h2>
            </div>
            <button
              onClick={() => { setSettingsView('lots'); loadLots(); loadScriptTypes(); }}
              className="w-full flex items-center justify-between p-5 bg-black border border-zinc-800 rounded-2xl group active:scale-[0.98] transition-all"
            >
              <div className="flex items-center gap-4">
                <div className="w-8 h-8 rounded-lg bg-zinc-800 flex items-center justify-center text-zinc-400 group-hover:text-white transition-colors">
                  <Package size={18} />
                </div>
                <span className="text-xs font-black text-white uppercase tracking-widest">Конфигурация лотов</span>
              </div>
              <div className="text-[10px] font-black text-zinc-600 uppercase tracking-widest group-hover:text-zinc-400 transition-colors">
                {lots.length} →
              </div>
            </button>
          </div>

          <div className="space-y-4">
            <div className="flex items-center gap-2 px-1">
              <Zap size={14} className="text-zinc-500" />
              <h2 className="text-[10px] font-black text-zinc-500 uppercase tracking-[0.2em]">Скрипты</h2>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {[
                { name: 'Spotify', type: 'spotify', color: 'text-emerald-400' },
                { name: 'Discord', type: 'discord_nitro', color: 'text-indigo-400' },
                { name: 'ChatGPT', type: 'chatgpt', color: 'text-green-400' },
                { name: 'TG Premium 1M', type: 'telegram_premium_1m', color: 'text-blue-400' },
                { name: 'TG Premium 3/6/12', type: 'telegram_premium_long', color: 'text-cyan-400' },
                { name: 'TG Stars', type: 'telegram_stars', color: 'text-amber-400' },
              ].map(s => (
                <div key={s.type} className="p-3 bg-black/40 rounded-xl border border-zinc-800/50 flex items-center gap-2">
                  <FileCode size={12} className={s.color} />
                  <span className="text-[10px] font-bold text-zinc-400">{s.name}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="p-6 bg-zinc-900/30 border border-zinc-800/50 rounded-3xl flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-zinc-800 flex items-center justify-center"><User size={16} className="text-zinc-400" /></div>
            <span className="text-[10px] font-black text-zinc-400 uppercase tracking-widest">FunPay Manager</span>
          </div>
          <Badge variant="green">v1.0</Badge>
        </div>
      </div>
    );
  };

  return (
    <div className="min-h-screen bg-black text-white font-sans selection:bg-white selection:text-black overflow-x-hidden">
      {/* Error toast */}
      {error && (
        <div className="fixed top-4 left-4 right-4 z-[100] bg-red-500/10 border border-red-500/30 rounded-2xl p-4 animate-slide-up">
          <div className="flex items-center gap-2">
            <AlertTriangle size={14} className="text-red-400" />
            <p className="text-[11px] font-bold text-red-400">{error}</p>
          </div>
        </div>
      )}

      <main className="max-w-md mx-auto p-6 pb-32">
        {activeTab === 'dashboard' && renderDashboard()}
        {activeTab === 'orders' && renderOrders()}
        {activeTab === 'automation' && renderAutomation()}
        {activeTab === 'settings' && renderSettings()}
      </main>

      <nav className="fixed bottom-0 left-0 right-0 z-50 flex justify-center pb-8 px-6">
        <div className="w-full max-w-sm bg-zinc-900/80 backdrop-blur-2xl border border-zinc-800/50 rounded-3xl p-3 flex justify-around items-center shadow-2xl">
          <NavButton active={activeTab === 'dashboard'} icon={LayoutDashboard} label="Главная" onClick={() => setActiveTab('dashboard')} />
          <NavButton active={activeTab === 'orders'} icon={ShoppingBag} label="Заказы" onClick={() => { setActiveTab('orders'); setSelectedOrder(null); }} />
          <NavButton active={activeTab === 'automation'} icon={Zap} label="Авто" onClick={() => setActiveTab('automation')} />
          <NavButton active={activeTab === 'settings'} icon={Settings} label="Настр" onClick={() => { setActiveTab('settings'); setSettingsView('main'); }} />
        </div>
      </nav>

      <div className="fixed top-0 left-1/2 -translate-x-1/2 w-full h-full pointer-events-none -z-10 overflow-hidden">
        <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-zinc-500/5 blur-[120px] rounded-full"></div>
        <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-zinc-500/5 blur-[120px] rounded-full"></div>
      </div>
    </div>
  );
}
