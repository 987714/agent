"""43课：问题与候选正文成对输入CrossEncoder，输出新的相关性排序。"""
import math
from functools import lru_cache
from sentence_transformers import CrossEncoder

@lru_cache(maxsize=1)
def get_reranker():
    # 延迟加载：第一次精排才下载/加载模型，之后复用。
    return CrossEncoder("BAAI/bge-reranker-base", max_length=512)


def rerank(question, candidates, final_k=3, model=None):      # candidates是混合召回得到的候选列表，得到的所有candidates进入精排，最终最多返回final_k个片段。
    if not isinstance(question, str) or not question.strip():
        raise ValueError("问题必须是非空字符串")
    if type(final_k) is not int or final_k <= 0:
        raise ValueError("final_k必须是正整数")
    if not candidates:
        return []

    pairs = []
    for candidate in candidates:
        pairs.append((question, candidate["text"]))          #把我的问题question和candidate候选文本放一对

    if model is None:
        model = get_reranker()                               
    scores = model.predict(pairs)                            # 对每一对“问题＋候选正文”打分,用的是训练好的大模型
    if len(scores) != len(candidates):
        raise ValueError("精排分数数量与候选片段数量不一致")

    results = []
    for candidate, score in zip(candidates, scores):
        score = float(score)
        if not math.isfinite(score):
            raise ValueError("精排分数不能包含NaN或无穷大")
        # 保留原来的融合分数score，新分数使用独立字段，避免混淆。
        result = dict(candidate)
        result["rerank_score"] = score
        results.append(result)

    return sorted(results, key=lambda item: item["rerank_score"], reverse=True)[:final_k]
