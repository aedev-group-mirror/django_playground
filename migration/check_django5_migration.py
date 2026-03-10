""" check project migrated to latest Django LTS Version 5.x """
import sys
import sqlite3
import subprocess
from importlib.metadata import version, PackageNotFoundError


def is_version_at_least(current, minimum):
    """Einfacher Vergleich von Versionsnummern-Strings."""
    c = [int(x) for x in current.split('.')[:3] if x.isdigit()]
    m = [int(x) for x in minimum.split('.')[:3] if x.isdigit()]
    return c >= m


def check_compatibility():
    print("--- Django Upgrade Compatibility Check (Modern) ---")

    # 1. Python Version Check
    py_ver = sys.version_info
    print(f"[*] Python Version: {py_ver.major}.{py_ver.minor}.{py_ver.micro}")
    if py_ver < (3, 10):
        print("    [!] ERROR: Django 5.x/6.x benötigt mindestens Python 3.10.")
    else:
        print("    [+] OK")

    # 2. SQLite Version Check
    sqlite_ver = sqlite3.sqlite_version
    print(f"[*] SQLite Version: {sqlite_ver}")
    if not is_version_at_least(sqlite_ver, "3.31.0"):
        print("    [!] ERROR: Für Django 5+ wird SQLite 3.31.0+ benötigt.")
    else:
        print("    [+] OK")

    # 3. Check for Critical Packages
    critical_packages = {
        'django-cms': '4.1.0',
        'django-filer': '3.0.0',
        'djangocms-text-ckeditor': '5.1.0',
        'easy-thumbnails': '2.8.5'
    }

    print("[*] Prüfe installierte Pakete via importlib.metadata...")
    for pkg, min_ver in critical_packages.items():
        try:
            current_ver = version(pkg)
            if not is_version_at_least(current_ver, min_ver):
                print(f"    [!] WARNUNG: {pkg} ist Version {current_ver}. Empfohlen: >= {min_ver}")
            else:
                print(f"    [+] {pkg} ({current_ver}) ist bereit.")
        except PackageNotFoundError:
            print(f"    [-] {pkg} ist nicht installiert.")

    # 4. Pip Check
    print("[*] Führe 'pip check' für Abhängigkeitskonflikte aus...")
    try:
        result = subprocess.run(['pip', 'check'], capture_output=True, text=True)
        if result.returncode == 0:
            print("    [+] Keine Paketkonflikte gefunden.")
        else:
            print(f"    [!] KONFLIKT GEFUNDEN:\n{result.stdout}")
    except FileNotFoundError:
        print("    [!] Fehler: 'pip' Befehl nicht gefunden.")


if __name__ == "__main__":
    check_compatibility()