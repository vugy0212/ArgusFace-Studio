' ==============================================================================
' ArgusFace Studio - Tiho pozadinsko pokretanje lokalnog API poslužitelja (Port 5055)
' Omogućuje 24/7 rad Docker Telegram Bota potpuno tiho u pozadini
' ==============================================================================
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strPath = fso.GetParentFolderName(WScript.ScriptFullName)

WshShell.CurrentDirectory = strPath

' Pronađi pythonw.exe (bez terminala)
pyw = "pythonw.exe"
If fso.FileExists(strPath & "\python\pythonw.exe") Then
    pyw = """" & strPath & "\python\pythonw.exe"""
ElseIf fso.FileExists(strPath & "\.venv\Scripts\pythonw.exe") Then
    pyw = """" & strPath & "\.venv\Scripts\pythonw.exe"""
End If

' Pokreni API poslužitelj u pozadini (0 = skriveni prozor)
WshShell.Run pyw & " -m src.api_server", 0, False
