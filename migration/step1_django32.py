#!/usr/bin/env python3
"""
step1_django32.py
═════════════════
Migrate:  Django 3.1  →  Django 3.2 (LTS)
          django-cms 3.8  stays at 3.8.x (patched)
          All companion packages bumped to 3.2-compatible versions.

Run from your project root (where manage.py lives):
    python path/to/step1_django32.py --project-root .
"""

import argparse
import sys
from pathlib import Path

# Allow running from any cwd
sys.path.insert(0, str(Path(__file__).parent))
from migration_utils import (
    banner, ok, info, warn, backup_sqlite, replace_in_dir, ensure_setting, update_requirements,
    manage, check_python_version, check_venv, run,
)

# ─────────────────────────────────────────────
# Package versions for this step
# ─────────────────────────────────────────────
REQUIREMENTS_UPDATES = {
    "Django":                     "==3.2.25",
    "django-classy-tags":         "==3.0.1",   # unchanged, already compatible
    "django-cms":                 "==3.11.8",  # last 3.x LTS release
    "django-crispy-forms":        "==1.14.0",  # unchanged
    "django-filer":               "==3.0.4",
    "django-formtools":           "==2.4",
    "django-js-asset":            "==2.0.0",
    "django-mptt":                "==0.14.0",
    "django-polymorphic":         "==3.1.0",
    "django-sekizai":             "==3.0.1",
    "django-treebeard":           "==4.7.1",
    "djangocms-admin-style":      "==3.2.0",
    "djangocms-attributes-field": "==2.2.0",
    "djangocms-bootstrap4":       "==2.0.0",   # kept, compatible maintained
    "djangocms-file":             "==3.0.0",
    "djangocms-googlemap":        "==2.0.0",
    "djangocms-icon":             "==2.0.0",
    "djangocms-link":             "==3.3.1",
    "djangocms-picture":          "==3.1.0",
    "djangocms-style":            "==3.0.0",
    "djangocms-text-ckeditor":    "==4.1.0",
    "djangocms-video":            "==3.0.0",
    "easy-thumbnails":            "==2.8.5",
}

ADDITIONS = [
    "# Required by Django 3.2+ for explicit default primary key type",
]


# ─────────────────────────────────────────────
# Code patches
# ─────────────────────────────────────────────
def patch_ugettext(project_root: Path):
    """
    Django 3.x deprecated ugettext/ugettext_lazy etc.
    They are REMOVED in Django 4.0, so fix them now.
    """
    banner("Patching deprecated ugettext imports")
    replacements = [
        ("from django.utils.translation import ugettext_lazy",
         "from django.utils.translation import gettext_lazy"),
        ("from django.utils.translation import ugettext_noop",
         "from django.utils.translation import gettext_noop"),
        ("from django.utils.translation import ugettext",
         "from django.utils.translation import gettext"),
        ("django.utils.translation.ugettext_lazy",
         "django.utils.translation.gettext_lazy"),
        ("django.utils.translation.ugettext",
         "django.utils.translation.gettext"),
        # Handle aliased imports like: ugettext_lazy as _
        ("ugettext_lazy as _", "gettext_lazy as _"),
        ("ugettext as _",      "gettext as _"),
    ]
    total = 0
    for old, new in replacements:
        total += replace_in_dir(project_root, "*.py", old, new)
    info(f"ugettext → gettext: {total} total replacements")


def patch_url_patterns(project_root: Path):
    """
    Django 3.1 still allowed old-style `url()` from django.conf.urls.
    Replace with re_path() or path() as appropriate.
    This does a conservative mechanical swap to re_path().
    """
    banner("Patching url() → re_path()")

    # Add re_path import alongside url import where needed
    replace_in_dir(
        project_root, "*.py",
        "from django.conf.urls import url",
        "from django.urls import re_path",
    )
    replace_in_dir(
        project_root, "*.py",
        "from django.conf.urls import include, url",
        "from django.urls import include, re_path",
    )
    replace_in_dir(
        project_root, "*.py",
        "from django.conf.urls import url, include",
        "from django.urls import re_path, include",
    )
    # If only url was imported along with patterns
    replace_in_dir(
        project_root, "*.py",
        "from django.conf.urls import patterns, url",
        "from django.urls import re_path",
    )
    # Rename the call itself (simple non-regex replacement; safe because
    # we already changed the import above)
    replace_in_dir(project_root, "*.py",
                   "    url(", "    re_path(")
    replace_in_dir(project_root, "*.py",
                   "\turl(", "\tre_path(")


def patch_default_auto_field(settings_files: list[Path]):
    """
    Django 3.2 warns if DEFAULT_AUTO_FIELD is not set.
    Add it to each settings file if missing.
    """
    banner("Adding DEFAULT_AUTO_FIELD setting")
    for sf in settings_files:
        ensure_setting(sf, "DEFAULT_AUTO_FIELD", '"django.db.models.AutoField"')


def patch_middleware_order(settings_files: list[Path]):
    """
    django-cms requires LocaleMiddleware to appear after
    SessionMiddleware and before CommonMiddleware.
    Just warn if ordering looks wrong – auto-fix is risky.
    """
    banner("Checking CMS middleware order")
    for sf in settings_files:
        content = sf.read_text(encoding="utf-8")
        mw_list = re.findall(r"'([^']+Middleware[^']*)'", content)
        if not mw_list:
            continue
        names = [m.split(".")[-1] for m in mw_list]
        required_order = [
            "SessionMiddleware",
            "LocaleMiddleware",
            "CommonMiddleware",
            "CsrfViewMiddleware",
        ]
        prev_idx = -1
        ok_order = True
        for name in required_order:
            if name in names:
                idx = names.index(name)
                if idx < prev_idx:
                    ok_order = False
                    warn(f"  {sf.name}: '{name}' appears before expected position.")
                prev_idx = idx
        if ok_order:
            ok(f"  {sf.name}: middleware order looks correct.")


import re  # noqa: E402 – needed for patch_middleware_order


def patch_cms_apphook_pool(project_root: Path):
    """
    CMS 3.9+ deprecates apphook_pool.register in favour of decorators.
    Warn only – mechanical rewrite is out of scope.
    """
    banner("Checking CMS apphook registrations")
    for p in project_root.rglob("cms_apps.py"):
        content = p.read_text()
        if "apphook_pool.register(" in content:
            warn(f"  {p}: uses apphook_pool.register() – "
                 "consider switching to @apphook_pool.register decorator.")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Step 1 – Upgrade to Django 3.2 / django-cms 3.11")
    parser.add_argument("--project-root", default=".", metavar="DIR",
                        help="Path to the Django project root (contains manage.py)")
    parser.add_argument("--requirements", default="requirements.txt",
                        help="Path to requirements file (relative to project root)")
    parser.add_argument("--settings", default="",
                        help="Comma-separated settings file paths to patch "
                             "(relative to project root). "
                             "Auto-discovered if omitted.")
    parser.add_argument("--db", default="project.db",
                        help="SQLite DB file path (relative to project root)")
    parser.add_argument("--skip-install", action="store_true",
                        help="Skip pip install (apply patches only)")
    parser.add_argument("--skip-migrate", action="store_true",
                        help="Skip manage.py migrate")
    args = parser.parse_args()

    check_python_version((3, 8))
    check_venv()

    root = Path(args.project_root).resolve()
    info(f"Project root: {root}")

    # ── Locate settings files ──────────────────
    if args.settings:
        settings_files = [root / s.strip() for s in args.settings.split(",")]
    else:
        settings_files = list(root.rglob("settings*.py"))
        settings_files = [s for s in settings_files
                          if "migration" not in str(s)]
        if settings_files:
            info(f"Auto-detected settings: {[str(s) for s in settings_files]}")
        else:
            warn("No settings files found – skipping settings patches.")

    # ── Backup DB ──────────────────────────────
    backup_sqlite(root / args.db, label="pre_step1")

    # ── Update requirements ────────────────────
    req_file = root / args.requirements
    if req_file.exists():
        banner("Updating requirements.txt")
        update_requirements(req_file, REQUIREMENTS_UPDATES, additions=ADDITIONS)
    else:
        warn(f"Requirements file not found: {req_file}")

    # ── Install packages ───────────────────────
    if not args.skip_install and req_file.exists():
        banner("Installing updated packages")
        run(f"{sys.executable} -m pip install -r {req_file}")

    # ── Code patches ───────────────────────────
    patch_ugettext(root)
    patch_url_patterns(root)
    if settings_files:
        patch_default_auto_field(settings_files)
        patch_middleware_order(settings_files)
    patch_cms_apphook_pool(root)

    # ── Database migrations ────────────────────
    if not args.skip_migrate:
        banner("Running database migrations")
        manage(root, "migrate", "--run-syncdb")

    banner("Step 1 complete ✔")
    print(textwrap.dedent("""
    Next steps:
      1. Run your test suite: python manage.py test
      2. Start the dev server and check the CMS admin.
      3. Fix any remaining deprecation warnings shown in the console.
      4. Commit everything to version control.
      5. Then run:  python step2_django42.py --project-root .
    """))


if __name__ == "__main__":
    import textwrap
    main()
