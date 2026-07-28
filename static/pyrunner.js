/*
 * Python execution worker.
 *
 * Pyodide is CPython built to WebAssembly, so this is a real interpreter in
 * the browser - no server, no API key, and nothing leaves the machine. It runs
 * in a worker for two reasons: the page stays responsive while the ~10 MB
 * runtime downloads, and an infinite loop can be killed by terminating the
 * worker, which is impossible on the main thread.
 *
 * The runtime is fetched once and reused for every subsequent run.
 */
const PYODIDE_VERSION = 'v0.26.4';
const PYODIDE_URL = `https://cdn.jsdelivr.net/pyodide/${PYODIDE_VERSION}/full/`;

let bootPromise = null;

function boot() {
    if (!bootPromise) {
        bootPromise = (async () => {
            self.importScripts(PYODIDE_URL + 'pyodide.js');
            self.postMessage({ type: 'status', message: 'downloading Python…' });
            const pyodide = await self.loadPyodide({ indexURL: PYODIDE_URL });
            self.postMessage({ type: 'status', message: 'Python ready' });
            return pyodide;
        })().catch((err) => {
            // Let the next attempt retry rather than caching the failure.
            bootPromise = null;
            throw err;
        });
    }
    return bootPromise;
}

self.onmessage = async (event) => {
    const code = event.data;
    const lines = [];

    try {
        const pyodide = await boot();

        // Capture both streams so print() and tracebacks land in the panel.
        pyodide.setStdout({ batched: (s) => lines.push(s) });
        pyodide.setStderr({ batched: (s) => lines.push(s) });

        await pyodide.runPythonAsync(code);
        self.postMessage({ type: 'result', ok: true, logs: lines });
    } catch (err) {
        self.postMessage({
            type: 'result',
            ok: false,
            logs: lines,
            error: String(err && err.message ? err.message : err),
        });
    }
};
