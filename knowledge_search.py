from functools import lru_cache
from pathlib import Path
from document_loader import load_document
from text_splitter import split_tokens
from hybrid_retriever import hybrid_retrieve
from metadata_filter import filter_by_source
KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge_files"


@lru_cache(maxsize=1)
def prepare_knowledge():                              #先读资料，然后把资料分成段落，并且embedding向量化
    # 首次查询才导入、加载模型；启动服务时不加载。
    from transformers import AutoTokenizer
    from embedding import embed_texts
    file_paths = []
    for path in sorted(KNOWLEDGE_DIR.iterdir()):
        if path.is_file() and path.suffix.lower() in (".txt", ".md"):
            file_paths.append(path)
    if not file_paths:
        raise ValueError("knowledge_files目录中没有可检索的.txt或.md资料")

    tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-small-zh-v1.5")
    chunk_size = 200
    overlap = 30
    chunk_documents = []
    for file_path in file_paths:
        document = load_document(file_path)
        text = document["text"]
        encoded = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
        tokens = encoded["input_ids"]
        offsets = encoded["offset_mapping"]
        chunks = split_tokens(tokens, chunk_size, overlap)

        for i in range(len(chunks)):
            first_position = offsets[i * (chunk_size - overlap)]
            if i == len(chunks) - 1:
                last_position = offsets[-1]
            else:
                last_position = offsets[chunk_size - 1 + i * (chunk_size - overlap)]
            chunk_documents.append({
                "text": text[first_position[0]:last_position[1]],
                "source": document["source"],
                "chunk_id": i
            })

    if not chunk_documents:
        raise ValueError("资料分词后没有可检索的片段")
    texts = []
    for chunk in chunk_documents:
        texts.append(chunk["text"])
    vectors = embed_texts(texts)
    return chunk_documents, vectors


def search_knowledge(question, source=""):          #函数的输入是要问的问题，和信息的文本来源，最终通过召回和排序，得到排序的结果
#source=""表示不限制来源，
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question必须是非空字符串")
    if not isinstance(source, str):
        raise ValueError("source必须是字符串；空字符串表示查全部资料")

    try:
        chunk_documents, vectors = prepare_knowledge()
        filtered_documents, filtered_vectors = filter_by_source(
            chunk_documents, vectors, source
        )
        if not filtered_documents:
            return []

        # Python会复用已导入的模块，不会每次查询都重新加载Embedding模型。
        from embedding import embed_texts
        from reranker import rerank
        question_vector = embed_texts([question])[0]
        search = hybrid_retrieve(
            filtered_documents, filtered_vectors, question_vector, question,
            top_k=10, candidate_k=10)             #两种方案混合召回
        selected = rerank(question, search["results"], final_k=3)          #对召回的结果排序，最多保留final_k个
    except (OSError, RuntimeError) as error:
        import traceback
        traceback.print_exc()  # 先在终端打印原始报错
        raise ValueError(
        "知识检索暂时失败，请检查资料读取或本地模型加载情况"
    ) from error
    return selected                       #返回排序的结果
