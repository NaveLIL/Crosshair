"""Small stdlib QMP client used by PXA reference tests; no hardware access."""
import json
import socket
import time


def connect(path, process, timeout=5):
    deadline = time.monotonic() + timeout
    while True:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(3)
        try:
            connection.connect(str(path))
            return connection
        except (FileNotFoundError, ConnectionRefusedError):
            connection.close()
            if process.poll() is not None:
                raise RuntimeError(f"QEMU exited {process.returncode} before socket connection")
            if time.monotonic() >= deadline:
                raise TimeoutError(f"QEMU socket timeout: {path.name}")
            time.sleep(0.02)


class Qmp:
    def __init__(self, path, process):
        self.socket = connect(path, process)
        self.stream = self.socket.makefile("rwb", buffering=0)
        if "QMP" not in self.receive():
            raise RuntimeError("missing QMP greeting")
        self.request("qmp_capabilities")

    def receive(self):
        line = self.stream.readline()
        if not line:
            raise RuntimeError("QMP closed before response")
        return json.loads(line)

    def request(self, name, arguments=None):
        message = {"execute": name}
        if arguments is not None:
            message["arguments"] = arguments
        self.stream.write(json.dumps(message).encode() + b"\n")
        while True:
            response = self.receive()
            if "error" in response:
                raise RuntimeError(response["error"])
            if "return" in response:
                return response["return"]

    def monitor(self, command):
        return self.request("human-monitor-command", {"command-line": command})

    def close(self):
        self.stream.close()
        self.socket.close()


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except Exception:
            process.kill()
            process.wait(timeout=3)
