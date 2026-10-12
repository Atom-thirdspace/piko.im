(() => {
  const api = document.body.dataset.searchApi;
  if (!api) return;

  const KINDS = [
    ["lesson", "Lessons"], ["problem", "Problems"],
    ["track", "Courses"], ["person", "People"],
  ];

  let root, input, list, status;
  let items = [];
  let cursor = -1;
  let timer = null;
  let inflight = null;
  let lastFocus = null;

  const build = () => {
    root = document.createElement("div");
    root.className = "pal";
    root.hidden = true;
    root.innerHTML =
      '<div class="pal__scrim" data-pal-close></div>' +
      '<div class="pal__box" role="dialog" aria-modal="true" aria-label="Search">' +
      '  <input class="pal__input" type="search" autocomplete="off"' +
      '         placeholder="Search lessons, problems, people\u2026"' +
      '         aria-label="Search" role="combobox" aria-expanded="true"' +
      '         aria-controls="pal-list">' +
      '  <div class="pal__status" aria-live="polite"></div>' +
      '  <ul class="pal__list" id="pal-list" role="listbox"></ul>' +
      '  <div class="pal__foot">' +
      '    <kbd>\u2191</kbd><kbd>\u2193</kbd> move' +
      '    <kbd>\u21b5</kbd> open <kbd>esc</kbd> close' +
      '  </div>' +
      "</div>";
    document.body.appendChild(root);

    input = root.querySelector(".pal__input");
    list = root.querySelector(".pal__list");
    status = root.querySelector(".pal__status");

    input.addEventListener("input", () => schedule(input.value));
    root.addEventListener("click", (ev) => {
      if (ev.target.closest("[data-pal-close]")) close();
    });
    list.addEventListener("mousemove", (ev) => {
      const li = ev.target.closest("[data-index]");
      if (li) select(Number(li.dataset.index));
    });
  };

  const isOpen = () => root && !root.hidden;

  const open = () => {
    if (!root) build();
    lastFocus = document.activeElement;
    root.hidden = false;
    document.documentElement.classList.add("is-pal-open");
    const seed = document.getElementById("search");
    input.value = seed && seed.value ? seed.value : "";
    input.select();
    input.focus();
    if (input.value) schedule(input.value);
    else render(null);
  };

  const close = () => {
    if (!isOpen()) return;
    root.hidden = true;
    document.documentElement.classList.remove("is-pal-open");
    if (inflight) inflight.abort();
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  };

  const schedule = (q) => {
    clearTimeout(timer);
    timer = setTimeout(() => run(q), 160);
  };

  const run = (q) => {
    const term = q.trim();
    if (term.length < 2) {
      render(null);
      status.textContent = term ? "Two letters or more." : "";
      return;
    }
    if (inflight) inflight.abort();
    inflight = new AbortController();
    status.textContent = "Searching\u2026";
    fetch(api + "?q=" + encodeURIComponent(term), {
      signal: inflight.signal,
      headers: { "Accept": "application/json" },
    })
      .then((res) => (res.ok ? res.json() : Promise.reject(res.status)))
      .then((data) => {
        render(data);
        status.textContent = data.total
          ? data.total + (data.total === 1 ? " result" : " results")
          : "Nothing matched \u201c" + term + "\u201d.";
      })
      .catch((err) => {
        if (err && err.name === "AbortError") return;
        status.textContent = "Search is unavailable right now.";
      });
  };

  const href = (row) => {
    if (row.kind === "problem") return "/problems/" + row.slug + "/";
    if (row.kind === "track") return "/learn/" + row.slug + "/";
    if (row.kind === "person") return "/u/" + row.slug + "/";
    if (row.track_slug && row.unit_slug) {
      return "/learn/" + row.track_slug + "/" + row.unit_slug + "/" + row.slug + "/";
    }
    return "";
  };

  const esc = (text) => {
    const node = document.createElement("span");
    node.textContent = text == null ? "" : text;
    return node.innerHTML;
  };

  const render = (data) => {
    items = [];
    list.innerHTML = "";
    cursor = -1;
    if (!data) return;

    KINDS.forEach(([kind, label]) => {
      const rows = (data.groups && data.groups[kind]) || [];
      if (!rows.length) return;

      const head = document.createElement("li");
      head.className = "pal__head";
      head.setAttribute("role", "presentation");
      head.textContent = label;
      list.appendChild(head);

      rows.forEach((row) => {
        const url = href(row);
        if (!url) return;
        const index = items.length;
        const li = document.createElement("li");
        li.className = "pal__item";
        li.dataset.index = String(index);
        li.setAttribute("role", "option");
        li.innerHTML =
          '<span class="pal__kind pal__kind--' + kind + '">' + esc(kind) + "</span>" +
          '<span class="pal__text"><span class="pal__title">' + esc(row.title) + "</span>" +
          (row.sub && row.sub !== " / "
            ? '<span class="pal__sub">' + esc(row.sub) + "</span>"
            : "") +
          "</span>";
        li.addEventListener("click", () => go(index));
        list.appendChild(li);
        items.push({ node: li, url: url });
      });
    });

    if (items.length) select(0);
  };

  const select = (index) => {
    if (!items.length) return;
    if (cursor >= 0 && items[cursor]) {
      items[cursor].node.classList.remove("is-on");
      items[cursor].node.setAttribute("aria-selected", "false");
    }
    cursor = (index + items.length) % items.length;
    const hit = items[cursor];
    hit.node.classList.add("is-on");
    hit.node.setAttribute("aria-selected", "true");
    hit.node.scrollIntoView({ block: "nearest" });
  };

  const go = (index) => {
    const hit = items[index];
    if (hit) window.location.href = hit.url;
  };

  const typing = (el) =>
    el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA"
           || el.tagName === "SELECT" || el.isContentEditable);

  document.addEventListener("keydown", (ev) => {
    const key = ev.key.toLowerCase();

    if ((ev.metaKey || ev.ctrlKey) && key === "k") {
      ev.preventDefault();
      isOpen() ? close() : open();
      return;
    }

    if (!isOpen()) {
      if (key === "/" && !typing(document.activeElement)
          && !ev.metaKey && !ev.ctrlKey && !ev.altKey) {
        ev.preventDefault();
        open();
      }
      return;
    }

    if (key === "escape") { ev.preventDefault(); close(); }
    else if (key === "arrowdown") { ev.preventDefault(); select(cursor + 1); }
    else if (key === "arrowup") { ev.preventDefault(); select(cursor - 1); }
    else if (key === "enter" && cursor >= 0) { ev.preventDefault(); go(cursor); }
  });

  document.addEventListener("click", (ev) => {
    const trigger = ev.target.closest("[data-pal-open]");
    if (trigger) { ev.preventDefault(); open(); }
  });
})();
