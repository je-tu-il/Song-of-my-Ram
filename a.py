import tkinter as tk
import ctypes
from ctypes import wintypes
import pyaudio
import threading
import time
import subprocess
import re

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100

class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

def get_pid_by_name(process_name):
    try:
        output = subprocess.check_output("tasklist", creationflags=subprocess.CREATE_NO_WINDOW).decode(errors='ignore')
        for line in output.splitlines():
            if process_name.lower() in line.lower():
                match = re.search(r'\s+(\d+)\s+', line)
                if match:
                    return int(match.group(1))
    except Exception:
        pass
    return None

class RAMAudioPlayer:
    def __init__(self, root):
        self.root = root
        self.root.title("Lecteur RAM Audio")
        
        self.is_running = True
        self.is_playing = False
        self.current_pid = None
        
        self.audio_thread = threading.Thread(target=self.audio_loop, daemon=True)
        self.audio_thread.start()
        
        self.lbl_status = tk.Label(root, text="En attente de sélection", font=("Arial", 10))
        self.lbl_status.pack(pady=10)

        tk.Button(root, text="Lire explorer.exe", command=lambda: self.switch_process("explorer.exe"), width=25).pack(pady=2)
        tk.Button(root, text="Lire notepad.exe", command=lambda: self.switch_process("notepad.exe"), width=25).pack(pady=2)
        tk.Button(root, text="Lire cmd.exe", command=lambda: self.switch_process("cmd.exe"), width=25).pack(pady=2)

        frame_custom = tk.Frame(root)
        frame_custom.pack(pady=2)
        self.entry_custom = tk.Entry(frame_custom, width=10)
        self.entry_custom.pack(side="left", padx=5)
        tk.Button(frame_custom, text="Lire Custom PID", command=self.switch_custom).pack(side="left")
        
        tk.Button(root, text="Pause", command=self.pause, width=25).pack(pady=10)

    def switch_process(self, process_name):
        pid = get_pid_by_name(process_name)
        if pid:
            self.current_pid = pid
            self.is_playing = True
            self.lbl_status.config(text=f"Lecture : {process_name} (PID: {pid})")
        else:
            self.lbl_status.config(text=f"Processus non trouvé : {process_name}")
            self.is_playing = False

    def switch_custom(self):
        pid_str = self.entry_custom.get()
        if pid_str.isdigit():
            self.current_pid = int(pid_str)
            self.is_playing = True
            self.lbl_status.config(text=f"Lecture Custom (PID: {self.current_pid})")
        else:
            self.lbl_status.config(text="Erreur : PID invalide")
            self.is_playing = False

    def pause(self):
        self.is_playing = False
        self.lbl_status.config(text="En pause")

    def audio_loop(self):
        p = pyaudio.PyAudio()
        stream = p.open(format=pyaudio.paUInt8, channels=1, rate=44100, output=True)

        while self.is_running:
            if not self.is_playing or not self.current_pid:
                time.sleep(0.1)
                continue

            active_pid = self.current_pid
            process_handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, active_pid)
            
            if not process_handle:
                time.sleep(0.5)
                continue

            address = 0
            mbi = MEMORY_BASIC_INFORMATION()

            while kernel32.VirtualQueryEx(process_handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)):
                if not self.is_playing or self.current_pid != active_pid:
                    break

                if mbi.State == MEM_COMMIT and not (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)):
                    buffer = ctypes.create_string_buffer(mbi.RegionSize)
                    bytes_read = ctypes.c_size_t(0)
                    
                    success = kernel32.ReadProcessMemory(
                        process_handle, 
                        ctypes.c_void_p(address), 
                        buffer, 
                        mbi.RegionSize, 
                        ctypes.byref(bytes_read)
                    )
                    
                    if success and bytes_read.value > 0:
                        try:
                            stream.write(buffer.raw[:bytes_read.value])
                        except IOError:
                            pass
                
                address += mbi.RegionSize
            
            kernel32.CloseHandle(process_handle)

if __name__ == "__main__":
    root = tk.Tk()
    app = RAMAudioPlayer(root)
    root.mainloop()