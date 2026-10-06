Option Explicit
Dim shell, files, folder, python, script
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
python = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Python\bin\pythonw.exe"
If Not files.FileExists(python) Then python = "pythonw.exe"
script = folder & "\App\dashcam_gui.py"
If Not files.FileExists(script) Then script = folder & "\dashcam_gui.py"
shell.Run Chr(34) & python & Chr(34) & " -B " & Chr(34) & script & Chr(34), 0, False
