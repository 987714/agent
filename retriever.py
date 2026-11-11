import numpy as np


# 检查输入 → 计算相似度 → 排序 → 取前top_k段
# → 返回正文、来源、编号和分数
def retrieve(chunk_documents, vectors, question_vector, top_k=3):       # 接收片段、片段向量和问题向量，返回top_k个
    """检索归一化向量；vectors[i]必须对应chunk_documents[i]。"""
    if type(top_k) is not int or top_k <= 0:
        raise ValueError("top_k必须是正整数")
    if len(chunk_documents) == 0:
        if len(vectors) != 0:
            raise ValueError("片段数量与向量数量必须一致")
        return []

    vectors = np.asarray(vectors, dtype=float)
    question_vector = np.asarray(question_vector, dtype=float)

    if vectors.ndim != 2:
        raise ValueError("片段向量必须是二维数组")
    if question_vector.ndim != 1:
        raise ValueError("问题向量必须是一维数组，请取embed_texts([question])[0]")
    if len(chunk_documents) != len(vectors):
        raise ValueError("片段数量与向量数量必须一致")
    if vectors.shape[1] == 0 or vectors.shape[1] != question_vector.shape[0]:
        raise ValueError("片段向量与问题向量的维度必须一致且非空")
    if not np.isfinite(vectors).all() or not np.isfinite(question_vector).all():
        raise ValueError("向量不能包含NaN或无穷大")

    # 单位长度向量的点积等于余弦相似度。
    if not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5):
        raise ValueError("片段向量需要先归一化")
    if not np.isclose(np.linalg.norm(question_vector), 1, atol=1e-5):
        raise ValueError("问题向量需要先归一化")

    scores = vectors @ question_vector     #点积计算余弦相似度  ,排的是下标而非正文，确保分数与原文不发生错位；同分保留原顺序。
    ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)  #排序
    results = []
    for index in ranked_indices[:top_k]:          #取前几段，组织返回结果
        chunk = chunk_documents[index]
        results.append({   
            "text": chunk["text"],
            "source": chunk["source"],
            "chunk_id": chunk["chunk_id"],
            "score": float(scores[index])
        })
    return results                         #最后返回的列表中有top_k个字典，然后这些字典按照我们的分数高低来排序，返回的列表中的字典中文本，来源，id，分数这四个要素
