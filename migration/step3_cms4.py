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
    "djangocms-admin-style":       "==4.0.0",
    "djangocms-attributes-field":  "==3.0.0",
    "djangocms-text":              "==0.6.0",    # replaces djangocms-text-ckeditor
    "djangocms-file":              "==4.0.0",
    "djangocms-googlemap":         "==3.0.0",
    "djangocms-icon":              "==3.0.0",
    "djangocms-link":              "==4.0.0",
    "djangocms-picture":           "==4.0.0",
    "djangocms-style":             "==4.0.0",
    "djangocms-video":             "==4.0.0",
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
    "djangocms-bootstrap4",      # incompatible with CMS 4 — see migration report
]

ADDITIONS = [
    "djangocms-versioning==2.1.0",
    "djangocms-text==0.6.0",
    "# NOTE: pytz kept intentionally — remove in step5_django52.py only",
    "# NOTE: djangocms-bootstrap4 removed — see cms4_bootstrap4_migration.txt",
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
                f"  REMOVE  'djangocms_bootstrap4'  "
                f"(see cms4_bootstrap4_migration.txt for your options)"
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

        # CMS_TOOLBAR_ANONYMOUS_ON removed
        if "CMS_TOOLBAR_ANONYMOUS_ON" in content:
            replace_in_file(
                sf,
                "CMS_TOOLBAR_ANONYMOUS_ON",
                "# CMS_TOOLBAR_ANONYMOUS_ON  # REMOVED in CMS 4")
            ok(f"  {sf.name}: commented out CMS_TOOLBAR_ANONYMOUS_ON")

        # CMS_RAW_ID_USERS deprecated
        if "CMS_RAW_ID_USERS" in content:
            warn(f"  {sf.name}: CMS_RAW_ID_USERS deprecated in CMS 4.")

        # Add versioning config
        if "DJANGOCMS_VERSIONING_LOCK_VERSIONS" not in content:
            ensure_setting(
                sf,
                "DJANGOCMS_VERSIONING_LOCK_VERSIONS",
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
    """Generate the Bootstrap4 migration strategy report."""
    banner("Generating Bootstrap4 migration report")

    report_path = Path("cms4_bootstrap4_migration.txt")
    with open(report_path, "w") as fh:
        fh.write(textwrap.dedent("""
        djangocms-bootstrap4 → CMS 4 migration
        ========================================

        djangocms-bootstrap4 is NOT compatible with django-cms 4.x.

        YOUR DATA (from kairos project.db):
          272 × Bootstrap4GridColumnPlugin
          109 × Bootstrap4GridRowPlugin
          108 × Bootstrap4LinkPlugin
           90 × Bootstrap4PicturePlugin
            6 × Bootstrap4BlockquotePlugin
          ───────────────────────────────
          585 plugin instances total across 11 pages (de/en/es)

        OPTION A — Migrate to djangocms-bootstrap5 (RECOMMENDED)
        ──────────────────────────────────────────────────────────
          pip install djangocms-bootstrap5
          Add 'djangocms_bootstrap5' to INSTALLED_APPS.
          Run: python manage.py migrate
          Run: python step3_kairos_bootstrap4_migrate.py --db project.db --mode full

          The kairos-specific migration script handles:
            - FK remapping (internal_link_id, page_link_id) via reverse_id
            - Copying GridRow / GridColumn / Link / Picture data to BS5 tables

        OPTION B — Convert to plain HTML (most control, most work)
          Replace Bootstrap4 plugin blocks with Text plugin HTML snippets.
          ~585 blocks across 3 languages = significant manual effort.

        OPTION C — Freeze old data (quick, but technical debt)
          Remove from INSTALLED_APPS, keep DB tables, render via custom tag.

        → Run step3_kairos_bootstrap4_migrate.py AFTER choosing an option.
        """).strip())

    ok(f"  Bootstrap4 migration report → {report_path}")


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
        f"{sys.executable} manage.py versioning_create_initial_versions",
        cwd=str(root), check=False,
    )
    if rc != 0:
        warn("  'versioning_create_initial_versions' not available yet — OK at this stage.")
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
        settings_files = [s for s in root.rglob("settings*.py")
                          if "migration" not in str(s)]

    backup_sqlite(root / args.db, label="pre_step3_cms4")

    req_file = root / args.requirements
    if req_file.exists():
        banner("Updating requirements.txt")
        update_requirements(req_file, REQUIREMENTS_UPDATES,
                            removals=REMOVALS, additions=ADDITIONS)

    if not args.skip_install and req_file.exists():
        banner("Installing updated packages")
        pip_uninstall("djangocms-text-ckeditor", "djangocms-bootstrap4", "django-cms")
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
      1. Edit INSTALLED_APPS as described in the warnings above.
      2. Open cms4_page_attribute_review.txt — fix each listed location.
      3. Open cms4_bootstrap4_migration.txt — choose your Bootstrap strategy.
      4. Run: python step3_kairos_bootstrap4_migrate.py --db project.db --mode remap-fks
      5. Start dev server, verify CMS pages in admin.
      6. Run: python manage.py check --deploy
      7. Commit to version control.
      8. Then: python step4_cms5.py --project-root .
         (CMS 4 → CMS 5, still on Django 4.2)
    """))


if __name__ == "__main__":
    main()
