"""Pinned on-device research plan selector for the Windows x64 trial."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sysconfig
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

from . import model_sandbox

ASSET_DIR = (
    Path(__file__).resolve().parent.parent / ".stockinsight" / "models" / "qwen2.5-0.5b"
)
REVISION = "9217f5db79a29953eb74d5343926648285ec7e67"
MODEL = "qwen2.5-0.5b-instruct-q4_k_m.gguf"
MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct-GGUF"
MODEL_HASH = "74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db"
MODEL_SIZE = 491_400_032
BUILD = "b12602"
ARCHIVE = f"llama-{BUILD}-bin-win-cpu-x64.zip"
ARCHIVE_HASH = "9957dab2f52e2599b85921ef3e2661287c1f3ad302bc0be07992e915cc6f7392"
ARCHIVE_SIZE = 25_012_065
PLAN_EXAMPLES = {
    "reported_figures": "How did operating cash flow compare year over year?",
    "market_context": "Did the stock sell off after earnings despite beating estimates?",
    "issuer_disclosure": "What did the company disclose in its filing about management guidance?",
    "disclosure": "What details did the company disclose in its official release?",
    "expectations": "How did actual quarterly results compare to prior market expectations?",
    "exposure": "Through what channel does this change affect the watched business?",
}


class LocalModelError(ValueError):
    pass


def _sha(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _download(name, url, size, digest):
    target = ASSET_DIR / name
    if target.exists():
        if target.stat().st_size != size or _sha(target) != digest:
            raise LocalModelError(f"Existing {name} differs from the pinned release.")
        return
    with tempfile.NamedTemporaryFile(
        dir=ASSET_DIR, delete=False, suffix=".part"
    ) as dest:
        temp = Path(dest.name)
    try:
        with urllib.request.urlopen(url, timeout=90) as stream, temp.open("wb") as dest:
            total = 0
            while block := stream.read(1024 * 1024):
                total += len(block)
                if total > size:
                    raise LocalModelError(f"{name} is larger than the pinned release.")
                dest.write(block)
        if total != size or _sha(temp) != digest:
            raise LocalModelError(
                f"{name} failed release size or SHA-256 verification."
            )
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)


def install():
    if sysconfig.get_platform() != "win-amd64":
        raise LocalModelError("This provisioning command supports Windows x64.")
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    _download(
        ARCHIVE,
        f"https://github.com/ggml-org/llama.cpp/releases/download/{BUILD}/{ARCHIVE}",
        ARCHIVE_SIZE,
        ARCHIVE_HASH,
    )
    _download(
        MODEL,
        f"https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/{MODEL}",
        MODEL_SIZE,
        MODEL_HASH,
    )


def available() -> bool:
    """Cheap installation check. Exact bytes are verified before inference."""
    if sysconfig.get_platform() != "win-amd64":
        return False
    try:
        return (ASSET_DIR / ARCHIVE).stat().st_size == ARCHIVE_SIZE and (
            ASSET_DIR / MODEL
        ).stat().st_size == MODEL_SIZE
    except OSError:
        return False


def _unpack_runtime(dest):
    # Use only pinned inference components. Each invocation gets its own DLL
    # search directory; concurrently running selector processes share no files.
    libraries = {
        "llama-completion.exe",
        "llama-completion-impl.dll",
        "llama-common.dll",
        "llama.dll",
        "ggml.dll",
        "ggml-base.dll",
        "libomp.dll",
        "mtmd.dll",
    }
    with zipfile.ZipFile(ASSET_DIR / ARCHIVE) as release:
        for member in release.namelist():
            if member in libraries or re.fullmatch(r"ggml-cpu-[a-z0-9]+\.dll", member):
                with release.open(member) as source, (dest / member).open("xb") as out:
                    shutil.copyfileobj(source, out)


def choose(question: str, candidates: dict[str, str]) -> tuple[str, dict]:
    """Generate one grammar-constrained plan choice on the local CPU."""
    if not isinstance(question, str) or not question.strip() or len(question) > 2_000:
        raise LocalModelError(
            "The local selector accepts a question of up to 2,000 characters."
        )
    if not isinstance(candidates, dict) or not 2 <= len(candidates) <= 8:
        raise LocalModelError(
            "Provide two to eight distinct application research plans."
        )
    entries = list(candidates.items())
    if any(
        not isinstance(key, str)
        or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key)
        or not isinstance(desc, str)
        or not desc.strip()
        or len(desc) > 240
        for key, desc in entries
    ):
        raise LocalModelError("Invalid application research plan.")
    if not available():
        raise LocalModelError(
            "Install the Windows CPU assets with python -m stockinsight.local_model install."
        )

    # A completion-style worked example per candidate gives this small
    # instruction model the assignment and the exact output vocabulary.
    examples = "\n".join(
        f"{PLAN_EXAMPLES.get(key, desc)} -> {key}" for key, desc in entries
    )
    question_line = " ".join(question.split()).replace("<", "‹").replace(">", "›")
    prompt = f"Examples of categories:\n{examples}\nQuestion: {question_line} ->"
    grammar = "root ::= " + " | ".join(json.dumps(key) for key in candidates)
    started = time.monotonic()
    try:
        if _sha(ASSET_DIR / ARCHIVE) != ARCHIVE_HASH:
            raise LocalModelError("Local inference assets failed SHA-256 verification.")
        with tempfile.TemporaryDirectory(dir=ASSET_DIR) as temp:
            work = Path(temp)
            _unpack_runtime(work)
            # The private package SID is granted access to this run only, never
            # the assets directory, original weights or workspace.
            shutil.copyfile(ASSET_DIR / MODEL, work / MODEL)
            if _sha(work / MODEL) != MODEL_HASH:
                raise LocalModelError(
                    "Local inference assets failed SHA-256 verification."
                )
            # No remote model host, inherited tokens, broker configuration or
            # operator-defined llama.cpp flags. The model emits one plan ID.
            system_root = os.environ["SystemRoot"]
            env = {
                "SystemRoot": system_root,
                "PATH": str(Path(system_root) / "System32"),
                "TEMP": temp,
                "TMP": temp,
            }
            prompt_file = work / "question.txt"
            prompt_file.write_text(prompt, encoding="utf-8")
            command = [
                str(work / "llama-completion.exe"),
                "--model",
                str(work / MODEL),
                "--offline",
                "--gpu-layers",
                "0",
                "--ctx-size",
                "4096",
                "--threads",
                "4",
                "--no-conversation",
                "--no-warmup",
                "--no-display-prompt",
                "--no-escape",
                "--color",
                "off",
                "--seed",
                "1",
                "--temperature",
                "0",
                "--n-predict",
                "70",
                "--grammar",
                grammar,
                "--file",
                str(prompt_file),
            ]
            result = model_sandbox.run(command, cwd=work, env=env, timeout=60)
            if result.returncode:
                raise LocalModelError(
                    f"The isolated CPU runtime exited with code 0x{result.returncode:08x}."
                )
            selected = (
                result.stdout.decode("ascii").strip().removesuffix(" [end of text]")
            )
            if selected not in candidates:
                raise LocalModelError(
                    "The local model did not return a permitted research method."
                )
    except (
        OSError,
        KeyError,
        UnicodeError,
        subprocess.TimeoutExpired,
        zipfile.BadZipFile,
    ) as exc:
        raise LocalModelError(
            "The verified Windows CPU model could not complete its selection."
        ) from exc
    return selected, {
        "mode": "on_device_model",
        "actual_model": MODEL_ID,
        "model_revision": REVISION,
        "model_sha256": MODEL_HASH,
        "runtime": "llama.cpp",
        "runtime_version": BUILD,
        "runtime_sha256": ARCHIVE_HASH,
        "device": "CPU",
        "isolation": "windows_appcontainer_no_capabilities",
        "billing_mode": "local_no_provider",
        "selected_plan": selected,
        "candidate_plans": list(candidates),
        "max_output_tokens": 70,
        "local_inferences": 1,
        "temperature": 0,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }


def verify():
    """Exercise the installed weights and the application's actual method menu."""
    from .local_research import PLANS

    questions = {
        "How much did revenue grow between fiscal Q1 and Q2?": "reported_figures",
        "Why did the stock price fall after results?": "market_context",
        "What risk qualifications appear in the company press release?": "issuer_disclosure",
    }
    results = []
    for question, expected in questions.items():
        choice, metadata = choose(question, PLANS)
        results.append(
            {
                "question": question,
                "selected": choice,
                "expected": expected,
                "matched": choice == expected,
                "elapsed_ms": metadata["elapsed_ms"],
            }
        )
    return {
        "model": MODEL_ID,
        "model_sha256": MODEL_HASH,
        "runtime_version": BUILD,
        "device": "CPU",
        "passed": all(r["matched"] for r in results),
        "results": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "verify"))
    args = parser.parse_args()
    try:
        if args.action == "install":
            install()
            print(f"Verified Windows CPU assets in {ASSET_DIR}")
        else:
            report = verify()
            print(json.dumps(report, indent=2))
            raise SystemExit(0 if report["passed"] else 1)
    except (OSError, LocalModelError) as exc:
        parser.exit(1, f"{exc}\n")
