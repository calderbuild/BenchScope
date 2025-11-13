"""BenchScope 日志分析工具"""
from __future__ import annotations

import argparse
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

COLLECTOR_PATTERNS = {
    "arxiv": re.compile(r"arXiv采集完成,有效候选(?P<count>\d+)条"),
    "github": re.compile(r"GitHub采集完成,候选总数(?P<count>\d+)")
}

PREFILTER_PATTERN = re.compile(r"预筛选完成: 保留(?P<kept>\d+)条 \(过滤率(?P<rate>[0-9.]+)%\)")
SCORE_PATTERN = re.compile(r"评分完成: (?P<count>\d+)条")
ERROR_PATTERN = re.compile(r"\[ERROR\]|ERROR")


@dataclass
class LogStats:
    collectors: Counter
    prefilter: tuple[int, float] | None
    scored: int
    errors: list[str]


def parse_log_file(path: Path) -> LogStats:
    collectors = Counter()
    prefilter_stats: tuple[int, float] | None = None
    scored = 0
    errors: list[str] = []

    with path.open("r", encoding="utf-8", errors="ignore") as log_file:
        for line in log_file:
            line = line.strip()
            for name, pattern in COLLECTOR_PATTERNS.items():
                match = pattern.search(line)
                if match:
                    collectors[name] += int(match.group("count"))
            if "HuggingFace采集完成" in line:
                count = int(re.findall(r"候选数(\d+)", line)[0]) if re.findall(r"候选数(\d+)", line) else 0
                collectors["huggingface"] += count
            pre_match = PREFILTER_PATTERN.search(line)
            if pre_match:
                prefilter_stats = (int(pre_match.group("kept")), float(pre_match.group("rate")))
            score_match = SCORE_PATTERN.search(line)
            if score_match:
                scored = int(score_match.group("count"))
            if ERROR_PATTERN.search(line):
                errors.append(line)
    return LogStats(collectors=collectors, prefilter=prefilter_stats, scored=scored, errors=errors)


def generate_report(stats: LogStats) -> str:
    lines = ["BenchScope 日志摘要", "===================="]
    if stats.collectors:
        lines.append("采集统计：")
        for name, count in stats.collectors.items():
            lines.append(f"- {name}: {count} 条")
    if stats.prefilter:
        kept, rate = stats.prefilter
        lines.append(f"预筛选：保留 {kept} 条 | 过滤率 {rate:.1f}%")
    if stats.scored:
        lines.append(f"评分完成：{stats.scored} 条")
    if stats.errors:
        lines.append("错误日志：")
        lines.extend(f"- {err}" for err in stats.errors[:5])
        if len(stats.errors) > 5:
            lines.append(f"... 其余 {len(stats.errors) - 5} 条错误见日志")
    else:
        lines.append("未检测到错误日志 ✅")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="BenchScope 日志分析器")
    parser.add_argument("log_path", help="日志文件路径")
    args = parser.parse_args()

    log_path = Path(args.log_path)
    if not log_path.exists():
        raise SystemExit(f"日志文件不存在: {log_path}")

    stats = parse_log_file(log_path)
    print(generate_report(stats))


if __name__ == "__main__":
    main()
