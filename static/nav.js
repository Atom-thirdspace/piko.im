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
   })();