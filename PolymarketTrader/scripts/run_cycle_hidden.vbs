' Launch one paper-trading cycle without a console window (same pattern as the stock trader's daily job:
' a visible cmd window gets closed by accident and kills the run).
' Output is appended to data\run_cycle.log; python runs unbuffered (-u) so the log shows progress.
' After the cycle, whatever happened to it (single "&"): the forecast log is exported, the observation log of the
' longshot rule takes its readings (no orders), and the status file is rewritten.
' The project folder is wherever this script lives (its parent folder), so the project can be moved or renamed.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
py = ".venv\Scripts\python.exe"
log = " >> data\run_cycle.log 2>&1"
sh.Run "cmd.exe /c ""echo ===== %DATE% %TIME% ===== >> data\run_cycle.log && " & py & " -u scripts\run_cycle.py" & log & _
       " & " & py & " scripts\export_forecasts.py" & log & _
       " & " & py & " -u scripts\shadow_longshot.py" & log & _
       " & " & py & " scripts\status.py --write > nul 2>&1""", 0, False
