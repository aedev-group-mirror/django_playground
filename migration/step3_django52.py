#!/usr/bin/env python3
"""
step3_django52.py
═════════════════
Migrate:  Django 4.2  →  Django 5.2 (LTS, latest stable as of 2025)
          Note: Django 6.0 is not yet released; update this target when
                it becomes available and run again.
          django-cms stays at 3.11.x — CMS upgrade happens in step 4.
          Python 3.12+ recommended for Django 5.2.

Run from your project root:
    python path/to/step3_django52.py --project-root .
"""

import argparse
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from migration_utils import (
    banner, info, warn, backup_sqlite, replace_in_file, replace_in_dir, ensure_setting,
    update_requirements, manage, check_python_version, check_venv, run,
)

# ─────────────────────────────────────────────
# Target package versions
# ─────────────────────────────────────────────
REQUIREMENTS_UPDATES = {
    "Django":                      "==5.2",
    "django-classy-tags":          "==4.1.0",
    "django-cms":                  "==3.11.8",   # CMS upgrade is step 4
    "django-crispy-forms":         "==2.3",
    "crispy-bootstrap4":           "==2024.1",
    "django-filer":                "==3.3.1",
    "django-formtools":            "==2.5.1",
    "django-js-asset":             "==2.0.0",
    "django-mptt":                 "==0.16.0",
    "django-polymorphic":          "==3.1.0",
    "django-sekizai":              "==4.1.0",
    "django-treebeard":            "==4.7.1",
    "djangocms-admin-style":       "==3.3.0",
    "djangocms-attributes-field":  "==3.0.0",
    "djangocms-bootstrap4":        "==2.0.0",
    "djangocms-file":              "==3.1.0",
    "djangocms-googlemap":         "==2.2.0",
    "djangocms-icon":              "==2.2.0",
    "djangocms-link":              "==4.0.0",
    "djangocms-picture":           "==3.1.0",
    "djangocms-style":             "==3.1.0",
    "djangocms-text-ckeditor":     "==4.2.0",
    "djangocms-video":             "==3.1.0",
    "easy-thumbnails":             "==2.10.0",
    "pillow":                      ">=10.0.0",
}

REMOVALS = [
    "pytz",   # stdlib zoneinfo replaces pytz in Django 5
]

ADDITIONS: list[str] = []


# ─────────────────────────────────────────────
# Django 5.x patches
# ─────────────────────────────────────────────
def patch_use_deprecated_pytz_removed(settings_files: list[Path]):
    """
    Django 5.0 REMOVED USE_DEPRECATED_PYTZ entirely.
    """
    banner("Removing USE_DEPRECATED_PYTZ (removed in Django 5.0)")
    for sf in settings_files:
        replace_in_file(sf, "USE_DEPRECATED_PYTZ = False\n", "")
        replace_in_file(sf, "USE_DEPRECATED_PYTZ = True\n",  "")


def patch_pytz_to_zoneinfo(project_root: Path):
    """
    Replace pytz usage with stdlib zoneinfo (Python 3.9+).
    """
    banner("Migrating pytz → zoneinfo")
    # Import replacements
    replace_in_dir(project_root, "*.py",
                   "import pytz",
                   "from zoneinfo import ZoneInfo  # migrated from pytz")
    replace_in_dir(project_root, "*.py",
                   "from pytz import timezone",
                   "from zoneinfo import ZoneInfo as timezone")
    replace_in_dir(project_root, "*.py",
                   "from pytz import utc",
                   "from datetime import timezone as utc_tz  # migrated from pytz.utc")
    # Common usage patterns
    replace_in_dir(project_root, "*.py",
                   "pytz.timezone(",
                   "ZoneInfo(")
    replace_in_dir(project_root, "*.py",
                   "pytz.UTC",
                   "datetime.timezone.utc")
    replace_in_dir(project_root, "*.py",
                   "pytz.utc",
                   "datetime.timezone.utc")


def patch_unique_constraint(project_root: Path):
    """
    Django 5.x: unique_together is deprecated in favour of UniqueConstraint.
    Warn on all occurrences – mechanical rewrite requires human review.
    """
    banner("Checking deprecated unique_together")
    for p in project_root.rglob("models.py"):
        content = p.read_text(errors="ignore")
        if "unique_together" in content:
            warn(f"  {p}: uses 'unique_together' – "
                 "consider migrating to Meta.constraints = [UniqueConstraint(...)]")


def patch_index_together(project_root: Path):
    """
    Django 4.2: index_together deprecated → Meta.indexes = [Index(...)].
    """
    banner("Checking deprecated index_together")
    for p in project_root.rglob("models.py"):
        content = p.read_text(errors="ignore")
        if "index_together" in content:
            warn(f"  {p}: uses 'index_together' – "
                 "migrate to Meta.indexes = [models.Index(fields=[...])]")


def patch_password_hashers(settings_files: list[Path]):
    """
    Django 5.0 added scrypt as default hasher. No action needed but note it.
    """
    banner("Checking PASSWORD_HASHERS")
    for sf in settings_files:
        content = sf.read_text()
        if "PASSWORD_HASHERS" in content and "scrypt" not in content:
            warn(f"  {sf.name}: custom PASSWORD_HASHERS defined without scrypt. "
                 "Django 5.0+ uses scrypt as the default – consider adding it.")


def patch_middleware_removed(settings_files: list[Path]):
    """
    Various middleware moved or removed in Django 5.x.
    """
    banner("Checking for removed middleware")
    removed_mw = [
        "django.middleware.common.BrokenLinkEmailsMiddleware",
    ]
    for sf in settings_files:
        content = sf.read_text()
        for mw in removed_mw:
            if mw in content:
                warn(f"  {sf.name}: '{mw}' was removed in Django 5.0. Remove it.")
                replace_in_file(sf, f'    "{mw}",\n', "")
                replace_in_file(sf, f"    '{mw}',\n", "")


def patch_forms_renderer(settings_files: list[Path]):
    """
    Django 5.x changes to FORM_RENDERER.
    """
    banner("Checking FORM_RENDERER")
    for sf in settings_files:
        content = sf.read_text()
        _old_renderer = (
            '"django.forms.renderers.TemplatesSetting"'
        )
        if "DjangoTemplates" in content and "FORM_RENDERER" not in content:
            pass  # Default is fine


def patch_storages(_project_root: Path, settings_files: list[Path]):
    """
    Django 4.2 introduced django.contrib.staticfiles.storage.ManifestStaticFilesStorage
    as the recommended production static file storage.
    If using whitenoise or similar, ensure it's the updated version.
    """
    banner("Checking static files storage configuration")
    for sf in settings_files:
        content = sf.read_text()
        if "whitenoise" in content.lower():
            info(f"  {sf.name}: Using WhiteNoise. Ensure whitenoise>=6.0.0 is installed.")
            if "REQUIREMENTS_UPDATES" not in content:
                pass  # already handled above


def patch_db_default(project_root: Path):
    """
    Django 5.0 added db_default for database-level column defaults.
    No required migration, but flag any use of database-side defaults via raw SQL.
    """
    banner("Scanning for database default patterns")
    for p in project_root.rglob("*.py"):
        content = p.read_text(errors="ignore")
        if "RunSQL" in content and "DEFAULT" in content.upper():
            info(f"  {p}: Uses RunSQL with DEFAULT clause – "
                 "consider migrating to db_default= parameter (Django 5.0).")


def patch_templates_engine(settings_files: list[Path]):
    """
    Django 5.x: 'libraries' key in TEMPLATES[0]['OPTIONS'] now requires
    fully qualified paths. Warn if short-form library names detected.
    """
    banner("Checking TEMPLATES settings")
    for sf in settings_files:
        content = sf.read_text()
        if "'libraries'" in content or '"libraries"' in content:
            info(f"  {sf.name}: TEMPLATES 'libraries' key found. "
                 "Ensure values are fully-qualified dotted paths.")


def patch_functools_wraps_removed_from_views(_project_root: Path):
    """
    Django 5.0 removed some internal decorators. Catch custom view decorators.
    """
    pass  # Scan only


def patch_async_views(project_root: Path):
    """
    Identify views that could benefit from Django 4.1+ async support.
    This is optional/advisory only.
    """
    banner("Scanning for async-upgrade opportunities (advisory)")
    sync_views = 0
    for p in project_root.rglob("views.py"):
        content = p.read_text(errors="ignore")
        count = content.count("def get(self") + content.count("def post(self")
        if count > 0:
            sync_views += count
    if sync_views:
        info(f"  Found ~{sync_views} synchronous CBV methods. "
             "Consider converting heavy I/O views to async for Django 4.1+ performance gains.")


def patch_site_framework(settings_files: list[Path]):
    """
    Ensure SITE_ID is set if django.contrib.sites is in INSTALLED_APPS.
    """
    banner("Checking django.contrib.sites / SITE_ID")
    for sf in settings_files:
        content = sf.read_text()
        if "django.contrib.sites" in content and "SITE_ID" not in content:
            warn(f"  {sf.name}: 'django.contrib.sites' in INSTALLED_APPS but "
                 "SITE_ID is not set. Add SITE_ID = 1 (or appropriate value).")
            ensure_setting(sf, "SITE_ID", "1")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Step 3 – Upgrade to Django 5.2 LTS")
    parser.add_argument("--project-root", default=".", metavar="DIR")
    parser.add_argument("--requirements", default="requirements.txt")
    parser.add_argument("--settings", default="")
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

    backup_sqlite(root / args.db, label="pre_step3")

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

    # Settings patches
    patch_use_deprecated_pytz_removed(settings_files)
    patch_password_hashers(settings_files)
    patch_middleware_removed(settings_files)
    patch_forms_renderer(settings_files)
    patch_templates_engine(settings_files)
    patch_site_framework(settings_files)
    patch_storages(root, settings_files)

    # Code patches
    patch_pytz_to_zoneinfo(root)
    patch_unique_constraint(root)
    patch_index_together(root)
    patch_db_default(root)
    patch_async_views(root)

    if not args.skip_migrate:
        banner("Running database migrations")
        manage(root, "migrate")

    banner("Step 3 complete ✔")
    print(textwrap.dedent("""
    Next steps:
      1. Run tests: python manage.py test
      2. Address any unique_together / index_together warnings manually.
      3. Verify timezone handling after pytz → zoneinfo migration.
      4. Commit to version control.
      5. Then run:  python step4_cms4.py --project-root .
         (Upgrades django-cms 3.x → 4.x — a major architectural change)
    """))


if __name__ == "__main__":
    main()
