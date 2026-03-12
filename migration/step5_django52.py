#!/usr/bin/env python3
"""
step5_django52.py
═════════════════
Migrate:  Django 4.2  →  Django 5.2 (LTS)
          Remove pytz → replace with stdlib zoneinfo
          Python 3.12 recommended.

Prerequisites: step4_cms5.py completed and verified.
               CMS 5 must be running stably on Django 4.2 before this step.

WHY THIS IS THE LAST STEP:
  - django-cms 3.11 is incompatible with Django 5.x — that is why Django
    stayed at 4.2 through steps 3 and 4.
  - pytz was kept through all CMS steps because older plugin versions
    depended on it internally.
  - Now that CMS 5 and all plugins are on their final versions, it is safe
    to upgrade Django and remove pytz.

Run from your project root:
    python path/to/step5_django52.py --project-root .
"""

import argparse
import re
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from migration_utils import (
    banner, ok, info, warn, backup_sqlite, replace_in_file, replace_in_dir,
    update_requirements, pip_uninstall, manage, check_python_version, check_venv, run,
)

# ─────────────────────────────────────────────
# Target package versions — final state
# ─────────────────────────────────────────────
REQUIREMENTS_UPDATES = {
    "Django":                      "==5.2",
    "django-cms":                  "==5.0.3",    # unchanged
    "django-classy-tags":          "==4.1.0",
    "django-sekizai":              "==4.1.0",
    "django-treebeard":            "==4.7.1",
    "django-mptt":                 "==0.16.0",
    "django-polymorphic":          "==3.1.0",
    "djangocms-versioning":        "==2.5.0",    # latest on PyPI
    "djangocms-admin-style":       "==3.3.1",    # latest on PyPI (no 4.x exists)
    "djangocms-attributes-field":  "==3.0.0",
    "djangocms-text":              ">=0.6.0",
    "djangocms-frontend":          ">=2.0.0",    # replaces djangocms-bootstrap4
    "djangocms-file":              "==3.0.1",    # latest on PyPI (no 4.x exists)
    "djangocms-googlemap":         "==2.2.0",    # latest on PyPI (no 3.x exists)
    "djangocms-icon":              ">=2.0.0",
    # claude correction: "djangocms-link":              "==4.0.0",
    "djangocms-link": ">=5.0.0",                 # djangocms-frontend 2.x requires >=5
    "djangocms-picture":           "==4.1.1",    # latest on PyPI
    "djangocms-style":             "==3.1.0",    # latest on PyPI (no 4.x exists)
    "djangocms-video":             "==3.1.0",    # latest on PyPI (no 4.x exists)
    "django-filer":                "==3.3.1",
    "easy-thumbnails":             "==2.10.0",
    "django-crispy-forms":         "==2.3",
    "crispy-bootstrap4":           "==2024.1",
    "django-formtools":            "==2.5.1",
    "django-js-asset":             "==2.0.0",
    # pillow is a transitive dep — pin for reproducibility
    "pillow":                      ">=10.0.0",
}

REMOVALS = [
    "pytz",   # replaced by stdlib zoneinfo — safe to remove now
]

ADDITIONS: list[str] = []


# ─────────────────────────────────────────────
# pytz → zoneinfo migration
# ─────────────────────────────────────────────
def patch_pytz_to_zoneinfo(project_root: Path):
    """
    Replace all pytz usage with stdlib zoneinfo (Python 3.9+).
    Only safe to do now that CMS 5 and all plugins no longer depend on pytz.
    """
    banner("Migrating pytz → stdlib zoneinfo")

    # Import replacements
    replace_in_dir(project_root, "*.py",
                   "import pytz",
                   "from zoneinfo import ZoneInfo  # migrated from pytz")
    replace_in_dir(project_root, "*.py",
                   "from pytz import timezone",
                   "from zoneinfo import ZoneInfo as timezone  # migrated from pytz")
    replace_in_dir(project_root, "*.py",
                   "from pytz import utc",
                   "from datetime import timezone as dt_timezone  # migrated from pytz.utc")
    replace_in_dir(project_root, "*.py",
                   "from pytz import UTC",
                   "from datetime import timezone as dt_timezone  # migrated from pytz.UTC")

    # Usage patterns
    replace_in_dir(project_root, "*.py",
                   "pytz.timezone(",   "ZoneInfo(")
    replace_in_dir(project_root, "*.py",
                   "pytz.UTC",         "datetime.timezone.utc")
    replace_in_dir(project_root, "*.py",
                   "pytz.utc",         "datetime.timezone.utc")

    # Check for .localize() — pytz-specific, no direct zoneinfo equivalent
    for p in project_root.rglob("*.py"):
        content = p.read_text(errors="ignore")
        if ".localize(" in content:
            warn(f"  {p}: uses .localize() — pytz-specific method. "
                 "Replace with: datetime.replace(tzinfo=ZoneInfo('...')) "
                 "or datetime(..., tzinfo=ZoneInfo('...'))")

    # Check for .normalize() — pytz-specific
    for p in project_root.rglob("*.py"):
        content = p.read_text(errors="ignore")
        if ".normalize(" in content and "pytz" in content:
            warn(f"  {p}: uses .normalize() — not needed with zoneinfo. "
                 "zoneinfo handles DST transitions automatically.")


def patch_use_deprecated_pytz(settings_files: list[Path]):
    """
    Remove USE_DEPRECATED_PYTZ entirely (hard-removed in Django 5.0).
    Before this step it was set to True; now we remove it.
    """
    banner("Removing USE_DEPRECATED_PYTZ (hard-removed in Django 5.0)")
    for sf in settings_files:
        content = sf.read_text()
        if "USE_DEPRECATED_PYTZ" in content:
            # Remove any variant of this setting
            for variant in [
                "USE_DEPRECATED_PYTZ = True  # Keep True until step5_django52.py — CMS 4 plugins still need pytz\n",
                "USE_DEPRECATED_PYTZ = True  # Still needed — pytz removed in step5_django52.py\n",
                "USE_DEPRECATED_PYTZ = True\n",
                "USE_DEPRECATED_PYTZ = False\n",
            ]:
                replace_in_file(sf, variant, "")
            # Also catch commented variants from step 2
            replace_in_file(
                sf, "# USE_DEPRECATED_PYTZ  # REMOVED in Django 5.0",
                "")
            ok(f"  {sf.name}: removed USE_DEPRECATED_PYTZ")
        else:
            ok(f"  {sf.name}: USE_DEPRECATED_PYTZ not present — OK")


# ─────────────────────────────────────────────
# Django 5.x specific patches
# ─────────────────────────────────────────────
def patch_middleware_removed(settings_files: list[Path]):
    """
    BrokenLinkEmailsMiddleware was removed in Django 5.0.
    """
    banner("Checking for removed middleware")
    removed = "django.middleware.common.BrokenLinkEmailsMiddleware"
    for sf in settings_files:
        content = sf.read_text()
        if removed in content:
            warn(f"  {sf.name}: '{removed}' removed in Django 5.0 — deleting.")
            replace_in_file(sf, f'    "{removed}",\n', "")
            replace_in_file(sf, f"    '{removed}',\n", "")
            ok(f"  {sf.name}: removed BrokenLinkEmailsMiddleware")


def patch_unique_constraint(project_root: Path):
    """
    unique_together is deprecated in Django 5.x — warn, cannot auto-fix.
    """
    banner("Checking deprecated unique_together / index_together")
    for p in project_root.rglob("models.py"):
        content = p.read_text(errors="ignore")
        if "unique_together" in content:
            warn(f"  {p}: 'unique_together' deprecated — "
                 "migrate to Meta.constraints = [UniqueConstraint(...)]")
        if "index_together" in content:
            warn(f"  {p}: 'index_together' deprecated — "
                 "migrate to Meta.indexes = [Index(fields=[...])]")


def patch_password_reset_timeout(settings_files: list[Path]):
    """
    PASSWORD_RESET_TIMEOUT_DAYS was removed in Django 4.0.
    Catch any that slipped through earlier steps.
    """
    banner("Checking PASSWORD_RESET_TIMEOUT_DAYS (removed in Django 4)")
    for sf in settings_files:
        content = sf.read_text()
        if "PASSWORD_RESET_TIMEOUT_DAYS" in content:
            warn(f"  {sf.name}: PASSWORD_RESET_TIMEOUT_DAYS still present — "
                 "replace with PASSWORD_RESET_TIMEOUT (seconds). "
                 "e.g. PASSWORD_RESET_TIMEOUT = 3 * 24 * 3600")


def patch_db_default_advisory(_project_root: Path):
    """
    Django 5.0 added db_default for database-level defaults.
    Advisory only — no required change.
    """
    banner("Advisory: db_default available in Django 5.0")
    info("  You can now use db_default= on model fields for database-level defaults.")
    info("  No action required.")


def patch_csrf_trusted_origins(settings_files: list[Path]):
    """
    Double-check CSRF_TRUSTED_ORIGINS has scheme prefix (Django 4.0+).
    Should have been fixed in step2, but verify.
    """
    banner("Verifying CSRF_TRUSTED_ORIGINS scheme prefix")
    # noinspection RegExpRedundantEscape
    pattern = re.compile(r"CSRF_TRUSTED_ORIGINS\s*=\s*\[([^\]]*)\]", re.DOTALL)
    for sf in settings_files:
        content = sf.read_text()
        m = pattern.search(content)
        if m:
            entries = [e.strip().strip("\"'")
                       for e in m.group(1).split(",") if e.strip()]
            needs_fix = [e for e in entries
                         if e and not e.startswith(("http://", "https://"))]
            if needs_fix:
                warn(f"  {sf.name}: still missing scheme prefix: {needs_fix}")
                new_block = m.group(0)
                for e in needs_fix:
                    new_block = new_block.replace(f"'{e}'", f"'https://{e}'")
                    new_block = new_block.replace(f'"{e}"', f'"https://{e}"')
                content = content.replace(m.group(0), new_block)
                sf.write_text(content)
                ok(f"  {sf.name}: fixed CSRF_TRUSTED_ORIGINS")
            else:
                ok(f"  {sf.name}: CSRF_TRUSTED_ORIGINS looks correct ✔")


def patch_async_advisory(project_root: Path):
    """Advisory: Django 4.1+ async view support."""
    banner("Advisory: async view support")
    count = sum(
        p.read_text(errors="ignore").count("def get(self") +
        p.read_text(errors="ignore").count("def post(self")
        for p in project_root.rglob("views.py")
    )
    if count:
        info(f"  ~{count} synchronous CBV methods found. "
             "Consider async for I/O-heavy views (Django 4.1+ feature).")


def run_deploy_check(root: Path):
    """Run manage.py check --deploy as recommended by the other AI."""
    banner("Running: python manage.py check --deploy")
    info("  This catches deprecated settings, security issues, and "
         "configuration problems for the new Django version.")
    rc = run(
        f"{sys.executable} manage.py check --deploy",
        cwd=str(root), check=False,
    )
    if rc != 0:
        warn("  check --deploy reported issues (see above). "
             "Address them before going to production.")
    else:
        ok("  check --deploy passed ✔")


def generate_final_checklist(root: Path):
    checklist_path = root / "FINAL_MIGRATION_CHECKLIST.md"
    checklist_path.write_text(textwrap.dedent("""
    # Final Migration Checklist — Django 5.2 + CMS 5

    ## ✅ Package versions (final state)
    - [ ] `Django==5.2`
    - [ ] `django-cms==5.0.x`
    - [ ] `djangocms-versioning==2.3.x`
    - [ ] `djangocms-text==0.8.x`
    - [ ] `pytz` NOT in requirements (removed)
    - [ ] All djangocms-* plugins on CMS-5-compatible versions

    ## ✅ Settings
    - [ ] `USE_DEPRECATED_PYTZ` ABSENT from settings.py
    - [ ] `USE_TZ = True` present
    - [ ] `TIME_ZONE` set to a valid IANA timezone string (e.g. 'Europe/Berlin')
    - [ ] `DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'`
    - [ ] `USE_L10N = True`
    - [ ] `CSRF_TRUSTED_ORIGINS` values have `https://` scheme prefix
    - [ ] `LANGUAGES` explicitly defined
    - [ ] `SITE_ID = 1`
    - [ ] `BrokenLinkEmailsMiddleware` absent
    - [ ] `SecurityMiddleware` is FIRST in MIDDLEWARE
    - [ ] `CMS_CONFIRM_VERSION_4` absent

    ## ✅ Code
    - [ ] No `pytz` imports anywhere (`grep -r "import pytz" .`)
    - [ ] No `.localize()` calls (pytz-specific)
    - [ ] No `ugettext` / `ugettext_lazy` calls
    - [ ] No `force_text` / `smart_text` calls
    - [ ] No `request.is_ajax()` calls
    - [ ] No `url()` calls (use `re_path()` or `path()`)
    - [ ] No `sideframe` references
    - [ ] cms4_page_attribute_review.txt — all resolved
    - [ ] unique_together / index_together warnings addressed

    ## ✅ Database
    - [ ] `python manage.py showmigrations` — no unapplied migrations
    - [ ] `python manage.py migrate --check` — passes
    - [ ] `python manage.py cms fix-tree` — runs clean
    - [ ] Sessions flushed: `python manage.py clearsessions`

    ## ✅ Static files
    - [ ] `python manage.py collectstatic --noinput --clear`
    - [ ] All CMS admin static assets loading

    ## ✅ Testing
    - [ ] `python manage.py check --deploy` — no issues
    - [ ] Test suite: `python manage.py test`
    - [ ] Manual smoke test: home page, CMS admin, all 11 pages (de/en/es)
    - [ ] CMS toolbar visible and functional
    - [ ] Member area (login-required page) accessible
    - [ ] Announcements, Meetings, Messages plugins rendering
    - [ ] PageLinkBox cards linking to correct pages
    - [ ] django-filer images displaying correctly

    ## ✅ Production deploy
    - [ ] Python 3.12 on server
    - [ ] Production DB migration run (with backup)
    - [ ] Environment variables updated
    - [ ] `gunicorn` / `uwsgi` restarted
    - [ ] Monitoring checked after deploy
    """).strip() + "\n")
    ok(f"  Final checklist → {checklist_path}")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Step 5 – Upgrade Django 4.2 → 5.2 LTS + remove pytz  "
                    "(CMS 5 must be running first)")
    parser.add_argument("--project-root", default=".", metavar="DIR")
    parser.add_argument("--requirements", default="requirements.txt")
    parser.add_argument("--settings", default="")
    parser.add_argument("--db", default="project.db")
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--skip-migrate",  action="store_true")
    args = parser.parse_args()

    banner("Pre-flight: confirm CMS 5 is stable on Django 4.2")
    print(textwrap.dedent("""
    Before upgrading Django, confirm:
      ✔ step4_cms5.py completed and CMS5_CHECKLIST.md is fully ticked off
      ✔ CMS 5 site is working end-to-end on Django 4.2
      ✔ python manage.py check --deploy passes on Django 4.2
      ✔ Full database backup taken

    Press ENTER to continue or Ctrl+C to abort.
    """))
    try:
        input()
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(0)

    check_python_version((3, 10))
    check_venv()

    root = Path(args.project_root).resolve()
    info(f"Project root: {root}")

    if args.settings:
        settings_files = [root / s.strip() for s in args.settings.split(",")]
    else:
        settings_files = [s for s in root.rglob("settings.py")
                          if "migration" not in str(s)]

    backup_sqlite(root / args.db, label="pre_step5_django52")

    req_file = root / args.requirements
    if req_file.exists():
        banner("Updating requirements.txt")
        update_requirements(req_file, REQUIREMENTS_UPDATES,
                            removals=REMOVALS, additions=ADDITIONS)

    if not args.skip_install and req_file.exists():
        banner("Installing updated packages")
        pip_uninstall("pytz")
        run(f"{sys.executable} -m pip install -r {req_file}")

    # pytz removal — the main event of this step
    patch_use_deprecated_pytz(settings_files)
    patch_pytz_to_zoneinfo(root)

    # Django 5.x specific patches
    patch_middleware_removed(settings_files)
    patch_unique_constraint(root)
    patch_password_reset_timeout(settings_files)
    patch_csrf_trusted_origins(settings_files)
    patch_db_default_advisory(root)
    patch_async_advisory(root)

    if not args.skip_migrate:
        banner("Running database migrations")
        manage(root, "migrate")

    run_deploy_check(root)
    generate_final_checklist(root)

    banner("Step 5 complete ✔  —  Migration suite finished!")
    print(textwrap.dedent("""
    Your kairos project is now running:
      Django 5.2 LTS  +  django-cms 5.x  +  djangocms-versioning 2.x

    Work through FINAL_MIGRATION_CHECKLIST.md before deploying to production.
    """))


if __name__ == "__main__":
    main()
