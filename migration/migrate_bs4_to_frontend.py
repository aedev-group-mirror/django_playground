#!/usr/bin/env python3
"""
migrate_bs4_to_frontend.py
══════════════════════════
Direct Bootstrap4 → djangocms-frontend 2.x migration script.

Bypasses the broken `manage.py frontend migrate` command which fails
because djangocms-frontend 2.x no longer registers sub-apps (grid,
image, link) as separate Django AppConfigs.

Reads Bootstrap4 plugin rows directly from the DB and creates
equivalent djangocms_frontend_frontenduiitem rows.

Prerequisites:
  - step3_cms4.py completed (CMS 4 migrations applied)
  - djangocms-frontend >= 2.0 installed
  - djangocms-link >= 5.0 installed
  - ALL djangocms_bootstrap4* removed from INSTALLED_APPS
  - djangocms_icon back in INSTALLED_APPS

Run from the kairos project root:
    python migration/migrate_bs4_to_frontend.py
"""

import json
import os
import sys
import django

sys.path.insert(0, os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kairos.settings")
django.setup()

from django.db import connection  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────

def sql(query, params=None):
    with connection.cursor() as cur:
        cur.execute(query, params or [])
        return cur.fetchall()

def execute(query, params=None):
    query = query.replace("?", "%s")
    with connection.cursor() as cur:
        cur.execute(query, params or [])

def table_exists(name):
    return name in connection.introspection.table_names()

def row_count(table):
    return sql(f"SELECT COUNT(*) FROM {table}")[0][0]


# ── Verify prerequisites ───────────────────────────────────────────────────────
print("\n── Checking prerequisites ────────────────────────────────────────")

required = [
    "djangocms_frontend_frontenduiitem",
    "cms_cmsplugin",
    "bootstrap4_grid_bootstrap4gridrow",
    "bootstrap4_grid_bootstrap4gridcolumn",
    "bootstrap4_link_bootstrap4link",
    "bootstrap4_picture_bootstrap4picture",
]
for t in required:
    if table_exists(t):
        print(f"  ✔  {t} ({row_count(t)} rows)")
    else:
        print(f"  ✘  {t} NOT FOUND — aborting.")
        sys.exit(1)

existing = row_count("djangocms_frontend_frontenduiitem")
if existing > 0:
    print(f"\n  ⚠  djangocms_frontend_frontenduiitem already has {existing} rows.")
    answer = input("     Continue and ADD more rows? (yes/no): ").strip().lower()
    if answer != "yes":
        print("Aborted.")
        sys.exit(0)


# ── GridRow ───────────────────────────────────────────────────────────────────

def migrate_grid_rows():
    print("\n── Bootstrap4GridRow → GridRowPlugin ────────────────────────────")
    rows = sql("""
        SELECT cmsplugin_ptr_id, horizontal_alignment, vertical_alignment,
               gutters, tag_type, attributes
        FROM bootstrap4_grid_bootstrap4gridrow
    """)
    print(f"  Found {len(rows)} rows")
    n = 0
    for (pid, h_align, v_align, gutters, tag_type, attributes_json) in rows:
        try:
            attributes = json.loads(attributes_json) if attributes_json else {}
        except (json.JSONDecodeError, TypeError):
            attributes = {}

        config = {
            "horizontal_alignment": h_align or "",
            "vertical_alignment": v_align or "",
            "gutters": bool(gutters),
            "tag_type": tag_type or "div",
            "attributes": attributes,
            "margin_x": None, "margin_y": None,
            "padding_x": None, "padding_y": None,
            "responsive_visibility": None,
            "background_context": "", "background_shadow": "",
        }
        execute("""
            INSERT OR IGNORE INTO djangocms_frontend_frontenduiitem
                (cmsplugin_ptr_id, ui_item, tag_type, config)
            VALUES (?, ?, ?, ?)
        """, [pid, "GridRow", tag_type or "div", json.dumps(config)])
        execute("UPDATE cms_cmsplugin SET plugin_type='GridRowPlugin' WHERE id=?", [pid])
        n += 1
    print(f"  ✔  Migrated {n}")
    return n


# ── GridColumn ────────────────────────────────────────────────────────────────

def migrate_grid_columns():
    print("\n── Bootstrap4GridColumn → GridColumnPlugin ──────────────────────")
    rows = sql("""
        SELECT cmsplugin_ptr_id, column_type, column_alignment, tag_type, attributes,
               xs_col, xs_order, xs_offset, xs_ml, xs_mr,
               sm_col, sm_order, sm_offset, sm_ml, sm_mr,
               md_col, md_order, md_offset, md_ml, md_mr,
               lg_col, lg_order, lg_offset, lg_ml, lg_mr,
               xl_col, xl_order, xl_offset, xl_ml, xl_mr
        FROM bootstrap4_grid_bootstrap4gridcolumn
    """)
    print(f"  Found {len(rows)} rows")
    sizes = ["xs", "sm", "md", "lg", "xl"]
    n = 0
    for row in rows:
        pid = row[0]
        tag_type = row[3]
        attributes_json = row[4]
        try:
            attributes = json.loads(attributes_json) if attributes_json else {}
        except (json.JSONDecodeError, TypeError):
            attributes = {}

        config = {
            "column_alignment": row[2] or "",
            "text_alignment": "",
            "tag_type": tag_type or "div",
            "attributes": attributes,
            "margin_x": None, "margin_y": None,
            "padding_x": None, "padding_y": None,
            "responsive_visibility": None,
            "background_context": "", "background_shadow": "",
        }
        for i, size in enumerate(sizes):
            base = 5 + i * 5
            col, order, offset, ml, mr = row[base:base+5]
            if col    is not None: config[f"{size}_col"]    = col
            if order  is not None: config[f"{size}_order"]  = order
            if offset is not None: config[f"{size}_offset"] = offset
            if ml     is not None: config[f"{size}_ms"]     = ml   # ml→ms (BS5)
            if mr     is not None: config[f"{size}_me"]     = mr   # mr→me (BS5)

        execute("""
            INSERT OR IGNORE INTO djangocms_frontend_frontenduiitem
                (cmsplugin_ptr_id, ui_item, tag_type, config)
            VALUES (?, ?, ?, ?)
        """, [pid, "GridColumn", tag_type or "div", json.dumps(config)])
        execute("UPDATE cms_cmsplugin SET plugin_type='GridColumnPlugin' WHERE id=?", [pid])
        n += 1
    print(f"  ✔  Migrated {n}")
    return n


# ── Picture ───────────────────────────────────────────────────────────────────

def migrate_pictures():
    print("\n── Bootstrap4Picture → ImagePlugin ──────────────────────────────")
    rows = sql("""
        SELECT cmsplugin_ptr_id, template, external_picture, width, height,
               alignment, caption_text, link_url, link_target, link_attributes,
               use_automatic_scaling, use_no_cropping, use_crop, use_upscale,
               picture_fluid, picture_rounded, picture_thumbnail,
               link_page_id, picture_id, thumbnail_options_id,
               use_responsive_image, attributes
        FROM bootstrap4_picture_bootstrap4picture
    """)
    print(f"  Found {len(rows)} rows")
    align_map = {
        "text-left": "start", "text-right": "end", "text-center": "center",
        "left": "start", "right": "end", "center": "center",
    }
    n = 0
    for row in rows:
        (pid, template, ext_pic, width, height, alignment, caption,
         link_url, link_target, link_attrs_json, auto_scale, no_crop,
         use_crop, upscale, fluid, rounded, thumbnail, link_page_id,
         picture_id, thumb_options_id, responsive, attributes_json) = row

        try:
            attributes = json.loads(attributes_json) if attributes_json else {}
        except (json.JSONDecodeError, TypeError):
            attributes = {}
        try:
            link_attrs = json.loads(link_attrs_json) if link_attrs_json else {}
        except (json.JSONDecodeError, TypeError):
            link_attrs = {}

        config = {
            "template": template or "default",
            "external_picture": ext_pic or "",
            "width": width, "height": height,
            "alignment": align_map.get(alignment or "", alignment or ""),
            "caption_text": caption or "",
            "external_link": link_url or "",
            "link_target": link_target or "",
            "link_attributes": link_attrs,
            "use_automatic_scaling": bool(auto_scale),
            "use_no_cropping": bool(no_crop),
            "use_crop": bool(use_crop),
            "use_upscale": bool(upscale),
            "picture_fluid": bool(fluid),
            "picture_rounded": bool(rounded),
            "picture_thumbnail": bool(thumbnail),
            "use_responsive_image": responsive or "inherit",
            "attributes": attributes,
            "margin_x": None, "margin_y": None,
            "responsive_visibility": None,
        }
        if picture_id:
            config["picture"] = {"model": "filer.image", "pk": picture_id}
        if link_page_id:
            config["internal_link"] = {"model": "cms.page", "pk": int(link_page_id)}
        if thumb_options_id:
            config["thumbnail_options"] = {
                "model": "easy_thumbnails.thumbnailoptions", "pk": thumb_options_id}

        execute("""
            INSERT OR IGNORE INTO djangocms_frontend_frontenduiitem
                (cmsplugin_ptr_id, ui_item, tag_type, config)
            VALUES (?, ?, ?, ?)
        """, [pid, "Image", "div", json.dumps(config)])
        execute("UPDATE cms_cmsplugin SET plugin_type='ImagePlugin' WHERE id=?", [pid])
        n += 1
    print(f"  ✔  Migrated {n}")
    return n


# ── Link ──────────────────────────────────────────────────────────────────────

def migrate_links():
    print("\n── Bootstrap4Link → LinkPlugin ──────────────────────────────────")
    rows = sql("""
        SELECT cmsplugin_ptr_id, template, name, external_link, anchor,
               mailto, phone, link_type, target, link_context, link_size,
               link_outline, link_block, internal_link_id, icon_left,
               icon_right, file_link_id, attributes
        FROM bootstrap4_link_bootstrap4link
    """)
    print(f"  Found {len(rows)} rows")
    n = 0
    for row in rows:
        (pid, template, name, ext_link, anchor, mailto, phone,
         link_type, target, link_context, link_size, link_outline,
         link_block, internal_link_id, icon_left, icon_right,
         file_link_id, attributes_json) = row

        try:
            attributes = json.loads(attributes_json) if attributes_json else {}
        except (json.JSONDecodeError, TypeError):
            attributes = {}

        config = {
            "template": template or "default",
            "name": name or "",
            "external_link": ext_link or "",
            "anchor": anchor or "",
            "mailto": mailto or "",
            "phone": phone or "",
            "link_type": link_type or "link",
            "link_target": target or "",
            "link_context": link_context or "",
            "link_size": link_size or "",
            "link_outline": bool(link_outline),
            "link_block": bool(link_block),
            "icon_left": icon_left or "",
            "icon_right": icon_right or "",
            "attributes": attributes,
            "margin_x": None, "margin_y": None,
        }
        if internal_link_id:
            config["internal_link"] = {"model": "cms.page", "pk": internal_link_id}
        if file_link_id:
            config["file_link"] = {"model": "filer.file", "pk": file_link_id}

        execute("""
            INSERT OR IGNORE INTO djangocms_frontend_frontenduiitem
                (cmsplugin_ptr_id, ui_item, tag_type, config)
            VALUES (?, ?, ?, ?)
        """, [pid, "Link", "a", json.dumps(config)])
        execute("UPDATE cms_cmsplugin SET plugin_type='LinkPlugin' WHERE id=?", [pid])
        n += 1
    print(f"  ✔  Migrated {n}")
    return n


# ── Blockquote ────────────────────────────────────────────────────────────────

def migrate_blockquotes():
    print("\n── Bootstrap4Blockquote → BlockquotePlugin ──────────────────────")
    tbl = "bootstrap4_content_bootstrap4blockquote"
    if not table_exists(tbl):
        print("  ⚠  Table not found — skipping")
        return 0
    rows = sql(f"""
        SELECT cmsplugin_ptr_id, quote_content, quote_origin,
               quote_alignment, attributes
        FROM {tbl}
    """)
    print(f"  Found {len(rows)} rows")
    n = 0
    for (pid, content, origin, alignment, attributes_json) in rows:
        try:
            attributes = json.loads(attributes_json) if attributes_json else {}
        except (json.JSONDecodeError, TypeError):
            attributes = {}

        config = {
            "quote_content": content or "",
            "quote_origin": origin or "",
            "quote_alignment": alignment or "",
            "attributes": attributes,
        }
        execute("""
            INSERT OR IGNORE INTO djangocms_frontend_frontenduiitem
                (cmsplugin_ptr_id, ui_item, tag_type, config)
            VALUES (?, ?, ?, ?)
        """, [pid, "Blockquote", "blockquote", json.dumps(config)])
        execute("UPDATE cms_cmsplugin SET plugin_type='BlockquotePlugin' WHERE id=?", [pid])
        n += 1
    print(f"  ✔  Migrated {n}")
    return n


# ── Run ───────────────────────────────────────────────────────────────────────
print("\n══════════════════════════════════════════════════════════════════")
print("  Bootstrap4 → djangocms-frontend 2.x  direct migration")
print("══════════════════════════════════════════════════════════════════")

total  = migrate_grid_rows()
total += migrate_grid_columns()
total += migrate_pictures()
total += migrate_links()
total += migrate_blockquotes()

print(f"\n  Total migrated: {total} plugins")

# ── Verify ────────────────────────────────────────────────────────────────────
print(f"\n  djangocms_frontend_frontenduiitem now has "
      f"{row_count('djangocms_frontend_frontenduiitem')} rows")

remaining = sql("""
    SELECT plugin_type, COUNT(*) n FROM cms_cmsplugin
    WHERE plugin_type LIKE 'Bootstrap4%'
    GROUP BY plugin_type ORDER BY n DESC
""")
if remaining:
    print("\n  ⚠  Remaining Bootstrap4 entries in cms_cmsplugin:")
    for ptype, n in remaining:
        print(f"       {n:4}×  {ptype}")
else:
    print("\n  ✔  No Bootstrap4 plugin_type entries remaining")

print("\nNext: python manage.py cms fix-tree")
