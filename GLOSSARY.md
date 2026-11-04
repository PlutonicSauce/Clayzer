# Clay Earth Dataset Foundry: agentic workflow evaluation

The vocabulary for evaluating agentic geospatial workflows: running a system under test on
known units of work, observing what it does, and judging both how it worked and what it
produced.

## Language

**Sandbox**:
The evaluation system as a whole: it runs Harnesses on Cases, captures Traces, and summarizes,
scores, and reports on them.
_Avoid_: observability sandbox (the source documents' phrase), eval tool, platform

### What is evaluated

**Task**:
One of the three kinds of work the hackathon evaluates: the ADB agentic eval, caption
generation, or the open track.
_Avoid_: track, challenge, use case

**Case**:
One concrete prompt within a Task, together with the expectations a good result must meet.
_Avoid_: task (for this level), scenario, test, prompt

**Harness**:
The whole system under test: the model, its instructions, its tool wiring, and whatever
framework drives it.
_Avoid_: agent (ambiguous between the model, the loop, and the whole system), bot

**Reference Harness**:
The deliberately plain Harness built for this sandbox, used to demonstrate the evaluation and
as a point of comparison for other Harnesses.
_Avoid_: our agent, default agent

### Captioning

**Chip**:
A fixed-size image tile of one place on one date: the unit a Caption describes.
_Avoid_: tile, patch, image

**Chip Pair**:
Two Chips of the same place on different dates.
_Avoid_: image pair, before/after

**Fixed Case**:
A caption-generation Case built on one Chip.
_Avoid_: single-image task

**Change Case**:
A caption-generation Case built on a Chip Pair; its Caption describes what changed.
_Avoid_: change task, temporal case

**Caption**:
The generated description of a Chip or Chip Pair: free text together with the Claims it makes.
_Avoid_: label (ambiguous with Reference Label), description

**Reference Caption**:
A human-written description of an image, used as a reference for judging and retrieving Captions.
_Avoid_: ground-truth caption, gold caption, human label

**Claim**:
One checkable statement inside a Caption, such as an object, its count, its position, or its
relation to another object.
_Avoid_: assertion, fact

**Reference Label**:
A known fact about a Chip, taken from an Answer Key, that a Caption is graded against.
_Avoid_: label (ambiguous with Caption), ground truth, annotation

**Answer Key**:
The dataset Reference Labels come from.
_Avoid_: ground truth dataset, reference set

**Caption Set**:
A collection of Captions from one source, such as one of Clay's caption pipelines, scored together
to judge how far the source can be trusted.
_Avoid_: caption dataset, caption corpus

**Object Class**:
A kind of thing a Claim can name, such as a solar array or a road, with its place in the Object
Ontology.
_Avoid_: object type, category, label

**Object Ontology**:
The set of Object Classes, how they relate (which class is a kind of which), and how each maps to
Answer Keys, benchmarks, and the words people use for it.
_Avoid_: taxonomy, vocabulary, class list

### Observing

**Run**:
One execution of a Harness on a Case.
_Avoid_: execution, session, attempt

**Trace**:
The complete, ordered record of one Run, holding everything needed to judge it later without
running it again.
_Avoid_: log, transcript, span tree (an exported span tree is a lossy view of a Trace, not the
Trace)

**Step**:
One entry in a Trace: either a model turn or a tool call.
_Avoid_: event, span, action

**Soft Failure**:
A tool call that reports success but whose response says it failed.
_Avoid_: silent error, hidden failure

**Harness Fault**:
A failed tool call caused by the system under test, such as asking for a dataset that doesn't
exist or guessing a file name.
_Avoid_: agent error, harness error

**Environment Fault**:
A failed tool call caused by something outside the Harness's control, such as the network,
certificate interception, or missing access.
_Avoid_: infrastructure error, external error

**Sandbox Failure**:
The evaluation machinery itself failed during a Run, so the Run has no valid score.
_Avoid_: harness error (it reads as a fault of the system under test), crash

### Judging

**Workflow Score**:
How well the Harness worked during a Run, judged from its Trace alone.
_Avoid_: workflow signals, process score, trace score

**Output Score**:
How good the Run's final answer is, judged against a Rubric and the Case's expectations.
_Avoid_: output quality, answer score, accuracy

**Rubric**:
The criteria an Output Score is judged on, each with a weight and a description of what 0,
0.5, and 1 mean.
_Avoid_: scorecard, checklist

**Gate**:
A Rubric criterion whose score caps the Output Score, so failing it can't be outweighed by
doing well on the others.
_Avoid_: blocker, hard requirement

**Judge**:
The model that grades a Run's final answer against a Rubric, using the Trace as its evidence.
_Avoid_: grader, evaluator, scorer

**Expected Fact**:
A specific statement that a correct answer to a Case must make.
_Avoid_: ground truth, answer key

**Unsupported Claim**:
A specific claim in an answer that appears in no tool output in the Trace.
_Avoid_: hallucination (it may be true; it is only unbacked)

**Calibration Label**:
A person's blind score of a Run against the same Rubric the Judge used, for measuring how far
the Judge can be trusted.
_Avoid_: human score, annotation

### Comparing

**Batch**:
A set of Runs, several per Case, made under one fixed configuration.
_Avoid_: experiment, suite

**Repeat**:
One of the several Runs of the same Case within a Batch.
_Avoid_: trial, iteration

**Spread**:
How much a Case's scores vary across the Repeats in a Batch.
_Avoid_: noise, variance (as a loose word)

**Baseline**:
The accepted Batch that later changes are measured against.
_Avoid_: reference batch, golden run

**Story**:
A recorded Run picked to demonstrate one point about the evaluation, with a note saying what it
shows.
_Avoid_: example, showcase
