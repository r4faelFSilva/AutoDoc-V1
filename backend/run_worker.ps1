# Worker arq — só é necessário no modo Redis (REDIS_URL configurado no .env).
# No modo fallback (sem Redis) os jobs rodam dentro da própria API.
Set-Location $PSScriptRoot
if (Test-Path ".\.venv\Scripts\python.exe") {
    & ".\.venv\Scripts\python.exe" -m arq app.jobs.worker.WorkerSettings
} else {
    python -m arq app.jobs.worker.WorkerSettings
}
