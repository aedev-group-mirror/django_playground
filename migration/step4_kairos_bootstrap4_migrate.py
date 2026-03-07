#!/usr/bin/env python3
"""
step4_kairos_bootstrap4_migrate.py
════════════════════════════════════
Kairos-specific companion to step4_cms4.py.

Handles two critical data problems specific to this project:

  1. FK REMAPPING after CMS 4 reassigns page IDs:
     - bootstrap4_link_bootstrap4link.internal_link_id  → cms_page.id
     - page_link_plugin_pagelinkboxmodel.page_link_id   → cms_page.id
     These FKs break because CMS 4 reassigns page IDs during data migration.
     This script uses the stable 'reverse_id' to find the new page IDs and
     patches the FKs accordingly.

  2. BOOTSTRAP4 → BOOTSTRAP5 schema migration (optional):
     Copies data from the bootstrap4_* tables into djangocms_bootstrap5_*
     tables (if djangocms-bootstrap5 is installed).
     Covers: GridContainer, GridRow, GridColumn, Link, Picture, Blockquote.

Run AFTER step4_cms4.py:
    python path/to/step4_kairos_bootstrap4_migrate.py \\
        --db path/to/project.db \\
        --mode remap-fks         # just fix page ID references
    or:
    python path/to/step4_kairos_bootstrap4_migrate.py \\
        --db path/to/project.db \\
        --mode full              # remap FKs + copy to bootstrap5 tables

IMPORTANT: Run this before starting the Django dev server after step 4.
"""

import argparse
import json
import sqlite3
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from migration_utils import banner, ok, info, warn, error, backup_sqlite

# ─────────────────────────────────────────────
# Known page reverse_ids from kairos project
# (verified from DB analysis)
# ─────────────────────────────────────────────
KAIROS_REVERSE_IDS = [
    "00_hl",         # Home
    "10",            # About us
    "20",            # The Rules
    "70_hl",         # Announcements
    "legal_notice",  # Legal Notice
    "60",            # Philosophy
    "90_hl",         # Messages
    "data_collection",
    "privacy_policy",
    "mbr_signup",    # Member Signup
    "96",            # Members List
]


# ─────────────────────────────────────────────
# Step 1: Build old → new page ID map via reverse_id
# ─────────────────────────────────────────────
def build_page_id_map(conn: sqlite3.Connection) -> dict[int, int]:
    """
    Before CMS 4 migration: map old draft page IDs to themselves.
    After CMS 4 migration: CMS may have changed IDs; use reverse_id to find new ones.

    Returns {old_page_id: new_page_id}
    """
    cur = conn.cursor()

    # Get current pages indexed by reverse_id
    cur.execute("""
        SELECT p.id, p.reverse_id, p.publisher_is_draft, t.title
        FROM cms_page p
        LEFT JOIN cms_title t ON t.page_id = p.id AND t.language = 'en'
        WHERE p.reverse_id != ''
        ORDER BY p.id
    """)
    pages = cur.fetchall()

    info("  Current page ID → reverse_id mapping:")
    for pid, rev_id, is_draft, title in pages:
        draft_label = "DRAFT " if is_draft else "PUBLIC"
        info(f"    id={pid} [{draft_label}] reverse_id='{rev_id}'  \"{title}\"")

    # For CMS 4: pages are no longer split into draft/public.
    # After the CMS 4 migration, there will be one Page record per page.
    # We prefer the DRAFT id (since CMS 4 keeps the draft as the canonical record).
    page_map: dict[int, int] = {}  # reverse_id → id    # ae: was dict[str, int]

    for pid, rev_id, is_draft, title in pages:
        if rev_id and rev_id not in page_map:
            page_map[rev_id] = pid
        elif rev_id and is_draft:
            # Prefer draft if both exist (pre-migration state)
            page_map[rev_id] = pid

    return page_map


def build_id_remap_from_pre_post(
    pre_map: dict[str, int],
    post_map: dict[str, int]
) -> dict[int, int]:
    """
    Given the reverse_id→id mapping BEFORE and AFTER the CMS 4 migration,
    compute the old_id → new_id remapping.
    """
    remap: dict[int, int] = {}
    for rev_id, old_id in pre_map.items():
        new_id = post_map.get(rev_id)
        if new_id and old_id != new_id:
            remap[old_id] = new_id
            info(f"  Remap: page {old_id} → {new_id} (reverse_id='{rev_id}')")
        elif new_id:
            ok(f"  No change: page {old_id} (reverse_id='{rev_id}')")
    return remap


# ─────────────────────────────────────────────
# Step 2: Fix Bootstrap4Link.internal_link_id FKs
# ─────────────────────────────────────────────
def fix_bootstrap4_link_fks(conn: sqlite3.Connection, remap: dict[int, int]) -> int:
    """
    Update bootstrap4_link_bootstrap4link.internal_link_id
    according to the old→new page ID remap.
    Returns number of rows updated.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT cmsplugin_ptr_id, name, internal_link_id
        FROM bootstrap4_link_bootstrap4link
        WHERE internal_link_id IS NOT NULL
    """)
    rows = cur.fetchall()

    updated = 0
    for plugin_id, name, old_page_id in rows:
        new_page_id = remap.get(old_page_id)
        if new_page_id:
            cur.execute("""
                UPDATE bootstrap4_link_bootstrap4link
                SET internal_link_id = ?
                WHERE cmsplugin_ptr_id = ?
            """, (new_page_id, plugin_id))
            info(f"  Bootstrap4Link id={plugin_id} '{name}': "
                 f"internal_link_id {old_page_id} → {new_page_id}")
            updated += 1
        elif old_page_id:
            warn(f"  Bootstrap4Link id={plugin_id} '{name}': "
                 f"old page_id={old_page_id} has no new mapping — "
                 "link may be broken. Check manually.")

    conn.commit()
    return updated


# ─────────────────────────────────────────────
# Step 3: Fix PageLinkBoxPlugin.page_link_id FKs
# ─────────────────────────────────────────────
def fix_page_link_plugin_fks(conn: sqlite3.Connection, remap: dict[int, int]) -> int:
    """
    Update page_link_plugin_pagelinkboxmodel.page_link_id
    according to the old→new page ID remap.

    From DB analysis, these 18 rows all point to:
      page 4  (The Rules)       → via reverse_id '20'
      page 5  (Announcements)   → via reverse_id '70_hl'
      page 15 (Messages)        → via reverse_id '90_hl'
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT cmsplugin_ptr_id, page_link_id, page_image_id
        FROM page_link_plugin_pagelinkboxmodel
    """)
    rows = cur.fetchall()

    updated = 0
    for plugin_id, old_page_id, image_id in rows:
        new_page_id = remap.get(old_page_id)
        if new_page_id:
            cur.execute("""
                UPDATE page_link_plugin_pagelinkboxmodel
                SET page_link_id = ?
                WHERE cmsplugin_ptr_id = ?
            """, (new_page_id, plugin_id))
            info(f"  PageLinkBox id={plugin_id}: "
                 f"page_link_id {old_page_id} → {new_page_id} (image_id={image_id})")
            updated += 1
        elif old_page_id:
            warn(f"  PageLinkBox id={plugin_id}: "
                 f"old page_id={old_page_id} has no new mapping!")

    conn.commit()
    return updated


# ─────────────────────────────────────────────
# Step 4: Fix Bootstrap4Picture.link_page_id FKs (if any)
# ─────────────────────────────────────────────
def fix_bootstrap4_picture_fks(conn: sqlite3.Connection, remap: dict[int, int]) -> int:
    cur = conn.cursor()
    cur.execute("""
        SELECT cmsplugin_ptr_id, link_page_id
        FROM bootstrap4_picture_bootstrap4picture
        WHERE link_page_id IS NOT NULL AND link_page_id != ''
    """)
    rows = cur.fetchall()

    if not rows:
        ok("  No Bootstrap4Picture link_page_id FKs to fix.")
        return 0

    updated = 0
    for plugin_id, old_page_id in rows:
        if old_page_id:
            new_page_id = remap.get(int(old_page_id))
            if new_page_id:
                cur.execute("""
                    UPDATE bootstrap4_picture_bootstrap4picture
                    SET link_page_id = ?
                    WHERE cmsplugin_ptr_id = ?
                """, (str(new_page_id), plugin_id))
                info(f"  Bootstrap4Picture id={plugin_id}: "
                     f"link_page_id {old_page_id} → {new_page_id}")
                updated += 1

    conn.commit()
    return updated


# ─────────────────────────────────────────────
# Step 5: Bootstrap4 → Bootstrap5 schema migration
# ─────────────────────────────────────────────
def check_bootstrap5_installed(conn: sqlite3.Connection) -> bool:
    cur = conn.cursor()
    cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name LIKE 'djangocms_bootstrap5%'
        LIMIT 1
    """)
    return cur.fetchone() is not None


def migrate_grid_to_bootstrap5(conn: sqlite3.Connection) -> dict[str, int]:
    """
    Copy Bootstrap4 Grid data to Bootstrap5 tables.

    Bootstrap5 Grid schema is similar to Bootstrap4 but with renamed breakpoints.
    Bootstrap4 breakpoints: xs, sm, md, lg, xl
    Bootstrap5 breakpoints: xs, sm, md, lg, xl, xxl (xxl is new, default NULL)

    Returns stats dict.
    """
    cur = conn.cursor()
    stats: dict[str, int] = {}

    # ── GridContainer ────────────────────────
    # BS4 has bootstrap4_grid_bootstrap4gridcontainer (0 rows in kairos)
    # Skip if empty.
    cur.execute("SELECT COUNT(*) FROM bootstrap4_grid_bootstrap4gridcontainer")
    if cur.fetchone()[0] > 0:
        warn("  GridContainer migration: non-empty, but not needed for kairos. Skipping.")

    # ── GridRow ──────────────────────────────
    # BS4: (cmsplugin_ptr_id, vertical_alignment, horizontal_alignment, gutters, tag_type, attributes)
    # BS5: Similar schema — check if table exists first
    cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='djangocms_bootstrap5_grid_bootstrap5gridrow'
    """)
    if cur.fetchone():
        cur.execute("""
            SELECT cmsplugin_ptr_id, vertical_alignment, horizontal_alignment,
                   tag_type, attributes
            FROM bootstrap4_grid_bootstrap4gridrow
        """)
        rows = cur.fetchall()
        n = 0
        for r in rows:
            try:
                cur.execute("""
                    INSERT OR IGNORE INTO djangocms_bootstrap5_grid_bootstrap5gridrow
                    (cmsplugin_ptr_id, vertical_alignment, horizontal_alignment,
                     tag_type, attributes)
                    VALUES (?, ?, ?, ?, ?)
                """, r)
                n += 1
            except Exception as e:
                warn(f"    Row {r[0]}: {e}")
        conn.commit()
        stats["grid_rows"] = n
        ok(f"  GridRow: migrated {n} rows to bootstrap5 table.")
    else:
        warn("  djangocms_bootstrap5_grid_bootstrap5gridrow not found — "
             "install djangocms-bootstrap5 first.")

    # ── GridColumn ───────────────────────────
    cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='djangocms_bootstrap5_grid_bootstrap5gridcolumn'
    """)
    if cur.fetchone():
        cur.execute("""
            SELECT cmsplugin_ptr_id, column_type, column_alignment, tag_type, attributes,
                   xs_col, xs_order, xs_ml, xs_mr, xs_offset,
                   sm_col, sm_order, sm_ml, sm_mr, sm_offset,
                   md_col, md_order, md_ml, md_mr, md_offset,
                   lg_col, lg_order, lg_ml, lg_mr, lg_offset,
                   xl_col, xl_order, xl_ml, xl_mr, xl_offset
            FROM bootstrap4_grid_bootstrap4gridcolumn
        """)
        rows = cur.fetchall()
        n = 0
        for r in rows:
            # BS5 adds xxl breakpoint (NULL for migrated content)
            try:
                cur.execute("""
                    INSERT OR IGNORE INTO djangocms_bootstrap5_grid_bootstrap5gridcolumn
                    (cmsplugin_ptr_id, column_type, column_alignment, tag_type, attributes,
                     xs_col, xs_order, xs_ml, xs_mr, xs_offset,
                     sm_col, sm_order, sm_ml, sm_mr, sm_offset,
                     md_col, md_order, md_ml, md_mr, md_offset,
                     lg_col, lg_order, lg_ml, lg_mr, lg_offset,
                     xl_col, xl_order, xl_ml, xl_mr, xl_offset,
                     xxl_col, xxl_order, xxl_ml, xxl_mr, xxl_offset)
                    VALUES (?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?,
                            NULL, NULL, 0, 0, NULL)
                """, r)
                n += 1
            except Exception as e:
                warn(f"    Column {r[0]}: {e}")
        conn.commit()
        stats["grid_columns"] = n
        ok(f"  GridColumn: migrated {n} rows to bootstrap5 table.")
    else:
        warn("  djangocms_bootstrap5_grid_bootstrap5gridcolumn not found.")

    return stats


def migrate_link_to_bootstrap5(conn: sqlite3.Connection) -> int:
    """
    Migrate Bootstrap4Link → Bootstrap5Link.
    Schema is nearly identical; just the table name changes.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='djangocms_bootstrap5_link_bootstrap5link'
    """)
    if not cur.fetchone():
        warn("  djangocms_bootstrap5_link_bootstrap5link not found. Skipping.")
        return 0

    cur.execute("""
        SELECT cmsplugin_ptr_id, template, name, anchor, mailto, phone,
               target, attributes, link_type, link_context, link_size,
               link_outline, link_block, internal_link_id, icon_left,
               icon_right, file_link_id, external_link
        FROM bootstrap4_link_bootstrap4link
    """)
    rows = cur.fetchall()
    n = 0
    for r in rows:
        try:
            cur.execute("""
                INSERT OR IGNORE INTO djangocms_bootstrap5_link_bootstrap5link
                (cmsplugin_ptr_id, template, name, anchor, mailto, phone,
                 target, attributes, link_type, link_context, link_size,
                 link_outline, link_block, internal_link_id, icon_left,
                 icon_right, file_link_id, external_link)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, r)
            n += 1
        except Exception as e:
            warn(f"    Link {r[0]}: {e}")
    conn.commit()
    ok(f"  Link: migrated {n} rows to bootstrap5 table.")
    return n


def migrate_picture_to_bootstrap5(conn: sqlite3.Connection) -> int:
    """
    Migrate Bootstrap4Picture → Bootstrap5Picture.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='djangocms_bootstrap5_picture_bootstrap5picture'
    """)
    if not cur.fetchone():
        warn("  djangocms_bootstrap5_picture_bootstrap5picture not found. Skipping.")
        return 0

    cur.execute("""
        SELECT cmsplugin_ptr_id, template, external_picture, width, height,
               alignment, caption_text, attributes, link_target, link_attributes,
               use_automatic_scaling, use_no_cropping, use_crop, use_upscale,
               picture_fluid, picture_rounded, picture_thumbnail,
               link_page_id, picture_id, thumbnail_options_id,
               use_responsive_image, link_url
        FROM bootstrap4_picture_bootstrap4picture
    """)
    rows = cur.fetchall()
    n = 0
    for r in rows:
        try:
            cur.execute("""
                INSERT OR IGNORE INTO djangocms_bootstrap5_picture_bootstrap5picture
                (cmsplugin_ptr_id, template, external_picture, width, height,
                 alignment, caption_text, attributes, link_target, link_attributes,
                 use_automatic_scaling, use_no_cropping, use_crop, use_upscale,
                 picture_fluid, picture_rounded, picture_thumbnail,
                 link_page_id, picture_id, thumbnail_options_id,
                 use_responsive_image, link_url)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, r)
            n += 1
        except Exception as e:
            warn(f"    Picture {r[0]}: {e}")
    conn.commit()
    ok(f"  Picture: migrated {n} rows to bootstrap5 table.")
    return n


# ─────────────────────────────────────────────
# Verification
# ─────────────────────────────────────────────
def verify_fks(conn: sqlite3.Connection):
    """Check that all FK references now point to existing pages."""
    banner("Verifying FK integrity after remapping")
    cur = conn.cursor()

    # Bootstrap4Link
    cur.execute("""
        SELECT bl.cmsplugin_ptr_id, bl.name, bl.internal_link_id
        FROM bootstrap4_link_bootstrap4link bl
        WHERE bl.internal_link_id IS NOT NULL
    """)
    for plugin_id, name, page_id in cur.fetchall():
        cur.execute("SELECT id FROM cms_page WHERE id=?", (page_id,))
        if cur.fetchone():
            ok(f"  Bootstrap4Link {plugin_id} '{name}' → page {page_id} ✔")
        else:
            error(f"  Bootstrap4Link {plugin_id} '{name}' → page {page_id} MISSING ✘")

    # PageLinkBoxPlugin
    cur.execute("""
        SELECT cmsplugin_ptr_id, page_link_id
        FROM page_link_plugin_pagelinkboxmodel
    """)
    for plugin_id, page_id in cur.fetchall():
        cur.execute("SELECT id FROM cms_page WHERE id=?", (page_id,))
        if cur.fetchone():
            ok(f"  PageLinkBox {plugin_id} → page {page_id} ✔")
        else:
            error(f"  PageLinkBox {plugin_id} → page {page_id} MISSING ✘")


# ─────────────────────────────────────────────
# Save pre-migration snapshot
# ─────────────────────────────────────────────
def save_pre_migration_page_map(conn: sqlite3.Connection, output_path: Path):
    """Save the reverse_id → page_id mapping to a JSON file for use after migration."""
    cur = conn.cursor()
    cur.execute("""
        SELECT p.id, p.reverse_id, p.publisher_is_draft, t.slug, t.title
        FROM cms_page p
        LEFT JOIN cms_title t ON t.page_id = p.id AND t.language = 'en'
        WHERE p.reverse_id != ''
        ORDER BY p.id
    """)
    rows = cur.fetchall()
    mapping = {
        row[1]: {  # reverse_id as key
            "old_id": row[0],
            "is_draft": bool(row[2]),
            "slug": row[3],
            "title": row[4],
        }
        for row in rows
    }
    output_path.write_text(json.dumps(mapping, indent=2))
    ok(f"  Pre-migration page map saved to: {output_path}")
    return mapping


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Kairos-specific Bootstrap4 data migration for CMS 4 upgrade")
    parser.add_argument("--db", required=True,
                        help="Path to the SQLite database file")
    parser.add_argument("--mode", default="remap-fks",
                        choices=["snapshot", "remap-fks", "bootstrap5", "full"],
                        help=(
                            "snapshot: save pre-migration page ID map (run BEFORE cms4 migrate)\n"
                            "remap-fks: fix broken page FK references (run AFTER cms4 migrate)\n"
                            "bootstrap5: copy BS4 data to BS5 tables (needs djangocms-bootstrap5)\n"
                            "full: remap-fks + bootstrap5\n"
                        ))
    parser.add_argument("--pre-migration-map",
                        default="pre_cms4_page_map.json",
                        help="Path to JSON file with pre-migration page ID mapping")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        error(f"Database not found: {db_path}")
        sys.exit(1)

    backup_sqlite(db_path, label="bootstrap4_migrate")
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = OFF")  # Disable FK checks during migration

    if args.mode == "snapshot":
        banner("Saving pre-migration page ID snapshot")
        save_pre_migration_page_map(conn, Path(args.pre_migration_map))
        print(textwrap.dedent("""
        Snapshot saved. Now run:
          python step4_cms4.py --project-root .
        Then run this script again with --mode remap-fks
        """))

    elif args.mode in ("remap-fks", "full"):
        banner("Remapping page ID FKs after CMS 4 migration")

        pre_map_path = Path(args.pre_migration_map)

        if not pre_map_path.exists():
            warn(f"  Pre-migration map not found at {pre_map_path}.")
            warn("  Attempting to use current page IDs (assumes IDs unchanged).")
            _page_map = build_page_id_map(conn)
            remap: dict[int, int] = {}  # no remapping needed
        else:
            import json as _json
            pre_map = _json.loads(pre_map_path.read_text())
            post_map = build_page_id_map(conn)

            # Convert reverse_id → old_id from pre-migration snapshot
            _pre_id_map = {data["old_id"]: rev_id for rev_id, data in pre_map.items()}

            # Build old_page_id → new_page_id
            remap = {}
            for rev_id, pre_data in pre_map.items():
                old_id = pre_data["old_id"]
                new_id = post_map.get(rev_id)
                if new_id and old_id != new_id:
                    remap[old_id] = new_id

        info(f"  Page ID remap: {remap if remap else 'no changes (IDs are stable)'}")

        if remap:
            n1 = fix_bootstrap4_link_fks(conn, remap)
            n2 = fix_page_link_plugin_fks(conn, remap)
            n3 = fix_bootstrap4_picture_fks(conn, remap)
            ok(f"  Fixed: {n1} Bootstrap4Link, {n2} PageLinkBox, {n3} Bootstrap4Picture FKs")
        else:
            ok("  No FK remapping needed — page IDs were preserved by CMS 4 migration.")

        verify_fks(conn)

        if args.mode == "full":
            if check_bootstrap5_installed(conn):
                banner("Migrating Bootstrap4 data → Bootstrap5 tables")
                migrate_grid_to_bootstrap5(conn)
                migrate_link_to_bootstrap5(conn)
                migrate_picture_to_bootstrap5(conn)
            else:
                warn("  djangocms-bootstrap5 tables not found. "
                     "Install djangocms-bootstrap5, run migrate, then re-run with --mode bootstrap5.")

    elif args.mode == "bootstrap5":
        if check_bootstrap5_installed(conn):
            banner("Migrating Bootstrap4 data → Bootstrap5 tables")
            migrate_grid_to_bootstrap5(conn)
            migrate_link_to_bootstrap5(conn)
            migrate_picture_to_bootstrap5(conn)
        else:
            error("djangocms-bootstrap5 tables not found in database. "
                  "Run: pip install djangocms-bootstrap5 && python manage.py migrate")
            sys.exit(1)

    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()

    banner("Done ✔")
    print(textwrap.dedent(f"""
    Mode: {args.mode}

    Next: start the dev server and check:
      - CMS pages load correctly
      - Bootstrap4/5 layout plugins render
      - PageLinkBox cards link to correct pages
      - All Bootstrap4Link internal links work
    """))


if __name__ == "__main__":
    main()
