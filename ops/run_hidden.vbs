' Runs any command with NO visible window and waits for it; the exit code is passed through to Task Scheduler.
' Usage (Task Scheduler action):
'   wscript.exe //B //Nologo "<path>\run_hidden.vbs" "<path>\program.exe" arg1 "arg with spaces" ...
' Console programs started this way get a hidden console that child processes (ffmpeg, node, powershell)
' inherit, so nothing pops up or steals focus from games / full-screen apps.
Option Explicit
Dim sh, cmd, i, a
Set sh = CreateObject("WScript.Shell")
cmd = ""
For i = 0 To WScript.Arguments.Count - 1
    a = WScript.Arguments(i)
    If a = "" Or InStr(a, " ") > 0 Or InStr(a, Chr(9)) > 0 Then a = Chr(34) & a & Chr(34)
    cmd = cmd & a & " "
Next
If Len(cmd) = 0 Then WScript.Quit 2
WScript.Quit sh.Run(Trim(cmd), 0, True)
