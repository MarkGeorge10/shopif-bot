"""
RAG Evaluation Helpers

Provides standard IR metrics to measure Pinecone retrieval quality:
- NDCG  (Normalized Discounted Cumulative Gain)
- Hit Rate (does any relevant result appear in top-k?)
- MRR   (Mean Reciprocal Rank)
- Average Pinecone similarity score

These are used both for offline evaluation and for real-time logging
in the search providers.
"""
import math
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ── Offline evaluation metrics ──────────────────────────────────────────────

def compute_ndcg(scores: list[float], ideal_k: int = 10) -> float:
    """
    Compute NDCG from a list of Pinecone similarity scores.
    Scores are already in [0, 1] range from cosine similarity.
    Higher is better. Returns 0.0 if scores is empty.
    """
    if not scores:
        return 0.0

    k = min(len(scores), ideal_k)
    dcg = sum(
        scores[i] / math.log2(i + 2)  # +2: log2(1) = 0, so start at log2(2)
        for i in range(k)
    )
    # Ideal DCG = sorted scores descending (already sorted by Pinecone relevance)
    ideal_scores = sorted(scores, reverse=True)[:k]
    idcg = sum(
        ideal_scores[i] / math.log2(i + 2)
        for i in range(k)
    )
    return dcg / idcg if idcg > 0 else 0.0


def compute_hit_rate(result_ids: list[str], relevant_ids: list[str]) -> float:
    """
    Fraction of relevant items that appear anywhere in the result set.
    Returns 1.0 if at least one relevant item is found, else 0.0.
    """
    if not relevant_ids:
        return 0.0
    hits = sum(1 for rid in relevant_ids if rid in result_ids)
    return hits / len(relevant_ids)


def compute_mrr(result_ids: list[str], relevant_ids: list[str]) -> float:
    """
    Mean Reciprocal Rank: 1/rank of the first relevant result.
    Returns 0.0 if no relevant result is found.
    """
    if not relevant_ids:
        return 0.0
    for rank, rid in enumerate(result_ids, start=1):
        if rid in relevant_ids:
            return 1.0 / rank
    return 0.0


# ── Aggregate metrics from SearchLog rows ───────────────────────────────────

async def compute_store_metrics(store_id: str, days: int = 7) -> dict:
    """
    Query the SearchLog table and compute aggregate stats for a store.
    Returns a dict ready to be serialized to the dashboard.
    """
    from datetime import datetime, timezone, timedelta
    from app.core.database import prisma

    since = datetime.now(timezone.utc) - timedelta(days=days)

    logs = await prisma.searchlog.find_many(
        where={"storeId": store_id, "createdAt": {"gte": since}},
        order={"createdAt": "desc"},
    )

    if not logs:
        return {
            "total_searches": 0,
            "pinecone_searches": 0,
            "native_searches": 0,
            "fallback_rate": 0.0,
            "avg_latency_ms": 0,
            "avg_pinecone_score": None,
            "avg_results_count": 0.0,
            "avg_ndcg": None,
            "thumbs_up": 0,
            "thumbs_down": 0,
            "feedback_ratio": None,
            "days": days,
        }

    total = len(logs)
    pinecone_logs = [l for l in logs if l.provider in ("pinecone", "hybrid")]
    native_logs   = [l for l in logs if l.provider == "shopify_native"]
    fallback_logs = [l for l in logs if l.fallbackUsed]

    all_scores = [s for l in pinecone_logs for s in (l.pineconeScores or [])]
    avg_score = sum(all_scores) / len(all_scores) if all_scores else None

    ndcg_values = [
        compute_ndcg(l.pineconeScores or [])
        for l in pinecone_logs
        if l.pineconeScores
    ]
    avg_ndcg = sum(ndcg_values) / len(ndcg_values) if ndcg_values else None

    latencies = [l.latencyMs for l in logs if l.latencyMs is not None]
    avg_latency = int(sum(latencies) / len(latencies)) if latencies else 0

    avg_results = sum(l.resultsCount for l in logs) / total

    thumbs_up   = sum(1 for l in logs if l.userFeedback == 1)
    thumbs_down = sum(1 for l in logs if l.userFeedback == -1)
    total_feedback = thumbs_up + thumbs_down
    feedback_ratio = thumbs_up / total_feedback if total_feedback > 0 else None

    return {
        "total_searches":    total,
        "pinecone_searches": len(pinecone_logs),
        "native_searches":   len(native_logs),
        "fallback_rate":     round(len(fallback_logs) / total, 3),
        "avg_latency_ms":    avg_latency,
        "avg_pinecone_score": round(avg_score, 3) if avg_score is not None else None,
        "avg_results_count": round(avg_results, 1),
        "avg_ndcg":          round(avg_ndcg, 3) if avg_ndcg is not None else None,
        "thumbs_up":         thumbs_up,
        "thumbs_down":       thumbs_down,
        "feedback_ratio":    round(feedback_ratio, 3) if feedback_ratio is not None else None,
        "days":              days,
    }
