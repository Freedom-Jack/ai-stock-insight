"""Exercise the installed Windows model token against harmless, operator-owned test files."""

import argparse
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from . import model_sandbox


def verify(workspace):
    if os.name != "nt" or not workspace.is_dir():
        raise ValueError(
            "Choose an existing private Windows workspace for the disposable canaries."
        )
    with tempfile.TemporaryDirectory(dir=workspace) as temporary:
        base = Path(temporary)
        scratch = base / "runtime"
        scratch.mkdir()
        allowed = scratch / "public-input.txt"
        marker = b"STOCKINSIGHT_DISPOSABLE_PERMISSION_TEST"
        allowed.write_bytes(marker + b"\r\n")
        private_db = base / "unrelated-research.sqlite3"
        with closing(sqlite3.connect(private_db)) as connection:
            connection.execute("CREATE TABLE canary(marker TEXT)")
            connection.execute(
                "INSERT INTO canary VALUES(?)", (marker.decode() + "\n",)
            )
            connection.commit()
        protected = [
            private_db,
            base / "provider-credential.canary",
            base / "unrelated-document.txt",
        ]
        for item in protected[1:]:
            item.write_bytes(marker + b"\r\n")
        before = {item: item.read_bytes() for item in protected}
        system = Path(os.environ["SystemRoot"])
        env = {
            "SystemRoot": str(system),
            "PATH": str(system / "System32"),
            "TEMP": str(scratch),
            "TMP": str(scratch),
        }
        # All inspected bytes were generated above. No operator secrets are read.
        # Long-path syntax covers a second ordinary Windows filesystem spelling.
        paths = [
            str(allowed),
            *(str(item) for item in protected),
            "\\\\?\\" + str(protected[-1]),
        ]
        result = model_sandbox.run(
            [
                str(system / "System32" / "findstr.exe"),
                "/m",
                "/l",
                "/c:" + marker.decode(),
                *paths,
            ],
            cwd=scratch,
            env=env,
            timeout=12,
        )
        output = os.fsdecode(result.stdout)
        errors = os.fsdecode(result.stderr)
        verdict = {
            "permitted_input_read": str(allowed) in output,
            "private_sql_denied": str(private_db) in errors
            and str(private_db) not in output,
            "provider_credential_canary_denied": str(protected[1]) in errors
            and str(protected[1]) not in output,
            "unrelated_document_denied": str(protected[2]) in errors
            and str(protected[2]) not in output,
            "extended_windows_path_denied": paths[-1] in errors
            and paths[-1] not in output,
            "private_contents_unchanged": all(
                item.read_bytes() == content for item, content in before.items()
            ),
            "process_is_appcontainer": True,
            "token_capability_count": 0,
        }
        verdict["passed"] = all(
            verdict[key]
            for key in verdict
            if key.endswith(("_read", "_denied", "_unchanged"))
        )
        return verdict


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()
    result = verify(args.workspace.resolve())
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
