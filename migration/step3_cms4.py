#!/usr/bin/env python3
"""
step3_cms4.py
═════════════
Migrate:  django-cms 3.11  →  django-cms 4.1.x
          Django stays at 4.2 LTS — DO NOT upgrade Django yet!

Prerequisites: step2_django42.py completed successfully.

CMS 4 introduced a major architectural overhaul:
  ─ Content objects are now versioned (via djangocms-versioning)
  ─ The Page model was split into Page (structure) + PageContent (content)
  ─ The old draft/live mechanism is replaced by djangocms-versioning
  ─ djangocms-text-ckeditor is replaced by djangocms-text
  ─ djangocms-bootstrap4 is incompatible and must be migrated

WHY DJANGO STAYS AT 4.2 HERE:
  django-cms 3.11 is incompatible with Django 5.x.
  We must complete the CMS upgrade first while still on Django 4.2,
  then upgrade Django in step5_django52.py.

Run from your project root:
    python path/to/step3_cms4.py --project-root .
"""

import argparse
import re
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from migration_utils import (
    banner, ok, info, warn, backup_sqlite, replace_in_file, replace_in_dir, ensure_setting,
    update_requirements, pip_uninstall, manage, check_python_version, check_venv, run,
)

# ─────────────────────────────────────────────
# Target package versions
# Django stays at 4.2 — CMS ecosystem upgrades only
# ─────────────────────────────────────────────
REQUIREMENTS_UPDATES = {
    "Django":                      "==4.2.17",   # UNCHANGED — do not bump yet
    "django-cms":                  "==4.1.3",
    "django-classy-tags":          "==4.1.0",
    "django-sekizai":              "==4.1.0",
    "django-treebeard":            "==4.7.1",
    "django-mptt":                 "==0.16.0",
    "django-polymorphic":          "==3.1.0",
    "djangocms-versioning":        "==2.1.0",    # NEW — required by CMS 4
    "djangocms-admin-style":       "==3.3.1",    # latest on PyPI (no 4.x exists)
    "djangocms-attributes-field":  "==3.0.0",
    "djangocms-text":              ">=0.6.0",    # replaces djangocms-text-ckeditor
    "djangocms-frontend":          ">=2.0.0",    # replaces djangocms-bootstrap4
    "djangocms-file":              "==3.0.1",    # latest on PyPI (no 4.x exists)
    "djangocms-googlemap":         "==2.2.0",    # latest on PyPI (no 3.x exists)
    "djangocms-icon":              ">=2.0.0",    # use range — exact new version uncertain
    # Claudo correction: "djangocms-link":              "==4.0.0",    # confirmed on PyPI
    "djangocms-link":              ">=5.0.0",    # djangocms-frontend 2.x requires >=5
    "djangocms-picture":           "==4.1.1",    # latest on PyPI
    "djangocms-style":             "==3.1.0",    # latest on PyPI (no 4.x exists)
    "djangocms-video":             "==3.1.0",    # latest on PyPI (no 4.x exists)
    "django-filer":                "==3.1.2",
    "easy-thumbnails":             "==2.9.0",
    "django-crispy-forms":         "==2.3",
    "crispy-bootstrap4":           "==2024.1",
    "django-formtools":            "==2.5.1",
    "django-js-asset":             "==2.0.0",
    # pytz stays for now — CMS 3.x plugins depend on it; it will be removed in step5_django52.py
    "pytz":                        "==2024.1",
}

REMOVALS = [
    "djangocms-text-ckeditor",   # replaced by djangocms-text
    # djangocms-bootstrap4 is kept installed temporarily during this step so
    # that djangocms-frontend can read its data during the migration command.
    # It is uninstalled by step3_kairos_bootstrap4_migrate.py --mode frontend
    # AFTER the migration has completed successfully.
]

ADDITIONS = [
    "djangocms-versioning==2.1.0",
    "djangocms-text>=0.6.0",
    "djangocms-frontend>=2.0.0",
    "# NOTE: djangocms-bootstrap4 removed AFTER running step3_kairos_bootstrap4_migrate.py",
    "# NOTE: pytz kept intentionally — remove in step5_django52.py only",
]


# ─────────────────────────────────────────────
# Settings patches
# ─────────────────────────────────────────────
def patch_installed_apps(settings_files: list[Path]):
    """
    Warn about required INSTALLED_APPS changes for CMS 4.
    Auto-fix is risky due to ordering requirements; we guide instead.
    """
    banner("Checking INSTALLED_APPS for CMS 4 requirements")

    for sf in settings_files:
        content = sf.read_text()
        issues: list[str] = []

        if "djangocms_text_ckeditor" in content:
            issues.append(
                f"  REMOVE  'djangocms_text_ckeditor'\n"
                f"  ADD     'djangocms_text'"
            )
        if "djangocms_bootstrap4" in content:
            issues.append(
                f"  REMOVE  ALL 'djangocms_bootstrap4*' entries from INSTALLED_APPS.\n"
                f"          (djangocms-link 5.x is incompatible with bootstrap4 at import time)\n"
                f"          The bootstrap4 DB tables stay intact — only remove from INSTALLED_APPS.\n"
                f"  KEEP    'djangocms_frontend'"
            )
        if "djangocms_versioning" not in content:
            issues.append(
                f"  ADD     'djangocms_versioning'  "
                f"← must appear BEFORE 'cms' in INSTALLED_APPS"
            )
        if "djangocms_text" not in content and "djangocms_text_ckeditor" not in content:
            issues.append(f"  ADD     'djangocms_text'")

        if issues:
            warn(f"\n  {sf.name} — manual INSTALLED_APPS edits required:")
            for issue in issues:
                warn(issue)
            warn(
                f"\n  Required order inside INSTALLED_APPS:\n"
                f"    'djangocms_versioning',   # BEFORE cms\n"
                f"    'cms',\n"
                f"    'menus',\n"
                f"    'djangocms_text',\n"
                f"    # ... other djangocms_* plugins\n"
            )
        else:
            ok(f"  {sf.name}: INSTALLED_APPS looks correct for CMS 4.")


def patch_cms_settings(settings_files: list[Path]):
    """Remove/warn about CMS settings that changed in CMS 4."""
    banner("Patching CMS_ settings for CMS 4")
    for sf in settings_files:
        content = sf.read_text()

        # CMS_CONFIRM_VERSION4 — REQUIRED by CMS 4, migrate refuses without it
        if "CMS_CONFIRM_VERSION4" not in content:
            ensure_setting(sf, "CMS_CONFIRM_VERSION4",
                           "True  # Required to confirm intentional upgrade to django-cms 4")
            ok(f"  {sf.name}: added CMS_CONFIRM_VERSION4 = True")

        # CMS_TOOLBAR_ANONYMOUS_ON removed
        if "CMS_TOOLBAR_ANONYMOUS_ON" in content:
            replace_in_file(
                sf, "CMS_TOOLBAR_ANONYMOUS_ON",
                "# CMS_TOOLBAR_ANONYMOUS_ON  # REMOVED in CMS 4")
            ok(f"  {sf.name}: commented out CMS_TOOLBAR_ANONYMOUS_ON")

        # CMS_RAW_ID_USERS deprecated
        if "CMS_RAW_ID_USERS" in content:
            warn(f"  {sf.name}: CMS_RAW_ID_USERS deprecated in CMS 4.")

        # Add versioning config
        if "DJANGOCMS_VERSIONING_LOCK_VERSIONS" not in content:
            ensure_setting(
                sf, "DJANGOCMS_VERSIONING_LOCK_VERSIONS",
                "False  # Set True to prevent concurrent editing")
            ok(f"  {sf.name}: added DJANGOCMS_VERSIONING_LOCK_VERSIONS")

        # TEXT plugin config rename
        if "TEXT_SAVE_IMAGE_FUNCTION" in content:
            warn(f"  {sf.name}: TEXT_SAVE_IMAGE_FUNCTION — "
                 "djangocms-text uses DJANGOCMS_TEXT_CONFIGURATION instead.")

        # IMPORTANT: Do NOT touch pytz settings here
        if "USE_DEPRECATED_PYTZ" not in content:
            ensure_setting(
                sf, "USE_DEPRECATED_PYTZ",
                "True  # Keep True until step5_django52.py — CMS 4 plugins still need pytz")
            ok(f"  {sf.name}: set USE_DEPRECATED_PYTZ = True (required until Django 5 step)")


def patch_template_tags(project_root: Path):
    """
    CMS 4 template tag changes.
    static_placeholder → page_placeholder is the main one.
    """
    banner("Patching CMS template tags")
    for ext in ("*.html", "*.htm"):
        n = replace_in_dir(project_root, ext,
                           "{% static_placeholder",
                           "{% page_placeholder")
        if n:
            warn(f"  Renamed {n}× static_placeholder → page_placeholder. "
                 "Verify placeholder names in CMS admin.")


def patch_cms_plugin_classes(project_root: Path):
    """Check custom CMS plugin files for CMS 4 compatibility issues."""
    banner("Checking custom CMS plugin classes")
    for p in project_root.rglob("cms_plugins.py"):
        content = p.read_text(errors="ignore")
        if "copy_relations" in content:
            info(f"  {p}: defines copy_relations() — verify it handles versioning correctly.")
        if "render_plugin = False" in content:
            warn(f"  {p}: render_plugin=False — verify behaviour in CMS 4 toolbar.")
        if "child_classes" in content or "parent_classes" in content:
            info(f"  {p}: uses child_classes/parent_classes — verify plugin hierarchy.")


def patch_cms_app_hooks(project_root: Path):
    """Check apphook definitions for CMS 4 compatibility."""
    banner("Checking CMS apphook definitions")
    for p in project_root.rglob("cms_apps.py"):
        content = p.read_text(errors="ignore")
        if "apphook_pool.register(" in content:
            warn(f"  {p}: uses apphook_pool.register() as a call. "
                 "Migrate to @apphook_pool.register decorator for CMS 4.")
        if "app_name" not in content and "namespace" not in content:
            warn(f"  {p}: no app_name/namespace — required for CMS 4 apphooks.")


def patch_page_model_references(project_root: Path):
    """
    CMS 4 split Page into Page + PageContent.
    Attributes like .title, .slug etc. moved to PageContent.
    Produce a review file — cannot be auto-fixed safely.
    """
    banner("Scanning for CMS Page model attribute access (manual review required)")

    moved_attrs = [
        r"\.title\b", r"\.slug\b", r"\.page_title\b", r"\.menu_title\b",
        r"\.meta_description\b", r"\.redirect\b", r"\.in_navigation\b",
        r"\.soft_root\b", r"\.template\b", r"\.language\b",
    ]

    hits: list[tuple[Path, int, str]] = []
    for p in project_root.rglob("*.py"):
        if ".git" in str(p) or "migrations" in str(p):
            continue
        content = p.read_text(errors="ignore")
        if "from cms" not in content and "import cms" not in content:
            continue
        for line_no, line in enumerate(content.splitlines(), 1):
            for attr in moved_attrs:
                if re.search(r"\bpage" + attr, line, re.IGNORECASE):
                    hits.append((p, line_no, line.strip()))

    report_path = Path("cms4_page_attribute_review.txt")
    with open(report_path, "w") as fh:
        fh.write("CMS 4: Page → PageContent attribute migration review\n")
        fh.write("=" * 60 + "\n\n")
        fh.write(
            "The following lines likely access Page model attributes that\n"
            "moved to PageContent in CMS 4. Review and update each:\n\n"
            "  Old: page.title\n"
            "  New: page.get_content_obj().title\n\n"
        )
        for path, lineno, line in hits:
            fh.write(f"{path}:{lineno}\n  {line}\n\n")

    if hits:
        warn(f"  {len(hits)} potential issues → {report_path}")
    else:
        ok(f"  No obvious Page attribute issues found. {report_path} is empty.")


def patch_bootstrap4_migration_report(_project_root: Path):
    """Generate the Bootstrap4 → djangocms-frontend migration report."""
    banner("Generating djangocms-frontend migration report")

    report_path = Path("cms4_bootstrap4_migration.txt")
    with open(report_path, "w") as fh:
        fh.write(textwrap.dedent("""
        djangocms-bootstrap4 → djangocms-frontend migration
        =====================================================

        djangocms-bootstrap4 is NOT compatible with django-cms 4.x.
        djangocms-frontend is the actively maintained successor to both
        djangocms-bootstrap4 and djangocms-bootstrap5, and is the
        recommended replacement for this project.

        YOUR DATA (from kairos project.db):
          272 × Bootstrap4GridColumnPlugin
          109 × Bootstrap4GridRowPlugin
          108 × Bootstrap4LinkPlugin
           90 × Bootstrap4PicturePlugin
            6 × Bootstrap4BlockquotePlugin
          ───────────────────────────────
          585 plugin instances total across 11 pages (de/en/es)

        RECOMMENDED PATH — djangocms-frontend
        ──────────────────────────────────────
        djangocms-frontend reads bootstrap4 data directly from the DB
        tables — it does NOT need djangocms-bootstrap4 in INSTALLED_APPS.

        IMPORTANT: djangocms-link 5.x (required by djangocms-frontend 2.x)
        is incompatible with djangocms-bootstrap4 at import time.
        bootstrap4_link imports from djangocms_link.forms which no longer
        exists in link 5.x. Therefore ALL djangocms_bootstrap4* apps MUST
        be removed from INSTALLED_APPS BEFORE running manage.py migrate.
        The bootstrap4 DB tables remain — Django does not drop tables for
        apps removed from INSTALLED_APPS.

        Step-by-step:

          1. Remove ALL djangocms_bootstrap4* from INSTALLED_APPS:
               'djangocms_bootstrap4',
               'djangocms_bootstrap4.contrib.bootstrap4_alerts',
               'djangocms_bootstrap4.contrib.bootstrap4_badge',
               'djangocms_bootstrap4.contrib.bootstrap4_card',
               'djangocms_bootstrap4.contrib.bootstrap4_carousel',
               'djangocms_bootstrap4.contrib.bootstrap4_collapse',
               'djangocms_bootstrap4.contrib.bootstrap4_content',
               'djangocms_bootstrap4.contrib.bootstrap4_grid',
               'djangocms_bootstrap4.contrib.bootstrap4_jumbotron',
               'djangocms_bootstrap4.contrib.bootstrap4_link',
               'djangocms_bootstrap4.contrib.bootstrap4_listgroup',
               'djangocms_bootstrap4.contrib.bootstrap4_media',
               'djangocms_bootstrap4.contrib.bootstrap4_picture',
               'djangocms_bootstrap4.contrib.bootstrap4_tabs',
               'djangocms_bootstrap4.contrib.bootstrap4_utilities',
             Also remove djangocms-bootstrap4 from requirements.txt.
             Keep 'djangocms_frontend' in INSTALLED_APPS.

          2. Run Django migrations:
               python manage.py migrate

          3. Run the kairos FK-remapping (fixes page ID references):
               python step3_kairos_bootstrap4_migrate.py \\
                   --db project.db --mode remap-fks

          4. Run djangocms-frontend's bootstrap4 migration command:
               python manage.py cms_frontend migrate bootstrap4
             (verify exact command name:
              python manage.py help | grep frontend)

          5. Verify the site renders correctly with the new plugins.

        WHAT djangocms-frontend PROVIDES vs Bootstrap4
        ────────────────────────────────────────────────
          Bootstrap4Plugin          → FrontendUIPlugin (generic container)
          Bootstrap4GridRowPlugin   → GridPlugin / ContainerPlugin
          Bootstrap4GridColumnPlugin→ ColumnPlugin
          Bootstrap4LinkPlugin      → LinkPlugin (frontend variant)
          Bootstrap4PicturePlugin   → ImagePlugin (frontend variant)
          Bootstrap4BlockquotePlugin→ BlockquotePlugin

        KAIROS-SPECIFIC FK REMAPPING
        ─────────────────────────────
        The kairos DB has 12 Bootstrap4Link.internal_link_id references
        and 18 PageLinkBox.page_link_id references that point directly
        to cms_page.id. These must be remapped BEFORE running the
        djangocms-frontend migration command (step 5 above), because the
        frontend migration reads these FKs to preserve the link targets.

        Run: python step3_kairos_bootstrap4_migrate.py --db project.db --mode remap-fks
        BEFORE running the djangocms-frontend migration command.

        FALLBACK OPTION — Convert to plain HTML
        ─────────────────────────────────────────
        If djangocms-frontend migration fails for any reason:
          Replace Bootstrap4 plugin blocks manually with Text plugin HTML.
          ~585 blocks across 3 languages = significant manual effort.
        """).strip())

    ok(f"  Migration report → {report_path}")


# ─────────────────────────────────────────────
# Database migration
# ─────────────────────────────────────────────
def run_cms4_data_migration(root: Path):
    banner("Running CMS 4 database migration")

    info("  Step A: Apply all schema migrations")
    manage(root, "migrate", "--run-syncdb")

    info("  Step B: Fix CMS tree structure")
    manage(root, "cms", "fix-tree")

    info("  Step C: Create initial versions for existing content")
    rc = run(
        f"{sys.executable} manage.py create_versions --username admin",
        cwd=str(root), check=False,
    )
    if rc != 0:
        warn("  'create_versions' not available yet — OK at this stage.")
        warn("  Run it manually once djangocms-versioning is fully configured.")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Step 3 – Upgrade django-cms 3.11 → 4.x  (Django stays at 4.2)")
    parser.add_argument("--project-root", default=".", metavar="DIR")
    parser.add_argument("--requirements", default="requirements.txt")
    parser.add_argument("--settings", default="")
    parser.add_argument("--db", default="project.db")
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--skip-migrate",  action="store_true")
    args = parser.parse_args()

    banner("⚠  CRITICAL BACKUP CHECK")
    print(textwrap.dedent(f"""
    This step modifies the CMS database structure irreversibly.
    Before proceeding, confirm you have:
      ✔ A full database backup  ({args.db}.bak or similar)
      ✔ A full media/static files backup
      ✔ The project committed to version control
      ✔ step2_django42.py completed successfully

    Also confirm: Django is at 4.2 (NOT 5.x).
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

    backup_sqlite(root / args.db, label="pre_step3_cms4")

    req_file = root / args.requirements
    if req_file.exists():
        banner("Updating requirements.txt")
        update_requirements(req_file, REQUIREMENTS_UPDATES,
                            removals=REMOVALS, additions=ADDITIONS)

    if not args.skip_install and req_file.exists():
        banner("Installing updated packages")
        # Only uninstall text-ckeditor here.
        # djangocms-bootstrap4 must stay installed so that the
        # djangocms-frontend migration command can read its plugin data.
        # It is removed later by: step3_kairos_bootstrap4_migrate.py --mode cleanup
        pip_uninstall("djangocms-text-ckeditor", "django-cms")
        run(f"{sys.executable} -m pip install -r {req_file}")

    patch_installed_apps(settings_files)
    patch_cms_settings(settings_files)
    patch_template_tags(root)
    patch_cms_plugin_classes(root)
    patch_cms_app_hooks(root)
    patch_page_model_references(root)
    patch_bootstrap4_migration_report(root)

    if not args.skip_migrate:
        run_cms4_data_migration(root)

    banner("Step 3 complete ✔")
    print(textwrap.dedent("""
    Manual follow-up required:
      1. Edit INSTALLED_APPS — remove ALL 'djangocms_bootstrap4*' entries.
         (djangocms-link 5.x is incompatible with bootstrap4 at import time)
         Keep 'djangocms_frontend'.
      2. Remove djangocms-bootstrap4 from requirements.txt.
      3. Open cms4_page_attribute_review.txt — fix each listed location.
      4. Run: python manage.py migrate
      5. Run FK remapping:
           python step3_kairos_bootstrap4_migrate.py --db project.db --mode remap-fks
      6. Run the djangocms-frontend migration command:
           python manage.py cms_frontend migrate bootstrap4
      7. Verify the site renders correctly.
      8. Run: python manage.py check --deploy
      9. Commit to version control.
     10. Then: python step4_cms5.py --project-root .
    """))


if __name__ == "__main__":
    main()
