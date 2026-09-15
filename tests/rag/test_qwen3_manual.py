import time


MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"


def print_gpu_memory(prefix: str, torch_module) -> None:
    if not torch_module.cuda.is_available():
        return

    allocated = torch_module.cuda.memory_allocated() / 1024**3
    reserved = torch_module.cuda.memory_reserved() / 1024**3
    free, total = torch_module.cuda.mem_get_info()

    print(f"{prefix}")
    print(f"  allocated : {allocated:.2f} GB")
    print(f"  reserved  : {reserved:.2f} GB")
    print(f"  free      : {free / 1024**3:.2f} GB")
    print(f"  total     : {total / 1024**3:.2f} GB")


def main() -> None:
    try:
        import numpy as np
        import torch
        from sentence_transformers import SentenceTransformer
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "This manual Qwen3 embedding test requires numpy, torch, and "
            "sentence-transformers. Install the local embedding dependencies "
            "before running it directly."
        ) from exc

    print("=" * 70)
    print("AITrans - Qwen3-Embedding-0.6B GPU Test")
    print("=" * 70)

    device = "cuda" if torch.cuda.is_available() else "cpu"

    print(f"PyTorch: {torch.__version__}")
    print(f"CUDA available: {torch.cuda.is_available()}")
    print(f"CUDA runtime: {torch.version.cuda}")
    print(f"Device: {device}")

    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print_gpu_memory("Before model loading", torch)

    print()
    print(f"Loading model: {MODEL_NAME}")

    start = time.perf_counter()

    model = SentenceTransformer(
        MODEL_NAME,
        device=device,
    )

    load_time = time.perf_counter() - start

    print(f"Model loaded in {load_time:.2f} s")

    print_gpu_memory("After model loading", torch)

    queries = [
        "How can Gaussian process optimization improve PID tuning?",
        "什么是基于高斯过程的PID参数整定？",
        "How does an LLM cooperate with Bayesian optimization?",
    ]

    documents = [
        (
            "Gaussian process regression provides a probabilistic surrogate "
            "model that can guide Bayesian optimization of PID controller gains."
        ),
        (
            "PID控制器包含比例、积分和微分参数，可以利用高斯过程和"
            "贝叶斯优化方法自动搜索性能更好的控制参数。"
        ),
        (
            "Large language models are effective at semantic reasoning and "
            "can provide local candidate suggestions conditioned on system state."
        ),
        (
            "Convolutional neural networks are widely used for computer vision."
        ),
    ]

    print()
    print("Encoding queries...")

    start = time.perf_counter()

    query_embeddings = model.encode(
        queries,
        prompt_name="query",
        batch_size=8,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )

    print("Encoding documents...")

    document_embeddings = model.encode(
        documents,
        batch_size=8,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )

    inference_time = time.perf_counter() - start

    similarities = np.matmul(
        query_embeddings,
        document_embeddings.T,
    )

    print()
    print("=" * 70)
    print("Results")
    print("=" * 70)

    print("Query embeddings shape:")
    print(query_embeddings.shape)

    print("Document embeddings shape:")
    print(document_embeddings.shape)

    print()
    print("Cosine similarity matrix:")
    print(np.round(similarities, 4))

    print()
    print(f"Embedding time: {inference_time:.4f} s")

    print_gpu_memory("After inference", torch)

    print()
    print("Best matching document for each query:")

    for query_index, query in enumerate(queries):
        best_index = int(np.argmax(similarities[query_index]))
        score = float(similarities[query_index][best_index])

        print()
        print(f"Query {query_index + 1}:")
        print(query)

        print(f"Best document #{best_index + 1}")
        print(documents[best_index])

        print(f"Score: {score:.4f}")


if __name__ == "__main__":
    main()
