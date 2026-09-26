"""
core/agents/agents.py — All agent classes.

Agents:
    PlannerAgent   — converts a task into a structured JSON step plan
    CoderAgent     — generates new code or produces a unified diff
    TesterAgent    — writes pytest test cases
    DebuggerAgent  — fixes code given error output
    CriticAgent    — reviews results, returns PASS or FAIL
    MemoryAgent    — stores and retrieves past successful tasks (in-process)
"""

import json
import logging
import re
from typing import AsyncGenerator

from unidiff import PatchSet

from core.utils.llm import llm, llm_stream

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PlannerAgent
# ---------------------------------------------------------------------------

class PlannerAgent:
    SYSTEM = (
        "You are a senior software architect. "
        "Given a task, produce a JSON object with two keys:\n"
        "  'explanation': a one-sentence description of the approach\n"
        "  'steps': an array of objects, each with:\n"
        "    'agent': one of coder | tester | debugger | critic | tool\n"
        "    'description': what this step does\n"
        "    'file': (optional) path of the file to edit\n"
        "    'parallel_group': (optional) integer for independent steps that may run in parallel; dependent steps MUST use different groups. Coder must finish before Tester, and Tester must finish before Debugger.\n"
        "    'tool_name': (required if agent=tool) the tool to execute (e.g., git_clone, pip_install)\n"
        "    'tool_params': (required if agent=tool) parameters dict for the tool\n"
        "When decomposing the task, preserve ALL explicit user requirements "
        "in the relevant step descriptions. "
        "Do NOT omit exact numbers, filenames, function names, imports, "
        "testing frameworks, constraints, or required behavior. "
        "If the user says exactly N tests, the test step description MUST "
        "explicitly say exactly N tests. "
        "If the user requires a specific import, filename, or framework, "
        "preserve that requirement verbatim in the step. "
        "Do not replace precise requirements with vague summaries. "
        "Return ONLY valid JSON — no markdown fences, no extra text."
    )

    async def create_plan(
        self,
        task: str,
        memory_context: str,
        repo_context: str,
    ) -> dict:
        prompt = (
            f"Task: {task}\n\n"
            f"Memory context:\n{memory_context}\n\n"
            f"Repo context:\n{repo_context}\n\n"
            "Produce the plan now."
        )
        raw = await llm(prompt, system=self.SYSTEM, agent="planner")
        try:
            return json.loads(raw)
        except Exception:
            logger.warning("Planner returned non-JSON; using fallback plan.")
            return {
                "explanation": raw[:200],
                "steps": [{"agent": "coder", "description": task}],
            }


# ---------------------------------------------------------------------------
# CoderAgent
# ---------------------------------------------------------------------------

class CoderAgent:
    SYSTEM_NEW = (
        "You are an expert software engineer working on a multi-file software project. "
        "Generate the complete contents of the requested project file. "
        "Follow the user's task requirements exactly. "

        "PROJECT CONSISTENCY IS CRITICAL: "
        "The generated file must be fully compatible with the other files in the project. "
        "Before writing code, inspect the provided context files, previous results, and task requirements. "
        "Reuse the exact module paths, class names, function names, method names, field names, "
        "endpoint names, enum values, and data structures already established by other files. "
        "Never invent a different module path when an existing project structure is provided. "
        "Never rename an existing field or method unless the task explicitly requires it. "
        "If models, schemas, services, routes, workers, or tests refer to the same object, "
        "make sure their names and interfaces match exactly. "
        "If a required field or method is referenced by another file, ensure the generated file "
        "defines it with the expected name and compatible type. "
        "Do not create duplicate alternative implementations of the same component. "

        "FILE STRUCTURE RULES: "
        "Respect the exact project structure requested by the task. "
        "If the task specifies app/services.py, import from app.services. "
        "If the task specifies app/services/task_service.py, import from app.services.task_service. "
        "Do not invent additional directories or modules unless necessary. "

        "API AND DATA MODEL CONSISTENCY: "
        "Use the exact field names defined by the existing schemas and models. "
        "Keep request schemas, response schemas, database models, service methods, routes, "
        "workers, and tests consistent with each other. "
        "Do not use aliases such as type/task_type or retries/retry_count unless explicitly defined. "

        "TEST CONSISTENCY: "
        "If generating a test file, test the actual implementation from the project. "
        "Do not redefine or copy the implementation inside tests. "
        "Use the exact public interfaces exposed by the application. "
        "Before writing tests, inspect the models, schemas, services, routes, and main application "
        "available in the context and write tests against those exact interfaces. "
        "A requested test file must NEVER be empty, truncated, or replaced with placeholder code. "
        "Every requested test case must have a real pytest implementation. "
        "Include all required imports, fixtures, test database setup, client setup, and cleanup. "
        "If the task requests multiple test cases, implement every case explicitly. "
        "Do not write only test names or comments. "
        "Do not use pass, TODO, or placeholder assertions. "
        "If the task requests a specific number of tests, follow that requirement. "

        "CODE QUALITY: "
        "Write clean, well-structured, production-ready code. "
        "Use type hints where appropriate. "
        "Include all required imports. "
        "Do not leave required functionality as pass, TODO, or placeholder code. "
        "Avoid circular imports. "

        "IMPORTANT FILE-TYPE RULES: "
        "If generating requirements.txt, output ONLY valid pip package requirements, "
        "one package specification per line. "
        "Never put Python code, import statements, Markdown, README text, or explanations "
        "inside requirements.txt. "
        "If generating README.md, output valid Markdown. "
        "If generating JSON, YAML, TOML, Dockerfile, configuration, HTML, CSS, JavaScript, "
        "or another non-Python file, output valid content for that file type. "
        "Do NOT use Markdown code fences around the file contents. "
    )
    SYSTEM_DIFF = (
        "You are an expert at producing minimal unified diffs (git diff format). "
        "Return ONLY the diff inside ```diff ... ``` fences — no explanation."
    )

    def _build_prompt(
        self,
        subtask: str,
        context_files: list[str],
        previous_results: list[dict],
        memory: str,
        existing_code: str = "",
    ) -> str:
        ctx  = "\n".join(context_files)
        prev = "\n".join(r.get("output", "")[:300] for r in previous_results)
        if existing_code:
            return (
                f"Existing code:\n```python\n{existing_code}\n```\n\n"
                f"Task: {subtask}\n\n"
                f"Context files:\n{ctx}\n\n"
                f"Memory:\n{memory}\n\n"
                "Generate a unified diff that applies the required changes."
            )
        return (
            f"Task: {subtask}\n\n"
            f"Context files:\n{ctx}\n\n"
            f"Previous results:\n{prev}\n\n"
            f"Memory:\n{memory}\n\n"
            "Write the complete content required by the task. "
            "Follow the task literally and respect the requested file type. "
            "For requirements.txt, output only valid pip package requirements, "
            "one package per line, with no Python code, imports, Markdown, or explanations. "
            "For README.md, output valid Markdown. "
            "For configuration files, output valid syntax for that format. "
            "For source files, output valid source code for the requested language. "
            "If this subtask creates a test file, use the exact testing framework "
            "requested by the user, create exactly the requested number of tests, "
            "import the function/class from the source module, and never redefine "
            "the implementation inside the test file. "
            "Do not add extra tests unless the task asks for them."
        )

    async def generate_code(
        self,
        subtask: str,
        context_files: list[str],
        previous_results: list[dict],
        memory: str,
        existing_code: str = "",
    ) -> str:
        if existing_code and len(existing_code) > 100:
            diff_text = await llm(
                self._build_prompt(subtask, context_files, previous_results, memory, existing_code),
                system=self.SYSTEM_DIFF,
                agent="coder",
            )
            return self._apply_diff(existing_code, diff_text)
        prompt = self._build_prompt(subtask, context_files, previous_results, memory)
        return await llm(prompt, system=self.SYSTEM_NEW, agent="coder")

    async def stream_code(
        self,
        subtask: str,
        context_files: list[str],
        previous_results: list[dict],
        memory: str,
        existing_code: str = "",
    ) -> AsyncGenerator[str, None]:
        system = self.SYSTEM_NEW

        if existing_code:
            prompt = (
                f"Existing code:\n{existing_code}\n\n"
                f"Task: {subtask}\n\n"
                f"Context files:\n{chr(10).join(context_files)}\n\n"
                f"Previous results:\n"
                f"{chr(10).join(r.get('output', '')[:300] for r in previous_results)}\n\n"
                f"Memory:\n{memory}\n\n"
                "Return the COMPLETE updated Python file. "
                "Return ONLY raw Python code. "
                "Do NOT return a git diff. "
                "Do NOT use Markdown fences. "
                "Do NOT omit unchanged code."
            )
        else:
            prompt = self._build_prompt(
                subtask, context_files, previous_results, memory, ""
            )

        async for token in llm_stream(prompt, system=system, agent="coder"):
            yield token

    @staticmethod
    def _apply_diff(original_code: str, diff_text: str) -> str:
        """
        Apply a unified diff produced by the LLM to *original_code*.

        The previous implementation had two defects that silently corrupted
        multi-hunk patches. It reset its source cursor to line 0 for every
        hunk, so context lines were copied from the top of the file rather
        than from the hunk's own location; and it indexed each hunk by its
        original line numbers after earlier hunks had already changed the
        length of the buffer, so every hunk after the first landed at the
        wrong offset. Both produced plausible-looking but wrong output rather
        than an error.

        A hunk's replacement text is simply its target side — context plus
        added lines — so it is taken directly from the hunk, and a running
        offset accounts for length changes made by preceding hunks.
        """
        match = re.search(r"```diff\s*(.*?)```", diff_text, re.DOTALL)
        raw_diff = match.group(1).strip() if match else diff_text.strip()
        if not raw_diff:
            return original_code

        try:
            patch = PatchSet(raw_diff)
        except Exception as exc:
            logger.warning("Could not parse diff (%s); returning original.", exc)
            return original_code

        lines = original_code.splitlines(keepends=True)
        offset = 0
        applied = 0

        try:
            for patched_file in patch:
                for hunk in patched_file:
                    start = hunk.source_start - 1 + offset
                    end = start + hunk.source_length
                    if start < 0 or end > len(lines):
                        raise IndexError(
                            f"hunk at source line {hunk.source_start} does not "
                            f"fit a {len(lines)}-line file"
                        )
                    # unidiff keeps the line ending in ``value``.
                    replacement = [
                        line.value for line in hunk
                        if line.is_context or line.is_added
                    ]
                    lines[start:end] = replacement
                    offset += len(replacement) - hunk.source_length
                    applied += 1
        except Exception as exc:
            logger.warning("Diff application failed (%s); returning original.", exc)
            return original_code

        return "".join(lines) if applied else original_code


# ---------------------------------------------------------------------------
# TesterAgent
# ---------------------------------------------------------------------------

class TesterAgent:
    SYSTEM = (
        "You are an expert software tester. "
        "Generate tests that follow the user's task requirements EXACTLY. "
        "If the task specifies an exact number of tests, generate exactly that "
        "number of test methods and no additional tests. "
        "Use the testing framework requested by the user. "
        "When testing a module, import the functions from the module under test. "
        "NEVER redefine the function being tested inside the test file. "
        "Return ONLY valid Python code. "
        "Do NOT use Markdown fences. "
        "Do NOT include explanations."
    )

    async def generate_tests(self, code: str, subtask: str) -> str:
        prompt = (
            f"Source code to test:\n```python\n{code}\n```\n\n"
            f"Task description:\n{subtask}\n\n"
            "Generate the COMPLETE test file. "
            "Follow the task description literally. "
            "If it says exactly 3 tests, create exactly 3 test methods. "
            "Do not add extra tests for edge cases unless requested. "
            "If the source file is named in the task, import the required "
            "function from that source module. "
            "Do NOT redefine or copy the implementation into the test file. "
            "Use the exact testing framework requested by the user. "
            "Return ONLY raw Python code."
        )
        return await llm(prompt, system=self.SYSTEM, agent="tester")


# ---------------------------------------------------------------------------
# DebuggerAgent
# ---------------------------------------------------------------------------

class DebuggerAgent:
    SYSTEM = (
        "You are an expert debugger. "
        "Given code and an error message, return a fixed version of the code. "
        "Return ONLY raw Python code. "
        "Do NOT use Markdown code fences. "
        "Do NOT include ```python or ``` anywhere in the response. "
        "Do NOT include explanations."
    )

    async def fix(self, code: str, error: str) -> str:
        prompt = (
            f"Code:\n```python\n{code}\n```\n\n"
            f"Error:\n{error}\n\n"
            "Fix the code. "
            "Return the COMPLETE corrected Python file as raw Python code only. "
            "Do NOT use Markdown fences. "
            "Do NOT return a diff. "
            "Do NOT omit unchanged code."
        )

        fixed = await llm(prompt, system=self.SYSTEM, agent="debugger")

        # Defensive cleanup if the model still returns Markdown fences.
        fixed = fixed.strip()

        if fixed.startswith("```python"):
            fixed = fixed[len("```python"):].lstrip("\n")
        elif fixed.startswith("```"):
            fixed = fixed[3:].lstrip("\n")

        if fixed.endswith("```"):
            fixed = fixed[:-3].rstrip()

        return fixed


# ---------------------------------------------------------------------------
# CriticAgent
# ---------------------------------------------------------------------------

class CriticAgent:
    SYSTEM = (
        "You are a senior code reviewer evaluating an AI coding pipeline. "
        "The Pipeline results contain the ACTUAL generated code and test output. "
        "Read the provided output literally. "
        "Do NOT replace code with placeholders such as <complete code>, "
        "<complete test file>, or similar descriptions. "
        "Do NOT claim that code is missing unless the provided pipeline results "
        "actually contain no implementation. "
        "If the implementation and tests are complete and correct, reply exactly "
        "'PASS'. Otherwise reply 'FAIL: <specific reason>'."
    )

    async def review(self, results: list[dict], task: str) -> str:
        summary = "\n".join(
            f"[{r.get('type', '?')}] {r.get('step', '')}: "
            f"{str(r.get('output', ''))}"
            for r in results
        )
        prompt = f"Original task: {task}\n\nPipeline results:\n{summary}"
        return await llm(prompt, system=self.SYSTEM, agent="critic")


# ---------------------------------------------------------------------------
# MemoryAgent
# ---------------------------------------------------------------------------

class MemoryAgent:
    """
    In-process short-term memory store.
    Swap retrieve() for a ChromaDB vector query for persistent cross-session memory.
    """

    def __init__(self) -> None:
        self._store: list[dict] = []

    def store(self, task: str, result: str) -> None:
        self._store.append({"task": task, "result": result})
        self._store = self._store[-20:]       # keep last 20 entries

    def retrieve(self, query: str, top_k: int = 3) -> str:
        query_lower = query.lower()
        hits = [
            e for e in self._store
            if any(w in e["task"].lower() for w in query_lower.split())
        ]
        return "\n".join(e["result"][:300] for e in hits[:top_k])
