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
}


def get_language(key):
    lang = LANGUAGES.get(key)
    if lang is None:
        raise KeyError("unsupported language: %r" % key)
    return lang
