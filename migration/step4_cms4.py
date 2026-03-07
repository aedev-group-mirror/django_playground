#!/usr/bin/env python3
"""
step4_cms4.py
═════════════
Migrate:  django-cms 3.11  →  django-cms 4.1.x
          All djangocms-* plugins updated to their CMS-4-compatible versions.

CMS 4 introduced a major architectural overhaul:
  ─ Content objects are now versioned (via djangocms-versioning)
  ─ The Page model was split into Page (structure) + PageContent (content)
  ─ TreeNode replaced the old Page-as-tree approach
  ─ Placeholders are now tied to Content objects, not Pages directly
  ─ The "draft/live" mechanism was removed; versioning handles it instead

Run from your project root:
    python path/to/step4_cms4.py --project-root .

CRITICAL: Take a full database + media backup before running this step.
The CMS 4 data migration is destructive and cannot be automatically reversed.
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
# ─────────────────────────────────────────────
REQUIREMENTS_UPDATES = {
    "django-cms":                  "==4.1.3",
    "django-classy-tags":          "==4.1.0",
    "django-sekizai":              "==4.1.0",
    "django-treebeard":            "==4.7.1",
    "django-mptt":                 "==0.16.0",
    "django-polymorphic":          "==3.1.0",
    "djangocms-admin-style":       "==4.0.0",
    "djangocms-attributes-field":  "==3.0.0",
    # djangocms-text-ckeditor is replaced by djangocms-text in CMS 4
    "djangocms-text":              "==0.6.0",
    "djangocms-file":              "==4.0.0",
    "djangocms-googlemap":         "==3.0.0",
    "djangocms-icon":              "==3.0.0",
    "djangocms-link":              "==4.0.0",
    "djangocms-picture":           "==4.0.0",
    "djangocms-style":             "==4.0.0",
    "djangocms-video":             "==4.0.0",
    "djangocms-versioning":        "==2.1.0",   # NEW – required by CMS 4
    "django-filer":                "==3.3.1",
    "easy-thumbnails":             "==2.10.0",
}

REMOVALS = [
    "djangocms-text-ckeditor",   # replaced by djangocms-text
    "djangocms-bootstrap4",      # needs manual migration (see note below)
    "djangocms-admin-style",     # version pinned above
]

ADDITIONS = [
    "djangocms-versioning==2.1.0",
    "djangocms-text==0.6.0",
    "# djangocms-bootstrap4 has been removed; see BOOTSTRAP_MIGRATION_NOTE below",
    "# Options: djangocms-bootstrap5 or manually port templates to plain HTML",
]


# ─────────────────────────────────────────────
# Settings patches for CMS 4
# ─────────────────────────────────────────────
def patch_cms_config_in_installed_apps(settings_files: list[Path]):
    """
    CMS 4 requires 'cms' app to be listed AFTER 'djangocms_versioning'
    and needs several new apps added.
    """
    banner("Patching INSTALLED_APPS for CMS 4")

    new_apps = [
        "djangocms_versioning",
        "djangocms_text",
    ]
    remove_apps = [
        "djangocms_text_ckeditor",
        "djangocms_bootstrap4",
    ]

    for sf in settings_files:
        content = sf.read_text()

        for old_app in remove_apps:
            if f'"{old_app}"' in content or f"'{old_app}'" in content:
                warn(f"  {sf.name}: Remove '{old_app}' from INSTALLED_APPS manually.")

        for new_app in new_apps:
            if new_app not in content:
                warn(f"  {sf.name}: Add '{new_app}' to INSTALLED_APPS.")

        # djangocms-bootstrap4 removal note
        if "djangocms_bootstrap4" in content:
            warn(
                f"  {sf.name}: 'djangocms_bootstrap4' is NOT compatible with CMS 4.\n"
                "  Options:\n"
                "    A) Install djangocms-bootstrap5 (separate project).\n"
                "    B) Convert Bootstrap4 plugin blocks to plain HTML snippets.\n"
                "  See BOOTSTRAP_MIGRATION_NOTE in step4_cms4.py for details."
            )


def patch_cms_settings(settings_files: list[Path]):
    """
    CMS 4 changed/removed several CMS_ settings.
    """
    banner("Patching CMS_ settings")
    for setting_file in settings_files:
        content = setting_file.read_text()

        # CMS_PERMISSION – unchanged, still supported
        # CMS_TEMPLATES – unchanged
        # CMS_LANGUAGES – unchanged
        # CMS_PLACEHOLDER_CONF – unchanged

        # CMS_TOOLBAR_ANONYMOUS_ON – removed in CMS 4
        if "CMS_TOOLBAR_ANONYMOUS_ON" in content:
            warn(f"  {setting_file.name}: CMS_TOOLBAR_ANONYMOUS_ON removed in CMS 4 – remove it.")
            replace_in_file(
                setting_file,
                "CMS_TOOLBAR_ANONYMOUS_ON",
                "# CMS_TOOLBAR_ANONYMOUS_ON  # REMOVED in CMS 4")

        # CMS_RAW_ID_USERS is deprecated
        if "CMS_RAW_ID_USERS" in content:
            warn(f"  {setting_file.name}: CMS_RAW_ID_USERS deprecated in CMS 4.")

        # Ensure CMS_TEMPLATES is defined (required)
        if "CMS_TEMPLATES" not in content:
            warn(f"  {setting_file.name}: CMS_TEMPLATES not found – required for CMS 4.")

        # Add versioning config if not present
        if "DJANGOCMS_VERSIONING_LOCK_VERSIONS" not in content:
            ensure_setting(
                setting_file,
                "DJANGOCMS_VERSIONING_LOCK_VERSIONS",
                "False  # Set True to prevent concurrent editing")

        # Text plugin config rename
        if "TEXT_SAVE_IMAGE_FUNCTION" in content:
            warn(f"  {setting_file.name}: TEXT_SAVE_IMAGE_FUNCTION – "
                 "djangocms-text uses DJANGOCMS_TEXT_CONFIGURATION instead.")


def patch_cms_toolbar_classes(project_root: Path):
    """
    CMS 4 changed toolbar API.
    ToolbarAPIMixin.get_item_count() no longer exists.
    Toolbar items now live in different namespaces.
    """
    banner("Checking CMS Toolbar customisations")
    for p in project_root.rglob("cms_toolbars.py"):
        content = p.read_text(errors="ignore")
        issues = {
            "CMSToolbar":          "still valid in CMS 4 – OK",
            "ToolbarAPIMixin":     "still valid in CMS 4 – OK",
            "get_item_count":      "REMOVED – use len(toolbar.menus) instead",
            "toolbar.menus":       "API changed slightly – verify menu keys",
            "PageMenu":            "OK in CMS 4",
        }
        for token, note in issues.items():
            if token in content:
                if "REMOVED" in note:
                    warn(f"  {p}: uses '{token}' – {note}")
                else:
                    info(f"  {p}: uses '{token}' – {note}")


def patch_cms_app_hooks(project_root: Path):
    """
    CMS 4: apphook_pool.register as a decorator is the canonical style.
    Also: get_urls() → get_urls() (unchanged, but namespace handling changed).
    """
    banner("Checking CMS apphook definitions")
    for p in project_root.rglob("cms_apps.py"):
        content = p.read_text(errors="ignore")
        if "apphook_pool.register(" in content:
            warn(f"  {p}: uses apphook_pool.register() as a call. "
                 "Migrate to @apphook_pool.register decorator for CMS 4 compatibility.")
        if "get_urls" in content:
            ok(f"  {p}: defines get_urls() – OK (still valid)")
        if "app_name" not in content and "namespace" not in content:
            warn(f"  {p}: no app_name/namespace found. "
                 "CMS 4 requires explicit namespace for any apphook.")


def patch_cms_plugin_classes(project_root: Path):
    """
    CMS 4 plugin API changes:
    - CMSPlugin.render() signature unchanged
    - copy_relations() still works
    - get_render_template() still works
    - plugin_type property unchanged
    But: CMSPlugin model fields slightly changed for versioning support.
    """
    banner("Checking CMS plugin classes")
    for p in project_root.rglob("cms_plugins.py"):
        content = p.read_text(errors="ignore")

        if "copy_relations" in content:
            info(f"  {p}: defines copy_relations() – verify it handles versioning.")

        if "get_render_template" in content:
            ok(f"  {p}: defines get_render_template() – OK")

        # Plugin render_plugin deprecated for some patterns
        if "render_plugin = False" in content:
            warn(f"  {p}: render_plugin=False – verify behaviour in CMS 4 toolbar.")

        if "child_classes" in content or "parent_classes" in content:
            info(f"  {p}: uses child_classes/parent_classes – "
                 "verify these are still correct with your plugin hierarchy.")


def patch_template_tags(project_root: Path):
    """
    CMS 4 template tag changes:
    - {% page_url %} → unchanged
    - {% cms_toolbar %} → unchanged
    - {% placeholder %} → unchanged (but content model changed)
    - {% static_placeholder %} → RENAMED to {% page_placeholder %} in CMS 4
    - {% show_placeholder %} → still valid
    - {% render_menu %} → still valid
    """
    banner("Patching CMS template tags")

    # static_placeholder renamed in CMS 4
    for ext in ("*.html", "*.htm"):
        n = replace_in_dir(project_root, ext,
                           "{% static_placeholder",
                           "{% page_placeholder")
        if n:
            warn(f"  Renamed {n} static_placeholder → page_placeholder. "
                 "Verify placeholder names in the CMS admin.")

    # Check for deprecated cms_tags usage
    for p in project_root.rglob("*.html"):
        content = p.read_text(errors="ignore")
        if "show_sub_menu" in content:
            info(f"  {p}: uses show_sub_menu – verify menu depth params for CMS 4.")
        if "{% page_language_url" in content:
            info(f"  {p}: uses page_language_url – OK in CMS 4.")


def patch_page_model_references(project_root: Path):
    """
    CMS 4 split Page into Page (tree node) + PageContent (language content).
    Any code accessing page.title, page.slug etc. via the old Page model
    must now go through PageContent.

    This is the most invasive CMS 4 change.
    We cannot auto-fix all cases; we produce a report instead.
    """
    banner("Scanning for CMS Page model attribute access (manual review required)")

    # Attributes that moved to PageContent
    moved_to_page_content = [
        ".title\b", ".slug\b", ".page_title\b", ".menu_title\b",
        ".meta_description\b", ".redirect\b", ".in_navigation\b",
        ".soft_root\b", ".template\b", ".language\b",
    ]

    hits: list[tuple[Path, int, str]] = []
    for p in project_root.rglob("*.py"):
        content = p.read_text(errors="ignore")
        # Only look in files that import from cms
        if "from cms" not in content and "import cms" not in content:
            continue
        for line_no, line in enumerate(content.splitlines(), 1):
            # Look for page.<moved_attr>
            for attr_pattern in moved_to_page_content:
                if re.search(r"\bpage" + attr_pattern, line, re.IGNORECASE):
                    hits.append((p, line_no, line.strip()))

    if hits:
        report_path = Path("cms4_page_attribute_review.txt")
        with open(report_path, "w") as fh:
            fh.write("CMS 4 Page → PageContent attribute migration review\n")
            fh.write("=" * 60 + "\n\n")
            fh.write(
                "These lines likely access Page model attributes that were\n"
                "moved to PageContent in CMS 4. Review and update each:\n\n"
                "  Old: page.title\n"
                "  New: page.get_content_obj().title\n"
                "       (or via request: request.current_page.get_content_obj().title)\n\n"
            )
            for path, lineno, line in hits:
                fh.write(f"{path}:{lineno}\n  {line}\n\n")
        warn(f"  {len(hits)} potential Page attribute issues written to: {report_path}")
    else:
        ok("  No obvious Page attribute issues found.")


def patch_bootstrap4_migration(project_root: Path):
    """
    djangocms-bootstrap4 is not compatible with CMS 4.
    Generate a report of all Bootstrap4 plugin usages in templates.
    """
    banner("Bootstrap4 plugin migration report")

    bs4_plugins = [
        "Bootstrap4GridPlugin", "Bootstrap4GridRowPlugin",
        "Bootstrap4GridColumnPlugin", "Bootstrap4AlertPlugin",
        "Bootstrap4BadgePlugin", "Bootstrap4ButtonPlugin",
        "Bootstrap4CardPlugin", "Bootstrap4CollapsePlugin",
        "Bootstrap4EmbedPlugin", "Bootstrap4FigurePlugin",
        "Bootstrap4JumbotronPlugin", "Bootstrap4LinkPlugin",
        "Bootstrap4ListGroupPlugin", "Bootstrap4MediaPlugin",
        "Bootstrap4PicturePlugin", "Bootstrap4SpacingPlugin",
        "Bootstrap4TabsPlugin",
    ]

    hits: list[str] = []
    for p in project_root.rglob("*.py"):
        content = p.read_text(errors="ignore")
        for plugin in bs4_plugins:
            if plugin in content:
                hits.append(f"{p}: {plugin}")

    report_path = Path("cms4_bootstrap4_migration.txt")
    with open(report_path, "w") as fh:
        fh.write("djangocms-bootstrap4 → CMS 4 migration\n")
        fh.write("=" * 60 + "\n\n")
        fh.write(textwrap.dedent("""
        djangocms-bootstrap4 is NOT compatible with django-cms 4.x.

        You have three options:

        Option A: Migrate to djangocms-bootstrap5
        ─────────────────────────────────────────
          pip install djangocms-bootstrap5
          Add 'djangocms_bootstrap5' to INSTALLED_APPS.
          Run the provided data migration command:
            python manage.py migrate djangocms_bootstrap4 zero  # after data copy
          Note: This is a community project; check its CMS 4 compatibility.

        Option B: Convert blocks to plain HTML
        ──────────────────────────────────────
          Use the CMS admin to export page content.
          Replace Bootstrap4 plugin blocks with plain HTML snippets
          using the Text plugin (djangocms-text).
          This is tedious but gives the most control.

        Option C: Keep djangocms-bootstrap4 data frozen
        ─────────────────────────────────────────────────
          Remove the app from INSTALLED_APPS but keep the migrations
          applied so existing data is preserved in the DB.
          Render Bootstrap4 content via a custom template tag that
          reads the old plugin data directly.

        Plugin usages found in codebase:
        """))
        if hits:
            for h in hits:
                fh.write(f"  {h}\n")
        else:
            fh.write("  None found in Python files (check CMS admin for DB records).\n")

    warn(f"  Bootstrap4 migration report written to: {report_path}")
    warn("  You MUST choose one of the three options above before the site goes live.")


# ─────────────────────────────────────────────
# Database migration for CMS 4
# ─────────────────────────────────────────────
def run_cms4_data_migration(root: Path):
    """
    CMS 4 ships a management command 'cms4_migration' that converts
    old-style Page/Title records to new Page/PageContent/TreeNode structure.
    """
    banner("Running CMS 4 database data migration")
    info("  Step A: Apply schema migrations for all apps")
    manage(root, "migrate", "--run-syncdb")

    info("  Step B: Run CMS 4 built-in content migration command")
    # This command was introduced in django-cms 4.0 to migrate CMS 3 data.
    # It converts cms_title records to PageContent and rebuilds the tree.
    manage(root, "cms", "fix-tree")
    run_code = run(
        f"{sys.executable} manage.py cms4-migrate-content",
        cwd=str(root),
        check=False,
    )
    if run_code != 0:
        warn("  'cms4-migrate-content' command not found or failed.")
        warn("  This is expected if running against a fresh CMS 4 install.")
        warn("  If you have existing CMS 3 data, run the migration manually:")
        warn("    python manage.py migrate cms")
        warn("    python manage.py migrate")

    info("  Step C: Rebuild tree structure")
    manage(root, "cms", "fix-tree")

    info("  Step D: Create initial versions (if djangocms-versioning installed)")
    run_code = run(
        f"{sys.executable} manage.py versioning_create_initial_versions",
        cwd=str(root),
        check=False,
    )
    if run_code != 0:
        info("  'versioning_create_initial_versions' not available yet – OK at this stage.")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Step 4 – Upgrade django-cms 3.11 → 4.x")
    parser.add_argument("--project-root", default=".", metavar="DIR")
    parser.add_argument("--requirements", default="requirements.txt")
    parser.add_argument("--settings", default="")
    parser.add_argument("--db", default="project.db")
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--skip-migrate",  action="store_true")
    parser.add_argument("--skip-code-patches", action="store_true")
    args = parser.parse_args()

    banner("⚠  CRITICAL BACKUP CHECK")
    print(textwrap.dedent(f"""
    This step modifies the CMS database structure irreversibly.
    Before proceeding, confirm you have:
      ✔ A full database backup  ({args.db}.bak)
      ✔ A full media/static files backup
      ✔ The project committed to version control

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

    backup_sqlite(root / args.db, label="pre_step4_cms4")

    req_file = root / args.requirements
    if req_file.exists():
        banner("Updating requirements.txt")
        update_requirements(req_file, REQUIREMENTS_UPDATES,
                            removals=REMOVALS, additions=ADDITIONS)
    else:
        warn(f"Requirements file not found: {req_file}")

    if not args.skip_install and req_file.exists():
        banner("Installing updated packages")
        # Uninstall old CMS packages first to avoid conflicts
        pip_uninstall("djangocms-text-ckeditor", "djangocms-bootstrap4",
                      "django-cms")
        run(f"{sys.executable} -m pip install -r {req_file}")

    if not args.skip_code_patches:
        patch_cms_config_in_installed_apps(settings_files)
        patch_cms_settings(settings_files)
        patch_cms_toolbar_classes(root)
        patch_cms_app_hooks(root)
        patch_cms_plugin_classes(root)
        patch_template_tags(root)
        patch_page_model_references(root)
        patch_bootstrap4_migration(root)

    if not args.skip_migrate:
        run_cms4_data_migration(root)

    banner("Step 4 complete ✔")
    print(textwrap.dedent("""
    Next steps:
      1. Open cms4_page_attribute_review.txt and fix each listed location.
      2. Open cms4_bootstrap4_migration.txt and choose your Bootstrap strategy.
      3. Manually update INSTALLED_APPS in settings.py:
           - Remove: 'djangocms_text_ckeditor', 'djangocms_bootstrap4'
           - Add:    'djangocms_versioning', 'djangocms_text'
      4. Update any CMS plugin registrations (see cms_plugins.py patches above).
      5. Start the dev server: python manage.py runserver
         Log in to /en/admin/ and verify pages/content appear correctly.
      6. Commit to version control.
      7. Then run:  python step5_cms5.py --project-root .
    """))


if __name__ == "__main__":
    main()
