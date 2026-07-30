@echo off
setlocal
set "JAVA_HOME=C:\Program Files\Android\Android Studio\jbr"
call "%~dp0gradlew.bat" clean assembleRelease
if errorlevel 1 exit /b %errorlevel%
copy /y "%~dp0app\build\outputs\apk\release\app-release.apk" "%~dp0release\PreinstallManager.apk" >nul
echo Built: %~dp0release\PreinstallManager.apk
