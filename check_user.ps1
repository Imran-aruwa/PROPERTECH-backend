# PowerShell script to run Python user check
$pythonExe = "$PSScriptRoot\venv\Scripts\python.exe"
$pythonScript = "$PSScriptRoot\check_user_temp.py"

& $pythonExe $pythonScript
