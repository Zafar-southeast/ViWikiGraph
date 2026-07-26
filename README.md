````markdown
# ViWikiGraph

## Cross-Modal Video-to-Wiki Generation for Evidence-Grounded VideoQA

**ViWikiGraph** converts a single video into a reusable, validated, and evidence-grounded knowledge package before downstream questions are observed. The package combines a human-readable narrative wiki, a KG-oriented wiki, linked visual media, timestamps, provenance records, and typed cross-modal evidence links.

During question answering, ViWikiGraph retrieves a compact evidence packet and returns an answer with a claim-level evidence trace.

## Overview

VideoQA evidence is often distributed across subtitles, speech, OCR text, scenes, objects, actions, events, and short temporal intervals. Query-time pipelines repeatedly process this information for each question, making the resulting knowledge difficult to reuse, inspect, and verify.

ViWikiGraph instead performs question-independent video-to-wiki construction once and reuses the validated knowledge package across multiple questions.

```mermaid
flowchart LR
    A[Video + Subtitles/ASR] --> B[Timestamped Multimodal Evidence]
    B --> C[Narrative Wiki]
    B --> D[KG-Oriented Wiki]
    B --> E[Linked Media Repository]
    C --> F[Pre-Storage Validation]
    D --> F
    E --> F
    F --> G[Validated Video Knowledge Package]
    G --> H[Cross-Modal Retrieval]
    H --> I[Answer + Claim-Level Evidence Trace]
    I --> J[Conditional Verification]
    J -->|Verified Source Evidence Only| K[Optional Evidence-Gated Refinement]
````

## Main Components

### 1. Multimodal Evidence Ingestion

The video is decomposed into timestamped evidence units, including:

* Subtitle, ASR, and dialogue spans
* OCR text
* Representative frames and scene snapshots
* Short event clips
* Entities, objects, actions, and events
* Visual descriptions and candidate relation triples

### 2. Narrative Wiki

`narrative_wiki.md` provides a human-readable account of the video through:

* Global and scene-level descriptions
* Localized events and actions
* Timestamps and temporal intervals
* Entity and object references
* Confidence, support, and provenance information

### 3. KG-Oriented Wiki

`kg_wiki.md` provides a structured representation containing:

* Canonical entities and events
* Subject–predicate–object triples
* Semantic and temporal relations
* Links between corresponding narrative and KG entries
* References to supporting text, timestamps, images, snapshots, and clips

### 4. Cross-Modal Evidence Linking

Shared identifiers and typed links connect narrative claims and KG entries to their supporting:

* Subtitle, ASR, and OCR spans
* Timestamps and temporal intervals
* Entity images and scene snapshots
* Event clips
* Provenance records

These links allow textual, visual, temporal, and structured evidence to be traced jointly.

### 5. Pre-Storage Validation

Claims, triples, media references, and cross-modal links are checked before becoming persistent knowledge. Unsupported or conflicting items may undergo a bounded local revision or be rejected, reducing the risk of storing ungrounded content.

### 6. Wiki-Grounded QA

For each question, ViWikiGraph retrieves a bounded evidence packet from the validated package. The QA module returns:

* The predicted answer
* A calibrated confidence score
* A claim-level evidence trace linking the answer to supporting wiki entries and source evidence

Conditional verification is activated for uncertain, conflicting, or visually ambiguous cases.

### 7. Evidence-Gated Refinement

Refinement is evaluated separately from standard QA. A package update is permitted only when the proposed patch is supported by verifier-confirmed source evidence.

Questions, candidate options, predicted answers, gold answers, and test labels are never treated as evidence for persistent updates.

## Knowledge Package

Each video produces a reusable package containing:

```text
video_knowledge_package/
├── narrative_wiki.md
├── kg_wiki.md
├── linked_media/
│   ├── entity_images/
│   ├── scene_snapshots/
│   └── event_clips/
└── cross-modal links, validation metadata, and provenance records
```

The exact serialization of link and provenance records follows the repository configuration.

## Key Properties

* **Question-independent:** Constructed without downstream questions or answer labels
* **Reusable:** One package supports repeated questions about the same video
* **Cross-modal:** Combines text, visual, temporal, and structured evidence
* **Validated:** Persistent items are checked before storage
* **Auditable:** Answer claims can be traced to timestamped source evidence
* **Efficient:** Offline construction cost is amortized across repeated questions
* **Leakage-controlled:** Downstream supervision is excluded from construction and refinement

## Results

ViWikiGraph is evaluated under a common retrieval-augmented protocol without task-specific fine-tuning of the foundation components.

| Dataset    |  Accuracy |
| ---------- | --------: |
| TVQA+      | **89.3%** |
| KnowIT VQA | **86.2%** |
| NExT-QA    | **82.9%** |

ViWikiGraph achieves state-of-the-art performance among the reimplemented systems under the common evaluation protocol while providing explicit provenance tracking and repeated-use efficiency.

## Evaluation Scope

The evaluation considers more than answer accuracy:

* Overall and question-type accuracy
* Evidence Recall@K and ranking quality
* Temporal grounding
* Answer–evidence support
* Claim-level trace and citation quality
* Package validation and provenance quality
* Robustness to evidence corruption
* Latency, storage, and repeated-question amortization
* Leakage-controlled refinement

## Usage Workflow

1. Provide a video and its available subtitle, ASR, or dialogue stream.
2. Extract timestamped textual, visual, temporal, and structured evidence.
3. Generate the narrative and KG-oriented Markdown wikis.
4. Validate claims, triples, media references, and cross-modal links.
5. Store the retained evidence as a reusable video knowledge package.
6. Retrieve a compact evidence packet for each downstream question.
7. Generate an answer with confidence and a claim-level evidence trace.
8. Optionally apply a source-verified package patch in the separate refinement setting.

## Reproducibility

The release is intended to include:

* Construction and QA configurations
* Prompts and validation criteria
* Retrieval and evidence-budget settings
* Benchmark preprocessing instructions
* Evaluation scripts
* Package-quality and provenance metrics
* Hardware and inference settings

Repository-specific installation commands, model checkpoints, and dataset preparation instructions will be added with the implementation release.

## Citation

Citation information will be added after publication.

## Responsible Use

ViWikiGraph improves evidence organization and traceability but does not guarantee that every generated claim or answer is correct. Outputs should be reviewed before use in high-stakes settings.

Dataset licenses, privacy requirements, and restrictions on processing identifiable video content must be respected.

```
```
