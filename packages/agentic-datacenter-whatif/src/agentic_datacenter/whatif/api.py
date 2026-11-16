"""The what-if job API (ADR 0019, decision 10).

A FastAPI router that a host mounts: a request is validated at once, queued,
and played on one worker thread, because REMORA's embedded service, its
simulated clock and its host registry are global to the process (ADR 0016).
A job id is the request hash and a sequence number, and the same request
always gives the same result. The router runs simulations only; it takes no
action on any plant, and serving it follows the bind rules of ADR 0009.
"""

from __future__ import annotations

import json
import queue
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse

from agentic_datacenter.core.profile import Profile
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.whatif.evidence import verify_whatif, write_whatif
from agentic_datacenter.whatif.models import Change, SpecError, WhatIfSpec, parse_spec
from agentic_datacenter.whatif.preflight import study
from agentic_datacenter.whatif.runner import GateFactory, run_whatif

PREFIX = "/api/v1/whatif"


@dataclass
class Job:
    """One what-if request and what has become of it."""

    id: str
    spec: WhatIfSpec
    status: str = "queued"
    error: str | None = None
    summary: dict[str, Any] | None = None
    series: dict[str, Any] | None = None
    policy: dict[str, Any] | None = None
    directory: Path | None = None
    done: threading.Event = field(default_factory=threading.Event)


class JobStore:
    """Holds the jobs and plays them one at a time on a worker thread."""

    def __init__(
        self,
        root: Path,
        profile: Profile,
        contracts: ContractLibrary,
        gates: Mapping[str, GateFactory] | None = None,
        commit: str = "unknown",
    ) -> None:
        """Keep evidence under *root*; play jobs on *profile* with *contracts*."""
        self.root, self.profile, self.contracts = root, profile, contracts
        self.gates, self.commit = gates, commit
        self._jobs: dict[str, Job] = {}
        self._queue: queue.Queue[Job | None] = queue.Queue()
        self._lock = threading.Lock()
        self._go = threading.Event()
        self._go.set()
        self._sequence = 0
        self._worker = threading.Thread(
            target=self._work, name="agentic-datacenter-whatif", daemon=True
        )
        self._worker.start()

    def submit(self, spec: WhatIfSpec) -> Job:
        """Queue *spec* and return its job.

        Raises:
            SpecError: If the change is not one a what-if can play.
        """
        study(spec.change, self.contracts)
        with self._lock:
            self._sequence += 1
            job = Job(f"wf-{spec.hash()[:12]}-{self._sequence:04d}", spec)
            self._jobs[job.id] = job
        self._queue.put(job)
        return job

    def get(self, job_id: str) -> Job | None:
        """Return a job by id."""
        with self._lock:
            return self._jobs.get(job_id)

    def _work(self) -> None:
        while True:
            job = self._queue.get()
            try:
                if job is None:
                    return
                self._go.wait()
                self._play(job)
            finally:
                self._queue.task_done()

    def _play(self, job: Job) -> None:
        job.status = "running"
        try:
            result = run_whatif(job.spec, self.profile, self.contracts, gates=self.gates)
            directory = write_whatif(
                result, self.root / job.id, self.profile, self.contracts, self.commit
            )
        except Exception as exc:  # a failed job is reported, never lost
            job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"
        else:
            job.summary, job.series, job.policy = result.summary(), result.series(), result.policy
            job.directory, job.status = directory, "done"
        job.done.set()

    def pause(self) -> None:
        """Hold the worker before its next job (for tests and maintenance)."""
        self._go.clear()

    def resume(self) -> None:
        """Let the worker go on."""
        self._go.set()

    def join(self) -> None:
        """Wait until every queued job has been played."""
        self._queue.join()

    def close(self) -> None:
        """Stop the worker after the jobs already queued."""
        self._go.set()
        self._queue.put(None)
        self._worker.join(timeout=60)


def _contract_view(contracts: ContractLibrary) -> list[dict[str, Any]]:
    out = []
    for contract_id in contracts.ids():
        contract = contracts.get(contract_id)
        assert contract is not None
        numbers = [name for name, a in contract.arguments.items() if a.type == "number"]
        if len(numbers) != 1:
            continue
        try:
            found = study(
                Change(contract_id=contract_id, argument=numbers[0], target=0.0), contracts
            )
        except SpecError:
            continue
        first = contract.writes[0]
        out.append({
            "id": contract.id, "title": contract.title, "argument": found.argument,
            "risk_tier": contract.risk_tier, "approval": contract.approval,
            "tags": list(found.tags),
            "bounds": first.bounds.model_dump(mode="json") if first.bounds else None,
            "limits": contract.limits.model_dump(mode="json", exclude_none=True),
            "premises": [p.expr for p in contract.premises],
            "rollback": contract.rollback is not None,
        })  # fmt: skip
    return out


def create_router(store: JobStore) -> APIRouter:
    """Return the router of the what-if job API, playing jobs on *store*."""
    router = APIRouter(prefix=PREFIX, tags=["whatif"])

    def finished(job_id: str) -> Job:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"no what-if job {job_id}")
        if job.status != "done":
            raise HTTPException(status_code=409, detail=f"job {job_id} is {job.status}")
        return job

    @router.post("/runs", status_code=202)
    def submit(request: dict[str, Any] = Body(...)) -> JSONResponse:  # noqa: B008
        try:
            job = store.submit(parse_spec(request))
        except SpecError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return JSONResponse({"id": job.id, "status": job.status}, status_code=202)

    @router.get("/runs/{job_id}")
    def status(job_id: str) -> dict[str, Any]:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"no what-if job {job_id}")
        return {
            "id": job.id, "status": job.status, "error": job.error,
            "request": job.spec.model_dump(mode="json"), "summary": job.summary,
        }  # fmt: skip

    @router.get("/runs/{job_id}/series")
    def series(job_id: str) -> dict[str, Any]:
        return finished(job_id).series or {}

    @router.get("/runs/{job_id}/policy")
    def policy(job_id: str) -> dict[str, Any]:
        return finished(job_id).policy or {}

    @router.get("/runs/{job_id}/evidence")
    def evidence(job_id: str) -> dict[str, Any]:
        job = finished(job_id)
        assert job.directory is not None
        manifest = json.loads((job.directory / "manifest.json").read_text(encoding="utf-8"))
        return {
            "directory": str(job.directory), "manifest": manifest,
            "problems": verify_whatif(job.directory),
        }  # fmt: skip

    @router.get("/contracts")
    def contracts() -> list[dict[str, Any]]:
        return _contract_view(store.contracts)

    return router
