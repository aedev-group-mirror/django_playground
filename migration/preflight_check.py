#!/usr/bin/env python3
"""
preflight_check.py
══════════════════
Run this FIRST, before any migration step.

Analyses your project and produces a comprehensive report of:
  ─ Current package versions
  ─ Python compatibility
  ─ Deprecated APIs in use
  ─ CMS configuration issues
  ─ Database state
  ─ Estimated effort per step

Usage:
    python path/to/preflight_check.py --project-root .
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from migration_utils import banner, ok, info, warn, error


# check helper functions ------------------------------------------------------

def check_python(report: dict):
    banner("Python version")
    v = sys.version_info
    report["python_version"] = f"{v.major}.{v.minor}.{v.micro}"
    if v < (3, 8):
        error(f"Python {v.major}.{v.minor} – too old. Need 3.8+ for Django 3.2, "
              "3.10+ for Django 4.2/5.2.")
        report["python_ok"] = False
    elif v < (3, 10):
        warn(f"Python {v.major}.{v.minor} – OK for Django 3.2/4.0, "
             "but upgrade to 3.10+ before Django 4.2.")
        report["python_ok"] = "partial"
    else:
        ok(f"Python {v.major}.{v.minor}.{v.micro} – good for all migration steps.")
        report["python_ok"] = True


def check_installed_packages(report: dict):
    banner("Installed packages")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "list", "--format=json"],
        capture_output=True, text=True
    )
    packages = {p["name"].lower(): p["version"]
                for p in json.loads(result.stdout)}
    report["packages"] = packages

    key_packages = [
        "django", "django-cms", "djangocms-versioning",
        "django-filer", "easy-thumbnails",
        "djangocms-text-ckeditor", "djangocms-text",
        "djangocms-bootstrap4",
        "django-crispy-forms", "crispy-bootstrap4",
    ]
    for pkg in key_packages:
        ver = packages.get(pkg, "NOT INSTALLED")
        if ver == "NOT INSTALLED":
            info(f"  {pkg}: not installed")
        else:
            ok(f"  {pkg}: {ver}")


def check_requirements_file(root: Path, report: dict):
    banner("requirements.txt")
    req = root / "requirements.txt"
    if not req.exists():
        warn("  requirements.txt not found – looked in project root.")
        # Try to find it
        candidates = list(root.rglob("requirements*.txt"))
        for c in candidates:
            info(f"  Found: {c}")
        report["requirements_file"] = str(candidates[0]) if candidates else None
        return
    report["requirements_file"] = str(req)
    ok(f"  Found: {req}")
    lines = [_line.strip() for _line in req.read_text().splitlines()
             if _line.strip() and not _line.startswith("#")]
    report["requirements_count"] = len(lines)
    info(f"  {len(lines)} requirements listed.")


def check_manage_py(root: Path, report: dict):
    banner("manage.py / project structure")
    mp = root / "manage.py"
    if mp.exists():
        ok(f"  manage.py found at {mp}")
        report["has_manage_py"] = True
        content = mp.read_text()
        # Try to extract settings module
        m = re.search(r'os\.environ\.setdefault\(["\']DJANGO_SETTINGS_MODULE["\'],\s*["\']([\w.]+)["\']', content)
        if m:
            ok(f"  Default settings module: {m.group(1)}")
            report["default_settings_module"] = m.group(1)
    else:
        error("  manage.py not found! Are you in the project root?")
        report["has_manage_py"] = False


def scan_deprecated_apis(root: Path, report: dict):
    banner("Scanning deprecated APIs (all migration steps)")

    findings: dict[str, list[str]] = {}

    patterns = {
        "ugettext_lazy":    ("Step 1", "Replace with gettext_lazy"),
        "ugettext":         ("Step 1", "Replace with gettext"),
        "force_text":       ("Step 2", "Replace with force_str"),
        "smart_text":       ("Step 2", "Replace with smart_str"),
        "render_to_response": ("Step 2", "Replace with render()"),
        "is_safe_url":      ("Step 2", "Replace with url_has_allowed_host_and_scheme"),
        "request.is_ajax": ("Step 2", "Replace with headers check"),
        "url(r'":           ("Step 1", "Replace with re_path()"),
        "from django.conf.urls import url": ("Step 1", "Use from django.urls import re_path"),
        "pytz":             ("Step 3", "Replace with zoneinfo"),
        "USE_DEPRECATED_PYTZ": ("Step 2/3", "Remove this setting"),
        "unique_together":  ("Step 3", "Migrate to UniqueConstraint"),
        "index_together":   ("Step 3", "Migrate to Index"),
        "static_placeholder": ("Step 4", "Rename to page_placeholder"),
        "sideframe":        ("Step 5", "Sideframe removed in CMS 5"),
        "apphook_pool.register(": ("Step 4", "Use decorator form"),
        "PASSWORD_RESET_TIMEOUT_DAYS": ("Step 2", "Use PASSWORD_RESET_TIMEOUT (seconds)"),
    }

    for p in root.rglob("*.py"):
        if ".git" in str(p) or "migrations" in str(p):
            continue
        # noinspection PyBroadException
        try:
            content = p.read_text(errors="ignore")
        except Exception:
            continue
        for pattern, (step, advice) in patterns.items():
            if pattern in content:
                key = f"[{step}] {pattern}"
                if key not in findings:
                    findings[key] = []
                findings[key].append(str(p.relative_to(root)))

    for p in root.rglob("*.html"):
        if ".git" in str(p):
            continue
        # noinspection PyBroadException
        try:
            content = p.read_text(errors="ignore")
        except Exception:
            continue
        html_patterns = {
            "load staticfiles": ("Step 2", "Replace with {% load static %}"),
            "load admin_static": ("Step 2", "Replace with {% load static %}"),
            "static_placeholder": ("Step 4", "Rename to page_placeholder"),
        }
        for pattern, (step, advice) in html_patterns.items():
            if pattern in content:
                key = f"[{step}] {pattern} (template)"
                if key not in findings:
                    findings[key] = []
                findings[key].append(str(p.relative_to(root)))

    report["deprecated_findings"] = findings
    if findings:
        warn(f"  Found {len(findings)} categories of deprecated API usage:")
        for key, files in findings.items():
            print(f"    {key}")
            print(f"      in {len(files)} file(s): {', '.join(files[:3])}"
                  + (" ..." if len(files) > 3 else ""))
    else:
        ok("  No obvious deprecated API usage found!")


def check_cms_config(root: Path, report: dict):
    banner("CMS configuration")
    settings_files = [s for s in root.rglob("settings*.py")
                      if "migration" not in str(s)]

    cms_config = {}
    for sf in settings_files:
        content = sf.read_text(errors="ignore")

        if "CMS_TEMPLATES" in content:
            ok(f"  {sf.name}: CMS_TEMPLATES defined")
            cms_config["has_cms_templates"] = True
        else:
            warn(f"  {sf.name}: CMS_TEMPLATES NOT defined – required")
            cms_config["has_cms_templates"] = False

        if "CMS_LANGUAGES" in content:
            ok(f"  {sf.name}: CMS_LANGUAGES defined")
        else:
            warn(f"  {sf.name}: CMS_LANGUAGES not found")

        if "djangocms_bootstrap4" in content:
            warn(f"  {sf.name}: djangocms_bootstrap4 in INSTALLED_APPS – "
                 "will need Bootstrap migration (Step 4)")
            cms_config["has_bootstrap4"] = True

        if "djangocms_text_ckeditor" in content:
            info(f"  {sf.name}: djangocms_text_ckeditor present – "
                 "will be replaced by djangocms_text (Step 4)")
            cms_config["has_text_ckeditor"] = True

        if "CMS_PERMISSION" in content:
            ok(f"  {sf.name}: CMS_PERMISSION defined")

    report["cms_config"] = cms_config


def check_database(root: Path, db_path: str, report: dict):
    banner("Database")
    db = root / db_path
    if not db.exists():
        # Try common names
        for candidate in ["db.sqlite3", "database.db", "dev.db"]:
            candidate_path = root / candidate
            if candidate_path.exists():
                db = candidate_path
                break
        else:
            warn(f"  Database not found at {root / db_path}")
            report["db_found"] = False
            return

    size_mb = db.stat().st_size / (1024 * 1024)
    ok(f"  Database: {db} ({size_mb:.1f} MB)")
    report["db_found"] = True
    report["db_path"] = str(db)
    report["db_size_mb"] = round(size_mb, 2)

    if size_mb > 100:
        warn("  Large database – migrations may take a while. "
             "Consider running steps during low-traffic periods.")


def check_media_files(root: Path, report: dict):
    banner("Media files")
    # Common locations
    for media_dir in ["media", "uploads", "files"]:
        candidate = root / media_dir
        if candidate.exists():
            files = list(candidate.rglob("*"))
            file_count = sum(1 for f in files if f.is_file())
            ok(f"  Media dir: {candidate} ({file_count} files)")
            report["media_dir"] = str(candidate)
            report["media_file_count"] = file_count
            return
    warn("  No media directory found (MEDIA_ROOT not auto-detected).")


def estimate_effort(report: dict) -> dict:
    """
    Give a rough effort estimate per step based on findings.
    """
    findings = report.get("deprecated_findings", {})

    def count_findings_for_step(step_label: str) -> int:
        return sum(len(v) for k, v in findings.items()
                   if step_label in k)

    effort = {
        "Step 1 (→ Django 3.2)": f"~{1 + count_findings_for_step('Step 1')} hours",
        "Step 2 (→ Django 4.2)": f"~{2 + count_findings_for_step('Step 2')} hours",
        "Step 3 (→ Django 5.2)": f"~{1 + count_findings_for_step('Step 3')} hours",
        "Step 4 (→ CMS 4)":      "~4-8 hours (major architectural change)",
        "Step 5 (→ CMS 5)":      f"~{1 + count_findings_for_step('Step 5')} hours",
        "Total estimate":        "~10-20 hours depending on codebase complexity",
    }
    if report.get("cms_config", {}).get("has_bootstrap4"):
        effort["Bootstrap4 migration (Step 4)"] = (
            "~2-4 EXTRA hours – manual Bootstrap4 plugin content migration"
        )
    return effort


def write_report(root: Path, report: dict):
    """Write the full report to a Markdown file."""
    report_path = root / "migration_preflight_report.md"
    lines = [
        "# Django / CMS Migration Pre-flight Report",
        "",
        f"**Python**: {report.get('python_version', 'unknown')}",
        f"**Python OK**: {report.get('python_ok', 'unknown')}",
        f"**Database**: {report.get('db_path', 'not found')} "
        f"({report.get('db_size_mb', '?')} MB)",
        f"**Media files**: {report.get('media_file_count', '?')} files",
        "",
        "## Deprecated API Findings",
        "",
    ]
    findings = report.get("deprecated_findings", {})
    if findings:
        for key, files in findings.items():
            lines.append(f"### `{key}`")
            for f in files:
                lines.append(f"- `{f}`")
            lines.append("")
    else:
        lines.append("_No obvious deprecated APIs found._\n")

    lines += [
        "## Effort Estimates",
        "",
    ]
    for step, est in estimate_effort(report).items():
        lines.append(f"- **{step}**: {est}")

    lines += [
        "",
        "## Installed Packages",
        "",
        "| Package | Version |",
        "| ------- | ------- |",
    ]
    for pkg, ver in sorted(report.get("packages", {}).items()):
        lines.append(f"| {pkg} | {ver} |")

    report_path.write_text("\n".join(lines) + "\n")
    ok(f"\n  Full report written to: {report_path}")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Pre-flight check before starting the migration")
    parser.add_argument("--project-root", default=".", metavar="DIR")
    parser.add_argument("--db", default="project.db")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    info(f"Project root: {root}")

    report: dict = {}

    check_python(report)
    check_installed_packages(report)
    check_requirements_file(root, report)
    check_manage_py(root, report)
    scan_deprecated_apis(root, report)
    check_cms_config(root, report)
    check_database(root, args.db, report)
    check_media_files(root, report)

    banner("Effort Estimates")
    for step, est in estimate_effort(report).items():
        info(f"  {step}: {est}")

    write_report(root, report)

    banner("Pre-flight complete")
    print(
        "\nReview migration_preflight_report.md, then begin with:\n"
        "  python step1_django32.py --project-root .\n"
    )


if __name__ == "__main__":
    main()
