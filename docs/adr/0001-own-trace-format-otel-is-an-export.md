# Our own Trace format is the record; OpenTelemetry is a lossy export

Each Run is recorded as a JSONL Trace holding every Step's full inputs and outputs, and all scoring, replay, and reporting read only that format. OpenTelemetry spans (for example through ADOT to X-Ray, AWS-05) are produced from it as an optional export for trace viewers, following the GenAI conventions but omitting tool outputs and model text. We chose this over making OTel the native format because replay and LLM judging need complete payloads, which OTel's GenAI conventions keep optional and are still changing; because a plain file per Run works offline, which the demo fallback depends on; and because scoring must not depend on any one tracing tool (the brief's "swappable" requirement, REQ-11).

## Consequences

Evaluating a Harness that only emits OpenTelemetry (for example a framework-based one) needs an importer from its spans into our Trace format, and only works if those spans include tool outputs.
