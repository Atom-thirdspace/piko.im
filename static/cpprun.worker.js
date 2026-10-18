import { compile } from 'https://cdn.jsdelivr.net/npm/browsercc@0.1.1/dist/index.js';
import {
  WASI, WASIProcExit, File, OpenFile, ConsoleStdout,
} from 'https://cdn.jsdelivr.net/npm/@bjorn3/browser_wasi_shim@0.4.2/dist/index.js';

const FLAGS = ['-O2', '-std=c++17', '-fno-exceptions'];
const OUTPUT_LIMIT = 256 * 1024;

const WARMUP = 'int main() { return 0; }';

async function build(source) {
  return compile({ source, fileName: 'main.cpp', flags: FLAGS });
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
    try {
      await build(WARMUP);
      self.postMessage({ type: 'ready' });
    } catch (err) {
      self.postMessage({ type: 'bootfail', error: String(err) });
    }
    return;
  }

  if (msg.type !== 'run') return;

  const started = performance.now();
  const ms = () => Math.round(performance.now() - started);

  try {
    const built = await build(msg.source);
    /* Tells the main thread to stop counting compile time against the
       program's own limit. */
    self.postMessage({ type: 'compiled', id: msg.id });

    if (!built.module) {
      var note = '';
      if (/exceptions disabled/i.test(built.compileOutput || '')) {
        note = '\n\n[Piko] The in-browser toolchain is built without C++ '
             + 'exceptions, so try/catch/throw will not compile here. '
             + 'Untick "Run C++ here" to use the judge, which supports them.';
      }
      self.postMessage({
        type: 'done', id: msg.id, status: 'compile_error',
        stdout: '', stderr: '',
        compile_output: (built.compileOutput || '') + note,
        ms: ms(),
      });
      return;
    }

    const result = await execute(built.module, msg.stdin);
    self.postMessage({
      type: 'done', id: msg.id,
      status: result.truncated ? 'output_limit_exceeded'
            : (result.code === 0 ? 'ok' : 'runtime_error'),
      stdout: result.out,
      stderr: result.code === 0 ? '' : ('exit status ' + result.code),
      /* Warnings are worth showing even when the build succeeded. */
      compile_output: built.compileOutput || '',
      ms: ms(),
    });
  } catch (err) {
    self.postMessage({
      type: 'done', id: msg.id, status: 'internal_error',
      stdout: '', stderr: '', compile_output: '',
      error: String(err), ms: ms(),
    });
  }
};
