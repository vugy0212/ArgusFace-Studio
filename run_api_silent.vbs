' ==============================================================================
' ArgusFace Studio - Tiho pozadinsko pokretanje lokalnog API poslužitelja (Port 5055)
' Omogućuje 24/7 rad Docker Telegram Bota potpuno tiho u pozadini
' ==============================================================================
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strPath = fso.GetParentFolderName(WScript.ScriptFullName)

WshShell.CurrentDirectory = strPath

' Pronađi python.exe (pokrenut sa stilom prozora 0 = potpuno skriven u pozadini)
py = "python.exe"
If fso.FileExists(strPath & "\.venv\Scripts\python.exe") Then
    py = strPath & "\.venv\Scripts\python.exe"
ElseIf fso.FileExists(strPath & "\python\python.exe") Then
    py = strPath & "\python\python.exe"
End If

' Pokreni API poslužitelj u pozadini (0 = potpuno skriven prozor)
WshShell.Run """" & py & """ -m src.api_server", 0, False
