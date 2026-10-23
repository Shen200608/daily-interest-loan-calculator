/*!
 * 利息计算器 · 利率字典
 * 负责：kind → 年化换算、分组、搜索别名、区间中值、民间叫法对照。
 * 依赖 js/finance.js（window.LixiFinance），单一公式来源；纯函数、零依赖。
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./finance.js'));
  else root.LixiRates = factory(root.LixiFinance);
})(typeof globalThis !== 'undefined' ? globalThis : this, function (F) {
  'use strict';

  if (!F) throw new Error('LixiRates 需要先加载 js/finance.js');

  /** 兜底 LPR（数据文件缺失时） */
  var DEFAULT_LPR = { '1y': 3.0, '5y': 3.5 };
  /** 司法保护上限倍数（4 倍 LPR） */
  var JUDICIAL_MULTIPLE = 4;

  /** kind 的中文说明 */
  var KIND_LABELS = {
    annual_pct: '年化利率（%）',
    monthly_pct: '月利率（%）',
    daily_pct: '日利率（%）',
    monthly_fen: '月息（分）',
    annual_fen: '年息（分）',
    monthly_li: '月息（厘）',
    annual_li: '年息（厘）',
    monthly_hao: '月息（毫）',
    daily_wan: '日息（万几）',
    per10k_yuan: '万份收益（元/万份·天）',
    lpr_plus_bp: 'LPR 加点（BP）',
    lpr_multiple: 'LPR 倍数',
    range_annual_pct: '年化区间（%）',
    range_daily_wan: '日息区间（万几）'
  };

  /** 每个口径的输入单位提示 */
  var KIND_UNITS = {
    annual_pct: '%',
    monthly_pct: '%',
    daily_pct: '%',
    monthly_fen: '分',
    annual_fen: '分',
    monthly_li: '厘',
    annual_li: '厘',
    monthly_hao: '毫',
    daily_wan: '‱',
    per10k_yuan: '元',
    lpr_plus_bp: 'BP',
    lpr_multiple: '倍',
    range_annual_pct: '%',
    range_daily_wan: '‱'
  };

  function isRangeKind(kind) {
    return kind === 'range_annual_pct' || kind === 'range_daily_wan';
  }

  /** 抓取 LPR 配置 */
  function readLpr(data) {
    var meta = (data && data.meta) || {};
    var lpr = meta.lpr || {};
    return {
      '1y': typeof lpr['1y'] === 'number' ? lpr['1y'] : DEFAULT_LPR['1y'],
      '5y': typeof lpr['5y'] === 'number' ? lpr['5y'] : DEFAULT_LPR['5y'],
      multiple: typeof meta.judicial_cap_multiple === 'number' ? meta.judicial_cap_multiple : JUDICIAL_MULTIPLE
    };
  }

  /**
   * 单条 rate → 年化百分数。
   * 文本型字段（display/asOf）缺失时给出安全默认值。
   */
  function rateToAnnual(rate, lpr) {
    var conf = lpr || DEFAULT_LPR;
    var kind = rate.kind;
    if (isRangeKind(kind)) {
      return F.normalizeToAnnual(null, kind, {
        min: Number(rate.min),
        max: Number(rate.max),
        lpr1y: conf['1y']
      });
    }
    return F.normalizeToAnnual(Number(rate.value), kind, { lpr1y: conf['1y'] });
  }

  /** 给一条记录补齐派生字段（不修改入参） */
  function decorate(rate, lpr) {
    var conf = lpr || DEFAULT_LPR;
    var out = {};
    for (var k in rate) if (Object.prototype.hasOwnProperty.call(rate, k)) out[k] = rate[k];
    var annual = null;
    var err = null;
    try {
      annual = rateToAnnual(rate, conf);
    } catch (e) {
      err = e.message;
    }
    out.annualPct = annual;
    out.error = err;
    out.isRange = isRangeKind(rate.kind);
    out.kindLabel = KIND_LABELS[rate.kind] || rate.kind;
    out.unit = KIND_UNITS[rate.kind] || '';
    out.aliases = Array.isArray(rate.aliases) ? rate.aliases : [];
    out.searchKey = [rate.name || '', out.aliases.join(' '), rate.note || '', out.kindLabel]
      .join(' ')
      .toLowerCase();
    out.groupTitle = out.group || '';
    return out;
  }

  /**
   * 整理数据文件 → { meta, lpr, groups, rates, byId, groupMap }
   */
  function normalizeData(data) {
    var lprInfo = readLpr(data);
    var rawGroups = Array.isArray(data && data.groups) ? data.groups : [];
    var groups = rawGroups.map(function (g) {
      return { id: g.id, title: g.title || g.id, desc: g.desc || '' };
    });
    if (!groups.length) {
      groups = [
        { id: 'official', title: '官方口径', desc: '' },
        { id: 'customary', title: '民间叫法', desc: '' },
        { id: 'deposit', title: '存款/理财', desc: '' },
        { id: 'loan', title: '贷款/房贷', desc: '' },
        { id: 'online_loan', title: '网贷/消费金融', desc: '' }
      ];
    }
    var groupMap = {};
    groups.forEach(function (g) {
      groupMap[g.id] = g;
    });

    var rawRates = Array.isArray(data && data.rates) ? data.rates : [];
    var rates = [];
    var byId = {};
    rawRates.forEach(function (r) {
      if (!r || !r.id) return;
      var d = decorate(r, lprInfo);
      d.groupTitle = (groupMap[d.group] && groupMap[d.group].title) || d.group || '其它';
      rates.push(d);
      byId[d.id] = d;
    });

    var meta = {};
    var rawMeta = (data && data.meta) || {};
    for (var mk in rawMeta) if (Object.prototype.hasOwnProperty.call(rawMeta, mk)) meta[mk] = rawMeta[mk];
    meta.lpr = lprInfo;

    return {
      meta: meta,
      lpr: lprInfo,
      groups: groups,
      groupMap: groupMap,
      rates: rates,
      byId: byId
    };
  }

  /** 按分组把利率归类： [{group, items:[]}] */
  function groupRates(rates, groups) {
    var out = [];
    groups.forEach(function (g) {
      var items = rates.filter(function (r) {
        return r.group === g.id;
      });
      if (items.length) out.push({ group: g, items: items });
    });
    var known = {};
    groups.forEach(function (g) {
      known[g.id] = true;
    });
    var rest = rates.filter(function (r) {
      return !known[r.group];
    });
    if (rest.length) out.push({ group: { id: '_other', title: '其它', desc: '' }, items: rest });
    return out;
  }

  /** 关键字过滤：匹配名称 / 别名 / 说明 / 分组名 */
  function search(rates, keyword) {
    var q = String(keyword == null ? '' : keyword)
      .trim()
      .toLowerCase();
    if (!q) return rates.slice();
    var terms = q.split(/\s+/).filter(Boolean);
    return rates.filter(function (r) {
      var hay = r.searchKey + ' ' + String(r.groupTitle || '').toLowerCase();
      return terms.every(function (t) {
        return hay.indexOf(t) >= 0;
      });
    });
  }

  /**
   * 「分/厘/毫」民间叫法对照：月息 vs 年息两种解释都给出。
   * @param {number} value 几「分」
   * @param {'fen'|'li'|'hao'} unit
   */
  function customaryTable(value, unit) {
    var v = Number(value) || 0;
    var perMonthPct;
    if (unit === 'li') perMonthPct = v * 0.1;
    else if (unit === 'hao') perMonthPct = v * 0.01;
    else perMonthPct = v * 1;
    var annualFromMonthly = perMonthPct * 12;
    var annualFromAnnual = perMonthPct * 10;
    return {
      value: v,
      unit: unit,
      monthlyRatePct: perMonthPct,
      monthlyAnnualPct: annualFromMonthly,
      annualAnnualPct: annualFromAnnual,
      monthlyPer10k: (monthlyRatePct * 100) / 1,
      dailyWanFromMonthly: (annualFromMonthly / 100 / 365) * 10000,
      dailyWanFromAnnual: (annualFromAnnual / 100 / 365) * 10000
    };
  }

  /** 民间叫法参考行（用于换算页对照表） */
  function customaryReferenceRows() {
    return [
      {
        name: '月息 1 分',
        monthlyPct: 1,
        annualPct: 12,
        trap: '民间「月息 1 分」= 月息 1% → 年化 12%；若被当成"年息 1 分"则是年化 10%。'
      },
      {
        name: '月息 1 厘',
        monthlyPct: 0.1,
        annualPct: 1.2,
        trap: '1 厘 = 0.1%/月，年化 1.2%；常用于描述极低利率。'
      },
      {
        name: '月息 1 毫',
        monthlyPct: 0.01,
        annualPct: 0.12,
        trap: '1 毫 = 0.01%/月，年化仅 0.12%。'
      },
      {
        name: '日息万 5',
        monthlyPct: 1.5,
        annualPct: 18.25,
        trap: '日息万 5 = 0.05%/日 → 年化 18.25%（不是 5%）。'
      },
      {
        name: '日息万 3',
        monthlyPct: 0.9,
        annualPct: 10.95,
        trap: '日息万 3 年化 10.95%，看起来低，但按天计息很贵。'
      },
      {
        name: '7 日年化 2%',
        monthlyPct: 0.1667,
        annualPct: 2,
        trap: '7 日年化是最近 7 天收益折算，不等于持有到期的确定收益。'
      }
    ];
  }

  /** 风险等级：24% 综合融资成本红线 / 36% 高利贷口径 */
  var RISK = {
    cap24: 24,
    cap36: 36,
    level: function (annualPct) {
      var a = Number(annualPct);
      if (!isFinite(a) || a < 0) return 'unknown';
      if (a > RISK.cap36) return 'danger';
      if (a > RISK.cap24) return 'warn';
      return 'safe';
    },
    text: function (annualPct) {
      var lv = RISK.level(annualPct);
      if (lv === 'danger') return '超过 36%：已触及高利贷口径红线，请高度警惕。';
      if (lv === 'warn') return '超过 24% 综合融资成本红线，成本偏高。';
      if (lv === 'safe') return '未超过 24% 综合融资成本参考线。';
      return '年化利率无效，无法判断风险。';
    }
  };

  return {
    DEFAULT_LPR: DEFAULT_LPR,
    JUDICIAL_MULTIPLE: JUDICIAL_MULTIPLE,
    KIND_LABELS: KIND_LABELS,
    KIND_UNITS: KIND_UNITS,
    RISK: RISK,
    isRangeKind: isRangeKind,
    readLpr: readLpr,
    rateToAnnual: rateToAnnual,
    decorate: decorate,
    normalizeData: normalizeData,
    groupRates: groupRates,
    search: search,
    customaryTable: customaryTable,
    customaryReferenceRows: customaryReferenceRows
  };
});
