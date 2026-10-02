/*
 * dom_bridge.js — the JavaScript-side DOM for MayBrowser.
 *
 * This file is embedded into the browser binary at build time (see
 * tools/embed_js.py).  It is plain ES5 so that Duktape can run it without a
 * transpiler.  The Maylang side injects a JSON snapshot of the parsed document
 * and reads back `__result` (the serialised HTML) and `__logs`.
 */
(function (global) {
  'use strict';

  var VOID = { area: 1, base: 1, br: 1, col: 1, embed: 1, hr: 1, img: 1,
               input: 1, link: 1, meta: 1, param: 1, source: 1, track: 1, wbr: 1 };

  var ENT = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: '\u00a0',
              copy: '\u00a9', reg: '\u00ae', trade: '\u2122', hellip: '\u2026',
              mdash: '\u2014', ndash: '\u2013', laquo: '\u00ab', raquo: '\u00bb',
              ldquo: '\u201c', rdquo: '\u201d', times: '\u00d7', divide: '\u00f7',
              bull: '\u2022', deg: '\u00b0', euro: '\u20ac', pound: '\u00a3' };

  function decodeEnt(s) {
    if (s.indexOf('&') < 0) { return s; }
    return s.replace(/&(#x?[0-9a-fA-F]+|[a-zA-Z]+);/g, function (m, body) {
      if (body.charAt(0) === '#') {
        var code = (body.charAt(1) === 'x' || body.charAt(1) === 'X')
          ? parseInt(body.slice(2), 16) : parseInt(body.slice(1), 10);
        if (code > 0 && code <= 0x10ffff) { return String.fromCharCode(code); }
        return m;
      }
      return Object.prototype.hasOwnProperty.call(ENT, body) ? ENT[body] : m;
    });
  }

  function escText(t) {
    return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function escAttr(t) {
    return String(t).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
  }

  function makeStyle() {
    var s = {};
    s.setProperty = function (k, v) { s[k] = v; };
    s.removeProperty = function (k) { delete s[k]; };
    s.getPropertyValue = function (k) { return s[k] || ''; };
    return s;
  }

  function Element(tag) {
    this.nodeType = 1;
    this._tag = String(tag).toLowerCase();
    this.tagName = this._tag.toUpperCase();
    this.childNodes = [];
    this.parentNode = null;
    this._attrs = {};
    this.style = makeStyle();
    this._events = {};
  }

  function TextNode(text) {
    this.nodeType = 3;
    this.data = String(text);
    this.childNodes = [];
    this.parentNode = null;
  }

  function CommentNode(text) {
    this.nodeType = 8;
    this.data = String(text);
    this.childNodes = [];
    this.parentNode = null;
  }

  function descendants(node, out) {
    out = out || [];
    for (var i = 0; i < node.childNodes.length; i++) {
      var c = node.childNodes[i];
      if (c.nodeType === 1) { out.push(c); descendants(c, out); }
    }
    return out;
  }

  function matchesSimple(el, sel) {
    sel = sel.replace(/\s+/g, ' ').trim();
    if (!sel) { return false; }
    // rightmost compound + descendants
    var groups = sel.split(' ');
    var last = groups[groups.length - 1];
    if (!matchesCompound(el, last)) { return false; }
    var idx = groups.length - 2;
    var cur = el.parentNode;
    while (idx >= 0) {
      if (!cur || cur.nodeType !== 1) { return false; }
      if (matchesCompound(cur, groups[idx])) { idx--; }
      cur = cur.parentNode;
    }
    return true;
  }

  function matchesCompound(el, comp) {
    var id = null, tag = null, classes = [];
    var re = /([.#]?)([A-Za-z0-9_\-]+|\*)/g, m;
    while ((m = re.exec(comp))) {
      if (m[1] === '#') { id = m[2]; }
      else if (m[1] === '.') { classes.push(m[2]); }
      else { tag = m[2]; }
    }
    if (tag && tag !== '*' && el._tag !== tag.toLowerCase()) { return false; }
    if (id && (el._attrs.id || '') !== id) { return false; }
    for (var i = 0; i < classes.length; i++) {
      var list = (el._attrs['class'] || '').split(/\s+/);
      if (list.indexOf(classes[i]) < 0) { return false; }
    }
    return true;
  }

  Element.prototype = {
    get id() { return this._attrs.id || ''; },
    set id(v) { this._attrs.id = String(v); },
    get className() { return this._attrs['class'] || ''; },
    set className(v) { this._attrs['class'] = String(v); },
    get firstChild() { return this.childNodes.length ? this.childNodes[0] : null; },
    get lastChild() { return this.childNodes.length ? this.childNodes[this.childNodes.length - 1] : null; },
    get children() { return this.childNodes.filter(function (c) { return c.nodeType === 1; }); },
    get nextSibling() {
      if (!this.parentNode) { return null; }
      var s = this.parentNode.childNodes, i = s.indexOf(this);
      return i >= 0 && i + 1 < s.length ? s[i + 1] : null;
    },
    get previousSibling() {
      if (!this.parentNode) { return null; }
      var s = this.parentNode.childNodes, i = s.indexOf(this);
      return i > 0 ? s[i - 1] : null;
    },
    get textContent() {
      var out = '';
      for (var i = 0; i < this.childNodes.length; i++) {
        var c = this.childNodes[i];
        out += c.nodeType === 3 || c.nodeType === 8 ? c.data : c.textContent;
      }
      return out;
    },
    set textContent(v) {
      this.childNodes = [];
      if (v !== '' && v != null) { this.appendChild(new TextNode(v)); }
    },
    get innerHTML() {
      var out = '';
      for (var i = 0; i < this.childNodes.length; i++) { out += serialize(this.childNodes[i]); }
      return out;
    },
    set innerHTML(html) {
      this.childNodes = [];
      var frag = parseFragment(String(html));
      for (var i = 0; i < frag.length; i++) { this.appendChild(frag[i]); }
    },
    get outerHTML() { return serialize(this); },
    get classList() {
      var self = this;
      var api = {
        add: function () { for (var i = 0; i < arguments.length; i++) { self._classOp('add', arguments[i]); } },
        remove: function () { for (var i = 0; i < arguments.length; i++) { self._classOp('remove', arguments[i]); } },
        toggle: function (c) { return self._classOp('toggle', c); },
        contains: function (c) { return (self._attrs['class'] || '').split(/\s+/).indexOf(c) >= 0; }
      };
      return api;
    },
    setAttribute: function (k, v) { this._attrs[String(k).toLowerCase()] = String(v); },
    getAttribute: function (k) { k = String(k).toLowerCase(); return this._attrs.hasOwnProperty(k) ? this._attrs[k] : null; },
    removeAttribute: function (k) { delete this._attrs[String(k).toLowerCase()]; },
    hasAttribute: function (k) { return this._attrs.hasOwnProperty(String(k).toLowerCase()); },
    appendChild: function (child) { return this.insertBefore(child, null); },
    insertBefore: function (child, ref) {
      if (child.parentNode) { child.parentNode.removeChild(child); }
      var s = this.childNodes;
      var at = ref ? s.indexOf(ref) : s.length;
      if (at < 0) { at = s.length; }
      s.splice(at, 0, child);
      child.parentNode = this;
      return child;
    },
    removeChild: function (child) {
      var s = this.childNodes, i = s.indexOf(child);
      if (i >= 0) { s.splice(i, 1); child.parentNode = null; }
      return child;
    },
    replaceChild: function (nu, old) {
      var s = this.childNodes, i = s.indexOf(old);
      if (i < 0) { return old; }
      if (nu.parentNode) { nu.parentNode.removeChild(nu); }
      s[i] = nu; nu.parentNode = this; old.parentNode = null;
      return old;
    },
    remove: function () { if (this.parentNode) { this.parentNode.removeChild(this); } },
    append: function () {
      for (var i = 0; i < arguments.length; i++) {
        var a = arguments[i];
        this.appendChild(typeof a === 'string' ? new TextNode(a) : a);
      }
    },
    prepend: function () {
      for (var i = arguments.length - 1; i >= 0; i--) {
        var a = arguments[i];
        this.insertBefore(typeof a === 'string' ? new TextNode(a) : a, this.firstChild);
      }
    },
    insertAdjacentHTML: function (pos, html) {
      var frag = parseFragment(html);
      if (pos === 'beforeend') { for (var i = 0; i < frag.length; i++) { this.appendChild(frag[i]); } }
      else if (pos === 'afterbegin') { for (var j = frag.length - 1; j >= 0; j--) { this.insertBefore(frag[j], this.firstChild); } }
      else if (pos === 'beforebegin' && this.parentNode) { for (var k = 0; k < frag.length; k++) { this.parentNode.insertBefore(frag[k], this); } }
      else if (pos === 'afterend' && this.parentNode) { var ref = this.nextSibling; for (var l = 0; l < frag.length; l++) { this.parentNode.insertBefore(frag[l], ref); } }
    },
    getElementsByTagName: function (tag) {
      tag = String(tag).toLowerCase();
      if (tag === '*') { return descendants(this); }
      return descendants(this).filter(function (e) { return e._tag === tag; });
    },
    getElementsByClassName: function (cls) {
      var want = String(cls).split(/\s+/);
      return descendants(this).filter(function (e) {
        var have = (e._attrs['class'] || '').split(/\s+/);
        for (var i = 0; i < want.length; i++) { if (have.indexOf(want[i]) < 0) { return false; } }
        return true;
      });
    },
    querySelector: function (sel) {
      var parts = splitSelectors(sel);
      var all = [this].concat(descendants(this));
      for (var i = 0; i < all.length; i++) {
        for (var j = 0; j < parts.length; j++) { if (matchesSimple(all[i], parts[j])) { return all[i]; } }
      }
      return null;
    },
    querySelectorAll: function (sel) {
      var parts = splitSelectors(sel), out = [];
      var all = [this].concat(descendants(this));
      for (var i = 0; i < all.length; i++) {
        for (var j = 0; j < parts.length; j++) { if (matchesSimple(all[i], parts[j])) { out.push(all[i]); break; } }
      }
      return out;
    },
    matches: function (sel) { return matchesSimple(this, sel); },
    closest: function (sel) {
      var cur = this;
      while (cur && cur.nodeType === 1) { if (matchesSimple(cur, sel)) { return cur; } cur = cur.parentNode; }
      return null;
    },
    addEventListener: function (type, fn) {
      (this._events[type] = this._events[type] || []).push(fn);
    },
    removeEventListener: function (type, fn) {
      var list = this._events[type];
      if (!list) { return; }
      var i = list.indexOf(fn); if (i >= 0) { list.splice(i, 1); }
    },
    dispatchEvent: function (ev) {
      var list = this._events[ev.type] || [];
      for (var i = 0; i < list.length; i++) { list[i].call(this, ev); }
      return true;
    },
    click: function () { this.dispatchEvent({ type: 'click', target: this }); },
    cloneNode: function (deep) {
      var e = new Element(this._tag), k;
      for (k in this._attrs) { if (this._attrs.hasOwnProperty(k)) { e._attrs[k] = this._attrs[k]; } }
      if (deep) { for (var i = 0; i < this.childNodes.length; i++) { e.appendChild(this.childNodes[i].cloneNode(true)); } }
      return e;
    },
    get value() { return this._value != null ? this._value : (this._attrs.value || ''); },
    set value(v) { this._value = String(v); },
    get checked() { return this._checked === true; },
    set checked(v) { this._checked = !!v; },
    _classOp: function (op, c) {
      var list = (this._attrs['class'] || '').split(/\s+/).filter(Boolean);
      var i = list.indexOf(c);
      if (op === 'add' && i < 0) { list.push(c); }
      else if (op === 'remove' && i >= 0) { list.splice(i, 1); }
      else if (op === 'toggle') { if (i >= 0) { list.splice(i, 1); return false; } list.push(c); return true; }
      else if (op === 'contains') { return i >= 0; }
      this._attrs['class'] = list.join(' ');
      return op === 'add' || op === 'remove';
    }
  };

  TextNode.prototype = {
    get textContent() { return this.data; },
    set textContent(v) { this.data = String(v); },
    get nodeValue() { return this.data; },
    set nodeValue(v) { this.data = String(v); },
    appendChild: function (c) { this.childNodes.push(c); c.parentNode = this; return c; },
    removeChild: function (c) { var i = this.childNodes.indexOf(c); if (i >= 0) { this.childNodes.splice(i, 1); } return c; },
    cloneNode: function () { return new TextNode(this.data); },
    querySelector: function () { return null; },
    querySelectorAll: function () { return []; }
  };
  CommentNode.prototype = TextNode.prototype;

  function splitSelectors(sel) {
    return String(sel).split(',').map(function (s) { return s.trim(); }).filter(Boolean);
  }

  function serialize(node) {
    if (node.nodeType === 3) { return escText(node.data); }
    if (node.nodeType === 8) { return '<!--' + node.data + '-->'; }
    var tag = node._tag, out = '<' + tag, k;
    for (k in node._attrs) { if (node._attrs.hasOwnProperty(k)) { out += ' ' + k + '="' + escAttr(node._attrs[k]) + '"'; } }
    var styleStr = '';
    for (var sk in node.style) {
      if (node.style.hasOwnProperty(sk) && typeof node.style[sk] === 'string') { styleStr += sk + ':' + node.style[sk] + ';'; }
    }
    if (styleStr) { out += ' style="' + escAttr(styleStr) + '"'; }
    if (VOID[tag]) { return out + '>'; }
    out += '>';
    for (var i = 0; i < node.childNodes.length; i++) { out += serialize(node.childNodes[i]); }
    return out + '</' + tag + '>';
  }

  // Minimal HTML fragment parser for innerHTML.
  function parseFragment(html) {
    var root = { childNodes: [] }, stack = [root], i = 0, n = html.length;
    function top() { return stack[stack.length - 1]; }
    function addText(t) {
      if (!t) { return; }
      top().childNodes.push(new TextNode(decodeEnt(t)));
    }
    while (i < n) {
      if (html.charAt(i) !== '<') {
        var j = html.indexOf('<', i); if (j < 0) { j = n; }
        addText(html.slice(i, j)); i = j; continue;
      }
      if (html.substr(i, 4) === '<!--') {
        var e = html.indexOf('-->', i + 4); if (e < 0) { e = n; }
        top().childNodes.push(new CommentNode(html.slice(i + 4, e)));
        i = e < n ? e + 3 : n; continue;
      }
      if (html.charAt(i + 1) === '!') { var g = html.indexOf('>', i); i = g < 0 ? n : g + 1; continue; }
      if (html.charAt(i + 1) === '/') {
        var m = html.indexOf('>', i); i = m < 0 ? n : m + 1;
        if (stack.length > 1) { stack.pop(); }
        continue;
      }
      var re = /^<([a-zA-Z][a-zA-Z0-9\-]*)((?:[^>"']|"[^"]*"|'[^']*')*)>/;
      var match = re.exec(html.slice(i));
      if (!match) { addText('<'); i++; continue; }
      var tag = match[1].toLowerCase();
      var attrStr = match[2] || '';
      var el = new Element(tag);
      var ar = /([a-zA-Z_:][a-zA-Z0-9_:.\-]*)(?:\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+)))?/g, am;
      while ((am = ar.exec(attrStr))) {
        var val = am[3] != null ? am[3] : (am[4] != null ? am[4] : (am[5] != null ? am[5] : ''));
        el._attrs[am[1].toLowerCase()] = decodeEnt(val);
      }
      top().childNodes.push(el);
      i += match[0].length;
      if (!VOID[tag] && !(html.charAt(i - 2) === '/')) { stack.push(el); }
    }
    return root.childNodes;
  }

  // ------------------------------------------------------------- document

  var documentElement = null, headEl = null, bodyEl = null;

  var document = {
    nodeType: 9,
    createElement: function (t) { return new Element(t); },
    createTextNode: function (t) { return new TextNode(t); },
    createComment: function (t) { return new CommentNode(t); },
    getElementById: function (id) {
      var all = descendants(documentElement);
      for (var i = 0; i < all.length; i++) { if (all[i]._attrs.id === id) { return all[i]; } }
      return null;
    },
    getElementsByTagName: function (tag) { return documentElement.getElementsByTagName(tag); },
    getElementsByClassName: function (cls) { return documentElement.getElementsByClassName(cls); },
    querySelector: function (sel) { return documentElement.querySelector(sel); },
    querySelectorAll: function (sel) { return documentElement.querySelectorAll(sel); },
    addEventListener: function () {},
    removeEventListener: function () {},
    write: function (s) {
      var frag = parseFragment(String(s));
      for (var i = 0; i < frag.length; i++) { bodyEl.appendChild(frag[i]); }
    },
    writeln: function (s) { document.write(String(s) + '\n'); },
    get documentElement() { return documentElement; },
    get body() { return bodyEl; },
    get head() { return headEl; },
    get title() {
      var t = headEl ? headEl.getElementsByTagName('title') : [];
      return t.length ? t[0].textContent : '';
    },
    set title(v) {
      var t = headEl ? headEl.getElementsByTagName('title') : [];
      var el = t.length ? t[0] : new Element('title');
      el.textContent = v;
      if (!t.length && headEl) { headEl.appendChild(el); }
    }
  };

  function build(node) {
    if (node.tag === '#text') { return new TextNode(node.text || ''); }
    var el = new Element(node.tag);
    var a = node.attrs || {}, k;
    for (k in a) { if (a.hasOwnProperty(k)) { el._attrs[k] = a[k]; } }
    var kids = node.children || [];
    for (var i = 0; i < kids.length; i++) { el.appendChild(build(kids[i])); }
    return el;
  }

  global.__init = function (snapshot) {
    documentElement = build(snapshot);
    var kids = documentElement.childNodes;
    for (var i = 0; i < kids.length; i++) {
      if (kids[i].nodeType === 1 && kids[i]._tag === 'head') { headEl = kids[i]; }
      if (kids[i].nodeType === 1 && kids[i]._tag === 'body') { bodyEl = kids[i]; }
    }
    if (!headEl) { headEl = new Element('head'); documentElement.insertBefore(headEl, documentElement.firstChild); }
    if (!bodyEl) { bodyEl = new Element('body'); documentElement.appendChild(bodyEl); }
    documentElement.parentNode = null;
  };

  global.__run = function (src) {
    try { (0, eval)(src); }
    catch (e) { __logs.push('JS error: ' + (e && e.message ? e.message : String(e))); }
  };

  global.__serialize = function () {
    return '<!doctype html>\n' + documentElement.outerHTML;
  };

  global.__logdump = function () { return __logs; };

  global.document = document;
  global.window = global;
  global.self = global;
  global.console = {
    log: function () { __logs.push(mapArgs(arguments)); },
    info: function () { __logs.push(mapArgs(arguments)); },
    warn: function () { __logs.push('warn: ' + mapArgs(arguments)); },
    error: function () { __logs.push('error: ' + mapArgs(arguments)); },
    debug: function () { __logs.push(mapArgs(arguments)); }
  };
  global.alert = function (s) { __logs.push('alert: ' + s); };

  function mapArgs(args) {
    var parts = [];
    for (var i = 0; i < args.length; i++) { parts.push(fmt(args[i])); }
    return parts.join(' ');
  }
  function fmt(v) {
    if (v === null) { return 'null'; }
    if (v === undefined) { return 'undefined'; }
    if (typeof v === 'object') { try { return JSON.stringify(v); } catch (e) { return String(v); } }
    return String(v);
  }
})();
