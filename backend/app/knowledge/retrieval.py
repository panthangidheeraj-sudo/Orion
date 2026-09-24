"""Local RAG retrieval (§12).

Returns document ID, page numbers, chunk text, similarity score and metadata,
as the specification requires — and the VLM receives the top evidence, never
the whole document.

Retrieval is hybrid.  Dense similarity finds passages that mean the same
thing; BM25 over FTS5 finds the ones that contain the literal token, which
matters enormously here because a technician's query is often exactly the
string printed on the machine — ``E17``, ``NSK6203``, ``24VDC``.  The two
rankings are fused with reciprocal rank fusion, and an exact-token hit gets a
small bonus so a manual page that literally names the code cannot be buried.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from app.config import settings
from app.logging_setup import get_logger
from app.memory import sqlite as db
from app.memory import vector_store as vs
from app.models.registry import registry
from app.util import timed

log = get_logger(__name__)

RRF_K = 60
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
# Words too common to tell one page from another.
_CITE_STOP = frozenset(
    "the and for with that this from what which when where should does did are was "
    "you your our its into onto have has had will would can could must about".split())


def _fts_query(text: str) -> str:
    """Build a safe FTS5 MATCH expression — user text is never interpolated raw."""
    terms = [t for t in _TOKEN.findall(text or "") if len(t) > 1][:16]
    if not terms:
        return ""
    return " OR ".join('"%s"' % t.replace('"', "") for t in terms)


def _lexical(query: str, limit: int, document_ids: Optional[Sequence[str]]) -> List[Dict[str, Any]]:
    expr = _fts_query(query)
    if not expr:
        return []
    sql = ("SELECT chunk_id, document_id, bm25(chunk_fts) AS rank FROM chunk_fts "
           "WHERE chunk_fts MATCH ? ")
    params: List[Any] = [expr]
    if document_ids:
        sql += " AND document_id IN (%s) " % ",".join("?" for _ in document_ids)
        params.extend(document_ids)
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    try:
        return db.query(sql, params)
    except Exception as exc:  # a malformed MATCH must not break the answer
        log.warning("fts query failed: %s", type(exc).__name__)
        return []


async def _dense(query: str, limit: int, allowed: Optional[List[str]]) -> List[Dict[str, Any]]:
    embedder = registry.embedding()
    if not embedder.is_ready():
        return []
    vec = (await embedder.embed([query]))[0]
    return vs.search(vs.DOCUMENT_CHUNK, vec, top_k=limit, allowed_ids=allowed)


def _allowed_chunks(document_ids: Optional[Sequence[str]]) -> Optional[List[str]]:
    if not document_ids:
        return None
    marks = ",".join("?" for _ in document_ids)
    rows = db.query(f"SELECT id FROM document_chunks WHERE document_id IN ({marks})",
                    list(document_ids))
    return [r["id"] for r in rows]


def _term_coverage(upper_content: str, terms: List[str]) -> float:
    """Fraction of the query's meaningful terms present as whole words."""
    if not terms:
        return 0.0
    hits = sum(1 for t in terms
               if re.search(r"\b" + re.escape(t) + r"\b", upper_content))
    return hits / len(terms)


def _diversify(results: List[Dict[str, Any]], top_k: int,
               per_document: int = 2) -> List[Dict[str, Any]]:
    """Stop one document monopolising the answer.

    A technician with a manual, a schematic and a parts list wants to see all
    three when they are all relevant. Without this, a long document with many
    chunks fills every slot and a one-page schematic that names the terminal is
    never shown.
    """
    kept: List[Dict[str, Any]] = []
    spill: List[Dict[str, Any]] = []
    seen: Dict[str, int] = {}
    for r in results:
        doc = r["document_id"]
        if seen.get(doc, 0) < per_document:
            seen[doc] = seen.get(doc, 0) + 1
            kept.append(r)
        else:
            spill.append(r)
        if len(kept) >= top_k:
            break
    # If diversity left room, fill it from what was held back.
    for r in spill:
        if len(kept) >= top_k:
            break
        kept.append(r)
    return kept[:top_k]


def _best_page(content: str, row: Dict[str, Any], query_tokens: set) -> int:
    """Cite the page the matching words are printed on, not the chunk's first page.

    A chunk may span a page break. ``page_spans`` records where each page's
    text sits inside the chunk, so the citation can name the page that
    actually contains the strongest match.
    """
    import json as _json

    default = row["page_start"]
    try:
        spans = (_json.loads(row.get("metadata_json") or "{}") or {}).get("page_spans") or []
    except Exception:
        return default
    if not spans or not query_tokens:
        return default
    # Whole words only: a substring test scores "ON" against "DIAGONAL" and
    # quietly moves the citation to the wrong page.
    terms = [t for t in query_tokens if len(t) >= 3 and t.lower() not in _CITE_STOP]
    if not terms:
        return default
    pattern = re.compile(r"\b(?:%s)\b" % "|".join(re.escape(t) for t in terms))
    upper = content.upper()
    best_page, best_score = default, 0.0
    for page, start, end in spans:
        segment = upper[start:end]
        if not segment:
            continue
        hits = 0.0
        for m in pattern.finditer(segment):
            tok = m.group(0)
            hits += 2.0 if any(ch.isdigit() for ch in tok) else 1.0
        if not hits:
            continue
        density = hits / max(1.0, len(segment) / 400.0)
        if density > best_score:
            best_page, best_score = page, density
    return best_page if best_score > 0 else default


def _hydrate(chunk_ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    if not chunk_ids:
        return {}
    marks = ",".join("?" for _ in chunk_ids)
    rows = db.query(
        "SELECT c.id, c.document_id, c.page_start, c.page_end, c.content, c.metadata_json, "
        "       d.filename, d.mime_type, d.page_count "
        f"FROM document_chunks c JOIN documents d ON d.id = c.document_id WHERE c.id IN ({marks})",
        list(chunk_ids))
    return {r["id"]: r for r in rows}


async def search_documents(query: str, top_k: int = 0,
                           document_ids: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    top_k = top_k or settings.retrieval_top_k
    pool = max(top_k * 4, 20)
    with timed() as t:
        allowed = _allowed_chunks(document_ids)
        dense = await _dense(query, pool, allowed)
        lexical = _lexical(query, pool, document_ids)

        fused: Dict[str, Dict[str, Any]] = {}
        for rank, hit in enumerate(dense):
            e = fused.setdefault(hit["owner_id"], {"rrf": 0.0, "dense": None, "lexical": None})
            e["rrf"] += 1.0 / (RRF_K + rank + 1)
            e["dense"] = hit["score"]
        for rank, hit in enumerate(lexical):
            e = fused.setdefault(hit["chunk_id"], {"rrf": 0.0, "dense": None, "lexical": None})
            e["rrf"] += 1.0 / (RRF_K + rank + 1)
            e["lexical"] = round(-float(hit["rank"]), 4)

        rows = _hydrate(list(fused.keys()))
        query_tokens = {t.upper() for t in _TOKEN.findall(query or "") if len(t) > 1}
        meaningful = [t for t in query_tokens
                      if len(t) >= 3 and t.lower() not in _CITE_STOP]

        results: List[Dict[str, Any]] = []
        for chunk_id, sc in fused.items():
            row = rows.get(chunk_id)
            if not row:
                continue
            content = row["content"]
            upper = content.upper()
            exact = sorted(tok for tok in query_tokens
                           if len(tok) >= 2 and any(ch.isdigit() for ch in tok) and tok in upper)
            # Reciprocal rank fusion alone produces near-identical scores when
            # both rankings put several chunks close together — two unrelated
            # passages can end up a hundred-thousandth apart, which is a coin
            # flip, not a ranking. Term coverage breaks that honestly: how much
            # of what the technician actually asked appears in this passage.
            coverage = _term_coverage(upper, meaningful)
            score = (sc["rrf"]
                     + (0.012 * min(len(exact), 3))     # exact technical token
                     + (0.010 * coverage))              # query terms present
            cite_page = _best_page(content, row, query_tokens)
            results.append({
                "chunk_id": chunk_id,
                "document_id": row["document_id"],
                "filename": row["filename"],
                "page_start": cite_page,
                "page_end": row["page_end"],
                "chunk_page_start": row["page_start"],
                "content": content,
                "score": round(score, 5),
                "dense_score": sc["dense"],
                "lexical_score": sc["lexical"],
                "exact_matches": exact,
                "term_coverage": round(coverage, 3),
                "metadata": row["metadata_json"],
                "source": "local_documents",
            })
        # A passage that shares no word with the question is not evidence, and
        # presenting it as such is worse than returning nothing: the technician
        # opens page 17 expecting an answer and finds boilerplate. Ranking can
        # always order something; relevance is a separate question.
        before = len(results)
        results = [r for r in results if r["term_coverage"] > 0 or r["exact_matches"]]
        dropped = before - len(results)

        results.sort(key=lambda r: r["score"], reverse=True)
        results = _diversify(results, top_k)

    return {
        "query": query,
        "results": results,
        "count": len(results),
        "irrelevant_dropped": dropped,
        "no_local_answer": not results,
        "duration_ms": t["ms"],
        "strategy": "dense+bm25 rrf" if dense else "bm25 only",
        "embedding_model": registry.embedding().model_id,
        "embedding_synthetic": registry.embedding().health().synthetic,
    }


async def search_memories(query: str, top_k: int = 6,
                          job_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Semantic memory search, with a lexical floor so it works unindexed."""
    embedder = registry.embedding()
    hits: List[Dict[str, Any]] = []
    if embedder.is_ready():
        vec = (await embedder.embed([query]))[0]
        hits = vs.search(vs.MEMORY, vec, top_k=top_k * 3)
    ids = [h["owner_id"] for h in hits]
    scores = {h["owner_id"]: h["score"] for h in hits}

    if ids:
        marks = ",".join("?" for _ in ids)
        rows = db.query(f"SELECT * FROM memories WHERE id IN ({marks})", ids)
    else:
        like = f"%{(query or '').strip()[:60]}%"
        rows = db.query(
            "SELECT * FROM memories WHERE content LIKE ? ORDER BY updated_at DESC LIMIT ?",
            (like, top_k))
    out = []
    for r in rows:
        if job_id and r.get("job_id") and r["job_id"] != job_id:
            continue
        out.append({**r, "score": scores.get(r["id"], 0.0)})
    out.sort(key=lambda r: (r["score"], r["updated_at"]), reverse=True)
    return out[:top_k]
