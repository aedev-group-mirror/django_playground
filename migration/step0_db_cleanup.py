#!/usr/bin/env python3
"""
step0_db_cleanup.py
════════════════════
Run this BEFORE step 1. Cleans up the kairos SQLite database:

  1. Flushes 23,255 expired sessions (saves ~2-3 MB, speeds up migrations)
  2. Verifies no orphan CMS plugin records
  3. Verifies draft/published page pairs are intact
  4. Verifies FK integrity of custom plugins (PageLinkBox, Bootstrap4Link)
  5. Reports any issues that need manual attention

Usage:
    python step0_db_cleanup.py --db path/to/project.db [--fix]
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from migration_utils import banner, ok, info, warn, error, backup_sqlite


def check_sessions(conn: sqlite3.Connection, fix: bool):
    banner("Sessions")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM django_session")
    total = cur.fetchone()[0]
    info(f"  {total} sessions found.")
    if total > 1000:
        warn(f"  {total} sessions — flushing them will speed up migrations.")
        if fix:
            cur.execute("DELETE FROM django_session")
            conn.commit()
            ok(f"  Deleted all {total} sessions.")
        else:
            info("  Run with --fix to delete sessions (or: python manage.py clearsessions)")


def check_page_pairs(conn: sqlite3.Connection):
    banner("CMS page draft/public pairs")
    cur = conn.cursor()
    cur.execute("""
        SELECT id, publisher_is_draft, publisher_public_id, reverse_id
        FROM cms_page ORDER BY id
    """)
    pages = cur.fetchall()

    # Check all draft pages have a matching published page
    drafts = {p[0]: p for p in pages if p[1] == 1}
    publics = {p[0]: p for p in pages if p[1] == 0}

    ok(f"  {len(drafts)} draft pages, {len(publics)} published pages")

    for draft_id, draft in drafts.items():
        pub_id = draft[2]  # publisher_public_id
        if pub_id and pub_id in publics:
            ok(f"  Draft {draft_id} (rev='{draft[3]}') ↔ Public {pub_id} ✔")
        elif pub_id:
            error(f"  Draft {draft_id} points to public {pub_id} but that page is missing!")
        else:
            warn(f"  Draft {draft_id} (rev='{draft[3]}') has no publisher_public_id — unpublished page")


def check_cms_plugins(conn: sqlite3.Connection):
    banner("CMS plugin integrity")
    cur = conn.cursor()

    # Check for plugins with no placeholder
    cur.execute("""
        SELECT COUNT(*) FROM cms_cmsplugin
        WHERE placeholder_id NOT IN (SELECT id FROM cms_placeholder)
    """)
    orphans = cur.fetchone()[0]
    if orphans:
        error(f"  {orphans} CMS plugins have invalid placeholder_id!")
    else:
        ok("  All CMS plugins have valid placeholder references.")

    # Check for plugin records in child tables that have no parent in cms_cmsplugin
    for table in [
        "bootstrap4_grid_bootstrap4gridcolumn",
        "bootstrap4_grid_bootstrap4gridrow",
        "bootstrap4_link_bootstrap4link",
        "bootstrap4_picture_bootstrap4picture",
        "bootstrap4_content_bootstrap4blockquote",
        "djangocms_text_ckeditor_text",
        "page_link_plugin_pagelinkboxmodel",
    ]:
        cur.execute(f"""
            SELECT COUNT(*) FROM {table}
            WHERE cmsplugin_ptr_id NOT IN (SELECT id FROM cms_cmsplugin)
        """)
        orphans = cur.fetchone()[0]
        if orphans:
            error(f"  {table}: {orphans} orphan rows (no parent in cms_cmsplugin)!")
        else:
            ok(f"  {table}: OK")


def check_filer_references(conn: sqlite3.Connection):
    banner("Filer image references")
    cur = conn.cursor()

    # Bootstrap4Picture → filer_image
    cur.execute("""
        SELECT COUNT(*) FROM bootstrap4_picture_bootstrap4picture
        WHERE picture_id IS NOT NULL
          AND picture_id NOT IN (SELECT id FROM filer_image)
    """)
    broken = cur.fetchone()[0]
    if broken:
        error(f"  Bootstrap4Picture: {broken} broken picture_id FK(s) to filer_image!")
    else:
        ok("  Bootstrap4Picture → filer_image: all FKs valid")

    # PageLinkBoxPlugin → filer_file
    cur.execute("""
        SELECT COUNT(*) FROM page_link_plugin_pagelinkboxmodel
        WHERE page_image_id IS NOT NULL
          AND page_image_id NOT IN (SELECT id FROM filer_file)
    """)
    broken = cur.fetchone()[0]
    if broken:
        error(f"  PageLinkBoxPlugin: {broken} broken page_image_id FK(s) to filer_file!")
    else:
        ok("  PageLinkBoxPlugin → filer_file: all FKs valid")


def check_page_fk_references(conn: sqlite3.Connection):
    banner("Page FK references (pre-migration baseline)")
    cur = conn.cursor()

    # Bootstrap4Link internal links
    cur.execute("""
        SELECT cmsplugin_ptr_id, name, internal_link_id
        FROM bootstrap4_link_bootstrap4link
        WHERE internal_link_id IS NOT NULL
    """)
    rows = cur.fetchall()
    for plugin_id, name, page_id in rows:
        cur.execute("SELECT publisher_is_draft, reverse_id FROM cms_page WHERE id=?", (page_id,))
        r = cur.fetchone()
        if r:
            ok(f"  Bootstrap4Link {plugin_id} '{name}' → page {page_id} "
               f"({'DRAFT' if r[0] else 'PUBLIC'}, rev='{r[1]}') ✔")
        else:
            error(f"  Bootstrap4Link {plugin_id} '{name}' → page {page_id} MISSING ✘")

    # PageLinkBox page links
    cur.execute("""
        SELECT cmsplugin_ptr_id, page_link_id
        FROM page_link_plugin_pagelinkboxmodel
    """)
    rows = cur.fetchall()
    for plugin_id, page_id in rows:
        cur.execute("SELECT publisher_is_draft, reverse_id FROM cms_page WHERE id=?", (page_id,))
        r = cur.fetchone()
        if r:
            ok(f"  PageLinkBox {plugin_id} → page {page_id} "
               f"({'DRAFT' if r[0] else 'PUBLIC'}, rev='{r[1]}') ✔")
        else:
            error(f"  PageLinkBox {plugin_id} → page {page_id} MISSING ✘")


def print_plugin_summary(conn: sqlite3.Connection):
    banner("Plugin type summary (for reference)")
    cur = conn.cursor()
    cur.execute("""
        SELECT plugin_type, COUNT(*) as cnt
        FROM cms_cmsplugin
        GROUP BY plugin_type
        ORDER BY cnt DESC
    """)
    for plugin_type, count in cur.fetchall():
        info(f"  {count:>5}  {plugin_type}")


def check_user_data(conn: sqlite3.Connection):
    banner("User / member data")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM auth_user")
    total_users = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM mbr_announcements_memberannouncement")
    total_ann = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM mbr_meeting_plugin_membermeeting")
    total_meetings = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM mbr_messages_membermessage")
    total_msgs = cur.fetchone()[0]

    ok(f"  {total_users} users")
    ok(f"  {total_ann} member announcements")
    ok(f"  {total_meetings} member meetings")
    ok(f"  {total_msgs} member messages")
    info("  These tables are CMS-independent and will survive all migration steps.")


def main():
    parser = argparse.ArgumentParser(
        description="Pre-migration DB cleanup for kairos project")
    parser.add_argument("--db", default="project.db",
                        help="Path to SQLite database")
    parser.add_argument("--fix", action="store_true",
                        help="Actually apply fixes (default: dry run / report only)")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        error(f"Database not found: {db_path}")
        sys.exit(1)

    backup_sqlite(db_path, label="pre_cleanup")
    conn = sqlite3.connect(str(db_path))

    check_sessions(conn, fix=args.fix)
    check_page_pairs(conn)
    check_cms_plugins(conn)
    check_filer_references(conn)
    check_page_fk_references(conn)
    check_user_data(conn)
    print_plugin_summary(conn)

    conn.close()

    banner("Cleanup check complete")
    if not args.fix:
        print("  Run with --fix to apply auto-fixable issues (session flush).")
    print("\n  Ready to begin migration? Run:\n    python step1_django32.py --project-root .\n")


if __name__ == "__main__":
    main()
