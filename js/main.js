/*!
 * 利息计算器 · 入口
 * 优先 fetch('data/rates.json')；失败（file:// 的 CORS 限制 / 离线 / JSON 损坏）时
 * 降级为内置最小数据集，并在页面顶部给出可关闭提示。
 */
(function () {
  'use strict';

  /** 内置最小数据集：字段结构与 data/rates.json 完全一致（SPEC 第 6 节） */
  var FALLBACK_RATES = {
    meta: {
      version: 1,
      updated: '2026-10-23',
      currency: 'CNY',
      lpr: { '1y': 3.0, '5y': 3.5 },
      judicial_cap_multiple: 4,
      disclaimer: '内置精简数据集（本地文件模式），仅供估算参考；完整数据请使用 http 服务或线上版本。',
      sources: [
        { title: '中国人民银行', url: 'https://www.pbc.gov.cn/', note: 'LPR 与政策利率' }
      ]
    },
    groups: [
      { id: 'official', title: '官方口径（央行/银行）', desc: 'LPR、公积金、房贷、信用卡等' },
      { id: 'customary', title: '民间叫法（分/厘/毫/日息万几）', desc: '月息几分几厘、日息万几等口语换算' },
      { id: 'deposit', title: '存款/理财', desc: '货币基金 7 日年化、储蓄国债等' },
      { id: 'loan', title: '贷款/房贷', desc: '房贷、消费贷、经营贷等' },
      { id: 'online_loan', title: '网贷/消费金融', desc: '主流平台日息区间，以实际合同为准' }
    ],
    rates: [
      {
        id: 'lpr-1y',
        group: 'official',
        name: 'LPR（1 年期）',
        aliases: ['LPR', '贷款市场报价利率', '一年期LPR', 'lpr 1y'],
        kind: 'annual_pct',
        value: 3.0,
        min: null,
        max: null,
        display: '3.00% 年化',
        asOf: '2026-10-23',
        note: '贷款市场报价利率 1 年期品种，是各类贷款的定价基准。',
        warning: null,
        source: 'https://www.pbc.gov.cn/'
      },
      {
        id: 'lpr-5y',
        group: 'official',
        name: 'LPR（5 年期以上）',
        aliases: ['LPR5年', '五年期LPR', '房贷基准', 'lpr 5y'],
        kind: 'annual_pct',
        value: 3.5,
        min: null,
        max: null,
        display: '3.50% 年化',
        asOf: '2026-10-23',
        note: '5 年期以上 LPR，房贷利率主要参考此品种。',
        warning: null,
        source: 'https://www.pbc.gov.cn/'
      },
      {
        id: 'housing-fund-5y',
        group: 'official',
        name: '公积金贷款（5 年以上）',
        aliases: ['公积金', '公积金贷款', '住房公积金', '公积金房贷'],
        kind: 'annual_pct',
        value: 2.6,
        min: null,
        max: null,
        display: '2.60% 年化',
        asOf: '2026-10-23',
        note: '首套个人住房公积金贷款 5 年期以上利率。',
        warning: null,
        source: 'https://www.mohurd.gov.cn/'
      },
      {
        id: 'mortgage-first',
        group: 'loan',
        name: '首套房贷（LPR 基准）',
        aliases: ['房贷', '首套房贷', '按揭', '住房贷款'],
        kind: 'annual_pct',
        value: 3.0,
        min: null,
        max: null,
        display: '3.00% 年化',
        asOf: '2026-10-23',
        note: '以 5 年期以上 LPR 为基准的商业性个人住房贷款利率参考。',
        warning: null,
        source: 'https://www.pbc.gov.cn/'
      },
      {
        id: 'consumer-loan',
        group: 'loan',
        name: '银行消费贷（参考）',
        aliases: ['消费贷', '信用贷', '个人消费贷款'],
        kind: 'annual_pct',
        value: 3.6,
        min: null,
        max: null,
        display: '3.60% 年化',
        asOf: '2026-10-23',
        note: '优质客户消费贷参考利率，实际以银行审批为准。',
        warning: null,
        source: 'https://www.pbc.gov.cn/'
      },
      {
        id: 'credit-card-cash',
        group: 'official',
        name: '信用卡取现日息（万分之五）',
        aliases: ['信用卡', '取现', '信用卡取现', '日息万5'],
        kind: 'daily_wan',
        value: 5,
        min: null,
        max: null,
        display: '日息万 5 ≈ 18.25% 年化',
        asOf: '2026-10-23',
        note: '信用卡透支取现通常按日息万分之五计收，另可能收取手续费。',
        warning: '成本较高',
        source: 'https://www.pbc.gov.cn/'
      },
      {
        id: 'monthly-fen-1',
        group: 'customary',
        name: '月息 1 分',
        aliases: ['月息1分', '一分利', '1分息', '月息一分'],
        kind: 'monthly_fen',
        value: 1,
        min: null,
        max: null,
        display: '月息 1% → 年化 12%',
        asOf: '2026-10-23',
        note: '民间「月息 1 分」通常指月息 1%，折合年化 12%。',
        warning: null,
        source: 'https://www.pbc.gov.cn/'
      },
      {
        id: 'monthly-li-5',
        group: 'customary',
        name: '月息 5 厘',
        aliases: ['月息5厘', '五厘', '5厘息'],
        kind: 'monthly_li',
        value: 5,
        min: null,
        max: null,
        display: '月息 0.5% → 年化 6%',
        asOf: '2026-10-23',
        note: '1 厘 = 0.1%/月，5 厘即月息 0.5%。',
        warning: null,
        source: 'https://www.pbc.gov.cn/'
      },
      {
        id: 'daily-wan-5',
        group: 'customary',
        name: '日息万 5',
        aliases: ['日息万5', '万5', '万分之五', '日息万分之五'],
        kind: 'daily_wan',
        value: 5,
        min: null,
        max: null,
        display: '日息 0.05% → 年化 18.25%',
        asOf: '2026-10-23',
        note: '日息万 5 = 0.05%/日，按 365 天折算年化 18.25%。',
        warning: '注意：日息万5 年化接近 18.25%',
        source: 'https://www.pbc.gov.cn/'
      },
      {
        id: 'daily-wan-3',
        group: 'customary',
        name: '日息万 3',
        aliases: ['日息万3', '万3', '万分之三'],
        kind: 'daily_wan',
        value: 3,
        min: null,
        max: null,
        display: '日息 0.03% → 年化 10.95%',
        asOf: '2026-10-23',
        note: '常见于部分消费金融产品的宣传口径。',
        warning: null,
        source: 'https://www.pbc.gov.cn/'
      },
      {
        id: 'monthly-hao-1',
        group: 'customary',
        name: '月息 1 毫',
        aliases: ['月息1毫', '一毫', '1毫息'],
        kind: 'monthly_hao',
        value: 1,
        min: null,
        max: null,
        display: '月息 0.01% → 年化 0.12%',
        asOf: '2026-10-23',
        note: '1 毫 = 0.01%/月，属于极低利率口径。',
        warning: null,
        source: 'https://www.pbc.gov.cn/'
      },
      {
        id: 'lpr-plus-60bp',
        group: 'official',
        name: 'LPR + 60BP',
        aliases: ['LPR加点', '加60个基点', 'lpr+60bp'],
        kind: 'lpr_plus_bp',
        value: 60,
        min: null,
        max: null,
        display: 'LPR(3.00%) + 0.60% = 3.60%',
        asOf: '2026-10-23',
        note: '在 1 年期 LPR 基础上加 60 个基点。',
        warning: null,
        source: 'https://www.pbc.gov.cn/'
      },
      {
        id: 'yu_e_bao-7d',
        group: 'deposit',
        name: '余额宝（7 日年化，参考）',
        aliases: ['余额宝', '7日年化', '货币基金', '七日年化'],
        kind: 'annual_pct',
        value: 1.3,
        min: null,
        max: null,
        display: '1.30% 7 日年化',
        asOf: '2026-10-23',
        note: '货币基金 7 日年化收益率随市场波动，此处为参考值。',
        warning: null,
        source: 'https://www.pbc.gov.cn/'
      },
      {
        id: 'fixed-deposit-1y',
        group: 'deposit',
        name: '银行 1 年定期存款',
        aliases: ['定期存款', '一年定期', '存款利率'],
        kind: 'annual_pct',
        value: 1.1,
        min: null,
        max: null,
        display: '1.10% 年化',
        asOf: '2026-10-23',
        note: '大型银行 1 年期整存整取挂牌利率参考。',
        warning: null,
        source: 'https://www.pbc.gov.cn/'
      },
      {
        id: 'savings-bond-3y',
        group: 'deposit',
        name: '储蓄国债（3 年期，参考）',
        aliases: ['国债', '储蓄国债', '三年期国债'],
        kind: 'annual_pct',
        value: 1.63,
        min: null,
        max: null,
        display: '1.63% 年化',
        asOf: '2026-10-23',
        note: '储蓄国债（电子式）3 年期票面利率参考。',
        warning: null,
        source: 'https://www.mof.gov.cn/'
      },
      {
        id: 'online-platform-range',
        group: 'online_loan',
        name: '主流网贷平台（日息区间）',
        aliases: ['网贷', '消费金融', '平台借款', '网络小贷'],
        kind: 'range_daily_wan',
        value: null,
        min: 2,
        max: 6,
        display: '日息万 2 ~ 万 6（中值万 4 ≈ 14.6% 年化）',
        asOf: '2026-10-23',
        note: '主流平台宣传日息区间；实际综合成本需计入服务费、担保费等。',
        warning: '按综合年化成本判断是否超过 24% 红线',
        source: 'https://www.pbc.gov.cn/'
      },
      {
        id: 'online-low-rate',
        group: 'online_loan',
        name: '持牌消费金融（低档年化）',
        aliases: ['消费金融', '持牌机构', '低息网贷'],
        kind: 'annual_pct',
        value: 7.2,
        min: null,
        max: null,
        display: '7.20% 年化',
        asOf: '2026-10-23',
        note: '持牌机构优质客户区间下限参考。',
        warning: null,
        source: 'https://www.pbc.gov.cn/'
      },
      {
        id: 'online-high-rate',
        group: 'online_loan',
        name: '网贷（接近司法上限）',
        aliases: ['高息网贷', '接近上限', '36%'],
        kind: 'annual_pct',
        value: 35.9,
        min: null,
        max: null,
        display: '35.90% 年化',
        asOf: '2026-10-23',
        note: '接近司法保护上限的高成本借款口径，仅作风险对照。',
        warning: '接近 36% 高利贷口径红线',
        source: 'https://www.pbc.gov.cn/'
      },
      {
        id: 'judicial-cap',
        group: 'official',
        name: '民间借贷司法保护上限（4 倍 LPR）',
        aliases: ['司法保护上限', '四倍LPR', '高利贷红线', '36%'],
        kind: 'lpr_multiple',
        value: 4,
        min: null,
        max: null,
        display: '4 × LPR(3.00%) = 12.00%',
        asOf: '2026-10-23',
        note: '民间借贷利率保护上限为合同成立时 1 年期 LPR 的 4 倍。',
        warning: '超过部分不受法律保护',
        source: 'https://www.pbc.gov.cn/'
      }
    ]
  };

  /**
   * 数据地址：基于 document.baseURI（相对 ./data/rates.json）解析，
   * 兼容三种场景：file:// 双击、GitHub Pages 子目录部署（/repo/）、URL 带 #hash。
   * 注意：绝对路径 '/data/rates.json' 在子目录部署下会 404，因此一律用相对路径。
   */
  function resolveDataUrl() {
    try {
      var base = document.baseURI || location.href;
      // 去掉 hash 与 query 后再解析，避免 #loan 之类的片段混进路径
      var clean = base.split('#')[0].split('?')[0];
      return new URL('data/rates.json', clean).href;
    } catch (e) {
      return './data/rates.json';
    }
  }

  var DATA_URL = resolveDataUrl();

  /** 拉取 data/rates.json，任何失败都返回 null */
  function loadRatesJson() {
    var opts = { cache: 'no-cache' };
    return fetch(DATA_URL, opts)
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (json) {
        if (!json || !Array.isArray(json.rates) || !json.rates.length) {
          throw new Error('利率数据为空');
        }
        return { data: json, fallback: false };
      })
      .catch(function () {
        // file:// 协议下 fetch 会被 CORS 拦截；尝试 retry 相对路径一次，仍失败则降级
        if (location.protocol === 'file:') return null;
        return fetch('./data/rates.json', opts)
          .then(function (res) {
            if (!res.ok) throw new Error('HTTP ' + res.status);
            return res.json();
          })
          .then(function (json) {
            if (!json || !Array.isArray(json.rates) || !json.rates.length) throw new Error('空数据');
            return { data: json, fallback: false };
          })
          .catch(function () {
            return null;
          });
      });
  }

  function logInfo() {
    /* 保持静默：控制台零 error 是验收标准之一 */
  }

  /** 用内置数据兜底 */
  function useFallback() {
    return { data: JSON.parse(JSON.stringify(FALLBACK_RATES)), fallback: true };
  }

  function boot(payload) {
    var normalized = window.LixiRates.normalizeData(payload.data);
    if (payload.fallback) {
      normalized.meta.disclaimer = normalized.meta.disclaimer || FALLBACK_RATES.meta.disclaimer;
    }
    window.LixiUI.mount(normalized, {
      fallback: payload.fallback,
      fallbackMessage: payload.fallbackMessage
    });
  }

  /** 显示致命错误（连内置数据都无法使用时） */
  function showFatal(err) {
    var banner = document.getElementById('modeBanner');
    var text = document.getElementById('modeBannerText');
    var main = document.getElementById('main');
    if (banner && text) {
      banner.hidden = false;
      banner.classList.add('banner--danger');
      text.textContent = '初始化失败：' + (err && err.message ? err.message : String(err));
    }
    if (main) {
      main.insertAdjacentHTML(
        'afterbegin',
        '<div class="wrap"><div class="error-box" role="alert">' +
          '计算器初始化失败，页面暂时无法使用。错误信息：' +
          String((err && err.message) || err).replace(/[<>&]/g, function (c) {
            return { '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c];
          }) +
          '。请刷新重试，或改用最新版 Chrome / Edge / Safari 打开。</div></div>'
      );
    }
  }

  function start() {
    if (!window.LixiFinance || !window.LixiRates || !window.LixiUI) {
      showFatal(new Error('脚本未完整加载（finance.js / rates.js / ui.js 缺失）'));
      return;
    }
    loadRatesJson().then(function (loaded) {
      var payload = loaded || useFallback();
      if (!loaded) {
        payload.fallbackMessage =
          '本地文件模式：已启用内置利率数据；使用 http 服务或线上版本可加载完整数据。';
      }
      try {
        boot(payload);
      } catch (err) {
        try {
          boot(Object.assign(useFallback(), { fallback: true }));
        } catch (err2) {
          showFatal(err2);
        }
      }
    });
  }

  /** 注册 Service Worker：只在 https / localhost 下注册，file:// 下跳过 */
  function registerSW() {
    if (!('serviceWorker' in navigator)) return;
    var host = location.hostname;
    var isLocal = host === 'localhost' || host === '127.0.0.1' || host === '[::1]' || /\.localhost$/.test(host);
    var isHttps = location.protocol === 'https:';
    if (!isHttps && !isLocal) return;
    try {
      navigator.serviceWorker.register('sw.js').catch(function () {
        /* 注册失败不影响使用，保持静默 */
      });
    } catch (e) {
      /* 忽略 */
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      start();
      registerSW();
    });
  } else {
    start();
    registerSW();
  }

  // 暴露给自检脚本
  window.LixiApp = {
    FALLBACK_RATES: FALLBACK_RATES,
    start: start
  };
  logInfo();
})();
