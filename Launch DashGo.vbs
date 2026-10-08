Option Explicit
Dim shell, files, folder, python, script
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
python = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Python\bin\pythonw.exe"
If Not files.FileExists(python) Then python = "pythonw.exe"
script = folder & "\App\dashcam_qt.py"
If Not files.FileExists(script) Then script = folder & "\dashcam_qt.py"
' pythonw has no console; the Qt main window must be allowed to show.
shell.Run Chr(34) & python & Chr(34) & " -B " & Chr(34) & script & Chr(34), 1, False
