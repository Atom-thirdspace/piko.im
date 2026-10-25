const OUTPUT_LIMIT = 256 * 1024;

function sandbox(source, stdinText) {
  let out = '';
  let truncated = false;
  let exitCode = 0;

  function write(text) {
    if (truncated) return;
    out += text;
    if (out.length > OUTPUT_LIMIT) {
      out = out.slice(0, OUTPUT_LIMIT) + '\n...[output truncated]';
      truncated = true;
    }
  }

  const format = (args) => args.map((a) => {
    if (typeof a === 'string') return a;
    try { return JSON.stringify(a); } catch (err) { return String(a); }
  }).join(' ');

  const console_ = {
    log: (...a) => write(format(a) + '\n'),
    info: (...a) => write(format(a) + '\n'),
    warn: (...a) => write(format(a) + '\n'),
    error: (...a) => write(format(a) + '\n'),
    debug: (...a) => write(format(a) + '\n'),
  };

  class Exit extends Error {
    constructor(code) { super('exit'); this.code = code; }
  }

  const process_ = {
    argv: ['node', 'main.js'],
    env: {},
    platform: 'browser',
    exit(code) { throw new Exit(code || 0); },
    stdout: { write(text) { write(String(text)); return true; } },
    stderr: { write(text) { write(String(text)); return true; } },
  };

  function require_(name) {
    const clean = String(name).replace(/^node:/, '');
    if (clean === 'fs') {
      return {
        readFileSync(target) {
          if (target === 0 || target === '/dev/stdin') { return stdinText; }
          throw new Error('Only stdin can be read here.');
        },
      };
    }
    if (clean === 'readline') {
      throw new Error("'readline' is not available in the browser runner. "
                    + "Read stdin in one go with "
                    + "require('fs').readFileSync(0, 'utf8').");
    }
    throw new Error("Cannot require '" + name + "' here.");
  }

  try {
    const run = new Function('console', 'process', 'require', 'module',
                             'exports', '"use strict";\n' + source);
    const mod = { exports: {} };
    run(console_, process_, require_, mod, mod.exports);
  } catch (err) {
    if (err instanceof Exit) {
      exitCode = err.code;
    } else {
      write('\n' + (err && err.stack ? err.stack : String(err)) + '\n');
      exitCode = 1;
    }
  }

  return { out, code: exitCode, truncated };
}

self.onmessage = (event) => {
  const msg = event.data || {};

  if (msg.type === 'boot') {
    self.postMessage({ type: 'ready' });      // nothing to load
    return;
  }
  if (msg.type !== 'run') return;

  const started = performance.now();
  try {
    const result = sandbox(msg.source, msg.stdin || '');
    self.postMessage({
      type: 'done', id: msg.id,
      status: result.truncated ? 'output_limit_exceeded'
            : (result.code === 0 ? 'ok' : 'runtime_error'),
      stdout: result.out,
      stderr: result.code === 0 ? '' : ('exit status ' + result.code),
      compile_output: '',
      ms: Math.round(performance.now() - started),
    });
  } catch (err) {
    self.postMessage({
      type: 'done', id: msg.id, status: 'internal_error',
      stdout: '', stderr: '', compile_output: '',
      error: String(err), ms: Math.round(performance.now() - started),
    });
  }
};
