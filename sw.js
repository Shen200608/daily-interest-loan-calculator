/*!
 * 利息计算器 · Service Worker
 * 缓存 shell + data/rates.json，实现离线可用。
 * 只在 https / localhost 下注册（见 js/main.js），file:// 下不会执行。
 */
'use strict';

// 修改任何 shell 资源（css/js/html）后必须把它加一，否则用户会一直用旧缓存。
// v2：修复复利按日计息 + 期间表「复利增益」列语义
// v3：期间表新增「单利对照／复利增益」独立列
// v4：「持有期间与计息口径」卡片移到「累计收益」表上方
const VERSION = 'v4';
const SHELL_CACHE = 'lixi-shell-' + VERSION;
const DATA_CACHE = 'lixi-data-' + VERSION;

/** 应用外壳（相对路径，兼容 GitHub Pages 子路径部署） */
const SHELL_ASSETS = [
  './',
  './index.html',
  './manifest.webmanifest',
  './icon.svg',
  './css/app.css?v=4',
  './js/finance.js?v=4',
  './js/rates.js?v=4',
  './js/ui.js?v=4',
  './js/main.js?v=4'
];

const DATA_ASSETS = ['./data/rates.json'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_ASSETS).catch(() => undefined))
      .then(() => caches.open(DATA_CACHE))
      .then((cache) => cache.addAll(DATA_ASSETS).catch(() => undefined))
      .then(() => self.skipWaiting())
      .catch(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== SHELL_CACHE && key !== DATA_CACHE)
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
      .catch(() => undefined)
  );
});

/** 网络优先（数据），失败回缓存 —— 保证利率数据尽量新，同时离线可用 */
function networkFirst(request, cacheName) {
  return fetch(request)
    .then((response) => {
      if (response && response.ok) {
        const copy = response.clone();
        caches.open(cacheName).then((cache) => cache.put(request, copy)).catch(() => undefined);
      }
      return response;
    })
    .catch(() =>
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return new Response(JSON.stringify({ meta: {}, groups: [], rates: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json; charset=utf-8' }
        });
      })
    );
}

/** 缓存优先（shell），后台更新 */
function cacheFirst(request, cacheName) {
  return caches.match(request).then((cached) => {
    if (cached) {
      fetch(request)
        .then((response) => {
          if (response && response.ok) {
            caches.open(cacheName).then((cache) => cache.put(request, response)).catch(() => undefined);
          }
        })
        .catch(() => undefined);
      return cached;
    }
    return fetch(request)
      .then((response) => {
        if (response && response.ok) {
          const copy = response.clone();
          caches.open(cacheName).then((cache) => cache.put(request, copy)).catch(() => undefined);
        }
        return response;
      })
      .catch(() => {
        // 导航请求离线兜底到 index.html
        if (request.mode === 'navigate') {
          return caches.match('./index.html').then((fallback) => fallback || caches.match('./'));
        }
        return new Response('', { status: 504, statusText: '离线且无缓存' });
      });
  });
}

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  let url;
  try {
    url = new URL(request.url);
  } catch (e) {
    return;
  }
  // 只处理同源请求；外部链接（数据来源）直接放行
  if (url.origin !== self.location.origin) return;

  if (url.pathname.endsWith('/data/rates.json') || url.pathname.endsWith('rates.json')) {
    event.respondWith(networkFirst(request, DATA_CACHE));
    return;
  }

  event.respondWith(cacheFirst(request, SHELL_CACHE));
});
