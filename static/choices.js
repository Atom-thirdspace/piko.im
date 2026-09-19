document.querySelectorAll("[data-max-choices]").forEach(function (group) {
  var max = parseInt(group.dataset.maxChoices, 10);
  var boxes = Array.prototype.slice.call(
    group.querySelectorAll("input[type=checkbox]"));

  function sync() {
    var chosen = boxes.filter(function (b) { return b.checked; }).length;
    boxes.forEach(function (b) { b.disabled = !b.checked && chosen >= max; });
  }

  boxes.forEach(function (b) { b.addEventListener("change", sync); });
  sync();
});
