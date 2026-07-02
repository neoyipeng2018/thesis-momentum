"""Feeds -> artifact + provenance (plan §5.2).

- RSS via feedparser (WordPress and Substack are the same path)
- excerpt-only guard: when fetch_full is set or the feed body is suspiciously
  short, fetch the post page and extract the article (trafilatura)
- Bluesky via the PUBLIC AppView — unauthenticated, nothing to manage
- X via manual paste (kind: manual)
- stamps the public timestamp (the anti-leakage anchor) and a content hash
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib

import feedparser
import yaml
from markdownify import markdownify

ROOT = pathlib.Path(__file__).resolve().parent.parent  # narrative-ledger/
RUNS = ROOT / "runs"
EXCERPT_THRESHOLD = 1500  # chars; below this a feed body is probably a teaser


def load_watchlist() -> dict:
    return yaml.safe_load((ROOT / "config" / "watchlist.yaml").read_text())


def fetch_post_html(url: str) -> str | None:
    """Full-page fetch for excerpt-only feeds. Returns markdown or None."""
    import trafilatura

    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return None
    return trafilatura.extract(downloaded, output_format="markdown", include_links=True)


def pull_rss(feed_url: str, since: dt.datetime, fetch_full: bool = False) -> list[dict]:
    feed = feedparser.parse(feed_url)
    items = []
    for e in feed.entries:
        tp = e.get("published_parsed") or e.get("updated_parsed")
        if not tp:
            continue
        published = dt.datetime(*tp[:6], tzinfo=dt.timezone.utc)
        if published < since:
            continue
        body = e.get("content", [{"value": e.get("summary", "")}])[0]["value"]
        item = {
            "title": e.get("title", "(untitled)"),
            "url": e.link,
            "published_at": published.isoformat(),
        }
        if fetch_full or len(body) < EXCERPT_THRESHOLD:
            md = fetch_post_html(e.link)
            if md:
                item["md"] = md
            else:
                item["html"] = body  # fall back to whatever the feed gave us
        else:
            item["html"] = body
        items.append(item)
    return items


def pull_bluesky(handle: str, since: dt.datetime) -> list[dict]:
    from atproto import Client

    c = Client(base_url="https://public.api.bsky.app")  # unauthenticated read
    feed = c.app.bsky.feed.get_author_feed(
        {"actor": handle, "filter": "posts_no_replies", "limit": 30}
    ).feed
    out = []
    for p in feed:
        created = dt.datetime.fromisoformat(p.post.record.created_at.replace("Z", "+00:00"))
        if created < since:
            continue
        rkey = p.post.uri.split("/")[-1]
        out.append(
            {
                "title": "(bluesky post)",
                "url": f"https://bsky.app/profile/{handle}/post/{rkey}",
                "published_at": created.isoformat(),
                "md": p.post.record.text,
            }
        )
    return out


def save_artifact(run_dir: pathlib.Path, item: dict, source: dict) -> None:
    md = item.get("md") or markdownify(item.get("html", ""), heading_style="ATX")
    digest = hashlib.sha256(md.encode()).hexdigest()[:12]
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "artifact.md").write_text(
        f"<!-- {item['url']} | {item['published_at']} | sha:{digest} -->\n\n"
        f"# {item['title']}\n\n{md}"
    )
    (run_dir / "sources.json").write_text(
        json.dumps(
            {
                "source_id": source["id"],
                "source_name": source.get("name", source["id"]),
                "venue": source.get("venue")
                or f"https://bsky.app/profile/{source.get('handle', '')}",
                "artifact_url": item["url"],
                "title": item["title"],
                "published_at": item["published_at"],
                "content_sha": digest,
                "evidence": [],
            },
            indent=2,
        )
    )


def run(source_id: str) -> pathlib.Path:
    wl = load_watchlist()
    defaults = wl["defaults"]
    try:
        src = next(s for s in wl["sources"] if s["id"] == source_id)
    except StopIteration:
        raise SystemExit(f"unknown source '{source_id}' — add it to config/watchlist.yaml")
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=defaults.get("recency_days", 30))

    if src["kind"] == "rss":
        items = pull_rss(src["feed"], since, src.get("fetch_full", False))
    elif src["kind"] == "bluesky":
        items = pull_bluesky(src["handle"], since)
    elif src["kind"] == "manual":
        raise SystemExit(
            "manual source: create runs/<date>_<id>/ yourself, paste the text into "
            "artifact.md with the '<!-- url | published_at | sha -->' header, and "
            "write sources.json (see any existing run for the shape)"
        )
    else:
        raise SystemExit(f"unknown kind '{src['kind']}'")

    if not items:
        raise SystemExit(f"no items from {source_id} in the last {defaults.get('recency_days', 30)} days")
    item = max(items, key=lambda i: i["published_at"])  # latest post, chosen by recency
    run_dir = RUNS / f"{dt.date.today().isoformat()}_{source_id}"
    save_artifact(run_dir, item, src)
    size = len((run_dir / "artifact.md").read_text())
    print(f"ingested -> {run_dir.relative_to(ROOT)}/artifact.md "
          f"({size:,} chars, published {item['published_at']})")
    return run_dir
