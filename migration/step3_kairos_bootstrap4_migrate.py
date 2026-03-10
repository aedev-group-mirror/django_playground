#!/usr/bin/env python3
"""
step3_kairos_bootstrap4_migrate.py
════════════════════════════════════
Kairos-specific companion to step3_cms4.py.

Handles two things in the correct order:

  1. FK REMAPPING (run BEFORE djangocms-frontend migration command):
     After CMS 4 reassigns page IDs, these FK columns break silently:
       bootstrap4_link_bootstrap4link.internal_link_id  → cms_page.id
       page_link_plugin_pagelinkboxmodel.page_link_id   → cms_page.id
     This script uses the stable 'reverse_id' to find the new page IDs
     and patches the FKs — so that djangocms-frontend reads correct
     page references when it migrates the plugin data.

  2. CLEANUP (run AFTER djangocms-frontend migration is verified):
     Uninstalls djangocms-bootstrap4 from pip and reminds you to remove
     it from INSTALLED_APPS.

FULL WORKFLOW:
  # Before step3_cms4.py — save page ID snapshot:
  python step3_kairos_bootstrap4_migrate.py --db project.db --mode snapshot

  # After step3_cms4.py, before the frontend migration command:
  python step3_kairos_bootstrap4_migrate.py --db project.db --mode remap-fks

  # Then run djangocms-frontend's own migration command:
  python manage.py cms_frontend migrate bootstrap4
  (verify exact command: python manage.py help | grep -i frontend)

  # After verifying the site renders correctly:
  python step3_kairos_bootstrap4_migrate.py --mode cleanup
"""

import argparse
import json
import sqlite3
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from migration_utils import (
    banner, ok, info, warn, error,
    backup_sqlite, pip_uninstall, run,
)


# ─────────────────────────────────────────────
# Page ID mapping helpers
# ─────────────────────────────────────────────
def build_page_id_map(conn: sqlite3.Connection) -> dict[str, int]:
    """
    Returns {reverse_id: page_id} for all pages.
    Prefers the draft record (publisher_is_draft=1) as the canonical
    page ID, since CMS 4 uses drafts as the primary record.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT p.id, p.reverse_id, p.publisher_is_draft, t.slug, t.title
        FROM cms_page p
        LEFT JOIN cms_title t ON t.page_id = p.id AND t.language = 'en'
        WHERE p.reverse_id != '' AND p.reverse_id IS NOT NULL
        ORDER BY p.id
    """)
    rows = cur.fetchall()

    page_map: dict[str, int] = {}
    for pid, rev_id, is_draft, slug, title in rows:
        if rev_id not in page_map or is_draft:
            page_map[rev_id] = pid

    info("  Current reverse_id → page_id mapping:")
    for rev_id, pid in sorted(page_map.items()):
        info(f"    '{rev_id}' → page {pid}")
    return page_map


def build_remap(pre_map: dict[str, int],
                post_map: dict[str, int]) -> dict[int, int]:
    """
    Compute {old_page_id: new_page_id} from before/after reverse_id maps.
    Only includes entries where the ID actually changed.
    """
    remap: dict[int, int] = {}
    for rev_id, old_id in pre_map.items():
        new_id = post_map.get(rev_id)
        if new_id is None:
            warn(f"  reverse_id '{rev_id}' not found after migration — "
                 "page may have been deleted.")
            continue
        if old_id != new_id:
            remap[old_id] = new_id
            warn(f"  Page ID changed: {old_id} → {new_id}  (reverse_id='{rev_id}')")
        else:
            ok(f"  Page ID stable: {old_id}  (reverse_id='{rev_id}')")
    return remap


# ─────────────────────────────────────────────
# FK remapping
# ─────────────────────────────────────────────
def fix_bootstrap4_link_fks(conn: sqlite3.Connection, remap: dict[int, int]) -> int:
    """
    Update bootstrap4_link_bootstrap4link.internal_link_id.

    Must run BEFORE djangocms-frontend migration command so that
    djangocms-frontend reads the correct page references when it
    converts Bootstrap4Link → FrontendLink.

    Kairos data: 12 rows reference pages 4, 5, 15, 17, 18
    (The Rules, Announcements, Messages, Data Collection, Privacy Policy)
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT cmsplugin_ptr_id, name, internal_link_id
        FROM bootstrap4_link_bootstrap4link
        WHERE internal_link_id IS NOT NULL
    """)
    rows = cur.fetchall()
    if not rows:
        ok("  No Bootstrap4Link internal_link_id FKs found.")
        return 0

    updated = 0
    for plugin_id, name, old_id in rows:
        new_id = remap.get(old_id)
        if new_id:
            cur.execute("""
                UPDATE bootstrap4_link_bootstrap4link
                SET internal_link_id = ?
                WHERE cmsplugin_ptr_id = ?
            """, (new_id, plugin_id))
            info(f"  Bootstrap4Link {plugin_id} '{name}': {old_id} → {new_id}")
            updated += 1
        else:
            # ID unchanged — verify it still exists
            cur.execute("SELECT id FROM cms_page WHERE id=?", (old_id,))
            if cur.fetchone():
                ok(f"  Bootstrap4Link {plugin_id} '{name}': page {old_id} stable ✔")
            else:
                error(f"  Bootstrap4Link {plugin_id} '{name}': "
                      f"page {old_id} NOT FOUND! Link will be broken.")
    conn.commit()
    return updated


def fix_page_link_plugin_fks(conn: sqlite3.Connection, remap: dict[int, int]) -> int:
    """
    Update page_link_plugin_pagelinkboxmodel.page_link_id.

    Must run BEFORE djangocms-frontend migration command.

    Kairos data: 18 rows, all referencing 3 pages:
      page 4  (The Rules)     — reverse_id '20'
      page 5  (Announcements) — reverse_id '70_hl'
      page 15 (Messages)      — reverse_id '90_hl'
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT cmsplugin_ptr_id, page_link_id, page_image_id
        FROM page_link_plugin_pagelinkboxmodel
    """)
    rows = cur.fetchall()
    if not rows:
        ok("  No PageLinkBoxPlugin page_link_id FKs found.")
        return 0

    updated = 0
    for plugin_id, old_id, image_id in rows:
        new_id = remap.get(old_id)
        if new_id:
            cur.execute("""
                UPDATE page_link_plugin_pagelinkboxmodel
                SET page_link_id = ?
                WHERE cmsplugin_ptr_id = ?
            """, (new_id, plugin_id))
            info(f"  PageLinkBox {plugin_id}: {old_id} → {new_id} (image={image_id})")
            updated += 1
        else:
            cur.execute("SELECT id FROM cms_page WHERE id=?", (old_id,))
            if cur.fetchone():
                ok(f"  PageLinkBox {plugin_id}: page {old_id} stable ✔")
            else:
                error(f"  PageLinkBox {plugin_id}: page {old_id} NOT FOUND!")
    conn.commit()
    return updated


def fix_bootstrap4_picture_fks(conn: sqlite3.Connection, remap: dict[int, int]) -> int:
    """
    Update bootstrap4_picture_bootstrap4picture.link_page_id.
    (In kairos DB these are all NULL, but checked for safety.)
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT cmsplugin_ptr_id, link_page_id
        FROM bootstrap4_picture_bootstrap4picture
        WHERE link_page_id IS NOT NULL AND link_page_id != ''
    """)
    rows = cur.fetchall()
    if not rows:
        ok("  No Bootstrap4Picture link_page_id FKs (as expected for kairos).")
        return 0

    updated = 0
    for plugin_id, old_id in rows:
        try:
            old_id_int = int(old_id)
        except (ValueError, TypeError):
            continue
        new_id = remap.get(old_id_int)
        if new_id:
            cur.execute("""
                UPDATE bootstrap4_picture_bootstrap4picture
                SET link_page_id = ?
                WHERE cmsplugin_ptr_id = ?
            """, (str(new_id), plugin_id))
            info(f"  Bootstrap4Picture {plugin_id}: link_page_id {old_id} → {new_id}")
            updated += 1
    conn.commit()
    return updated


# ─────────────────────────────────────────────
# Verify FK integrity post-remapping
# ─────────────────────────────────────────────
def verify_fks(conn: sqlite3.Connection) -> bool:
    """
    Confirm all FK references point to existing cms_page rows.
    Must pass before running the djangocms-frontend migration command.
    """
    banner("Verifying FK integrity")
    cur = conn.cursor()
    all_ok = True

    cur.execute("""
        SELECT cmsplugin_ptr_id, name, internal_link_id
        FROM bootstrap4_link_bootstrap4link
        WHERE internal_link_id IS NOT NULL
    """)
    for plugin_id, name, page_id in cur.fetchall():
        cur.execute("SELECT id FROM cms_page WHERE id=?", (page_id,))
        if cur.fetchone():
            ok(f"  Bootstrap4Link {plugin_id} '{name}' → page {page_id} ✔")
        else:
            error(f"  Bootstrap4Link {plugin_id} '{name}' → page {page_id} MISSING ✘")
            all_ok = False

    cur.execute("SELECT cmsplugin_ptr_id, page_link_id FROM page_link_plugin_pagelinkboxmodel")
    for plugin_id, page_id in cur.fetchall():
        cur.execute("SELECT id FROM cms_page WHERE id=?", (page_id,))
        if cur.fetchone():
            ok(f"  PageLinkBox {plugin_id} → page {page_id} ✔")
        else:
            error(f"  PageLinkBox {plugin_id} → page {page_id} MISSING ✘")
            all_ok = False

    if all_ok:
        ok("  All FK references valid ✔  — safe to run djangocms-frontend migration.")
    else:
        error("  FK errors above must be fixed before running the frontend migration!")
    return all_ok


# ─────────────────────────────────────────────
# djangocms-frontend migration command runner
# ─────────────────────────────────────────────
def run_frontend_migration(project_root: Path) -> bool:
    """
    Run djangocms-frontend's built-in bootstrap4 migration command.

    djangocms-frontend reads the existing Bootstrap4 plugin records and
    creates equivalent FrontendUI plugin instances. The old bootstrap4
    table data is left in place until cleanup.

    The exact management command name varies by version — we try known
    variants in order.
    """
    banner("Running djangocms-frontend bootstrap4 migration")

    candidates = [
        "cms_frontend migrate bootstrap4",       # djangocms-frontend >= 2.x (most likely)
        "frontend_migration --from=bootstrap4",  # alternative
        "migrate_bootstrap4",                    # older variant
    ]

    for cmd in candidates:
        info(f"  Trying: python manage.py {cmd}")
        rc = run(f"{sys.executable} manage.py {cmd}",
                 cwd=str(project_root), check=False)
        if rc == 0:
            ok(f"  Success: python manage.py {cmd}")
            return True
        warn(f"  Not available (exit {rc}), trying next...")

    error(textwrap.dedent("""
    None of the known command variants worked.
    Find the correct command for your installed version:

      python manage.py help | grep -i frontend
      python manage.py help | grep -i bootstrap
      pip show djangocms-frontend

    Then run it manually and re-run --mode cleanup when done.
    Docs: https://djangocms-frontend.readthedocs.io/en/latest/migration.html
    """))
    return False


# ─────────────────────────────────────────────
# Cleanup — remove djangocms-bootstrap4
# ─────────────────────────────────────────────
def run_cleanup():
    """
    Remove djangocms-bootstrap4 after the frontend migration is verified.
    """
    banner("Cleanup: uninstalling djangocms-bootstrap4")
    pip_uninstall("djangocms-bootstrap4")
    warn(textwrap.dedent("""
    Manual edit required in settings.py:
      Remove 'djangocms_bootstrap4' from INSTALLED_APPS.
      Keep   'djangocms_frontend'   (this is the new plugin app).

    Then run:
      python manage.py migrate
      python manage.py cms fix-tree
      python manage.py check --deploy
    """))
    ok("  djangocms-bootstrap4 uninstalled.")


# ─────────────────────────────────────────────
# Snapshot
# ─────────────────────────────────────────────
def save_snapshot(conn: sqlite3.Connection, output_path: Path):
    cur = conn.cursor()
    cur.execute("""
        SELECT p.id, p.reverse_id, p.publisher_is_draft, t.slug, t.title
        FROM cms_page p
        LEFT JOIN cms_title t ON t.page_id = p.id AND t.language = 'en'
        WHERE p.reverse_id != '' AND p.reverse_id IS NOT NULL
        ORDER BY p.id
    """)
    mapping = {}
    for pid, rev_id, is_draft, slug, title in cur.fetchall():
        if rev_id not in mapping or is_draft:
            mapping[rev_id] = {
                "old_id": pid, "is_draft": bool(is_draft),
                "slug": slug, "title": title,
            }
    output_path.write_text(json.dumps(mapping, indent=2, ensure_ascii=False))
    ok(f"  Snapshot saved → {output_path}  ({len(mapping)} pages)")
    info("  Run step3_cms4.py, then come back with --mode remap-fks.")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Kairos Bootstrap4 → djangocms-frontend data migration helper")
    parser.add_argument("--db", default="project.db")
    parser.add_argument(
        "--mode", default="remap-fks",
        choices=["snapshot", "remap-fks", "frontend", "cleanup", "full"],
        help=(
            "snapshot  : save page ID map BEFORE step3_cms4.py\n"
            "remap-fks : fix page FK refs AFTER step3_cms4.py, BEFORE frontend migration\n"
            "frontend  : run djangocms-frontend migration command only\n"
            "cleanup   : uninstall djangocms-bootstrap4 AFTER frontend migration verified\n"
            "full      : remap-fks + frontend + cleanup in one go\n"
        )
    )
    parser.add_argument("--pre-migration-map", default="pre_cms4_page_map.json")
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()

    if args.mode == "cleanup":
        run_cleanup()
        return

    if args.mode == "frontend":
        run_frontend_migration(root)
        return

    db_path = Path(args.db)
    if not db_path.exists():
        error(f"Database not found: {db_path}")
        sys.exit(1)

    backup_sqlite(db_path, label=f"bs4_{args.mode}")
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = OFF")

    if args.mode == "snapshot":
        banner("Saving pre-migration page ID snapshot")
        save_snapshot(conn, Path(args.pre_migration_map))

    elif args.mode in ("remap-fks", "full"):
        banner("Remapping page ID FKs after CMS 4 migration")

        pre_map_path = Path(args.pre_migration_map)
        if pre_map_path.exists():
            pre_data = json.loads(pre_map_path.read_text())
            pre_map = {r: d["old_id"] for r, d in pre_data.items()}
            post_map = build_page_id_map(conn)
            remap = build_remap(pre_map, post_map)
        else:
            warn(f"  {pre_map_path} not found — verifying current IDs without remapping.")
            remap = {}

        n1 = fix_bootstrap4_link_fks(conn, remap)
        n2 = fix_page_link_plugin_fks(conn, remap)
        n3 = fix_bootstrap4_picture_fks(conn, remap)
        if remap:
            ok(f"  Remapped: {n1} Bootstrap4Link, {n2} PageLinkBox, {n3} Bootstrap4Picture")

        fks_ok = verify_fks(conn)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()

        if args.mode == "full":
            if not fks_ok:
                error("FK errors — fix them before continuing.")
                sys.exit(1)
            success = run_frontend_migration(root)
            if success:
                run_cleanup()
            else:
                warn("Frontend migration failed — run --mode cleanup manually after fixing.")
            return

        if fks_ok:
            print(textwrap.dedent("""
            FKs remapped and verified. Now run the djangocms-frontend command:

              python manage.py cms_frontend migrate bootstrap4
              (or: python manage.py help | grep -i frontend  to find the command)

            Verify the site renders correctly, then:
              python step3_kairos_bootstrap4_migrate.py --mode cleanup
            """))
        return

    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()
    banner("Done ✔")


if __name__ == "__main__":
    main()
