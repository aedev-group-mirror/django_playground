#!/usr/bin/env python3
"""
step2_django42.py
═════════════════
Migrate:  Django 3.2  →  Django 4.2 (LTS)
          django-cms 3.11  →  3.11.x (stays on 3.x branch for now)
          Companion packages updated to 4.2-compatible versions.

Run from your project root:
    python path/to/step2_django42.py --project-root .

IMPORTANT: Python 3.10+ is required for Django 4.2.
"""

import argparse
import re
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from migration_utils import (
    banner, ok, info, warn, backup_sqlite, replace_in_file, replace_in_dir, ensure_setting,
    update_requirements, manage, check_python_version, check_venv, run,
)

# ─────────────────────────────────────────────
# Target package versions
# ─────────────────────────────────────────────
REQUIREMENTS_UPDATES = {
    "Django":                      "==4.2.17",
    "django-classy-tags":          "==4.1.0",
    "django-cms":                  "==3.11.8",   # last 3.x; CMS 4 in step 4
    "django-crispy-forms":         "==2.3",
    "crispy-bootstrap4":           "==2024.1",   # new split package
    "django-filer":                "==3.1.2",
    "django-formtools":            "==2.5.1",
    "django-js-asset":             "==2.0.0",
    "django-mptt":                 "==0.16.0",
    "django-polymorphic":          "==3.1.0",
    "django-sekizai":              "==4.0.0",
    "django-treebeard":            "==4.7.1",
    "djangocms-admin-style":       "==3.2.3",
    "djangocms-attributes-field":  "==3.0.0",
    "djangocms-bootstrap4":        "==2.0.0",
    "djangocms-file":              "==3.0.1",
    "djangocms-googlemap":         "==2.1.1",
    "djangocms-icon":              "==2.1.0",
    "djangocms-link":              "==3.3.1",
    "djangocms-picture":           "==3.1.0",
    "djangocms-style":             "==3.1.0",
    "djangocms-text-ckeditor":     "==4.1.1",
    "djangocms-video":             "==3.1.0",
    "easy-thumbnails":             "==2.9.0",
    "pytz":                        "==2024.1",   # still needed by easy-thumbnails
}

ADDITIONS = [
    "crispy-bootstrap4==2024.1",  # django-crispy-forms split this out
]

REMOVALS: list[str] = []


# ─────────────────────────────────────────────
# Django 4.x Code patches
# ─────────────────────────────────────────────
def patch_csrf_trusted_origins(settings_files: list[Path]):
    """
    Django 4.0: CSRF_TRUSTED_ORIGINS values must now include the scheme.
    e.g. 'example.com' → 'https://example.com'
    We can't know the real origins, so we just warn.
    """
    banner("Checking CSRF_TRUSTED_ORIGINS")
    # noinspection RegExpRedundantEscape
    pattern = re.compile(r"CSRF_TRUSTED_ORIGINS\s*=\s*\[([^\]]*)\]", re.DOTALL)
    for sf in settings_files:
        content = sf.read_text()
        m = pattern.search(content)
        if m:
            entries = [e.strip().strip("\"'") for e in m.group(1).split(",") if e.strip()]
            needs_fix = [e for e in entries if e and not e.startswith(("http://", "https://"))]
            if needs_fix:
                warn(f"  {sf.name}: CSRF_TRUSTED_ORIGINS entries need 'https://' prefix:")
                for e in needs_fix:
                    warn(f"    '{e}'  →  'https://{e}'")
                # Auto-fix
                new_block = m.group(0)
                for e in needs_fix:
                    new_block = new_block.replace(f"'{e}'", f"'https://{e}'")
                    new_block = new_block.replace(f'"{e}"', f'"https://{e}"')
                content = content.replace(m.group(0), new_block)
                sf.write_text(content)
                ok(f"  Auto-fixed CSRF_TRUSTED_ORIGINS in {sf.name}")


def patch_use_l10n(settings_files: list[Path]):
    """
    Django 4.0: USE_L10N defaults to True. Explicitly setting it to False
    was previously required to avoid date-format changes.
    Just warn if it's missing.
    """
    banner("Checking USE_L10N setting")
    for sf in settings_files:
        content = sf.read_text()
        if "USE_L10N" not in content:
            warn(f"  {sf.name}: USE_L10N not set. "
                 "Django 4.0 defaults to True. "
                 "Add USE_L10N = True explicitly to silence warnings.")
            ensure_setting(sf, "USE_L10N", "True")


def patch_use_deprecated_pytz(settings_files: list[Path]):
    """
    Django 4.0 deprecated USE_DEPRECATED_PYTZ (removed in 5.0).
    Ensure it's not set or set to False.
    """
    banner("Patching USE_DEPRECATED_PYTZ")
    for sf in settings_files:
        replace_in_file(sf, "USE_DEPRECATED_PYTZ = True",
                        "USE_DEPRECATED_PYTZ = False  # Migrated: was True")
        ensure_setting(sf, "USE_DEPRECATED_PYTZ", "False")


def patch_removed_features(project_root: Path):
    """
    Django 4.0 hard-removed several deprecated APIs.
    """
    banner("Patching removed Django APIs")

    # ForceStr / force_text removed
    replace_in_dir(project_root, "*.py",
                   "from django.utils.encoding import force_text",
                   "from django.utils.encoding import force_str")
    replace_in_dir(project_root, "*.py",
                   "from django.utils.encoding import smart_text",
                   "from django.utils.encoding import smart_str")
    replace_in_dir(project_root, "*.py", "force_text(", "force_str(")
    replace_in_dir(project_root, "*.py", "smart_text(", "smart_str(")

    # HttpRequest.is_ajax() removed in 4.0
    replace_in_dir(
        project_root, "*.py",
        "request.is_ajax()",
        "request.headers.get('x-requested-with') == 'XMLHttpRequest'",
    )

    # render_to_response removed in 4.0
    replace_in_dir(
        project_root, "*.py",
        "from django.shortcuts import render_to_response",
        "from django.shortcuts import render",
    )
    replace_in_dir(
        project_root, "*.py",
        "from django.template.response import SimpleTemplateResponse",
        "from django.template.response import SimpleTemplateResponse",  # keep
    )

    # django.utils.http.is_safe_url removed in 4.0
    replace_in_dir(
        project_root, "*.py",
        "from django.utils.http import is_safe_url",
        "from django.utils.http import url_has_allowed_host_and_scheme as is_safe_url",
    )

    # FlatPage / sites framework – no action needed here but remind
    for settings in project_root.rglob("*.py"):
        content = settings.read_text(errors="ignore")
        if "from django.contrib.admin.views.decorators import staff_member_required" in content:
            # Still exists in 4.2, just note
            pass

    # PASSWORD_RESET_TIMEOUT_DAYS removed (use PASSWORD_RESET_TIMEOUT in seconds)
    for settings in project_root.rglob("settings*.py"):
        content = settings.read_text()
        if "PASSWORD_RESET_TIMEOUT_DAYS" in content:
            warn(f"  {settings.name}: PASSWORD_RESET_TIMEOUT_DAYS is removed. "
                 "Use PASSWORD_RESET_TIMEOUT (seconds). "
                 "e.g.  PASSWORD_RESET_TIMEOUT = 3 * 24 * 60 * 60")
            replace_in_file(
                settings,
                "PASSWORD_RESET_TIMEOUT_DAYS",
                "# PASSWORD_RESET_TIMEOUT_DAYS (REMOVED) - see PASSWORD_RESET_TIMEOUT\n"
                "PASSWORD_RESET_TIMEOUT",
            )


def patch_crispy_forms(_project_root: Path, settings_files: list[Path]):
    """
    django-crispy-forms 2.x split Bootstrap4 into a separate package.
    settings.py needs CRISPY_TEMPLATE_PACK → CRISPY_ALLOWED_TEMPLATE_PACKS
    and CRISPY_TEMPLATE_PACK = "bootstrap4".
    """
    banner("Patching django-crispy-forms → 2.x API")
    for sf in settings_files:
        content = sf.read_text()
        if "CRISPY_TEMPLATE_PACK" in content:
            # Ensure crispy-bootstrap4 helper addition
            if "CRISPY_ALLOWED_TEMPLATE_PACKS" not in content:
                ensure_setting(sf, "CRISPY_ALLOWED_TEMPLATE_PACKS",
                               '("bootstrap4",)')
        else:
            ensure_setting(sf, "CRISPY_TEMPLATE_PACK", '"bootstrap4"')
            ensure_setting(sf, "CRISPY_ALLOWED_TEMPLATE_PACKS", '("bootstrap4",)')


def patch_formtools(project_root: Path):
    """
    django-formtools 2.5 made SessionWizardView import path canonical.
    No mechanical change needed; just confirm.
    """
    banner("Checking django-formtools usage")
    for p in project_root.rglob("*.py"):
        content = p.read_text(errors="ignore")
        if "formtools.wizard" in content:
            ok(f"  {p}: uses formtools.wizard – OK (path unchanged)")


def patch_admin_site(project_root: Path):
    """
    Django 4.x: AdminSite.each_context() signature changed.
    Catch custom AdminSite subclasses.
    """
    banner("Checking custom AdminSite")
    for p in project_root.rglob("*.py"):
        content = p.read_text(errors="ignore")
        if "class.*AdminSite" in content and "each_context" in content:
            warn(f"  {p}: custom AdminSite.each_context – check signature "
                 "(added `request` param).")


def patch_middleware_security(settings_files: list[Path]):
    """
    Remind about SecurityMiddleware position.
    """
    banner("Checking SecurityMiddleware position")
    for sf in settings_files:
        content = sf.read_text()
        mw_lines = [_line.strip() for _line in content.splitlines() if "Middleware" in _line and "#" not in _line]
        first_mw = next((_line for _line in mw_lines if "SecurityMiddleware" in _line), None)
        if first_mw and mw_lines.index(first_mw) != 0:
            warn(f"  {sf.name}: SecurityMiddleware should be the FIRST "
                 "middleware in the list.")


def patch_re_path_imports(project_root: Path):
    """
    In case step 1 was skipped: catch any remaining conf.urls imports.
    """
    replace_in_dir(
        project_root, "*.py",
        "from django.conf.urls import url",
        "from django.urls import re_path",
    )


def patch_staticfiles_storage(_settings_files: list[Path]):
    """
    Django 4.2 deprecated whitenoise path that many projects used.
    No change needed for default staticfiles storage.
    """
    pass


# ─────────────────────────────────────────────
# Template patches
# ─────────────────────────────────────────────
def patch_templates(project_root: Path):
    """
    Django 4.x template changes:
    - {% load staticfiles %} → {% load static %}  (was deprecated since 2.1, now removed)
    - {% load admin_static %} → {% load static %}
    """
    banner("Patching Django templates")
    for ext in ("*.html", "*.htm"):
        replace_in_dir(project_root, ext,
                       "{% load staticfiles %}", "{% load static %}")
        replace_in_dir(project_root, ext,
                       "{% load admin_static %}", "{% load static %}")
        # CMS placeholders – no change needed at this step


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Step 2 – Upgrade to Django 4.2 LTS")
    parser.add_argument("--project-root", default=".", metavar="DIR")
    parser.add_argument("--requirements", default="requirements.txt")
    parser.add_argument("--settings", default="",
                        help="Comma-separated settings file paths")
    parser.add_argument("--db", default="project.db")
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--skip-migrate",  action="store_true")
    args = parser.parse_args()

    check_python_version((3, 10))
    check_venv()

    root = Path(args.project_root).resolve()
    info(f"Project root: {root}")

    if args.settings:
        settings_files = [root / s.strip() for s in args.settings.split(",")]
    else:
        settings_files = [s for s in root.rglob("settings*.py")
                          if "migration" not in str(s)]
        info(f"Auto-detected settings: {[str(s) for s in settings_files]}")

    backup_sqlite(root / args.db, label="pre_step2")

    req_file = root / args.requirements
    if req_file.exists():
        banner("Updating requirements.txt")
        update_requirements(req_file, REQUIREMENTS_UPDATES,
                            removals=REMOVALS, additions=ADDITIONS)
    else:
        warn(f"Requirements file not found: {req_file}")

    if not args.skip_install and req_file.exists():
        banner("Installing updated packages")
        run(f"{sys.executable} -m pip install -r {req_file}")

    # Code patches
    patch_csrf_trusted_origins(settings_files)
    patch_use_l10n(settings_files)
    patch_use_deprecated_pytz(settings_files)
    patch_removed_features(root)
    patch_re_path_imports(root)
    patch_crispy_forms(root, settings_files)
    patch_formtools(root)
    patch_admin_site(root)
    patch_middleware_security(settings_files)
    patch_templates(root)

    if not args.skip_migrate:
        banner("Running database migrations")
        manage(root, "migrate")

    banner("Step 2 complete ✔")
    print(textwrap.dedent("""
    Next steps:
      1. Run tests: python manage.py test
      2. Check for any remaining DeprecationWarnings in the console.
      3. Verify CSRF_TRUSTED_ORIGINS entries are correct.
      4. Review any PASSWORD_RESET_TIMEOUT changes in settings.
      5. Commit to version control.
      6. Then run:  python step3_django52.py --project-root .
    """))


if __name__ == "__main__":
    main()
