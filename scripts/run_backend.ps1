$ErrorActionPreference = 'Stop'

& .\.venv\Scripts\Activate.ps1
$reloadArgs = @()
if ($env:UVICORN_RELOAD -eq '1') {
    $reloadArgs = @('--reload')
}
& .\.venv\Scripts\python.exe -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000 @reloadArgs
