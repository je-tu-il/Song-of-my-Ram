import tkinter as tk
import ctypes
from ctypes import wintypes
import threading
import psutil
import sys
import numpy as np
from PIL import Image, ImageTk

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

class RAMVisualizer:
    def __init__(self, root):
        self.root = root
        self.root.title("RAM Image Renderer (Static)")
        
        self.width = 256
        self.height = 256
        self.required_pixels = self.width * self.height
        
        self.palette = np.array([
            [255, 255, 255],
            [255, 0, 0],
            [0, 255, 0],
            [0, 0, 255],
            [255, 255, 0],
            [0, 255, 255],
            [255, 0, 255],
            [128, 128, 128]
        ], dtype=np.uint8)
        
        self.is_processing = False
        self.target_pid = self.get_largest_process()
        
        self.canvas = tk.Label(root, width=self.width, height=self.height, bg="black")
        self.canvas.pack(pady=10, padx=10)
        
        frame_btn = tk.Frame(root)
        frame_btn.pack(pady=5)
        tk.Button(frame_btn, text="Générer Image", command=self.generate_image).pack(padx=5)

    def get_largest_process(self):
        max_rss = 0
        target = None
        for proc in psutil.process_iter(['pid', 'memory_info']):
            try:
                rss = proc.info['memory_info'].rss
                pid = proc.info['pid']
                
                handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    if rss > max_rss:
                        max_rss = rss
                        target = pid
            except:
                continue
        return target

    def generate_image(self):
        if not self.is_processing and self.target_pid:
            self.is_processing = True
            threading.Thread(target=self.extract_and_render, daemon=True).start()

    def update_ui(self, img):
        img_tk = ImageTk.PhotoImage(img)
        self.canvas.img_tk = img_tk 
        self.canvas.config(image=img_tk)
        self.is_processing = False

    def extract_and_render(self):
        process_handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, self.target_pid)
        if not process_handle:
            self.root.after(0, lambda: setattr(self, 'is_processing', False))
            return

        address = 0
        mbi = MEMORY_BASIC_INFORMATION()
        
        accumulated_data = []
        collected_count = 0

        while collected_count < self.required_pixels:
            if not kernel32.VirtualQueryEx(process_handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)):
                break
                
            base_addr = mbi.BaseAddress or 0
            region_end = base_addr + mbi.RegionSize

            if mbi.State == MEM_COMMIT and not (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)):
                read_size = min(mbi.RegionSize, 1024 * 1024) 
                buffer = ctypes.create_string_buffer(read_size)
                bytes_read = ctypes.c_size_t(0)
                
                success = kernel32.ReadProcessMemory(process_handle, ctypes.c_void_p(base_addr), buffer, read_size, ctypes.byref(bytes_read))
                
                if success and bytes_read.value > 0:
                    raw_data = np.frombuffer(buffer.raw[:bytes_read.value], dtype=np.uint8)
                    
                    non_zero_data = raw_data[raw_data != 0]
                    
                    if non_zero_data.size > 0:
                        accumulated_data.append(non_zero_data)
                        collected_count += non_zero_data.size
            
            address = region_end

        kernel32.CloseHandle(process_handle)
        
        if collected_count > 0:
            full_data = np.concatenate(accumulated_data)
            final_pixels = full_data[:self.required_pixels]
            
            if final_pixels.size < self.required_pixels:
                padding = np.zeros(self.required_pixels - final_pixels.size, dtype=np.uint8)
                final_pixels = np.concatenate((final_pixels, padding))
                
            indices = final_pixels % len(self.palette)
            rgb_data = self.palette[indices].reshape((self.height, self.width, 3))
            
            img = Image.fromarray(rgb_data, 'RGB')
            self.root.after(0, self.update_ui, img)
        else:
            self.root.after(0, lambda: setattr(self, 'is_processing', False))

if __name__ == "__main__":
    root = tk.Tk()
    app = RAMVisualizer(root)
    root.mainloop()