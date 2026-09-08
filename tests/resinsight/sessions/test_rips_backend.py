"""Exercise the native client against a separate process using the upstream protocol.

These tests establish the client boundary. They do not establish ResInsight acceptance.
"""

import argparse
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import grpc
import psutil
import pytest
import rips  # noqa: F401
from rips.generated import (
    App_pb2,
    App_pb2_grpc,
    Commands_pb2,
    Commands_pb2_grpc,
    Definitions_pb2,
    PdmObject_pb2,
    PdmObject_pb2_grpc,
    Project_pb2_grpc,
)

from resinsight_mcp.contracts.errors import ContractError, ErrorCode, MutationEffect
from resinsight_mcp.contracts.sessions import Endpoint, ObjectKind, ProcessIdentity
from resinsight_mcp.resinsight.sessions._rips import RipsApplication, RipsApplicationFactory


def _serve() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", type=int)
    parser.add_argument("--major", type=int, default=2026)
    parser.add_argument("--portnumberfile", type=Path)
    arguments = parser.parse_args()
    stopped = threading.Event()
    state = {"address": 100}

    class App(App_pb2_grpc.AppServicer):
        def GetVersion(self, request, context):
            return App_pb2.Version(major_version=arguments.major, minor_version=9)

        def Exit(self, request, context):
            threading.Timer(0.1, stopped.set).start()
            return Definitions_pb2.Empty()

    class Project(Project_pb2_grpc.ProjectServicer):
        def GetPdmObject(self, request, context):
            return PdmObject_pb2.PdmObject(class_keyword="Project", address=1)

    class Objects(PdmObject_pb2_grpc.PdmObjectServiceServicer):
        def GetDescendantPdmObjects(self, request, context):
            records = {
                "Reservoir": ("Reservoir", {"id": "7", "name": '"Case A"', "filePath": '"/a"'}),
                "View": ("View", {"id": "8"}),
                "WellPath": ("WellPath", {"name": '"Well A"'}),
            }
            kind, parameters = records[request.child_keyword]
            return PdmObject_pb2.PdmObjectArray(
                objects=[
                    PdmObject_pb2.PdmObject(
                        class_keyword=kind, address=state["address"], parameters=parameters
                    )
                ]
            )

    class Commands(Commands_pb2_grpc.CommandsServicer):
        def Execute(self, request, context):
            if request.HasField("openProject"):
                state["address"] += 1
                if request.openProject.path.endswith("delay"):
                    time.sleep(1)
                if request.openProject.path.endswith("error"):
                    context.abort(grpc.StatusCode.INTERNAL, "Read failed after closing project")
            return Commands_pb2.CommandReply()

    server = grpc.server(ThreadPoolExecutor(max_workers=4))
    App_pb2_grpc.add_AppServicer_to_server(App(), server)
    Project_pb2_grpc.add_ProjectServicer_to_server(Project(), server)
    PdmObject_pb2_grpc.add_PdmObjectServiceServicer_to_server(Objects(), server)
    Commands_pb2_grpc.add_CommandsServicer_to_server(Commands(), server)
    port = server.add_insecure_port(f"127.0.0.1:{arguments.server}")
    server.start()
    arguments.portnumberfile.write_text("")
    time.sleep(0.08)
    arguments.portnumberfile.write_text(str(port))
    print("Protocol fixture ready", flush=True)
    stopped.wait()
    server.stop(0).wait()


@pytest.fixture
def executable(tmp_path: Path) -> Path:
    script = tmp_path / "protocol-server"
    script.write_text(
        f"#!{sys.executable}\nimport runpy\n"
        f"runpy.run_path({str(Path(__file__).resolve())!r})['_serve']()\n"
    )
    script.chmod(0o700)
    return script


@pytest.fixture
def server_major() -> int:
    return 2026


@pytest.fixture
def endpoint(executable: Path, tmp_path: Path, server_major: int):
    port_file = tmp_path / "fixture.port"
    process = subprocess.Popen(
        [
            str(executable),
            "--server",
            "0",
            "--portnumberfile",
            str(port_file),
            "--major",
            str(server_major),
        ]
    )
    try:
        deadline = time.monotonic() + 10
        while not port_file.exists() or not port_file.read_text().strip():
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.02)
        yield Endpoint(port=int(port_file.read_text())), process
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)


def test_attach_observes_supported_objects_and_disconnect_preserves_process(endpoint, tmp_path):
    address, process = endpoint
    application = RipsApplicationFactory(tmp_path).attach(address)
    assert application.process.pid == process.pid
    snapshot = application.snapshot()
    assert snapshot.root_address == "1"
    assert {item.kind for item in snapshot.objects} == set(ObjectKind)
    case = next(item for item in snapshot.objects if item.kind == ObjectKind.CASE)
    assert case.name == "Case A"
    assert dict(case.attributes) == {"id": "7", "file_path": "/a"}
    application.open_project(tmp_path / "project.rsp")
    assert application.snapshot() != snapshot
    application.save_project(tmp_path / "saved.rsp")
    application.close_project()
    application.disconnect()
    assert process.poll() is None
    with pytest.raises(ContractError) as failure:
        application.snapshot()
    assert failure.value.error.code == ErrorCode.LOST_CONNECTION


def test_deadline_reports_uncertain_mutation_without_retry(endpoint, tmp_path):
    address, _ = endpoint
    application = RipsApplicationFactory(tmp_path, rpc_timeout=0.2).attach(address)
    try:
        with pytest.raises(ContractError) as failure:
            application.open_project(tmp_path / "delay")
        assert failure.value.error.code == ErrorCode.BUSY
        assert failure.value.error.effect == MutationEffect.UNKNOWN
        assert {item.address for item in application.snapshot().objects} == {"101"}
    finally:
        application.disconnect()


def test_remote_failure_does_not_claim_project_was_unchanged(endpoint, tmp_path):
    address, _ = endpoint
    application = RipsApplicationFactory(tmp_path).attach(address)
    try:
        with pytest.raises(ContractError) as failure:
            application.open_project(tmp_path / "error")
        assert failure.value.error.code == ErrorCode.EXECUTION_FAILED
        assert failure.value.error.effect == MutationEffect.UNKNOWN
    finally:
        application.disconnect()


def test_termination_confirms_process_exit(endpoint, tmp_path):
    address, process = endpoint
    application = RipsApplicationFactory(tmp_path).attach(address)
    application.terminate()
    application.disconnect()
    process.wait(timeout=5)
    assert not psutil.pid_exists(application.process.pid)


def test_unproved_process_identity_is_rejected(endpoint):
    address, process = endpoint
    with pytest.raises(ContractError) as failure:
        RipsApplication(address, ProcessIdentity(pid=process.pid, start_marker="0"), 1)
    assert failure.value.error.code == ErrorCode.LOST_CONNECTION
    assert failure.value.error.effect == MutationEffect.NOT_APPLIED
    assert process.poll() is None


@pytest.mark.parametrize("server_major", [2025])
def test_version_mismatch_refuses_attach_without_exiting(endpoint, tmp_path):
    address, process = endpoint
    with pytest.raises(ContractError) as failure:
        RipsApplicationFactory(tmp_path).attach(address)
    assert failure.value.error.code == ErrorCode.EXECUTION_FAILED
    assert failure.value.error.effect == MutationEffect.NOT_APPLIED
    assert process.poll() is None


def test_dead_process_does_not_return_previous_observations(endpoint, tmp_path):
    address, process = endpoint
    application = RipsApplicationFactory(tmp_path).attach(address)
    assert application.snapshot().objects
    process.terminate()
    process.wait(timeout=5)
    try:
        with pytest.raises(ContractError) as failure:
            application.snapshot()
        assert failure.value.error.code == ErrorCode.LOST_CONNECTION
    finally:
        application.disconnect()


def test_launch_records_host_identity_and_output(executable, tmp_path):
    application = RipsApplicationFactory(tmp_path / "logs").launch(executable)
    try:
        assert application.process.pid != os.getpid()
        assert application.verify_process() == application.process
        assert application.snapshot().objects
        assert "Protocol fixture ready" in next((tmp_path / "logs").glob("*.log")).read_text()
    finally:
        application.terminate()
        application.disconnect()
