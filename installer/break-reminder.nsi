; BreakReminder — NSIS installer script
; -----------------------------------------------------------------------------
; Wraps the PyInstaller one-folder bundle at dist\BreakReminder\ into a
; Windows installer. Produces installer\BreakReminder-Setup-<version>.exe.
;
; Build with:  makensis installer\break-reminder.nsi
; Requires:    NSIS 3.x on PATH (preinstalled on GitHub's windows-latest runner)
;
; Honors PRD constraints:
;   FR-001: downloadable installer for public distribution
;   FR-002: uninstall removes binaries but preserves user data
;           (we never touch %APPDATA%\BreakReminder during uninstall)
;   FR-003: autostart is opt-in and lives in settings, NOT in the installer
;           (no Run-key registration here on purpose)

!define APP_NAME      "BreakReminder"
!define APP_VERSION   "0.7.0"
!define APP_PUBLISHER "BreakReminder"
!define APP_EXE       "BreakReminder.exe"
!define APP_REGKEY    "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"

Name           "${APP_NAME}"
; OutFile is resolved relative to THIS script's directory (installer\),
; so we deliberately do NOT prefix with "installer\" — that would land
; the artefact at installer\installer\BreakReminder-Setup-X.Y.Z.exe.
OutFile        "BreakReminder-Setup-${APP_VERSION}.exe"
InstallDir     "$LOCALAPPDATA\Programs\${APP_NAME}"
InstallDirRegKey HKCU "Software\${APP_NAME}" "InstallDir"
RequestExecutionLevel user        ; per-user install; no UAC prompt
ShowInstDetails   show
ShowUninstDetails show

!include "MUI2.nsh"

!define MUI_ABORTWARNING
; !define MUI_ICON   "..\resources\app.ico"   ; uncomment when icon ships
; !define MUI_UNICON "..\resources\app.ico"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; ---------------------------------------------------------------------------
; Install
; ---------------------------------------------------------------------------

Section "Install"
  SetOutPath "$INSTDIR"
  ; PyInstaller --windowed --name BreakReminder produces dist\BreakReminder
  ; (no trailing backslash on the comment: NSIS treats a comment-line
  ;  ending in "\" as a line continuation and would silently swallow the
  ;  next directive — warning 6050.)
  File /r "..\dist\BreakReminder\*.*"

  ; Start Menu shortcut
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortCut  "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
  CreateShortCut  "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk"   "$INSTDIR\Uninstall.exe"

  ; Uninstaller
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  ; Add/Remove Programs entry
  WriteRegStr HKCU "${APP_REGKEY}" "DisplayName"     "${APP_NAME}"
  WriteRegStr HKCU "${APP_REGKEY}" "DisplayVersion"  "${APP_VERSION}"
  WriteRegStr HKCU "${APP_REGKEY}" "Publisher"       "${APP_PUBLISHER}"
  WriteRegStr HKCU "${APP_REGKEY}" "DisplayIcon"     "$INSTDIR\${APP_EXE}"
  WriteRegStr HKCU "${APP_REGKEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${APP_REGKEY}" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKCU "${APP_REGKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${APP_REGKEY}" "NoRepair" 1

  ; Remember install dir for upgrades
  WriteRegStr HKCU "Software\${APP_NAME}" "InstallDir" "$INSTDIR"
SectionEnd

; ---------------------------------------------------------------------------
; Uninstall
; ---------------------------------------------------------------------------
;
; FR-002: preserve user data. We deliberately do NOT touch
; %APPDATA%\BreakReminder — that holds settings, custom reminders, and the
; event log. A user who wants a true wipe can delete the folder manually.

Section "Uninstall"
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk"
  RMDir  "$SMPROGRAMS\${APP_NAME}"

  RMDir /r "$INSTDIR"

  DeleteRegKey HKCU "${APP_REGKEY}"
  DeleteRegKey HKCU "Software\${APP_NAME}"
SectionEnd
