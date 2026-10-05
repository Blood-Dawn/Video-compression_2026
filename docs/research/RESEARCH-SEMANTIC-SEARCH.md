# Semantic Search Research

## Purpose

Semantic search will allow users to search surveillance metadata and indexed content using natural-language meaning rather than relying only on exact keywords.

Example searches include:

- "person near a parking lot"
- "vehicle at night"
- "someone wearing red"
- "activity near the entrance"

The Week 6 implementation is intentionally a skeleton. It defines the interfaces and data flow without downloading a machine-learning model during normal installation or CI.

## Model Choice

The proposed initial embedding model is `sentence-transformers/all-MiniLM-L6-v2`.

Reasons for this choice:

- Smaller than many larger transformer models.
- Designed for sentence and text embeddings.
- Produces fixed-size vectors suitable for similarity search.
- Reasonable for CPU-based local use.
- Can be downloaded once and then used locally without a network connection.

The actual model is optional. The Week 6 skeleton uses a deterministic stub embedder so tests and CI do not require model downloads.

## Embedding Storage

SQLite remains the system of record for surveillance segment metadata.

Embeddings should be stored separately from the core metadata columns. Each embedding should have a stable association with the corresponding segment database ID.

The initial implementation can use serialized vectors and a simple similarity scan. A dedicated vector index can be evaluated later if the number of embeddings becomes large enough to require it.

Existing exact metadata queries should continue to work and can be combined with semantic similarity results.

## Search Architecture

The proposed semantic-search flow is:

1. User enters a natural-language query.
2. The query is converted into an embedding.
3. Stored candidate embeddings are loaded.
4. Similarity is calculated between the query and candidates.
5. Candidates are ranked by similarity.
6. Existing metadata filters can be applied.
7. Ranked results are returned to the GUI.

Semantic search complements existing metadata and keyword search rather than replacing it.

## Offline Story

The core application must not download a model automatically.

CI must not download a machine-learning model.

The default installation should not require semantic-search dependencies.

Semantic search should be an opt-in feature. When enabled, the user explicitly installs the required dependencies and obtains the embedding model.

After the model has been downloaded, it can be stored locally and used without network access.

A semantic search request should never silently download a model.

## CI and Testing

CI should use the deterministic stub embedder.

The test suite should verify:

- Embedding generation.
- Embedding dimensions.
- Embedding storage and retrieval.
- Similarity ranking.
- Result formatting.
- Integration with existing metadata filters.

Tests using the real embedding model should remain optional and should only run when the semantic-search dependencies and model are explicitly available.

## Opt-In Dependency Strategy

Semantic search should be an optional feature.

The core project should remain usable on CPU-only and legacy systems without installing transformer or vector-search dependencies.

The implementation should follow this pattern:

core application
|
+-- existing metadata search
|
+-- optional semantic search
        |
        +-- stub embedder (tests/CI)
        |
        +-- real embedder (opt-in)

## Initial Skeleton

The Week 6 skeleton should define a small embedding interface that allows callers to work with either:

- A deterministic stub embedder for testing and CI.
- A real local embedding implementation when the optional dependency is installed.

The semantic-search layer should not depend directly on a specific model implementation.

This separation allows a real embedding model to be added later without changing callers that perform searches.

## Recommendation

Start with a deterministic stub embedder and a simple persisted vector representation.

Evaluate the local embedding model after the search interface and integration tests are stable.

A simple SQLite-backed or in-memory linear similarity scan should be sufficient for the initial implementation. A dedicated vector index should only be introduced if real-world data volume demonstrates a need for it.

This approach keeps semantic search:

- Optional.
- Offline-friendly.
- CPU-compatible.
- Deterministic in CI.
- Easy to test.
- Compatible with the existing metadata search system.