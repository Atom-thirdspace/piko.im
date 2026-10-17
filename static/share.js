document.addEventListener("click", function (event) {
    var button = event.target.closest(".js-share");
    if (!button) return;

    var url = button.dataset.shareUrl;
    var title = button.dataset.shareTitle || document.title;

    var say = function (text) {
        var was = button.dataset.label || button.textContent;
        button.dataset.label = was;
        button.textContent = text;
        setTimeout(function () { button.textContent = was; }, 1600);
    };

    if (navigator.share) {
        navigator.share({ title: title, url: url }).catch(function () {});
        return;
    }
    if (navigator.clipboard) {
        navigator.clipboard.writeText(url)
            .then(function () { say("Copied"); })
            .catch(function () { say("Copy failed"); });
        return;
    }
    say(url);
});
