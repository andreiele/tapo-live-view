Option Explicit

Dim shell, fso, scriptDir, extraArgs, venvPyw, ok

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = scriptDir

extraArgs = ""
If WScript.Arguments.Count > 0 Then
    extraArgs = " " & WScript.Arguments(0)
End If

venvPyw = scriptDir & "\.venv\Scripts\pythonw.exe"
ok = False

If fso.FileExists(venvPyw) Then
    On Error Resume Next
    shell.Run """" & venvPyw & """ """ & scriptDir & "\wizard.py""" & extraArgs, 0, False
    If Err.Number = 0 Then ok = True
    On Error Goto 0
End If

If Not ok Then
    On Error Resume Next
    shell.Run "py -3w """ & scriptDir & "\wizard.py""" & extraArgs, 0, False
    If Err.Number = 0 Then ok = True
    On Error Goto 0
End If

If Not ok Then
    On Error Resume Next
    shell.Run "pythonw """ & scriptDir & "\wizard.py""" & extraArgs, 0, False
    If Err.Number = 0 Then ok = True
    On Error Goto 0
End If

If Not ok Then
    MsgBox "Python was not found." & vbCrLf & vbCrLf & _
        "Install Python 3.9 or newer from python.org and tick ""Add python.exe to PATH"", then try again.", _
        vbCritical, "Tapo Live View"
End If
