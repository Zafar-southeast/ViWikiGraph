ViWikiGraph

Cross-Modal Video-to-Wiki Generation for Evidence-Grounded VideoQA

ViWikiGraph converts a single video into a reusable, validated, and evidence-grounded knowledge package before downstream questions are observed. The package combines a human-readable narrative wiki, a KG-oriented wiki, linked visual media, timestamps, provenance, and typed cross-modal evidence links. During question answering, ViWikiGraph retrieves a compact evidence packet and returns an answer with a claim-level evidence trace.

Overview

VideoQA evidence is often distributed across subtitles, speech, OCR text, scenes, objects, actions, events, and short temporal intervals. Query-time pipelines repeatedly process this information for each question, making the resulting knowledge difficult to reuse, inspect, and verify.

ViWikiGraph instead performs question-independent video-to-wiki construction once and reuses the validated package across multiple questions.

flowchart LR
    A[Video + subtitles/ASR] --> B[Timestamped multimodal evidence]
    B --> C[Narrative Wiki]
    B --> D[KG-Oriented Wiki]
    B --> E[Linked Media Repository]
    C --> F[Pre-storage Validation]
    D --> F
    E --> F
    F --> G[Validated Video Knowledge Package]
    G --> H[Cross-Modal Retrieval]
    H --> I[Answer + Claim-Level Evidence Trace]
    I --> J[Conditional Verification]
    J -->|Verified source evidence only| K[Optional Evidence-Gated Refinement]

Main Components

1. Multimodal Evidence Ingestion

The video is decomposed into timestamped evidence units, including:

subtitle, ASR, and dialogue spans;

OCR text;

representative frames and scene snapshots;

short event clips;

entities, objects, actions, and events;

visual descriptions and candidate relation triples.

2. Narrative Wiki

narrative_wiki.md provides a human-readable account of the video through:

global and scene-level descriptions;

localized events and actions;

timestamps and temporal intervals;

entity and object references;

confidence, support, and provenance information.

3. KG-Oriented Wiki

kg_wiki.md provides a structured representation containing:

canonical entities and events;

subject-predicate-object triples;

semantic and temporal relations;

links between corresponding narrative and KG entries;

references to supporting text, timestamps, images, snapshots, and clips.

4. Cross-Modal Evidence Linking

Shared identifiers and typed links connect narrative claims and KG entries to their supporting:

subtitle, ASR, and OCR spans;

timestamps and temporal intervals;

entity images and scene snapshots;

event clips;

provenance records.

These links allow textual, visual, temporal, and structured evidence to be traced jointly.

5. Pre-Storage Validation

Claims, triples, media references, and cross-modal links are checked before becoming persistent knowledge. Unsupported or conflicting items may be locally revised or rejected, reducing the risk of storing ungrounded content.

6. Wiki-Grounded QA

For each question, ViWikiGraph retrieves a bounded evidence packet from the validated package. The QA module returns:

the predicted answer;

calibrated confidence;

a claim-level evidence trace linking the answer to supporting wiki entries and source evidence.

Conditional verification is activated for uncertain, conflicting, or visually ambiguous cases.

7. Evidence-Gated Refinement

Refinement is evaluated separately from standard QA. A package update is permitted only when the proposed patch is supported by verifier-confirmed source evidence.

Questions, candidate options, predicted answers, gold answers, and test labels are never treated as evidence for persistent updates.

Knowledge Package

Each video produces a reusable package containing:

video_knowledge_package/
├── narrative_wiki.md
├── kg_wiki.md
├── linked_media/
│   ├── entity_images/
│   ├── scene_snapshots/
│   └── event_clips/
└── cross-modal links, validation metadata, and provenance records

The exact serialization of link and provenance records follows the repository configuration.

Key Properties

Question-independent: constructed without downstream questions or answer labels.

Reusable: one package supports repeated questions about the same video.

Cross-modal: combines text, vision, temporal evidence, and structured relations.

Validated: persistent items are checked before storage.

Auditable: answer claims can be traced to timestamped source evidence.

Efficient: offline construction cost is amortized across repeated questions.

Leakage-controlled: downstream supervision is excluded from construction and refinement.

Results

ViWikiGraph is evaluated under a common retrieval-augmented protocol without task-specific fine-tuning of the foundation components.

Dataset

Accuracy

TVQA+

89.3%

KnowIT VQA

86.2%

NExT-QA

82.9%

The method achieves state-of-the-art performance among the reimplemented systems under the common evaluation protocol while providing explicit provenance tracking and repeated-use efficiency.

Evaluation Scope

The evaluation considers more than answer accuracy:

answer and question-type accuracy;

evidence Recall@K and ranking quality;

temporal grounding;

answer-evidence support;

claim-level trace and citation quality;

package validation and provenance quality;

robustness to evidence corruption;

latency, storage, and repeated-question amortization;

leakage-controlled refinement.

Usage Workflow

Provide a video and its available subtitle, ASR, or dialogue stream.

Extract timestamped textual, visual, temporal, and structured evidence.

Generate the narrative and KG-oriented Markdown wikis.

Validate claims, triples, media references, and cross-modal links.

Store the retained evidence as a reusable video knowledge package.

Retrieve a compact evidence packet for each downstream question.

Generate an answer with confidence and a claim-level evidence trace.

Optionally apply a source-verified package patch in the separate refinement setting.

Reproducibility

The release is intended to include:

construction and QA configurations;

prompts and validation criteria;

retrieval and evidence-budget settings;

benchmark preprocessing instructions;

evaluation scripts;

package-quality and provenance metrics;

hardware and inference settings.

Repository-specific installation commands, model checkpoints, and dataset preparation instructions should be added when the implementation is released.

Citation

Citation information will be added after publication.

Responsible Use

ViWikiGraph improves evidence organization and traceability but does not guarantee that every generated claim or answer is correct. Outputs should be reviewed when used in high-stakes settings. Dataset licenses, privacy requirements, and restrictions on processing identifiable video content must be respected.
