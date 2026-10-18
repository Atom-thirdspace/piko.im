const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v0.29.0/full/';

let pyodide = null;
let runner = null;

const HARNESS = `
import io, sys, traceback

def _piko_run(source, stdin_text):
    out, err = io.StringIO(), io.StringIO()
    saved = (sys.stdin, sys.stdout, sys.stderr)
    sys.stdin = io.StringIO(stdin_text or "")
    sys.stdout, sys.stderr = out, err
    status = "ok"
    try:
        exec(compile(source, "main.py", "exec"), {"__name__": "__main__"})
    except SystemExit as exc:
        if exc.code not in (0, None):
            status = "runtime_error"
            err.write("SystemExit: %s\\n" % exc.code)
    except MemoryError:
        status = "memory_limit_exceeded"
        err.write("MemoryError\\n")
    except BaseException as exc:
        status = "runtime_error"
        # Drop our own exec frame so line numbers point at their code.
        tb = exc.__traceback__.tb_next if exc.__traceback__ else None
        err.write("".join(traceback.format_exception(type(exc), exc, tb)))
    finally:
        sys.stdin, sys.stdout, sys.stderr = saved
    return [status, out.getvalue(), err.getvalue()]
`;

async function boot() {
    if (pyodide) return;
    importScripts(PYODIDE + 'pyodide.js');
    pyodide = await loadPyodide({ indexURL: PYODIDE });
    pyodide.runPython(HARNESS);
    runner = pyodide.globals.get('_piko_run');
}

self.onmessage = async (event) => {
    const msg = event.data || {};
    if (msg.type === 'boot') {
    try {
      await boot();
      self.postMessage({ type: 'ready' });
    } catch (err) {
      self.postMessage({ type: 'bootfail', error: String(err) });
    }
    return;
  }

  if (msg.type !== 'run') return;

  const started = performance.now();
  try{
    await boot();
    const result = runner(msg.source, msg.stdin)
    const [status, stdout, stderr] = result.toJs();
    result.destroy()
    self.postMessage({
      type: 'done', id: msg.id, status: status,
      stdout: stdout, stderr: stderr,
      ms: Math.round(performance.now() - started),
    });
  } catch (err) {
     self.postMessage({
      type: 'done', id: msg.id, status: 'internal_error',
      stdout: '', stderr: '', error: String(err),
      ms: Math.round(performance.now() - started),
    });
  }
};
