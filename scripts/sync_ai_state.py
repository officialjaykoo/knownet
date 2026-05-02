from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))

from knownet_api.services.ai_state import build_ai_state_for_page, encode_state_json  # noqa: E402


SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_state_pages (
  id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  page_id TEXT NOT NULL,
  slug TEXT NOT NULL,
  title TEXT NOT NULL,
  source_path TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  state_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(vault_id, page_id)
);
CREATE INDEX IF NOT EXISTS idx_ai_state_pages_vault_updated
  ON ai_state_pages(vault_id, updated_at);
"""


def sync_ai_state(*, db_path: Path, pages_dir: Path, vault_id: str) -> dict:
    if not db_path.exists():
        raise SystemExit(f"database not found: {db_path}")
    if not pages_dir.exists():
        raise SystemExit(f"pages dir not found: {pages_dir}")

    records = [build_ai_state_for_page(path, vault_id=vault_id) for path in sorted(pages_dir.glob("*.md"))]
    with sqlite3.connect(db_path) as connection:
        connection.executescript(SCHEMA)
        for record in records:
            connection.execute(
                "INSERT INTO ai_state_pages (id, vault_id, page_id, slug, title, source_path, content_hash, state_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(vault_id, page_id) DO UPDATE SET "
                "slug = excluded.slug, title = excluded.title, source_path = excluded.source_path, "
                "content_hash = excluded.content_hash, state_json = excluded.state_json, updated_at = excluded.updated_at",
                (
                    record["id"],
                    record["vault_id"],
                    record["page_id"],
                    record["slug"],
                    record["title"],
                    record["source_path"],
                    record["content_hash"],
                    encode_state_json(record["state_json"]),
                    record["updated_at"],
                ),
            )
    return {"synced": len(records), "db_path": str(db_path), "pages_dir": str(pages_dir)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync KnowNet pages into structured AI state JSON rows.")
    parser.add_argument("--db", default=str(ROOT / "data/knownet.db"))
    parser.add_argument("--pages-dir", default=str(ROOT / "data/pages"))
    parser.add_argument("--vault-id", default="local-default")
    args = parser.parse_args()
    result = sync_ai_state(db_path=Path(args.db), pages_dir=Path(args.pages_dir), vault_id=args.vault_id)
    print(result)


if __name__ == "__main__":
    main()
