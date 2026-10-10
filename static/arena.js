(function () {
    "use strict";

    var root = document.querySelector('.arena');
    if (!root) { return; }

    var d = root.dataset;
    var promptEl = root.querySelector('[data-prompt]');
    var choicesEl = root.querySelector('[data-choices]');
    var shortEl = root.querySelector('[data-short]');
    var inputEl = root.querySelector('[data-input]');
    var verdictEl = root.querySelector('[data-verdict]');
    var timerEl = root.querySelector('[data-timer]');
    var comboEl = root.querySelector('[data-combo]');
    var posEl = root.querySelector('[data-position]');
    var diffEl = root.querySelector('[data-difficulty]');

    var bossBar = root.querySelector('[data-boss-bar]');
    var playerBar = root.querySelector('[data-player-bar]');
    var bossHp = root.querySelector('[data-boss-hp]');
    var playerHp = root.querySelector('[data-player-hp]');
    var sigil = root.querySelector('[data-sigil]');

    var current = null;
    var ticking = null;
    var locked = false;

    function token() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.content : '';
    }

    function post(url, body) {
        return fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': token()
            },
            body: JSON.stringify(body)
        });
    }

    function paint(state) {
        bossBar.style.width = (100 * state.boss_hp / state.boss_hp_max) + '%';
        playerBar.style.width =
            (100 * state.player_hp / state.player_hp_max) + '%';
        bossHp.textContent = state.boss_hp;
        playerHp.textContent = state.player_hp;

        comboEl.hidden = state.combo < 2;
        comboEl.textContent = state.combo + ' hit combo';
    }

    function flash(cls) {
        root.classList.remove('is-hitting', 'is-hurt');
        // Reading offsetWidth restarts the animation when the same class is
        // reapplied two answers in a row.
        void root.offsetWidth;
        root.classList.add(cls);
        setTimeout(function () { root.classList.remove(cls); }, 420);
    }

    function stopClock() {
        if (ticking) {
            clearInterval(ticking);
            ticking = null;
        }
    }

    // The bar is a convenience. The deadline that counts is the server's, so
    // a paused tab or a fiddled clock buys nothing.
    function startClock(seconds, window_) {
        stopClock();
        var endsAt = Date.now() + seconds * 1000;
        ticking = setInterval(function () {
            var left = Math.max(0, endsAt - Date.now()) / 1000;
            timerEl.style.width = (100 * left / window_) + '%';
            timerEl.classList.toggle('is-low', left < window_ * 0.25);
            if (left <= 0) {
                stopClock();
                submit('', null);
            }
        }, 100);
    }

    function renderQuestion(q) {
        current = q;
        locked = false;
        verdictEl.hidden = true;
        verdictEl.textContent = '';
        promptEl.textContent = q.prompt;
        posEl.textContent = 'Q' + q.position;
        diffEl.textContent = q.difficulty;
        diffEl.className = 'pill pill-' + q.difficulty;

        choicesEl.textContent = '';
        if (q.kind === 'choice') {
            shortEl.hidden = true;
            choicesEl.hidden = false;
            q.choices.forEach(function (c) {
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'arena__choice';
                btn.textContent = c.text;
                btn.addEventListener('click', function () {
                    submit(null, c.key);
                });
                choicesEl.appendChild(btn);
            });
        } else {
            choicesEl.hidden = true;
            shortEl.hidden = false;
            inputEl.value = '';
            inputEl.focus();
        }

        startClock(q.seconds_left, q.window);
    }

    function renderVerdict(data) {
        verdictEl.hidden = false;
        verdictEl.className = 'arena__verdict '
            + (data.correct ? 'is-hit' : 'is-miss');

        var line = document.createElement('p');
        line.className = 'arena__verdict-line';
        if (data.correct) {
            line.textContent = '⚔ ' + data.damage + ' damage';
        } else if (data.timed_out) {
            line.textContent = 'Too slow. The answer was ' + data.answer;
        } else {
            line.textContent = 'Missed. The answer was ' + data.answer;
        }
        verdictEl.appendChild(line);

        if (data.explain_html) {
            var why = document.createElement('div');
            why.className = 'arena__why';
            why.innerHTML = data.explain_html;
            verdictEl.appendChild(why);
        }
    }

    function lockChoices() {
        choicesEl.querySelectorAll('.arena__choice').forEach(function (b) {
            b.disabled = true;
        });
        inputEl.disabled = true;
    }

    function unlockInput() {
        inputEl.disabled = false;
    }

    async function submit(text, choiceKey) {
        if (locked || !current) { return; }
        locked = true;
        stopClock();
        lockChoices();

        try {
            var res = await post(d.answerUrl, {
                question_id: current.question_id,
                answer: text,
                choice: choiceKey
            });
            var data = await res.json();
            if (!res.ok) {
                locked = false;
                unlockInput();
                return;
            }

            if (data.stale) { next(); return; }

            paint(data);
            renderVerdict(data);
            flash(data.correct ? 'is-hitting' : 'is-hurt');

            // Long enough to read why, short enough to keep the pressure on.
            setTimeout(function () {
                if (data.done) {
                    location.href = d.resultUrl;
                } else {
                    next();
                }
            }, data.correct ? 900 : 2400);
        } catch (err) {
            locked = false;
            unlockInput();
        }
    }

    async function next() {
        unlockInput();
        try {
            var res = await fetch(d.questionUrl);
            var data = await res.json();
            paint(data);
            if (data.done) {
                location.href = d.resultUrl;
                return;
            }
            renderQuestion(data.question);
        } catch (err) {
            promptEl.textContent = 'Lost the connection. Reload to carry on.';
        }
    }

    shortEl.addEventListener('submit', function (ev) {
        ev.preventDefault();
        submit(inputEl.value, null);
    });

    // 1-4 picks a multiple choice option without reaching for the mouse.
    document.addEventListener('keydown', function (ev) {
        if (!current || current.kind !== 'choice' || locked) { return; }
        var n = parseInt(ev.key, 10);
        if (n >= 1 && n <= current.choices.length) {
            submit(null, current.choices[n - 1].key);
        }
    });

    if (sigil) { sigil.classList.add('is-alive'); }
    next();
}());
