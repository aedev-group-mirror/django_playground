#!/usr/bin/env python3
"""
step5_cms5.py
═════════════
Migrate:  django-cms 4.1  →  django-cms 5.x (latest stable)
          Also ensures Django 5.2 compatibility of all plugins.

CMS 5 continued the CMS 4 architecture but with:
  ─ Improved versioning API
  ─ djangocms-moderation integration
  ─ Cleaned-up toolbar and placeholder APIs
  ─ Dropped Python 3.8/3.9 support

Run from your project root:
    python path/to/step5_cms5.py --project-root .
"""

import argparse
import re
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from migration_utils import (
    banner, ok, info, warn, backup_sqlite, replace_in_file, replace_in_dir, update_requirements,
    manage, check_python_version, check_venv, run,
)

# ─────────────────────────────────────────────
# Target package versions for CMS 5
# ─────────────────────────────────────────────
REQUIREMENTS_UPDATES = {
    "Django":                      "==5.2",
    "django-cms":                  "==5.0.3",
    "django-classy-tags":          "==4.1.0",
    "django-sekizai":              "==4.1.0",
    "django-treebeard":            "==4.7.1",
    "django-mptt":                 "==0.16.0",
    "django-polymorphic":          "==3.1.0",
    "djangocms-versioning":        "==2.3.0",
    "djangocms-admin-style":       "==4.1.0",
    "djangocms-attributes-field":  "==3.0.0",
    "djangocms-text":              "==0.8.0",
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
}

REMOVALS: list[str] = []
ADDITIONS: list[str] = []


# ─────────────────────────────────────────────
# CMS 5 patches
# ─────────────────────────────────────────────
def patch_cms5_imports(project_root: Path):
    """
    CMS 5 cleaned up several import paths.
    """
    banner("Patching CMS 5 import paths")

    replacements = [
        # Placeholder
        ("from cms.models.placeholdermodel import Placeholder",
         "from cms.models import Placeholder"),
        # Page
        ("from cms.models.pagemodel import Page",
         "from cms.models import Page"),
        ("from cms.models.contentmodels import PageContent",
         "from cms.models import PageContent"),
        # Plugin base
        ("from cms.plugin_base import CMSPluginBase",
         "from cms.plugin_base import CMSPluginBase"),  # unchanged
        # Toolbar
        ("from cms.toolbar_base import CMSToolbar",
         "from cms.toolbar_base import CMSToolbar"),  # unchanged
        # Utils
        ("from cms.utils import get_cms_setting",
         "from cms.utils.conf import get_cms_setting"),
        ("from cms.utils.page_resolver import get_page_from_request",
         "from cms.utils.page import get_page_from_request"),
    ]

    for old, new in replacements:
        if old != new:
            n = replace_in_dir(project_root, "*.py", old, new)
            if n:
                ok(f"  Updated {n}x: {old[:60]}")


def patch_versioning_api(project_root: Path):
    """
    djangocms-versioning 2.x changed the version state constants.
    """
    banner("Checking djangocms-versioning API")

    _state_renames = [
        ("DRAFT",      "DRAFT"),         # unchanged
        ("PUBLISHED",  "PUBLISHED"),     # unchanged
        ("UNPUBLISHED", "UNPUBLISHED"),  # unchanged
        ("ARCHIVED",   "ARCHIVED"),      # unchanged
     ]

    for p in project_root.rglob("*.py"):
        content = p.read_text(errors="ignore")
        if "djangocms_versioning" not in content and "versioning" not in content:
            continue
        # Look for version.publish() calls that changed signature
        if ".publish(" in content:
            info(f"  {p}: calls .publish() – verify it passes `user` kwarg "
                 "(required in versioning 2.x).")
        if "Version.objects.filter" in content:
            info(f"  {p}: queries Version model directly – "
                 "verify field names against versioning 2.x schema.")


def patch_cms5_toolbar(project_root: Path):
    """
    CMS 5 toolbar changes:
    - toolbar.get_left_items() / get_right_items() changed
    - Add/edit toolbar item API tweaks
    """
    banner("Checking CMS toolbar customisations for CMS 5")
    for p in project_root.rglob("cms_toolbars.py"):
        content = p.read_text(errors="ignore")
        if "get_left_items" in content or "get_right_items" in content:
            warn(f"  {p}: uses get_left_items/get_right_items – "
                 "verify these still exist in cms 5 toolbar API.")
        if "ButtonList" in content:
            info(f"  {p}: uses ButtonList – OK in CMS 5.")
        if "SideframeButton" in content:
            info(f"  {p}: uses SideframeButton – verify it still exists "
                 "in CMS 5 (sideframe was deprecated).")
        if "ModalButton" in content:
            info(f"  {p}: uses ModalButton – OK in CMS 5.")


def patch_cms5_sideframe_deprecated(project_root: Path, _settings_files: list[Path]):
    """
    CMS 5 removed the sideframe in favour of the full-modal admin.
    """
    banner("Sideframe → Modal migration")
    for p in project_root.rglob("*.py"):
        content = p.read_text(errors="ignore")
        if "sideframe" in content.lower() or "SideframeButton" in content:
            warn(f"  {p}: references sideframe – "
                 "this was REMOVED in CMS 5. Use ModalButton or admin views.")
    for p in project_root.rglob("*.html"):
        content = p.read_text(errors="ignore")
        if "sideframe" in content.lower():
            warn(f"  {p}: template references sideframe – review for CMS 5.")


def patch_cms5_placeholder_api(project_root: Path):
    """
    CMS 5 Placeholder API changes:
    - Placeholder.get_plugins() → still valid
    - get_placeholder_from_slot() signature changed slightly
    - render_placeholder() context requirements
    """
    banner("Checking Placeholder API usage")
    for p in project_root.rglob("*.py"):
        content = p.read_text(errors="ignore")
        if "render_placeholder" in content:
            info(f"  {p}: uses render_placeholder – verify `request` is passed "
                 "as first positional arg in CMS 5.")
        if "get_plugins_for_placeholder" in content:
            info(f"  {p}: uses get_plugins_for_placeholder – "
                 "verify call signature for CMS 5.")


def patch_cms5_menu_api(project_root: Path):
    """
    CMS 5 menus: NavigationNode unchanged, but some modifiers moved.
    """
    banner("Checking CMS menu customisations")
    for code_file in project_root.rglob("cms_menus.py"):
        content = code_file.read_text(errors="ignore")
        if "Modifier" in content:
            info(f"  {code_file}: defines a menu Modifier – "
                 "verify it imports from cms.menu_bases in CMS 5.")
        replace_in_file(
            code_file,
            "from menus.base import NavigationNode",
            "from menus.base import NavigationNode")  # unchanged, just verify


def patch_cms5_apphook_namespace(project_root: Path):
    """
    CMS 5 requires apphook namespaces to be explicitly unique.
    """
    banner("Checking apphook namespace uniqueness")
    namespaces: list[tuple[str, Path]] = []
    for p in project_root.rglob("cms_apps.py"):
        content = p.read_text(errors="ignore")
        for match in re.finditer(r'app_name\s*=\s*["\'](\w+)["\']', content):
            namespaces.append((match.group(1), p))
    seen: dict[str, Path] = {}
    for ns, p in namespaces:
        if ns in seen:
            warn(f"  Duplicate apphook namespace '{ns}' in {p} and {seen[ns]}. "
                 "CMS 5 requires unique namespaces.")
        else:
            seen[ns] = p
            ok(f"  Namespace '{ns}' in {p.name} – unique ✔")


def patch_cms5_settings(settings_files: list[Path]):
    """
    CMS 5 specific settings changes.
    """
    banner("Patching settings for CMS 5")
    for setting_file in settings_files:
        content = setting_file.read_text()

        # CMS_CONFIRM_VERSION_4 was a temporary migration flag in CMS 4.0
        if "CMS_CONFIRM_VERSION_4" in content:
            replace_in_file(
                setting_file,
                "CMS_CONFIRM_VERSION_4",
                "# CMS_CONFIRM_VERSION_4  # Removed: no longer needed in CMS 5")

        # Ensure django.contrib.messages is in INSTALLED_APPS (required by CMS 5)
        if "django.contrib.messages" not in content:
            warn(f"  {setting_file.name}: 'django.contrib.messages' not in INSTALLED_APPS "
                 "– required by CMS 5.")

        # CMS 5 requires LANGUAGES to be set
        if "LANGUAGES" not in content and "LANGUAGE_CODE" in content:
            warn(f"  {setting_file.name}: LANGUAGES list not found. "
                 "CMS 5 requires explicit LANGUAGES setting.")

        # Check for CMS_LANGUAGES referencing correct structure
        if "CMS_LANGUAGES" in content:
            ok(f"  {setting_file.name}: CMS_LANGUAGES defined – OK.")

        # Check TEXT plugin config
        if "CKEDITOR" in content.upper() or "ckeditor" in content:
            warn(f"  {setting_file.name}: CKEDITOR config detected – "
                 "djangocms-text (CMS 5) uses a different editor config. "
                 "See djangocms-text docs for DJANGOCMS_TEXT_CONFIGURATION.")


def generate_final_checklist(root: Path):
    """
    Write a human-readable migration checklist.
    """
    checklist_path = root / "CMS5_MIGRATION_CHECKLIST.md"
    checklist_path.write_text(textwrap.dedent("""
    # django-cms 5 Migration Final Checklist

    Work through each item below before deploying to production.

    ## ✅ Package Versions
    - [ ] `django-cms==5.0.x` installed
    - [ ] `djangocms-versioning==2.3.x` installed
    - [ ] `djangocms-text==0.8.x` installed (replaces djangocms-text-ckeditor)
    - [ ] All other djangocms-* plugins on their CMS-5-compatible versions
    - [ ] `Django==5.2` installed
    - [ ] No `pytz` in requirements (use stdlib `zoneinfo`)
    - [ ] `crispy-bootstrap4` installed alongside `django-crispy-forms`

    ## ✅ INSTALLED_APPS
    - [ ] `'djangocms_versioning'` listed BEFORE `'cms'`
    - [ ] `'djangocms_text'` listed (NOT `djangocms_text_ckeditor`)
    - [ ] `'djangocms_bootstrap4'` REMOVED
    - [ ] `'django.contrib.messages'` present
    - [ ] `'django.contrib.sites'` present (and SITE_ID set)

    ## ✅ MIDDLEWARE
    - [ ] `SecurityMiddleware` is FIRST
    - [ ] `LocaleMiddleware` appears after `SessionMiddleware`
    - [ ] `CmsMiddleware` (formerly `cms.middleware.page.CurrentPageMiddleware`) present
    - [ ] `BrokenLinkEmailsMiddleware` REMOVED (if present)

    ## ✅ Settings
    - [ ] `DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'` (or BigAutoField)
    - [ ] `USE_L10N = True`
    - [ ] `USE_DEPRECATED_PYTZ` REMOVED
    - [ ] `CMS_TEMPLATES` defined
    - [ ] `CMS_LANGUAGES` defined
    - [ ] `SITE_ID = 1` (or appropriate)
    - [ ] `CSRF_TRUSTED_ORIGINS` values have `https://` scheme prefix
    - [ ] `DJANGOCMS_VERSIONING_LOCK_VERSIONS` set as desired

    ## ✅ Database
    - [ ] All migrations applied: `python manage.py showmigrations`
    - [ ] No unapplied migrations: `python manage.py migrate --check`
    - [ ] `python manage.py cms fix-tree` run successfully
    - [ ] CMS pages visible in admin
    - [ ] Page content (PageContent) accessible in admin

    ## ✅ Templates
    - [ ] `{% load static %}` (not `staticfiles`)
    - [ ] `{% static_placeholder %}` renamed to `{% page_placeholder %}`
    - [ ] All CMS template tags working correctly
    - [ ] Bootstrap4 plugin blocks either migrated or replaced

    ## ✅ Code
    - [ ] `cms4_page_attribute_review.txt` reviewed and fixed
    - [ ] `cms4_bootstrap4_migration.txt` strategy chosen and implemented
    - [ ] No `ugettext` / `ugettext_lazy` calls (use `gettext` / `gettext_lazy`)
    - [ ] No `force_text` / `smart_text` calls (use `force_str` / `smart_str`)
    - [ ] No `request.is_ajax()` calls
    - [ ] App hooks use decorator-style registration
    - [ ] Unique namespaces for all app hooks

    ## ✅ Media / Static Files
    - [ ] `python manage.py collectstatic` runs without errors
    - [ ] Filer media files accessible (check MEDIA_ROOT / MEDIA_URL)
    - [ ] CMS icon and image plugins loading correctly

    ## ✅ Testing
    - [ ] `python manage.py check --deploy` passes
    - [ ] Test suite passes: `python manage.py test`
    - [ ] Manual smoke test: home page, at least one CMS page, admin
    - [ ] CMS toolbar visible when logged in as staff
    - [ ] New page can be created, published, and viewed

    ## ✅ Production Deploy
    - [ ] New Python 3.10+ runtime confirmed on server
    - [ ] All environment variables / secrets updated
    - [ ] Production database migration run (with backup)
    - [ ] Monitoring / error tracking alert thresholds checked
    """).strip() + "\n")
    ok(f"Checklist written to: {checklist_path}")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Step 5 – Upgrade django-cms 4.x → 5.x")
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

    backup_sqlite(root / args.db, label="pre_step5_cms5")

    req_file = root / args.requirements
    if req_file.exists():
        banner("Updating requirements.txt")
        update_requirements(req_file, REQUIREMENTS_UPDATES,
                            removals=REMOVALS, additions=ADDITIONS)

    if not args.skip_install and req_file.exists():
        banner("Installing updated packages")
        run(f"{sys.executable} -m pip install -r {req_file}")

    # CMS 5 code patches
    patch_cms5_imports(root)
    patch_versioning_api(root)
    patch_cms5_toolbar(root)
    patch_cms5_sideframe_deprecated(root, settings_files)
    patch_cms5_placeholder_api(root)
    patch_cms5_menu_api(root)
    patch_cms5_apphook_namespace(root)
    patch_cms5_settings(settings_files)

    if not args.skip_migrate:
        banner("Running database migrations")
        manage(root, "migrate")
        info("  Fixing CMS tree after migration")
        manage(root, "cms", "fix-tree")

    generate_final_checklist(root)

    banner("Step 5 complete ✔  –  Migration suite finished!")
    print(textwrap.dedent("""
    All automated migration steps are done.

    Now work through CMS5_MIGRATION_CHECKLIST.md to verify everything.

    Quick smoke test:
      python manage.py check --deploy
      python manage.py runserver
      → Open http://localhost:8000/en/admin/ and verify CMS pages.
    """))


if __name__ == "__main__":
    main()
