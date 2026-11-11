def split_tokens(tokens, chunk_size, overlap):
    """按Token数量切分，保留相邻片段的重叠部分。"""
    if type(chunk_size) is not int or chunk_size <= 0:
        raise ValueError("chunk_size必须是正整数")
    if type(overlap) is not int:
        raise ValueError("overlap必须是整数")
    if not (0 <= overlap < chunk_size):
        raise ValueError("overlap必须满足0 <= overlap < chunk_size")

    start = 0
    step = chunk_size - overlap
    chunks = []

    while start < len(tokens):
        end = start + chunk_size
        chunks.append(tokens[start:end])

        # 已包含最后一个Token，不再生成只有重复内容的尾段。
        if end >= len(tokens):
            break
        start += step

    return chunks
