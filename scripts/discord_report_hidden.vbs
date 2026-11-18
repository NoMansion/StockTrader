' Post the daily Discord report without a console window (Task Scheduler "StockTrader Discord Report",
' weekdays 6:20 pm CT, after the daily job has sent its orders). --wait lets a still-running daily job finish first.
' Output is appended to data\discord_report.log.
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "E:\Coding\StockTrader"
sh.Run "cmd.exe /c "".venv\Scripts\python.exe -u scripts\discord_report.py --wait >> data\discord_report.log 2>&1""", 0, False
