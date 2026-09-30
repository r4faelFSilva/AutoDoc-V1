# Rode a partir da pasta backend. Só observa ./app — evita loop de reload por causa de .venv/
Set-Location $PSScriptRoot
if (Test-Path ".\.venv\Scripts\python.exe") {
    & ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000
} else {
    python -m uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000
}
