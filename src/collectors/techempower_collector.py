"""TechEmpower Web框架性能采集器"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

from src.common import constants
from src.config import Settings, get_settings
from src.models import RawCandidate

logger = logging.getLogger(__name__)


class TechEmpowerCollector:
    """抓取 TechEmpower Framework Benchmarks 最新一轮成绩"""

    TEST_TYPES: tuple[str, ...] = (
        "json",
        "db",
        "query",
        "cached-query",
        "fortune",
        "update",
        "plaintext",
    )
    RUNS_LIMIT = 3

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        cfg = self.settings.sources.techempower
        self.enabled = cfg.enabled
        self.base_url = (
            cfg.base_url.rstrip("/") if cfg.base_url else constants.TECHEMPOWER_BASE_URL
        )
        self.timeout = cfg.timeout_seconds
        self.min_composite_score = cfg.min_composite_score
        self.score_scale = constants.TECHEMPOWER_SCORE_SCALE

    async def collect(self) -> List[RawCandidate]:
        """采集候选项"""

        if not self.enabled:
            logger.info("TechEmpower采集器已禁用,跳过")
            return []

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                index_resp = await client.get(self.base_url)
                index_resp.raise_for_status()
                run_list = self._parse_runs(index_resp.text)
                if not run_list:
                    logger.warning("未获取到TechEmpower测试轮次")
                    return []

                candidates: List[RawCandidate] = []
                for run in run_list:
                    run_uuid = run["uuid"]
                    run_meta = await self._fetch_run_metadata(client, run_uuid)
                    if not run_meta:
                        logger.warning("TechEmpower运行元数据为空, uuid=%s", run_uuid)
                        continue

                    raw_payload = await self._fetch_raw_payload(client, run_meta)
                    if not raw_payload:
                        logger.warning("TechEmpower原始数据为空, uuid=%s", run_uuid)
                        continue

                    candidates.extend(
                        self._build_candidates(run, run_meta, raw_payload)
                    )
        except httpx.TimeoutException:
            logger.error("TechEmpower请求超时(>%ss)", self.timeout)
            return []
        except httpx.HTTPError as exc:
            logger.error("TechEmpower请求失败: %s", exc)
            return []
        except Exception as exc:  # noqa: BLE001
            logger.error("TechEmpower采集异常: %s", exc, exc_info=True)
            return []

        logger.info("TechEmpower采集完成,有效候选%d条", len(candidates))
        return candidates

    def _parse_runs(self, html: str) -> List[Dict[str, str]]:
        """从首页HTML解析最近几条测试记录"""

        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select("table.resultsTable tbody tr")[: self.RUNS_LIMIT]
        runs: List[Dict[str, str]] = []
        for row in rows:
            uuid_attr = row.get("data-uuid")
            if not uuid_attr:
                continue
            uuid = str(uuid_attr)

            cells = row.find_all("td")
            env_text = cells[0].get_text(" ", strip=True) if cells else ""
            stats_text = cells[1].get_text(" ", strip=True) if len(cells) > 1 else ""
            time_text = cells[2].get_text(" ", strip=True) if len(cells) > 2 else ""

            runs.append(
                {
                    "uuid": uuid,
                    "environment": env_text,
                    "stats": stats_text,
                    "time": time_text,
                }
            )

        return runs

    async def _fetch_run_metadata(
        self, client: httpx.AsyncClient, run_uuid: str
    ) -> Dict[str, Any] | None:
        """拉取运行基础元数据"""

        resp = await client.get(f"{self.base_url}/results/{run_uuid}.json")
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result") if isinstance(data, dict) else None
        if not result:
            return None
        result.setdefault("uuid", run_uuid)
        return result

    async def _fetch_raw_payload(
        self, client: httpx.AsyncClient, run_meta: Dict[str, Any]
    ) -> Dict[str, Any] | None:
        """下载完整的原始JSON数据"""

        raw_file = (run_meta.get("json") or {}).get("fileName")
        if not raw_file:
            logger.warning("TechEmpower运行缺少raw JSON文件名")
            return None

        raw_url = f"{self.base_url}/raw/{raw_file}"
        resp = await client.get(raw_url)
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, dict):
            return None
        return payload

    def _build_candidates(
        self,
        latest_run: Dict[str, str],
        run_meta: Dict[str, Any],
        payload: Dict[str, Any],
    ) -> List[RawCandidate]:
        """根据原始数据构造候选列表"""

        frameworks = payload.get("frameworks") or []
        raw_data = payload.get("rawData") or {}
        duration = max(payload.get("duration") or 0, 1)
        meta_entries = payload.get("testMetadata") or []
        meta_map = {
            entry.get("framework") or entry.get("project_name"): entry
            for entry in meta_entries
            if isinstance(entry, dict)
        }

        candidates: List[RawCandidate] = []
        for framework in frameworks:
            metrics_rps = self._extract_metrics(framework, raw_data, duration)
            if not metrics_rps:
                continue

            composite_score = self._compute_composite(metrics_rps)
            if composite_score < self.min_composite_score:
                continue

            metadata = self._build_metadata(
                framework,
                metrics_rps,
                composite_score,
                meta_map.get(framework, {}),
                run_meta,
                latest_run,
            )

            candidate = RawCandidate(
                title=f"TechEmpower Benchmark - {metadata.get('display_name', framework)}",
                url=f"{self.base_url}/results/{run_meta.get('uuid')}",
                source="techempower",
                abstract=self._build_description(framework, metadata, metrics_rps),
                publish_date=self._parse_run_datetime(run_meta.get("startTime")),
                raw_metadata=metadata,
            )
            candidates.append(candidate)

        # 高分优先，避免候选过多
        candidates.sort(
            key=lambda c: float(c.raw_metadata.get("composite_score", 0.0)),
            reverse=True,
        )
        return candidates

    def _extract_metrics(
        self, framework: str, raw_data: Dict[str, Any], duration: int
    ) -> Dict[str, float]:
        """提取每个测试维度的峰值吞吐 (req/s)"""

        metrics: Dict[str, float] = {}
        for test_type in self.TEST_TYPES:
            type_data = raw_data.get(test_type)
            if not isinstance(type_data, dict):
                continue
            records = type_data.get(framework)
            if not records:
                continue

            best_rps = 0.0
            for record in records:
                total = record.get("totalRequests")
                if not isinstance(total, (int, float)):
                    continue
                rps = float(total) / duration
                best_rps = max(best_rps, rps)
            if best_rps > 0:
                metrics[test_type] = best_rps

        return metrics

    def _compute_composite(self, metrics_rps: Dict[str, float]) -> float:
        """根据各测试维度计算缩放后的综合得分"""

        if not metrics_rps:
            return 0.0
        avg_rps = sum(metrics_rps.values()) / len(metrics_rps)
        return avg_rps / self.score_scale

    def _build_metadata(
        self,
        framework: str,
        metrics_rps: Dict[str, float],
        composite_score: float,
        meta_entry: Dict[str, Any],
        run_meta: Dict[str, Any],
        latest_run: Dict[str, str],
    ) -> Dict[str, str]:
        """组装飞书所需的raw_metadata"""

        metadata: Dict[str, str] = {
            "framework": framework,
            "display_name": str(meta_entry.get("display_name") or framework),
            "language": str(meta_entry.get("language") or "unknown"),
            "classification": str(meta_entry.get("classification") or ""),
            "approach": str(meta_entry.get("approach") or ""),
            "platform": str(meta_entry.get("platform") or ""),
            "database": str(meta_entry.get("database") or ""),
            "orm": str(meta_entry.get("orm") or ""),
            "notes": str(meta_entry.get("notes") or ""),
            "benchmark_name": str(
                run_meta.get("name") or latest_run.get("environment", "")
            ),
            "benchmark_date": str(
                run_meta.get("startTime") or latest_run.get("time", "")
            ),
            "environment": str(latest_run.get("environment", "")),
            "composite_score": f"{composite_score:.2f}",
        }

        for test_type, rps in metrics_rps.items():
            metadata[f"{test_type}_rps"] = f"{rps:.0f}"
            metadata[f"{test_type}_score"] = f"{rps / self.score_scale:.2f}"

        return metadata

    def _build_description(
        self, framework: str, metadata: Dict[str, str], metrics_rps: Dict[str, float]
    ) -> str:
        """生成简明描述"""

        language = metadata.get("language", "unknown").title()
        classification = metadata.get("classification", "").strip() or "未分类"
        approach = metadata.get("approach", "").strip() or "未注明"
        score = metadata.get("composite_score", "0")

        lines = [
            f"{framework} - {language} / {classification} / {approach}",
            f"综合得分: {score}",
            "性能指标 (k req/s):",
        ]

        for test_type in self.TEST_TYPES:
            rps = metrics_rps.get(test_type)
            if not rps:
                continue
            label = self._format_test_type(test_type)
            lines.append(f"- {label}: {rps / 1000:.1f}k")

        return "\n".join(lines)

    @staticmethod
    def _format_test_type(test_type: str) -> str:
        mapping = {
            "json": "JSON",
            "db": "单查询",
            "query": "多查询",
            "cached-query": "缓存查询",
            "fortune": "Fortune",
            "update": "更新",
            "plaintext": "Plaintext",
        }
        return mapping.get(test_type, test_type)

    @staticmethod
    def _parse_run_datetime(value: Any) -> Optional[datetime]:
        """解析官网提供的时间文本"""

        if not value:
            return None
        if isinstance(value, datetime):
            return value

        text = str(value).replace(" at ", " ")
        for fmt in ("%Y-%m-%d %I:%M %p", "%Y-%m-%d %H:%M %p"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return None
