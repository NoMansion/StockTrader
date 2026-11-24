' Launch the morning opening-auction fallback without a console window.
' Task Scheduler ("StockTrader Open Fallback", weekdays every 3 min 8:32-8:50 am CT) calls this; output goes to data\open_fallback.log.
' The project folder is wherever this script lives (its parent folder), so it runs from any drive.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
sh.Run "cmd.exe /c "".venv\Scripts\python.exe -u scripts\open_fallback.py >> data\open_fallback.log 2>&1""", 0, False
