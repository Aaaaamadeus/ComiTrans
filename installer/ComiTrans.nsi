; -*- coding: utf-8 -*-
; Standard NSIS wizard. No custom drawing, animation, or bootstrapper.
Unicode True
!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "WordFunc.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"

Name "ComiTrans ${VERSION}"
OutFile "${OUTPUT}"
InstallDir "$PROGRAMFILES64\ComiTrans"
RequestExecutionLevel admin
!ifdef GENERATE_UNINSTALLER
; NSIS exports the final uninstaller at compile time for optional external signing.
!uninstfinalize 'cmd /D /C copy /Y "%1" "${UNINSTALLER_OUT}" >nul' = 0
!endif
ManifestDPIAware True
SetCompressor /SOLID lzma
ShowInstDetails show
ShowUninstDetails show
VIProductVersion "${VERSION}.0"
VIAddVersionKey /LANG=1033 "ProductName" "ComiTrans"
VIAddVersionKey /LANG=1033 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "FileVersion" "${VERSION}.0"
VIAddVersionKey /LANG=1033 "FileDescription" "ComiTrans Setup"
VIAddVersionKey /LANG=1033 "LegalCopyright" "ComiTrans contributors"

!define INSTALL_KEY "Software\ComiTrans\Installer"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\ComiTrans"
!define SERVICE_NAME "ComiTransReleaseCheck"
!define SERVICE_DIR "$PROGRAMFILES64\ComiTrans Release Service"
!define MUI_ICON "${ICON}"
!define MUI_UNICON "${ICON}"
!define MUI_ABORTWARNING
!ifndef GENERATE_UNINSTALLER
!insertmacro MUI_PAGE_WELCOME
!define MUI_DIRECTORYPAGE_TEXT_TOP "$(DirectoryHelp)"
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE VerifyDirectory
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!else
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH
!endif
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "TradChinese"
!insertmacro MUI_LANGUAGE "Japanese"
!include "${LOCALIZATION}"

Var Parameters
!ifndef GENERATE_UNINSTALLER
Var PreviousDirectory
!endif
Var LogFile
Var LogHandle
Var SetupMutex

!macro Trace TEXT
  DetailPrint "${TEXT}"
  FileOpen $LogHandle $LogFile a
  FileSeek $LogHandle 0 END
  FileWriteUTF16LE $LogHandle "${TEXT}$\r$\n"
  FileClose $LogHandle
!macroend

!macro Fail STRING
  !insertmacro Trace "ERROR: ${STRING}"
  MessageBox MB_OK|MB_ICONSTOP "${STRING}" /SD IDOK
  SetErrorLevel 2
  Abort
!macroend

; Compile the same initialization and service-stop code into both programs.
!macro CommonFunctions PREFIX
Function ${PREFIX}Initialize
  SetRegView 64
  SetShellVarContext all
  ${GetParameters} $Parameters
  ClearErrors
  ${GetOptions} $Parameters "/quiet" $0
  ${IfNot} ${Errors}
    SetSilent silent
  ${EndIf}
  StrCpy $LogFile "$TEMP\ComiTrans-install.log"
  ${GetOptions} $Parameters "/log " $0
  ${If} $0 != ""
    StrCpy $LogFile $0
  ${EndIf}
  ${GetOptions} $Parameters "/LOG=" $0
  ${If} $0 != ""
    StrCpy $LogFile $0
  ${EndIf}
  ${GetOptions} $Parameters "/LANG=" $0
  ${If} $0 != ""
    StrCpy $LANGUAGE $0
  ${EndIf}
  System::Call 'kernel32::CreateMutexW(p 0, i 0, w "Global\ComiTransSetup") p.s ?e'
  Pop $0
  Pop $SetupMutex
  ${If} $0 = 183
  ${OrIf} $SetupMutex = 0
    !insertmacro Fail "$(AlreadyRunning)"
  ${EndIf}
FunctionEnd

Function ${PREFIX}CheckApplicationClosed
  IfFileExists "$INSTDIR\ComiTrans.exe" 0 done
  System::Call 'kernel32::CreateFileW(w "$INSTDIR\ComiTrans.exe", i 0x40000000, i 7, p 0, i 3, i 0x80, p 0) p.r0'
  ${If} $0 = -1
    !insertmacro Fail "$(CloseApplication)"
  ${EndIf}
  System::Call 'kernel32::CloseHandle(p r0)'
  done:
FunctionEnd

Function ${PREFIX}StopReleaseService
  System::Call 'advapi32::OpenSCManagerW(p 0, p 0, i 1) p.r0'
  ${If} $0 = 0
    !insertmacro Fail "$(ServiceError)"
  ${EndIf}
  System::Call 'advapi32::OpenServiceW(p r0, w "${SERVICE_NAME}", i 0x24) p.r1 ?e'
  Pop $2
  System::Call 'advapi32::CloseServiceHandle(p r0)'
  ${If} $1 = 0
    ${If} $2 = 1060
      Return
    ${EndIf}
    !insertmacro Fail "$(ServiceError)"
  ${EndIf}
  System::Alloc 36
  Pop $2
  System::Call 'advapi32::ControlService(p r1, i 1, p r2)'
  StrCpy $5 0
  ${Do}
    System::Call 'advapi32::QueryServiceStatus(p r1, p r2) i.r3'
    ${If} $3 = 0
      StrCpy $4 0
      ${Break}
    ${EndIf}
    System::Call '*$2(i .r3, i .r4)'
    ${If} $4 = 1
      ${Break}
    ${EndIf}
    Sleep 500
    IntOp $5 $5 + 1
  ${LoopUntil} $5 >= 30
  System::Free $2
  System::Call 'advapi32::CloseServiceHandle(p r1)'
  ${If} $4 != 1
    !insertmacro Fail "$(ServiceError)"
  ${EndIf}
FunctionEnd
!macroend
!ifndef GENERATE_UNINSTALLER
!insertmacro CommonFunctions ""

Function ConfigureAndStartReleaseService
  ; Pass a quoted executable path directly to SCM, without command-line parsing.
  StrCpy $7 '$\"${SERVICE_DIR}\ComiTransReleaseService.exe$\"'
  StrCpy $6 "NT AUTHORITY\LocalService"
  System::Call 'advapi32::OpenSCManagerW(p 0, p 0, i 3) p.r0 ?e'
  Pop $8
  ${If} $0 = 0
    !insertmacro Trace "Open service manager: $8"
    !insertmacro Fail "$(ServiceError)"
  ${EndIf}
  System::Call 'advapi32::OpenServiceW(p r0, w "${SERVICE_NAME}", i 0x16) p.r1 ?e'
  Pop $8
  ${If} $1 = 0
    ${If} $8 != 1060
      System::Call 'advapi32::CloseServiceHandle(p r0)'
      !insertmacro Trace "Open service: $8"
      !insertmacro Fail "$(ServiceError)"
    ${EndIf}
    System::Call 'advapi32::CreateServiceW(p r0, w "${SERVICE_NAME}", w "ComiTrans Release Check", i 0x16, i 0x10, i 2, i 1, w r7, p 0, p 0, p 0, w r6, p 0) p.r1 ?e'
    Pop $8
    System::Call 'advapi32::CloseServiceHandle(p r0)'
    ${If} $1 = 0
      !insertmacro Trace "Create service: $8"
      !insertmacro Fail "$(ServiceError)"
    ${EndIf}
  ${Else}
    System::Call 'advapi32::ChangeServiceConfigW(p r1, i 0x10, i 2, i 1, w r7, p 0, p 0, p 0, w r6, p 0, w "ComiTrans Release Check") i.r3 ?e'
    Pop $8
    System::Call 'advapi32::CloseServiceHandle(p r0)'
    ${If} $3 = 0
      System::Call 'advapi32::CloseServiceHandle(p r1)'
      !insertmacro Trace "Configure service: $8"
      !insertmacro Fail "$(ServiceError)"
    ${EndIf}
  ${EndIf}
  System::Call 'advapi32::StartServiceW(p r1, i 0, p 0) i.r3 ?e'
  Pop $8
  ${If} $3 = 0
  ${AndIf} $8 != 1056
    System::Call 'advapi32::CloseServiceHandle(p r1)'
    !insertmacro Trace "Start service: $8"
    !insertmacro Fail "$(ServiceError)"
  ${EndIf}
  System::Alloc 36
  Pop $2
  StrCpy $5 0
  ${Do}
    System::Call 'advapi32::QueryServiceStatus(p r1, p r2) i.r3 ?e'
    Pop $8
    ${If} $3 = 0
      StrCpy $4 0
      ${Break}
    ${EndIf}
    System::Call '*$2(i .r3, i .r4)'
    ${If} $4 != 2
      ${Break}
    ${EndIf}
    Sleep 500
    IntOp $5 $5 + 1
  ${LoopUntil} $5 >= 30
  System::Free $2
  System::Call 'advapi32::CloseServiceHandle(p r1)'
  ${If} $4 != 4
    !insertmacro Trace "Service startup failed: state=$4, error=$8"
    !insertmacro Fail "$(ServiceError)"
  ${EndIf}
  !insertmacro Trace "Release service configured and running"
FunctionEnd
!else
!insertmacro CommonFunctions "un."
!endif

Function .onInit
!ifdef GENERATE_UNINSTALLER
  ; Build-time helper only; it never installs files or touches the registry.
  WriteUninstaller "${UNINSTALLER_OUT}"
  SetErrorLevel 0
  Quit
!else
  Call Initialize
  ${IfNot} ${RunningX64}
    !insertmacro Fail "$(Require64Bit)"
  ${EndIf}
  ReadRegStr $PreviousDirectory HKLM "${INSTALL_KEY}" "InstallDir"
  ${If} $PreviousDirectory != ""
    ReadRegStr $0 HKLM "${INSTALL_KEY}" "InstallerType"
    ${If} $0 != "NSIS"
      !insertmacro Fail "$(LegacyInstaller)"
    ${EndIf}
    ReadRegStr $0 HKLM "${INSTALL_KEY}" "Version"
    ${VersionCompare} $0 "${VERSION}" $1
    ${If} $1 = 1
      !insertmacro Fail "$(NewerInstalled)"
    ${EndIf}
    ; /D still takes precedence (NSIS applies it after .onInit).
    StrCpy $INSTDIR $PreviousDirectory
  ${EndIf}
  !insertmacro Trace "ComiTrans ${VERSION} NSIS setup started"
!endif
FunctionEnd

!ifndef GENERATE_UNINSTALLER
Function NormalizeDirectory
  ; NSIS GetFullPathName rejects missing parent folders; the Win32 API does not.
  System::Call 'kernel32::GetFullPathNameW(w "$INSTDIR", i ${NSIS_MAX_STRLEN}, w .r9, p 0) i.r8'
  ${If} $8 = 0
  ${OrIf} $8 >= ${NSIS_MAX_STRLEN}
    !insertmacro Fail "$(InvalidDirectory)"
  ${EndIf}
  StrCpy $INSTDIR $9
  ${Do}
    StrLen $8 $INSTDIR
    StrCpy $9 $INSTDIR 1 -1
    ${If} $8 <= 3
    ${OrIf} $9 != "\"
      ${Break}
    ${EndIf}
    StrCpy $INSTDIR $INSTDIR -1
  ${Loop}
FunctionEnd

Function VerifyDirectory
  Call NormalizeDirectory
  !insertmacro Trace "Selected folder: $INSTDIR"
  StrLen $0 $WINDIR
  IntOp $0 $0 + 1
  StrCpy $1 $INSTDIR $0
  ${If} $INSTDIR == $WINDIR
  ${OrIf} $1 == "$WINDIR\"
  ${OrIf} $INSTDIR == "${SERVICE_DIR}"
    !insertmacro Fail "$(InvalidDirectory)"
  ${EndIf}
  ; Browsing to a parent folder or drive creates an application subfolder.
  ; Preserve older NSIS installations that used a differently named folder.
  ${If} $INSTDIR != $PreviousDirectory
    ${GetFileName} $INSTDIR $0
    ${If} $0 != "ComiTrans"
      StrCpy $INSTDIR "$INSTDIR\ComiTrans"
      Call NormalizeDirectory
    ${EndIf}
  ${EndIf}
  ${If} $PreviousDirectory != ""
    ${If} $INSTDIR != $PreviousDirectory
      !insertmacro Fail "$(KeepDirectory)"
    ${EndIf}
    Return
  ${EndIf}
  ${GetRoot} $INSTDIR $0
  StrLen $1 $0
  !insertmacro Trace "Resolved installation folder: $INSTDIR (root=$0)"
  ${If} $1 != 2
  ${OrIf} $INSTDIR == "$0\"
  ${OrIf} $INSTDIR == $WINDIR
  ${OrIf} $INSTDIR == $SYSDIR
  ${OrIf} $INSTDIR == $PROGRAMFILES64
  ${OrIf} $INSTDIR == $PROGRAMFILES32
  ${OrIf} $INSTDIR == "${SERVICE_DIR}"
    !insertmacro Fail "$(InvalidDirectory)"
  ${EndIf}
  ; A new installation must not take ownership of unrelated files.
  ; FindFirst leaves the filename unchanged when the directory does not exist.
  StrCpy $1 ""
  FindFirst $0 $1 "$INSTDIR\*"
  ${DoWhile} $1 != ""
    ${If} $1 != "."
    ${AndIf} $1 != ".."
      FindClose $0
      !insertmacro Fail "$(InvalidDirectory)"
    ${EndIf}
    FindNext $0 $1
  ${Loop}
  FindClose $0
FunctionEnd
!endif

Function .onInstFailed
  !insertmacro Trace "$(InstallError)"
  SetErrorLevel 2
FunctionEnd

Section "ComiTrans" MainSection
!ifndef GENERATE_UNINSTALLER
  Call VerifyDirectory
  Call CheckApplicationClosed
  Call StopReleaseService
  !insertmacro Trace "Installing application to $INSTDIR"
  ClearErrors
  CreateDirectory "$INSTDIR"
  ${If} ${Errors}
    !insertmacro Trace "Creating installation folder failed"
    !insertmacro Fail "$(InstallError)"
  ${EndIf}
  SetOutPath "$INSTDIR"
  SetOverwrite on
  ClearErrors
  File "${PAYLOAD}\Uninstall.exe"
  ${If} ${Errors}
    !insertmacro Trace "Writing uninstaller failed"
    !insertmacro Fail "$(InstallError)"
  ${EndIf}
  ; Register the uninstall entry before extraction so an interrupted install
  ; can be retried or removed through Windows Settings.
  WriteRegStr HKLM "${INSTALL_KEY}" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "${INSTALL_KEY}" "Version" "${VERSION}"
  WriteRegStr HKLM "${INSTALL_KEY}" "ProductCode" "NSIS"
  WriteRegStr HKLM "${INSTALL_KEY}" "InstallerType" "NSIS"
  WriteRegStr HKLM "${INSTALL_KEY}" "SetupManaged" "1"
  WriteRegStr HKLM "${INSTALL_KEY}" "SetupSource" "$EXEPATH"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayName" "ComiTrans"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "Publisher" "ComiTrans"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\ComiTrans.exe,0"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegStr HKLM "${UNINSTALL_KEY}" "QuietUninstallString" '$\"$INSTDIR\Uninstall.exe$\" /S'
  WriteRegDWORD HKLM "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINSTALL_KEY}" "NoRepair" 1
  ${If} ${Errors}
    !insertmacro Trace "Writing uninstall registration failed"
    !insertmacro Fail "$(InstallError)"
  ${EndIf}
  ClearErrors
  File /r /x ComiTransReleaseService.exe /x Uninstall.exe "${PAYLOAD}\*"
  ${If} ${Errors}
    !insertmacro Trace "Extracting application files failed"
    !insertmacro Fail "$(InstallError)"
  ${EndIf}
  SetOutPath "${SERVICE_DIR}"
  ClearErrors
  File "${PAYLOAD}\ComiTransReleaseService.exe"
  ${If} ${Errors}
    !insertmacro Trace "Writing service binary failed"
    !insertmacro Fail "$(InstallError)"
  ${EndIf}
  Call ConfigureAndStartReleaseService
  SetOutPath "$INSTDIR"
  CreateShortcut "$SMPROGRAMS\ComiTrans.lnk" "$INSTDIR\ComiTrans.exe"
  CreateShortcut "$DESKTOP\ComiTrans.lnk" "$INSTDIR\ComiTrans.exe"
  ReadRegStr $0 HKLM "Software\Classes\.comitrans" ""
  ClearErrors
  ${If} $0 != "ComiTrans.PdfProject"
    WriteRegStr HKLM "${INSTALL_KEY}" "PreviousAssociation" "$0"
  ${EndIf}
  WriteRegStr HKLM "Software\Classes\.comitrans" "" "ComiTrans.PdfProject"
  WriteRegStr HKLM "Software\Classes\.comitrans\OpenWithProgids" "ComiTrans.PdfProject" ""
  WriteRegStr HKLM "Software\Classes\ComiTrans.PdfProject" "" "ComiTrans PDF Project"
  WriteRegStr HKLM "Software\Classes\ComiTrans.PdfProject\DefaultIcon" "" '$\"$INSTDIR\ComiTrans.exe$\",0'
  WriteRegStr HKLM "Software\Classes\ComiTrans.PdfProject\shell\open\command" "" '$\"$INSTDIR\ComiTrans.exe$\" $\"%1$\"'
  ${If} ${Errors}
    !insertmacro Fail "$(InstallError)"
  ${EndIf}
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  WriteRegDWORD HKLM "${UNINSTALL_KEY}" "EstimatedSize" $0
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
  !insertmacro Trace "Installation completed: ${VERSION}"
  SetErrorLevel 0
!endif
SectionEnd

!ifdef GENERATE_UNINSTALLER
Function un.onInit
  Call un.Initialize
  ReadRegStr $0 HKLM "${INSTALL_KEY}" "InstallerType"
  ReadRegStr $1 HKLM "${INSTALL_KEY}" "InstallDir"
  ${If} $0 != "NSIS"
  ${OrIf} $1 != $INSTDIR
    !insertmacro Fail "$(InvalidUninstall)"
  ${EndIf}
FunctionEnd

Section "Uninstall"
  Call un.CheckApplicationClosed
  Call un.StopReleaseService
  System::Call 'advapi32::OpenSCManagerW(p 0, p 0, i 1) p.r0'
  System::Call 'advapi32::OpenServiceW(p r0, w "${SERVICE_NAME}", i 0x10000) p.r1 ?e'
  Pop $8
  System::Call 'advapi32::CloseServiceHandle(p r0)'
  ${If} $1 != 0
    System::Call 'advapi32::DeleteService(p r1) i.r3 ?e'
    Pop $8
    System::Call 'advapi32::CloseServiceHandle(p r1)'
    ${If} $3 = 0
      !insertmacro Trace "Delete service: $8"
      !insertmacro Fail "$(ServiceError)"
    ${EndIf}
  ${ElseIf} $8 != 1060
    !insertmacro Trace "Open service for deletion: $8"
    !insertmacro Fail "$(ServiceError)"
  ${EndIf}
  SetOutPath "$TEMP"
  Delete "${SERVICE_DIR}\ComiTransReleaseService.exe"
  RMDir "${SERVICE_DIR}"
  !include "${UNINSTALL_FILES}"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  Delete "$SMPROGRAMS\ComiTrans.lnk"
  Delete "$DESKTOP\ComiTrans.lnk"
  ReadRegStr $0 HKLM "Software\Classes\.comitrans" ""
  ${If} $0 == "ComiTrans.PdfProject"
    ReadRegStr $0 HKLM "${INSTALL_KEY}" "PreviousAssociation"
    ${If} $0 == ""
      DeleteRegValue HKLM "Software\Classes\.comitrans" ""
    ${Else}
      WriteRegStr HKLM "Software\Classes\.comitrans" "" "$0"
    ${EndIf}
  ${EndIf}
  DeleteRegValue HKLM "Software\Classes\.comitrans\OpenWithProgids" "ComiTrans.PdfProject"
  DeleteRegKey /ifempty HKLM "Software\Classes\.comitrans\OpenWithProgids"
  DeleteRegKey /ifempty HKLM "Software\Classes\.comitrans"
  ReadRegStr $0 HKLM "Software\Classes\ComiTrans.PdfProject\shell\open\command" ""
  ${If} $0 == '$\"$INSTDIR\ComiTrans.exe$\" $\"%1$\"'
    DeleteRegKey HKLM "Software\Classes\ComiTrans.PdfProject"
  ${EndIf}
  DeleteRegKey HKLM "${UNINSTALL_KEY}"
  DeleteRegKey HKLM "${INSTALL_KEY}"
  DeleteRegKey /ifempty HKLM "Software\ComiTrans"
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
  !insertmacro Trace "Uninstallation completed; user data retained"
  SetErrorLevel 0
SectionEnd
!endif
