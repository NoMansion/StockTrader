' Launch the morning opening-auction fallback without a console window.
' Task Scheduler ("StockTrader Open Fallback", weekdays 8:35 am CT) calls this; output goes to data\open_fallback.log.
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "E:\Coding\StockTrader"
sh.Run "cmd.exe /c "".venv\Scripts\python.exe -u scripts\open_fallback.py >> data\open_fallback.log 2>&1""", 0, False
