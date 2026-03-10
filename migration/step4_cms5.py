#!/usr/bin/env python3
"""
step4_cms5.py
═════════════
Migrate:  django-cms 4.1  →  django-cms 5.x
          Django stays at 4.2 LTS — DO NOT upgrade Django yet!

Prerequisites: step3_cms4.py completed and verified.

CMS 5 continued the CMS 4 architecture with:
  ─ Improved versioning API (djangocms-versioning 2.x)
  ─ Cleaned-up toolbar and placeholder APIs
  ─ Sideframe removed in favour of full-modal admin
  ─ Dropped Python 3.8/3.9 support

WHY DJANGO STAYS AT 4.2 HERE:
  We upgrade CMS to its final version first while on the stable Django 4.2
  LTS base. Once CMS 5 is running cleanly, step5_django52.py upgrades Django
  and removes pytz.

Run from your project root:
    python path/to/step4_cms5.py --project-root .
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
# Django stays at 4.2 — CMS 5 + plugins only
# ─────────────────────────────────────────────
REQUIREMENTS_UPDATES = {
    "Django":                      "==4.2.17",   # UNCHANGED
    "django-cms":                  "==5.0.3",
    "django-classy-tags":          "==4.1.0",
    "django-sekizai":              "==4.1.0",
    "django-treebeard":            "==4.7.1",
    "django-mptt":                 "==0.16.0",
    "django-polymorphic":          "==3.1.0",
    "djangocms-versioning":        "==2.3.0",
    "djangocms-admin-style":       "==3.3.1",
    "djangocms-attributes-field":  "==3.0.0",
    "djangocms-text":              "==0.8.0",
    "djangocms-frontend":          ">=2.0.0",    # replaces djangocms-bootstrap4
    "djangocms-file":              "==4.1.0",
    "djangocms-googlemap":         "==3.1.0",
    "djangocms-icon":              "==3.1.0",
    "djangocms-link":              "==4.1.0",
    "djangocms-picture":           "==4.1.0",
    "djangocms-style":             "==4.1.0",
    "djangocms-video":             "==4.1.0",
    "django-filer":                "==3.3.1",
    "easy-thumbnails":             "==2.10.0",
    "django-crispy-forms":         "==2.3",
    "crispy-bootstrap4":           "==2024.1",
    "django-formtools":            "==2.5.1",
    "django-js-asset":             "==2.0.0",
    # pytz still kept — will be removed in step5_django52.py
    "pytz":                        "==2024.1",
}

REMOVALS: list[str] = []
ADDITIONS = [
    "# NOTE: pytz kept intentionally until step5_django52.py",
]


# ─────────────────────────────────────────────
# CMS 5 code patches
# ─────────────────────────────────────────────
def patch_cms5_import_paths(project_root: Path):
    """CMS 5 reorganised several internal import paths."""
    banner("Patching CMS 5 import paths")
    replacements = [
        ("from cms.utils import get_cms_setting",
         "from cms.utils.conf import get_cms_setting"),
        ("from cms.utils.page_resolver import get_page_from_request",
         "from cms.utils.page import get_page_from_request"),
        ("from cms.models.placeholdermodel import Placeholder",
         "from cms.models import Placeholder"),
        ("from cms.models.pagemodel import Page",
         "from cms.models import Page"),
        ("from cms.models.contentmodels import PageContent",
         "from cms.models import PageContent"),
    ]
    for old, new in replacements:
        n = replace_in_dir(project_root, "*.py", old, new)
        if n:
            ok(f"  {n}× updated: {old[:70]}")


def patch_cms5_sideframe(project_root: Path, _settings_files: list[Path]):
    """
    CMS 5 removed the sideframe entirely (replaced by full-modal admin).
    """
    banner("Checking for sideframe usage (removed in CMS 5)")
    for p in list(project_root.rglob("*.py")) + list(project_root.rglob("*.html")):
        content = p.read_text(errors="ignore")
        if "sideframe" in content.lower() or "SideframeButton" in content:
            warn(f"  {p}: references sideframe — REMOVED in CMS 5. "
                 "Replace with ModalButton or direct admin views.")
        if "SideframeButton" in content:
            replace_in_file(p, "SideframeButton", "ModalButton")
            warn(f"  {p}: auto-replaced SideframeButton → ModalButton. "
                 "Verify the modal URL is correct.")


def patch_cms5_toolbar(project_root: Path):
    """Check toolbar customisations for CMS 5 API changes."""
    banner("Checking CMS 5 toolbar customisations")
    for p in project_root.rglob("cms_toolbars.py"):
        content = p.read_text(errors="ignore")
        if "get_left_items" in content or "get_right_items" in content:
            warn(f"  {p}: uses get_left_items/get_right_items — "
                 "verify these still exist in CMS 5 toolbar API.")
        if "ButtonList" in content:
            ok(f"  {p}: uses ButtonList — OK in CMS 5.")
        if "ModalButton" in content:
            ok(f"  {p}: uses ModalButton — OK in CMS 5.")


def patch_versioning_api(project_root: Path):
    """
    djangocms-versioning 2.x changed Version state handling slightly.
    """
    banner("Checking djangocms-versioning 2.x API usage")
    for p in project_root.rglob("*.py"):
        content = p.read_text(errors="ignore")
        if "djangocms_versioning" not in content and "versioning" not in content.lower():
            continue
        if ".publish(" in content:
            info(f"  {p}: calls .publish() — verify it passes the `user` kwarg "
                 "(required in versioning 2.x).")
        if "Version.objects.filter" in content:
            info(f"  {p}: queries Version model directly — "
                 "verify field names against versioning 2.x schema.")


def patch_cms5_placeholder_api(project_root: Path):
    """CMS 5 Placeholder API — render_placeholder signature check."""
    banner("Checking Placeholder API usage")
    for p in project_root.rglob("*.py"):
        content = p.read_text(errors="ignore")
        if "render_placeholder" in content:
            info(f"  {p}: uses render_placeholder — verify `request` is "
                 "passed as first positional arg (required in CMS 5).")


def patch_cms5_apphook_namespaces(project_root: Path):
    """CMS 5 requires apphook namespaces to be unique."""
    banner("Checking apphook namespace uniqueness")
    namespaces: dict[str, Path] = {}
    for p in project_root.rglob("cms_apps.py"):
        content = p.read_text(errors="ignore")
        for match in re.finditer(r'app_name\s*=\s*["\'](\w+)["\']', content):
            ns = match.group(1)
            if ns in namespaces:
                warn(f"  Duplicate namespace '{ns}' in {p} and {namespaces[ns]}. "
                     "CMS 5 requires unique namespaces.")
            else:
                namespaces[ns] = p
                ok(f"  Namespace '{ns}' in {p.name} — unique ✔")


def patch_cms5_settings(settings_files: list[Path]):
    """CMS 5 settings changes."""
    banner("Patching settings for CMS 5")
    for sf in settings_files:
        content = sf.read_text()

        # CMS_CONFIRM_VERSION_4 was a temporary flag in CMS 4.0
        if "CMS_CONFIRM_VERSION_4" in content:
            replace_in_file(
                sf, "CMS_CONFIRM_VERSION_4",
                "# CMS_CONFIRM_VERSION_4  # No longer needed in CMS 5")
            ok(f"  {sf.name}: commented out CMS_CONFIRM_VERSION_4")

        if "django.contrib.messages" not in content:
            warn(f"  {sf.name}: 'django.contrib.messages' missing from "
                 "INSTALLED_APPS — required by CMS 5.")

        if "LANGUAGES" not in content and "LANGUAGE_CODE" in content:
            warn(f"  {sf.name}: LANGUAGES list not found — "
                 "CMS 5 requires an explicit LANGUAGES setting.")

        # Text plugin config note
        if "CKEDITOR" in content.upper() or "ckeditor" in content:
            warn(f"  {sf.name}: CKEditor config detected — djangocms-text "
                 "uses DJANGOCMS_TEXT_CONFIGURATION instead. Remove old CKEditor settings.")

        # Remind: USE_DEPRECATED_PYTZ still needed here
        if "USE_DEPRECATED_PYTZ" not in content:
            ensure_setting(
                sf, "USE_DEPRECATED_PYTZ",
                "True  # Still needed — pytz removed in step5_django52.py")

        ok(f"  {sf.name}: CMS 5 settings check done.")


def generate_final_checklist(root: Path):
    """Write a go-live checklist for after CMS 5 is running."""
    checklist_path = root / "CMS5_CHECKLIST.md"
    checklist_path.write_text(textwrap.dedent("""
    # CMS 5 on Django 4.2 — Pre-Django-5 Checklist

    Work through each item below before running step5_django52.py.

    ## ✅ Packages
    - [ ] `django-cms==5.0.x` installed and working
    - [ ] `djangocms-versioning==2.3.x` installed
    - [ ] `djangocms-text==0.8.x` installed
    - [ ] `Django==4.2.x` (confirm NOT yet on 5.x)
    - [ ] `pytz` still in requirements (intentional — remove in step 5)

    ## ✅ INSTALLED_APPS
    - [ ] `'djangocms_versioning'` listed BEFORE `'cms'`
    - [ ] `'djangocms_text'` present (not `djangocms_text_ckeditor`)
    - [ ] `'djangocms_bootstrap4'` absent
    - [ ] `'django.contrib.messages'` present

    ## ✅ Settings
    - [ ] `USE_DEPRECATED_PYTZ = True` set (keep until step 5)
    - [ ] `CMS_CONFIRM_VERSION_4` removed
    - [ ] `LANGUAGES` explicitly defined
    - [ ] `SITE_ID = 1` set

    ## ✅ CMS functionality
    - [ ] `python manage.py migrate` — no pending migrations
    - [ ] `python manage.py cms fix-tree` — runs without errors
    - [ ] CMS toolbar visible when logged in as staff
    - [ ] All 11 kairos pages accessible in admin
    - [ ] Page content (PageContent) visible for de/en/es
    - [ ] Bootstrap5 plugins rendering (if Option A chosen)
    - [ ] PageLinkBox cards link to correct pages
    - [ ] Member plugins (Announcements, Meetings, Messages) rendering

    ## ✅ Code
    - [ ] cms4_page_attribute_review.txt — all items resolved
    - [ ] No sideframe references remaining
    - [ ] Apphook namespaces are unique
    - [ ] `python manage.py check --deploy` passes

    ## ✅ When this checklist is complete
    Run: python step5_django52.py --project-root .
    That step upgrades Django 4.2 → 5.2 and removes pytz.
    """).strip() + "\n")
    ok(f"  Checklist written → {checklist_path}")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Step 4 – Upgrade django-cms 4.x → 5.x  (Django stays at 4.2)")
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
        settings_files = [s for s in root.rglob("settings.py")
                          if "migration" not in str(s)]

    backup_sqlite(root / args.db, label="pre_step4_cms5")

    req_file = root / args.requirements
    if req_file.exists():
        banner("Updating requirements.txt")
        update_requirements(req_file, REQUIREMENTS_UPDATES,
                            removals=REMOVALS, additions=ADDITIONS)

    if not args.skip_install and req_file.exists():
        banner("Installing updated packages")
        run(f"{sys.executable} -m pip install -r {req_file}")

    patch_cms5_import_paths(root)
    patch_cms5_sideframe(root, settings_files)
    patch_cms5_toolbar(root)
    patch_versioning_api(root)
    patch_cms5_placeholder_api(root)
    patch_cms5_apphook_namespaces(root)
    patch_cms5_settings(settings_files)

    if not args.skip_migrate:
        banner("Running database migrations")
        manage(root, "migrate")
        manage(root, "cms", "fix-tree")

    generate_final_checklist(root)

    banner("Step 4 complete ✔")
    print(textwrap.dedent("""
    CMS 5 is now running on Django 4.2.

    Next:
      1. Work through CMS5_CHECKLIST.md completely.
      2. Run: python manage.py check --deploy
      3. Smoke-test the site end-to-end.
      4. Commit to version control.
      5. Only then: python step5_django52.py --project-root .
         (upgrades Django 4.2 → 5.2 and removes pytz)
    """))


if __name__ == "__main__":
    main()
