import tkinter as tk
from tkinter import ttk
import ctypes
from ctypes import wintypes
import pyaudio
import threading
import time
import psutil
import sys

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

if not is_admin():
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
    sys.exit()

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
winmm = ctypes.windll.winmm

class ProcessReader:
    def __init__(self, pid):
        self.handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        self.address = 0
        self.current_region_end = 0

    def read_byte(self, step=512):
        if not self.handle:
            return 0
            
        while True:
            if self.address >= self.current_region_end:
                mbi = MEMORY_BASIC_INFORMATION()
                if not kernel32.VirtualQueryEx(self.handle, ctypes.c_void_p(self.address), ctypes.byref(mbi), ctypes.sizeof(mbi)):
                    self.address = 0 
                    self.current_region_end = 0
                    return 0
                
                base_addr = mbi.BaseAddress or 0
                self.current_region_end = base_addr + mbi.RegionSize
                
                if mbi.State != MEM_COMMIT or (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)):
                    self.address = self.current_region_end
                    continue
                    
            buffer = ctypes.create_string_buffer(1)
            bytes_read = ctypes.c_size_t(0)
            success = kernel32.ReadProcessMemory(self.handle, ctypes.c_void_p(self.address), buffer, 1, ctypes.byref(bytes_read))
            self.address += step
            
            if success and bytes_read.value > 0:
                return buffer.raw[0]
            else:
                self.address = self.current_region_end

    def close(self):
        if self.handle:
            kernel32.CloseHandle(self.handle)

class RAMOrchestrator:
    def __init__(self, root):
        self.root = root
        self.root.title("RAM Audio Engine")
        self.root.geometry("550x420")
        
        style = ttk.Style()
        style.theme_use('clam')
        
        self.is_playing = False
        self.audio_thread = None
        self.bpm = 60
        self.max_processes = 10
        
        self.scales = {
            "bass": [36, 38, 40, 43, 45],
            "chord": [(48, 52, 55), (50, 53, 57), (52, 55, 59), (55, 59, 62), (57, 60, 64)],
            "arpeggio": [60, 62, 64, 67, 69, 72],
            "melody": [72, 74, 76, 79, 81, 84]
        }
        
        self.roles = [
            {"name": "Cello", "channel": 0, "instrument": 42, "dur_mult": 1.0, "scale": "bass", "vol": 0.9},
            {"name": "Electric Piano", "channel": 1, "instrument": 4, "dur_mult": 0.5, "scale": "chord", "vol": 0.7},
            {"name": "Marimba", "channel": 2, "instrument": 12, "dur_mult": 0.25, "scale": "arpeggio", "vol": 0.6},
            {"name": "Alto Sax", "channel": 3, "instrument": 65, "dur_mult": 0.125, "scale": "melody", "vol": 0.8},
            {"name": "Synth Pad", "channel": 4, "instrument": 88, "dur_mult": 2.0, "scale": "chord", "vol": 0.5},
            {"name": "Clean Guitar", "channel": 5, "instrument": 27, "dur_mult": 0.5, "scale": "arpeggio", "vol": 0.6},
            {"name": "Glockenspiel", "channel": 6, "instrument": 9, "dur_mult": 0.25, "scale": "melody", "vol": 0.7},
            {"name": "Synth Bass", "channel": 7, "instrument": 38, "dur_mult": 1.0, "scale": "bass", "vol": 0.8},
            {"name": "Clarinet", "channel": 8, "instrument": 71, "dur_mult": 0.125, "scale": "melody", "vol": 0.7},
            {"name": "Pizzicato", "channel": 10, "instrument": 45, "dur_mult": 0.5, "scale": "chord", "vol": 0.6}
        ]
        
        self.target_processes = []
        
        self.setup_ui()
        self.auto_select_processes()

    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="RAM Synthesis & Orchestration", font=("Segoe UI", 12, "bold")).pack(pady=5)
        
        self.mode_var = tk.StringVar(value="midi")
        mode_frame = ttk.Frame(main_frame)
        mode_frame.pack(pady=5)
        ttk.Radiobutton(mode_frame, text="Electronic (Raw PCM)", variable=self.mode_var, value="pcm").pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(mode_frame, text="Concerto (MIDI Instruments)", variable=self.mode_var, value="midi").pack(side=tk.LEFT, padx=10)

        bpm_frame = ttk.Frame(main_frame)
        bpm_frame.pack(pady=5, fill=tk.X)
        ttk.Label(bpm_frame, text="Tempo (BPM):").pack(side=tk.LEFT)
        self.bpm_var = tk.IntVar(value=self.bpm)
        self.bpm_slider = ttk.Scale(bpm_frame, from_=20, to=200, variable=self.bpm_var, command=self.update_bpm)
        self.bpm_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        self.bpm_label = ttk.Label(bpm_frame, text=str(self.bpm))
        self.bpm_label.pack(side=tk.LEFT)

        self.info_text = tk.Text(main_frame, height=8, width=60, state=tk.DISABLED, bg="#f0f0f0", font=("Consolas", 9))
        self.info_text.pack(pady=10)

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(pady=10)

        ttk.Button(btn_frame, text="Lecture", command=self.play, width=15).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="Pause", command=self.stop, width=15).pack(side=tk.RIGHT, padx=10)

    def update_bpm(self, val):
        self.bpm = int(float(val))
        self.bpm_label.config(text=str(self.bpm))

    def auto_select_processes(self):
        procs = []
        for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
            try:
                pid = proc.info['pid']
                if proc.info['memory_info'] is None:
                    continue
                    
                handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    procs.append(proc.info)
            except:
                continue
                
        procs.sort(key=lambda x: x['memory_info'].rss, reverse=True)
        self.target_processes = procs[:self.max_processes]
        
        self.info_text.config(state=tk.NORMAL)
        self.info_text.delete(1.0, tk.END)
        for i, p in enumerate(self.target_processes):
            ram_mb = p['memory_info'].rss / (1024 * 1024)
            role_name = self.roles[i % len(self.roles)]['name']
            self.info_text.insert(tk.END, f"[{role_name}] {p['name']} ({ram_mb:.1f} MB)\n")
        self.info_text.config(state=tk.DISABLED)

    def play(self):
        if self.is_playing or not self.target_processes:
            return

        self.is_playing = True
        if self.mode_var.get() == "pcm":
            self.audio_thread = threading.Thread(target=self.electronic_audio_loop, daemon=True)
        else:
            self.audio_thread = threading.Thread(target=self.midi_audio_loop, daemon=True)
        self.audio_thread.start()

    def stop(self):
        self.is_playing = False

    def electronic_audio_loop(self):
        pid = self.target_processes[0]['pid']
        process_handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not process_handle:
            self.is_playing = False
            return

        p = pyaudio.PyAudio()
        stream = p.open(format=pyaudio.paUInt8, channels=1, rate=44100, output=True)

        address = 0
        mbi = MEMORY_BASIC_INFORMATION()

        while self.is_playing and kernel32.VirtualQueryEx(process_handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            if mbi.State == MEM_COMMIT and not (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)):
                buffer = ctypes.create_string_buffer(mbi.RegionSize)
                bytes_read = ctypes.c_size_t(0)
                
                success = kernel32.ReadProcessMemory(process_handle, ctypes.c_void_p(address), buffer, mbi.RegionSize, ctypes.byref(bytes_read))
                
                if success and bytes_read.value > 0:
                    try:
                        stream.write(buffer.raw[:bytes_read.value])
                    except IOError:
                        pass
            address += mbi.RegionSize

        stream.stop_stream()
        stream.close()
        p.terminate()
        kernel32.CloseHandle(process_handle)

    def midi_audio_loop(self):
        hMidiOut = ctypes.c_void_p()
        winmm.midiOutOpen(ctypes.byref(hMidiOut), 0, 0, 0, 0)

        for config in self.roles:
            msg = 0xC0 | config["channel"] | (config["instrument"] << 8)
            winmm.midiOutShortMsg(hMidiOut, msg)

        readers = [ProcessReader(p['pid']) for p in self.target_processes]
        
        next_tick_time = time.perf_counter()
        tick = 0
        
        active_notes = []

        while self.is_playing:
            now = time.perf_counter()
            tick_duration = (60.0 / self.bpm) / 8 
            
            remaining_notes = []
            for off_time, channel, note in active_notes:
                if now >= off_time:
                    msg = 0x80 | channel | (note << 8)
                    winmm.midiOutShortMsg(hMidiOut, msg)
                else:
                    remaining_notes.append((off_time, channel, note))
            active_notes = remaining_notes

            if now >= next_tick_time:
                for i, reader in enumerate(readers):
                    config = self.roles[i % len(self.roles)]
                    tick_interval = int(config["dur_mult"] / 0.125)
                    if tick_interval == 0: tick_interval = 1
                    
                    if tick % tick_interval == 0:
                        val = reader.read_byte(step=2048)
                        if val != 0:
                            scale = self.scales[config["scale"]]
                            item = scale[val % len(scale)]
                            
                            channel = config["channel"]
                            vol = int(config["vol"] * 127)
                            note_duration = config["dur_mult"] * (60.0/self.bpm) * 0.9 
                            
                            notes_to_play = item if isinstance(item, tuple) else (item,)
                            
                            for note in notes_to_play:
                                msg = 0x90 | channel | (note << 8) | (vol << 16)
                                winmm.midiOutShortMsg(hMidiOut, msg)
                                active_notes.append((now + note_duration, channel, note))

                tick += 1
                next_tick_time += tick_duration
            else:
                time.sleep(0.001)

        for _, channel, note in active_notes:
            msg = 0x80 | channel | (note << 8)
            winmm.midiOutShortMsg(hMidiOut, msg)
            
        winmm.midiOutClose(hMidiOut)
        for r in readers:
            r.close()

if __name__ == "__main__":
    root = tk.Tk()
    app = RAMOrchestrator(root)
    root.mainloop()