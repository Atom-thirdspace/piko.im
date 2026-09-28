/* A small code editor: a transparent textarea layered over highlighted text.
 *
 * No dependencies and no CDN, which keeps the page loading the same way the
 * rest of the site does. The textarea stays a real textarea, so selection,
 * spellcheck-off, IME, mobile keyboards and - importantly - the browser's own
 * undo stack all keep working. Everything we insert goes through
 * execCommand('insertText') for exactly that reason: it edits the field the
 * way a keystroke would, so ctrl+Z still walks back through it.
 */
(function (global) {
  "use strict";

  var IDENT_START = /[A-Za-z_$]/;
  var IDENT_PART = /[A-Za-z0-9_$]/;
  var DIGIT = /[0-9]/;

  function words(s) {
    var set = Object.create(null);
    s.split(" ").forEach(function (w) { if (w) { set[w] = true; } });
    return set;
  }

  var LANGS = {
    python: {
      line: "#",
      block: null,
      triple: true,
      prefix: "@",                       // decorators
      indentAfter: /:\s*$/,
      keywords: words("False None True and as assert async await break class " +
        "continue def del elif else except finally for from global if import " +
        "in is lambda nonlocal not or pass raise return try while with yield " +
        "match case"),
      builtins: words("abs all any bin bool bytes callable chr dict dir " +
        "divmod enumerate filter float format frozenset getattr hasattr hash " +
        "hex id input int isinstance issubclass iter len list map max min " +
        "next object oct open ord pow print range repr reversed round set " +
        "setattr slice sorted str sum tuple type zip self cls")
    },
    cpp: {
      line: "//",
      block: ["/*", "*/"],
      triple: false,
      prefix: "#",                       // preprocessor
      indentAfter: /[{(]\s*$/,
      keywords: words("alignas alignof and auto bool break case catch char " +
        "class const constexpr continue decltype default delete do double " +
        "else enum explicit export extern false float for friend goto if " +
        "inline int long mutable namespace new noexcept nullptr operator or " +
        "private protected public register return short signed sizeof static " +
        "static_cast struct switch template this throw true try typedef " +
        "typename union unsigned using virtual void volatile while"),
      builtins: words("cin cout cerr endl std string vector map set pair " +
        "queue stack deque size_t printf scanf sort swap push_back")
    },
    java: {
      line: "//",
      block: ["/*", "*/"],
      triple: false,
      prefix: "@",                       // annotations
      indentAfter: /[{(]\s*$/,
      keywords: words("abstract assert boolean break byte case catch char " +
        "class const continue default do double else enum extends final " +
        "finally float for goto if implements import instanceof int " +
        "interface long native new package private protected public return " +
        "short static strictfp super switch synchronized this throw throws " +
        "transient try var void volatile while true false null"),
      builtins: words("String System out println print Integer Double Long " +
        "Math Scanner List ArrayList Map HashMap Set HashSet Arrays " +
        "Collections StringBuilder length charAt")
    }
  };

  var STARTERS = {
    python: "import sys\n\ndef main():\n    data = sys.stdin.read().split()\n    \n\nmain()\n",
    cpp: "#include <bits/stdc++.h>\nusing namespace std;\n\nint main() {\n    ios::sync_with_stdio(false);\n    cin.tie(nullptr);\n    \n    return 0;\n}\n",
    java: "import java.util.*;\nimport java.io.*;\n\npublic class Main {\n    public static void main(String[] args) throws IOException {\n        Scanner sc = new Scanner(System.in);\n        \n    }\n}\n"
  };

  var PAIRS = { "(": ")", "[": "]", "{": "}", '"': '"', "'": "'" };
  var CLOSERS = { ")": true, "]": true, "}": true, '"': true, "'": true };

  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  /* Scanner. A hand-written loop rather than one large regex - triple-quoted
   * strings and escapes are far easier to get right this way, and on a file
   * this size it costs well under a millisecond. */
  function highlight(src, cfg) {
    var out = [];
    var i = 0;
    var n = src.length;

    function push(cls, text) {
      out.push(cls ? '<span class="t-' + cls + '">' + esc(text) + "</span>"
                   : esc(text));
    }

    while (i < n) {
      var ch = src[i];

      // line comment
      if (cfg.line && src.startsWith(cfg.line, i)) {
        var stop = src.indexOf("\n", i);
        if (stop === -1) { stop = n; }
        push("com", src.slice(i, stop));
        i = stop;
        continue;
      }

      // block comment
      if (cfg.block && src.startsWith(cfg.block[0], i)) {
        var end = src.indexOf(cfg.block[1], i + cfg.block[0].length);
        end = end === -1 ? n : end + cfg.block[1].length;
        push("com", src.slice(i, end));
        i = end;
        continue;
      }

      // triple-quoted string (python)
      if (cfg.triple && (src.startsWith('"""', i) || src.startsWith("'''", i))) {
        var fence = src.substr(i, 3);
        var close = src.indexOf(fence, i + 3);
        close = close === -1 ? n : close + 3;
        push("str", src.slice(i, close));
        i = close;
        continue;
      }

      // string / char literal
      if (ch === '"' || ch === "'" || (ch === "`" && cfg.triple === false)) {
        var j = i + 1;
        while (j < n) {
          if (src[j] === "\\") { j += 2; continue; }
          if (src[j] === ch || src[j] === "\n") { break; }
          j++;
        }
        if (j < n && src[j] === ch) { j++; }
        push("str", src.slice(i, j));
        i = j;
        continue;
      }

      // decorator / annotation / preprocessor line
      if (cfg.prefix && ch === cfg.prefix &&
          (i === 0 || src[i - 1] === "\n" || /\s/.test(src[i - 1]))) {
        var k = i + 1;
        if (cfg.prefix === "#") {                 // whole preprocessor line
          while (k < n && src[k] !== "\n") { k++; }
        } else {
          while (k < n && IDENT_PART.test(src[k])) { k++; }
        }
        if (k > i + 1) { push("meta", src.slice(i, k)); i = k; continue; }
      }

      // number
      if (DIGIT.test(ch) ||
          (ch === "." && i + 1 < n && DIGIT.test(src[i + 1]))) {
        var m = i;
        while (m < n && /[0-9a-fA-FxXbBoO._']/.test(src[m])) { m++; }
        // a trailing exponent sign, e.g. 1e-9
        if (m < n && /[eE]/.test(src[m - 1]) && /[+-]/.test(src[m])) {
          m++;
          while (m < n && DIGIT.test(src[m])) { m++; }
        }
        push("num", src.slice(i, m));
        i = m;
        continue;
      }

      // identifier / keyword
      if (IDENT_START.test(ch)) {
        var p = i;
        while (p < n && IDENT_PART.test(src[p])) { p++; }
        var word = src.slice(i, p);

        // a name directly before "(" reads as a call
        var after = p;
        while (after < n && src[after] === " ") { after++; }

        if (cfg.keywords[word]) { push("kw", word); }
        else if (cfg.builtins[word]) { push("bi", word); }
        else if (src[after] === "(") { push("fn", word); }
        else { push("", word); }
        i = p;
        continue;
      }

      // operators and punctuation
      if (/[+\-*/%=<>!&|^~?:;,.]/.test(ch)) {
        push("op", ch);
        i++;
        continue;
      }

      push("", ch);
      i++;
    }

    return out.join("");
  }

  function Editor(root, options) {
    options = options || {};
    var self = this;

    this.root = root;
    this.lang = options.language && LANGS[options.language] ? options.language : "python";

    root.classList.add("ed");
    root.innerHTML =
      '<div class="ed__gutter" aria-hidden="true"></div>' +
      '<div class="ed__wrap">' +
        '<pre class="ed__hl" aria-hidden="true"><code></code></pre>' +
        '<textarea class="ed__area" spellcheck="false" autocapitalize="off" ' +
                  'autocomplete="off" autocorrect="off" wrap="off"></textarea>' +
      "</div>";

    this.gutter = root.querySelector(".ed__gutter");
    this.pre = root.querySelector(".ed__hl");
    this.code = root.querySelector(".ed__hl code");
    this.area = root.querySelector(".ed__area");

    if (options.label) { this.area.setAttribute("aria-label", options.label); }
    if (options.placeholder) { this.area.placeholder = options.placeholder; }

    this.onRun = options.onRun || null;
    this.onSubmit = options.onSubmit || null;
    this.onChange = options.onChange || null;

    this.area.addEventListener("input", function () { self.refresh(); });
    this.area.addEventListener("scroll", function () { self.sync(); });
    this.area.addEventListener("keydown", function (ev) { self.key(ev); });

    this.setValue(options.value || "");
  }

  Editor.prototype.cfg = function () { return LANGS[this.lang]; };

  Editor.prototype.getValue = function () { return this.area.value; };

  Editor.prototype.setValue = function (text) {
    this.area.value = text;
    this.refresh();
  };

  Editor.prototype.setLanguage = function (key) {
    if (LANGS[key]) {
      this.lang = key;
      this.refresh();
    }
  };

  Editor.prototype.focus = function () { this.area.focus(); };

  Editor.prototype.sync = function () {
    this.pre.scrollTop = this.area.scrollTop;
    this.pre.scrollLeft = this.area.scrollLeft;
    this.gutter.scrollTop = this.area.scrollTop;
  };

  Editor.prototype.refresh = function () {
    var src = this.area.value;
    // A trailing newline leaves the last (empty) line unrendered in the <pre>,
    // which knocks the gutter one row out of step.
    this.code.innerHTML = highlight(src, this.cfg()) + "\n";

    var lines = src.split("\n").length;
    if (this._lines !== lines) {
      var buf = [];
      for (var i = 1; i <= lines; i++) { buf.push(i); }
      this.gutter.textContent = buf.join("\n");
      this._lines = lines;
    }

    this.sync();
    if (this.onChange) { this.onChange(this); }
  };

  /* Insert through the browser so the native undo stack keeps the edit. */
  Editor.prototype.insert = function (text) {
    var ok = false;
    try {
      ok = document.execCommand("insertText", false, text);
    } catch (err) {
      ok = false;
    }
    if (!ok) {
      var a = this.area;
      var s = a.selectionStart;
      var e = a.selectionEnd;
      a.value = a.value.slice(0, s) + text + a.value.slice(e);
      a.selectionStart = a.selectionEnd = s + text.length;
    }
    this.refresh();
  };

  Editor.prototype.lineStart = function (pos) {
    return this.area.value.lastIndexOf("\n", pos - 1) + 1;
  };

  Editor.prototype.key = function (ev) {
    var a = this.area;
    var s = a.selectionStart;
    var e = a.selectionEnd;
    var val = a.value;
    var cfg = this.cfg();

    if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) {
      ev.preventDefault();
      if (ev.shiftKey) {
        if (this.onSubmit) { this.onSubmit(); }
      } else if (this.onRun) {
        this.onRun();
      }
      return;
    }

    // Tab indents; shift+Tab and any multi-line selection shift the block.
    if (ev.key === "Tab") {
      ev.preventDefault();
      var multi = val.slice(s, e).indexOf("\n") !== -1;
      if (!multi && !ev.shiftKey) { this.insert("    "); return; }

      var from = this.lineStart(s);
      var to = val.indexOf("\n", e);
      if (to === -1) { to = val.length; }

      var block = val.slice(from, to).split("\n").map(function (line) {
        if (ev.shiftKey) { return line.replace(/^ {1,4}/, ""); }
        return line.trim() === "" ? line : "    " + line;
      }).join("\n");

      a.setSelectionRange(from, to);
      this.insert(block);
      a.setSelectionRange(from, from + block.length);
      return;
    }

    if (ev.key === "Enter") {
      ev.preventDefault();
      var head = val.slice(this.lineStart(s), s);
      var pad = (head.match(/^[ \t]*/) || [""])[0];
      if (cfg.indentAfter && cfg.indentAfter.test(head)) { pad += "    "; }

      // Opening a block between a pair puts the closer on its own line.
      var closes = val[s] === "}" || val[s] === ")" || val[s] === "]";
      if (closes && /[{([]\s*$/.test(head)) {
        var inner = pad;
        var outer = pad.slice(0, Math.max(0, pad.length - 4));
        this.insert("\n" + inner + "\n" + outer);
        a.selectionStart = a.selectionEnd = s + 1 + inner.length;
        this.refresh();
        return;
      }
      this.insert("\n" + pad);
      return;
    }

    // Typing the closer you already have just steps over it.
    if (CLOSERS[ev.key] && s === e && val[s] === ev.key) {
      ev.preventDefault();
      a.selectionStart = a.selectionEnd = s + 1;
      return;
    }

    if (PAIRS[ev.key]) {
      var quote = ev.key === '"' || ev.key === "'";
      if (s !== e) {                                   // wrap the selection
        ev.preventDefault();
        this.insert(ev.key + val.slice(s, e) + PAIRS[ev.key]);
        a.setSelectionRange(s + 1, s + 1 + (e - s));
        return;
      }
      // Do not auto-pair a quote against a word - that is usually an apostrophe.
      var nextCh = val[s] || "";
      if (quote && IDENT_PART.test(val[s - 1] || "")) { return; }
      if (nextCh && IDENT_PART.test(nextCh)) { return; }

      ev.preventDefault();
      this.insert(ev.key + PAIRS[ev.key]);
      a.selectionStart = a.selectionEnd = s + 1;
      return;
    }

    // Backspace in the middle of an empty pair clears both halves.
    if (ev.key === "Backspace" && s === e && s > 0) {
      if (PAIRS[val[s - 1]] === val[s]) {
        ev.preventDefault();
        a.setSelectionRange(s - 1, s + 1);
        this.insert("");
      }
    }
  };

  global.PikoEditor = {
    create: function (root, options) { return new Editor(root, options); },
    starter: function (key) { return STARTERS[key] || ""; },
    languages: LANGS
  };
})(window);
