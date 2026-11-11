def filter_by_source(chunk_documents, vectors, source=""):
    """按来源精确过滤，同时保留对应片段与向量。"""
    if len(chunk_documents) != len(vectors):
        raise ValueError("片段数量与向量数量必须一致")
    if not isinstance(source, str):
        raise ValueError("source必须是字符串")
    filtered_documents = []
    filtered_vectors = []
    for i in range(len(chunk_documents)):
        if not source or chunk_documents[i]["source"] == source:
            filtered_documents.append(chunk_documents[i])
            filtered_vectors.append(vectors[i])
    return filtered_documents, filtered_vectors
