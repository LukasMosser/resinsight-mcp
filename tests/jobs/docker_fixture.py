"""A separate command process models the Docker lifecycle for focused tests."""

import json
import sys
import time
from pathlib import Path

path = Path.cwd() / "container.json"
arguments = sys.argv[1:]
command = arguments[0]


def save(record: dict) -> None:
    path.write_text(json.dumps(record))


def read() -> dict:
    record = json.loads(path.read_text())
    state = record["State"]
    if state["Running"] and time.time() >= record["until"]:
        state.update(Running=False, Status="exited")
        save(record)
    return record


if command == "create":
    name = arguments[arguments.index("--name") + 1]
    label = arguments[arguments.index("--label") + 1]
    key, token = label.split("=", 1)
    image_index = next(index for index, value in enumerate(arguments) if "@sha256:" in value)
    settings = json.loads((Path.cwd() / "settings.json").read_text())
    save(
        {
            "Id": "a" * 64,
            "Name": f"/{name}",
            "Config": {"Image": arguments[image_index], "Labels": {key: token}},
            "State": {"Running": False, "Status": "created", "ExitCode": settings["exit_code"]},
            "duration": settings["duration"],
        }
    )
    print("a" * 64)
elif command == "container":
    if (Path.cwd() / "fail-inspect").exists():
        raise RuntimeError("The simulated Docker daemon is unavailable.")
    if arguments[1] == "ls":
        if path.exists():
            record = read()
            print(json.dumps({"ID": record["Id"], "Names": record["Name"].removeprefix("/")}))
    else:
        print(json.dumps([read()]))
elif command == "start":
    record = read()
    record["until"] = time.time() + record["duration"]
    record["State"].update(Running=True, Status="running")
    save(record)
    print(record["Id"])
elif command == "logs":
    print("The simulated program started.", flush=True)
    while read()["State"]["Running"]:
        time.sleep(0.02)
    print("The simulated program stopped.", flush=True)
elif command == "stop":
    record = read()
    record["State"].update(Running=False, Status="exited", ExitCode=137)
    save(record)
elif command == "rm":
    path.unlink()
else:
    raise RuntimeError(f"Unexpected Docker command: {arguments}")
