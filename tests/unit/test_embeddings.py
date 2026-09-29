from app.core.embeddings import get_embedder


def test_embedder_dimension_and_query():
    embedder = get_embedder()
    assert embedder.dim == 384

    doc_embs = embedder.embed_documents(["Database connection pool exhausted", "TLS certificate expired"])
    assert len(doc_embs) == 2
    assert len(doc_embs[0]) == 384
    assert len(doc_embs[1]) == 384

    query_emb = embedder.embed_query("connection timeout to postgres")
    assert len(query_emb) == 384


def test_embedder_caching():
    embedder = get_embedder()
    text = "Unique incident description for testing cache mechanism"
    res1 = embedder.embed_documents([text])[0]
    res2 = embedder.embed_documents([text])[0]
    assert res1 == res2
