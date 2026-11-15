' 작업 스케줄러에서 호출하는 백그라운드 실행 스크립트
' cmd 창이 보이지 않게 update_data.py 를 실행한다.
Set fso = CreateObject("Scripting.FileSystemObject")
ScriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = ScriptDir
shell.Run "cmd /c python tools\update_data.py >> .tmp\update.log 2>&1", 0, False
