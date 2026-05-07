from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any


SECTION_ALIASES = {
    "score": {"score", "점수"},
    "verdict": {"verdict", "판정", "충분한가", "현재 충분한가"},
    "top_changes": {"top 3", "top 5", "top changes", "concrete changes", "변경사항", "구체적 변경사항"},
    "do_not_change": {"what should not", "do not change", "바꾸지 말아야", "변경하지 말아야"},
    "standard_patterns": {"standard", "open-source", "standards", "표준", "오픈소스"},
}

REMOVE_RE = re.compile(r"\b(remove|drop|delete|strip|eliminate)\b|제거|삭제|빼라", re.IGNORECASE)
KEEP_RE = re.compile(r"\b(do not remove|do not change|keep|stay|preserve|유지|건드리지)\b", re.IGNORECASE)


def _normalize_key(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", text.lower())
    text = re.sub(r"[^a-z0-9가-힣_.:/-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:120]


def _line_items(text: str) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        cleaned = line.strip().lstrip("-*0123456789. )\t").strip()
        cleaned = re.sub(r"^\*\*(.+?)\*\*", r"\1", cleaned).strip()
        if len(cleaned) >= 8:
            items.append(cleaned[:400])
    return items


def _section_name(line: str) -> str | None:
    cleaned = line.strip().strip("#").strip("*").strip().lower()
    for section, aliases in SECTION_ALIASES.items():
        if any(alias in cleaned for alias in aliases):
            return section
    return None


def parse_review_sections(text: str) -> dict[str, Any]:
    sections: dict[str, list[str]] = defaultdict(list)
    current = "top_changes"
    for line in text.splitlines():
        name = _section_name(line)
        if name:
            current = name
            continue
        sections[current].append(line)
    parsed: dict[str, Any] = {}
    score_match = re.search(r"(?i)(?:score|점수)\s*[:：]?\s*\*{0,2}(\d{1,3})\s*/\s*100", text)
    if score_match:
        parsed["score"] = int(score_match.group(1))
    for section in SECTION_ALIASES:
        parsed[section] = _line_items("\n".join(sections.get(section) or []))
    return parsed


def compare_ai_reviews(reviews: list[dict[str, str]]) -> dict[str, Any]:
    parsed_reviews = []
    recommendation_sources: dict[str, set[str]] = defaultdict(set)
    recommendation_text: dict[str, str] = {}
    do_not_sources: dict[str, set[str]] = defaultdict(set)
    remove_terms: dict[str, set[str]] = defaultdict(set)
    keep_terms: dict[str, set[str]] = defaultdict(set)

    for review in reviews:
        source = review.get("source_agent") or "external_ai"
        parsed = parse_review_sections(review.get("text") or "")
        parsed_reviews.append({"source_agent": source, **parsed})
        for item in parsed.get("top_changes") or []:
            key = _normalize_key(item)
            if not key:
                continue
            recommendation_sources[key].add(source)
            recommendation_text.setdefault(key, item)
            if REMOVE_RE.search(item):
                remove_terms[key].add(source)
        for item in parsed.get("do_not_change") or []:
            key = _normalize_key(item)
            if not key:
                continue
            do_not_sources[key].add(source)
            if KEEP_RE.search(item):
                keep_terms[key].add(source)

    source_count = max(1, len({review.get("source_agent") or "external_ai" for review in reviews}))
    common = [
        {"text": recommendation_text[key], "sources": sorted(sources)}
        for key, sources in recommendation_sources.items()
        if len(sources) >= min(2, source_count)
    ]
    model_specific = [
        {"text": recommendation_text[key], "sources": sorted(sources)}
        for key, sources in recommendation_sources.items()
        if len(sources) == 1
    ]
    conflicts = []
    for remove_key, remove_sources in remove_terms.items():
        for keep_key, keep_sources in keep_terms.items():
            if remove_key and keep_key and (remove_key in keep_key or keep_key in remove_key):
                conflicts.append(
                    {
                        "item": recommendation_text.get(remove_key, remove_key),
                        "remove_sources": sorted(remove_sources),
                        "keep_sources": sorted(keep_sources),
                    }
                )

    do_not_consensus = [
        {"text": key, "sources": sorted(sources)}
        for key, sources in do_not_sources.items()
        if len(sources) >= min(2, source_count)
    ]
    candidate_counter = Counter()
    for key, sources in recommendation_sources.items():
        candidate_counter[key] = len(sources)
    candidates = [
        {"text": recommendation_text[key], "support_count": count, "sources": sorted(recommendation_sources[key])}
        for key, count in candidate_counter.most_common(8)
    ]
    return {
        "reviews": parsed_reviews,
        "common_recommendations": common,
        "model_specific_recommendations": model_specific,
        "conflicts": conflicts,
        "do_not_change_consensus": do_not_consensus,
        "candidate_implementation_list": candidates,
    }
