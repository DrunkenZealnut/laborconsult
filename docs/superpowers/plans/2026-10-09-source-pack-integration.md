# Collected source pack integration plan

**Goal:** Register reviewed official references and rerun the original 50 questions using identical code and input before and after ingestion.

**Architecture:** Use the existing embedding model, active Pinecone namespace and metadata conventions. Keep original downloads immutable; generated review, cleaned text, vector ledger and evaluation results live in the external evaluation directory. Merge only confirmed new vectors into the existing BM25 corpus, preserving all other entries.

**Tech stack:** Existing Python environment, XML parsing, OpenAI embeddings, Pinecone, gzip JSONL, existing local evaluation harness.

**Spec:** User authorized edition/rights review → text cleaning → search registration → quality retest. Input: `/Users/zealnutkim/Downloads/laborconsult-source-pack-2026-10-09/catalog.json`.

## Constraints

- Namespace `laborlaw-v2`; index resolves through `app.config.resolve_index_name()` and must be the dedicated laborconsult index.
- Existing source-type labels and embedding dimension 1536 remain unchanged.
- No existing vector deletion, reset, legal-rule automatic approval, public evaluation publication or customer message delivery.
- Hold sources with unconfirmed reuse rights, outdated/conflicting instructions or unresolved provenance.
- Statutory current body, current annexes and separately identified applicable clauses only; exclude future provisions and mixed historical amendments from current-law chunks.
- Evaluation uses identical title+body fixture, code, provider configuration and cache-only legal API; Supabase persistence disabled.
- Existing score85.78 is contextual history, not a directly comparable baseline.

## Review focus

Future XML clauses; PDF/HWP/XML duplicate works; image-only annexes; accidental source-type promotion of restricted manuals; partial upload/BM25 overwrite.

## Tasks

- [x] Review every collected work and record inclusion/hold decisions with dates and rights evidence.
- [x] Run before evaluation on all50 title+body questions and preserve complete answers.
- [x] Prepare current-law/decision/approved-interpretation text and deterministic source-specific vectors; validate IDs, URLs, source dates and hashes before remote writes.
- [x] Upsert only this batch, fetch every written ID for verification, preserve rollback ledger; atomically merge verified metadata into BM25 without removing unrelated data.
- [x] Run after evaluation using the same inputs/code; compare retrieval and answer checks, record limitations and unresolved quality issues.

**Execution:** User already instructed sequential execution. Continue each authorized step without an additional plan-approval gate. This is data integration using existing product code, not a new product feature.

**Verified data result:** 128 works reviewed; 54 registered and 74 held. 7,111 remotely fetched records; BM25 82,184 → 89,295, preserving all original rows. Eight specifically reviewed operative supplementary clauses accompany 21 affected body chunks. The first partial after run was archived and excluded before these corrections; final after uses a frozen corpus.

**Protocol:** The harness's raw worktree fingerprint includes the intended BM25 binary change. Preserve its mismatch; independently verify identical product code and settings while excluding only this exact generated data file. Do not commit until final generation and checks finish, because that changes the recorded HEAD.

**Verified evaluation result:** Before and after each 50/50 completed, with identical title+body questions, product HEAD 7d80f4d and settings revision8. Actual provider OpenAI/gpt-6-sol for all answers after Claude quota fallback. Pipeline errors/truncations0. Paired qualitative review:15 improved,29 unchanged,3 mixed,3 regressed. Priority15 cases grounded against official sources; secondary9-case review completed. These observations are not a100-point legal score or a causal estimate of source additions. Raw worktree hash differs only because of the intentional BM25 file change; product-code equality is separately verified. Original85.78 is not comparable.

**Handoff:** External artifacts are under `/Users/zealnutkim/DEV/laborconsult_eval/source-integration-20261009`; `integration_result.txt` summarizes application and gaps, and `paired-semantic-review.txt` contains all50 comparisons. Shared Pinecone data is active; main local BM25 file updated. Hosted BM25 requires including this committed corpus in a later deployment; existing local process caches require reload/restart.
