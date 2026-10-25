/* Runs the learner's code in their own tab instead of on the judge.
   Nothing here is scored: Submit still goes to the server, because a
   browser cannot be trusted to say whether a hidden test passed.

   Python loads on intent (9.6MB). C++ always runs here too, but it is
   fetched only when Run is actually pressed: clang and wasm-ld are
   themselves WebAssembly, about 26MB over the wire and ~100MB resident
   once unpacked. */
(function () {
  var ENGINES = {
    python: {
      url: null, module: false, optIn: false,
      compileMs: 0, runMs: 5000,
      worker: null, booting: null
    },
    cpp: {
      url: null, module: true, optIn: false,
      /* The first call downloads a toolchain, so the build phase gets a
         long leash. The program itself does not. */
      compileMs: 120000, runMs: 5000,
      worker: null, booting: null
    }
  };

  var OUTPUT_LIMIT = 256 * 1024;
  var OPT_IN_KEY = 'piko:browserrun:';
  var seq = 0;

  /* Languages cheap enough to fetch before the learner has asked for
     anything. C++ is not one of them: 26MB on hover is a hostile default
     on a phone or a metered connection, so it waits for a real Run. */
  var EAGER = { python: true };

  function warmable(lang) {
    if (!EAGER[lang]) { return false; }
    try {
      var link = navigator.connection;
      if (link && (link.saveData || /2g/.test(link.effectiveType || ''))) {
        return false;
      }
    } catch (err) { /* no Network Information API: assume it is fine */ }
    return true;
  }

  function engine(lang) {
    return Object.prototype.hasOwnProperty.call(ENGINES, lang)
      ? ENGINES[lang] : null;
  }

  function enabled(lang) {
    var eng = engine(lang);
    if (!eng || !eng.url) { return false; }
    if (!eng.optIn) { return true; }
    try {
      return localStorage.getItem(OPT_IN_KEY + lang) === '1';
    } catch (err) {
      return false;                  // private window: never opt in silently
    }
  }

  function setEnabled(lang, on) {
    try {
      if (on) { localStorage.setItem(OPT_IN_KEY + lang, '1'); }
      else { localStorage.removeItem(OPT_IN_KEY + lang); }
    } catch (err) { /* nothing we can do, and nothing that breaks */ }
    if (!on) { shutdown(lang); }
  }

  function shutdown(lang) {
    var eng = engine(lang);
    if (!eng || !eng.worker) { return; }
    eng.worker.terminate();
    eng.worker = null;
    eng.booting = null;
  }

  function spawn(eng) {
    eng.worker = eng.module
      ? new Worker(eng.url, { type: 'module' })
      : new Worker(eng.url);
    return eng.worker;
  }

  function preload(lang) {
    var eng = engine(lang);
    if (!eng || !eng.url) { return Promise.resolve(false); }
    if (eng.booting) { return eng.booting; }

    eng.booting = new Promise(function (resolve) {
      var w = spawn(eng);
      w.addEventListener('message', function onBoot(ev) {
        if (!ev.data) { return; }
        if (ev.data.type === 'ready') {
          w.removeEventListener('message', onBoot);
          resolve(true);
        } else if (ev.data.type === 'bootfail') {
          w.removeEventListener('message', onBoot);
          eng.worker = null;
          eng.booting = null;
          resolve(false);
        }
      });
      w.postMessage({ type: 'boot' });
    });
    return eng.booting;
  
  }

  function run(lang, source, stdin, onPhase) {
    var eng = engine(lang);
    if (!eng || !eng.url) {
      return Promise.resolve(null);
    }

    return new Promise(function (resolve) {
      if (!eng.worker) { preload(lang); }

      var id = ++seq;
      var timer = null;
      var w = eng.worker;

      function finish(payload) {
        clearTimeout(timer);
        w.removeEventListener('message', onMessage);
        resolve(payload);
      }

      /* An infinite loop in wasm ignores every timer inside the worker, so
         the clock lives out here and is enforced by killing it. */
      function arm(ms) {
        clearTimeout(timer);
        timer = setTimeout(function () {
          w.terminate();
          eng.worker = null;
          eng.booting = null;
          preload(lang);                   // ready for the next attempt
          finish({
            status: 'done', verdict: 'time_limit_exceeded',
            stdout: '', stderr: '', compile_output: '',
            time_ms: ms, error: '', where: 'browser'
          });
        }, ms);
      }

      function onMessage(ev) {
        var data = ev.data;
        if (!data || data.id !== id) { return; }

        /* C++ reports the build separately so the program's own time limit
           is not inflated by however long clang took. */
        if (data.type === 'compiled') {
          if (onPhase) { onPhase('running'); }
          arm(eng.runMs);
          return;
        }
        if (data.type !== 'done') { return; }

        var stdout = data.stdout || '';
        var status = data.status;
        if (stdout.length > OUTPUT_LIMIT) {
          stdout = stdout.slice(0, OUTPUT_LIMIT) + '\n...[output truncated]';
          status = 'output_limit_exceeded';
        }
        finish({
          status: 'done',
          verdict: status,
          stdout: stdout,
          stderr: data.stderr || '',
          compile_output: data.compile_output || '',
          time_ms: data.ms || 0,
          error: data.error || '',
          where: 'browser'
        });
      }

      w.addEventListener('message', onMessage);
      arm(eng.compileMs || eng.runMs);
      w.postMessage({ type: 'run', id: id, source: source, stdin: stdin || '' });
    });
  }

  window.PikoRun = {
    configure: function (lang, url) {
      var eng = engine(lang);
      if (eng) { eng.url = url; }
    },
    /* Known to this build and allowed by the learner. */
    supports: function (lang) { return !!window.Worker && enabled(lang); },
    /* This build has an engine for it, so Run will happen in the tab. */
    offers: function (lang) {
      var eng = engine(lang);
      return !!window.Worker && !!eng && !!eng.url;
    },
    /* Cheap enough to fetch before Run is pressed. */
    warmable: warmable,
    enabled: enabled,
    setEnabled: setEnabled,
    preload: preload,
    run: run
  };
})();
