"""教学版BM25：无需额外依赖，不等同于生产级中文分词器。"""
import math
import re
from collections import Counter


def tokenize(text):
    """保留英文/编号整体；中文使用单字和相邻双字，不生成跨标点词。"""
    terms = []
    for part in re.findall(r"[a-zA-Z0-9]+(?:[-_][a-zA-Z0-9]+)*|[\u4e00-\u9fff]+", text.lower()):
        if "\u4e00" <= part[0] <= "\u9fff":
            terms.extend(part)
            terms.extend(part[i:i + 2] for i in range(len(part) - 1))
        else:
            terms.append(part)
    return terms


def keyword_retrieve(chunk_documents, question, top_k=10):
    if type(top_k) is not int or top_k <= 0:
        raise ValueError("top_k必须是正整数")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("问题必须是非空字符串")
    if not chunk_documents:
        return []

    query_terms = set(tokenize(question))
    documents = [tokenize(chunk["text"]) for chunk in chunk_documents]
    frequencies = [Counter(terms) for terms in documents]
    average_length = sum(map(len, documents)) / len(documents)
    if not average_length or not query_terms:
        return []

    document_frequency = Counter()
    for terms in documents:
        document_frequency.update(set(terms))

    k1, b = 1.2, 0.75
    scores = []
    for terms, frequency in zip(documents, frequencies):
        score = 0.0
        for term in query_terms:
            tf = frequency[term]
            if not tf:
                continue
            df = document_frequency[term]
            idf = math.log(1 + (len(documents) - df + 0.5) / (df + 0.5))
            denominator = tf + k1 * (1 - b + b * len(terms) / average_length)
            score += idf * tf * (k1 + 1) / denominator
        scores.append(score)

    ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    results = []
    for index in ranked_indices:
        if scores[index] <= 0:
            continue  # 没有关键词命中的片段不加入BM25候选。
        results.append({**chunk_documents[index], "score": float(scores[index])})
        if len(results) == top_k:
            break
    return results
