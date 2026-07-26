# ViWikiGraph — Video-to-Wiki QA

A **RAG-only** pipeline that turns each video's dataset-provided features into a small,
provenance-tracked "wiki" — narrative sections plus a knowledge graph — and then answers
questions by routing, retrieving, and (optionally) verifying evidence against that wiki.

It runs over three video-QA benchmarks through a common adapter layer:

| Dataset   | Type            | Notes                                            |
|-----------|-----------------|--------------------------------------------------|
| TVQA      | MCQ + subtitles | uses provided subtitles and visual concepts      |
| KnowIT    | MCQ + knowledge | builds a leakage-safe external-knowledge corpus  |
| NExT-QA   | MCQ             | VidOR-mapped, optional captions                  |

The pipeline supports dataset-provided textual and visual features as well as an
optional VLM frame-extraction path enabled with `--use-vlm`. It can use either a
configured OpenAI-compatible API or a local Hugging Face model . When no LLM is enabled, deterministic fallback paths remain available
for offline testing.

Existing VLM-derived knowledge packages can be reused for QA, evaluation,
ablations, and answer-model comparisons without decoding or processing the videos
again.

## Repository structure

``` 
.
├── viwikigraph/
│   ├── _init_.py
│   ├── _main_.py             # python -m viwikigraph
│   ├── cli.py                  # build/index/qa/eval/report/ablate/stress
│   ├── config.py
│   ├── pipeline.py
│   │
│   ├── core/
│   │   ├── schemas.py
│   │   ├── io.py
│   │   └── text.py
│   │
│   ├── llm/
│   │   ├── client.py           # API client and response cache
│   │   ├── local_llama.py      # local Hugging Face Llama backend
│   │   └── prompts.py
│   │
│   ├── datasets/
│   │   └── adapters.py
│   │
│   ├── knowledge/
│   │   ├── extraction.py
│   │   ├── vision.py           # VLM frame extraction/descriptions
│   │   ├── wiki.py
│   │   ├── kg.py
│   │   ├── linking.py          # typed cross-modal links
│   │   ├── validation.py
│   │   ├── refinement.py       # post-QA package refinement
│   │   └── corpus.py
│   │
│   ├── retrieval/
│   │   └── index.py
│   │
│   └── qa/
│       ├── answering.py
│       ├── evaluation.py
│       └── reporting.py
│
├── viwikigraph_eval/           # extended evaluation and audit tooling
│   ├── runtime_logger.py
│   ├── retrieval_hooks.py
│   ├── prediction_hooks.py
│   ├── corruption.py
│   ├── refinement_partitions.py
│   ├── manifest_logger.py
│   └── audit_templates.py
│
├── tests/
├── scripts/
│   ├── smoke_llm.py
│   ├── compare_model_predictions.py
│   └── run_saved_llama_verification.py
│
├── configs/
│   └── datasets.yaml
│
├── docs/
│   ├── DATA_SETUP.md
│   ├── RUNNING.md
│   ├── IMPLEMENTATION_SPEC.md
│   └── paper/
│
├── complete_evaluation_core.py
├── run_complete_evaluation.py
├── README.md
├── LICENSE
├── .gitignore
└── pyproject.toml
```

Each sub-package re-exports its public symbols, so imports stay stable, e.g.
`from viwikigraph.qa import answer_question` or `from viwikigraph.datasets import TVQAAdapter`.

## Requirements

- **Python ≥ 3.12**
- The core API-based pipeline uses the Python standard library.
- **PyYAML is optional.** Without it, configuration files are handled by the built-in minimal YAML parser in `viwikigraph.config`.
- API-based LLM generation requires a configured API key and endpoint.
- Local Llama inference requires:
  - PyTorch with CUDA support
  - Transformers
  - Accelerate
  - A compatible NVIDIA GPU
  - A locally downloaded model, such as Llama 3.1 8B Instruct

The API and local-Llama backends are independent. Local-model dependencies are not required when using the configured API.

## Installation

```bash
# editable install (optional — the package also runs from the repo root as-is)
pip install -e .              # add [yaml] for PyYAML, [dev] for pytest:  pip install -e ".[dev]"
```

## Configuration

LLM access is configured via environment variables (a local `.env` is auto-loaded):

| Variable                        | Purpose                                    | Default                      |
|---------------------------------|--------------------------------------------|------------------------------|
| `AIGCBEST_API_KEY`              | API key (required for live LLM calls)      | —                            |
| `AIGCBEST_BASE_URL`             | OpenAI-compatible base URL                 | `https://api2.aigcbest.top`  |
| `AIGCBEST_AUTH_SCHEME`          | optional auth scheme override              | —                            |
| `VIWIKIGRAPH_MODEL`             | model id (falls back to `AIGCBEST_MODEL`,  | `claude-sonnet-4-6`          |
|                                 | then `ADAGRAPHLOOM_MODEL`)                  |                              |

Dataset paths, retrieval budgets, and run mode live in `configs/datasets.yaml`; any path can be
overridden with `{DATASET}_*` environment variables (see `viwikigraph/config.py`).

## Data setup

Datasets are **not** committed (`data/` is gitignored). See **[docs/DATA_SETUP.md](docs/DATA_SETUP.md)**
for exactly what to download per dataset and where to place it.

## Usage

All commands take `--dataset {tvqa,knowit,nextqa}`, `--split`, and `--experiment-id`; outputs land
under `{output_root}/{experiment_id}/{dataset}/{split}/`. Sampling flags
(`--limit` / `--sample-seed` / `--stratify-by`) are deterministic across stages.

```bash
# 1. build per-video knowledge packages (deterministic; add --use-llm for live generation)
python -m viwikigraph build  --dataset tvqa --split val --experiment-id exp1 --limit 50 --use-llm

# 2. answer questions over the built packages
python -m viwikigraph qa     --dataset tvqa --split val --experiment-id exp1 --limit 50 --mode mcq --use-llm

# 3. score predictions against gold labels
python -m viwikigraph eval   --dataset tvqa --split val --experiment-id exp1 --limit 50

# 4. assemble report.md + run_config.json
python -m viwikigraph report --dataset tvqa --split val --experiment-id exp1 --limit 50
```

Additional commands: `index` (rebuild retrieval indexes), `ablate --variant …`
(e.g. `no_narrative`, `no_kg`,`no_cross_modal_links`, `no_pre_storage_validation`, `no_media`,
`no_provenance`, and `flat_markdown`.), and `stress --setting … --level …`
(degraded-evidence robustness tests). Run `python -m viwikigraph <command> --help` for flags.

After an editable install you can also use the `viwikigraph` console script in place of
`python -m viwikigraph`.

## Testing

```bash
pytest            
```

## Documentation

- [docs/DATA_SETUP.md](docs/DATA_SETUP.md) — dataset downloads and layout
- [docs/RUNNING.md](docs/RUNNING.md) — end-to-end run instructions for each dataset

