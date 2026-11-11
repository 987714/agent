from keyword_retriever import keyword_retrieve
from retriever import retrieve


def rrf_fuse(vector_results, keyword_results, top_k=3, rrf_k=60):
    """RRF：每个排名贡献1/(rrf_k+rank)，不相加两路原始分数。"""
    if type(top_k) is not int or top_k <= 0:
        raise ValueError("top_k必须是正整数")
    if type(rrf_k) is not int or rrf_k <= 0:
        raise ValueError("rrf_k必须是正整数")
    combined = {}
    for route, results in (("vector", vector_results), ("keyword", keyword_results)):
        seen = set()
        for rank, item in enumerate(results, start=1):
            key = (item["source"], item["chunk_id"])
            if key in seen:
                continue
            seen.add(key)
            if key not in combined:
                combined[key] = {
                    "text": item["text"], "source": item["source"],
                    "chunk_id": item["chunk_id"], "score": 0.0,
                    "vector_rank": None, "keyword_rank": None,
                    "vector_score": None, "keyword_score": None
                }
            result = combined[key]
            result["score"] += 1 / (rrf_k + rank)
            result[f"{route}_rank"] = rank
            result[f"{route}_score"] = item["score"]
    return sorted(combined.values(), key=lambda item: item["score"], reverse=True)[:top_k]


def hybrid_retrieve(chunk_documents, vectors, question_vector, question,top_k=3, candidate_k=10):
    if type(candidate_k) is not int or candidate_k <= 0:
        raise ValueError("candidate_k必须是正整数")
    if type(top_k) is not int or top_k <= 0:
        raise ValueError("top_k必须是正整数")
    candidate_k = max(candidate_k, top_k)
    keys = [(chunk["source"], chunk["chunk_id"]) for chunk in chunk_documents]
    if len(set(keys)) != len(keys):
        raise ValueError("同一来源中的chunk_id不能重复")
    # 两路都只收到主程序已经过滤后的资料，不能绕过来源条件。
    vector_results = retrieve(chunk_documents, vectors, question_vector, candidate_k)
    keyword_results = keyword_retrieve(chunk_documents, question, candidate_k)
    return {
        "vector_results": vector_results,
        "keyword_results": keyword_results,
        "results": rrf_fuse(vector_results, keyword_results, top_k)
    }

#融合分数 = 向量榜的排名贡献 + 关键词榜的排名贡献     RRF不是把名次直接相加，而是先把每个名次转换成贡献，再累加，result["score"] += 1 / (rrf_k + rank)根据这一句，贡献值是比如一个第一一个第三，1/(60+1),还有一个是1/(60+3)