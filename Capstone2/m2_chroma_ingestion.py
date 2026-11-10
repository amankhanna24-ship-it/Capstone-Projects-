"""
m2_chroma_ingestion.py — ingestion and indexing pipeline.

    python m2_chroma_ingestion.py              # incremental: only new/changed documents
    python m2_chroma_ingestion.py --rebuild    # wipe the collection and re-index everything
    python m2_chroma_ingestion.py --dry-run    # chunk only, no embeddings (free) -> data/processed/chunks.jsonl
    python m2_chroma_ingestion.py --prune      # also delete chunks whose source left the manifest

Pipeline
    manifest.json ─► load (PDF / DOCX / Markdown / HTML / URL / CSV)
                  ─► chunk with a strategy chosen per document type
                  ─► add contextual header + metadata (department, doc_type, dates, version…)
                  ─► embed (OpenAI) ─► upsert into ChromaDB with deterministic IDs

Chunking strategy per document type (see CHUNKING below):
    policy   (PDF)   section-aware: split on numbered headings, then recursive 900/150 chars
    contract (DOCX)  clause-level: one clause per chunk, long clauses split 1500/200
    runbook  (MD)    header-aware: split on #/##/###, then recursive 1200/150
    faq/web  (HTML)  heading sections h1–h3, then recursive 800/100
    ticket   (CSV)   one row = one chunk, never split
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langsmith import traceable

from kb_common import (
    COLLECTION,
    DATA_DIR,
    PROCESSED_DIR,
    date_to_int,
    embed_documents,
    get_chroma,
    get_collection,
    sha1,
)

FAR_FUTURE = 99991231


# --------------------------------------------------------------------------
# 1. Loaders  -> list[Section]
# --------------------------------------------------------------------------
@dataclass
class Section:
    text: str
    section: str = ""
    page: int = -1


HEADING_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+[A-Z][^\n]{2,80}$")


def load_pdf(path: Path) -> list[Section]:
    """Page-aware PDF loader that also detects numbered headings ('3. Hotels')."""
    from pypdf import PdfReader

    sections: list[Section] = []
    current = Section(text="", section="Preamble", page=1)
    for page_no, page in enumerate(PdfReader(str(path)).pages, start=1):
        for line in (page.extract_text() or "").splitlines():
            if HEADING_RE.match(line) and len(line) < 90:
                if current.text.strip():
                    sections.append(current)
                current = Section(text="", section=line.strip(), page=page_no)
            else:
                current.text += line + "\n"
    if current.text.strip():
        sections.append(current)
    return sections


def load_docx(path: Path) -> list[Section]:
    """Every Heading / Title paragraph starts a new section (= a contract clause)."""
    from docx import Document

    sections: list[Section] = []
    current = Section(text="", section="Preamble")
    for para in Document(str(path)).paragraphs:
        style = (para.style.name or "").lower() if para.style is not None else ""
        if style.startswith("heading") or style == "title":
            if current.text.strip():
                sections.append(current)
            current = Section(text="", section=para.text.strip())
        elif para.text.strip():
            current.text += para.text.strip() + "\n\n"
    if current.text.strip():
        sections.append(current)
    # tables (common in contracts / schedules) — keep them, one section per table
    for t_idx, table in enumerate(Document(str(path)).tables, start=1):
        rows = [" | ".join(c.text.strip() for c in row.cells) for row in table.rows]
        sections.append(Section(text="\n".join(rows), section=f"Table {t_idx}"))
    return sections


def load_markdown(path: Path) -> list[Section]:
    splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")], strip_headers=True
    )
    out = []
    for d in splitter.split_text(path.read_text(encoding="utf-8")):
        path_parts = [d.metadata.get(k) for k in ("h1", "h2", "h3") if d.metadata.get(k)]
        out.append(Section(text=d.page_content, section=" > ".join(path_parts[1:] or path_parts)))
    return out


def load_html(html: str) -> list[Section]:
    """Strip navigation/boilerplate, then group content under the nearest h1–h3."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup

    sections: list[Section] = []
    heads: dict[int, str] = {}
    current = Section(text="", section="Introduction")
    for el in root.find_all(["h1", "h2", "h3", "p", "li", "pre", "td", "dd", "dt"]):
        if el.name in ("h1", "h2", "h3"):
            if current.text.strip():
                sections.append(current)
            level = int(el.name[1])
            heads = {k: v for k, v in heads.items() if k < level}
            heads[level] = el.get_text(" ", strip=True)
            path = [heads[k] for k in sorted(heads) if k > 1] or [heads.get(1, "")]
            current = Section(text="", section=" > ".join(path))
        else:
            txt = el.get_text(" ", strip=True)
            if txt:
                current.text += txt + "\n"
    if current.text.strip():
        sections.append(current)
    return sections


def load_url(url: str) -> list[Section]:
    import requests

    resp = requests.get(url, timeout=30, headers={"User-Agent": "kb-chatbot-ingestion/1.0"})
    resp.raise_for_status()
    return load_html(resp.text)


# --------------------------------------------------------------------------
# 2. Chunking strategies per document type
# --------------------------------------------------------------------------
CHUNKING = {
    #  doc_type   (chunk_size, overlap)  — characters, not tokens (~4 chars ≈ 1 token)
    "policy": (900, 150),
    "contract": (1500, 200),
    "runbook": (1200, 150),
    "faq": (800, 100),
    "web": (800, 100),
    "default": (1000, 150),
}


def split_sections(sections: list[Section], doc_type: str) -> list[Section]:
    size, overlap = CHUNKING.get(doc_type, CHUNKING["default"])
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size, chunk_overlap=overlap, separators=["\n\n", "\n", ". ", " ", ""]
    )
    out: list[Section] = []
    for s in sections:
        body = s.text.strip()
        if not body:
            continue
        if len(body) <= size:
            out.append(Section(body, s.section, s.page))
        else:
            out.extend(Section(piece, s.section, s.page) for piece in splitter.split_text(body))
    return out


def contextualise(title: str, doc_id: str, section: str, body: str) -> str:
    """Prepend a short header so every chunk carries its own context.

    Helps both sides: BM25 can match the doc ID / title, and the embedding knows
    *which* policy a sentence like 'the cap is GBP 180' belongs to.
    """
    head = f"{title} ({doc_id})"
    if section:
        head += f" — {section}"
    return f"{head}\n{body.strip()}"


# --------------------------------------------------------------------------
# 3. Build chunks for one manifest entry
# --------------------------------------------------------------------------
def base_metadata(entry: dict, versions: dict) -> dict:
    eff = date_to_int(entry.get("effective_date")) or 0
    fam = entry.get("doc_family", entry.get("doc_id"))
    expiry, is_latest = versions.get((fam, entry.get("doc_id")), (FAR_FUTURE, True))
    return {
        "doc_id": entry["doc_id"],
        "doc_family": fam,
        "title": entry["title"],
        "department": entry["department"],
        "doc_type": entry["doc_type"],
        "visibility": entry.get("visibility", "company"),
        "version": str(entry.get("version", "")),
        "effective_date": eff,
        "effective_date_iso": entry.get("effective_date", ""),
        "expiry_date": expiry,
        "is_latest": is_latest,
        "source": entry.get("url") or entry.get("path"),
    }


def chunks_for_document(entry: dict, versions: dict) -> list[dict]:
    """Returns [{id, text, metadata}] for one document (or one CSV row-set)."""
    doc_type = entry["doc_type"]

    if entry.get("loader") == "csv_rows":
        return chunks_for_csv(entry)

    if entry.get("url"):
        sections, file_type = load_url(entry["url"]), "url"
    else:
        path = DATA_DIR / entry["path"]
        suffix = path.suffix.lower()
        file_type = suffix.lstrip(".")
        if suffix == ".pdf":
            sections = load_pdf(path)
        elif suffix == ".docx":
            sections = load_docx(path)
        elif suffix in (".md", ".markdown"):
            sections = load_markdown(path)
        elif suffix in (".html", ".htm"):
            sections = load_html(path.read_text(encoding="utf-8"))
        elif suffix == ".txt":
            sections = [Section(path.read_text(encoding="utf-8"))]
        else:
            raise ValueError(f"No loader for {suffix} ({path})")

    pieces = split_sections(sections, doc_type)
    meta = base_metadata(entry, versions)
    meta["file_type"] = file_type
    out = []
    for i, p in enumerate(pieces):
        text = contextualise(meta["title"], meta["doc_id"], p.section, p.text)
        out.append(
            {
                "id": f"{meta['doc_id']}::{i:04d}::{sha1(text)[:8]}",
                "text": text,
                "metadata": {**meta, "section": p.section[:200], "page": p.page, "chunk_index": i},
            }
        )
    return out


def chunks_for_csv(entry: dict) -> list[dict]:
    """Tickets: one row = one self-contained chunk with its own doc_id and date."""
    path = DATA_DIR / entry["path"]
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tid = row[entry["id_field"]]
            title = entry.get("title_template", "{%s}" % entry["id_field"]).format(**row)
            body = "\n".join(f"{k}: {v}" for k, v in row.items() if v)
            text = f"{title}\n{body}"
            iso = row.get(entry.get("date_field", ""), "")
            meta = {
                "doc_id": tid,
                "doc_family": tid,
                "title": title,
                "department": entry["department"],
                "doc_type": entry["doc_type"],
                "visibility": entry.get("visibility", "department"),
                "version": str(entry.get("version", "1")),
                "effective_date": date_to_int(iso) or 0,
                "effective_date_iso": iso,
                "expiry_date": FAR_FUTURE,
                "is_latest": True,
                "source": entry["path"],
                "file_type": "csv",
                "section": "",
                "page": -1,
                "chunk_index": 0,
            }
            out.append({"id": f"{tid}::0000::{sha1(text)[:8]}", "text": text, "metadata": meta})
    return out


def compute_versions(entries: list[dict]) -> dict:
    """For each doc_family, work out which version is current and when older ones expired.

    expiry_date of v1 = effective_date of v2, so an `as_of` filter can find the
    version that was in force on any given day.
    """
    today = date_to_int(date.today())
    fams: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        if e.get("loader") != "csv_rows":
            fams[e.get("doc_family", e["doc_id"])].append(e)
    out = {}
    for fam, items in fams.items():
        items = sorted(items, key=lambda e: date_to_int(e.get("effective_date")) or 0)
        in_force = [e for e in items if (date_to_int(e.get("effective_date")) or 0) <= today]
        latest_id = (in_force or items)[-1]["doc_id"]
        for i, e in enumerate(items):
            nxt = date_to_int(items[i + 1].get("effective_date")) if i + 1 < len(items) else FAR_FUTURE
            out[(fam, e["doc_id"])] = (nxt, e["doc_id"] == latest_id)
    return out


# --------------------------------------------------------------------------
# 4. Index into Chroma (incremental, idempotent)
# --------------------------------------------------------------------------
@traceable(run_type="chain", name="index_document")
def index_chunks(col, doc_id: str, chunks: list[dict], doc_hash: str, force: bool) -> str:
    existing = col.get(where={"doc_id": doc_id}, include=["metadatas"], limit=1)
    if existing["ids"] and not force and existing["metadatas"][0].get("doc_hash") == doc_hash:
        return "unchanged"
    if existing["ids"]:
        col.delete(where={"doc_id": doc_id})  # remove stale chunks of the old version
    vectors = embed_documents([c["text"] for c in chunks])
    col.upsert(
        ids=[c["id"] for c in chunks],
        documents=[c["text"] for c in chunks],
        embeddings=vectors,
        metadatas=[{**c["metadata"], "doc_hash": doc_hash} for c in chunks],
    )
    return "updated" if existing["ids"] else "added"


@traceable(run_type="chain", name="ingest_corpus")
def ingest(rebuild: bool = False, dry_run: bool = False, prune: bool = False, only: str | None = None) -> None:
    manifest = json.loads((DATA_DIR / "manifest.json").read_text(encoding="utf-8"))
    entries = [e for e in manifest["documents"] if e.get("enabled", True)]
    versions = compute_versions(entries)

    if rebuild and not dry_run:
        try:
            get_chroma().delete_collection(COLLECTION)
            print(f"[ingest] dropped collection '{COLLECTION}'")
        except Exception:
            pass
    col = None if dry_run else get_collection()

    all_chunks: list[dict] = []
    report = []
    for entry in entries:
        label = entry.get("doc_id") or entry.get("path")
        if only and only not in (entry.get("doc_id"), entry.get("path")):
            continue
        try:
            chunks = chunks_for_document(entry, versions)
        except Exception as exc:  # one bad file must not stop the whole run
            print(f"[ingest] ✗ {label}: {exc}")
            continue
        all_chunks.extend(chunks)

        # group by doc_id (a CSV entry yields many documents)
        by_doc: dict[str, list[dict]] = defaultdict(list)
        for c in chunks:
            by_doc[c["metadata"]["doc_id"]].append(c)
        for doc_id, doc_chunks in by_doc.items():
            doc_hash = sha1(json.dumps([c["text"] for c in doc_chunks]) + json.dumps(doc_chunks[0]["metadata"], sort_keys=True))
            status = "dry-run" if dry_run else index_chunks(col, doc_id, doc_chunks, doc_hash, force=rebuild)
            sizes = [len(c["text"]) for c in doc_chunks]
            report.append((doc_id, entry["doc_type"], len(doc_chunks), sum(sizes) // len(sizes), status))

    if prune and col is not None and not only:
        keep = {c["metadata"]["doc_id"] for c in all_chunks}
        stale = {m["doc_id"] for m in col.get(include=["metadatas"])["metadatas"]} - keep
        for d in stale:
            col.delete(where={"doc_id": d})
        print(f"[ingest] pruned {len(stale)} documents no longer in the manifest: {sorted(stale)}")

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROCESSED_DIR / "chunks.jsonl", "w", encoding="utf-8") as f:
        for c in all_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"\n{'doc_id':<16} {'type':<9} {'chunks':>6} {'avg chars':>9}  status")
    print("-" * 56)
    for row in report:
        print(f"{row[0]:<16} {row[1]:<9} {row[2]:>6} {row[3]:>9}  {row[4]}")
    print("-" * 56)
    types = Counter(c["metadata"]["doc_type"] for c in all_chunks)
    print(f"{len(all_chunks)} chunks  ·  by type: {dict(types)}")
    if col is not None:
        print(f"collection '{COLLECTION}' now holds {col.count()} chunks")
    print(f"chunk dump for inspection: {PROCESSED_DIR / 'chunks.jsonl'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rebuild", action="store_true", help="drop and recreate the collection")
    ap.add_argument("--dry-run", action="store_true", help="chunk only; no embeddings, no writes to Chroma")
    ap.add_argument("--prune", action="store_true", help="delete documents that were removed from the manifest")
    ap.add_argument("--only", help="ingest a single doc_id or path")
    a = ap.parse_args()
    ingest(rebuild=a.rebuild, dry_run=a.dry_run, prune=a.prune, only=a.only)
