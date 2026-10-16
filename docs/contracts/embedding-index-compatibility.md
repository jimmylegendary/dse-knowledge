# Embedding/index compatibility contract

Status: design contract, not a deployment choice. The relational PostgreSQL + pgvector baseline and graph backend decision are described in [02-storage-retrieval.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/research/02-storage-retrieval.md). Candidate model roles are listed in [04-models-ingestion-evaluation.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/research/04-models-ingestion-evaluation.md).

This contract prevents a model output from being written into an index with an incompatible dimension, type, distance operator or extension version. It does not imply a retrieval quality result. Each candidate index must be tested against a flat/exact baseline on the same held-out DSE query set.

## Space identity and immutable metadata

An embedding space is keyed by the exact provider/model ID and model revision, task/instruction and query/document formatter, tokenizer, chunking and normalization version, output dimension, output dtype, and preprocessing revision. Persist these values on every vector row or an immutable collection manifest. Query and document vectors may only be compared if the model defines them as compatible asymmetric inputs. Do not place different model revisions, dimensions, prefixes, output precisions or metric conventions in one index. An embedding model or dimension change creates a new index generation and requires re-embedding and quality evaluation.

The source corpus contract uses 512-token chunks with 64-token overlap for cost comparison. That is only a workload assumption; the chunk size/overlap is part of the embedding-space key and can be changed only with a new generation. Raw document tokens and billed chunked tokens differ because overlap is sent again.

## pgvector limits and types

The upstream [pgvector README at v0.8.7 commit `f37c13f68b57d2c3472b2214fbcff699d6d34876`](https://github.com/pgvector/pgvector/blob/f37c13f68b57d2c3472b2214fbcff699d6d34876/README.md) gives these distinct limits:

- Exact storage supports up to 16,000 dimensions for `vector` and `halfvec`. `vector` stores float32 and takes `4 × dimensions + 8` bytes; `halfvec` stores half precision and takes `2 × dimensions + 8` bytes.
- HNSW and IVFFlat indexes support `vector` up to 2,000 dimensions, `halfvec` up to 4,000, and `bit` up to 64,000. The limits apply to both ANN index methods. They are lower than the type's exact-storage limit.
- pgvector distance operators include L2 `<->`, negative inner product `<#>`, cosine distance `<=>`, and binary Hamming `<~>`. An ANN index operator class and query `ORDER BY` operator must match.
- Exact search has no ANN index. Keep it as the gold retrieval result and measure ANN recall against it. Approximate filtering may return too few rows; iterative scans, partitions, or a different design need paired ACL-filtered recall/latency testing.

The upstream comparator is v0.8.7, not a promise about any managed PostgreSQL service. Supabase documents the dimension thresholds for pgvector 0.7.0+ and exposes the installed version through `SELECT extversion FROM pg_extension WHERE extname = 'vector';`. Supabase also says explicit extension version pinning is deprecated from 2026-08-05. For any managed service/profile, record the database engine/version, SKU/edition and actual `extversion` from that deployment; run a dimension/index creation check. Until that check, managed extension compatibility is `not_verified`; the table's upstream comparator is not a deployment observation.

## Candidate compatibility matrix

“ANN: yes” means the stated output dimension fits the pgvector dimension ceiling; it does not assert the selected managed instance has that extension version, enough memory, or an acceptable recall/latency result. Unknown deployed `extversion` means `not_verified`, even when the dimension is within the upstream limit. Exact-storage and ANN boundary cases, including Qwen MRL and unknown managed-version states, are fixed in [embedding-index-cases.json](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/fixtures/p0/embedding-index-cases.json). All float paths use explicit L2 normalization and cosine distance as the initial comparison convention. Where a provider/model has a defined normalisation contract, preserve it; otherwise normalize both query and document vectors in the pinned formatter. Confirm exact vs approximate ordering in SQL before publishing an index.

| Model ID / family | Output dimension used for baseline | Default/alternate output type | `vector` exact | `vector` HNSW/IVFFlat | `halfvec` exact | `halfvec` HNSW/IVFFlat | Distance / implementation note | Managed extension version |
|---|---:|---|---|---|---|---|---|---|
| `BAAI/bge-m3` dense | 1024 | float32 | Yes | Yes | Yes | Yes | Cosine after pinned normalization. Its sparse and ColBERT/multi-vector outputs are separate retrieval structures, not additional values in this one dense column. | Upstream comparator v0.8.7; read deployed `extversion`. |
| `intfloat/multilingual-e5-large-instruct` | 1024 | float32 | Yes | Yes | Yes | Yes | Cosine; record the required query instruction and no-document-instruction format. | Same. |
| `Qwen/Qwen3-Embedding-0.6B` | 1024 | float32 | Yes | Yes | Yes | Yes | Cosine; pin model prompt/task and explicit normalization. | Same. |
| `Qwen/Qwen3-Embedding-4B` | 2560 | float32 | Yes | **No** | Yes | Yes | Cosine; 2560 exceeds indexed `vector` limit but fits `halfvec` ANN. Half conversion is lossy and needs its own quality gate. | Same. |
| `Qwen/Qwen3-Embedding-8B` | 4096 | float32 | Yes | **No** | Yes | **No** | Cosine exact-only at default size. 4096 exceeds both ANN limits (`vector` 2000, `halfvec` 4000). Supported MRL output 1024 fits both dimension ceilings, but is a separate index variant with a required retrieval-quality gate. | Same. |
| `text-embedding-3-small` | 1536 | float32 | Yes | Yes | Yes | Yes | OpenAI documents unit-normalized output; cosine is the baseline. Inner product is ranking-equivalent only while both vectors remain unit-normalized. | Same. |
| `text-embedding-3-large` | 3072 | float32 | Yes | **No** | Yes | Yes | OpenAI documents unit-normalized output. A requested reduced dimension is a distinct space and must be recorded. | Same. |
| `gemini-embedding-2` | 3072 default; 1536 alternative | float32 | Yes | 1536: Yes; 3072: **No** | Yes | Yes | Google supports 128–3072 output dimensions and normalization for reduced dimensions; 1536 is a documented recommended choice that fits `vector` ANN. | Same. |
| `voyage-4-large` | 1024 default; 2048 alternative | float32 | Yes | 1024: Yes; 2048: **No** | Yes | Yes for both dimensions | Voyage supports 256/512/1024/2048. The 2048 output exceeds `vector` ANN's 2000 limit but fits the `halfvec` 4000 ceiling after a separately quality-gated precision conversion. Optional `int8`, `uint8`, `binary`, `ubinary` outputs are separate encodings; binary uses bit/Hamming coarse retrieval plus float rerank, not cosine. | Same. |
| `embed-v5.0-pro` | 2048 default; 1024 alternative | float | Yes | 1024: Yes; 2048: **No** | Yes | Yes for both dimensions | Cohere supports 256/512/768/1024/1536/2048. The default 2048 exceeds `vector` ANN's 2000 limit but fits the `halfvec` 4000 ceiling after a separately quality-gated precision conversion. Quantized `int8`/binary outputs are distinct spaces and are not silently cast to float. | Same. |
| `jina-embeddings-v5-text-small-retrieval` | 1024 | float32 | Yes | Yes | Yes | Yes | Retrieval task and query/document formatter are part of the space; local weight license is CC BY-NC 4.0. | Same. |

`vector` and `halfvec` exact columns can hold Qwen3-Embedding-8B at 4096 dimensions because the type storage maximum is 16,000; the HNSW/IVFFlat index still cannot. The result is exact search only until output dimensions are reduced, a supported quantized index is measured, or a different vector service is selected. Binary quantization changes the distance function and is a candidate generator; rerank from retained float vectors or another approved high-precision source before treating it as final ranking.

## Managed-extension compatibility gate

Before a profile can claim pgvector compatibility, record and check:

1. Provider, managed product, PostgreSQL engine version, region, SKU/edition, and `vector` extension `extversion` from the actual instance.
2. Model/revision, output dimension/dtype, query/document formatter, normalization, chunking and embedding-space ID.
3. Storage type (`vector`, `halfvec`, `bit`, or separate sparse/multi-vector representation), index method (exact, HNSW or IVFFlat), operator class and query distance operator.
4. Whether the DDL succeeds on that deployed extension; `EXPLAIN` confirms the intended index; ACL prefilter behavior and filtered recall meet the acceptance gate.
5. Exact-vs-ANN Recall@k/nDCG and p95 latency on the same held-out DSE queries. Compare float32, halfvec and binary/MRL variants separately. Do not use storage reduction as a quality conclusion.

The API/model documentation and upstream source links used for this compatibility assessment are [pgvector v0.8.7](https://github.com/pgvector/pgvector/blob/f37c13f68b57d2c3472b2214fbcff699d6d34876/README.md), [Supabase vector index limits](https://supabase.com/docs/guides/ai/vector-indexes), [Supabase extension-version behavior](https://supabase.com/changelog/extension-version-pinning-ignored), [Qwen3-Embedding-8B model card at revision `1d8ad4ca9b3dd8059ad90a75d4983776a23d44af`](https://huggingface.co/Qwen/Qwen3-Embedding-8B/tree/1d8ad4ca9b3dd8059ad90a75d4983776a23d44af), [OpenAI embeddings](https://developers.openai.com/api/docs/guides/embeddings), [Gemini Embeddings](https://ai.google.dev/gemini-api/docs/embeddings), [Voyage dimensions/quantization](https://docs.voyageai.com/docs/flexible-dimensions-and-quantization), [Cohere Embed models](https://docs.cohere.com/docs/cohere-embed), and [Jina v5 retrieval model](https://huggingface.co/jinaai/jina-embeddings-v5-text-small-retrieval).
