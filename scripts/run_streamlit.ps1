$ErrorActionPreference = 'Stop'

& .\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "$PWD;$env:PYTHONPATH"
$env:STREAMLIT_SERVER_FILE_WATCHER_TYPE = "none"
$env:STREAMLIT_SERVER_RUN_ON_SAVE = "false"
& .\.venv\Scripts\python.exe -m streamlit run app\streamlit_app.py
