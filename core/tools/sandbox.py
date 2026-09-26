"""
core/tools/sandbox.py — Isolated Docker sandbox for the interactive app.

Injects code via an in-memory tar archive, runs it inside a resource-capped
container with networking disabled, and force-removes the container on exit
regardless of outcome.

Scope: this sandbox executes *standalone* generated code for the web
application. It is deliberately not used for benchmark runs, where the agent
must act on a real repository with project dependencies installed — see
``eval/instance_env.py``. Using this image for SWE-bench tasks was the reason
earlier benchmark runs produced import errors instead of test results.

The image must already contain pytest. The previous version attempted
``pip install pytest`` inside a container created with
``network_disabled=True``, which cannot succeed; the resulting
"No module named pytest" was then surfaced as though it were a test failure.
Availability is now checked up front and reported as an environment problem.
Override the image with ``SANDBOX_IMAGE``.
"""

import io
import logging
import os
import tarfile
from typing import Tuple

import docker
import docker.errors

logger = logging.getLogger(__name__)


class DockerSandbox:
    def __init__(self) -> None:
        self.client  = docker.from_env()
        # Build with: docker build -f Dockerfile.sandbox -t agentforge-sandbox .
        self.image   = os.getenv("SANDBOX_IMAGE", "agentforge-sandbox:latest")
        self.timeout = int(os.getenv("SANDBOX_TIMEOUT", "30"))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_tar(filename: str, content: str) -> bytes:
        """Return an in-memory tar archive containing *content* as *filename*."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            encoded = content.encode("utf-8")
            info    = tarfile.TarInfo(name=filename)
            info.size = len(encoded)
            tar.addfile(info, io.BytesIO(encoded))
        return buf.getvalue()

    def _copy_to_container(
        self,
        container,
        filename: str,
        content: str,
        dest_dir: str = "/tmp",
    ) -> None:
        """Write generated content directly into the container."""
        import base64

        data = base64.b64encode(content.encode("utf-8")).decode("ascii")

        safe_dir = dest_dir.rstrip("/")
        safe_file = filename.lstrip("/")

        # Create parent directories for nested generated files.
        # Example: backend/database.py -> /tmp/backend/database.py
        parent_dir = f"{safe_dir}/{safe_file.rsplit("/", 1)[0]}" if "/" in safe_file else safe_dir

        mkdir_command = f"mkdir -p {parent_dir}"
        result = container.exec_run(["bash", "-c", mkdir_command])

        if result.exit_code != 0:
            raise RuntimeError(
                f"Failed to create directory {parent_dir}: "
                f"{result.output.decode(errors='replace')}"
            )

        command = (
            f"mkdir -p {safe_dir} && "
            f"echo {data} | base64 -d > "
            f"{safe_dir}/{safe_file}"
        )

        result = container.exec_run(
            ["bash", "-c", command],
            demux=False,
        )

        if result.exit_code != 0:
            output = (
                result.output.decode("utf-8", errors="replace")
                if result.output
                else ""
            )
            raise RuntimeError(
                f"Failed to write {safe_dir}/{safe_file}: {output}"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_code(
        self,
        code: str,
        test_code: str = "",
        files: dict[str, str] | None = None,
        test_filename: str = "test_code.py",
    ) -> Tuple[str, str]:
        """
        Execute *code* inside a sandboxed container.

        If *test_code* is provided, pytest is run after the main script.
        Returns (stdout, stderr).
        """
        container = None
        try:
            container = self.client.containers.run(
                self.image,
                command="sleep 60",          # idle — code injected via exec_run
                detach=True,
                remove=False,
                mem_limit="512m",
                nano_cpus=500_000_000,       # 0.5 CPU
                pids_limit=64,
                network_disabled=True,
                tmpfs={"/workspace": "size=128m,exec"},
            )

            self._copy_to_container(container, "code.py", code, "/tmp")

            # Copy generated project files so tests can import them.
            if files:
                for filename, content in files.items():
                    self._copy_to_container(
                        container,
                        filename,
                        content,
                        "/tmp",
                    )

            # Install generated Python dependencies inside this same sandbox.
            # This must happen before pytest runs.
            if files and files.get("requirements.txt"):
                import base64
                import re

                requirements = files["requirements.txt"]

                # Validate requirements.txt before passing it to pip.
                # Reject obvious Python/Markdown/code content.
                invalid_lines = []

                for line_number, raw_line in enumerate(
                    requirements.splitlines(), 1
                ):
                    line = raw_line.strip()

                    if not line or line.startswith("#"):
                        continue

                    if (
                        line.startswith(("import ", "from "))
                        or "```" in line
                        or line.startswith(("#!", "<", "{", "["))
                        or not re.match(
                            r"^[A-Za-z0-9_.-]+"
                            r"(?:\[[A-Za-z0-9_, .-]+\])?"
                            r"(?:[<>=!~]=?\s*[A-Za-z0-9.*+!_-]+)?"
                            r"(?:\s*;.*)?$",
                            line,
                        )
                    ):
                        invalid_lines.append(
                            f"line {line_number}: {line}"
                        )

                if invalid_lines:
                    return (
                        "",
                        "Invalid requirements.txt generated:\n"
                        + "\n".join(invalid_lines[:20]),
                    )

                encoded = base64.b64encode(
                    requirements.encode("utf-8")
                ).decode("ascii")

                # Write requirements into the sandbox.
                write_requirements = (
                    f"echo {encoded} | base64 -d > /tmp/requirements.txt"
                )

                write_result = container.exec_run(
                    ["bash", "-c", write_requirements],
                    demux=False,
                )

                if write_result.exit_code != 0:
                    output = (
                        write_result.output.decode(
                            "utf-8",
                            errors="replace"
                        )
                        if write_result.output
                        else ""
                    )
                    return (
                        "",
                        "Could not prepare requirements.txt:\n" + output,
                    )

                # Check whether all requested packages are already
                # available in the sandbox image. The sandbox has
                # networking disabled, so avoid pip when possible.
                check_command = (
                    "python - <<'PY2'\n"
                    "import importlib.util\n"
                    "import re\n"
                    "missing = []\n"
                    "for raw in open('/tmp/requirements.txt'):\n"
                    "    line = raw.strip()\n"
                    "    if not line or line.startswith('#'):\n"
                    "        continue\n"
                    "    name = re.split(r'[<>=!~;\[]', line, 1)[0].strip()\n"
                    "    module = name.replace('-', '_')\n"
                    "    if not importlib.util.find_spec(module):\n"
                    "        missing.append(name)\n"
                    "if missing:\n"
                    "    print('MISSING:' + ','.join(missing))\n"
                    "else:\n"
                    "    print('ALL_INSTALLED')\n"
                    "PY2"
                )

                check_result = container.exec_run(
                    ["bash", "-c", check_command],
                    demux=False,
                )

                check_output = (
                    check_result.output.decode(
                        "utf-8",
                        errors="replace"
                    )
                    if check_result.output
                    else ""
                )

                if "ALL_INSTALLED" not in check_output:
                    # Dependencies are missing. Try pip, but give a
                    # clear error if the offline sandbox cannot install them.
                    install_command = (
                        "python -m pip install "
                        "--no-input "
                        "-r /tmp/requirements.txt"
                    )

                    install_result = container.exec_run(
                        ["bash", "-c", install_command],
                        demux=False,
                    )

                    if install_result.exit_code != 0:
                        output = (
                            install_result.output.decode(
                                "utf-8",
                                errors="replace"
                            )
                            if install_result.output
                            else ""
                        )
                        return (
                            "",
                            "Dependency installation failed. "
                            "The sandbox is offline and these dependencies "
                            "are not included in the sandbox image.\n"
                            + output,
                        )

            _, output = container.exec_run(
                "bash -c 'cd /tmp && python code.py'",
                demux=False,
            )
            stdout = output.decode("utf-8", errors="replace") if output else ""
            stderr = ""

            if test_code:
                probe, _ = container.exec_run("python -m pytest --version")
                if probe != 0:
                    return stdout, (
                        f"pytest is not installed in sandbox image "
                        f"{self.image!r}, and networking is disabled so it "
                        f"cannot be installed at run time. Set SANDBOX_IMAGE "
                        f"to an image that includes pytest."
                    )

                self._copy_to_container(container, test_filename, test_code, "/tmp")
                _, t_out = container.exec_run(
                    f"bash -c 'cd /tmp && python -m pytest {test_filename} -v --tb=short'",
                    demux=False,
                )
                pytest_output = (
                    t_out.decode("utf-8", errors="replace") if t_out else ""
                )
                stdout += f"\n\n--- pytest ---\n{pytest_output}"

            return stdout, stderr

        except docker.errors.DockerException as exc:
            return "", f"DockerException: {exc}"
        except Exception as exc:
            return "", str(exc)
        finally:
            if container:
                try:
                    container.remove(force=True)
                except Exception:
                    pass
