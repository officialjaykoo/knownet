import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def page_id_from_slug(slug: str) -> str:
    return f"page_{slug.replace('-', '_')}"


def strip_frontmatter(markdown: str) -> str:
    if markdown.startswith("---\n"):
        end = markdown.find("\n---\n", 4)
        return markdown[end + 5 :] if end != -1 else markdown
    if markdown.startswith("---\r\n"):
        end = markdown.find("\r\n---\r\n", 5)
        return markdown[end + 7 :] if end != -1 else markdown
    return markdown


def parse_frontmatter(markdown: str) -> dict[str, str]:
    if markdown.startswith("---\r\n"):
        marker = "\r\n---\r\n"
        start = 5
    elif markdown.startswith("---\n"):
        marker = "\n---\n"
        start = 4
    else:
        return {}
    end = markdown.find(marker, start)
    if end == -1:
        return {}
    result: dict[str, str] = {}
    for line in markdown[start:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip("\"'")
    return result


def normalize_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value.lower()).strip("-")
    return slug or "untitled"


def _plain_text(markdown: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", markdown)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_>#-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _sections(body: str) -> list[dict]:
    sections: list[dict] = []
    current: dict | None = None
    buffer: list[str] = []
    position = 0
    for line in body.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            if current:
                section_body = _plain_text("\n".join(buffer))[:1200]
                current["text"] = section_body
                current["body"] = section_body
                sections.append(current)
            position += 1
            heading = match.group(2).strip()
            current = {
                "heading": heading,
                "level": len(match.group(1)),
                "section_key": normalize_slug(heading),
                "position": position,
            }
            buffer = []
        elif current:
            buffer.append(line)
    if current:
        section_body = _plain_text("\n".join(buffer))[:1200]
        current["text"] = section_body
        current["body"] = section_body
        sections.append(current)
    return sections


def _links(body: str) -> list[dict]:
    links: list[dict] = []
    for match in re.finditer(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", body):
        target = match.group(1).strip()
        display = match.group(2).strip() if match.group(2) else target
        links.append({"target": normalize_slug(target), "display": display})
    return links


def build_ai_state_for_page(path: Path, *, vault_id: str = "local-default") -> dict:
    markdown = path.read_text(encoding="utf-8")
    frontmatter = parse_frontmatter(markdown)
    body = strip_frontmatter(markdown)
    slug = normalize_slug(frontmatter.get("slug") or path.stem)
    title = frontmatter.get("title") or slug.replace("-", " ").title()
    content_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    sections = _sections(body)
    summary = next((section["text"] for section in sections if section["text"]), _plain_text(body)[:1200])
    return {
        "id": f"ai_state_{slug.replace('-', '_')}",
        "vault_id": vault_id,
        "page_id": page_id_from_slug(slug),
        "slug": slug,
        "title": title,
        "source_path": str(path).replace("\\", "/"),
        "content_hash": content_hash,
        "state_json": {
            "schema_version": 1,
            "kind": "page_state",
            "page_id": page_id_from_slug(slug),
            "slug": slug,
            "title": title,
            "summary": summary,
            "sections": sections,
            "links": _links(body),
            "source": {
                "format": "markdown",
                "path": str(path).replace("\\", "/"),
                "content_hash": content_hash,
            },
        },
        "updated_at": utc_now(),
    }


def encode_state_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


async def ensure_ai_state_schema(sqlite_path: Path) -> None:
    import aiosqlite

    async with aiosqlite.connect(sqlite_path) as connection:
        await connection.executescript(
            """
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
        )
        await connection.commit()
