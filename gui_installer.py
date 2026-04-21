#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import json
import os
import threading
import shlex

TARGET = "/mnt"
LIVE_ROOT = "/"

def run(cmd, log=None):
    """Execute a shell command and stream output to log."""
    if log:
        log(f"$ {cmd}")
    args = cmd if isinstance(cmd, list) else shlex.split(cmd)
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in process.stdout:
        if log:
            log(line.strip())
    process.wait()
    if process.returncode != 0:
        raise Exception(f"Command failed: {cmd}")

def get_disks():
    try:
        out = subprocess.check_output("lsblk -J -o NAME,SIZE,TYPE,MOUNTPOINT", shell=True)
        data = json.loads(out)
        return [d for d in data["blockdevices"] if d["type"] == "disk"]
    except:
        return []

def partition_disk(disk, log):
    log(f"Wiping {disk}...")
    run(f"wipefs -a {disk}", log)
    run(f"parted {disk} --script mklabel msdos", log)
    run(f"parted {disk} --script mkpart primary ext4 1MiB 100%", log)
    return disk + "1"

def install_os(log, progress, disk):
    try:
        progress(10, "Preparing partitions...")
        root_part = partition_disk(disk, log)
        run(f"mkfs.ext4 -F {root_part}", log)
        os.makedirs(TARGET, exist_ok=True)
        run(f"mount {root_part} {TARGET}", log)

        progress(30, "Copying system files (Live to Disk)...")
        exclude_opts = [
            "--exclude=/mnt",
            "--exclude=/proc",
            "--exclude=/sys",
            "--exclude=/dev",
            "--exclude=/tmp",
            "--exclude=/run",
            "--exclude=/lost+found"
        ]
        run(["rsync", "-a", "--info=progress2"] + exclude_opts + [LIVE_ROOT, TARGET + "/"], log)

        progress(70, "Post-install: Removing installer & adding browser...")
        target_desktop = f"{TARGET}/root/Desktop"
        install_desktop = f"{target_desktop}/Install.desktop"
        if os.path.exists(install_desktop):
            os.remove(install_desktop)

        os.makedirs(target_desktop, exist_ok=True)
        browser_desktop = f"{target_desktop}/Browser.desktop"
        with open(browser_desktop, "w") as f:
            f.write("[Desktop Entry]\nName=Web Browser\nExec=midori\nIcon=web-browser\nType=Application\nTerminal=false\n")
        os.chmod(browser_desktop, 0o755)

        xinitrc_path = f"{TARGET}/root/.xinitrc"
        with open(xinitrc_path, "w") as f:
            f.write("fluxbox &\npcmanfm --desktop &\nmidori &\n")

        progress(85, "Installing Bootloader...")
        os.makedirs(f"{TARGET}/boot", exist_ok=True)
        run(f"cp /usr/share/limine/limine-bios.sys {TARGET}/boot/", log)
        run(["limine", "bios-install", disk], log)

        progress(95, "Finalizing config...")
        with open(f"{TARGET}/boot/limine.conf", "w") as f:
            f.write(f"TIMEOUT=5\nGRAPHICS=yes\n\n:BradOS\n    PROTOCOL=linux\n    KERNEL_PATH=/boot/bzImage\n    CMDLINE=root={root_part} rw\n")

        progress(100, "Done!")
        messagebox.showinfo("Success", "BradOS installed! The installer has been removed from the target. Reboot now.")
    except Exception as e:
        messagebox.showerror("Error", str(e))

class Installer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BradOS Installer")
        self.geometry("700x500")
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
        tk.Label(self, text="BradOS v1.0", font=("Arial", 28)).pack(pady=50)
        tk.Button(self, text="Start Installation", command=lambda: root.show(DiskPage), height=2, width=20).pack()

class DiskPage(tk.Frame):
    def __init__(self, root):
        super().__init__(root)
        tk.Label(self, text="Select Target Drive", font=("Arial", 14)).pack(pady=20)
        self.disks = get_disks()
        options = [f"/dev/{d['name']} ({d['size']})" for d in self.disks]
        self.combo = ttk.Combobox(self, values=options, state="readonly", width=40)
        self.combo.pack(pady=10)
        tk.Button(self, text="Continue", command=self.confirm).pack(pady=20)

    def confirm(self):
        if self.combo.current() == -1:
            return
        self.master.selected_disk = "/dev/" + self.disks[self.combo.current()]["name"]
        if messagebox.askyesno("Confirm", "Format drive? All data will be lost."):
            self.master.show(InstallPage)

class InstallPage(tk.Frame):
    def __init__(self, root):
        super().__init__(root)
        self.prog_val = tk.IntVar()
        ttk.Progressbar(self, variable=self.prog_val, maximum=100).pack(fill="x", padx=30, pady=20)
        self.log_box = tk.Text(self, height=15, bg="black", fg="green")
        self.log_box.pack(fill="both", padx=30)
        tk.Button(self, text="Begin", command=self.start).pack(pady=10)

    def start(self):
        threading.Thread(target=lambda: install_os(self.log, self.set_prog, self.master.selected_disk), daemon=True).start()

    def log(self, m):
        self.log_box.insert("end", m + "\n")
        self.log_box.see("end")

    def set_prog(self, v, m):
        self.prog_val.set(v)
        self.log(m)

if __name__ == "__main__":
    Installer().mainloop()