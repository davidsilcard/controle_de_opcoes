"""Expose JUnit failures as GitHub annotations without requiring artifact download."""

from pathlib import Path
from xml.etree import ElementTree


def escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


if __name__ == "__main__":
    report = Path("pytest-results.xml")
    if report.exists():
        for case in ElementTree.parse(report).iter("testcase"):
            for failure in list(case):
                if failure.tag in {"failure", "error"}:
                    name = case.get("name", "pytest")
                    detail = (failure.text or failure.get("message", ""))[-5000:]
                    print(f"::error::{escape(name + chr(10) + detail)}")
