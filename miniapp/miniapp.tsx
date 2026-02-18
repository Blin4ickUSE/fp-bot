import React, { useState, useEffect, useMemo, useRef } from 'react';
import { 
  Smartphone, Monitor, Tv, CreditCard, History, 
  UserPlus, Gift, ChevronLeft, Copy, Trash2, Edit2, 
  CheckCircle, Clock, Globe, Shield, Zap, Plus, Sparkles,
  LogOut, Download, Apple, Command, User, ChevronDown, 
  ArrowRight, Frown, BookOpen, Crown, ChevronRight, Wallet, Sliders, X,
  Rocket, AlertTriangle, FileText, ExternalLink, MessageCircle
} from 'lucide-react';

// ==========================================
// 0. ENV & API HELPERS
// ==========================================

declare const importMetaMini: any | undefined;

const rawEnvMini: any =
  (typeof importMetaMini !== 'undefined' && importMetaMini.env) ||
  (typeof (window as any) !== 'undefined' && (window as any).__ENV__) ||
  {};

const API_BASE_URL_MINI: string = rawEnvMini.VITE_API_URL || rawEnvMini.REACT_APP_API_URL || '/api';
const SUPPORT_URL: string = rawEnvMini.VITE_SUPPORT_URL || rawEnvMini.REACT_APP_SUPPORT_URL || 'https://t.me/vpn12help_bot';
const BOT_USERNAME_MINI: string = rawEnvMini.VITE_BOT_USERNAME || rawEnvMini.REACT_APP_BOT_USERNAME || 'blnnnbot';

async function miniApiFetch(path: string, options: RequestInit = {}): Promise<any> {
  // Всегда используем относительный путь /api - nginx проксирует на backend
  const cleanPath = path.startsWith('/') ? path : `/${path}`;
  const url = `/api${cleanPath}`;
  
  const res = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  });
  
  // Обработка бана (статус 403)
  if (res.status === 403) {
    try {
      const data = await res.json();
      if (data.banned) {
        return { _banned: true, reason: data.reason || 'Аккаунт заблокирован' };
      }
    } catch {}
    throw new Error('Access denied');
  }
  
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Request failed with status ${res.status}`);
  }
  try {
    return await res.json();
  } catch {
    return null;
  }
}

// ==========================================
// 1. TYPES & INTERFACES
// ==========================================

type ViewState = 
  | 'home' 
  | 'wizard' 
  | 'topup' 
  | 'wait_payment' 
  | 'success_payment' 
  | 'devices' 
  | 'buy_device' 
  | 'instruction_view' 
  | 'history' 
  | 'referral' 
  | 'referral_detail' 
  | 'promo';

type PlatformId = 'android' | 'ios' | 'windows' | 'macos' | 'linux' | 'androidtv';

interface Plan {
  id: string;
  duration: string;
  price: number;
  highlight: boolean;
  days: number;
  isTrial?: boolean;
}

interface PaymentMethodVariant {
  id: string;
  name: string;
  feePercent: number;
}

interface PaymentMethod {
  id: string;
  name: string;
  icon: string | React.ReactNode;
  feePercent: number;
  variants?: PaymentMethodVariant[];
}

interface Device {
  id: number;
  name: string;
  type: PlatformId | string;
  added: string;
  key_uuid?: string;
  short_uuid?: string;
  key_status?: string;
  days_left?: number;
  hours_left?: number;
  is_expired?: boolean;
  expiry_date?: string;
}

interface HistoryItem {
  id: number;
  type: string;
  title: string;
  amount: number;
  date: string;
}

interface ReferralTransaction {
  date: string;
  title: string;
  type: string;
  amount: number;
  income: number;
}

interface ReferralUser {
  id: number;
  name: string;
  date: string;
  spent: number;
  myProfit: number;
  history: ReferralTransaction[];
}

interface InstructionStep {
  title: string;
  desc: string;
  actions?: {
    label: string;
    type?: 'copy_key' | 'trigger_add' | 'nav_android' | 'nav_ios';
    url?: string;
    primary?: boolean;
  }[];
}

interface PlatformData {
  id: PlatformId;
  title: string;
  icon: React.ReactNode;
  steps: InstructionStep[];
}

// ==========================================
// 2. CONSTANTS & CONTENT
// ==========================================

const OFFER_AGREEMENT_TEXT = `
**Редакция от 01.01.2024 (Версия 2.0)**

Настоящий документ является официальным предложением (публичной офертой) сервиса **12VPN** (далее — «Исполнитель») и содержит все существенные условия предоставления услуг по предоставлению удаленного доступа к сети Интернет.

### 1. ТЕРМИНЫ И ОПРЕДЕЛЕНИЯ
В целях настоящего Документа используются следующие термины:
* **1.1. Сервис (12VPN)** — программно-аппаратный комплекс, предоставляющий функционал перенаправления интернет-трафика через удаленные серверы.
* **1.2. Ключ доступа (Конфигурация)** — уникальный цифровой код/файл, генерируемый Сервисом, являющийся техническим средством аутентификации Пользователя в системе.
* **1.3. Стороннее ПО** — программное обеспечение третьих лиц (в т.ч. приложение «Happ», V2Ray и аналоги), устанавливаемое Пользователем на свое устройство для взаимодействия с Сервисом.
* **1.4. Аномальная активность** — паттерны сетевого поведения, отклоняющиеся от стандартного профиля использования (в т.ч. массовые рассылки, сканирование портов, превышение лимитов сессий).

### 2. ПРЕДМЕТ СОГЛАШЕНИЯ
* **2.1.** Исполнитель предоставляет Пользователю неисключительное право (лицензию) на использование Ключа доступа к инфраструктуре Сервиса, а Пользователь обязуется оплатить данное право.
* **2.2.** Доступ к Сервису предоставляется по принципу **«AS IS» («КАК ЕСТЬ»)**. Исполнитель не гарантирует совместимость Сервиса с любым конкретным программным обеспечением или устройством Пользователя.
* **2.3. Момент оказания услуги.** Услуга считается оказанной в полном объеме и надлежащего качества в момент автоматической отправки Ключа доступа в интерфейсе Telegram-бота. С этого момента обязательства Исполнителя считаются выполненными.

### 3. ТЕХНИЧЕСКИЕ УСЛОВИЯ И ОГРАНИЧЕНИЯ
* **3.1. Локации и Маршруты.** Пользователю предоставляется доступ к динамическому пулу серверов. Исполнитель вправе в одностороннем порядке, без предварительного уведомления, изменять географическое расположение серверов, IP-адреса и маршруты трафика в целях оптимизации нагрузки. Наличие конкретной страны (геолокации) не гарантируется.
* **3.2. Скорость соединения.** Скорость доступа к сети Интернет через Сервис не является фиксированной и зависит от:
    * Нагрузки на общий (shared) канал связи;
    * Удаленности конечного ресурса;
    * Ограничений интернет-провайдера Пользователя (в т.ч. шейпинга UDP/TCP трафика).
* **3.3. Лицензионные ограничения.** Один Ключ доступа предназначен для использования строго на **1 (одном) устройстве**.
    * Система автоматически фиксирует нарушение данного условия.
    * При выявлении одновременных сессий с разных устройств, Ключ блокируется автоматически.
* **3.4. Стороннее ПО.** Исполнитель не является разработчиком клиентских приложений (Happ и др.) и не несет ответственности за их удаление из магазинов приложений (AppStore/Google Play), сбои в их работе или некорректные обновления.

### 4. РЕГЛАМЕНТ ТЕХНИЧЕСКОГО ОБСЛУЖИВАНИЯ (SLA)
* **4.1. Плановые работы.** Исполнитель вправе проводить технические работы с полной остановкой Сервиса на неограниченное время, при условии уведомления Пользователей (в канале или боте) не менее чем за 24 часа.
* **4.2. Аварийные работы.** Допускается перерыв в предоставлении Услуг без предварительного уведомления общей продолжительностью до **100 (ста) часов в календарный месяц**. Данные перерывы не являются основанием для перерасчета стоимости или возврата средств.
* **4.3.** Блокировка доступа к Сервису со стороны государственных регуляторов (РКН) или интернет-провайдеров признается обстоятельством непреодолимой силы (Форс-мажор) и исключает ответственность Исполнителя.

### 5. ПОЛИТИКА ВОЗВРАТА СРЕДСТВ (REFUND POLICY)
* **5.1.** Возврат денежных средств возможен **исключительно** при одновременном соблюдении **ВСЕХ** следующих условий:
    * а) С момента покупки прошло не более 72 часов (3 суток);
    * б) Объем потребленного трафика по Ключу составляет менее **1 (одного) Мегабайта**;
    * в) Пользователь обратился в Техническую поддержку, и специалисты Поддержки не смогли обеспечить подключение на устройстве Пользователя в течение 24 часов с момента обращения.
* **5.2.** Во всех иных случаях, включая (но не ограничиваясь) низкую скорость, высокий пинг, субъективное нежелание использовать Сервис, возврат средств **НЕ ПРОИЗВОДИТСЯ**.

### 6. ОТВЕТСТВЕННОСТЬ И ПРАВИЛА ИСПОЛЬЗОВАНИЯ
* **6.1. Запрещенные действия.** Пользователю категорически запрещено:
    * Использовать торрент-клиенты (P2P протоколы);
    * Осуществлять массовые рассылки (спам);
    * Сканировать порты, IP-адреса, осуществлять DDoS-атаки;
    * Распространять Ключ доступа третьим лицам (перепродажа, «слив» в публичный доступ).
    * Использовать Сервис для противоправных действий согласно УК РФ.
* **6.2. Санкции за нарушения.**
    * При выявлении нарушений (в т.ч. автоматическими алгоритмами анализа трафика) доступ к Услуге **приостанавливается**.
    * Срок действия подписки в период приостановки **не продлевается и не замораживается**.
* **6.3. Порядок обжалования.**
    * Пользователь имеет право подать апелляцию в Техническую поддержку в течение **7 (семи) календарных дней** с момента блокировки.
    * Бремя доказывания отсутствия нарушений лежит на Пользователе.
    * Администрация оставляет за собой право отказать в разблокировке и в предоставлении подробностей о причинах блокировки в целях защиты алгоритмов безопасности Сервиса.

### 7. ЗАКЛЮЧИТЕЛЬНЫЕ ПОЛОЖЕНИЯ
* **7.1.** Администрация вправе в одностороннем порядке вносить изменения в настоящую Оферту.
* **7.2.** Оплата Услуг означает полное и безоговорочное согласие с условиями настоящей Оферты.
`;

const PRIVACY_POLICY_TEXT = `
### 1. ОБЩИЕ ПОЛОЖЕНИЯ
**1.1.** Настоящая Политика регламентирует порядок сбора, обработки и хранения технических данных пользователей сервиса 12VPN.
**1.2.** Основным приоритетом Сервиса является минимизация хранимых персональных данных при обеспечении технической стабильности и безопасности сети.

### 2. СОСТАВ СОБИРАЕМЫХ ДАННЫХ
Сервис не осуществляет сбор, хранение или анализ содержимого интернет-трафика Пользователя (Deep Packet Inspection), истории посещенных веб-ресурсов или переписки.
В целях технического обеспечения Услуг собираются следующие метаданные:

**2.1. Идентификационные данные платформы:**
* Уникальный идентификатор пользователя Telegram (Telegram ID);
* Имя пользователя (Username);
* История обращений в службу поддержки (включая переданные скриншоты и логи ошибок).

**2.2. Технические данные сессий:**
* **Объем трафика:** Учет входящих и исходящих пакетов данных (в байтах) для контроля лимитов и выявления аномальной нагрузки.
* **Аппаратные идентификаторы:** Хешированные данные об устройстве (HWID) или уникальные «отпечатки» клиента (Fingerprint). Сбор данных осуществляется исключительно с целью предотвращения мультиаккаунтинга (нарушение правила «1 ключ = 1 устройство») и борьбы с перепродажей Ключей.

**2.3. Платежные данные:**
* ID транзакции, сумма, метод оплаты. Полные данные банковских карт не обрабатываются и не хранятся Сервисом (обработка производится на стороне платежных шлюзов).

### 3. ЦЕЛИ ОБРАБОТКИ И ХРАНЕНИЯ
**3.1.** Обеспечение автоматической выдачи и ротации цифровых ключей.
**3.2.** Автоматический мониторинг нагрузки на сеть и предотвращение перегрузок (DDoS).
**3.3.** Выявление нарушений Условий использования (сканирование портов, спам-активность) на основе анализа метаданных трафика.

### 4. ПЕРЕДАЧА ДАННЫХ И ВЗАИМОДЕЙСТВИЕ С ТРЕТЬИМИ ЛИЦАМИ
**4.1.** Сервис не передает данные третьим лицам в коммерческих или маркетинговых целях.
**4.2.** Раскрытие накопленных метаданных государственным органам возможно исключительно при наличии вступившего в законную силу судебного акта, оформленного в соответствии с процессуальным законодательством РФ, и врученного Администрации Сервиса надлежащим образом.

### 5. ОТКАЗ ОТ ОТВЕТСТВЕННОСТИ
**5.1.** Пользователь осознает, что использование сети Интернет связано с рисками. Сервис не несет ответственности за перехват данных, произошедший на устройстве Пользователя или на узлах сети, не контролируемых Сервисом.
`;

// Один бесплатный тариф в честь Рамадана (до 20.03.2026). Платные подписки отключены.
const RAMADAN_END = new Date('2026-03-20');
const daysUntilRamadanEnd = Math.max(1, Math.ceil((RAMADAN_END.getTime() - Date.now()) / (1000 * 60 * 60 * 24)));
const VPN_PLANS_DEFAULT: Plan[] = [
  { id: 'ramadan', duration: 'Бесплатно в честь Рамадана (до 20.03.2026)', price: 0, highlight: true, days: daysUntilRamadanEnd, isTrial: false }
];

const PRESET_AMOUNTS = [100, 250, 500, 1000, 2000, 5000]; // Минимум 50₽, максимум 100,000₽


// Платежные методы загружаются из API с комиссиями, но оставляем дефолтные
const PAYMENT_METHODS_DEFAULT: PaymentMethod[] = [
  { 
    id: 'sbp', 
    name: 'СБП', 
    icon: '⚡', 
    feePercent: 0, 
    variants: [
      { id: 'platega_sbp', name: 'Platega', feePercent: 0 }
    ]
  },
  { 
    id: 'card', 
    name: 'Банковская карта', 
    icon: '💳', 
    feePercent: 0, 
    variants: [
      { id: 'platega_card', name: 'Platega', feePercent: 0 }
    ]
  },
];

const WITHDRAW_METHODS = [
  { id: 'balance', name: 'На баланс', icon: <Wallet size={20} />, min: 1 },
  { id: 'card', name: 'На карту', icon: <CreditCard size={20} />, min: 200 },
  // КРИПТОВАЛЮТА ОТКЛЮЧЕНА
  // { id: 'crypto', name: 'Криптокошелек', icon: <img src="https://cryptologos.cc/logos/tether-usdt-logo.svg?v=026" className="w-5 h-5 invert" alt="USDT" />, min: 200 },
];

const PLATFORMS: { id: PlatformId; name: string; icon: React.ReactNode }[] = [
  { id: 'android', name: 'Android', icon: <Smartphone size={32} /> },
  { id: 'ios', name: 'iOS (iPhone)', icon: <Apple size={32} /> },
  { id: 'windows', name: 'Windows PC', icon: <Monitor size={32} /> },
  { id: 'macos', name: 'MacOS', icon: <Command size={32} /> },
  { id: 'linux', name: 'Linux', icon: <Monitor size={32} /> },
  { id: 'androidtv', name: 'Android TV', icon: <Tv size={32} /> },
];

const INSTRUCTIONS: Record<string, PlatformData> = {
  android: {
    id: 'android',
    title: 'Android',
    icon: <Smartphone size={20} />,
    steps: [
      {
        title: '1. Установка приложения',
        desc: 'Установите приложение из Google Play или скачайте APK.',
        actions: [
          { label: 'Google Play', url: 'https://play.google.com/store/apps/details?id=com.happproxy', primary: true },
          { label: 'Скачать .APK', url: 'https://github.com/Happ-proxy/happ-android/releases/latest/download/Happ.apk', primary: false }
        ]
      },
      {
        title: '2. Добавляем подписку',
        desc: 'Нажмите кнопку ниже, чтобы добавить подписку в приложение.',
        actions: [
          { label: 'Добавить подписку', type: 'trigger_add', primary: true }
        ]
      },
      {
        title: '3. Обновляем и подключаемся',
        desc: 'В приложении нажмите кнопку обновления (🔄) и выберите локацию.'
      }
    ]
  },
  ios: {
    id: 'ios',
    title: 'iOS (iPhone/iPad)',
    icon: <Apple size={20} />,
    steps: [
      {
        title: '1. Установка приложения',
        desc: 'Установите приложение из App Store.',
        actions: [
          { label: 'App Store', url: 'https://apps.apple.com/ru/app/happ-proxy-utility-plus/id6746188973', primary: true }
        ]
      },
      {
        title: '2. Добавляем подписку',
        desc: 'Нажмите кнопку ниже для автоматического добавления.',
        actions: [
          { label: 'Добавить подписку', type: 'trigger_add', primary: true }
        ]
      },
      {
        title: '3. Подключение',
        desc: 'Нажмите (🔄) в приложении, выберите сервер и подключитесь.',
        actions: [
          { label: 'Подключиться!', url: 'happ://connect', primary: true }
        ]
      }
    ]
  },
  windows: {
    id: 'windows',
    title: 'Windows',
    icon: <Monitor size={20} />,
    steps: [
      {
        title: '1. Установка',
        desc: 'Скачайте и установите .EXE файл.',
        actions: [
          { label: 'Скачать .EXE', url: 'https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe', primary: true }
        ]
      },
      {
        title: '2. Копирование ключа',
        desc: 'Скопируйте ваш персональный ключ доступа.',
        actions: [
          { label: 'Скопировать ключ', type: 'copy_key', primary: true }
        ]
      },
      {
        title: '3. Настройка',
        desc: 'Вставьте скопированный ключ в приложение и подключитесь.'
      }
    ]
  },
  macos: {
    id: 'macos',
    title: 'MacOS',
    icon: <Command size={20} />,
    steps: [
      {
        title: '1. Установка',
        desc: 'Установите через AppStore.',
        actions: [
          { label: 'App Store', url: 'https://apps.apple.com/ru/app/happ-proxy-utility-plus/id6746188973', primary: true }
        ]
      },
      {
        title: '2. Ключ доступа',
        desc: 'Скопируйте ключ и вставьте его в приложении.',
        actions: [
          { label: 'Скопировать ключ', type: 'copy_key', primary: true }
        ]
      }
    ]
  },
  linux: {
    id: 'linux',
    title: 'Linux',
    icon: <Monitor size={20} />, 
    steps: [
      {
        title: '1. Установка',
        desc: 'Скачайте релиз с GitHub.',
        actions: [
          { label: 'GitHub Releases', url: 'https://github.com/Happ-proxy/happ-desktop/releases/', primary: true }
        ]
      },
      {
        title: '2. Ключ доступа',
        desc: 'Скопируйте ключ и вставьте его в приложении.',
        actions: [
          { label: 'Скопировать ключ', type: 'copy_key', primary: true }
        ]
      }
    ]
  },
  androidtv: {
    id: 'androidtv',
    title: 'Android TV',
    icon: <Tv size={20} />,
    steps: [
      {
        title: '1. Подготовка',
        desc: 'Сначала добавьте ключ на свой смартфон.',
        actions: [
          { label: 'Инструкция Android', type: 'nav_android', primary: false },
          { label: 'Инструкция iOS', type: 'nav_ios', primary: false }
        ]
      },
      {
        title: '2. Установка на TV',
        desc: 'Найдите "Happ" в Google Play на телевизоре и установите.'
      },
      {
        title: '3. Синхронизация',
        desc: 'На TV: нажмите "+" -> "Добавить подписку". На телефоне: "+" -> "QR-код". Отсканируйте код.'
      }
    ]
  }
};

// ==========================================
// 3. UI COMPONENTS
// ==========================================

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'outline' | 'danger' | 'ghost' | 'trial' | 'gold';
}

const Button: React.FC<ButtonProps> = ({ children, onClick, variant = 'primary', className = '', disabled = false }) => {
  const baseStyle = "w-full py-3.5 rounded-xl font-semibold transition-all duration-200 flex items-center justify-center gap-2 active:scale-[0.97] disabled:opacity-50 disabled:active:scale-100 disabled:cursor-not-allowed ripple";
  const variants = {
    primary: "bg-blue-500 hover:bg-blue-600 text-white",
    secondary: "bg-white/5 hover:bg-white/10 text-white border border-white/10",
    outline: "border border-blue-500/50 text-blue-400 hover:bg-blue-500/10",
    danger: "bg-red-500/20 text-red-400 hover:bg-red-500/30 border border-red-500/40",
    ghost: "text-gray-400 hover:text-white hover:bg-white/5",
    trial: "bg-gradient-to-r from-purple-500 to-blue-500 text-white hover:brightness-110",
    gold: "bg-gradient-to-r from-amber-500 to-yellow-500 text-white"
  };

  return (
    <button onClick={onClick} className={`${baseStyle} ${variants[variant]} ripple ${className}`} disabled={disabled}>
      {children}
    </button>
  );
};

const Card: React.FC<{ children: React.ReactNode, className?: string, onClick?: () => void }> = ({ children, className = '', onClick }) => (
  <div onClick={onClick} className={`bg-white/5 border border-white/10 rounded-2xl p-5 ${className}`}>
    {children}
  </div>
);

const Header: React.FC<{ title: string, onBack?: () => void }> = ({ title, onBack }) => (
  <div className="flex items-center gap-4 mb-6 px-4">
    {onBack && (
      <button onClick={onBack} className="w-10 h-10 rounded-full bg-white/5 flex items-center justify-center text-white hover:bg-white/10 transition-colors">
        <ChevronLeft size={22} />
      </button>
    )}
    <h1 className="text-2xl font-bold text-white">{title}</h1>
  </div>
);

const Modal: React.FC<{ title: string, isOpen: boolean, onClose: () => void, children: React.ReactNode, fullHeight?: boolean }> = ({ title, isOpen, onClose, children, fullHeight = false }) => {
  if (!isOpen) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/80 backdrop-blur-sm transition-opacity" onClick={onClose}></div>
      <div className={`relative bg-black border border-white/10 w-full max-w-sm rounded-3xl p-6 shadow-2xl transform transition-all scale-100 flex flex-col ${fullHeight ? 'h-[85vh]' : 'max-h-[90vh]'}`}>
        <div className="flex justify-between items-center mb-4 shrink-0">
          <h3 className="text-xl font-bold text-white">{title}</h3>
          <button onClick={onClose} className="w-9 h-9 rounded-full bg-white/5 flex items-center justify-center text-gray-400 hover:text-white hover:bg-white/10 transition-colors">
            <X size={20} />
          </button>
        </div>
        <div className="overflow-y-auto custom-scrollbar flex-1 pr-1">
            {children}
        </div>
      </div>
    </div>
  );
};

// Simple Markdown Renderer for Legal Docs
const MarkdownRenderer: React.FC<{ content: string }> = ({ content }) => {
  const lines = content.split('\n');
  return (
    <div className="space-y-3 text-slate-300 text-sm leading-relaxed">
      {lines.map((line, idx) => {
        if (line.startsWith('### ')) {
          return <h3 key={idx} className="text-lg font-bold text-white mt-4 mb-2">{line.replace('### ', '')}</h3>;
        }
        if (line.startsWith('**') && !line.includes('**', 2)) {
          // Headers that are just bold lines or similar
          return <p key={idx} className="font-bold text-white">{line.replace(/\*\*/g, '')}</p>;
        }
        if (line.startsWith('* ')) {
           // List items
           const cleanLine = line.replace('* ', '');
           // Simple bold parser for inside line
           const parts = cleanLine.split('**');
           return (
             <div key={idx} className="flex gap-2 pl-2">
                <span className="text-blue-500 mt-1.5">•</span>
                <span>
                    {parts.map((part, pIdx) => (pIdx % 2 === 1 ? <strong key={pIdx} className="text-slate-200">{part}</strong> : part))}
                </span>
             </div>
           );
        }
        // Paragraphs with inline bold
        const parts = line.split('**');
        return (
            <p key={idx} className={line.trim() === '' ? 'h-2' : ''}>
                {parts.map((part, pIdx) => (pIdx % 2 === 1 ? <strong key={pIdx} className="text-slate-200">{part}</strong> : part))}
            </p>
        );
      })}
    </div>
  );
};


// ==========================================
// 4. MAIN APPLICATION
// ==========================================

export default function App() {
  // --- STATE ---
  const [view, setView] = useState<ViewState>('home'); 
  const [balance, setBalance] = useState<number>(0);
  const [isTrialUsed, setIsTrialUsed] = useState<boolean>(false);
  const [userId, setUserId] = useState<number | null>(null);
  const [telegramId, setTelegramId] = useState<number | null>(null);
  const [username, setUsername] = useState<string>('User');
  const [displayName, setDisplayName] = useState<string>('User'); // first_name для отображения
  const [userPhotoUrl, setUserPhotoUrl] = useState<string | null>(null);
  
  // Data
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [deviceKeys, setDeviceKeys] = useState<Map<number, string>>(new Map()); // key: device_id, value: key_config
  
  // Modal States
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [withdrawModalOpen, setWithdrawModalOpen] = useState(false); 
  // Legal Docs Modal
  const [docModalOpen, setDocModalOpen] = useState(false);
  const [docContent, setDocContent] = useState<{ title: string, text: string } | null>(null);
  const [publicPages, setPublicPages] = useState<{ offer: string, privacy: string }>({
    offer: OFFER_AGREEMENT_TEXT,
    privacy: PRIVACY_POLICY_TEXT
  });

  const [currentDevice, setCurrentDevice] = useState<Device | null>(null);
  const [newName, setNewName] = useState('');

  // Ban Status
  const [isBanned, setIsBanned] = useState(false);
  const [banReason, setBanReason] = useState<string>('');

  // Onboarding (Tutorial)
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [onboardingStep, setOnboardingStep] = useState(0);

  // Referral Data
  const [referrals, setReferrals] = useState({ count: 0, earned: 0, partnerBalance: 0 });
  const [referralList, setReferralList] = useState<ReferralUser[]>([]);
  const [selectedReferral, setSelectedReferral] = useState<ReferralUser | null>(null);
  const [lastCardWithdrawal, setLastCardWithdrawal] = useState<string | null>(null);
  const [withdrawState, setWithdrawState] = useState({ 
    step: 1, 
    amount: '', 
    method: null as string | null, 
    phone: '', 
    bank: '', 
    cryptoNet: '', 
    cryptoAddr: '',
  });

  // TopUp State
  const [topupStep, setTopupStep] = useState(1); 
  const [topupAmount, setTopupAmount] = useState(0);
  const [selectedMethod, setSelectedMethod] = useState<string | null>(null);
  const [selectedVariant, setSelectedVariant] = useState<string | null>(null);
  const [paymentMethods, setPaymentMethods] = useState<PaymentMethod[]>(PAYMENT_METHODS_DEFAULT);
  const [paymentUrl, setPaymentUrl] = useState<string | null>(null); // URL для оплаты
  
  // Pending Purchase
  const [pendingAction, setPendingAction] = useState<{ type: string, payload: any } | null>(null);

  // VPN Plans - загружаются из API, fallback на дефолтные
  const [vpnPlans, setVpnPlans] = useState<Plan[]>(VPN_PLANS_DEFAULT);

  // Connection Wizard State
  const [wizardStep, setWizardStep] = useState(1); // 1: Platform, 2: Plan, 3: Payment/Confirm, 4: Instructions
  const [wizardPlatform, setWizardPlatform] = useState<PlatformId>('android');
  const [wizardPlan, setWizardPlan] = useState<Plan | null>(null);
  const [wizardType] = useState<'vpn'>('vpn'); 
  const [useAutoPay, setUseAutoPay] = useState(false);
  const [savedPaymentMethods, setSavedPaymentMethods] = useState<any[]>([]);
  const [selectedPaymentMethodId, setSelectedPaymentMethodId] = useState<string | null>(null);

  
  // Extend subscription state - для продления существующего ключа
  const [extendingDevice, setExtendingDevice] = useState<Device | null>(null);
  const [extendPlan, setExtendPlan] = useState<Plan | null>(null); 
  
  // Instructions State
  const [activePlatform, setActivePlatform] = useState<string>('android');

  // Detect Platform & load user on Mount
  useEffect(() => {
    const ua = navigator.userAgent.toLowerCase();
    let detected: PlatformId = 'android';
    if (ua.includes('iphone') || ua.includes('ipad')) detected = 'ios';
    else if (ua.includes('android')) detected = 'android';
    else if (ua.includes('win')) detected = 'windows';
    else if (ua.includes('mac')) detected = 'macos';
    else if (ua.includes('linux')) detected = 'linux';
    
    setActivePlatform(detected);
    setWizardPlatform(detected);

    // Определяем Telegram ID и username из Telegram WebApp
    let tgId: number | null = null;
    let tgUsername: string = '';
    let tgFirstName: string = '';
    let referralId: number | null = null;
    const win: any = window as any;
    
    if (win.Telegram?.WebApp?.initDataUnsafe?.user) {
      const tgUser = win.Telegram.WebApp.initDataUnsafe.user;
      tgId = Number(tgUser.id);
      tgUsername = tgUser.username || '';
      tgFirstName = tgUser.first_name || '';
      
      // Получаем URL аватарки пользователя из Telegram WebApp
      if (tgUser.photo_url) {
        setUserPhotoUrl(tgUser.photo_url);
      }
      
      // Извлекаем реферальный ID из start_param (формат: ref123456789)
      const startParam = win.Telegram.WebApp.initDataUnsafe?.start_param;
      if (startParam && typeof startParam === 'string') {
        const refMatch = startParam.match(/ref(\d+)/);
        if (refMatch) {
          referralId = parseInt(refMatch[1], 10);
          // Нельзя быть своим собственным рефералом
          if (referralId === tgId) {
            referralId = null;
          }
        }
      }
      
      // Уведомляем Telegram что приложение готово
      win.Telegram.WebApp.ready();
      win.Telegram.WebApp.expand();
    } else {
      const params = new URLSearchParams(window.location.search);
      const fromQuery = params.get('telegram_id');
      if (fromQuery) tgId = Number(fromQuery);
      tgUsername = params.get('username') || '';
      tgFirstName = params.get('first_name') || '';
      // Также проверяем ref параметр из URL
      const refParam = params.get('ref');
      if (refParam) {
        referralId = parseInt(refParam, 10);
        if (isNaN(referralId) || referralId === tgId) {
          referralId = null;
        }
      }
    }
    
    if (!tgId) {
      console.error('Telegram ID не определен. Приложение работает только через Telegram.');
      return;
    }

    setTelegramId(tgId);
    if (tgUsername) setUsername(tgUsername);
    // Устанавливаем displayName: приоритет first_name, затем username
    setDisplayName(tgFirstName || tgUsername || 'User');

    (async () => {
      try {
        // Пользователь (автоматически создается если не существует)
        // Передаем реферальный ID и first_name если есть
        let userUrl = `/user/info?telegram_id=${tgId}&username=${encodeURIComponent(tgUsername)}`;
        if (tgFirstName) {
          userUrl += `&first_name=${encodeURIComponent(tgFirstName)}`;
        }
        if (referralId) {
          userUrl += `&ref=${referralId}`;
        }
        const userData = await miniApiFetch(userUrl);
        
        // Проверяем бан
        if (userData && userData._banned) {
          setIsBanned(true);
          setBanReason(userData.reason || 'Аккаунт заблокирован');
          return; // Не загружаем остальные данные
        }
        
        if (userData) {
          setUserId(userData.id);
          setBalance(userData.balance || 0);
          setUsername(userData.username || `User_${tgId}`);
          // Обновляем displayName: full_name из API или первоначальное значение
          setDisplayName(userData.full_name || tgFirstName || userData.username || `User_${tgId}`);
          setIsTrialUsed(userData.trial_used === 1 || userData.trial_used === true);
          setReferrals({
            count: userData.referrals_count || 0,
            earned: userData.referral_earned || 0,
            partnerBalance: userData.partner_balance || 0,
          });
          if (userData.last_card_withdrawal) {
            setLastCardWithdrawal(userData.last_card_withdrawal);
          }
          
          // Показываем онбординг для новых пользователей (без устройств и ключей)
          const onboardingShown = localStorage.getItem(`onboarding_${tgId}`);
          if (!onboardingShown && !userData.trial_used && userData.balance === 0) {
            setShowOnboarding(true);
          }
        }

        // Устройства
        const devicesData = await miniApiFetch(`/user/devices?telegram_id=${tgId}`);
        if (Array.isArray(devicesData)) {
          const devicesList: Device[] = devicesData.map((d: any) => ({
            id: d.id,
            name: d.name,
            type: d.type,
            added: d.added,
            key_uuid: d.key_uuid,
            short_uuid: d.short_uuid,
            key_status: d.key_status,
            days_left: d.days_left,
            hours_left: d.hours_left,
            is_expired: d.is_expired,
            expiry_date: d.expiry_date
          }));
          setDevices(devicesList);
          
          const keysMap = new Map<number, string>();
          devicesData.forEach((d: any) => {
            if (d.key_config) {
              keysMap.set(d.id, d.key_config);
            }
          });
          setDeviceKeys(keysMap);
        }

        // История
        const historyData = await miniApiFetch(`/user/history?telegram_id=${tgId}`);
        if (Array.isArray(historyData)) {
          setHistory(historyData);
        }

        // Публичные страницы (оферта и политика)
        try {
          const publicPagesData = await miniApiFetch('/public-pages');
          if (publicPagesData) {
            setPublicPages({
              offer: publicPagesData.offer?.content || OFFER_AGREEMENT_TEXT,
              privacy: publicPagesData.privacy?.content || PRIVACY_POLICY_TEXT
            });
          }
        } catch (e) {
          console.error('Failed to load public pages, using defaults', e);
        }

        // Тарифы: только бесплатный в честь Рамадана (до 20.03.2026). Платные из API не используем.
        setVpnPlans(VPN_PLANS_DEFAULT);
      } catch (err) {
        console.error('Ошибка загрузки данных:', err);
      }
    })();
  }, []);
  
  // Load referrals list
  useEffect(() => {
    if (!telegramId) return;
    (async () => {
      try {
        const data = await miniApiFetch(`/user/referrals?telegram_id=${telegramId}`);
        if (Array.isArray(data)) {
          setReferralList(data);
        }
      } catch (e) {
        console.error('Failed to load referrals list', e);
      }
    })();
  }, [telegramId]);
  
  // Helpers
  const formatMoney = (val: number) => new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', maximumFractionDigits: 0 }).format(val);
  
  const addHistoryItem = (type: string, title: string, amount: number) => {
    const newItem: HistoryItem = {
      id: Date.now(),
      type,
      title,
      amount,
      date: new Date().toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' })
    };
    setHistory(prev => [newItem, ...prev]);
  };

  const refreshDevices = async () => {
    if (!telegramId) return;
    try {
      const devicesData = await miniApiFetch(`/user/devices?telegram_id=${telegramId}`);
      if (Array.isArray(devicesData)) {
        const devicesList: Device[] = devicesData.map((d: any) => ({
          id: d.id,
          name: d.name,
          type: d.type,
          added: d.added,
          key_uuid: d.key_uuid,
          short_uuid: d.short_uuid,
          key_status: d.key_status,
          days_left: d.days_left,
          hours_left: d.hours_left,
          is_expired: d.is_expired,
          expiry_date: d.expiry_date
        }));
        setDevices(devicesList);

        const keysMap = new Map<number, string>();
        devicesData.forEach((d: any) => {
          if (d.key_config) {
            keysMap.set(d.id, d.key_config);
          }
        });
        setDeviceKeys(keysMap);
      }
    } catch (e) {
      console.error('Failed to refresh devices', e);
    }
  };

  const refreshUserData = async (): Promise<{ balance: number } | null> => {
    if (!telegramId) return null;
    try {
      const userData = await miniApiFetch(`/user/info?telegram_id=${telegramId}`);
      if (userData) {
        const newBalance = userData.balance || 0;
        setBalance(newBalance);
        setUserId(userData.id);
        setUsername(userData.username || `User_${telegramId}`);
        setIsTrialUsed(userData.trial_used === 1 || userData.trial_used === true);
        setReferrals({
          count: userData.referrals_count || 0,
          earned: userData.referral_earned || 0,
          partnerBalance: userData.partner_balance || 0,
        });
        if (userData.last_card_withdrawal) {
          setLastCardWithdrawal(userData.last_card_withdrawal);
        }
        return { balance: newBalance };
      }
      return null;
    } catch (e) {
      console.error('Failed to refresh user data', e);
      return null;
    }
  };

  const refreshAll = async () => {
    await Promise.all([
      refreshUserData(),
      refreshDevices(),
    ]);
  };

  // Получить userId, если еще не загружен
  const ensureUserId = async (): Promise<number | null> => {
    if (userId) return userId;
    if (!telegramId) return null;
    
    try {
      const userData = await miniApiFetch(`/user/info?telegram_id=${telegramId}`);
      if (userData && userData.id) {
        setUserId(userData.id);
        setBalance(userData.balance || 0);
        setIsTrialUsed(userData.trial_used === 1 || userData.trial_used === true);
        return userData.id;
      }
    } catch (e) {
      console.error('Failed to ensure userId', e);
    }
    return null;
  };

  // Получить Happ зашифрованную ссылку через наш бэкенд (который проксирует на crypto.happ.su)
  const getHappEncryptedLink = async (subscriptionUrl: string): Promise<string | null> => {
    try {
      const response = await fetch('/api/encrypt-link', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: subscriptionUrl })
      });
      
      if (response.ok) {
        const data = await response.json();
        if (data && data.encrypted_link) {
          console.log('Got encrypted link:', data.encrypted_link);
          return data.encrypted_link;
        }
      }
      const errorText = await response.text();
      console.error('Encryption API failed:', response.status, errorText);
      return null;
    } catch (e) {
      console.error('Encryption API error:', e);
      return null;
    }
  };

  // Открыть Happ с зашифрованной ссылкой через редирект-страницу
  const openHappWithSubscription = async (deviceId?: number) => {
    console.log('openHappWithSubscription called, deviceId:', deviceId);
    console.log('Available devices:', devices);
    console.log('Device keys:', Array.from(deviceKeys.entries()));
    
    let subscriptionUrl: string | null = null;
    
    // Получаем URL подписки из deviceKeys
    if (deviceId && deviceKeys.has(deviceId)) {
      subscriptionUrl = deviceKeys.get(deviceId) || null;
    } else {
      // Пробуем найти активное устройство с ключом
      const activeDevice = devices.find(d => deviceKeys.has(d.id));
      if (activeDevice) {
        subscriptionUrl = deviceKeys.get(activeDevice.id) || null;
        console.log('Found active device:', activeDevice.id, 'with URL:', subscriptionUrl);
      }
    }
    
    if (!subscriptionUrl) {
      console.log('No subscription URL found');
      alert('У вас нет активных подписок. Сначала создайте подписку.');
      return;
    }
    
    // Шифруем ссылку
    console.log('Encrypting URL:', subscriptionUrl);
    const encryptedLink = await getHappEncryptedLink(subscriptionUrl);
    console.log('Encrypted link:', encryptedLink);
    
    if (!encryptedLink) {
      alert('Не удалось зашифровать ссылку. Попробуйте позже.');
      return;
    }
    
    // Telegram не позволяет открывать не-HTTPS ссылки напрямую,
    // поэтому используем редирект через API
    const redirectUrl = `${window.location.origin}/api/redirect?url=${encodeURIComponent(encryptedLink)}`;
    console.log('Opening redirect URL:', redirectUrl);
    
    // Открываем редирект-страницу
    const win = window as any;
    if (win.Telegram?.WebApp?.openLink) {
      // openLink открывает во внешнем браузере - там сработает редирект на happ://
      win.Telegram.WebApp.openLink(redirectUrl);
    } else {
      // Fallback - открываем в новом окне
      window.open(redirectUrl, '_blank');
    }
  };

  const handleCopy = (text: string, deviceId?: number) => {
    try {
      // Если передан deviceId, пытаемся получить реальный ключ из deviceKeys
      let keyToCopy = text;
      if (deviceId && deviceKeys.has(deviceId)) {
        keyToCopy = deviceKeys.get(deviceId)!;
      }
      
      const el = document.createElement('textarea');
      el.value = keyToCopy;
      document.body.appendChild(el);
      el.select();
      document.execCommand('copy');
      document.body.removeChild(el);
      alert('Скопировано в буфер!');
    } catch (e) {
      console.error(e);
      alert('Ошибка копирования. Пожалуйста, выделите и скопируйте текст вручную.');
    }
  };

  const openDoc = (title: string, text: string) => {
      setDocContent({ title, text });
      setDocModalOpen(true);
  };

  // --- LOGIC: MODAL HANDLERS ---

  const openEditModal = (device: Device) => {
    setCurrentDevice(device);
    setNewName(device.name);
    setEditModalOpen(true);
  };

  const saveDeviceName = () => {
    if (newName && newName.trim() !== '' && currentDevice) {
      setDevices(prev => prev.map(d => d.id === currentDevice.id ? { ...d, name: newName } : d));
      setEditModalOpen(false);
      setCurrentDevice(null);
    }
  };

  const openDeleteModal = (device: Device) => {
    setCurrentDevice(device);
    setDeleteModalOpen(true);
  };

  const confirmDeleteDevice = async () => {
    if (!currentDevice || !telegramId) return;
    
    try {
      // Удаляем на сервере
      const result = await miniApiFetch(`/user/devices/${currentDevice.id}?telegram_id=${telegramId}`, {
        method: 'DELETE'
      });
      
      if (result && result.success) {
        // Обновляем локально
        setDevices(prev => prev.filter(d => d.id !== currentDevice.id));
        setDeviceKeys(prev => {
          const newMap = new Map(prev);
          newMap.delete(currentDevice.id);
          return newMap;
        });
        addHistoryItem('device_del', `Удалено устройство: ${currentDevice.name}`, 0);
      } else {
        alert(result?.error || 'Не удалось удалить устройство');
        // Обновляем список устройств с сервера на случай рассинхронизации
        refreshDevices();
      }
    } catch (e) {
      console.error('Failed to delete device', e);
      alert('Ошибка при удалении устройства');
      // Обновляем список устройств с сервера
      refreshDevices();
    }
    
    setDeleteModalOpen(false);
    setCurrentDevice(null);
  };

  // --- LOGIC: WITHDRAWAL ---

  const openWithdrawModal = () => {
    setWithdrawState(prev => ({ ...prev, step: 1, amount: '', method: null })); 
    setWithdrawModalOpen(true);
  };

  const handleWithdrawNext = async () => {
    const { step, amount, method } = withdrawState;
    const numAmount = Number(amount);

    if (step === 1) {
      if (!amount || numAmount <= 0) return alert("Введите сумму");
      if (numAmount > referrals.partnerBalance) return alert("Недостаточно средств на реферальном балансе");
      setWithdrawState(prev => ({ ...prev, step: 2 }));
    } else if (step === 2) {
      if (!method) return alert("Выберите метод");
      if (method === 'card' || method === 'crypto') {
        if (numAmount < 200) return alert("Минимальная сумма вывода на карту/крипто - 200₽");
        
        // Проверка 30-дневного лимита для карты
        if (method === 'card' && lastCardWithdrawal) {
          const lastDate = new Date(lastCardWithdrawal);
          const now = new Date();
          const daysSince = Math.floor((now.getTime() - lastDate.getTime()) / (24 * 60 * 60 * 1000));
          if (daysSince < 30) {
            const daysLeft = 30 - daysSince;
            return alert(`Вывод на карту доступен не чаще 1 раза в 30 дней. Осталось дней: ${daysLeft}`);
          }
        }
      }
      setWithdrawState(prev => ({ ...prev, step: 3 }));
    } else if (step === 3) {
      // Отправляем запрос на сервер для обработки вывода
      try {
        const requestData: any = {
          telegram_id: telegramId,
          amount: numAmount,
          method: method,
        };
        
        if (method === 'card') {
          if (!withdrawState.phone || !withdrawState.bank) return alert("Заполните все поля");
          requestData.phone = withdrawState.phone;
          requestData.bank = withdrawState.bank;
        } else if (method === 'crypto') {
          if (!withdrawState.cryptoNet || !withdrawState.cryptoAddr) return alert("Заполните все поля");
          requestData.crypto_net = withdrawState.cryptoNet;
          requestData.crypto_addr = withdrawState.cryptoAddr;
        }
        
        const result = await miniApiFetch('/user/withdraw', {
          method: 'POST',
          body: JSON.stringify(requestData),
        });
        
        if (result && result.success) {
          if (method === 'balance') {
            setBalance(prev => prev + numAmount);
            addHistoryItem('ref_out', 'Вывод на баланс', numAmount);
          } else if (method === 'card') {
            setLastCardWithdrawal(new Date().toISOString());
            addHistoryItem('ref_req', 'Заявка на вывод (Карта)', 0);
          } else if (method === 'crypto') {
            addHistoryItem('ref_req', 'Заявка на вывод (Crypto)', 0);
          }
          
          setReferrals(prev => ({ ...prev, partnerBalance: prev.partnerBalance - numAmount }));
          setWithdrawState(prev => ({ ...prev, step: 4 }));
        } else {
          alert(result?.error || 'Не удалось выполнить вывод');
        }
      } catch (e) {
        console.error('Withdrawal error:', e);
        alert('Ошибка при выводе средств');
      }
    }
  };


  // Функция продления существующей подписки
  const extendSubscription = async (device: Device, plan: Plan) => {
    const price = plan.price;
    const currentUserId = await ensureUserId();
    
    if (!currentUserId) {
      alert('Не удалось загрузить данные пользователя. Попробуйте перезагрузить приложение.');
      return;
    }
    
    if (balance < price) {
      // Недостаточно средств - переходим к пополнению
      if(window.confirm(`Недостаточно средств. Стоимость: ${price} ₽. Ваш баланс: ${balance} ₽. Пополнить баланс?`)) {
        setPendingAction({
          type: 'extend',
          payload: { device, plan, price, name: `Продление VPN (${plan.duration})` }
        });
        setTopupAmount(price - balance);
        setTopupStep(2);
        setView('topup');
      }
      return;
    }
    
    try {
      const res = await miniApiFetch('/subscription/extend', {
        method: 'POST',
        body: JSON.stringify({
          user_id: currentUserId,
          key_id: device.id,
          days: plan.days,
          price: price,
        }),
      });
      
      if (res && res.success) {
        addHistoryItem('extend', `Продление подписки (${plan.duration})`, -price);
        await refreshAll();
        setExtendingDevice(null);
        setExtendPlan(null);
        setView('devices');
        alert('Подписка успешно продлена!');
      } else {
        alert(res?.error || 'Не удалось продлить подписку');
      }
    } catch (e) {
      console.error('Failed to extend subscription', e);
      alert('Ошибка продления подписки');
    }
  };

  const wizardActivate = async () => {
    let price = 0;
    let name = '';

    // Получаем userId если еще не загружен
    const currentUserId = await ensureUserId();
    if (!currentUserId) {
      alert('Не удалось загрузить данные пользователя. Попробуйте перезагрузить приложение.');
      return;
    }

    if (wizardType === 'vpn') {
        if (!wizardPlan) return;
        if (wizardPlan.isTrial) {
            // Активируем триал через API
            try {
              const res = await miniApiFetch('/subscription/create', {
                method: 'POST',
                body: JSON.stringify({
                  user_id: currentUserId,
                  days: wizardPlan.days || 1,
                  type: 'vpn',
                  is_trial: true,
                  price: 0,
                }),
              });
              
              if (res && res.success) {
                setIsTrialUsed(true);
                addHistoryItem('trial', 'Активация пробного периода', 0);
                await refreshAll();
                setWizardStep(4);
              } else {
                alert(res?.error || 'Ошибка активации пробного периода');
              }
            } catch (e) {
              console.error('Failed to activate trial', e);
              alert('Ошибка активации пробного периода');
            }
            return;
        }
        price = wizardPlan.price;
        name = `VPN (${wizardPlan.duration})`;
    }

    if (balance < price) {
      if(window.confirm(`Недостаточно средств. Пополнить баланс на ${price - balance} ₽?`)) {
        setPendingAction({
            type: 'wizard',
            payload: { wizardType: 'vpn', wizardPlan, useAutoPay, selectedPaymentMethodId, price, name }
        });
        setTopupAmount(price - balance);
        setTopupStep(2); // Сразу к способу оплаты
        setView('topup');
      }
      return;
    }

    
    try {
      const res = await miniApiFetch('/subscription/create', {
        method: 'POST',
        body: JSON.stringify({
          user_id: currentUserId,
          days: wizardPlan?.days || 30,
          type: 'vpn',
          price: price,
        }),
      });
      
      if (res && res.success) {
        addHistoryItem('buy_dev', `Подключение: ${name}`, -price);
        await refreshAll();
        setWizardStep(4);
      } else {
        alert(res?.error || 'Не удалось создать подписку');
      }
    } catch (e) {
      console.error(e);
      alert('Ошибка при создании подписки');
    }
  };

  const getPaymentTotal = () => {
    if (!selectedMethod) return topupAmount;
    const method = paymentMethods.find(m => m.id === selectedMethod);
    if (!method) return topupAmount;
    
    let fee = method.feePercent;
    
    // Check if variants exist and one is selected
    if (method.variants && selectedVariant) {
        const v = method.variants.find(v => v.id === selectedVariant);
        if (v) fee = v.feePercent;
    }

    const feeAmount = topupAmount * (fee / 100);
    return topupAmount + feeAmount;
  };

  // --- VIEWS ---

  const HomeView = () => {
    const activeDevice = devices.find(d => !d.is_expired && (d.days_left !== undefined && d.days_left > 0 || d.hours_left !== undefined && d.hours_left > 0));
    const subscriptionActive = activeDevice !== undefined;
    const activeDevicesCount = devices.filter(d => !d.is_expired).length;
    
    return (
      <div className="pb-24">
        {/* Header */}
        <div className="flex items-center justify-between py-6 px-4">
          <div>
            <div className="text-2xl font-bold text-white mb-1">Привет, {displayName}</div>
            <div className="text-sm text-gray-500">Добро пожаловать в 12VPN</div>
          </div>
          <button 
            onClick={() => window.open(SUPPORT_URL, '_blank')}
            className="w-10 h-10 rounded-full bg-white/5 flex items-center justify-center text-gray-400 hover:text-white hover:bg-white/10 transition-colors"
          >
            <MessageCircle size={20} />
          </button>
        </div>

        {/* Main Content */}
        <div className="px-4 space-y-5">
          {/* Balance Card */}
          <div className="bg-white/5 rounded-3xl p-6 border border-white/10">
            <div className="flex items-center justify-between mb-4">
              <div>
                <div className="text-sm text-gray-400 mb-1">Баланс</div>
                <div className="text-4xl font-bold text-white">{formatMoney(balance)}</div>
              </div>
              <button
                onClick={() => { setTopupStep(1); setView('topup'); }}
                className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white text-sm font-semibold rounded-xl transition-colors"
              >
                Пополнить
              </button>
            </div>
          </div>

          {/* Subscription Card */}
          <div className="bg-white/5 rounded-3xl p-6 border border-white/10">
            <div className="flex items-center justify-between mb-4">
              <div>
                <div className="text-sm text-gray-400 mb-1">Подписка</div>
                <div className="flex items-center gap-2">
                  <div className={`w-2 h-2 rounded-full ${subscriptionActive ? 'bg-emerald-400' : 'bg-red-400'}`}></div>
                  <span className="text-lg font-semibold text-white">{subscriptionActive ? 'Активна' : 'Неактивна'}</span>
                </div>
              </div>
              {subscriptionActive && activeDevice && (
                <div className="text-right">
                  <div className="text-xs text-gray-500">Осталось</div>
                  <div className="text-sm font-semibold text-white">
                    {activeDevice.days_left !== undefined && activeDevice.days_left > 0 
                      ? `${activeDevice.days_left} дн.`
                      : activeDevice.hours_left !== undefined && activeDevice.hours_left > 0
                      ? `${activeDevice.hours_left} ч.`
                      : 'Активна'}
                  </div>
                </div>
              )}
            </div>
            <button
              onClick={() => subscriptionActive ? setView('devices') : (() => { setWizardStep(1); setWizardPlan(null); setView('wizard'); })()}
              className="w-full bg-blue-500 hover:bg-blue-600 text-white font-semibold py-3.5 rounded-2xl transition-colors"
            >
              {subscriptionActive ? 'Управление' : 'Подключить VPN'}
            </button>
          </div>

          {/* Quick Actions Grid */}
          <div className="grid grid-cols-2 gap-3">
            <button
              onClick={() => { setTopupStep(1); setView('topup'); }}
              className="bg-white/5 rounded-2xl p-4 border border-white/10 hover:bg-white/10 transition-colors text-left"
            >
              <div className="w-10 h-10 rounded-xl bg-blue-500/20 flex items-center justify-center mb-3">
                <Wallet size={20} className="text-blue-400" />
              </div>
              <div className="text-white font-semibold mb-1">Пополнить</div>
              <div className="text-xs text-gray-400">Минимум 50₽</div>
            </button>
            
            <button
              onClick={() => setView('history')}
              className="bg-white/5 rounded-2xl p-4 border border-white/10 hover:bg-white/10 transition-colors text-left"
            >
              <div className="w-10 h-10 rounded-xl bg-white/10 flex items-center justify-center mb-3">
                <Clock size={20} className="text-white" />
              </div>
              <div className="text-white font-semibold mb-1">История</div>
              <div className="text-xs text-gray-400">Все транзакции</div>
            </button>

            <button
              onClick={() => setView('referral')}
              className="bg-white/5 rounded-2xl p-4 border border-white/10 hover:bg-white/10 transition-colors text-left"
            >
              <div className="w-10 h-10 rounded-xl bg-emerald-500/20 flex items-center justify-center mb-3">
                <UserPlus size={20} className="text-emerald-400" />
              </div>
              <div className="text-white font-semibold mb-1">Рефералы</div>
              <div className="text-xs text-gray-400">{referrals.count} приглашено</div>
            </button>

            <button
              onClick={() => setView('promo')}
              className="bg-white/5 rounded-2xl p-4 border border-white/10 hover:bg-white/10 transition-colors text-left"
            >
              <div className="w-10 h-10 rounded-xl bg-purple-500/20 flex items-center justify-center mb-3">
                <Gift size={20} className="text-purple-400" />
              </div>
              <div className="text-white font-semibold mb-1">Промокод</div>
              <div className="text-xs text-gray-400">Активировать</div>
            </button>
          </div>

          {/* Active Devices */}
          {devices.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center justify-between px-1">
                <div className="text-sm text-gray-400">Активные устройства</div>
                <button
                  onClick={() => setView('devices')}
                  className="text-xs text-blue-400 hover:text-blue-300"
                >
                  Все →
                </button>
              </div>
              {devices.slice(0, 2).map((device) => (
                <div 
                  key={device.id}
                  onClick={() => setView('devices')}
                  className="bg-white/5 rounded-2xl p-4 border border-white/10 hover:bg-white/10 transition-colors cursor-pointer"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-xl bg-white/10 flex items-center justify-center">
                        {device.type === 'ios' || device.type === 'android' ? (
                          <Smartphone size={18} className="text-white" />
                        ) : (
                          <Monitor size={18} className="text-white" />
                        )}
                      </div>
                      <div>
                        <div className="text-white font-semibold text-sm">
                          {device.is_trial ? 'Пробная' : 'VPN'} #{device.id}
                        </div>
                        <div className="text-xs text-gray-400">
                          {device.is_expired ? 'Истекла' : 
                           device.days_left !== undefined && device.days_left > 0 ? `${device.days_left} дней` :
                           device.hours_left !== undefined && device.hours_left > 0 ? `${device.hours_left} часов` : 'Активна'}
                        </div>
                      </div>
                    </div>
                    <ChevronRight size={18} className="text-gray-400" />
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Referral Earnings */}
          {referrals.earned > 0 && (
            <div className="bg-gradient-to-r from-emerald-500/10 to-blue-500/10 rounded-2xl p-4 border border-emerald-500/20">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-gray-400 mb-1">Реферальный доход</div>
                  <div className="text-2xl font-bold text-emerald-400">+{formatMoney(referrals.earned)}</div>
                </div>
                <button
                  onClick={() => setView('referral')}
                  className="px-4 py-2 bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-400 text-sm font-semibold rounded-xl transition-colors border border-emerald-500/30"
                >
                  Вывести
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  };

  const WizardView = () => (
    <div className="pb-24">
      <Header 
        title={
            wizardStep === 1 ? "Выбор устройства" : 
            wizardStep === 2 ? "Выбор тарифа" : 
            wizardStep === 3 ? "Подтверждение" : "Настройка"
        } 
        onBack={() => {
            if (wizardStep === 1) setView('home');
            else setWizardStep(prev => prev - 1);
        }} 
      />

      {wizardStep === 1 && (
        <div className="px-4 space-y-6">
            {devices.length > 0 && (
              <button 
                onClick={() => setView('devices')}
                className="w-full bg-white/5 hover:bg-white/10 border border-white/10 rounded-2xl p-4 flex items-center justify-between transition-colors"
              >
                <div className="flex items-center gap-3">
                  <Monitor size={20} className="text-white" />
                  <span className="text-white font-semibold">Мои устройства</span>
                  <span className="bg-blue-500 text-white text-xs px-2 py-1 rounded-full">{devices.length}</span>
                </div>
                <ChevronRight size={20} className="text-gray-400" />
              </button>
            )}
            <div className="text-sm text-gray-400 text-center mb-4">Выберите тип устройства</div>
            <div className="grid grid-cols-2 gap-3">
                {PLATFORMS.map(p => (
                    <button 
                        key={p.id}
                        onClick={() => { setWizardPlatform(p.id); setWizardStep(2); }}
                        className="bg-white/5 hover:bg-white/10 border border-white/10 rounded-2xl p-5 flex flex-col items-center gap-3 transition-colors"
                    >
                        <div className="text-white">{p.icon}</div>
                        <span className="font-semibold text-white text-sm">{p.name}</span>
                    </button>
                ))}
            </div>
        </div>
      )}

      {wizardStep === 2 && (
        <div className="px-4 space-y-3">
            <div className="text-sm text-gray-400 px-1">Выберите период для {PLATFORMS.find(p => p.id === wizardPlatform)?.name}</div>
            {(vpnPlans || VPN_PLANS_DEFAULT).filter(plan => !plan.isTrial || !isTrialUsed).map((plan) => (
                <button
                    key={plan.id}
                    onClick={() => { setWizardPlan(plan); setWizardStep(3); }}
                    className={`w-full p-4 rounded-2xl border transition-colors text-left ${
                        plan.isTrial ? 'bg-purple-500/10 border-purple-500/30' : 
                        (plan.highlight ? 'bg-amber-500/10 border-amber-500/30' : 'bg-white/5 border-white/10 hover:bg-white/10')
                    }`}
                >
                    <div className="flex justify-between items-center">
                        <div>
                            <div className={`font-semibold text-lg flex items-center gap-2 ${
                                plan.highlight ? 'text-amber-400' : plan.isTrial ? 'text-purple-400' : 'text-white'
                            }`}>
                                {plan.duration}
                                {plan.highlight && <Crown size={16} fill="currentColor" />}
                            </div>
                            {plan.isTrial && <div className="text-xs text-purple-300 mt-1">Бесплатно</div>}
                        </div>
                        <div className="text-right">
                            <div className={`font-bold text-xl ${
                                plan.highlight ? 'text-amber-400' : plan.isTrial ? 'text-purple-400' : 'text-white'
                            }`}>{plan.price} ₽</div>
                        </div>
                    </div>
                </button>
            ))}
        </div>
      )}

      {wizardStep === 3 && (
        <div className="px-4 space-y-6">
            <div className="bg-white/5 rounded-3xl p-6 border border-white/10 text-center">
                <div className="text-gray-400 text-sm mb-2">Вы подключаете</div>
                <div className="text-2xl font-bold text-white mb-6">
                    {wizardPlan?.duration}
                </div>
                
                <div className="border-t border-white/10 pt-4 flex justify-between items-center">
                    <span className="text-gray-400">Стоимость:</span>
                    <span className="text-xl font-bold text-white">
                        {wizardPlan?.price} ₽
                    </span>
                </div>
            </div>

            <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-2xl p-4 flex gap-3 items-start">
                <AlertTriangle className="text-yellow-400 shrink-0 mt-0.5" size={18} />
                <div className="text-yellow-400 text-xs leading-relaxed">
                    <strong>Важно:</strong> 1 подписка = 1 устройство. При использовании на нескольких устройствах подписка будет заблокирована.
                </div>
            </div>

            <div className="space-y-4">
                <div className="flex justify-between items-center text-sm">
                    <span className="text-gray-400">Ваш баланс:</span>
                    <span className={`font-semibold ${
                        balance < (wizardPlan?.price || 0) 
                        ? 'text-red-400' 
                        : 'text-emerald-400'
                    }`}>{balance} ₽</span>
                </div>

                {balance >= (wizardPlan?.price || 0) ? (
                    <Button onClick={wizardActivate} variant={wizardPlan?.isTrial || (wizardPlan?.price === 0) ? 'trial' : 'primary'}>
                        {wizardPlan?.isTrial || (wizardPlan?.price === 0) ? 'Активировать бесплатно' : 'Оплатить и подключить'}
                    </Button>
                ) : (
                    <Button onClick={() => {
                        const price = wizardPlan?.price || 0;
                        setPendingAction({
                            type: 'wizard',
                            payload: { wizardType: 'vpn', wizardPlan, useAutoPay, selectedPaymentMethodId, price, name: `VPN (${wizardPlan?.duration})` }
                        });
                        setTopupAmount(price - balance);
                        setTopupStep(2);
                        setView('topup');
                    }}>
                        Пополнить на {(wizardPlan?.price || 0) - balance} ₽
                    </Button>
                )}
            </div>
        </div>
      )}

      {wizardStep === 4 && (
        <div className="flex-1 flex flex-col h-full animate-fade-in">
            <div className="text-center mb-6">
                <div className="w-16 h-16 bg-green-500/10 rounded-full flex items-center justify-center text-green-500 mx-auto mb-4 animate-scale-in">
                    <CheckCircle size={32} />
                </div>
                <h2 className="text-2xl font-bold text-white animate-slide-up">Успешно!</h2>
                <p className="text-slate-400 animate-slide-up" style={{ animationDelay: '0.1s' }}>Подписка активирована. Настройте ваше устройство:</p>
            </div>

            <div className="flex-1 overflow-y-auto bg-slate-800/50 rounded-2xl p-4 border border-slate-700">
                {INSTRUCTIONS[wizardPlatform].steps.map((step, idx) => (
                    <div key={idx} className="relative pl-6 border-l-2 border-slate-700 pb-6 last:border-0 last:pb-0">
                        <div className="absolute -left-[9px] top-0 w-4 h-4 rounded-full bg-slate-900 border-2 border-blue-500"></div>
                        <h3 className="font-bold text-white text-md mb-1 leading-none">{step.title}</h3>
                        <p className="text-slate-400 text-xs mb-3 leading-relaxed">{step.desc}</p>
                        
                        {step.actions && (
                            <div className="flex flex-col gap-2">
                            {step.actions.map((action, aIdx) => (
                                <button
                                key={aIdx}
                                onClick={async () => {
                                    if (action.type === 'copy_key') {
                                        // Получаем ключ первого активного устройства или показываем сообщение
                                        const activeDevice = devices.find(d => d.id);
                                        if (activeDevice && deviceKeys.has(activeDevice.id)) {
                                            handleCopy('', activeDevice.id);
                                        } else {
                                            alert('У вас нет активных устройств с ключами. Сначала создайте подписку.');
                                        }
                                    } else if (action.type === 'trigger_add') {
                                        // Открываем Happ с зашифрованной ссылкой
                                        await openHappWithSubscription();
                                    } else if (action.url) {
                                        window.open(action.url, '_blank');
                                    }
                                }}
                                className={`py-2 px-3 rounded-lg text-xs font-semibold text-center transition-colors ${
                                    action.primary 
                                    ? 'bg-blue-600 text-white hover:bg-blue-500' 
                                    : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                                }`}
                                >
                                {action.label}
                                </button>
                            ))}
                            </div>
                        )}
                    </div>
                ))}
            </div>

            <Button className="mt-4" variant="secondary" onClick={() => setView('home')}>
                На главную
            </Button>
        </div>
      )}
    </div>
  );

  const DevicesView = () => {
    const activeDevice = devices.find(d => !d.is_expired && (d.days_left !== undefined && d.days_left > 0 || d.hours_left !== undefined && d.hours_left > 0)) || devices[0] || null;
    const isExpired = activeDevice ? activeDevice.is_expired === true : true;
    
    const getTimeLeftText = () => {
      if (!activeDevice) return null;
      if (isExpired) return null;
      if (activeDevice.days_left === undefined || activeDevice.days_left === null) return null;
      if (activeDevice.days_left > 0) {
        const date = new Date(new Date().getTime() + activeDevice.days_left * 24 * 60 * 60 * 1000);
        return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });
      }
      if (activeDevice.hours_left && activeDevice.hours_left > 0) {
        const date = new Date(new Date().getTime() + activeDevice.hours_left * 60 * 60 * 1000);
        return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });
      }
      return null;
    };
    
    const timeLeftText = getTimeLeftText();
    const deviceName = activeDevice ? (activeDevice.is_trial ? 'Пробная подписка' : 'Подписка VPN') : 'Нет подписки';
    const deviceStatus = activeDevice && !isExpired;
    
    return (
      <div className="pb-24">
        <div className="px-4 space-y-6">
          {/* Current Subscription */}
          <div className="bg-white/5 rounded-3xl p-6 border border-white/10">
            <div className="flex items-center justify-between mb-4">
              <div>
                <div className="text-lg font-semibold text-white mb-1">{deviceName}</div>
                <div className="flex items-center gap-2">
                  <div className={`w-2 h-2 rounded-full ${deviceStatus ? 'bg-emerald-400' : 'bg-red-400'}`}></div>
                  <span className="text-sm text-gray-400">{deviceStatus ? 'Активна' : 'Неактивна'}</span>
                </div>
              </div>
              {timeLeftText && (
                <div className="text-right">
                  <div className="text-xs text-gray-500 mb-1">До</div>
                  <div className="text-sm font-medium text-white">{timeLeftText}</div>
                </div>
              )}
            </div>
            
            <button
              onClick={() => { 
                if (activeDevice && !isExpired) {
                  setActivePlatform(activeDevice.type);
                  setView('instruction_view');
                } else if (activeDevice) {
                  setExtendingDevice(activeDevice);
                  setExtendPlan(null);
                  setView('extend_subscription');
                } else {
                  setWizardStep(1);
                  setWizardPlan(null);
                  setView('wizard');
                }
              }}
              className="w-full bg-blue-500 hover:bg-blue-600 text-white font-semibold py-4 rounded-2xl transition-colors"
            >
              {isExpired ? 'Продлить подписку' : 'Настроить устройство'}
            </button>
          </div>

          {/* All Devices */}
          {devices.length > 0 && (
            <div className="space-y-3">
              <div className="text-sm text-gray-400 px-1">Все устройства ({devices.length})</div>
              {devices.map((device) => (
                <div 
                  key={device.id} 
                  className="bg-white/5 rounded-2xl p-4 border border-white/10 hover:bg-white/10 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="w-12 h-12 rounded-xl bg-white/10 flex items-center justify-center">
                        {device.type === 'ios' || device.type === 'android' ? (
                          <Smartphone size={20} className="text-white" />
                        ) : (
                          <Monitor size={20} className="text-white" />
                        )}
                      </div>
                      <div>
                        <div className="text-white font-semibold text-sm mb-1">
                          {device.is_trial ? 'Пробная' : 'VPN'} #{device.id}
                        </div>
                        <div className="text-xs text-gray-400">
                          {device.is_expired ? 'Истекла' : 
                           device.days_left !== undefined && device.days_left > 0 ? `${device.days_left} дней` :
                           device.hours_left !== undefined && device.hours_left > 0 ? `${device.hours_left} часов` : 'Активна'}
                        </div>
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <button 
                        onClick={() => openEditModal(device)}
                        className="p-2 rounded-xl bg-white/5 hover:bg-white/10 text-gray-400 hover:text-white transition-colors"
                      >
                        <Edit2 size={16} />
                      </button>
                      <button 
                        onClick={() => openDeleteModal(device)}
                        className="p-2 rounded-xl bg-white/5 hover:bg-white/10 text-gray-400 hover:text-red-400 transition-colors"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {devices.length === 0 && (
            <div className="text-center py-12">
              <div className="text-gray-500 text-sm mb-4">Нет подключенных устройств</div>
              <button
                onClick={() => { setWizardStep(1); setWizardPlan(null); setView('wizard'); }}
                className="bg-blue-500 hover:bg-blue-600 text-white font-semibold py-3 px-6 rounded-2xl transition-colors"
              >
                Подключить устройство
              </button>
            </div>
          )}
        </div>
      </div>
    );
  };

  // View для продления подписки - выбор тарифа
  const ExtendSubscriptionView = () => {
    const plansForExtend = vpnPlans.filter(p => !p.isTrial); // Без триала
    
    return (
      <div className="pb-24">
        <Header 
          title="Продление подписки" 
          onBack={() => {
            setExtendingDevice(null);
            setExtendPlan(null);
            setView('devices');
          }} 
        />
        
        <div className="px-4 space-y-6">
          {extendingDevice && (
            <div className="bg-white/5 rounded-2xl p-4 border border-white/10">
              <div className="text-gray-400 text-sm mb-1">Продление ключа</div>
              <div className="text-white font-semibold">
                {extendingDevice.is_trial ? 'Пробная подписка' : 'Подписка VPN'} | #{extendingDevice.id}
              </div>
            </div>
          )}
          
          <div className="space-y-3">
            <div className="text-sm text-gray-400 px-1">Выберите период продления</div>
            {plansForExtend.map(plan => (
              <button
                key={plan.id}
                onClick={() => setExtendPlan(plan)}
                className={`w-full p-4 rounded-2xl text-left transition-colors border ${
                  extendPlan?.id === plan.id
                    ? 'bg-blue-500/20 border-blue-500'
                    : 'bg-white/5 border-white/10 hover:bg-white/10'
                }`}
              >
                <div className="flex justify-between items-center">
                  <div>
                    <div className={`font-semibold text-lg ${extendPlan?.id === plan.id ? 'text-blue-400' : 'text-white'}`}>
                      {plan.duration}
                    </div>
                    <div className="text-gray-400 text-sm">{plan.days} дней</div>
                  </div>
                  <div className={`text-xl font-bold ${extendPlan?.id === plan.id ? 'text-blue-400' : 'text-white'}`}>
                    {plan.price} ₽
                  </div>
                </div>
              </button>
            ))}
          </div>
          
          <Button 
            disabled={!extendPlan || !extendingDevice}
            onClick={() => {
              if (extendPlan && extendingDevice) {
                extendSubscription(extendingDevice, extendPlan);
              }
            }}
          >
            Продлить за {extendPlan?.price || 0} ₽
          </Button>
        </div>
      </div>
    );
  };

  const TopUpView = () => (
    <div className="pb-24">
      <Header 
        title={topupStep === 1 ? "Пополнение баланса" : "Способ оплаты"} 
        onBack={() => {
          if (topupStep === 2) setTopupStep(1);
          else setView('home');
        }} 
      />
      
      {topupStep === 1 && (
        <div className="px-4 space-y-6">
          <div className="bg-white/5 rounded-3xl p-6 border border-white/10">
            <div className="text-center mb-6">
              <div className="text-sm text-gray-400 mb-3">Сумма пополнения</div>
              <div className="text-6xl font-bold text-white mb-2">
                {topupAmount > 0 ? topupAmount : '0'}<span className="text-4xl text-gray-500 ml-1">₽</span>
              </div>
              <input
                type="number"
                value={topupAmount || ''}
                onChange={(e) => {
                  const val = parseInt(e.target.value) || 0;
                  if (val >= 0 && val <= 100000) setTopupAmount(val);
                }}
                placeholder="Введите сумму"
                className="w-full bg-white/5 border border-white/10 rounded-2xl px-4 py-3 text-white text-center text-lg font-semibold focus:border-blue-500 focus:outline-none mt-4"
              />
            </div>

            <div className="grid grid-cols-3 gap-2">
              {PRESET_AMOUNTS.map(amount => (
                <button
                  key={amount}
                  onClick={() => setTopupAmount(amount)}
                  className={`py-3 rounded-xl text-sm font-semibold transition-colors ${
                    topupAmount === amount 
                    ? 'bg-blue-500 text-white' 
                    : 'bg-white/5 text-gray-300 border border-white/10 hover:bg-white/10'
                  }`}
                >
                  {amount}₽
                </button>
              ))}
            </div>
          </div>
          
          <Button 
            disabled={!topupAmount || topupAmount < 50 || topupAmount > 100000}
            onClick={() => {
              if (topupAmount < 50) {
                alert('Минимальная сумма пополнения: 50₽');
                return;
              }
              if (topupAmount > 100000) {
                alert('Максимальная сумма пополнения: 100,000₽');
                return;
              }
              setTopupStep(2);
            }}
          >
            Продолжить
          </Button>
        </div>
      )}

      {topupStep === 2 && (
        <div className="px-4 space-y-6">
          <div className="bg-white/5 rounded-3xl p-6 border border-white/10">
            <div className="space-y-3 mb-6">
              <div className="flex justify-between items-center text-sm">
                <span className="text-gray-400">Сумма:</span>
                <span className="text-white font-semibold">{topupAmount} ₽</span>
              </div>
              {selectedMethod && (
                <div className="flex justify-between items-center text-sm">
                  <span className="text-gray-400">Комиссия ({
                    (() => {
                      const method = paymentMethods.find(m => m.id === selectedMethod);
                      if (method?.variants && selectedVariant) {
                        return method.variants.find(v => v.id === selectedVariant)?.feePercent;
                      }
                      return method?.feePercent;
                    })()
                  }%):</span>
                  <span className="text-gray-300">+{
                    (() => {
                      const total = getPaymentTotal();
                      return (total - topupAmount).toFixed(1).replace(/\.0$/, '');
                    })()
                  } ₽</span>
                </div>
              )}
              <div className="flex justify-between items-center pt-3 border-t border-white/10 font-bold text-lg">
                <span className="text-white">Итого:</span>
                <span className="text-blue-400">{getPaymentTotal()} ₽</span>
              </div>
            </div>
          </div>

          <div className="space-y-3">
            <div className="text-sm text-gray-400 px-1">Выберите способ оплаты</div>
            {paymentMethods.map(method => (
              <div key={method.id}>
                <button
                  onClick={() => { 
                    setSelectedMethod(method.id);
                    if (method.variants && method.variants.length > 0) {
                      setSelectedVariant(method.variants[0].id);
                    } else {
                      setSelectedVariant(null);
                    }
                  }}
                  className={`w-full p-4 rounded-2xl flex items-center justify-between transition-colors border ${
                    selectedMethod === method.id
                    ? 'bg-blue-500/20 border-blue-500 text-white'
                    : 'bg-white/5 border-white/10 text-gray-300 hover:bg-white/10'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <span className="text-2xl">{method.icon}</span>
                    <div className="text-left">
                      <div className="font-semibold">{method.name}</div>
                      <div className="text-xs text-gray-400 mt-0.5">
                        {method.variants ? 'Выберите провайдера' : (method.feePercent === 0 ? 'Без комиссии' : `Комиссия ${method.feePercent}%`)}
                      </div>
                    </div>
                  </div>
                  {selectedMethod === method.id && <CheckCircle size={20} className="text-blue-400" />}
                </button>
                
                {selectedMethod === method.id && method.variants && (
                  <div className="mt-2">
                    <select 
                      value={selectedVariant || ''}
                      onChange={(e) => setSelectedVariant(e.target.value)}
                      className="w-full bg-white/5 border border-white/10 rounded-xl p-3 text-sm text-white focus:border-blue-500 outline-none"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {method.variants.map(v => (
                        <option key={v.id} value={v.id} className="bg-black">
                          {v.name}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </div>
            ))}
          </div>

          <Button 
            disabled={!selectedMethod}
            onClick={async () => {
              if (!userId) {
                alert('Пользователь не загружен, попробуйте позже');
                return;
              }
              try {
                const total = getPaymentTotal();
                const method = paymentMethods.find(m => m.id === selectedMethod);
                let methodKey = selectedMethod || 'platega_sbp';
                
                if (method?.variants && selectedVariant) {
                  methodKey = selectedVariant;
                } else if (method?.variants && method.variants.length > 0) {
                  // Если метод имеет варианты, но не выбран, используем первый
                  methodKey = method.variants[0].id;
                }
                
                const res = await miniApiFetch('/payment/create', {
                  method: 'POST',
                  body: JSON.stringify({
                    user_id: userId,
                    amount: total,
                    method: methodKey
                  }),
                });

                const payUrl = res.confirmation_url || res.payment_url;
                if (payUrl) {
                  setPaymentUrl(payUrl);
                  try {
                    if (window.Telegram?.WebApp?.openLink) {
                      window.Telegram.WebApp.openLink(payUrl);
                    } else {
                      window.open(payUrl, '_blank');
                    }
                  } catch {
                    window.open(payUrl, '_blank');
                  }
                }
                setView('wait_payment');
              } catch (e) {
                console.error(e);
                alert('Не удалось создать платёж, попробуйте позже');
              }
            }}
          >
            Оплатить {getPaymentTotal()} ₽
          </Button>
        </div>
      )}
    </div>
  );

  const BuyDeviceView = () => (
    <div className="min-h-full flex flex-col animate-in slide-in-from-right duration-300">
      <Header title="Новое подключение" onBack={() => setView('devices')} />
      
      <div className="flex-1 flex flex-col">
         <div className="text-center py-10 opacity-70">
              <p className="mb-4">Для подключения VPN мы рекомендуем использовать мастер настройки.</p>
              <Button onClick={() => { setWizardStep(1); setWizardPlan(null); setView('wizard'); }}>
                  Открыть мастер подключения
              </Button>
         </div>
      </div>
    </div>
  );
  
  const PaymentWaitView = () => {
    const [checking, setChecking] = useState(false);
    const [pollingActive, setPollingActive] = useState(false);
    const checkingRef = useRef(false);
    
    const doPaymentCheck = async () => {
      if (checkingRef.current) return;
      checkingRef.current = true;
      setChecking(true);
      
      try {
        const oldBalance = balance;
        const result = await refreshUserData();
        const newBalance = result?.balance ?? oldBalance;
        
        if (newBalance > oldBalance) {
          const depositAmount = newBalance - oldBalance;
          addHistoryItem('deposit', 'Пополнение баланса', depositAmount);
          setPollingActive(false);
          
          // Если была отложенная покупка - выполняем её
          if (pendingAction) {
            const action = pendingAction;
            const payload = action.payload;
            
            // Проверяем, достаточно ли средств теперь
            if (newBalance >= payload.price) {
              try {
                const currentUserId = await ensureUserId();
                if (currentUserId) {
                  // Если это продление существующей подписки
                  if (action.type === 'extend' && payload.device && payload.plan) {
                    const res = await miniApiFetch('/subscription/extend', {
                      method: 'POST',
                      body: JSON.stringify({
                        user_id: currentUserId,
                        key_id: payload.device.id,
                        days: payload.plan.days,
                        price: payload.price,
                      }),
                    });
                    
                    if (res && res.success) {
                      addHistoryItem('extend', `Продление подписки (${payload.plan.duration})`, -payload.price);
                      setPendingAction(null);
                      setPaymentUrl(null);
                      setExtendingDevice(null);
                      setExtendPlan(null);
                      await refreshAll();
                      setView('devices');
                      return;
                    }
                  } else {
                    // Создаём новую подписку
                    const res = await miniApiFetch('/subscription/create', {
                      method: 'POST',
                      body: JSON.stringify({
                        user_id: currentUserId,
                        days: payload.wizardPlan?.days || 30,
                        type: 'vpn',
                        price: payload.price,
                      }),
                    });
                    
                    if (res && res.success) {
                      addHistoryItem('buy_dev', `Подключение: ${payload.name}`, -payload.price);
                      setPendingAction(null);
                      setPaymentUrl(null);
                      setActivePlatform(wizardPlatform);
                      await refreshAll();
                      setWizardStep(4);
                      setView('wizard');
                      return;
                    }
                  }
                }
              } catch (e) {
                console.error('Failed to process pending action after payment', e);
              }
            }
            
            // Если не удалось выполнить действие - просто переходим к инструкциям
            setPendingAction(null);
            setPaymentUrl(null);
            setActivePlatform(wizardPlatform);
            await refreshDevices();
            setView('instruction_view');
          } else {
            // Просто пополнение баланса - на главную
            setPaymentUrl(null);
            await refreshAll();
            setView('home');
          }
        }
      } finally {
        checkingRef.current = false;
        setChecking(false);
      }
    };
    
    // Автоматическая проверка баланса каждые 3 секунды
    useEffect(() => {
      if (!pollingActive) return;
      
      const interval = setInterval(() => {
        doPaymentCheck();
      }, 3000);
      
      return () => clearInterval(interval);
    }, [pollingActive]);
    
    // Запускаем polling при открытии страницы
    useEffect(() => {
      setPollingActive(true);
      return () => setPollingActive(false);
    }, []);
    
    return (
      <div className="flex flex-col items-center justify-center min-h-[80vh] animate-in zoom-in duration-300 text-center px-4">
        <div className="w-24 h-24 rounded-full bg-gradient-to-br from-blue-600/20 to-purple-600/20 flex items-center justify-center mb-8 relative">
          <div className="absolute inset-0 rounded-full border-4 border-blue-500/50 border-t-blue-500 animate-spin"></div>
          <div className="absolute inset-2 rounded-full border-4 border-purple-500/30 border-b-purple-500 animate-spin" style={{ animationDirection: 'reverse', animationDuration: '1.5s' }}></div>
          <CreditCard className="text-blue-400" size={32} />
        </div>
        <h2 className="text-2xl font-bold text-white mb-3">Обрабатываем платёж...</h2>
        <p className="text-slate-400 mb-2 max-w-xs">
          {pendingAction ? 'VPN подключится автоматически после оплаты' : 'Завершите оплату в открывшемся окне'}
        </p>
        <p className="text-slate-500 text-xs mb-8">
          Страница обновится автоматически
        </p>
        {paymentUrl && (
          <Button onClick={() => {
            try {
              if (window.Telegram?.WebApp?.openLink) {
                window.Telegram.WebApp.openLink(paymentUrl);
              } else {
                window.open(paymentUrl, '_blank');
              }
            } catch {
              window.open(paymentUrl, '_blank');
            }
          }}>
            <ExternalLink size={18} className="mr-2" />
            Перейти к оплате
          </Button>
        )}
        <div className="mt-4 text-xs text-slate-500">
          {checking ? 'Проверка оплаты...' : 'Автоматическая проверка каждые 3 сек.'}
        </div>
        <button 
          onClick={() => window.open(SUPPORT_URL, '_blank')} 
          className="mt-4 text-blue-500 text-sm hover:text-blue-300 font-medium flex items-center gap-2"
        >
          <MessageCircle size={16} /> Связаться с поддержкой
        </button>
        <button onClick={() => { setPaymentUrl(null); setPendingAction(null); setPollingActive(false); setView('home'); }} className="mt-3 text-slate-500 text-sm hover:text-slate-300">
          Отменить
        </button>
      </div>
    );
  };

  const PaymentSuccessView = () => (
    <div className="flex flex-col items-center justify-center min-h-[80vh] animate-in zoom-in duration-500 text-center px-4">
      <div className="w-24 h-24 rounded-full bg-green-500/20 flex items-center justify-center mb-6 text-green-500">
        <CheckCircle size={48} />
      </div>
      <h2 className="text-3xl font-bold text-white mb-2">Успешно!</h2>
      <p className="text-slate-400 mb-8">Баланс пополнен на {topupAmount} ₽.</p>
      <Button onClick={async () => {
        setTopupAmount(0);
        setSelectedMethod(null);
        setTopupStep(1);
        // Обновляем данные пользователя с сервера
        await refreshUserData();
        setView('home');
      }}>
        Вернуться в кабинет
      </Button>
    </div>
  );

  const InstructionView = () => {
    const currentInstr = INSTRUCTIONS[activePlatform] || INSTRUCTIONS['android'];

    return (
      <div className="pb-24">
        <Header title="Настройка" onBack={() => setView('devices')} />

        <div className="px-4 space-y-5">
          {/* Platform Selector */}
          <div className="bg-white/5 rounded-3xl p-4 border border-white/10">
            <label className="text-xs text-gray-400 mb-2 block">Платформа</label>
            <div className="relative">
              <select 
                value={activePlatform}
                onChange={(e) => setActivePlatform(e.target.value as PlatformId)}
                className="w-full appearance-none bg-white/5 border border-white/10 text-white py-3 pl-4 pr-10 rounded-xl focus:outline-none focus:border-blue-500 transition-colors"
              >
                {Object.entries(INSTRUCTIONS).map(([key, data]) => (
                  <option key={key} value={key}>{data.title}</option>
                ))}
              </select>
              <div className="absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none text-gray-400">
                <ChevronDown size={18} />
              </div>
            </div>
          </div>

          {/* Status Card */}
          <div className="bg-blue-500/10 border border-blue-500/20 rounded-3xl p-4 flex gap-3">
            <div className="text-blue-400 mt-0.5"><CheckCircle size={20} /></div>
            <div>
              <div className="font-semibold text-blue-400 text-sm mb-1">Устройство готово</div>
              <div className="text-blue-400/70 text-xs">Следуйте инструкции ниже для подключения</div>
            </div>
          </div>

          {/* Instructions Steps */}
          <div className="space-y-4">
            {currentInstr.steps.map((step, idx) => (
              <div key={idx} className="bg-white/5 rounded-3xl p-5 border border-white/10">
                <div className="flex items-start gap-3 mb-3">
                  <div className="w-8 h-8 rounded-full bg-blue-500/20 border border-blue-500/30 flex items-center justify-center text-blue-400 font-bold text-sm flex-shrink-0">
                    {idx + 1}
                  </div>
                  <div className="flex-1">
                    <h3 className="font-semibold text-white text-base mb-2">{step.title}</h3>
                    <p className="text-gray-400 text-sm leading-relaxed">{step.desc}</p>
                  </div>
                </div>
                
                {step.actions && (
                  <div className="flex flex-col gap-2 mt-4">
                    {step.actions.map((action, aIdx) => (
                      <button
                        key={aIdx}
                        onClick={async () => {
                          if (action.type === 'copy_key') {
                            // Получаем ключ устройства для текущей платформы
                            const deviceForPlatform = devices.find(d => d.type === activePlatform);
                            if (deviceForPlatform && deviceKeys.has(deviceForPlatform.id)) {
                              handleCopy('', deviceForPlatform.id);
                            } else {
                              alert('У вас нет активных устройств с ключами для этой платформы. Сначала создайте подписку.');
                            }
                          } else if (action.type === 'nav_android') {
                            setActivePlatform('android');
                          } else if (action.type === 'nav_ios') {
                            setActivePlatform('ios');
                          } else if (action.type === 'trigger_add') {
                            // Открываем Happ с зашифрованной ссылкой
                            await openHappWithSubscription();
                          } else if (action.url) {
                            window.open(action.url, '_blank');
                          }
                        }}
                        className={`py-3 px-4 rounded-xl text-sm font-semibold text-center transition-colors ${
                          action.primary 
                          ? 'bg-blue-500 hover:bg-blue-600 text-white' 
                          : 'bg-white/5 hover:bg-white/10 text-gray-300 border border-white/10'
                        }`}
                      >
                        {action.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  };

  const HistoryView = () => (
    <div className="pb-24">
      <Header title="История транзакций" onBack={() => setView('home')} />
      <div className="px-4 space-y-3">
        {history.length === 0 ? (
          <div className="text-center py-12">
            <div className="text-gray-500 text-sm">Нет транзакций</div>
          </div>
        ) : (
          history.map(item => (
            <div key={item.id} className="bg-white/5 p-4 rounded-2xl border border-white/10 flex justify-between items-center">
              <div className="flex items-center gap-3">
                <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${
                  item.amount > 0 ? 'bg-emerald-500/20 text-emerald-400' : 
                  (item.amount < 0 ? 'bg-red-500/20 text-red-400' : 'bg-white/10 text-gray-400')
                }`}>
                  {item.amount > 0 ? <Download size={18} /> : (item.amount < 0 ? <LogOut size={18} /> : <Clock size={18} />)}
                </div>
                <div>
                  <div className="font-semibold text-white text-sm">{item.title}</div>
                  <div className="text-xs text-gray-400">{item.date}</div>
                </div>
              </div>
              <div className={`font-bold ${
                item.amount > 0 ? 'text-emerald-400' : 
                (item.amount < 0 ? 'text-white' : 'text-gray-400')
              }`}>
                {item.amount > 0 ? '+' : ''}{item.amount !== 0 ? formatMoney(item.amount) : '0 ₽'}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );

  const ReferralDetailView = () => {
    if (!selectedReferral) return null;
    return (
     <div className="pb-24">
        <Header title={selectedReferral.name} onBack={() => setView('referral')} />
        
        <div className="px-4 space-y-6">
          <div className="grid grid-cols-2 gap-3">
             <div className="bg-white/5 p-4 rounded-2xl border border-white/10">
                <div className="text-xs text-gray-400 mb-1">Потратил всего</div>
                <div className="text-xl font-bold text-white">{formatMoney(selectedReferral.spent)}</div>
             </div>
             <div className="bg-white/5 p-4 rounded-2xl border border-white/10">
                <div className="text-xs text-gray-400 mb-1">Вы получили</div>
                <div className="text-xl font-bold text-emerald-400">+{formatMoney(selectedReferral.myProfit)}</div>
             </div>
          </div>

          <div className="space-y-3">
            <div className="text-sm text-gray-400 px-1">История операций</div>
            {selectedReferral.history.length > 0 ? selectedReferral.history.map((h, idx) => (
              <div key={idx} className="bg-white/5 p-4 rounded-2xl border border-white/10 flex justify-between items-center">
                 <div>
                    <div className="font-semibold text-white text-sm">{h.title}</div>
                    <div className="text-xs text-gray-400 mt-1">{h.date}</div>
                 </div>
                 <div className="text-right">
                    <div className="text-white font-semibold">{formatMoney(h.amount)}</div>
                    <div className="text-xs text-emerald-400 font-bold mt-1">+{formatMoney(h.income)}</div>
                 </div>
              </div>
           )) : (
              <div className="text-center py-12 bg-white/5 rounded-2xl border border-white/10">
                <div className="text-gray-500 text-sm">Нет операций</div>
              </div>
           )}
          </div>
        </div>
     </div>
    );
  };

  const ReferralView = () => (
    <div className="pb-24">
      <Header title="Реферальная программа" onBack={() => setView('home')} />
      
      <div className="px-4 space-y-6">
        <div className="bg-gradient-to-r from-emerald-500/10 to-blue-500/10 rounded-3xl p-6 border border-emerald-500/20 text-center">
          <div className="text-gray-400 text-sm mb-2">Доступно для вывода</div>
          <div className="text-5xl font-bold text-emerald-400 mb-4">{formatMoney(referrals.partnerBalance)}</div>
          
          {referrals.partnerBalance > 0 ? (
            <button 
              onClick={openWithdrawModal}
              className="bg-emerald-500 hover:bg-emerald-600 text-white px-6 py-3 rounded-2xl font-semibold transition-colors"
            >
              Вывести средства
            </button>
          ) : (
            <div className="text-gray-500 text-sm">Пригласите друзей, чтобы заработать</div>
          )}

          <div className="grid grid-cols-2 gap-4 mt-6 pt-6 border-t border-white/10">
            <div>
              <div className="text-2xl font-bold text-white">{referrals.count}</div>
              <div className="text-xs text-gray-400 mt-1">Приглашено</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-emerald-400">+{formatMoney(referrals.earned)}</div>
              <div className="text-xs text-gray-400 mt-1">Заработано</div>
            </div>
          </div>
        </div>

        <div className="bg-white/5 rounded-2xl p-4 border border-white/10">
          <label className="text-xs text-gray-400 mb-2 block">Ваша реферальная ссылка</label>
          <div className="flex gap-2">
            <div className="bg-white/5 flex-1 p-3 rounded-xl text-gray-300 font-mono text-xs truncate border border-white/10">
              {telegramId ? `https://t.me/${BOT_USERNAME_MINI}?start=ref${telegramId}` : 'Загрузка...'}
            </div>
            <button
              onClick={() => {
                if (telegramId) {
                  handleCopy(`https://t.me/${BOT_USERNAME_MINI}?start=ref${telegramId}`);
                }
              }}
              className="bg-blue-500 hover:bg-blue-600 px-4 rounded-xl text-white transition-colors"
            >
              <Copy size={18} />
            </button>
          </div>
          <div className="text-xs text-gray-500 mt-3">
            За каждого приглашённого друга вы получите 50₽ за его первую покупку
          </div>
        </div>
        
        <div className="space-y-3">
          <div className="text-sm text-gray-400 px-1">Приглашённые пользователи</div>
          {referralList.length === 0 ? (
            <div className="text-center py-12 bg-white/5 rounded-2xl border border-white/10">
              <UserPlus size={32} className="text-gray-600 mx-auto mb-3" />
              <p className="text-gray-500 text-sm">У вас пока нет рефералов</p>
              <p className="text-gray-600 text-xs mt-1">Поделитесь ссылкой выше</p>
            </div>
          ) : (
            referralList.map(user => (
              <button 
                 key={user.id} 
                 onClick={() => { setSelectedReferral(user); setView('referral_detail'); }}
                 className="w-full bg-white/5 border border-white/10 p-4 rounded-2xl flex justify-between items-center hover:bg-white/10 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-white/10 flex items-center justify-center text-gray-400">
                    <User size={18} />
                  </div>
                  <div className="text-left">
                    <div className="text-sm font-semibold text-white">{user.name}</div>
                    <div className="text-xs text-gray-400">{user.date}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                   <div className="text-right">
                     <div className="text-xs text-gray-400">Доход</div>
                     <div className="text-sm font-bold text-emerald-400">+{formatMoney(user.myProfit)}</div>
                   </div>
                   <ChevronRight size={18} className="text-gray-400" />
                </div>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );

  const PromoView = () => {
    const [code, setCode] = useState('');
    return (
      <div className="pb-24">
        <Header title="Промокод" onBack={() => setView('home')} />
        <div className="px-4 space-y-6">
          <div className="text-center py-8">
            <div className="w-16 h-16 bg-purple-500/20 rounded-full flex items-center justify-center text-purple-400 mx-auto mb-4">
              <Gift size={32} />
            </div>
            <h2 className="text-xl font-bold text-white mb-2">Активация промокода</h2>
            <p className="text-gray-400 text-sm">
              Введите промокод для получения бонуса
            </p>
          </div>
          <input 
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            placeholder="PROMO2025"
            className="w-full bg-white/5 border border-white/10 rounded-2xl p-4 text-center text-xl font-mono text-white tracking-widest uppercase focus:border-purple-500 focus:outline-none placeholder:text-gray-600"
          />
          <Button 
            disabled={!code} 
            onClick={async () => {
              if (!userId) {
                alert('Пользователь не загружен, попробуйте позже');
                return;
              }
              try {
                const res = await miniApiFetch('/promocode/apply', {
                  method: 'POST',
                  body: JSON.stringify({ user_id: userId, code }),
                });
                if (res.success) {
                  alert(res.message || 'Промокод успешно применён');
                  if (telegramId) {
                    const data = await miniApiFetch(`/user/info?telegram_id=${telegramId}`);
                    setBalance(data.balance ?? balance);
                    setReferrals({
                      count: data.referrals_count ?? referrals.count,
                      earned: data.referral_earned ?? referrals.earned,
                      partnerBalance: data.partner_balance ?? referrals.partnerBalance,
                    });
                    if (data.last_card_withdrawal) {
                      setLastCardWithdrawal(data.last_card_withdrawal);
                    }
                  }
                } else {
                  alert(res.error || 'Промокод не найден');
                }
              } catch (e) {
                console.error(e);
                alert('Ошибка применения промокода');
              } finally {
                setCode('');
              }
            }}
          >
            Активировать
          </Button>
        </div>
      </div>
    );
  };

  // Страница "Доступ ограничен"
  if (isBanned) {
    return (
      <div className="max-w-md mx-auto bg-black min-h-screen relative text-white font-sans selection:bg-blue-500/30">
        <div className="p-4 min-h-screen flex flex-col items-center justify-center">
          <div className="text-center px-4 animate-in fade-in duration-500">
            {/* Иконка */}
            <div className="w-24 h-24 mx-auto mb-6 rounded-full bg-red-500/10 flex items-center justify-center">
              <svg className="w-12 h-12 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
              </svg>
            </div>
            
            {/* Заголовок */}
            <h1 className="text-2xl font-bold text-white mb-3">Доступ ограничен</h1>
            
            {/* Описание */}
            <p className="text-slate-400 mb-6 leading-relaxed">
              Ваш аккаунт заблокирован за нарушение правил сервиса.
            </p>
            
            {/* Причина */}
            {banReason && (
              <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 mb-6">
                <div className="text-sm text-red-400 font-medium mb-1">Причина:</div>
                <div className="text-white text-sm">{banReason}</div>
              </div>
            )}
            
            {/* Инфо блок */}
            <div className="bg-slate-800/50 rounded-xl p-4 mb-6 text-left">
              <h3 className="text-sm font-semibold text-white mb-2 flex items-center gap-2">
                <svg className="w-4 h-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Информация
              </h3>
              <ul className="text-sm text-slate-400 space-y-2">
                <li>• Администрация оставляет за собой право отказать в разблокировке</li>
                <li>• Подробности о причинах блокировки могут не предоставляться в целях защиты алгоритмов безопасности</li>
              </ul>
            </div>
            
            {/* Кнопка поддержки */}
            <a 
              href={SUPPORT_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-center gap-2 w-full py-3 bg-slate-800 hover:bg-slate-700 border border-slate-600 rounded-xl text-white font-medium transition-colors"
            >
              <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>
              </svg>
              Связаться с поддержкой
            </a>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-md mx-auto bg-black min-h-screen relative text-white font-sans selection:bg-blue-500/30">
      <div className="p-4 min-h-screen flex flex-col">
        {view === 'home' && <HomeView />}
        {view === 'wizard' && <WizardView />}
        {view === 'topup' && <TopUpView />}
        {view === 'wait_payment' && <PaymentWaitView />}
        {view === 'success_payment' && <PaymentSuccessView />}
        {view === 'devices' && <DevicesView />}
        {view === 'extend_subscription' && <ExtendSubscriptionView />}
        {view === 'buy_device' && <BuyDeviceView />}
        {view === 'instruction_view' && <InstructionView />}
        {view === 'history' && <HistoryView />}
        {view === 'referral' && <ReferralView />}
        {view === 'referral_detail' && <ReferralDetailView />}
        {view === 'promo' && <PromoView />}
      </div>

      {/* Bottom Navigation */}
      <div className="fixed bottom-0 left-0 right-0 max-w-md mx-auto bg-black border-t border-white/10 z-10">
        <div className="grid grid-cols-5 py-3">
          <button
            onClick={() => setView('home')}
            className={`flex flex-col items-center gap-1 py-1 transition-colors ${
              view === 'home' ? 'text-blue-400' : 'text-gray-500'
            }`}
          >
            <div className={`w-9 h-9 flex items-center justify-center rounded-xl transition-colors ${
              view === 'home' ? 'bg-blue-500/20' : ''
            }`}>
              <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
                <path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/>
              </svg>
            </div>
            <span className={`text-xs font-medium ${view === 'home' ? 'text-blue-400' : 'text-gray-500'}`}>Главная</span>
          </button>
          <button
            onClick={() => setView('devices')}
            className={`flex flex-col items-center gap-1 py-1 transition-colors ${
              view === 'devices' ? 'text-blue-400' : 'text-gray-500'
            }`}
          >
            <div className={`w-9 h-9 flex items-center justify-center rounded-xl transition-colors ${
              view === 'devices' ? 'bg-blue-500/20' : ''
            }`}>
              <Sparkles size={18} />
            </div>
            <span className={`text-xs font-medium ${view === 'devices' ? 'text-blue-400' : 'text-gray-500'}`}>Подписка</span>
          </button>
          <button
            onClick={() => { setTopupStep(1); setView('topup'); }}
            className={`flex flex-col items-center gap-1 py-1 transition-colors ${
              view === 'topup' ? 'text-blue-400' : 'text-gray-500'
            }`}
          >
            <div className={`w-9 h-9 flex items-center justify-center rounded-xl transition-colors ${
              view === 'topup' ? 'bg-blue-500/20' : ''
            }`}>
              <Wallet size={18} />
            </div>
            <span className={`text-xs font-medium ${view === 'topup' ? 'text-blue-400' : 'text-gray-500'}`}>Баланс</span>
          </button>
          <button
            onClick={() => setView('referral')}
            className={`flex flex-col items-center gap-1 py-1 transition-colors ${
              view === 'referral' || view === 'referral_detail' ? 'text-blue-400' : 'text-gray-500'
            }`}
          >
            <div className={`w-9 h-9 flex items-center justify-center rounded-xl transition-colors ${
              view === 'referral' || view === 'referral_detail' ? 'bg-blue-500/20' : ''
            }`}>
              <UserPlus size={18} />
            </div>
            <span className={`text-xs font-medium ${view === 'referral' || view === 'referral_detail' ? 'text-blue-400' : 'text-gray-500'}`}>Рефералы</span>
          </button>
          <button
            onClick={() => window.open(SUPPORT_URL, '_blank')}
            className="flex flex-col items-center gap-1 py-1 transition-colors text-gray-500 hover:text-blue-400"
          >
            <div className="w-9 h-9 flex items-center justify-center rounded-xl">
              <MessageCircle size={18} />
            </div>
            <span className="text-xs font-medium">Поддержка</span>
          </button>
        </div>
      </div>

      {/* Footer with Legal Links */}
      <div className="fixed bottom-20 left-0 right-0 max-w-md mx-auto bg-black border-t border-white/10 px-4 py-2 z-10">
        <div className="flex items-center justify-center gap-4 text-xs text-gray-500">
          <button
            onClick={() => {
              setDocContent({ title: 'Договор оферты', text: publicPages.offer });
              setDocModalOpen(true);
            }}
            className="hover:text-blue-400 transition-colors"
          >
            Договор оферты
          </button>
          <span className="text-gray-600">•</span>
          <button
            onClick={() => {
              setDocContent({ title: 'Политика конфиденциальности', text: publicPages.privacy });
              setDocModalOpen(true);
            }}
            className="hover:text-blue-400 transition-colors"
          >
            Политика конфиденциальности
          </button>
        </div>
      </div>
      
      {/* MODALS */}
      
      <Modal 
        title="Изменить имя" 
        isOpen={editModalOpen} 
        onClose={() => setEditModalOpen(false)}
      >
        <div className="space-y-4">
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            className="w-full bg-slate-800 border border-slate-600 rounded-xl p-3 text-white focus:border-blue-500 outline-none"
            placeholder="Название устройства"
            autoFocus
          />
          <Button onClick={saveDeviceName}>Сохранить</Button>
        </div>
      </Modal>

      <Modal 
        title="Удалить устройство" 
        isOpen={deleteModalOpen} 
        onClose={() => setDeleteModalOpen(false)}
      >
        <div className="space-y-4">
          <p className="text-slate-300">
            Вы уверены, что хотите удалить <b>{currentDevice?.name}</b>? Это действие нельзя отменить.
          </p>
          <div className="grid grid-cols-2 gap-3">
             <Button variant="secondary" onClick={() => setDeleteModalOpen(false)}>Отмена</Button>
             <Button variant="danger" onClick={confirmDeleteDevice}>Удалить</Button>
          </div>
        </div>
      </Modal>

      {/* Legal Docs Modal - New Feature */}
      <Modal
        title={docContent?.title || 'Документ'}
        isOpen={docModalOpen}
        onClose={() => setDocModalOpen(false)}
        fullHeight
      >
        <div className="pb-6">
            <MarkdownRenderer content={docContent?.text || ''} />
        </div>
      </Modal>

      {/* WITHDRAW MODAL */}
      <Modal
        title="Вывод средств"
        isOpen={withdrawModalOpen}
        onClose={() => setWithdrawModalOpen(false)}
      >
        {withdrawState.step === 1 && (
          <div className="space-y-4">
            <div className="text-sm text-slate-400">Доступно: <span className="text-green-500 font-bold">{referrals.partnerBalance.toFixed(2)} ₽</span></div>
            {referrals.partnerBalance < 200 && (
              <div className="p-3 bg-yellow-900/20 border border-yellow-500/30 rounded-xl text-yellow-400 text-sm">
                Минимальная сумма для вывода на карту или крипто — 200₽. На баланс можно вывести любую сумму.
              </div>
            )}
            <input
              type="number"
              placeholder="Сумма вывода"
              value={withdrawState.amount}
              onChange={(e) => setWithdrawState({ ...withdrawState, amount: e.target.value })}
              className="w-full bg-slate-800 border border-slate-600 rounded-xl p-3 text-white focus:border-blue-500 outline-none"
            />
            <Button onClick={handleWithdrawNext}>Далее</Button>
          </div>
        )}

        {withdrawState.step === 2 && (
          <div className="space-y-3">
            <div className="text-sm text-slate-400 mb-2">Выберите метод:</div>
            {WITHDRAW_METHODS.map(method => (
              <button
                key={method.id}
                onClick={() => setWithdrawState({ ...withdrawState, method: method.id })}
                disabled={Number(withdrawState.amount) < method.min && method.min > 0}
                className={`w-full p-4 rounded-xl flex items-center justify-between transition-all border ${
                  withdrawState.method === method.id
                  ? 'bg-blue-600/10 border-blue-600 text-white'
                  : 'bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-750 disabled:opacity-50 disabled:cursor-not-allowed'
                }`}
              >
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-slate-700 flex items-center justify-center text-slate-300">
                    {method.icon}
                  </div>
                  <div className="text-left">
                    <div className="font-medium">{method.name}</div>
                    {method.min > 0 && Number(withdrawState.amount) < method.min && (
                      <div className="text-xs text-red-400">Мин. сумма {method.min} ₽</div>
                    )}
                  </div>
                </div>
                {withdrawState.method === method.id && <CheckCircle size={20} className="text-blue-500" />}
              </button>
            ))}
            <div className="pt-4 flex gap-3">
               <Button variant="secondary" onClick={() => setWithdrawState({ ...withdrawState, step: 1 })}>Назад</Button>
               <Button onClick={handleWithdrawNext}>Подтвердить</Button>
            </div>
          </div>
        )}

        {withdrawState.step === 3 && (
          <div className="space-y-4">
            {withdrawState.method === 'balance' && (
              <p className="text-slate-300 text-center">
                Средства будут зачислены на ваш внутренний баланс моментально.
              </p>
            )}
            
            {withdrawState.method === 'card' && (
              <>
                <div className="text-sm text-slate-400 mb-2">Заполните реквизиты:</div>
                <input
                  type="tel"
                  placeholder="+7 9xx xxx xx xx"
                  value={withdrawState.phone}
                  onChange={(e) => setWithdrawState({ ...withdrawState, phone: e.target.value })}
                  className="w-full bg-slate-800 border border-slate-600 rounded-xl p-3 text-white mb-2 focus:border-blue-500 outline-none"
                />
                <input
                  type="text"
                  placeholder="Название банка (Сбер, Тинькофф...)"
                  value={withdrawState.bank}
                  onChange={(e) => setWithdrawState({ ...withdrawState, bank: e.target.value })}
                  className="w-full bg-slate-800 border border-slate-600 rounded-xl p-3 text-white focus:border-blue-500 outline-none"
                />
              </>
            )}

            {withdrawState.method === 'crypto' && (
              <>
                <div className="text-sm text-slate-400 mb-2">Реквизиты кошелька:</div>
                <input
                  type="text"
                  placeholder="Сеть (TRC-20, BEP-20...)"
                  value={withdrawState.cryptoNet}
                  onChange={(e) => setWithdrawState({ ...withdrawState, cryptoNet: e.target.value })}
                  className="w-full bg-slate-800 border border-slate-600 rounded-xl p-3 text-white mb-2 focus:border-blue-500 outline-none"
                />
                <input
                  type="text"
                  placeholder="Адрес кошелька"
                  value={withdrawState.cryptoAddr}
                  onChange={(e) => setWithdrawState({ ...withdrawState, cryptoAddr: e.target.value })}
                  className="w-full bg-slate-800 border border-slate-600 rounded-xl p-3 text-white focus:border-blue-500 outline-none font-mono text-sm"
                />
              </>
            )}

            <div className="pt-4 flex gap-3">
               <Button variant="secondary" onClick={() => setWithdrawState({ ...withdrawState, step: 2 })}>Назад</Button>
               <Button onClick={handleWithdrawNext}>Подтвердить</Button>
            </div>
          </div>
        )}

        {withdrawState.step === 4 && (
          <div className="text-center py-4">
            <div className="w-16 h-16 bg-green-500/10 rounded-full flex items-center justify-center text-green-500 mx-auto mb-4">
              <CheckCircle size={32} />
            </div>
            <h3 className="text-xl font-bold text-white mb-2">
              {withdrawState.method === 'balance' ? 'Готово!' : 'Заявка принята'}
            </h3>
            <p className="text-slate-400 text-sm mb-6">
              {withdrawState.method === 'balance' 
                ? 'Средства зачислены на ваш баланс.' 
                : 'Если нарушений нет, средства поступят в течение 3-х рабочих дней.'}
            </p>
            <Button onClick={() => setWithdrawModalOpen(false)}>Отлично</Button>
          </div>
        )}
      </Modal>

      {/* Онбординг для новых пользователей */}
      {showOnboarding && (
        <div className="fixed inset-0 z-[100] bg-slate-950 flex flex-col">
          {/* Progress dots */}
          <div className="flex justify-center gap-2 pt-6 pb-4">
            {[0, 1, 2, 3].map(i => (
              <div 
                key={i} 
                className={`w-2 h-2 rounded-full transition-all ${i === onboardingStep ? 'bg-blue-500 w-6' : 'bg-slate-700'}`}
              />
            ))}
          </div>
          
          {/* Content */}
          <div className="flex-1 flex flex-col items-center justify-center px-8 text-center">
            {onboardingStep === 0 && (
              <>
                <div className="w-24 h-24 bg-blue-600/20 rounded-full flex items-center justify-center mb-6">
                  <Shield className="text-blue-500" size={48} />
                </div>
                <h2 className="text-2xl font-bold text-white mb-4">Добро пожаловать!</h2>
                <p className="text-slate-400 leading-relaxed">
                  BLIN VPN — это современный и безопасный VPN-сервис. 
                  Мы поможем вам защитить ваше интернет-соединение.
                </p>
              </>
            )}
            
            {onboardingStep === 1 && (
              <>
                <div className="w-24 h-24 bg-green-600/20 rounded-full flex items-center justify-center mb-6">
                  <Gift className="text-green-500" size={48} />
                </div>
                <h2 className="text-2xl font-bold text-white mb-4">Бесплатный пробный период</h2>
                <p className="text-slate-400 leading-relaxed">
                  Попробуйте VPN абсолютно бесплатно! 
                  Активируйте 24-часовой пробный период и оцените качество сервиса.
                </p>
              </>
            )}
            
            {onboardingStep === 2 && (
              <>
                <div className="w-24 h-24 bg-purple-600/20 rounded-full flex items-center justify-center mb-6">
                  <UserPlus className="text-purple-500" size={48} />
                </div>
                <h2 className="text-2xl font-bold text-white mb-4">Реферальная программа</h2>
                <p className="text-slate-400 leading-relaxed">
                  Приглашайте друзей и получайте бонусы! 
                  За каждого приглашённого друга вы получите 50₽ за его первую покупку.
                </p>
              </>
            )}
            
            {onboardingStep === 3 && (
              <>
                <div className="w-24 h-24 bg-yellow-600/20 rounded-full flex items-center justify-center mb-6">
                  <Rocket className="text-yellow-500" size={48} />
                </div>
                <h2 className="text-2xl font-bold text-white mb-4">Начнём!</h2>
                <p className="text-slate-400 leading-relaxed">
                  Всё готово для начала работы. 
                  Нажмите "Подключить VPN" на главном экране, чтобы настроить защиту.
                </p>
              </>
            )}
          </div>
          
          {/* Buttons */}
          <div className="px-6 pb-8 space-y-3">
            {onboardingStep < 3 ? (
              <>
                <button 
                  onClick={() => setOnboardingStep(prev => prev + 1)}
                  className="w-full py-4 bg-blue-600 hover:bg-blue-500 text-white rounded-2xl font-bold transition-colors"
                >
                  Далее
                </button>
                <button 
                  onClick={() => {
                    setShowOnboarding(false);
                    localStorage.setItem(`onboarding_${telegramId}`, 'true');
                  }}
                  className="w-full py-3 text-slate-500 hover:text-slate-300 transition-colors"
                >
                  Пропустить
                </button>
              </>
            ) : (
              <button 
                onClick={() => {
                  setShowOnboarding(false);
                  localStorage.setItem(`onboarding_${telegramId}`, 'true');
                }}
                className="w-full py-4 bg-blue-600 hover:bg-blue-500 text-white rounded-2xl font-bold transition-colors"
              >
                Начать пользоваться
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}