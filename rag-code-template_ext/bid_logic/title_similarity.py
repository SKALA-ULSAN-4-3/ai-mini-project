"""공고문 인덱스 없이 공고명과 프로필 질의의 코사인 유사도를 계산한다."""

from math import sqrt

from .common import number


def embedding_title_similarity(embeddings, query, titles):
    """PipelineEmbeddings 등 embed_query/embed_documents 인터페이스를 받는다.

    빈 공고명은 임베딩 API에 보내지 않는다. 모델·정규화는 주입된 어댑터가 맡는다.
    """
    positions = [i for i, title in enumerate(titles) if title.strip()]
    scores = [0.0] * len(titles)
    if not query.strip() or not positions:
        return scores
    q = [float(number(v)) for v in embeddings.embed_query(query)]
    vectors = embeddings.embed_documents([titles[i] for i in positions])
    if not q or len(vectors) != len(positions):
        raise ValueError("공고명 임베딩 개수 또는 차원이 올바르지 않습니다.")
    qnorm = sqrt(sum(v * v for v in q))
    for i, raw in zip(positions, vectors):
        v = [float(number(x)) for x in raw]
        if len(v) != len(q):
            raise ValueError("질의와 공고명 임베딩 차원이 다릅니다.")
        norm = sqrt(sum(x * x for x in v))
        scores[i] = sum(a * b for a, b in zip(q, v)) / (qnorm * norm) if qnorm and norm else 0.0
    return scores
