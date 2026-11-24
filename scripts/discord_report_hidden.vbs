' Post the daily Discord report without a console window (Task Scheduler "StockTrader Discord Report",
' weekdays 6:20 pm CT, after the daily job has sent its orders). --wait lets a still-running daily job finish first.
' Output is appended to data\discord_report.log.
' The project folder is wherever this script lives (its parent folder), so it runs from any drive.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
sh.Run "cmd.exe /c "".venv\Scripts\python.exe -u scripts\discord_report.py --wait >> data\discord_report.log 2>&1""", 0, False
