#NoEnv
#SingleInstance Force
#Persistent
SetBatchLines, -1
SetWorkingDir, %A_ScriptDir%
SendMode, Input

; ============================================================
; CONFIGURATION
; ============================================================

MIN_DURATION := 100
MAX_DURATION := 1000

; Nombre de commandes à lire en avance
PREFETCH_COUNT := 6

; Taille maximale d'un bloc mémoire lu
SCAN_BLOCK_SIZE := 65536

; Nombre maximal de blocs scannes par passage
SCAN_BLOCKS_PER_PASS := 32

; Intervalle de la boucle principale
LOOP_INTERVAL := 20

; ============================================================
; VARIABLES GLOBALES
; ============================================================

global engineRunning := false
global isBusy := false

global hProcess := 0
global currentPid := 0

global scanAddress := 0
global regionEnd := 0

global candidateAddress := 0
global streamReady := false

global commandQueue := []

; ============================================================
; ELEVATION ADMINISTRATEUR
; ============================================================

if (!A_IsAdmin)
{
    Run, *RunAs "%A_AhkPath%" "%A_ScriptFullPath%"
    ExitApp
}

EnableDebugPrivilege()

; ============================================================
; INTERFACE
; ============================================================

Gui, +AlwaysOnTop -Caption +ToolWindow
Gui, Color, 202020

Gui, Add, Text, x8 y7 w14 h14 vStatusDot BackgroundRed
Gui, Add, Text, x28 y5 w250 h18 vStatusText cFFFFFF, OFF

Gui, Show, x10 y10 w290 h30, RAM Reader

; ============================================================
; HOTKEY
; AltGr + V
; ============================================================

<^>!v::ToggleEngine()

; ============================================================
; BOUCLE PRINCIPALE
; ============================================================

SetTimer, MainLoop, %LOOP_INTERVAL%
return

MainLoop:

if (!engineRunning)
    return

if (isBusy)
    return

isBusy := true

; ------------------------------------------------------------
; Prélecture
; ------------------------------------------------------------

if (commandQueue.Length() < PREFETCH_COUNT)
{
    PrefetchFrames()
}

; ------------------------------------------------------------
; Exécution de la première commande disponible
; ------------------------------------------------------------

if (commandQueue.Length() > 0)
{
    frame := commandQueue.RemoveAt(1)

    ExecuteFrame(frame)
}

isBusy := false

return

; ============================================================
; ACTIVATION / DESACTIVATION
; ============================================================

ToggleEngine()
{
    global engineRunning

    if (engineRunning)
    {
        engineRunning := false
        GuiControl, +BackgroundRed, StatusDot
        GuiControl,, StatusText, OFF
        ToolTip, MOTEUR OFF
        SetTimer, RemoveToolTip, -1500

        ReleaseKeys()
        CloseCurrentProcess()

        return
    }

    engineRunning := true

    GuiControl, +BackgroundGreen, StatusDot
    GuiControl,, StatusText, ON

    ToolTip, MOTEUR ON - recherche d'un processus...
    SetTimer, RemoveToolTip, -1500
}

; ============================================================
; PREFETCH
; ============================================================

PrefetchFrames()
{
    global hProcess
    global currentPid
    global scanAddress
    global regionEnd
    global candidateAddress
    global streamReady
    global commandQueue
    global PREFETCH_COUNT

    if (hProcess && currentPid)
        pid := currentPid
    else
        pid := FindTargetProcess()

    if (!pid)
    {
        GuiControl,, StatusText, AUCUN PROCESSUS
        ToolTip, ERREUR : aucun processus trouve
        SetTimer, RemoveToolTip, -1500
        return
    }

    ; --------------------------------------------------------
    ; Nouveau processus
    ; --------------------------------------------------------

    if (pid != currentPid)
    {
        CloseCurrentProcess()

        hProcess := DllCall("kernel32.dll\OpenProcess"
            , "UInt", 0x0410
            , "Int", 0
            , "UInt", pid
            , "Ptr")

        if (!hProcess)
        {
            GuiControl,, StatusText, OPENPROCESS ECHEC
            ToolTip, ERREUR : OpenProcess a echoue
            SetTimer, RemoveToolTip, -1500
            return
        }

        currentPid := pid
        GuiControl,, StatusText, PID %pid% - LECTURE OK

        scanAddress := 0
        regionEnd := 0
        candidateAddress := 0
        streamReady := false

        commandQueue := []
    }

    if (!hProcess)
        return

    ; --------------------------------------------------------
    ; Recherche du flux
    ; --------------------------------------------------------

    if (!streamReady)
    {
        if (!FindBitStream())
            return
    }

    ; --------------------------------------------------------
    ; Prélecture des commandes
    ; --------------------------------------------------------

    while (commandQueue.Length() < PREFETCH_COUNT)
    {
        frame := ReadNextFrame()

        if (!IsObject(frame))
        {
            streamReady := false
            break
        }

        commandQueue.Push(frame)
    }
}

; ============================================================
; RECHERCHE D'UNE ZONE MEMOIRE LISIBLE
; ============================================================

FindBitStream()
{
    global hProcess
    global scanAddress
    global regionEnd
    global candidateAddress
    global streamReady

    if (!hProcess)
        return false

    if (!GetNextReadableRegion(scanAddress, baseAddress, regionSize))
    {
        scanAddress := 0
        return false
    }

    regionEnd := baseAddress + regionSize
    candidateAddress := baseAddress
    scanAddress := regionEnd
    streamReady := true
    GuiControl,, StatusText, MEMOIRE OK : %candidateAddress%

    ToolTip, ZONE MEMOIRE LISIBLE ! Adresse : %candidateAddress%
    SetTimer, RemoveToolTip, -1500

    return true
}

; ============================================================
; ANCIEN SCAN DE BITS CONSERVE POUR REFERENCE
; ============================================================

SearchBuffer(bufferPtr, size)
{
    if (size < 7)
        return -1

    max := size - 7

    Loop, % max + 1
    {
        i := A_Index - 1

        valid := true

        Loop, 7
        {
            offset := i + A_Index - 1

            value := NumGet(bufferPtr + 0, offset, "UChar")

            if (value != 0 && value != 1)
            {
                valid := false
                break
            }
        }

        if (valid)
            return i
    }

    return -1
}

; ============================================================
; LECTURE D'UNE TRAME
;
; 7 bits :
;
; BIT 0-1 :
;   00 = rien
;   01 = gauche
;   10 = droite
;   11 = suivant / skip
;
; BIT 2-6 :
;   durée codée sur 5 bits
;
; ============================================================

ReadNextFrame()
{
    global hProcess
    global candidateAddress
    global MIN_DURATION
    global MAX_DURATION

    if (!hProcess)
        return false

    if (!candidateAddress)
        return false

    VarSetCapacity(oneByte, 1, 0)
    bytesRead := 0

    ok := DllCall("kernel32.dll\ReadProcessMemory"
        , "Ptr", hProcess
        , "Ptr", candidateAddress
        , "Ptr", &oneByte
        , "Ptr", 1
        , "Ptr", &bytesRead)

    if (!ok || bytesRead != 1)
        return false

    value := NumGet(oneByte, 0, "UChar")

    ; Chaque octet brut produit un déplacement gauche ou droite.
    command := Mod(value, 2) + 1

    ; --------------------------------------------------------
    ; Conversion 0..31 -> MIN_DURATION..MAX_DURATION
    ; --------------------------------------------------------

    durationRange := MAX_DURATION - MIN_DURATION

    duration := MIN_DURATION
        + Round((value / 255.0) * durationRange)

    ; --------------------------------------------------------
    ; Avance dans le flux
    ; --------------------------------------------------------

    candidateAddress += 1

    ; --------------------------------------------------------
    ; Construction de la trame
    ; --------------------------------------------------------

    frame := {}

    frame.command := command
    frame.duration := duration

    return frame
}

; ============================================================
; EXECUTION D'UNE TRAME
; ============================================================

ExecuteFrame(frame)
{
    if (!IsObject(frame))
        return

    command := frame.command
    duration := frame.duration

    GuiControl,, StatusText, COMMANDE %command% - %duration% ms
    ToolTip, COMMANDE : %command% / DUREE : %duration% ms
    SetTimer, RemoveToolTip, -1500

    ; --------------------------------------------------------
    ; 00 = rien
    ; --------------------------------------------------------

    if (command = 0)
    {
        Sleep, %duration%
        return
    }

    ; --------------------------------------------------------
    ; 11 = skip
    ; --------------------------------------------------------

    if (command = 3)
    {
        return
    }

    ; --------------------------------------------------------
    ; 01 = gauche
    ; --------------------------------------------------------

    if (command = 1)
    {
        SendInput, {Left down}
        Sleep, %duration%
        SendInput, {Left up}

        return
    }

    ; --------------------------------------------------------
    ; 10 = droite
    ; --------------------------------------------------------

    if (command = 2)
    {
        SendInput, {Right down}
        Sleep, %duration%
        SendInput, {Right up}

        return
    }
}

; ============================================================
; VIRTUALQUERYEX
; ============================================================

GetNextReadableRegion(address, ByRef baseAddress, ByRef regionSize)
{
    global hProcess

    if (!hProcess)
        return false

    ; --------------------------------------------------------
    ; Taille de MEMORY_BASIC_INFORMATION
    ; --------------------------------------------------------

    if (A_PtrSize = 8)
        mbiSize := 48
    else
        mbiSize := 28

    VarSetCapacity(mbi, mbiSize, 0)

    Loop
    {
        result := DllCall("kernel32.dll\VirtualQueryEx"
            , "Ptr", hProcess
            , "Ptr", address
            , "Ptr", &mbi
            , "Ptr", mbiSize
            , "Ptr")

        if (!result)
            return false

        ; ----------------------------------------------------
        ; Structure MEMORY_BASIC_INFORMATION
        ; ----------------------------------------------------

        if (A_PtrSize = 8)
        {
            baseAddress := NumGet(mbi, 0, "Ptr")
            regionSize := NumGet(mbi, 24, "Ptr")
            state := NumGet(mbi, 32, "UInt")
            protect := NumGet(mbi, 36, "UInt")
        }
        else
        {
            baseAddress := NumGet(mbi, 0, "UInt")
            regionSize := NumGet(mbi, 12, "UInt")
            state := NumGet(mbi, 16, "UInt")
            protect := NumGet(mbi, 20, "UInt")
        }

        if (state = 0x1000 && !(protect & 0x01) && !(protect & 0x100))
            return true

        nextAddress := baseAddress + regionSize

        if (nextAddress <= address)
            return false

        address := nextAddress
    }
}

; ============================================================
; RECHERCHE D'UN PROCESSUS ACCESSIBLE
; ============================================================

FindTargetProcess()
{
    bestPid := 0
    bestMemory := 0

    try
    {
        wmi := ComObjGet("winmgmts:")

        query := "SELECT ProcessId, WorkingSetSize FROM Win32_Process WHERE ProcessId <> " . A_Pid

        processes := wmi.ExecQuery(query)

        for process in processes
        {
            pid := process.ProcessId
            memory := process.WorkingSetSize

            if (!pid)
                continue

            testHandle := DllCall("kernel32.dll\OpenProcess"
                , "UInt", 0x0410
                , "Int", 0
                , "UInt", pid
                , "Ptr")

            if (!testHandle)
                continue

            DllCall("kernel32.dll\CloseHandle", "Ptr", testHandle)

            if (memory > bestMemory)
            {
                bestMemory := memory
                bestPid := pid
            }
        }
    }
    catch e
    {
        return 0
    }

    return bestPid
}

; ============================================================
; SEDEBUGPRIVILEGE
; ============================================================

EnableDebugPrivilege()
{
    TOKEN_ADJUST_PRIVILEGES := 0x20
    TOKEN_QUERY := 0x08
    SE_PRIVILEGE_ENABLED := 0x2

    hToken := 0

    if (!DllCall("advapi32.dll\OpenProcessToken"
        , "Ptr", DllCall("kernel32.dll\GetCurrentProcess", "Ptr")
        , "UInt", TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY
        , "Ptr*", hToken))
    {
        return false
    }

    VarSetCapacity(luid, 8, 0)

    if (!DllCall("advapi32.dll\LookupPrivilegeValue"
        , "Ptr", 0
        , "Str", "SeDebugPrivilege"
        , "Ptr", &luid))
    {
        DllCall("kernel32.dll\CloseHandle", "Ptr", hToken)
        return false
    }

    VarSetCapacity(tp, 16, 0)

    NumPut(1, tp, 0, "UInt")
    NumPut(NumGet(luid, 0, "UInt"), tp, 4, "UInt")
    NumPut(NumGet(luid, 4, "UInt"), tp, 8, "UInt")
    NumPut(SE_PRIVILEGE_ENABLED, tp, 12, "UInt")

    result := DllCall("advapi32.dll\AdjustTokenPrivileges"
        , "Ptr", hToken
        , "Int", 0
        , "Ptr", &tp
        , "UInt", 0
        , "Ptr", 0
        , "Ptr", 0)

    DllCall("kernel32.dll\CloseHandle", "Ptr", hToken)

    return result
}

; ============================================================
; FERMETURE PROCESSUS
; ============================================================

CloseCurrentProcess()
{
    global hProcess
    global currentPid

    if (hProcess)
    {
        DllCall("kernel32.dll\CloseHandle", "Ptr", hProcess)
        hProcess := 0
    }

    currentPid := 0
}

; ============================================================
; SECURITE TOUCHES
; ============================================================

ReleaseKeys()
{
    SendInput, {Left up}
    SendInput, {Right up}
}

; ============================================================
; SORTIE
; ============================================================

OnExit, HandleExit
return

HandleExit:

ReleaseKeys()
CloseCurrentProcess()

ExitApp
return
RemoveToolTip:
ToolTip
return