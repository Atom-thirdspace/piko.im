/* Drives the onboarding questionnaire against /api/onboarding/*.
   The server owns the flow: every response tells us which stage to render. */
(function () {
  "use strict";

  var root = document.getElementById("quiz");
  if (!root) return;

  var urls = {
    state: root.dataset.stateUrl,
    answer: root.dataset.answerUrl,
    back: root.dataset.backUrl,
    placement: root.dataset.placementUrl,
    preview: root.dataset.previewUrl,
    complete: root.dataset.completeUrl,
    home: root.dataset.homeUrl,
  };

  var body = document.getElementById("quiz-body");
  var title = document.getElementById("quiz-title");
  var errorBox = document.getElementById("quiz-error");
  var progress = document.getElementById("quiz-progress");
  var backBtn = document.getElementById("quiz-back");
  var nextBtn = document.getElementById("quiz-next");

  var current = null;       // the step or stage payload being shown
  var selection = null;     // string for "choice", array for "multi"
  var placementAnswers = {};

  function api(url, method, payload) {
    return fetch(url, {
      method: method || "GET",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: payload ? JSON.stringify(payload) : undefined,
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok) throw new Error(data.error || "Something went wrong.");
        return data;
      });
    });
  }

  function showError(message) {
    errorBox.textContent = message;
    errorBox.hidden = !message;
  }

  function setProgress(done, total) {
    var pct = total ? Math.round((done / total) * 100) : 0;
    progress.style.width = Math.min(pct, 100) + "%";
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  /* ---------- questions ---------- */

  function renderStep(state) {
    var step = state.step;
    current = { stage: "questions", step: step };
    selection = step.kind === "multi" ? (step.chosen || []).slice() : (step.chosen || null);

    title.textContent = step.prompt;
    body.innerHTML = "";

    var list = el("div", "quiz-options");
    step.options.forEach(function (option) {
      var btn = el("button", "quiz-option", option.label);
      btn.type = "button";
      btn.dataset.id = option.id;
      if (isChosen(option.id)) btn.classList.add("is-chosen");
      btn.addEventListener("click", function () { choose(option.id, list); });
      list.appendChild(btn);
    });
    body.appendChild(list);

    if (step.kind === "multi") {
      body.appendChild(el("p", "quiz-hint",
        "Pick up to " + step.max_choices + ", or continue without choosing."));
    }

    setProgress(state.progress.answered, state.progress.total);
    backBtn.hidden = state.progress.answered === 0;
    nextBtn.hidden = false;
    nextBtn.textContent = "Continue";
    syncNext();
  }

  function isChosen(id) {
    return current.step.kind === "multi"
      ? selection.indexOf(id) !== -1
      : selection === id;
  }

  function choose(id, list) {
    var step = current.step;
    if (step.kind === "multi") {
      var at = selection.indexOf(id);
      if (at === -1) {
        if (selection.length >= step.max_choices) return;
        selection.push(id);
      } else {
        selection.splice(at, 1);
      }
    } else {
      selection = id;
    }
    Array.prototype.forEach.call(list.children, function (btn) {
      btn.classList.toggle("is-chosen", isChosen(btn.dataset.id));
    });
    showError("");
    syncNext();

    // Single-choice steps advance on their own; multi waits for Continue.
    if (step.kind !== "multi") submitAnswer();
  }

  function syncNext() {
    var step = current.step;
    var count = step.kind === "multi" ? selection.length : (selection ? 1 : 0);
    nextBtn.disabled = count < step.min_choices;
  }

  function submitAnswer() {
    nextBtn.disabled = true;
    api(urls.answer, "POST", { key: current.step.key, value: selection })
      .then(render)
      .catch(function (err) { showError(err.message); syncNext(); });
  }

  /* ---------- placement quiz ---------- */

  function renderPlacement(state) {
    current = { stage: "placement", questions: state.questions };
    placementAnswers = {};

    title.textContent = "A few quick questions";
    body.innerHTML = "";

    state.questions.forEach(function (question, index) {
      var card = el("div", "quiz-question");
      card.appendChild(el("p", "quiz-question-prompt",
        (index + 1) + ". " + question.prompt));

      var list = el("div", "quiz-options");
      question.choices.forEach(function (choice) {
        var btn = el("button", "quiz-option", choice.text);
        btn.type = "button";
        btn.addEventListener("click", function () {
          placementAnswers[question.id] = choice.id;
          Array.prototype.forEach.call(list.children, function (other) {
            other.classList.remove("is-chosen");
          });
          btn.classList.add("is-chosen");
          nextBtn.disabled = false;
        });
        list.appendChild(btn);
      });
      card.appendChild(list);
      body.appendChild(card);
    });

    setProgress(1, 1);
    backBtn.hidden = true;
    nextBtn.hidden = false;
    nextBtn.disabled = true;
    nextBtn.textContent = "Submit answers";
  }

  function submitPlacement() {
    nextBtn.disabled = true;
    api(urls.placement, "POST", { responses: placementAnswers })
      .then(function (result) {
        showError("");
        return loadPreview(result);
      })
      .catch(function (err) { showError(err.message); nextBtn.disabled = false; });
  }

  /* ---------- review ---------- */

  function loadPreview(placementResult) {
    return api(urls.preview).then(function (data) {
      renderReview(data.recommendation, data.tracks, placementResult);
    });
  }

  function renderReview(rec, tracks, placementResult) {
    current = { stage: "review", track: rec.track_slug };

    title.textContent = "Here's your starting point";
    body.innerHTML = "";

    if (placementResult) {
      body.appendChild(el("p", "quiz-score",
        "You scored " + placementResult.score + " of " + placementResult.possible +
        " - that puts you at " + placementResult.level + "."));
    }

    var summary = el("div", "quiz-summary");
    summary.appendChild(el("h2", null, rec.track_title || rec.track_slug));
    rec.reasons.forEach(function (reason) {
      summary.appendChild(el("p", "quiz-reason", reason));
    });
    summary.appendChild(el("p", "quiz-goal",
      "Daily goal: " + rec.daily_goal_xp + " XP - level " + rec.level + "."));
    body.appendChild(summary);

    if (tracks && tracks.length > 1) {
      body.appendChild(el("p", "quiz-hint", "Prefer a different track?"));
      var list = el("div", "quiz-options");
      tracks.forEach(function (track) {
        var btn = el("button", "quiz-option", track.title);
        btn.type = "button";
        if (track.slug === current.track) btn.classList.add("is-chosen");
        btn.addEventListener("click", function () {
          current.track = track.slug;
          Array.prototype.forEach.call(list.children, function (other) {
            other.classList.remove("is-chosen");
          });
          btn.classList.add("is-chosen");
        });
        list.appendChild(btn);
      });
      body.appendChild(list);
    }

    setProgress(1, 1);
    backBtn.hidden = true;
    nextBtn.hidden = false;
    nextBtn.disabled = false;
    nextBtn.textContent = "Start learning";
  }

  function finish() {
    nextBtn.disabled = true;
    api(urls.complete, "POST", { track_slug: current.track })
      .then(function (result) { renderDone(result); })
      .catch(function (err) {
        showError(err.message === "catalog_missing"
          ? "The lesson catalog hasn't been seeded yet - run 'flask seed-catalog'."
          : err.message);
        nextBtn.disabled = false;
      });
  }

  function renderDone(result) {
    title.textContent = "You're all set";
    body.innerHTML = "";

    var lesson = result.next_lesson;
    body.appendChild(el("p", "quiz-summary-line",
      result.track.title + " - " + result.daily_goal_xp + " XP a day."));
    if (lesson) {
      body.appendChild(el("p", "quiz-summary-line",
        "First up: " + lesson.title + " (" + lesson.xp + " XP)"));
    }

    setProgress(1, 1);
    backBtn.hidden = true;
    nextBtn.hidden = false;
    nextBtn.disabled = false;
    nextBtn.textContent = "Go to Piko";
    current = { stage: "done" };
  }

  /* ---------- dispatch ---------- */

  function render(state) {
    showError("");
    if (state.stage === "questions") return renderStep(state);
    if (state.stage === "placement") return renderPlacement(state);
    if (state.stage === "review") {
      if (state.recommendation) {
        return renderReview(state.recommendation, null, null);
      }
      return loadPreview(null);
    }
    // Already finished this questionnaire in an earlier session.
    window.location.href = urls.home;
  }

  nextBtn.addEventListener("click", function () {
    if (!current) return;
    if (current.stage === "questions") return submitAnswer();
    if (current.stage === "placement") return submitPlacement();
    if (current.stage === "review") return finish();
    window.location.href = urls.home;
  });

  backBtn.addEventListener("click", function () {
    api(urls.back, "POST").then(render).catch(function (err) {
      showError(err.message);
    });
  });

  api(urls.state).then(render).catch(function (err) { showError(err.message); });
})();
