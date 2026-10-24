/*!
 * 利息计算器 · 界面层
 * 全部 DOM 绑定、渲染与事件；公式只调用 LixiFinance，利率字典只调用 LixiRates。
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./finance.js'), require('./rates.js'));
  else root.LixiUI = factory(root.LixiFinance, root.LixiRates);
})(typeof globalThis !== 'undefined' ? globalThis : this, function (F, R) {
  'use strict';

  /* =========================== 小工具 =========================== */

  var CURRENCY = new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY' });
  var CURRENCY_NARROW = new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency: 'CNY',
    maximumFractionDigits: 2
  });
  var NUMBER_2 = new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  /** 金额：¥1,234.56 */
  function money(v) {
    var n = Number(v);
    if (!isFinite(n)) return '—';
    return CURRENCY.format(n);
  }

  /** 金额（表格用，去掉货币符号的紧凑写法保留 ¥） */
  function moneyCell(v) {
    var n = Number(v);
    if (!isFinite(n)) return '—';
    return CURRENCY_NARROW.format(n);
  }

  /** 百分比：3.65% */
  function pct(v, digits) {
    var n = Number(v);
    if (!isFinite(n)) return '—';
    var d = digits == null ? 4 : digits;
    return (
      n.toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: d }) + '%'
    );
  }

  function num2(v) {
    var n = Number(v);
    if (!isFinite(n)) return '—';
    return NUMBER_2.format(n);
  }

  /** 万元/亿元 友好显示 */
  function moneyCn(v) {
    var n = Number(v);
    if (!isFinite(n)) return '—';
    var abs = Math.abs(n);
    if (abs >= 1e8) return (n / 1e8).toFixed(2) + ' 亿元';
    if (abs >= 1e4) return (n / 1e4).toFixed(2) + ' 万元';
    return money(n);
  }

  function $(id) {
    return document.getElementById(id);
  }

  function qsa(sel, ctx) {
    return Array.prototype.slice.call((ctx || document).querySelectorAll(sel));
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  /** 去掉千分位与空格，解析为数字（空 → NaN） */
  function parseNum(str) {
    if (typeof str === 'number') return str;
    if (str == null) return NaN;
    var s = String(str).replace(/[,\s，]/g, '').trim();
    if (!s) return NaN;
  var n = Number(s);
    return isFinite(n) ? n : NaN;
  }

  /** 千分位格式化（保留用户输入中的小数点） */
  function formatThousands(value) {
    var s = String(value == null ? '' : value).replace(/[,\s，]/g, '');
    if (!s) return '';
    var neg = s.charAt(0) === '-';
    if (neg) s = s.slice(1);
    var parts = s.split('.');
    var intPart = parts[0].replace(/\D/g, '');
    var decPart = parts.length > 1 ? parts[1].replace(/[^\d]/g, '') : null;
    if (!intPart && decPart == null) return '';
    var out = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    if (decPart != null) out += '.' + decPart.slice(0, 2);
    return (neg ? '-' : '') + out;
  }

  /** 数字输入框：失焦时补千分位，聚焦时还原纯数字 */
  function bindThousands(input, onInput) {
    if (!input) return;
    input.addEventListener('focus', function () {
      var n = parseNum(input.value);
      input.value = isFinite(n) ? String(n) : '';
      try {
        input.setSelectionRange(input.value.length, input.value.length);
      } catch (e) {
        /* 某些浏览器对 type=number 不支持，忽略 */
      }
    });
    input.addEventListener('input', function () {
      if (onInput) onInput(parseNum(input.value));
    });
    input.addEventListener('blur', function () {
      var n = parseNum(input.value);
      if (isFinite(n) && n >= 0) input.value = formatThousands(n);
      if (onInput) onInput(n);
    });
  }

  /* =========================== 中文大写金额 =========================== */

  var CN_DIGITS = ['零', '壹', '贰', '叁', '肆', '伍', '陆', '柒', '捌', '玖'];
  var CN_UNITS = ['', '拾', '佰', '仟'];
  var CN_BIG = ['', '万', '亿', '万亿'];

  function sectionToCn(section) {
    var out = '';
    var zero = false;
    for (var i = 0; i < 4; i++) {
      var digit = Math.floor(section / Math.pow(10, 3 - i)) % 10;
      if (digit === 0) {
        if (out) zero = true;
      } else {
        if (zero) {
          out += '零';
          zero = false;
        }
        out += CN_DIGITS[digit] + CN_UNITS[3 - i];
      }
    }
    return out;
  }

  /** 1234.56 → 人民币壹仟贰佰叁拾肆元伍角陆分 */
  function toChineseCapital(amount) {
    var n = Number(amount);
    if (!isFinite(n)) return '';
    if (n < 0) return '负' + toChineseCapital(-n);
    if (n === 0) return '人民币零元整';
    if (n >= 1e16) return '金额过大';
    var cents = Math.round(n * 100);
    var intPart = Math.floor(cents / 100);
    var fracPart = cents % 100;
    var intText = '';
    if (intPart === 0) {
      intText = '零';
    } else {
      var groups = [];
      var rest = intPart;
      while (rest > 0) {
        groups.push(rest % 10000);
        rest = Math.floor(rest / 10000);
      }
      for (var g = groups.length - 1; g >= 0; g--) {
        var sec = groups[g];
        if (sec === 0) {
          if (intText && g > 0) intText += intText.slice(-1) !== '零' ? '零' : '';
          continue;
        }
        var piece = sectionToCn(sec);
        if (intText && sec < 1000 && intText.slice(-1) !== '零') intText += '零';
        intText += piece + CN_BIG[g];
      }
      intText = intText.replace(/零+$/, '');
    }
    var fracText = '';
    var jiao = Math.floor(fracPart / 10);
    var fen = fracPart % 10;
    if (jiao > 0) fracText += CN_DIGITS[jiao] + '角';
    if (fen > 0) {
      if (jiao > 0 && fen > 0) fracText += CN_DIGITS[fen] + '分';
      else if (jiao === 0) fracText += CN_DIGITS[fen] + '分';
    }
    if (!fracText) return '人民币' + intText + '元整';
    return '人民币' + intText + '元' + fracText;
  }

  /* =========================== 状态 =========================== */

  var state = {
    data: null,
    rates: [],
    groups: [],
    lpr: { '1y': 3.0, '5y': 3.5, multiple: 4 },
    fallback: false,
    tab: 'interest',
    periodDays: 30,
    customDays: 30,
    basis: 365,
    compound: false,
    loanMethod: 'equal_installment',
    onlineMethod: 'interest_first',
    onlineExpanded: false,
    loanSchedule: null,
    onlineResult: null
  };

  /** 各下拉的选中项（用于「自定义」判断与提示） */
  var rateSelectChoices = {
    rateA: null,
    rateB: null,
    loan: null,
    online: null
  };

  /* =========================== 页签 =========================== */

  function switchTab(name, focusPanel) {
    state.tab = name;
    qsa('.tab').forEach(function (t) {
      var on = t.dataset.tab === name;
      t.classList.toggle('is-active', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      t.tabIndex = on ? 0 : -1;
    });
    // 手机端底部导航同步高亮
    qsa('.tabbar__btn').forEach(function (b) {
      var on = b.dataset.tab === name;
      b.classList.toggle('is-active', on);
      if (on) b.setAttribute('aria-current', 'page');
      else b.removeAttribute('aria-current');
    });
    qsa('.panel').forEach(function (p) {
      var on = p.id === 'panel-' + name;
      p.hidden = !on;
    });
    if (focusPanel) {
      var panel = $('panel-' + name);
      if (panel) panel.focus({ preventScroll: true });
    }
    // 切页后回到顶部，手机上尤其需要（否则停在上一页的滚动位置）
    if (focusPanel === undefined || focusPanel === true) {
      try {
        window.scrollTo(0, 0);
      } catch (e) {
        /* ignore */
      }
    }
    try {
      history.replaceState(null, '', '#' + name);
    } catch (e) {
      /* file:// 下可能被拒绝，忽略 */
    }
  }

  function initTabs() {
    qsa('.tab').forEach(function (tab) {
      tab.addEventListener('click', function () {
        switchTab(tab.dataset.tab);
      });
      tab.addEventListener('keydown', function (ev) {
        var tabs = qsa('.tab');
        var idx = tabs.indexOf(tab);
        var next = null;
        if (ev.key === 'ArrowRight') next = tabs[(idx + 1) % tabs.length];
        else if (ev.key === 'ArrowLeft') next = tabs[(idx - 1 + tabs.length) % tabs.length];
        else if (ev.key === 'Home') next = tabs[0];
        else if (ev.key === 'End') next = tabs[tabs.length - 1];
        if (next) {
          ev.preventDefault();
          next.focus();
          switchTab(next.dataset.tab);
        }
      });
    });
    // 手机底部导航
    qsa('.tabbar__btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        switchTab(btn.dataset.tab);
      });
    });
    var hash = (location.hash || '').replace('#', '');
    if (['interest', 'loan', 'online', 'convert', 'rates'].indexOf(hash) >= 0) {
      switchTab(hash, false);
    }
  }

  /**
   * 给表格每格补 data-label（取自表头），供手机端卡片式布局显示「标签：值」。
   * 桌面端由 CSS 隐藏 thead，这层数据不影响桌面渲染。
   *
   * 同时给「长内容」单元格加 .is-block：说明文字、来源链接、操作按钮这类
   * 内容较长的列，在手机卡片里整行铺满显示，否则标签会把正文挤成窄条。
   */
  function labelTableCells(rootEl) {
    if (!rootEl) return;
    var tables = rootEl.querySelectorAll ? rootEl.querySelectorAll('table') : [];
    Array.prototype.forEach.call(tables, function (table) {
      var ths = table.querySelectorAll('thead th');
      if (!ths.length) return;
      var labels = Array.prototype.map.call(ths, function (th, i) {
        var t = (th.textContent || '').trim();
        return t || ('列' + (i + 1));
      });
      Array.prototype.forEach.call(table.querySelectorAll('tbody tr'), function (tr) {
        var cells = tr.children;
        if (cells.length === 1 && cells[0].colSpan > 1) return; // 空态行跳过
        Array.prototype.forEach.call(cells, function (td, i) {
          // 第一格作为卡片标题，不需要标签
          if (i === 0) {
            td.removeAttribute('data-label');
            return;
          }
          if (labels[i]) td.setAttribute('data-label', labels[i]);
          // 长内容判定：含说明段落 / 来源链接 / 按钮 → 整行块级显示
          var longContent =
            td.querySelector('.rate-note') ||
            td.querySelector('.rate-source') ||
            td.querySelector('button') ||
            td.querySelector('a');
          if (longContent) td.classList.add('is-block');
          else td.classList.remove('is-block');
        });
      });
    });
  }

  /* =========================== 自定义利率下拉 =========================== */

  /**
   * 构造一个可搜索、带分组的下拉。
   * @param {HTMLElement} mount
   * @param {{group?:string, onPick:function, placeholder?:string}} opts
   */
  function RateSelect(mount, opts) {
    this.mount = mount;
    this.opts = opts || {};
    this.open = false;
    this.activeIndex = -1;
    this.filtered = [];
    this.build();
  }

  RateSelect.prototype.build = function () {
    var self = this;
    var mount = this.mount;
    mount.innerHTML = '';
    mount.classList.add('rate-select');

    var trigger = el('button', 'rs__trigger');
    trigger.type = 'button';
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');
    var text = el('span', 'rs__trigger-text is-placeholder', this.opts.placeholder || '搜索或选择利率方案');
    var caret = el('span', 'rs__caret', '▼');
    caret.setAttribute('aria-hidden', 'true');
    trigger.appendChild(text);
    trigger.appendChild(caret);
    mount.appendChild(trigger);
    this.trigger = trigger;
    this.triggerText = text;

    var panel = el('div', 'rs__panel');
    panel.hidden = true;
    var searchWrap = el('div', 'rs__search-wrap');
    var search = el('input', 'rs__search');
    search.type = 'search';
    search.placeholder = '输入关键字筛选（如 公积金 / 万5 / 房贷）';
    search.setAttribute('aria-label', '搜索利率方案');
    searchWrap.appendChild(search);
    panel.appendChild(searchWrap);

    var list = el('div', 'rs__list');
    list.setAttribute('role', 'listbox');
    list.setAttribute('aria-label', '利率方案列表');
    panel.appendChild(list);

    var reset = el('button', 'rs__reset', '自定义：不选方案，直接手填年化利率');
    reset.type = 'button';
    panel.appendChild(reset);

    mount.appendChild(panel);
    this.panel = panel;
    this.search = search;
    this.list = list;

    trigger.addEventListener('click', function (e) {
      e.stopPropagation();
      self.toggle();
    });
    trigger.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        self.openPanel();
      }
    });
    search.addEventListener('input', function () {
      self.renderList(search.value);
    });
    search.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        self.closePanel();
        trigger.focus();
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        self.moveActive(1);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        self.moveActive(-1);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (self.activeIndex >= 0 && self.filtered[self.activeIndex]) {
          self.pick(self.filtered[self.activeIndex]);
        }
      }
    });
    reset.addEventListener('click', function () {
      self.setChoice(null);
      self.closePanel();
      if (self.opts.onPick) self.opts.onPick(null);
      trigger.focus();
    });
    document.addEventListener('click', function (e) {
      if (self.open && !mount.contains(e.target)) self.closePanel();
    });
  };

  /** 数据填充 */
  RateSelect.prototype.setData = function (rates, groups) {
    this.rates = rates || [];
    this.groups = groups || [];
    if (this.open) this.renderList(this.search.value);
  };

  RateSelect.prototype.groupFiltered = function () {
    if (!this.opts.group || this.opts.group === 'all') return this.rates;
    return this.rates.filter(
      function (r) {
        return r.group === this.opts.group;
      }.bind(this)
    );
  };

  RateSelect.prototype.toggle = function () {
    if (this.open) this.closePanel();
    else this.openPanel();
  };

  RateSelect.prototype.openPanel = function () {
    closeAllRateSelects(this);
    this.open = true;
    this.panel.hidden = false;
    this.mount.classList.add('is-open');
    this.trigger.setAttribute('aria-expanded', 'true');
    this.search.value = '';
    this.renderList('');
    var self = this;
    setTimeout(function () {
      self.search.focus();
    }, 0);
  };

  RateSelect.prototype.closePanel = function () {
    this.open = false;
    this.panel.hidden = true;
    this.mount.classList.remove('is-open');
    this.trigger.setAttribute('aria-expanded', 'false');
    this.activeIndex = -1;
  };

  RateSelect.prototype.renderList = function (keyword) {
    var self = this;
    var pool = this.groupFiltered();
    var filtered = R.search(pool, keyword);
    this.filtered = filtered;
    this.activeIndex = -1;
    this.list.innerHTML = '';

    if (!filtered.length) {
      this.list.appendChild(el('div', 'rs__empty', '没有匹配的利率方案，可在上方直接手填年化利率。'));
      return;
    }

    var grouped = R.groupRates(filtered, this.groups);
    grouped.forEach(function (bucket) {
      var label = el('div', 'rs__group-label', bucket.group.title + '（' + bucket.items.length + '）');
      self.list.appendChild(label);
      bucket.items.forEach(function (rate) {
        var btn = el('button', 'rs__opt');
        btn.type = 'button';
        btn.setAttribute('role', 'option');
        var name = el('span', 'rs__opt-name', rate.name);
        // 一律用实时换算值渲染；换算失败的条目显示「换算失败」而不是误导性的 0%
        var valText;
        if (rate.annualPct == null || !isFinite(rate.annualPct)) {
          valText = '换算失败';
        } else {
          valText = rate.isRange
            ? pct(rate.min, 2) + '~' + pct(rate.max, 2)
            : pct(rate.annualPct, 4);
        }
        var val = el('span', 'rs__opt-val', valText);
        btn.appendChild(name);
        btn.appendChild(val);
        btn.title = rate.name + (rate.note ? '\n' + rate.note : '');
        btn.addEventListener('click', function (e) {
          e.stopPropagation();
          self.pick(rate);
        });
        btn.addEventListener('mouseenter', function () {
          self.setActiveEl(btn);
        });
        self.list.appendChild(btn);
      });
    });
  };

  RateSelect.prototype.setActiveEl = function (target) {
    qsa('.rs__opt', this.list).forEach(function (b) {
      b.classList.toggle('is-active', b === target);
    });
  };

  RateSelect.prototype.moveActive = function (delta) {
    var items = qsa('.rs__opt', this.list);
    if (!items.length) return;
    this.activeIndex = (this.activeIndex + delta + items.length) % items.length;
    var target = items[this.activeIndex];
    this.setActiveEl(target);
    if (target.scrollIntoView) target.scrollIntoView({ block: 'nearest' });
  };

  RateSelect.prototype.pick = function (rate) {
    var target = document.getElementById(this.opts.targetId);
    if (target && rate && rate.annualPct != null) {
      target.value = String(Math.round(rate.annualPct * 1e6) / 1e6);
    }
    this.setChoice(rate);
    this.closePanel();
    if (this.opts.onPick) this.opts.onPick(rate);
  };

  /** 设置显示文案（rate 为 null 表示自定义） */
  RateSelect.prototype.setChoice = function (rate) {
    if (rate && rate.annualPct != null) {
      this.triggerText.textContent = (rate.isRange ? '区间中值 · ' : '') + rate.name;
      this.triggerText.classList.remove('is-placeholder');
      this.current = rate.id;
    } else {
      this.triggerText.textContent = '自定义（手动输入年化利率）';
      this.triggerText.classList.add('is-placeholder');
      this.current = null;
    }
  };

  var rateSelects = [];
  function closeAllRateSelects(except) {
    rateSelects.forEach(function (rs) {
      if (rs !== except && rs.open) rs.closePanel();
    });
  }

  /* =========================== 页签 1：利息计算 =========================== */

  function getPrincipal() {
    var v = parseNum($('principal').value);
    return v;
  }

  function currentDays() {
    return state.periodDays === 'custom' ? state.customDays : state.periodDays;
  }

  function renderInterest() {
    var principal = getPrincipal();
    var a = parseNum($('rateA-annual').value);
    var b = parseNum($('rateB-annual').value);
    var days = currentDays();
    var basis = state.basis;
    var compound = state.compound;

    var upper = $('principalUpper');
    if (isFinite(principal) && principal > 0) {
      upper.textContent = toChineseCapital(principal);
      upper.classList.remove('field__hint--danger');
    } else if ($('principal').value.trim() === '') {
      upper.textContent = '请输入本金金额';
    } else {
      upper.textContent = '本金需为大于 0 的数字';
      upper.classList.add('field__hint--danger');
    }

    var valid = isFinite(principal) && principal > 0 && isFinite(a) && isFinite(b) && a >= 0 && b >= 0;
    if (!valid) {
      clearInterestResults('请输入有效的本金与两个收益率');
      return;
    }

    var cmp, daysUsed;
    try {
      cmp = F.compareRates(principal, a, b, days);
      daysUsed = days;
    } catch (err) {
      showTabError('interestResults', err);
      return;
    }

    // 按当前口径（360/365 + 复利）重算期间利息
    var A = F.dailyInterestByBasis(principal, a, days, basis, compound);
    var B = F.dailyInterestByBasis(principal, b, days, basis, compound);

    $('resAdaily').textContent = money(A.daily);
    $('resBdaily').textContent = money(B.daily);

    var diffDaily = F.ROUND(B.daily - A.daily);
    var diffMonthly = F.ROUND(B.monthly - A.monthly);
    var diffAnnual = F.ROUND(B.annual - A.annual);

    $('resDiffDaily').textContent = (diffDaily > 0 ? '+' : '') + money(diffDaily);
    $('resDiffMonthly').textContent = (diffMonthly > 0 ? '+' : '') + money(diffMonthly);
    $('resDiffAnnual').textContent = (diffAnnual > 0 ? '+' : '') + money(diffAnnual);
    $('resDiffDaily').className = 'stat__value ' + signClass(diffDaily);
    $('resDiffMonthly').className = 'stat__value ' + signClass(diffMonthly);
    $('resDiffAnnual').className = 'stat__value ' + signClass(diffAnnual);

    var ratioText = '—';
    if (A.annualPct > 0 && B.annualPct > 0) {
      var hi = Math.max(A.annualPct, B.annualPct) / Math.min(A.annualPct, B.annualPct);
      ratioText = hi.toFixed(2) + ' 倍';
    } else if (A.annualPct === 0 && B.annualPct === 0) {
      ratioText = '相同';
    }
    $('resRatio').textContent = ratioText;

    // 胜负高亮
    var winner = cmp.better;
    $('cardA').classList.toggle('is-win', winner === 'a');
    $('cardB').classList.toggle('is-win', winner === 'b');
    $('cardA').classList.toggle('is-lose', winner === 'b');
    $('cardB').classList.toggle('is-lose', winner === 'a');
    $('statAdaily').classList.toggle('stat--win', winner === 'a');
    $('statBdaily').classList.toggle('stat--win', winner === 'b');

    // 结论
    var verdict = $('interestVerdict');
    verdict.innerHTML = '';
    var main = el('span', 'verdict__main');
    var detail = el('span', 'verdict__detail');
    var periodInterestDiff = F.ROUND(B.periodInterest - A.periodInterest);
    if (winner === 'equal') {
      main.className = 'verdict__main verdict__main--equal';
      main.textContent = '两个方案收益率相同';
      detail.textContent = '年化都是 ' + pct(a, 4) + '，' + daysUsed + ' 天收益一样。';
    } else {
      var winnerLabel = winner === 'b' ? '方案 B' : '方案 A';
      var higher = winner === 'b' ? b : a;
      var lower = winner === 'b' ? a : b;
      var diffAnnualAbs = Math.abs(diffAnnual);
      var diffDailyAbs = Math.abs(diffDaily);
      var diffPeriodAbs = Math.abs(periodInterestDiff);
      main.className = 'verdict__main verdict__main--' + winner;
      main.textContent = winnerLabel + ' 更高：年化 ' + pct(higher, 4) + ' vs ' + pct(lower, 4);
      detail.textContent =
        (winner === 'b' ? 'B 比 A' : 'A 比 B') +
        ' 每日多赚 ' + money(diffDailyAbs) +
        '，每年多赚 ' + money(diffAnnualAbs) +
        '，' + daysUsed + ' 天多赚 ' + money(diffPeriodAbs) + '。';
    }
    verdict.appendChild(main);
    verdict.appendChild(detail);

    // 期间表
    var tbody = $('periodTableBody');
    tbody.innerHTML = '';
    var rows = [
      { label: '方案 A', annual: A.annualPct, interest: A.periodInterest, end: A.endAmount, cmp: A },
      { label: '方案 B', annual: B.annualPct, interest: B.periodInterest, end: B.endAmount, cmp: B }
    ];
    rows.forEach(function (r) {
      var tr = document.createElement('tr');
      tr.appendChild(td(r.label));
      tr.appendChild(td(pct(r.annual, 4)));
      tr.appendChild(td(money(r.interest), 'num'));
      tr.appendChild(td(money(r.end), 'num'));
      // 第 5 列（复利增益）只在复利口径下出现，否则少一列更整齐
      if (compound) tr.appendChild(td('—', 'num'));
      tbody.appendChild(tr);
    });
    // 复利口径下补「单利对照」行，让用户能看到复利比单利多赚了多少。
    // 注意：增益 = 复利利息 − 单利利息，是「多赚的钱」而非利息本身，
    // 所以单列成「复利增益」行并用 + 号与正色标示，不混进方案行的金额里。
    if (compound) {
      addCompareRow(tbody, '方案 A（单利对照）', A.annualPct, A.periodSimple, F.ROUND(A.principal + A.periodSimple), '—');
      addCompareRow(tbody, '方案 B（单利对照）', B.annualPct, B.periodSimple, F.ROUND(B.principal + B.periodSimple), '—');
      addGainRow(tbody, '复利增益（A）', A.compoundGain);
      addGainRow(tbody, '复利增益（B）', B.compoundGain);
    }
    // 增益列只在复利口径下出现，避免单利时多一个空列
    var gainHead = $('gainHead');
    if (gainHead) gainHead.hidden = !compound;

    // 手机端卡片式表格需要每格带上列名
    labelTableCells($('panel-interest'));

    $('periodResultTitle').textContent = '持有 ' + daysUsed + ' 天的累计收益';    $('basisNote').textContent =
      '当前口径：' + (basis === 365 ? '日历天 365 基准' : '360 天基准') + ' · ' + (compound ? '复利（按日计息）' : '单利');
  }

  /**
   * 期间表的普通行：方案 | 年化 | 期间利息 | 到期本息 | 复利增益
   * @param {HTMLElement} tbody
   * @param {string} label
   * @param {number} annual
   * @param {number} interest 期间利息
   * @param {number} end 到期本息
   * @param {string} gainText 增益列文本（单利口径下传 '—' 或空）
   */
  function addCompareRow(tbody, label, annual, interest, end, gainText) {
    var tr = document.createElement('tr');
    tr.appendChild(td(label));
    tr.appendChild(td(pct(annual, 4)));
    tr.appendChild(td(money(interest), 'num'));
    tr.appendChild(td(money(end), 'num'));
    tr.appendChild(td(gainText || '—', 'num'));
    tbody.appendChild(tr);
    return tr;
  }

  /**
   * 复利增益行：只填「复利增益」列（= 复利利息 − 单利利息），其余列留空。
   * 这样增益数字永远落在标题写明的「复利增益」列里，不会被误读成期间利息。
   */
  function addGainRow(tbody, label, gain) {
    var tr = document.createElement('tr');
    tr.className = 'is-total';
    tr.appendChild(td(label, 'table__caption-note'));
    tr.appendChild(td('—'));
    tr.appendChild(td('—', 'num'));
    tr.appendChild(td('—', 'num'));
    var cell = td((gain > 0 ? '+' : '') + money(gain), 'num ' + signClass(gain));
    tr.appendChild(cell);
    tbody.appendChild(tr);
    return tr;
  }

  function td(text, cls) {
    var cell = document.createElement('td');
    if (cls) cell.className = cls;
    cell.textContent = text;
    return cell;
  }

  function signClass(v) {
    if (v > 0) return 'is-positive';
    if (v < 0) return 'is-negative';
    return '';
  }

  function clearInterestResults(msg) {
    $('resAdaily').textContent = '—';
    $('resBdaily').textContent = '—';
    $('resDiffDaily').textContent = '—';
    $('resDiffMonthly').textContent = '—';
    $('resDiffAnnual').textContent = '—';
    $('resRatio').textContent = '—';
    $('interestVerdict').innerHTML = '';
    var note = el('span', 'verdict__detail', msg || '请输入有效数字');
    $('interestVerdict').appendChild(note);
    var tbody = $('periodTableBody');
    tbody.innerHTML = '';
    var tr = document.createElement('tr');
    var cell = td(msg || '输入本金与利率后自动计算');
    cell.colSpan = 5;
    cell.className = 'table__empty';
    tr.appendChild(cell);
    tbody.appendChild(tr);
    $('periodResultTitle').textContent = '期间收益';
    var gh = $('gainHead');
    if (gh) gh.hidden = true;
    $('cardA').classList.remove('is-win', 'is-lose');
    $('cardB').classList.remove('is-win', 'is-lose');
  }

  /* =========================== 页签 2：贷款计算 =========================== */

  function loanMonths() {
    var term = parseNum($('loanTerm').value);
    var unit = $('loanTermUnit').value;
    if (!isFinite(term) || term <= 0) return NaN;
    return unit === 'year' ? Math.round(term * 12) : Math.round(term);
  }

  function renderLoan() {
    var principal = parseNum($('loanPrincipal').value);
    var rate = parseNum($('loanRate').value);
    var months = loanMonths();

    var upper = $('loanPrincipalUpper');
    if (isFinite(principal) && principal > 0) upper.textContent = toChineseCapital(principal);
    else upper.textContent = '';

    var hint = $('loanMonthsHint');
    if (isFinite(months) && months > 0) {
      hint.textContent = '共 ' + months + ' 期（约 ' + (months / 12).toFixed(1) + ' 年）';
      hint.classList.remove('field__hint--danger');
    } else {
      hint.textContent = '请输入有效期限';
      hint.classList.add('field__hint--danger');
    }

    if (!(isFinite(principal) && principal > 0 && isFinite(rate) && rate >= 0 && isFinite(months) && months >= 1)) {
      clearLoanResults('请输入有效的本金、利率与期限');
      return;
    }
    if (months > 1200) {
      clearLoanResults('期限最长 1200 期（100 年）');
      return;
    }

    var result;
    try {
      result = F.loanSchedule(principal, rate, months, state.loanMethod);
    } catch (err) {
      clearLoanResults(err.message);
      return;
    }
    state.loanSchedule = result;

    var summ = F.scheduleSummary(result.schedule);
    var ratio = result.totalPayment > 0 ? (result.totalInterest / result.totalPayment) * 100 : 0;

    var labels = {
      equal_installment: ['每月还款', '等额本息'],
      equal_principal: ['首月还款', '等额本金（逐月递减）'],
      interest_first: ['每月利息', '先息后本（到期还本）'],
      bullet: ['到期应还', '到期一次还本付息']
    };
    var lab = labels[state.loanMethod] || ['每月还款', ''];
    $('loanPaymentLabel').textContent = lab[0];
    $('loanMonthly').textContent = money(result.payment);
    $('loanMonthlySub').textContent =
      state.loanMethod === 'equal_principal'
        ? '末月 ' + money(summ.lastPayment)
        : state.loanMethod === 'bullet'
        ? '第 ' + result.months + ' 期一次性结清'
        : '共 ' + result.months + ' 期';
    $('loanTotalInterest').textContent = money(result.totalInterest);
    $('loanTotalPayment').textContent = money(result.totalPayment);
    $('loanInterestRatio').textContent = ratio.toFixed(2) + '%';

    var principalPct = 100 - ratio;
    $('loanBarPrincipal').style.width = Math.max(0, Math.min(100, principalPct)) + '%';
    $('loanBarInterest').style.width = Math.max(0, Math.min(100, ratio)) + '%';
    $('loanBar').setAttribute(
      'aria-label',
      '总还款 ' + money(result.totalPayment) + '，其中本金 ' + money(result.principal) + '（' + principalPct.toFixed(1) + '%），利息 ' + money(result.totalInterest) + '（' + ratio.toFixed(1) + '%）'
    );
    $('loanLegendPrincipal').textContent = money(result.principal) + ' · ' + principalPct.toFixed(1) + '%';
    $('loanLegendInterest').textContent = money(result.totalInterest) + ' · ' + ratio.toFixed(1) + '%';
    $('loanBarDesc').textContent =
      '总还款 ' + moneyCn(result.totalPayment) + '，其中利息 ' + moneyCn(result.totalInterest) + '（' + ratio.toFixed(1) + '%）';
    $('loanTableDesc').textContent = '共 ' + result.months + ' 期，逐期本金、利息与剩余本金（可导出 CSV）';

    var tbody = $('loanTableBody');
    var frag = document.createDocumentFragment();
    result.schedule.forEach(function (row) {
      var tr = document.createElement('tr');
      tr.appendChild(td(String(row.period)));
      tr.appendChild(td(moneyCell(row.payment)));
      tr.appendChild(td(moneyCell(row.principal)));
      tr.appendChild(td(moneyCell(row.interest)));
      tr.appendChild(td(moneyCell(row.remaining)));
      frag.appendChild(tr);
    });
    tbody.innerHTML = '';
    tbody.appendChild(frag);
    labelTableCells($('panel-loan'));
  }

  function clearLoanResults(msg) {
    state.loanSchedule = null;
    $('loanMonthly').textContent = '—';
    $('loanMonthlySub').textContent = '';
    $('loanTotalInterest').textContent = '—';
    $('loanTotalPayment').textContent = '—';
    $('loanInterestRatio').textContent = '—';
    $('loanBarPrincipal').style.width = '100%';
    $('loanBarInterest').style.width = '0%';
    $('loanLegendPrincipal').textContent = '—';
    $('loanLegendInterest').textContent = '—';
    $('loanTableDesc').textContent = msg || '调整上方参数后自动生成';
    var tbody = $('loanTableBody');
    tbody.innerHTML = '';
    var tr = document.createElement('tr');
    var cell = td(msg || '调整上方参数后自动生成');
    cell.colSpan = 5;
    cell.className = 'table__empty';
    tr.appendChild(cell);
    tbody.appendChild(tr);
  }

  /* =========================== 页签 3：网贷计算 =========================== */

  function onlineDays() {
    var v = parseNum($('onlineDays').value);
    var unit = $('onlineDaysUnit').value;
    if (!isFinite(v) || v <= 0) return NaN;
    return unit === 'month' ? Math.round(v * 30) : Math.round(v);
  }

  function renderOnline() {
    var principal = parseNum($('onlinePrincipal').value);
    var rate = parseNum($('onlineRate').value);
    var days = onlineDays();

    var hint = $('onlineDaysHint');
    if (isFinite(days) && days > 0) {
      hint.textContent = '共 ' + days + ' 天（约 ' + (days / 30).toFixed(1) + ' 个月）';
      hint.classList.remove('field__hint--danger');
    } else {
      hint.textContent = '请输入有效天数';
      hint.classList.add('field__hint--danger');
    }

    if (!(isFinite(principal) && principal > 0 && isFinite(rate) && rate >= 0 && isFinite(days) && days >= 1)) {
      clearOnlineResults('请输入有效的本金、年化利率与借款天数');
      renderRisk(null);
      return;
    }

    var result;
    try {
      result = F.onlineLoan(principal, rate, days, state.onlineMethod);
      var daily = F.dailyPayment(principal, rate, days);
      result.dailyPaymentInfo = daily;
    } catch (err) {
      clearOnlineResults(err.message);
      renderRisk(null);
      return;
    }
    state.onlineResult = result;

    $('onlineDailyInterest').textContent = money(result.dailyInterest);
    $('onlineDailyPayment').textContent =
      state.onlineMethod === 'interest_first' ? money(result.dailyInterest) : money(result.dailyPayment);
    $('onlineTotalInterest').textContent = money(result.totalInterest);
    $('onlineTotalPayment').textContent = money(result.totalPayment);

    // 实际年化：按现金流 IRR 求日收益率，再用「单利年化」（× 365）折算。
    // 这是国内综合年化成本的通行口径；复利折算仅作为次要信息提示，避免误导。
    var aprText = pct(rate, 4);
    var aprSub = '名义年化；实际按天计息，与 IRR 接近';
    try {
      var flows = [principal];
      result.schedule.forEach(function (row) {
        flows.push(-row.payment);
      });
      var dailyIrr = F.irr(flows);
      var aprSimple = dailyIrr * 365 * 100;
      var aprCompound = (Math.pow(1 + dailyIrr, 365) - 1) * 100;
      if (isFinite(aprSimple) && aprSimple >= 0) {
        aprText = pct(aprSimple, 2);
        var diff = Math.abs(aprSimple - rate);
        aprSub =
          'IRR 单利年化（× 365）' +
          (diff < 0.05 ? '，与名义年化一致' : '') +
          (isFinite(aprCompound) && aprCompound - aprSimple > 0.05
            ? '；若按日复利折算为 ' + pct(aprCompound, 2)
            : '');
      }
    } catch (e) {
      aprSub = '名义年化（现金流无法求解 IRR）';
    }
    $('onlineApr').textContent = aprText;
    $('onlineAprSub').textContent = aprSub;

    renderRisk(rate);

    // 明细：默认按月聚合
    var tbody = $('onlineTableBody');
    tbody.innerHTML = '';
    var rows = state.onlineExpanded ? result.schedule : aggregateByMonth(result.schedule);
    $('onlineThPeriod').textContent = state.onlineExpanded ? '天数' : '期数（按月聚合）';
    $('onlineToggleAll').textContent = state.onlineExpanded ? '收起（按月聚合）' : '展开全部 ' + result.schedule.length + ' 天';
    $('onlineToggleAll').setAttribute('aria-expanded', state.onlineExpanded ? 'true' : 'false');
    $('onlineTableDesc').textContent = state.onlineExpanded
      ? '共 ' + result.schedule.length + ' 天，按天列出'
      : '共 ' + result.schedule.length + ' 天，按月聚合（' + rows.length + ' 期）';

    var frag = document.createDocumentFragment();
    rows.forEach(function (row) {
      var tr = document.createElement('tr');
      tr.appendChild(td(row.label != null ? row.label : String(row.day)));
      tr.appendChild(td(moneyCell(row.payment)));
      tr.appendChild(td(moneyCell(row.principal)));
      tr.appendChild(td(moneyCell(row.interest)));
      tr.appendChild(td(moneyCell(row.remaining)));
      frag.appendChild(tr);
    });
    tbody.appendChild(frag);
    labelTableCells($('panel-online'));
  }

  /** 按 30 天把日明细聚合成月 */
  function aggregateByMonth(schedule) {
    var out = [];
    var bucket = null;
    schedule.forEach(function (row, idx) {
      if (idx % 30 === 0) {
        if (bucket) out.push(bucket);
        bucket = {
          label: '第 ' + (Math.floor(idx / 30) + 1) + ' 月',
          payment: 0,
          principal: 0,
          interest: 0,
          remaining: row.remaining
        };
      }
      bucket.payment = F.ROUND(bucket.payment + row.payment);
      bucket.principal = F.ROUND(bucket.principal + row.principal);
      bucket.interest = F.ROUND(bucket.interest + row.interest);
      bucket.remaining = row.remaining;
    });
    if (bucket) out.push(bucket);
    return out;
  }

  function renderRisk(annualPct) {
    var bar = $('onlineRisk');
    bar.className = 'risk-bar';
    bar.innerHTML = '';
    if (annualPct == null || !isFinite(annualPct)) {
      bar.textContent = '';
      return;
    }
    var level = R.RISK.level(annualPct);
    bar.classList.add('risk-bar--' + level);
    var icon = el('span', 'risk-bar__icon', level === 'danger' ? '⛔' : level === 'warn' ? '⚠️' : '✅');
    icon.setAttribute('aria-hidden', 'true');
    var textWrap = el('span');
    var title = el('b');
    if (level === 'danger') {
      title.textContent = '高利贷口径警告';
      textWrap.appendChild(title);
      textWrap.appendChild(
        document.createTextNode(
          '：当前年化 ' +
            pct(annualPct, 2) +
            ' 已超过 36%。按民间借贷司法口径，超过部分不受法律保护，请务必核实合同综合成本。'
        )
      );
    } else if (level === 'warn') {
      title.textContent = '成本偏高';
      textWrap.appendChild(title);
      textWrap.appendChild(
        document.createTextNode(
          '：当前年化 ' + pct(annualPct, 2) + ' 已超过 24% 综合融资成本参考红线。建议对比其他渠道后再决定。'
        )
      );
    } else {
      title.textContent = '风险提示';
      textWrap.appendChild(title);
      textWrap.appendChild(
        document.createTextNode(
          '：当前年化 ' +
            pct(annualPct, 2) +
            ' 未超过 24% 参考线。仍请以合同写明的综合年化成本（含服务费、担保费）为准。'
        )
      );
    }
    bar.appendChild(icon);
    bar.appendChild(textWrap);
  }

  function clearOnlineResults(msg) {
    state.onlineResult = null;
    $('onlineDailyInterest').textContent = '—';
    $('onlineDailyPayment').textContent = '—';
    $('onlineTotalInterest').textContent = '—';
    $('onlineTotalPayment').textContent = '—';
    $('onlineApr').textContent = '—';
    $('onlineAprSub').textContent = '';
    var tbody = $('onlineTableBody');
    tbody.innerHTML = '';
    var tr = document.createElement('tr');
    var cell = td(msg || '调整上方参数后自动生成');
    cell.colSpan = 5;
    cell.className = 'table__empty';
    tr.appendChild(cell);
    tbody.appendChild(tr);
  }

  /* =========================== 页签 4：利率换算 =========================== */

  var CONV_ITEMS = [
    { key: 'annualPct', label: '年化利率', digits: 4, unit: '%', sub: '一年期口径' },
    { key: 'monthlyPct', label: '月利率', digits: 4, unit: '%', sub: '年化 ÷ 12' },
    { key: 'dailyPct', label: '日利率', digits: 6, unit: '%', sub: '年化 ÷ 365' },
    { key: 'dailyWan', label: '日息（万几）', digits: 4, unit: '万', sub: '万分之几 / 天' },
    { key: 'monthlyFen', label: '月息（分）', digits: 4, unit: '分', sub: '1 分 = 1%/月' },
    { key: 'annualFen', label: '年息（分）', digits: 4, unit: '分', sub: '1 分 = 10%/年' },
    { key: 'monthlyLi', label: '月息（厘）', digits: 4, unit: '厘', sub: '1 厘 = 0.1%/月' },
    { key: 'annualLi', label: '年息（厘）', digits: 4, unit: '厘', sub: '1 厘 = 1%/年' },
    { key: 'monthlyHao', label: '月息（毫）', digits: 4, unit: '毫', sub: '1 毫 = 0.01%/月' },
    { key: 'basisPoints', label: '基点（BP）', digits: 2, unit: 'BP', sub: '100 BP = 1%' }
  ];

  /** 按项目单位格式化换算值（分/厘/毫/万几 不能带 % 号） */
  function formatConvValue(item, val) {
    if (item.unit === '%') return pct(val, item.digits);
    var text = Number(val).toLocaleString('zh-CN', {
      minimumFractionDigits: 0,
      maximumFractionDigits: item.digits
    });
    if (item.unit === 'BP') return text;
    if (item.unit === '万') return '万 ' + text;
    return text + ' ' + item.unit;
  }

  function renderConvert() {
    var value = parseNum($('convValue').value);
    var kind = $('convKind').value;
    var grid = $('convGrid');
    grid.innerHTML = '';
    var hint = $('convHint');

    if (!isFinite(value) || value < 0) {
      hint.textContent = '请输入不小于 0 的利率数值。';
      hint.classList.add('field__hint--danger');
      grid.appendChild(el('p', 'empty-state', '输入数值后这里是 10 种口径的完整换算。'));
      return;
    }
    hint.classList.remove('field__hint--danger');
    hint.textContent = '以「' + (R.KIND_LABELS[kind] || kind) + '」为输入口径换算。';

    var result;
    try {
      var opts = { lpr1y: state.lpr['1y'], min: value, max: value };
      if (R.isRangeKind(kind)) {
        // 区间口径在换算页按单值处理：直接当成年化或万几输入
        result =
          kind === 'range_daily_wan'
            ? F.convert(value, 'daily_wan', opts)
            : F.convert(value, 'annual_pct', opts);
      } else {
        result = F.convert(value, kind, opts);
      }
    } catch (err) {
      hint.textContent = err.message;
      hint.classList.add('field__hint--danger');
      grid.appendChild(el('p', 'empty-state', err.message));
      return;
    }

    CONV_ITEMS.forEach(function (item, idx) {
      var box = el('div', 'conv-item' + (idx === 0 ? ' conv-item--primary' : ''));
      box.appendChild(el('span', 'conv-item__label', item.label));
      var val = result[item.key];
      box.appendChild(el('span', 'conv-item__value', formatConvValue(item, val)));
      box.appendChild(el('span', 'conv-item__sub', item.sub));
      grid.appendChild(box);
    });

    var risk = el('div', 'conv-item');
    risk.appendChild(el('span', 'conv-item__label', '合规参考'));
    var level = R.RISK.level(result.annualPct);
    var cap24 = R.RISK.cap24;
    var cap36 = R.RISK.cap36;
    var capText =
      level === 'danger'
        ? '超过 36%，高利贷口径'
        : level === 'warn'
        ? '超过 24% 参考红线'
        : '未超过 24% 参考线';
    risk.appendChild(el('span', 'conv-item__value', capText));
    risk.appendChild(
      el(
        'span',
        'conv-item__sub',
        '司法保护上限参考：' + (state.lpr['1y'] * state.lpr.multiple).toFixed(2) + '%（4 倍 1 年期 LPR）· 红线 ' + cap24 + '% / ' + cap36 + '%'
      )
    );
    grid.appendChild(risk);
  }

  function renderCustomaryTable() {
    var tbody = $('convCustomaryBody');
    tbody.innerHTML = '';
    var rows = R.customaryReferenceRows();
    rows.forEach(function (row) {
      var tr = document.createElement('tr');
      tr.appendChild(td(row.name));
      tr.appendChild(td(pct(row.monthlyPct, 4)));
      tr.appendChild(td(pct(row.annualPct, 4)));
      var annualAsAnnual = row.monthlyPct * 10;
      tr.appendChild(td(pct(annualAsAnnual, 4)));
      var noteCell = td(row.trap);
      noteCell.className = 'rate-note';
      tr.appendChild(noteCell);
      tbody.appendChild(tr);
    });
    labelTableCells($('panel-convert'));
  }

  function renderFee() {
    var principal = parseNum($('feePrincipal').value);
    var fee = parseNum($('feeMonthly').value);
    var months = parseNum($('feeMonths').value);
    var hint = $('feeHint');

    if (!(isFinite(principal) && principal > 0 && isFinite(fee) && fee >= 0 && isFinite(months) && months >= 1)) {
      $('feeAprReal').textContent = '—';
      $('feeAprSimple').textContent = '—';
      $('feeTotal').textContent = '—';
      $('feeTotalPayment').textContent = '—';
      hint.textContent = '请输入有效的本金、月费率与期数。';
      hint.classList.add('field__hint--danger');
      return;
    }

    try {
      var r = F.aprFromFee(principal, fee, months);
      $('feeAprReal').textContent = pct(r.aprAnnual, 2);
      $('feeAprSimple').textContent = pct(r.aprSimple, 2);
      $('feeTotal').textContent = money(r.totalFee);
      $('feeTotalPayment').textContent = money(r.totalPayment);
      var times = r.aprSimple > 0 ? (r.aprAnnual / r.aprSimple).toFixed(2) : '—';
      hint.classList.remove('field__hint--danger');
      hint.textContent =
        '名义年化 ' +
        pct(r.aprSimple, 2) +
        '，真实年化 ' +
        pct(r.aprAnnual, 2) +
        '，约为名义值的 ' +
        times +
        ' 倍（因为本金逐月减少，利息却按全额本金收费）。';
      var lvl = R.RISK.level(r.aprAnnual);
      hint.className = 'field__hint' + (lvl === 'danger' ? ' field__hint--danger' : lvl === 'warn' ? ' field__hint--warn' : '');
    } catch (err) {
      hint.textContent = err.message;
      hint.classList.add('field__hint--danger');
    }
  }

  function initConvKind() {
    var sel = $('convKind');
    sel.innerHTML = '';
    F.KINDS.forEach(function (kind) {
      if (R.isRangeKind(kind)) return;
      var opt = document.createElement('option');
      opt.value = kind;
      opt.textContent = R.KIND_LABELS[kind] || kind;
      if (kind === 'annual_pct') opt.selected = true;
      sel.appendChild(opt);
    });
  }

  /* =========================== 页签 5：利率大全 =========================== */

  function renderRatesTable(keyword) {
    var wrap = $('ratesGroups');
    var pool = R.search(state.rates, keyword);
    $('ratesCount').textContent = keyword
      ? '匹配 ' + pool.length + ' 条 / 共 ' + state.rates.length + ' 条'
      : '共 ' + state.rates.length + ' 条利率，覆盖 ' + R.groupRates(state.rates, state.groups).length + ' 个分组。';

    wrap.innerHTML = '';
    if (!pool.length) {
      wrap.appendChild(el('p', 'empty-state', '没有找到相关利率。试试「LPR」「公积金」「余额宝」「万5」「信用卡」。'));
      return;
    }

    var buckets = R.groupRates(pool, state.groups);
    buckets.forEach(function (bucket) {
      var section = el('section', 'rate-group');
      var head = el('div', 'rate-group__head');
      head.appendChild(el('h3', 'rate-group__title', bucket.group.title));
      if (bucket.group.desc) head.appendChild(el('span', 'rate-group__desc', bucket.group.desc));
      head.appendChild(el('span', 'rate-group__count', bucket.items.length + ' 条'));
      section.appendChild(head);

      var scroll = el('div', 'table-scroll');
      var table = el('table', 'table');
      var caption = el('caption', 'sr-only', bucket.group.title + ' 利率列表');
      table.appendChild(caption);
      var thead = document.createElement('thead');
      var htr = document.createElement('tr');
      ['名称 / 别名', '口径', '年化', 'asOf', '说明', '来源', '操作'].forEach(function (h) {
        var th = document.createElement('th');
        th.scope = 'col';
        th.textContent = h;
        htr.appendChild(th);
      });
      thead.appendChild(htr);
      table.appendChild(thead);

      var tbody = document.createElement('tbody');
      bucket.items.forEach(function (rate) {
        var tr = document.createElement('tr');

        var nameTd = document.createElement('td');
        var nameSpan = el('span', 'rate-name', rate.name);
        nameTd.appendChild(nameSpan);
        if (rate.aliases && rate.aliases.length) {
          nameTd.appendChild(el('span', 'rate-alias', rate.aliases.join(' · ')));
        }
        // 手机端整行做卡片标题（名称 + 别名），别让别名挤到右边一栏
        nameTd.classList.add('is-block');
        tr.appendChild(nameTd);

        var kindTd = document.createElement('td');
        kindTd.appendChild(el('span', 'pill pill--' + (rate.group || 'loan'), rate.kindLabel));
        tr.appendChild(kindTd);

        var annualTd = document.createElement('td');
        var lvl = R.RISK.level(rate.annualPct);
        var annualText;
        if (rate.annualPct == null || !isFinite(rate.annualPct)) {
          annualText = '换算失败';
        } else if (rate.isRange) {
          annualText = pct(rate.min, 4) + ' ~ ' + pct(rate.max, 4) + '（中值 ' + pct(rate.annualPct, 4) + '）';
        } else if (rate.kind === 'lpr_plus_bp' && Number(rate.value) < 0) {
          // LPR 减点：明确展示折算过程，避免读成 0%
          annualText =
            pct(rate.annualPct, 4) +
            '（LPR ' + pct(state.lpr['1y'], 2) + ' ' + Number(rate.value) + 'BP）';
        } else {
          annualText = pct(rate.annualPct, 4);
        }
        var annualSpan = el(
          'span',
          'rate-annual' + (lvl === 'danger' ? ' rate-annual--danger' : lvl === 'warn' ? ' rate-annual--warn' : ''),
          annualText
        );
        annualTd.appendChild(annualSpan);
        tr.appendChild(annualTd);

        tr.appendChild(td(rate.asOf || '—'));

        var noteTd = document.createElement('td');
        var noteSpan = el('span', 'rate-note', rate.note || rate.display || '');
        noteTd.appendChild(noteSpan);
        if (rate.warning) {
          noteTd.appendChild(el('span', 'pill pill--warn', rate.warning));
        }
        tr.appendChild(noteTd);

        var srcTd = document.createElement('td');
        if (rate.source && /^https?:/i.test(rate.source)) {
          var a = document.createElement('a');
          a.className = 'rate-source';
          a.href = rate.source;
          a.target = '_blank';
          a.rel = 'noopener noreferrer';
          a.textContent = '数据来源 ↗';
          srcTd.appendChild(a);
        } else {
          srcTd.textContent = '—';
        }
        tr.appendChild(srcTd);

        var opTd = document.createElement('td');
        var useBtn = el('button', 'btn btn--ghost btn--sm', '用这个');
        useBtn.type = 'button';
        useBtn.addEventListener('click', function () {
          useRate(rate);
        });
        opTd.appendChild(useBtn);
        tr.appendChild(opTd);

        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      scroll.appendChild(table);
      section.appendChild(scroll);
      wrap.appendChild(section);
    });
    labelTableCells(wrap);
  }

  /** 「用这个」：跳到利息计算页并填入方案 A */
  function useRate(rate) {
    var target = $('rateA-annual');
    if (target && rate.annualPct != null) {
      target.value = String(Math.round(rate.annualPct * 1e6) / 1e6);
    }
    if (rateSelects[0]) rateSelects[0].setChoice(rate);
    updateRateNote('A', rate);
    switchTab('interest');
    renderInterest();
    if (target) {
      target.focus({ preventScroll: false });
    }
  }

  function renderRatesMeta() {
    var box = $('ratesMeta');
    var meta = state.data && state.data.meta;
    if (!meta) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    box.innerHTML = '';
    var title = el('h3', 'card__title', '数据说明');
    box.appendChild(title);
    var dl = el('dl', 'meta-list');
    function row(k, v) {
      var dt = document.createElement('dt');
      dt.textContent = k;
      var dd = document.createElement('dd');
      dd.textContent = v;
      dd.style.margin = '0 0 6px';
      dl.appendChild(dt);
      dl.appendChild(dd);
    }
    if (meta.updated) row('数据更新日期', meta.updated);
    if (state.lpr) {
      row(
        'LPR 参考（1 年期 / 5 年期以上）',
        state.lpr['1y'].toFixed(2) + '% / ' + state.lpr['5y'].toFixed(2) + '%'
      );
      row(
        '民间借贷司法保护上限（' + state.lpr.multiple + ' 倍 1 年期 LPR）',
        (state.lpr['1y'] * state.lpr.multiple).toFixed(2) + '%'
      );
    }
    if (meta.disclaimer) row('免责声明', meta.disclaimer);
    if (Array.isArray(meta.sources) && meta.sources.length) {
      var dt = document.createElement('dt');
      dt.textContent = '数据来源';
      dl.appendChild(dt);
      var dd = document.createElement('dd');
      dd.style.margin = '0 0 6px';
      meta.sources.forEach(function (src, i) {
        if (i) dd.appendChild(document.createTextNode(' · '));
        if (src.url) {
          var a = document.createElement('a');
          a.className = 'rate-source';
          a.href = src.url;
          a.target = '_blank';
          a.rel = 'noopener noreferrer';
          a.textContent = src.title || src.url;
          dd.appendChild(a);
        } else {
          dd.appendChild(document.createTextNode(src.title || ''));
        }
      });
      dl.appendChild(dd);
    }
    box.appendChild(dl);
  }

  /* =========================== 通用：错误显示 / CSV =========================== */

  function showTabError(containerId, err) {
    var box = $(containerId);
    if (!box) return;
    var msg = err && err.message ? err.message : String(err);
    box.innerHTML = '';
    var div = el('div', 'error-box', '计算出错：' + msg + '。请检查输入后重试。');
    box.appendChild(div);
  }

  function downloadFile(filename, content) {
    try {
      var blob = new Blob(['\ufeff' + content], { type: 'text/csv;charset=utf-8' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      setTimeout(function () {
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }, 100);
      return true;
    } catch (e) {
      alert('导出失败：当前浏览器不支持 Blob 下载，请改用 http 方式打开页面。');
      return false;
    }
  }

  function csvCell(v) {
    var s = String(v == null ? '' : v);
    if (/[",\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
    return s;
  }

  function exportLoanCsv() {
    if (!state.loanSchedule) {
      alert('请先完成一次有效的贷款计算。');
      return;
    }
    var r = state.loanSchedule;
    var lines = [];
    lines.push(['期数', '月供(元)', '本金(元)', '利息(元)', '剩余本金(元)'].map(csvCell).join(','));
    r.schedule.forEach(function (row) {
      lines.push(
        [row.period, row.payment.toFixed(2), row.principal.toFixed(2), row.interest.toFixed(2), row.remaining.toFixed(2)]
          .map(csvCell)
          .join(',')
      );
    });
    lines.push('');
    lines.push(['贷款本金', r.principal.toFixed(2)].map(csvCell).join(','));
    lines.push(['年化利率', r.annualPct + '%'].map(csvCell).join(','));
    lines.push(['期数', r.months].map(csvCell).join(','));
    lines.push(['总还款', r.totalPayment.toFixed(2)].map(csvCell).join(','));
    lines.push(['总利息', r.totalInterest.toFixed(2)].map(csvCell).join(','));
    downloadFile('贷款还款明细_' + r.months + '期.csv', lines.join('\r\n'));
  }

  function exportOnlineCsv() {
    if (!state.onlineResult) {
      alert('请先完成一次有效的网贷计算。');
      return;
    }
    var r = state.onlineResult;
    var lines = [];
    lines.push(['天数', '还款(元)', '本金(元)', '利息(元)', '剩余本金(元)'].map(csvCell).join(','));
    r.schedule.forEach(function (row) {
      lines.push(
        [row.day, row.payment.toFixed(2), row.principal.toFixed(2), row.interest.toFixed(2), row.remaining.toFixed(2)]
          .map(csvCell)
          .join(',')
      );
    });
    lines.push('');
    lines.push(['借款本金', r.principal.toFixed(2)].map(csvCell).join(','));
    lines.push(['年化利率', r.annualPct + '%'].map(csvCell).join(','));
    lines.push(['借款天数', r.days].map(csvCell).join(','));
    lines.push(['每日利息', r.dailyInterest.toFixed(2)].map(csvCell).join(','));
    lines.push(['总利息', r.totalInterest.toFixed(2)].map(csvCell).join(','));
    lines.push(['总还款', r.totalPayment.toFixed(2)].map(csvCell).join(','));
    downloadFile('网贷还款明细_' + r.days + '天.csv', lines.join('\r\n'));
  }

  /* =========================== 利率卡片提示 =========================== */

  function updateRateNote(slot, rate) {
    var elId = slot === 'A' ? 'rateA-note' : 'rateB-note';
    var box = $(elId);
    if (!box) return;
    if (!rate || rate.annualPct == null) {
      box.textContent = '当前为自定义利率，可直接在上面输入年化百分比。';
      box.classList.remove('field__hint--danger', 'field__hint--warn');
      return;
    }
    var parts = [];
    parts.push('年化 ' + pct(rate.annualPct, 4));
    if (rate.isRange) parts.push('原始区间 ' + pct(rate.min, 4) + ' ~ ' + pct(rate.max, 4) + '，已取中值');
    // 用实时换算值重新生成口径说明，避免直接信任 data 里的 display 字符串
    parts.push('口径 ' + (rate.kindLabel || rate.kind));
    if (rate.kind === 'lpr_plus_bp') {
      parts.push('按 LPR ' + pct(state.lpr['1y'], 2) + ' 加 ' + Number(rate.value) + 'BP 实时折算');
    }
    if (rate.asOf) parts.push('数据日期 ' + rate.asOf);
    if (rate.note) parts.push(rate.note);
    box.textContent = parts.join(' · ');
    var lvl = R.RISK.level(rate.annualPct);
    box.className = 'rate-card__note' + (lvl === 'danger' ? ' field__hint--danger' : lvl === 'warn' ? ' field__hint--warn' : '');
  }

  /* =========================== 初始化 =========================== */

  function buildRateSelects() {
    rateSelects = [];
    var specs = [
      { id: 'rateA-select', targetId: 'rateA-annual', group: 'all', slot: 'A' },
      { id: 'rateB-select', targetId: 'rateB-annual', group: 'all', slot: 'B' },
      { id: 'loanRateSelect', targetId: 'loanRate', group: 'all', slot: 'loan' },
      { id: 'onlineRateSelect', targetId: 'onlineRate', group: 'online_loan', slot: 'online' }
    ];
    specs.forEach(function (spec) {
      var mount = $(spec.id);
      if (!mount) return;
      var rs = new RateSelect(mount, {
        targetId: spec.targetId,
        group: spec.group,
        onPick: function (rate) {
          if (spec.slot === 'A' || spec.slot === 'B') {
            updateRateNote(spec.slot, rate);
            renderInterest();
          } else if (spec.slot === 'loan') {
            renderLoan();
          } else if (spec.slot === 'online') {
            renderOnline();
          }
          // 手填输入框时清空选择文案
        }
      });
      rateSelects.push(rs);
    });
  }

  function syncSelectsWithData() {
    rateSelects.forEach(function (rs) {
      rs.setData(state.rates, state.groups);
    });
  }

  /** 用户手改年化输入框 → 下拉显示「自定义」 */
  function bindManualRateInputs() {
    var mapping = [
      { inputId: 'rateA-annual', rsIndex: 0, slot: 'A' },
      { inputId: 'rateB-annual', rsIndex: 1, slot: 'B' },
      { inputId: 'loanRate', rsIndex: 2, slot: 'loan' },
      { inputId: 'onlineRate', rsIndex: 3, slot: 'online' }
    ];
    mapping.forEach(function (m) {
      var input = $(m.inputId);
      if (!input) return;
      input.addEventListener('input', function () {
        var rs = rateSelects[m.rsIndex];
        if (rs && rs.current) {
          var chosen = state.rates.filter(function (r) {
            return r.id === rs.current;
          })[0];
          var typed = parseNum(input.value);
          if (!chosen || !isFinite(typed) || Math.abs(typed - chosen.annualPct) > 0.000001) {
            rs.setChoice(null);
            if (m.slot === 'A' || m.slot === 'B') updateRateNote(m.slot, null);
          }
        }
        if (m.slot === 'A' || m.slot === 'B') renderInterest();
        else if (m.slot === 'loan') renderLoan();
        else renderOnline();
      });
    });
  }

  function initPeriodControls() {
    var chips = qsa('#periodChips .seg__btn');
    chips.forEach(function (btn) {
      btn.addEventListener('click', function () {
        chips.forEach(function (b) {
          b.classList.toggle('is-active', b === btn);
        });
        var d = btn.dataset.days;
        if (d === 'custom') {
          state.periodDays = 'custom';
          state.customDays = Math.max(1, Math.round(parseNum($('daysInput').value) || 30));
          $('daysInput').focus();
        } else {
          state.periodDays = Number(d);
          $('daysInput').value = state.periodDays;
        }
        renderInterest();
      });
    });
    $('daysInput').addEventListener('input', function () {
      var v = Math.round(parseNum($('daysInput').value));
      if (isFinite(v) && v >= 1) {
        state.customDays = v;
        if (state.periodDays === 'custom') renderInterest();
      }
    });
    $('daysInput').addEventListener('change', function () {
      var v = Math.round(parseNum($('daysInput').value));
      if (isFinite(v) && v >= 1) {
        state.customDays = v;
        // 输入自定义天数时自动切到「自定义」
        var customBtn = qsa('#periodChips .seg__btn').filter(function (b) {
          return b.dataset.days === 'custom';
        })[0];
        if (customBtn) {
          qsa('#periodChips .seg__btn').forEach(function (b) {
            b.classList.toggle('is-active', b === customBtn);
          });
          state.periodDays = 'custom';
        }
        renderInterest();
      }
    });

    qsa('#basisToggle .seg__btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        qsa('#basisToggle .seg__btn').forEach(function (b) {
          b.classList.toggle('is-active', b === btn);
        });
        state.basis = Number(btn.dataset.basis);
        renderInterest();
      });
    });

    $('compoundToggle').addEventListener('change', function (e) {
      state.compound = e.target.checked;
      renderInterest();
    });
  }

  function initLoanControls() {
    qsa('input[name="loan-method"]').forEach(function (radio) {
      radio.addEventListener('change', function () {
        if (radio.checked) {
          state.loanMethod = radio.value;
          renderLoan();
        }
      });
    });
    $('loanExport').addEventListener('click', exportLoanCsv);
  }

  function initOnlineControls() {
    qsa('input[name="online-method"]').forEach(function (radio) {
      radio.addEventListener('change', function () {
        if (radio.checked) {
          state.onlineMethod = radio.value;
          renderOnline();
        }
      });
    });
    $('onlineExport').addEventListener('click', exportOnlineCsv);
    $('onlineToggleAll').addEventListener('click', function () {
      state.onlineExpanded = !state.onlineExpanded;
      renderOnline();
    });
  }

  function initPresets() {
    qsa('#principalPresets .chip').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var v = Number(btn.dataset.amount);
        var input = $('principal');
        input.value = formatThousands(v);
        renderInterest();
      });
    });
    var swap = function () {
      var a = $('rateA-annual').value;
      $('rateA-annual').value = $('rateB-annual').value;
      $('rateB-annual').value = a;
      // 交换下拉显示
      var ca = rateSelects[0] ? rateSelects[0].current : null;
      var cb = rateSelects[1] ? rateSelects[1].current : null;
      var find = function (id) {
        return (
          state.rates.filter(function (r) {
            return r.id === id;
          })[0] || null
        );
      };
      if (rateSelects[0]) rateSelects[0].setChoice(find(cb));
      if (rateSelects[1]) rateSelects[1].setChoice(find(ca));
      updateRateNote('A', find(cb));
      updateRateNote('B', find(ca));
      renderInterest();
    };
    $('swapRates').addEventListener('click', swap);
    $('swapRatesB').addEventListener('click', swap);
  }

  function initRatesTab() {
    var search = $('ratesSearch');
    search.addEventListener('input', function () {
      renderRatesTable(search.value);
    });
  }

  function initBanner() {
    var close = $('modeBannerClose');
    if (close) {
      close.addEventListener('click', function () {
        var b = $('modeBanner');
        if (b) b.hidden = true;
      });
    }
  }

  /**
   * 手机端「添加到主屏幕」提示。
   * 仅在：小屏幕 + 未安装（display-mode 不是 standalone）+ 用户没关过 时显示。
   * 已装到桌面后不再打扰。
   */
  function initInstallTip() {
    var tip = $('installTip');
    if (!tip) return;

    var DISMISS_KEY = 'lixi_install_tip_dismissed';
    function isStandalone() {
      try {
        if (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) return true;
        if (window.navigator && window.navigator.standalone) return true;
      } catch (e) {
        /* ignore */
      }
      return false;
    }
    function isMobileWidth() {
      return window.innerWidth <= 700;
    }
    function dismissed() {
      try {
        return window.localStorage.getItem(DISMISS_KEY) === '1';
      } catch (e) {
        return false;
      }
    }

    function update() {
      var show = isMobileWidth() && !isStandalone() && !dismissed();
      tip.hidden = !show;
      if (show) {
        // 根据平台给不同的操作提示
        var isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
          (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
        var text = $('installTipText');
        if (text) {
          text.textContent = isIOS
            ? '装到手机桌面：点底部「分享」按钮 → 「添加到主屏幕」，之后可全屏、可离线使用。'
            : '装到手机桌面：点右上角「⋮」→「添加到主屏幕」，之后可全屏、可离线使用。';
        }
      }
    }

    var close = $('installTipClose');
    if (close) {
      close.addEventListener('click', function () {
        tip.hidden = true;
        try {
          window.localStorage.setItem(DISMISS_KEY, '1');
        } catch (e) {
          /* 隐私模式下可能不可写，忽略 */
        }
      });
    }

    update();
    window.addEventListener('resize', update);
    // 从桌面图标启动时 display-mode 会变，重新评估
    try {
      window.matchMedia('(display-mode: standalone)').addEventListener('change', update);
    } catch (e) {
      /* 老浏览器不支持 addEventListener，忽略 */
    }
  }

  /** 全局错误兜底：任何未捕获异常都变成页面提示，而不是白屏 */
  function installErrorGuard() {
    function show(err) {
      try {
        var banner = $('modeBanner');
        var text = $('modeBannerText');
        if (!banner || !text) return;
        banner.hidden = false;
        banner.classList.add('banner--danger');
        text.textContent = '页面出现异常：' + (err && err.message ? err.message : String(err)) + '。你可以继续使用其他页签，或刷新重试。';
      } catch (e) {
        /* 兜底的兜底，避免二次崩溃 */
      }
    }
    window.addEventListener('error', function (ev) {
      show(ev.error || ev.message);
    });
    window.addEventListener('unhandledrejection', function (ev) {
      show(ev.reason);
    });
  }

  /** 挂载：由 main.js 在数据就绪后调用 */
  function mount(appData, opts) {
    opts = opts || {};
    state.data = appData;
    state.rates = appData.rates;
    state.groups = appData.groups;
    state.lpr = appData.lpr;
    state.fallback = !!opts.fallback;

    installErrorGuard();
    initBanner();
    initInstallTip();
    initTabs();
    buildRateSelects();
    syncSelectsWithData();
    bindManualRateInputs();
    initPeriodControls();
    initLoanControls();
    initOnlineControls();
    initPresets();
    initRatesTab();
    initConvKind();
    renderCustomaryTable();
    renderRatesTable('');
    renderRatesMeta();

    // 本金 / 利率输入
    bindThousands($('principal'), renderInterest);
    bindThousands($('loanPrincipal'), renderLoan);
    bindThousands($('onlinePrincipal'), renderOnline);
    bindThousands($('feePrincipal'), renderFee);

    ['daysInput', 'rateA-annual', 'rateB-annual'].forEach(function (id) {
      var node = $(id);
      if (node) node.addEventListener('change', renderInterest);
    });
    ['loanRate', 'loanTerm'].forEach(function (id) {
      var node = $(id);
      if (node) node.addEventListener('change', renderLoan);
    });
    ['onlineRate', 'onlineDays'].forEach(function (id) {
      var node = $(id);
      if (node) node.addEventListener('change', renderOnline);
    });
    ['loanTermUnit'].forEach(function (id) {
      var node = $(id);
      if (node) node.addEventListener('change', renderLoan);
    });
    $('onlineDaysUnit').addEventListener('change', renderOnline);
    $('convValue').addEventListener('input', renderConvert);
    $('convKind').addEventListener('change', renderConvert);
    ['feeMonthly', 'feeMonths'].forEach(function (id) {
      var node = $(id);
      if (node) node.addEventListener('input', renderFee);
    });

    // 首次渲染
    $('principal').value = formatThousands(parseNum($('principal').value) || 10000);
    $('loanPrincipal').value = formatThousands(parseNum($('loanPrincipal').value) || 1000000);
    $('onlinePrincipal').value = formatThousands(parseNum($('onlinePrincipal').value) || 10000);
    $('feePrincipal').value = formatThousands(parseNum($('feePrincipal').value) || 10000);

    if (opts.fallback) {
      var banner = $('modeBanner');
      var btext = $('modeBannerText');
      if (banner && btext) {
        banner.hidden = false;
        banner.classList.add('banner--warn');
        btext.textContent = opts.fallbackMessage || '本地文件模式：已启用内置利率数据；使用 http 服务或线上版本可加载完整数据。';
      }
    }

    renderInterest();
    renderLoan();
    renderOnline();
    renderConvert();
    renderFee();

    // 深链接：例如 #loan 打开贷款页
    var hash = (location.hash || '').replace('#', '');
    if (['interest', 'loan', 'online', 'convert', 'rates'].indexOf(hash) >= 0) {
      switchTab(hash);
    }
  }

  return {
    mount: mount,
    switchTab: switchTab,
    state: state,
    // 供自检 / 调试使用
    _internals: {
      toChineseCapital: toChineseCapital,
      formatThousands: formatThousands,
      parseNum: parseNum,
      money: money,
      pct: pct,
      aggregateByMonth: aggregateByMonth
    }
  };
});
