#!/usr/bin/env python3

import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import json
import os
import threading

# Configuration for BradOS
TARGET = "/mnt"
LIVE_ROOT = "/"  # The running Live ISO root

# =========================
# SYSTEM HELPERS
# =========================
def run(cmd, log=None):
    if log:
        log(f"$ {cmd}")

    process = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    for line in process.stdout:
        if log:
            log(line.strip())

    process.wait()

    if process.returncode != 0:
        raise Exception(f"Command failed: {cmd}")

# =========================
# DISK DETECTION
# =========================
def get_disks():
    try:
        out = subprocess.check_output(
            "lsblk -J -o NAME,SIZE,TYPE,MOUNTPOINT",
            shell=True
        )
        data = json.loads(out)
        return [d for d in data["blockdevices"] if d["type"] == "disk"]
    except Exception:
        return []

# =========================
# PARTITIONING & FORMATTING
# =========================
def partition_disk(disk, log):
    log(f"Wiping and partitioning {disk}...")
    run(f"wipefs -a {disk}", log)
    
    # Using MSDOS/MBR for simplicity in BIOS mode
    run(f"parted {disk} --script mklabel msdos", log)
    run(f"parted {disk} --script mkpart primary ext4 1MiB 100%", log)
    
    return None, disk + "1"

def format_and_mount(efi, root, log):
    log(f"Formatting {root} as ext4...")
    run(f"mkfs.ext4 -F {root}", log)

    os.makedirs(TARGET, exist_ok=True)
    run(f"mount {root} {TARGET}", log)

# =========================
# CORE INSTALLATION LOGIC
# =========================
def install_os(log, progress, selected_disk):
    try:
        progress(10, "Copying system files to disk...")
        
        # RSYNC EXCLUSIONS: Crucial to prevent infinite loops and virtual files
        # We exclude /mnt (the target), /proc, /sys, /dev, and /tmp
        run(f"rsync -a --info=progress2 --exclude='/mnt/*' --exclude='/proc/*' "
            f"--exclude='/sys/*' --exclude='/dev/*' --exclude='/tmp/*' "
            f"{LIVE_ROOT} {TARGET}/", log)

        progress(70, "Installing Limine Bootloader...")
        
        # Create boot directory on target
        os.makedirs(f"{TARGET}/boot", exist_ok=True)
        
        # Copy the injected Limine system files to target
        run(f"cp /usr/share/limine/limine-bios.sys {TARGET}/boot/", log)
        
        # Deploy Limine to the MBR of the selected drive
        run(f"limine bios-install {selected_disk}", log)

        progress(90, "Configuring Bootloader...")

        # Generate target limine.conf
        with open(f"{TARGET}/boot/limine.conf", "w") as f:
            f.write(f"""TIMEOUT=5
GRAPHICS=yes

:BradOS
    PROTOCOL=linux
    KERNEL_PATH=/boot/bzImage
    CMDLINE=root={selected_disk}1 rw
""")

        progress(100, "Installation Successful!")
        messagebox.showinfo("Success", "BradOS has been installed! Please reboot and remove your installation media.")

    except Exception as e:
        messagebox.showerror("Installation Error", str(e))

# =========================
# GUI APPLICATION
# =========================
class Installer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BradOS Installer")
        self.geometry("800x550")
        self.selected_disk = None
        self.frames = {}

        for F in (WelcomePage, DiskPage, InstallPage):
            frame = F(self)
            self.frames[F] = frame
            frame.place(relwidth=1, relheight=1)

        self.show(WelcomePage)

    def show(self, page):
        self.frames[page].tkraise()

class WelcomePage(tk.Frame):
    def __init__(self, root):
        super().__init__(root)
        tk.Label(self, text="Welcome to BradOS", font=("Arial", 24, "bold")).pack(pady=50)
        tk.Label(self, text="This will install the full BradOS environment to your computer.").pack(pady=10)
        tk.Button(self, text="Begin Installation", font=("Arial", 12),
                  command=lambda: root.show(DiskPage), width=20, height=2).pack(pady=40)

class DiskPage(tk.Frame):
    def __init__(self, root):
        super().__init__(root)
        tk.Label(self, text="Select Installation Target", font=("Arial", 18)).pack(pady=20)
        
        self.disks = get_disks()
        self.selected = tk.StringVar()
        options = [f"/dev/{d['name']} ({d['size']})" for d in self.disks]

        self.combo = ttk.Combobox(self, values=options, textvariable=self.selected, width=40, state="readonly")
        self.combo.pack(pady=20)

        tk.Button(self, text="Continue", command=self.confirm, width=15).pack(pady=20)

    def confirm(self):
        if self.combo.current() == -1:
            messagebox.showerror("Error", "Please select a target disk.")
            return

        disk_name = "/dev/" + self.disks[self.combo.current()]["name"]
        if messagebox.askyesno("Confirm Erase", f"Are you sure? All data on {disk_name} will be destroyed."):
            self.master.selected_disk = disk_name
            self.master.show(InstallPage)

class InstallPage(tk.Frame):
    def __init__(self, root):
        super().__init__(root)
        self.label = tk.Label(self, text="Installing BradOS...", font=("Arial", 16))
        self.label.pack(pady=10)

        self.progress = tk.IntVar()
        self.bar = ttk.Progressbar(self, maximum=100, variable=self.progress)
        self.bar.pack(fill="x", padx=40, pady=20)

        self.log_box = tk.Text(self, bg="black", fg="white", font=("Courier", 10))
        self.log_box.pack(fill="both", expand=True, padx=20, pady=10)

        self.btn_start = tk.Button(self, text="Install Now", command=self.start)
        self.btn_start.pack(pady=10)

    def log(self, msg):
        self.log_box.insert(tk.END, msg + "\n")
        self.log_box.see(tk.END)

    def set_progress(self, value, msg):
        self.progress.set(value)
        self.log(msg)

    def start(self):
        self.btn_start.config(state="disabled")
        disk = self.master.selected_disk
        threading.Thread(target=lambda: self.run_install(disk), daemon=True).start()

    def run_install(self, disk):
        try:
            efi, root_part = partition_disk(disk, self.log)
            format_and_mount(efi, root_part, self.log)
            install_os(self.log, self.set_progress, disk)
        except Exception as e:
            messagebox.showerror("Critical Failure", str(e))

if __name__ == "__main__":
    app = Installer()
    app.mainloop()