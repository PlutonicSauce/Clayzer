"""Durable standalone AgentCore traces and cooperative execution deadlines."""

from __future__ import annotations

import time

from clayzer.trace import RunInfo, Step, Tracer, dumps

# Leave 300 seconds for the current bounded request, shutdown, and final S3 writes.
RUN_SECONDS = 600
CALL_RESERVE_SECONDS = 100


class RunFailure(RuntimeError):
    """A failed Run's public locator, without the underlying error or credentials."""

    def __init__(self, run: RunInfo, key: str, trace_saved: bool):
        super().__init__("caption run failed")
        self.details = {
            "run_id": run.run_id,
            "batch_id": run.batch_id,
            "trace_key": key,
            "status": run.status,
            "trace_saved": trace_saved,
        }


class RuntimeSink:
    """Checkpoints live outside scored Batches; unfinished snapshots have no run_end."""

    def __init__(self, store, key: str):
        self.store, self.key = store, key

    def write(self, run: RunInfo, steps: list[Step]) -> None:
        self.store.put(
            self.key,
            dumps(run, steps, final=run.ended_at is not None),
            "application/x-ndjson",
        )


class RuntimeTracer(Tracer):
    """Save run_start before work and each completed Step, including failed calls.

    Cooperative checks stop new calls before the budget is exhausted. An abrupt VM
    termination still leaves a readable `running` snapshot of the completed Steps;
    it cannot be misread as a successfully completed Run.
    """

    def __init__(self, run: RunInfo, sink: RuntimeSink, seconds: float = RUN_SECONDS):
        super().__init__(run, [sink])
        self.deadline = time.monotonic() + seconds
        self.sink = sink
        run.metadata["deadline_seconds"] = seconds

    def check_deadline(self) -> None:
        if time.monotonic() + CALL_RESERVE_SECONDS >= self.deadline:
            raise TimeoutError("caption Run reached its execution deadline")

    def checkpoint(self) -> None:
        self.sink.write(self.run, self.steps)

    def converse(self, *args, **kwargs):
        self.check_deadline()
        return super().converse(*args, **kwargs)

    def _add(self, *args, **kwargs) -> None:
        super()._add(*args, **kwargs)
        self.checkpoint()


class BoundedTools:
    """Bound each geospatial call and stop starting work near the Run deadline."""

    def __init__(self, box, tracer: RuntimeTracer):
        self.box, self.tracer, self.specs = box, tracer, box.specs

    def server_for(self, name: str) -> str | None:
        return self.box.server_for(name)

    def call(self, name: str, arguments: dict, timeout: float | None = None):
        self.tracer.check_deadline()
        return self.box.call(name, arguments, timeout=min(timeout or 30, 30))
