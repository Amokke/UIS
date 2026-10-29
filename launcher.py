import customtkinter as ctk
import subprocess
import sys
import os
import json
import winreg
import re
from pathlib import Path
from typing import Optional, Tuple

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

CONFIG_FILE = "apps.json"
INSTALLERS_DIR = "installers"

def parse_uninstall_string(uninstall_str: str) -> Tuple[str, list[str]]:
    """Разбирает UninstallString на путь и аргументы."""
    # Часто бывает: '"C:\Program Files\...\uninstall.exe" /S'
    match = re.match(r'^"(.*?)"\s*(.*)$', uninstall_str.strip())
    if match:
        path = match.group(1)
        args = match.group(2).split()
    else:
        # Если нет кавычек: C:\...\uninstall.exe /S
        parts = uninstall_str.split()
        path = parts[0]
        args = parts[1:]
    return path, args

def get_uninstall_command(app) -> Optional[list[str]]:
    uninstall_key = app.get("uninstall_key")
    uninstall_value = app.get("uninstall_value")
    if not uninstall_key or not uninstall_value:
        return None

    try:
        if uninstall_key.startswith("HKEY_LOCAL_MACHINE"):
            root = winreg.HKEY_LOCAL_MACHINE
            subkey = uninstall_key[len("HKEY_LOCAL_MACHINE\\"):]
        elif uninstall_key.startswith("HKEY_CURRENT_USER"):
            root = winreg.HKEY_CURRENT_USER
            subkey = uninstall_key[len("HKEY_CURRENT_USER\\"):]
        else:
            return None

        with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ) as key:
            uninstall_str, _ = winreg.QueryValueEx(key, uninstall_value)
            path, args = parse_uninstall_string(uninstall_str)
            # Добавляем тихий режим, если его нет
            if "/S" not in args and "/silent" not in args.lower() and "/qn" not in args:
                args.append("/S")
            return [path] + args
    except Exception:
        return None

def check_installed(reg_key: str, reg_value: str | None) -> bool:
    if not reg_key:
        return False
    try:
        if reg_key.startswith("HKEY_LOCAL_MACHINE"):
            root = winreg.HKEY_LOCAL_MACHINE
            subkey = reg_key[len("HKEY_LOCAL_MACHINE\\"):]
        elif reg_key.startswith("HKEY_CURRENT_USER"):
            root = winreg.HKEY_CURRENT_USER
            subkey = reg_key[len("HKEY_CURRENT_USER\\"):]
        else:
            return False

        with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ) as key:
            if reg_value:
                winreg.QueryValueEx(key, reg_value)
            return True
    except FileNotFoundError:
        return False
    except Exception:
        return False

# Простая эвристика версии: ищем цифры в строке и сравниваем.
def version_compare(installed_ver: str | None, target_ver: str) -> int:
    def extract_nums(v: str | None):
        if not v:
            return []
        nums = re.findall(r'\d+', v)
        return [int(x) for x in nums]

    i = extract_nums(installed_ver)
    t = extract_nums(target_ver)

    # Если не смогли вытащить цифры — считаем, что версии разные
    if not i or not t:
        return -1 if not i else 1

    for a, b in zip(i, t):
        if a < b:
            return -1
        if a > b:
            return 1
    # Если все совпало до длины меньшей, но одна длиннее — считаем большей
    if len(i) < len(t):
        return -1
    if len(i) > len(t):
        return 1
    return 0

def get_installed_version(app) -> str | None:
    # Можно добавить чтение DisplayVersion из Uninstall-ключа — это самый надёжный способ.
    # Для простоты пока не делаем, но можно дописать.
    return None

class InstallerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Мой аналог MInstAll (Install/Uninstall/Update)")
        self.geometry("700x650")

        self.apps = []
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.apps = data.get("apps", [])
        except Exception as e:
            self.log(f"❌ Ошибка загрузки {CONFIG_FILE}: {e}", "red")

        if not self.apps:
            lbl_error = ctk.CTkLabel(self, text="Не найдено приложений в apps.json", text_color="red")
            lbl_error.pack(pady=20)
            return

        # Верхняя панель
        panel = ctk.CTkFrame(self)
        panel.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(panel, text="Приложения", font=("Arial", 16, "bold")).pack(side="left", padx=(0,20))

        btn_install = ctk.CTkButton(panel, text="Установить", command=self.install_selected, width=120, height=40)
        btn_install.pack(side="left")

        btn_uninstall = ctk.CTkButton(panel, text="Удалить", command=self.uninstall_selected, width=120, height=40, fg_color="#a12a2a")
        btn_uninstall.pack(side="left", padx=5)

        btn_update = ctk.CTkButton(panel, text="Обновить", command=self.update_selected, width=120, height=40, fg_color="#d39f1e")
        btn_update.pack(side="left", padx=5)

        # Список с чекбоксами
        self.check_vars = {}
        self.status_labels = {}

        list_frame = ctk.CTkScrollableFrame(self, label_text="Список программ")
        list_frame.pack(fill="both", expand=True, padx=10, pady=5)

        for app in self.apps:
            row = ctk.CTkFrame(list_frame)
            row.pack(fill="x", pady=4)

            var = ctk.StringVar()
            cb = ctk.CTkCheckBox(row, text=app["name"], variable=var, command=lambda v=var: self.on_check(v))
            cb.pack(side="left", padx=10)
            self.check_vars[app["name"]] = {"var": var, "app": app}

            lbl = ctk.CTkLabel(row, text="...", width=200)
            lbl.pack(side="right", padx=20)
            self.status_labels[app["name"]] = lbl

        self.refresh_statuses()

        # Лог
        self.log_text = ctk.CTkTextbox(self, height=220, font=("Consolas", 11))
        self.log_text.pack(fill="both", expand=False, padx=10, pady=10)
        self.log("Готов к работе. Выберите программы и нажмите Установить/Удалить/Обновить.")

    def on_check(self, var):
        pass  # можно добавить подсветку строки при выборе

    def refresh_statuses(self):
        for name, data in self.status_labels.items():
            app = self.check_vars[name]["app"]
            installed = check_installed(app.get("reg_key"), app.get("reg_value"))
            target_ver = app.get("version")
            inst_ver = get_installed_version(app)
            cmp = version_compare(inst_ver, target_ver)

            if installed and cmp == 0:
                status = "✅ Установлено (актуальная версия)"
                color = "green"
            elif installed and cmp < 0:
                status = "🟡 Установлено (требуется обновление)"
                color = "orange"
            elif installed:
                # cmp > 0 — у пользователя версия новее, чем в конфиге
                status = "ℹ️ Установлено (версия новее, чем в списке)"
                color = "gray"
            else:
                status = "⬜ Не установлено"
                color = "white"

            data.configure(text=status, text_color=color)

    def log(self, msg: str, color: str = "white"):
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")

    def get_selected_apps(self):
        selected = []
        for name, data in self.check_vars.items():
            if data["var"].get() == "1":
                selected.append(data["app"])
        return selected

    def install_selected(self):
        apps = self.get_selected_apps()
        if not apps:
            self.log("⚠️ Ничего не выбрано для установки", "orange")
            return
        for app in apps:
            self.run_install(app)
        self.refresh_statuses()

    def uninstall_selected(self):
        apps = self.get_selected_apps()
        if not apps:
            self.log("⚠️ Ничего не выбрано для удаления", "orange")
            return
        for app in apps:
            self.run_uninstall(app)
        self.refresh_statuses()

    def update_selected(self):
        apps = self.get_selected_apps()
        if not apps:
            self.log("⚠️ Ничего не выбрано для обновления", "orange")
            return
        for app in apps:
            # Обновление = удалить + установить
            self.run_uninstall(app)
            self.run_install(app)
        self.refresh_statuses()

    def run_install(self, app):
        installer_path = Path(INSTALLERS_DIR) / app["file"]
        if not installer_path.exists():
            self.log(f"❌ Файл не найден: {installer_path}", "red")
            return

        if check_installed(app.get("reg_key"), app.get("reg_value")):
            self.log(f"⚠️ {app['name']} уже установлен. Пропускаем установку.", "orange")
            return

        self.log(f"🚀 Установка: {app['name']}")
        try:
            if app["type"] == "msi":
                cmd = ["msiexec", "/i", str(installer_path.absolute())]
                if app.get("args"):
                    cmd.extend(app["args"].split())
            else:
                cmd = [str(installer_path.absolute())]
                if app.get("args"):
                    cmd.extend(app["args"].split())

            self.log(f"📜 Команда: {' '.join(cmd)}")
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if proc.returncode == 0 or proc.returncode == 3010:
                self.log(f"✅ Установлено: {app['name']}", "green")
            else:
                self.log(f"❌ Ошибка установки (код {proc.returncode})", "red")
                if proc.stderr:
                    self.log(proc.stderr)
        except subprocess.TimeoutExpired:
            self.log("❌ Превышено время ожидания (10 мин)", "red")
        except Exception as e:
            self.log(f"❌ Исключение: {e}", "red")

    def run_uninstall(self, app):
        cmd = get_uninstall_command(app)
        if not cmd:
            self.log(f"❌ Не удалось получить команду удаления для: {app['name']}. Проверьте uninstall_key/uninstall_value в apps.json.", "red")
            return

        self.log(f"🗑️ Удаление: {app['name']}")
        self.log(f"📜 Команда: {' '.join(cmd)}")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if proc.returncode == 0 or proc.returncode == 1605:  # 1605 — компонент уже удалён
                self.log(f"✅ Удалено: {app['name']}", "green")
            else:
                self.log(f"❌ Ошибка удаления (код {proc.returncode})", "red")
                if proc.stderr:
                    self.log(proc.stderr)
        except subprocess.TimeoutExpired:
            self.log("❌ Превышено время ожидания удаления (5 мин)", "red")
        except Exception as e:
            self.log(f"❌ Исключение: {e}", "red")

if __name__ == "__main__":
    # ВАЖНО: запускать от имени администратора
    app = InstallerApp()
    app.mainloop()
