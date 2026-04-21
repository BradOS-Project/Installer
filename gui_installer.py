#!/usr/bin/env python3

import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import json
import os
import threading

TARGET = "/mnt"
LIVE_ROOT = "/"  # in live ISO this becomes your running OS


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
# DISK DETECTION (lsblk)
# =========================
def get_disks():
    out = subprocess.check_output(
        "lsblk -J -o NAME,SIZE,TYPE,MOUNTPOINT",
        shell=True
    )
    data = json.loads(out)

    disks = []
    for d in data["blockdevices"]:
        if d["type"] == "disk":
            disks.append(d)
    return disks


# =========================
# PARTITIONING
# =========================
def partition_disk(disk, log):
    log("Wiping disk...")

    run(f"wipefs -a {disk}", log)

    if os.path.exists("/sys/firmware/efi"):
        log("UEFI mode detected")

        run(f"parted {disk} --script mklabel gpt", log)
        run(f"parted {disk} --script mkpart ESP fat32 1MiB 512MiB", log)
        run(f"parted {disk} --script set 1 esp on", log)
        run(f"parted {disk} --script mkpart primary ext4 512MiB 100%", log)

        return disk + "1", disk + "2"

    else:
        log("BIOS mode detected")

        run(f"parted {disk} --script mklabel msdos", log)
        run(f"parted {disk} --script mkpart primary ext4 1MiB 100%", log)

        return None, disk + "1"


# =========================
# FORMAT + MOUNT
# =========================
def format_and_mount(efi, root, log):
    if efi:
        run(f"mkfs.fat -F32 {efi}", log)

    run(f"mkfs.ext4 {root}", log)

    os.makedirs(TARGET, exist_ok=True)
    run(f"mount {root} {TARGET}", log)

    if efi:
        os.makedirs(f"{TARGET}/boot/efi", exist_ok=True)
        run(f"mount {efi} {TARGET}/boot/efi", log)


# =========================
# INSTALL OS (THIS IS THE CORE)
# =========================
def install_os(log, progress):
    try:
        progress(10, "Starting install")

        # COPY SYSTEM FILES (THIS IS THE OS INSTALL STEP)
        run(f"rsync -a --info=progress2 {LIVE_ROOT}/ {TARGET}/", log)

        progress(70, "Installing bootloader")

        # placeholder (replace with real limine-install later)
        run("limine-install /dev/sda || true", log)

        progress(90, "Writing config")

        os.makedirs(f"{TARGET}/boot", exist_ok=True)

        with open(f"{TARGET}/boot/limine.conf", "w") as f:
            f.write("""TIMEOUT=5

:MyOS
    PROTOCOL=linux
    KERNEL_PATH=/boot/bzImage
    CMDLINE=root=/dev/sda2 rw
""")

        progress(100, "Done")

        messagebox.showinfo("Success", "Installation complete!")

    except Exception as e:
        messagebox.showerror("Error", str(e))


# =========================
# GUI APP
# =========================
class Installer(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("MyOS Installer")
        self.geometry("750x500")

        self.selected_disk = None

        self.frames = {}

        for F in (WelcomePage, DiskPage, InstallPage):
            frame = F(self)
            self.frames[F] = frame
            frame.place(relwidth=1, relheight=1)

        self.show(WelcomePage)

    def show(self, page):
        self.frames[page].tkraise()


# =========================
# WELCOME PAGE
# =========================
class WelcomePage(tk.Frame):
    def __init__(self, root):
        super().__init__(root)

        tk.Label(self, text="Welcome to MyOS Installer", font=("Arial", 20)).pack(pady=40)

        tk.Button(self, text="Start Installation",
                  command=lambda: root.show(DiskPage)).pack()


# =========================
# DISK SELECTION PAGE
# =========================
class DiskPage(tk.Frame):
    def __init__(self, root):
        super().__init__(root)

        tk.Label(self, text="Select Installation Disk", font=("Arial", 16)).pack(pady=10)

        self.disks = get_disks()
        self.selected = tk.StringVar()

        options = [f"/dev/{d['name']} ({d['size']})" for d in self.disks]

        self.combo = ttk.Combobox(self, values=options, textvariable=self.selected)
        self.combo.pack(pady=10)

        tk.Button(self, text="Continue", command=self.confirm).pack(pady=10)

    def confirm(self):
        if self.combo.current() == -1:
            messagebox.showerror("Error", "Select a disk")
            return

        disk = "/dev/" + self.disks[self.combo.current()]["name"]

        if not messagebox.askyesno("WARNING", "This will ERASE ALL DATA. Continue?"):
            return

        if not messagebox.askyesno("FINAL CONFIRM", "Are you absolutely sure?"):
            return

        self.master.selected_disk = disk
        self.master.show(InstallPage)


# =========================
# INSTALL PAGE
# =========================
class InstallPage(tk.Frame):
    def __init__(self, root):
        super().__init__(root)

        tk.Label(self, text="Installing MyOS...", font=("Arial", 16)).pack(pady=10)

        self.progress = tk.IntVar()

        self.bar = ttk.Progressbar(self, maximum=100, variable=self.progress)
        self.bar.pack(fill="x", padx=20, pady=10)

        self.log_box = tk.Text(self)
        self.log_box.pack(fill="both", expand=True)

        tk.Button(self, text="Start Install", command=self.start).pack(pady=10)

    def log(self, msg):
        self.log_box.insert(tk.END, msg + "\n")
        self.log_box.see(tk.END)

    def set_progress(self, value, msg):
        self.progress.set(value)
        self.log(msg)

    def start(self):
        disk = self.master.selected_disk

        def thread():
            try:
                self.log(f"Installing to {disk}")

                efi, root = partition_disk(disk, self.log)
                format_and_mount(efi, root, self.log)
                install_os(self.log, self.set_progress)

            except Exception as e:
                messagebox.showerror("Error", str(e))

        threading.Thread(target=thread, daemon=True).start()


# =========================
# RUN
# =========================
if __name__ == "__main__":
    app = Installer()
    app.mainloop()