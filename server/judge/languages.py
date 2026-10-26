from dataclasses import dataclass
from typing import Optional, Sequence

@dataclass(frozen=True)
class Language:
    key: str
    label:str
    image:str
    source_name:str
    run_cmd: Sequence[str]
    compile_cmd: Optional[Sequence[str]] = None
    default_memory_mb: int = 256
    compile_timeout_sec: int = 15

LANGUAGES = {
    "python": Language(
        key="python",
        label="Python 3.12",
        image="python:3.12-alpine",
        source_name="main.py",
        run_cmd=("python3", "-u", "/work/main.py"),
    ),
    "cpp": Language(
        key="cpp",
        label="C++17",
        image="gcc:13",
        source_name="main.cpp",
        compile_cmd=("g++", "-O2", "-std=c++17", "-o", "/work/main", "/work/main.cpp"),
        run_cmd=("/work/main",),
    ),
    "java": Language(
        key="java",
        label="Java 17",
        image="eclipse-temurin:17-jdk",
        source_name="Main.java",
        compile_cmd=("javac", "-d", "/work", "/work/Main.java"),
        run_cmd=("java", "-XX:+UseSerialGC", "-Xss64m", "-cp", "/work", "Main"),
        default_memory_mb=512,      # JVM overhead blows past 256m on its own
        compile_timeout_sec=25,
    ),
    "c": Language(
        key="c",
        label="C17",
        image="gcc:13",                 # already pulled for C++
        source_name="main.c",
        compile_cmd=("gcc", "-O2", "-std=c17", "-o", "/work/main",
                     "/work/main.c", "-lm"),
        run_cmd=("/work/main",),
    ),
    "javascript": Language(
        key="javascript",
        label="JavaScript (Node 22)",
        image="node:22-alpine",
        source_name="main.js",
        run_cmd=("node", "--stack-size=65500", "/work/main.js"),
        default_memory_mb=320,          # V8 reserves more than CPython does
    ),
    "go": Language(
        key="go",
        label="Go 1.23",
        image="golang:1.23-alpine",
        source_name="main.go",
        # GOCACHE must be writable and GOFLAGS must not reach for the
        # network: the sandbox has none.
        compile_cmd=("sh", "-c",
                     "GOCACHE=/tmp/gocache GOPATH=/tmp/gopath "
                     "CGO_ENABLED=0 GOFLAGS=-mod=mod "
                     "go build -o /work/main /work/main.go"),
        run_cmd=("/work/main",),
        compile_timeout_sec=30,       
    ),
    "rust": Language(
        key="rust",
        label="Rust 1.83",
        image="rust:1.83-slim",
        source_name="main.rs",
        compile_cmd=("rustc", "-O", "--edition", "2021",
                     "-o", "/work/main", "/work/main.rs"),
        run_cmd=("/work/main",),
        default_memory_mb=320,
        compile_timeout_sec=40,         # rustc is the slowest of the set
    ),
    "typescript": Language(
        key="typescript",
        label="TypeScript (Node 22)",
        image="node:22-alpine",
        source_name="main.ts",
        run_cmd=("node", "--experimental-strip-types", "/work/main.ts"),
        default_memory_mb=320,
    ),
}


def get_language(key):
    lang = LANGUAGES.get(key)
    if lang is None:
        raise KeyError("unsupported language: %r" % key)
    return lang
