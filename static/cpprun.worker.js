import { compile } from 'https://cdn.jsdelivr.net/npm/browsercc@0.1.1/dist/index.js';
import {
  WASI, WASIProcExit, File, OpenFile, ConsoleStdout,
} from 'https://cdn.jsdelivr.net/npm/@bjorn3/browser_wasi_shim@0.4.2/dist/index.js';

/* Run is not scored and is not timed against the judge's limit, so how
   fast the generated code is does not matter here - only how fast clang
   gets there. Submit goes to the judge, which still builds with -O2. */
const FLAGS = ['-O0', '-std=c++17', '-fno-exceptions'];
const OUTPUT_LIMIT = 256 * 1024;

const WARMUP = 'int main() { return 0; }';
const PHASE = {};

/* Compiled modules, keyed by source. Running the same code again against
   different input is the common case and should cost nothing. */
const MODULE_CACHE = new Map();
const CACHE_MAX = 8;

async function build(source) {
  return compile({ source, fileName: 'main.cpp', flags: FLAGS });
}

async function digest(text) {
  const bytes = new TextEncoder().encode(text);
  const hash = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(hash).slice(0, 16))
    .map((b) => b.toString(16).padStart(2, '0')).join('');
}

async function buildCached(source) {
  let key = null;
  try {
    key = await digest(source);
  } catch (err) {
    /* No crypto.subtle without a secure origin. Compile every time. */
    return Object.assign({}, await build(source), { cached: false });
  }

  const hit = MODULE_CACHE.get(key);
  if (hit) {
    MODULE_CACHE.delete(key);          // reinsert so LRU order holds
    MODULE_CACHE.set(key, hit);
    return Object.assign({}, hit, { cached: true });
  }

  const built = await build(source);
  if (built.module) {
    MODULE_CACHE.set(key, built);
    if (MODULE_CACHE.size > CACHE_MAX) {
      MODULE_CACHE.delete(MODULE_CACHE.keys().next().value);
    }
  }
  return Object.assign({}, built, { cached: false });
}

function mark(name){
  PHASE[name] = performance.now();
}

function phases(){
  const out = {};
  const keys = Object.keys(PHASE);
  for (let i = 1; i < keys.length; i++) {
    out[keys[i]] = Math.round(PHASE[keys[i]] - PHASE[keys[i - 1]]);
  }
  return out;
}

function execute(module, stdinText) {
  let out = '';
  let truncated = false;

  const sink = (bytes) => {
    if (truncated) return;
    out += new TextDecoder().decode(bytes);
    if (out.length > OUTPUT_LIMIT) {
      out = out.slice(0, OUTPUT_LIMIT) + '\n...[output truncated]';
      truncated = true;
    }
  };

  /* The raw constructor hands us bytes, which is what sink decodes.
     lineBuffered hands over decoded strings instead, and holds back a
     final line that has no newline on it. */
  const stdout = new ConsoleStdout(sink);
  const stderr = new ConsoleStdout(sink);
  const stdin = new OpenFile(
    new File(new TextEncoder().encode(stdinText || '')));

  const wasi = new WASI([], [], [stdin, stdout, stderr]);
  return WebAssembly.instantiate(module, {
    wasi_snapshot_preview1: wasi.wasiImport,
  }).then((instance) => {
    let code = 0;
    try {
      wasi.start(instance);
    } catch (err) {
      /* wasi.start throws WASIProcExit even on a clean exit(0). */
      if (err instanceof WASIProcExit) {
        code = err.code;
      } else {
        throw err;
      }
    }
    return { out, code, truncated };
  });
}

self.onmessage = async (event) => {
  const msg = event.data || {};

  if (msg.type === 'boot') {
    mark('boot');
    try {
      await build(WARMUP);
      mark('toolchain');
      self.postMessage({ type: 'ready', phases: phases() });
    } catch (err) {
      self.postMessage({ type: 'bootfail', error: String(err) });
    }
    return;
  }

  if (msg.type !== 'run') return;

  const started = performance.now();
  const ms = () => Math.round(performance.now() - started);

  try {
    mark('run_start');
    const built = await buildCached(msg.source);
    mark('compiled');
    /* Tells the main thread to stop counting compile time against the
       program's own limit. */
    self.postMessage({ type: 'compiled', id: msg.id, cached: built.cached });

    if (!built.module) {
      var note = '';
      if (/exceptions disabled/i.test(built.compileOutput || '')) {
        note = '\n\n[Piko] C++ runs in your browser here, and this toolchain '
             + 'is built without exceptions, so try/catch/throw will not '
             + 'compile. Submit still uses the judge, which supports them.';
      }
      self.postMessage({
        type: 'done', id: msg.id, status: 'compile_error',
        stdout: '', stderr: '',
        compile_output: (built.compileOutput || '') + note,
        ms: ms(), phases: phases(),
      });
      return;
    }

    const result = await execute(built.module, msg.stdin);
    mark('ran');
    self.postMessage({
      type: 'done', id: msg.id,
      status: result.truncated ? 'output_limit_exceeded'
            : (result.code === 0 ? 'ok' : 'runtime_error'),
      stdout: result.out,
      stderr: result.code === 0 ? '' : ('exit status ' + result.code),
      /* Warnings are worth showing even when the build succeeded. */
      compile_output: built.compileOutput || '',
      ms: ms(), cached: built.cached, phases: phases(),
    });
  } catch (err) {
    self.postMessage({
      type: 'done', id: msg.id, status: 'internal_error',
      stdout: '', stderr: '', compile_output: '',
      error: String(err), ms: ms(),
    });
  }
};
