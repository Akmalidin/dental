' SADAF — запуск оффлайн-режима иконкой (без чёрного окна консоли).
' Сделайте ярлык этого файла на рабочий стол и поставьте иконку (icon-512.png / .ico).
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")
sh.CurrentDirectory = fso.GetParentFolderName(WScript.ScriptFullName)
' запускаем локальный сервер скрыто (0 = без окна)
sh.Run "cmd /c offline_start.bat", 0, False
' даём серверу подняться и открываем браузер
WScript.Sleep 3500
sh.Run "http://127.0.0.1:8765/"
