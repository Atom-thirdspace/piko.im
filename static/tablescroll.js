(() => {
  document.querySelectorAll("table").forEach((table) => {
    if (table.closest(".tablescroll")) return;

    const wrap = document.createElement("div");
    wrap.className = "tablescroll";
    table.parentNode.insertBefore(wrap, table);
    wrap.appendChild(table);

    if (table.scrollWidth > wrap.clientWidth) {
      const caption = table.caption ? table.caption.textContent.trim() : "";
      const label = table.getAttribute("aria-label") || caption;
      wrap.setAttribute("role", "region");
      wrap.setAttribute("aria-label", label ? label + ", scrollable" : "Table, scrollable");
      wrap.tabIndex = 0;
    }
  });
})();
