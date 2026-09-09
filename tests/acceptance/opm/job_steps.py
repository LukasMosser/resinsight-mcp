"""Run, reconnect, and cancel jobs only through the public tool catalog."""

import asyncio
import time
from dataclasses import dataclass, field

from public_client import PublicClient, Record, TrialFailure, write

TERMINAL = {"succeeded", "failed", "canceled", "unknown"}
LIMITS = {"cpu_count": 2, "memory_mib": 2048, "wall_time_seconds": 60}


def reference(job: Record) -> Record:
    return {"session_id": job["model"]["session_id"], "job_id": job["job_id"]}


@dataclass
class Jobs:
    known: dict[str, Record] = field(default_factory=dict)

    async def submit(
        self, api: PublicClient, label: str, prepared: Record, *, long: bool = False
    ) -> Record:
        limits = LIMITS | {"cpu_count": 1} if long else LIMITS
        job = await api.call(
            "job_submit", {"prepared": prepared, "limits": limits, "resource_policy": "enforce"}
        )
        self.known[job["job_id"]] = job
        api.evidence.check(f"{label}-job-lineage", job["model"] == prepared["revision"]["model"])
        write(api.evidence.output / f"{label}-submitted.json", job)
        return job

    async def poll(self, api: PublicClient, job: Record, *, running: bool = False) -> Record:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            current = await api.call("job_poll", reference(job))
            self.known[current["job_id"]] = current
            if running and current["state"] == "running" and current["container_id"]:
                return current
            if current["state"] in TERMINAL:
                if running:
                    raise TrialFailure("The long job stopped before disconnect acceptance.")
                return current
            await asyncio.sleep(0.2)
        raise TrialFailure("The public job did not reach its required state within 90 seconds.")

    async def run(self, api: PublicClient, label: str, prepared: Record) -> tuple[Record, Record]:
        job = await self.poll(api, await self.submit(api, label, prepared))
        api.evidence.check(
            f"{label}-successful-execution", job["state"] == "succeeded" and job["exit_code"] == 0
        )
        result = await api.call("opm_collect", reference(job))
        api.evidence.check(
            f"{label}-accepted-result",
            result["model"] == job["model"]
            and result["job_id"] == job["job_id"]
            and result["assessment"] == "accepted"
            and {item["role"] for item in result["manifest"]["outputs"]}
            == {"EGRID", "INIT", "UNRST", "SMSPEC", "UNSMRY"},
        )
        repeated = await api.call("opm_collect", reference(job))
        api.evidence.check(f"{label}-stable-collection", repeated == result)
        write(api.evidence.output / f"{label}-job.json", job)
        write(api.evidence.output / f"{label}-result.json", result)
        return job, result

    async def cancel(self, api: PublicClient, job: Record) -> Record:
        await api.call("job_cancel", reference(job))
        final = await self.poll(api, job)
        api.evidence.check(
            "owned-job-canceled", final["state"] == "canceled" and final["termination_confirmed"]
        )
        await api.call("opm_collect", reference(final), failure="invalid_model")
        return final

    async def cleanup(self, api: PublicClient) -> None:
        unresolved: list[Record] = []
        for job in tuple(self.known.values()):
            try:
                current = await api.call("job_poll", reference(job))
                self.known[current["job_id"]] = current
                if current["state"] not in {"succeeded", "failed", "canceled"}:
                    await api.call("job_cancel", reference(current))
                    current = await self.poll(api, current)
                self.known[current["job_id"]] = current
                api.evidence.check(
                    f"cleanup-job-{current['job_id']}",
                    current["state"] in {"succeeded", "failed", "canceled"}
                    and current["exit_code"] is not None,
                )
            except Exception as error:
                unresolved.append(
                    {
                        "reference": reference(job),
                        "last_known_job": self.known[job["job_id"]],
                        "error": str(error),
                    }
                )
        write(
            api.evidence.output / "normal-job-cleanup.json",
            {
                "jobs": list(self.known.values()),
                "unresolved": unresolved,
                "containers_retained": True,
                "reason": "Public tools confirm termination but do not expose container removal.",
            },
        )
        if unresolved:
            identities = ", ".join(item["reference"]["job_id"] for item in unresolved)
            raise TrialFailure(f"Public job cleanup remains unresolved: {identities}.")
