(() => {
  const nav = document.querySelector(".topnav");
  if (!nav) return;

  const toggle = nav.querySelector("[data-nav-toggle]");
  const panel = nav.querySelector("[data-nav-panel]");
  if (!toggle || !panel) return;

  const isOpen = () => nav.hasAttribute("data-nav-open");

  const open = () => {
    nav.setAttribute("data-nav-open", "");
    toggle.setAttribute("aria-expanded", "true");
    document.documentElement.classList.add("is-nav-open");
  };

  const close = () => {
    nav.removeAttribute("data-nav-open");
    toggle.setAttribute("aria-expanded", "false");
    document.documentElement.classList.remove("is-nav-open");
  };

  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    isOpen() ? close() : open();
  });

  panel.addEventListener("click", (event) => {
    if (event.target.closest("a")) close();
  });

  document.addEventListener("click", (event) => {
    if (!isOpen()) return;
    if (panel.contains(event.target) || toggle.contains(event.target)) return;
    close();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && isOpen()) {
      close();
      toggle.focus();
    }
   });

   window.matchMedia("(min-width: 60.0625rem)").addEventListener("change", (event) => {
        if (event.matches) close();
    });

  const groups = nav.querySelectorAll("[data-navgroup]");
  const wide = window.matchMedia("(min-width: 60.0625rem)");

  // Only the groups inside the drawer flatten into section headings. The
  // alerts and account menus live in the header and stay click-driven.
  const drawerGroups = panel.querySelectorAll("[data-navgroup]");

  const syncGroups = () => {
    drawerGroups.forEach((group) => {
      if (wide.matches) group.removeAttribute("open");
      else group.setAttribute("open", "");
    });
  };

  syncGroups();
  wide.addEventListener("change", syncGroups);

  groups.forEach((group) => {
    group.addEventListener("toggle", () => {
      if (!group.open || !wide.matches) return;
      groups.forEach((other) => {
        if (other !== group) other.removeAttribute("open");
      });
    });
  });

  document.addEventListener("click", (event) => {
    if (!wide.matches) return;
    groups.forEach((group) => {
      if (!group.contains(event.target)) group.removeAttribute("open");
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !wide.matches) return;
    groups.forEach((group) => group.removeAttribute("open"));
  });

  // Hover to open, with a little intent either side: a short delay before
  // opening stops the menus flickering as the pointer crosses the bar, and a
  // longer one before closing forgives a wobble on the way to the menu.
  const OPEN_AFTER = 90;
  const CLOSE_AFTER = 220;
  const hoverable = window.matchMedia("(hover: hover) and (pointer: fine)");
  let timer = null;

  const cancel = () => {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
  };

  const schedule = (fn, wait) => {
    cancel();
    timer = setTimeout(() => {
      timer = null;
      fn();
    }, wait);
  };

  const byHover = () => wide.matches && hoverable.matches;

  // Only the section menus open on hover. Alerts and the account menu are
  // click-only: they are destinations, not things to brush past.
  drawerGroups.forEach((group) => {
    group.addEventListener("pointerenter", (event) => {
      if (event.pointerType === "touch" || !byHover()) return;
      schedule(() => {
        groups.forEach((other) => {
          if (other !== group) other.removeAttribute("open");
        });
        group.setAttribute("open", "");
      }, OPEN_AFTER);
    });

    group.addEventListener("pointerleave", (event) => {
      if (event.pointerType === "touch" || !byHover()) return;
      schedule(() => group.removeAttribute("open"), CLOSE_AFTER);
    });

    // A tap or click settles it immediately, so the pending hover timer
    // must not reopen what the click just closed.
    group.addEventListener("click", cancel);

    // Keyboard users tab into the trigger and expect the same menu.
    group.addEventListener("focusin", () => {
      if (!wide.matches) return;
      cancel();
      group.setAttribute("open", "");
    });

    group.addEventListener("focusout", (event) => {
      if (!wide.matches) return;
      if (group.contains(event.relatedTarget)) return;
      group.removeAttribute("open");
    });
  });

  // The alerts panel loads its rows the first time it opens, so base.html
  // costs no extra query on pages nobody opens it from.
  const alerts = nav.querySelector("[data-alerts]");
  if (alerts) {
    const list = alerts.querySelector("[data-alerts-list]");
    let state = "idle";

    const say = (text) => {
      list.innerHTML = "";
      const p = document.createElement("p");
      p.className = "navalerts__state";
      p.textContent = text;
      list.append(p);
    };

    const paint = (items) => {
      if (!items.length) {
        say("Nothing yet.");
        return;
      }
      list.innerHTML = "";
      items.forEach((item) => {
        const link = document.createElement("a");
        link.className = "navalerts__item";
        link.href = item.url;
        if (item.unread) link.dataset.unread = "";

        const icon = document.createElement("span");
        icon.className = "navalerts__icon";
        icon.setAttribute("aria-hidden", "true");
        icon.textContent = item.icon;

        const body = document.createElement("span");
        body.className = "navalerts__body";

        const title = document.createElement("span");
        title.className = "navalerts__title";
        title.textContent = item.title;

        const meta = document.createElement("span");
        meta.className = "navalerts__meta";
        meta.textContent = item.kind + " · " + item.ago;

        body.append(title, meta);
        link.append(icon, body);
        list.append(link);
      });
    };

    const load = () => {
      if (state !== "idle") return;
      state = "loading";
      fetch(alerts.dataset.alertsUrl, {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      })
        .then((response) => {
          if (!response.ok) throw new Error(response.status);
          return response.json();
        })
        .then((data) => {
          state = "done";
          paint(data.items || []);
        })
        .catch(() => {
          // Let the next open try again rather than stranding the panel.
          state = "idle";
          say("Couldn't load these. Open the full list instead.");
        });
    };

    alerts.addEventListener("toggle", () => {
      if (alerts.open) load();
    });
  }
   })();