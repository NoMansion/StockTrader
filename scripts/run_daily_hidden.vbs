' Launch the daily paper-trading run without a console window.
' Task Scheduler ("StockTrader Daily", 16:30 CT) calls this instead of cmd.exe directly, because
' a visible cmd window gets closed by accident (2026-11-09: the run died with STATUS_CONTROL_C_EXIT).
' Output is appended to data\run_daily.log; python runs unbuffered (-u) so the log shows progress.
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "E:\Coding\StockTrader"
sh.Run "cmd.exe /c ""echo ===== %DATE% %TIME% ===== >> data\run_daily.log && .venv\Scripts\python.exe -u scripts\run_daily.py >> data\run_daily.log 2>&1""", 0, False
