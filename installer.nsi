; ==============================================================================
; NSIS Installation Script for Dictaphone (Диктофон)
; ==============================================================================

Unicode True
SetCompressor /SOLID lzma

!define PRODUCT_NAME "Диктофон"
!define PRODUCT_INTERNAL_NAME "Dictaphone"
!define PRODUCT_VERSION "1.0.1"
!define PRODUCT_PUBLISHER "AudioRecorder"
!define PRODUCT_EXE "Dictaphone.exe"
!define PRODUCT_UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_INTERNAL_NAME}"
!define PRODUCT_DIR_REGKEY "Software\Microsoft\Windows\CurrentVersion\App Paths\${PRODUCT_EXE}"

Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "dist\DictaphoneSetup.exe"
InstallDir "$PROGRAMFILES64\${PRODUCT_INTERNAL_NAME}"
InstallDirRegKey HKLM "${PRODUCT_DIR_REGKEY}" ""
RequestExecutionLevel admin

; ------------------------------------------------------------------------------
; Modern UI 2 Includes and Configuration
; ------------------------------------------------------------------------------
!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

!define MUI_ICON "resources\icon.ico"
!define MUI_UNICON "resources\icon.ico"
!define MUI_ABORTWARNING

; Welcome Page
!insertmacro MUI_PAGE_WELCOME

; Directory Selection Page
!insertmacro MUI_PAGE_DIRECTORY

; Installation Progress Page
!insertmacro MUI_PAGE_INSTFILES

; Finish Page
!define MUI_FINISHPAGE_RUN "$INSTDIR\${PRODUCT_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Запустить ${PRODUCT_NAME}"
!insertmacro MUI_PAGE_FINISH

; Uninstaller Pages
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

; Languages (Russian default, English fallback)
!insertmacro MUI_LANGUAGE "Russian"
!insertmacro MUI_LANGUAGE "English"

; ------------------------------------------------------------------------------
; Installer Section
; ------------------------------------------------------------------------------
Section "MainSection" SEC01
    ; Завершаем работающий процесс перед обновлением/установкой
    ExecWait 'taskkill /F /IM ${PRODUCT_EXE}'

    SetOutPath "$INSTDIR"
    SetOverwrite on

    ; Копируем файлы собранного приложения
    File /r "dist\Dictaphone\*.*"

    ; Создаем ярлыки в меню Пуск
    CreateDirectory "$SMPROGRAMS\${PRODUCT_NAME}"
    CreateShortcut "$SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk" "$INSTDIR\${PRODUCT_EXE}" "" "$INSTDIR\${PRODUCT_EXE}" 0
    CreateShortcut "$SMPROGRAMS\${PRODUCT_NAME}\Удалить ${PRODUCT_NAME}.lnk" "$INSTDIR\uninstall.exe" "" "$INSTDIR\uninstall.exe" 0

    ; Создаем ярлык на Рабочем столе
    CreateShortcut "$DESKTOP\${PRODUCT_NAME}.lnk" "$INSTDIR\${PRODUCT_EXE}" "" "$INSTDIR\${PRODUCT_EXE}" 0

    ; Генерируем деинсталлятор
    WriteUninstaller "$INSTDIR\uninstall.exe"

    ; Запись информации об установке в реестр
    WriteRegStr HKLM "${PRODUCT_DIR_REGKEY}" "" "$INSTDIR\${PRODUCT_EXE}"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayName" "${PRODUCT_NAME}"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayIcon" "$INSTDIR\${PRODUCT_EXE},0"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "InstallLocation" "$INSTDIR"
    WriteRegDWORD HKLM "${PRODUCT_UNINST_KEY}" "NoModify" 1
    WriteRegDWORD HKLM "${PRODUCT_UNINST_KEY}" "NoRepair" 1

    ; Расчет приблизительного размера для Панели управления Windows
    ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
    IntFmt $0 "0x%08X" $0
    WriteRegDWORD HKLM "${PRODUCT_UNINST_KEY}" "EstimatedSize" "$0"
SectionEnd

; ------------------------------------------------------------------------------
; Uninstaller Section
; ------------------------------------------------------------------------------
Section "Uninstall"
    ; Закрываем работающий экземпляр перед удалением
    ExecWait 'taskkill /F /IM ${PRODUCT_EXE}'

    ; Удаляем ярлыки
    Delete "$DESKTOP\${PRODUCT_NAME}.lnk"
    Delete "$SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk"
    Delete "$SMPROGRAMS\${PRODUCT_NAME}\Удалить ${PRODUCT_NAME}.lnk"
    RMDir "$SMPROGRAMS\${PRODUCT_NAME}"

    ; Удаляем все файлы и каталог приложения
    RMDir /r "$INSTDIR"

    ; Удаляем ветки реестра
    DeleteRegKey HKLM "${PRODUCT_UNINST_KEY}"
    DeleteRegKey HKLM "${PRODUCT_DIR_REGKEY}"
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "AudioDictaphone"
SectionEnd
