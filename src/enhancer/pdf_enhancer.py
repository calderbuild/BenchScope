"""arXiv PDF 深度解析增强器。

功能概览:
1. 下载 arXiv PDF 到本地缓存目录
2. 使用 scipdf_parser 解析 PDF 全文结构
3. 提取 Evaluation / Dataset / Baselines 等关键章节摘要
4. 提取作者与机构信息，补全 raw_institutions
5. 将解析结果写入 RawCandidate 的摘要与 raw_metadata，用于后续 LLM 评分
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import arxiv
import httpx
import requests
from bs4 import XMLParsedAsHTMLWarning
from scipdf.pdf import parse_pdf_to_dict  # type: ignore[import]

from src.common import constants
from src.models import RawCandidate

# 过滤 scipdf_parser 库的 XML 解析警告
# scipdf 内部使用 BeautifulSoup 的 HTML 解析器处理 XML，触发此警告
# 不影响功能，lxml 已安装但 scipdf 未正确使用
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PDFContent:
    """PDF 解析结果容器。"""

    title: str
    abstract: str  # 完整摘要（预期 500-1000 字）
    sections: dict[str, str]  # {"Introduction": "...", "Methods": "...", ...}
    authors_affiliations: list[tuple[str, str]]  # [("Alice Zhang", "Stanford University"), ...]
    references: list[str]  # 引用文献列表（原始字符串）
    evaluation_summary: Optional[str] = None  # Evaluation 部分摘要（最多 2000 字）
    dataset_summary: Optional[str] = None  # Dataset 部分摘要（最多 1000 字）
    baselines_summary: Optional[str] = None  # Baselines 部分摘要（最多 1000 字）
    introduction_summary: Optional[str] = None  # 引言摘要（最多 2000 字）
    method_summary: Optional[str] = None  # 方法/框架摘要（最多 3000 字）
    conclusion_summary: Optional[str] = None  # 结论/讨论摘要（最多 2000 字）
    extracted_github_url: Optional[str] = None  # 从PDF正文提取的GitHub链接
    extracted_dataset_url: Optional[str] = None  # 从PDF正文提取的数据集链接
    extracted_paper_url: Optional[str] = None  # 从PDF正文提取的论文链接


class PDFEnhancer:
    """arXiv PDF 深度解析增强器。

    使用场景：
    - 仅对 source == "arxiv" 的候选条目进行增强
    - 在规则预筛选之后调用，减少无效 PDF 下载

    降级策略：
    - 任一阶段失败（下载/解析/提取）时，返回原始 candidate，不影响主流程
    """

    def __init__(self, cache_dir: Optional[str] = None) -> None:
        """初始化 PDF 增强器。

        Args:
            cache_dir: PDF 缓存目录，默认使用 /tmp/arxiv_pdf_cache
        """
        # 使用本地缓存目录，避免重复下载同一篇论文
        self.cache_dir = Path(cache_dir or constants.ARXIV_PDF_CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # 自动判定 GROBID 服务：优先环境变量，其次本地探测，最后云端兜底
        self.grobid_url = self._resolve_grobid_url()

        logger.info(
            "PDFEnhancer 初始化完成，缓存目录: %s, GROBID服务: %s",
            self.cache_dir,
            self.grobid_url,
        )

    async def enhance_candidate(self, candidate: RawCandidate) -> RawCandidate:
        """增强单个候选项，仅处理 arXiv 来源。

        整体流程：
        1. 解析 URL 获取 arXiv ID
        2. 下载 PDF（带缓存）
        3. 解析 PDF 结构
        4. 合并解析结果到 RawCandidate
        """
        if candidate.source != "arxiv":
            return candidate

        arxiv_id = self._extract_arxiv_id(candidate.url or candidate.paper_url or "")
        if not arxiv_id:
            logger.warning("无法从 URL 中提取 arXiv ID: %s", candidate.url)
            return candidate

        try:
            pdf_path = await self._download_pdf(arxiv_id)
            if not pdf_path:
                return candidate

            pdf_content = await self._parse_pdf(pdf_path)
            if not pdf_content:
                return candidate

            enhanced = await self._merge_pdf_content(candidate, pdf_content)
            logger.info("PDF 增强成功: %s (%s)", candidate.title[:80], arxiv_id)
            return enhanced
        except Exception as exc:  # noqa: BLE001
            # 任何异常都不应中断主流程，而是降级为返回原始 candidate
            logger.error("PDF 增强失败 (%s): %s", arxiv_id, exc)
            return candidate

    async def enhance_batch(self, candidates: list[RawCandidate]) -> list[RawCandidate]:
        """批量增强候选项，默认采用受限并发。"""

        if not candidates:
            return []

        semaphore = asyncio.Semaphore(max(1, constants.PDF_ENHANCER_MAX_CONCURRENCY))
        results: list[Optional[RawCandidate]] = [None] * len(candidates)

        async def _enhance_with_lock(index: int, candidate: RawCandidate) -> None:
            async with semaphore:
                results[index] = await self.enhance_candidate(candidate)

        await asyncio.gather(
            *[_enhance_with_lock(idx, cand) for idx, cand in enumerate(candidates)]
        )

        return [
            item if item is not None else candidates[idx]
            for idx, item in enumerate(results)
        ]

    async def _download_pdf(self, arxiv_id: str) -> Optional[Path]:
        """下载 arXiv PDF（带缓存）。"""

        pdf_path = self.cache_dir / f"{arxiv_id}.pdf"

        if pdf_path.exists():
            logger.debug("命中 PDF 缓存: %s", arxiv_id)
            return pdf_path

        sdk_success = await self._download_via_arxiv_sdk(arxiv_id, pdf_path)
        if not sdk_success:
            http_success = await self._download_via_http(arxiv_id, pdf_path)
            if not http_success:
                return None

        if not pdf_path.exists() or pdf_path.stat().st_size == 0:
            logger.warning("PDF 文件异常（空文件）: %s", arxiv_id)
            if pdf_path.exists():
                pdf_path.unlink(missing_ok=True)
            return None

        return pdf_path

    async def _download_via_arxiv_sdk(self, arxiv_id: str, pdf_path: Path) -> bool:
        """通过官方 arxiv SDK 下载 PDF。"""

        try:
            search = arxiv.Search(id_list=[arxiv_id])
            paper = next(search.results())
        except StopIteration:
            logger.warning("未找到对应 arXiv 论文: %s", arxiv_id)
            return False
        except Exception as exc:  # noqa: BLE001
            logger.warning("arXiv API 查询失败 (%s): %s", arxiv_id, exc)
            return False

        try:
            await asyncio.to_thread(
                paper.download_pdf,
                dirpath=str(self.cache_dir),
                filename=f"{arxiv_id}.pdf",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("arXiv导出PDF失败，准备走HTTP兜底 (%s): %s", arxiv_id, exc)
            return False

        logger.info("PDF 下载成功 (export.arxiv.org): %s", arxiv_id)
        return True

    async def _download_via_http(self, arxiv_id: str, pdf_path: Path) -> bool:
        """使用 HTTP 直连下载 PDF，解决 export 延迟导致的404。"""

        success = await asyncio.to_thread(self._stream_pdf_to_file, arxiv_id, pdf_path)
        if success:
            logger.info("PDF 直连下载成功: %s", arxiv_id)
        else:
            logger.error("PDF 直连下载失败: %s", arxiv_id)
        return success

    def _stream_pdf_to_file(self, arxiv_id: str, pdf_path: Path) -> bool:
        """串流写入 PDF 文件（同步函数，供线程池调用）。"""

        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        # 逐步尝试 export → 主站直连，并在 404 场景下等待再试，缓解 PDF 尚未同步的问题
        for attempt in range(1, constants.ARXIV_PDF_HTTP_MAX_RETRIES + 1):
            for base_url in (
                constants.ARXIV_PDF_EXPORT_BASE,
                constants.ARXIV_PDF_PRIMARY_BASE,
            ):
                pdf_url = f"{base_url.rstrip('/')}/{arxiv_id}.pdf"
                try:
                    with httpx.stream(
                        "GET",
                        pdf_url,
                        timeout=constants.ARXIV_PDF_TIMEOUT_SECONDS,
                        follow_redirects=True,
                    ) as response:
                        response.raise_for_status()
                        with pdf_path.open("wb") as file_obj:
                            for chunk in response.iter_bytes(
                                constants.PDF_DOWNLOAD_CHUNK_SIZE
                            ):
                                file_obj.write(chunk)
                    return True
                except httpx.HTTPStatusError as exc:
                    logger.debug("PDF直连状态异常(%s): %s", pdf_url, exc)
                    if exc.response.status_code == 404:
                        continue
                except httpx.RequestError as exc:
                    logger.debug("PDF直连请求失败(%s): %s", pdf_url, exc)
            time.sleep(constants.ARXIV_PDF_HTTP_RETRY_DELAY_SECONDS)
        return False

    async def _parse_pdf(self, pdf_path: Path) -> Optional[PDFContent]:
        """使用 scipdf_parser 解析 PDF（带 GROBID 重试与自动切换）。"""

        article_dict = await self._call_grobid_with_retry(pdf_path)
        if not isinstance(article_dict, dict):
            if article_dict is None:
                return None
            logger.warning("PDF解析结果非字典类型: %s", type(article_dict))
            return None

        sections: dict[str, str] = {}
        raw_sections: Any = article_dict.get("sections") or []
        for section in raw_sections:
            if not isinstance(section, dict):
                continue
            heading = (section.get("heading") or "").strip()
            text = (section.get("text") or "").strip()
            if heading and text:
                sections[heading] = text

        authors_affiliations: list[tuple[str, str]] = []
        raw_authors: Any = article_dict.get("authors") or []
        for author in raw_authors:
            if not isinstance(author, dict):
                continue
            name = (author.get("name") or "").strip()
            affiliation_dict: Any = author.get("affiliation") or {}
            if isinstance(affiliation_dict, dict):
                affiliation = (affiliation_dict.get("institution") or "").strip()
            else:
                affiliation = str(affiliation_dict).strip()

            if name:
                authors_affiliations.append((name, affiliation))

        all_configs = constants.PDF_SECTION_P1_CONFIGS + constants.PDF_SECTION_P2_CONFIGS
        summaries: dict[str, Optional[str]] = {}
        for name, keywords, max_len in all_configs:
            summaries[name] = self._extract_section_summary(
                sections, keywords=keywords, max_len=max_len
            )

        introduction_summary = summaries["introduction"]
        method_summary = summaries["method"]
        evaluation_summary = summaries["evaluation"]
        dataset_summary = summaries["dataset"]
        baselines_summary = summaries["baselines"]
        conclusion_summary = summaries["conclusion"]

        # 至少提取2个P1核心章节，若不足仅警告不阻断流程
        p1_count = sum(
            1
            for name, _, _ in constants.PDF_SECTION_P1_CONFIGS
            if summaries[name]
        )
        if p1_count < constants.PDF_MIN_P1_SECTIONS:
            logger.warning(
                "PDF核心章节不足: %d < %d (期望), 可能影响LLM推理",
                p1_count,
                constants.PDF_MIN_P1_SECTIONS,
            )

        raw_references: Any = article_dict.get("references") or []
        references = [str(ref) for ref in raw_references]

        return PDFContent(
            title=(article_dict.get("title") or "").strip(),
            abstract=(article_dict.get("abstract") or "").strip(),
            sections=sections,
            authors_affiliations=authors_affiliations,
            references=references,
            evaluation_summary=evaluation_summary,
            dataset_summary=dataset_summary,
            baselines_summary=baselines_summary,
            introduction_summary=introduction_summary,
            method_summary=method_summary,
            conclusion_summary=conclusion_summary,
        )

    async def _call_grobid_with_retry(self, pdf_path: Path) -> Optional[dict[str, Any]]:
        """调用 GROBID 并在连接异常时自动重试与重选服务。"""

        last_exc: Optional[Exception] = None
        for attempt in range(1, constants.GROBID_MAX_RETRIES + 1):
            try:
                return await asyncio.to_thread(
                    parse_pdf_to_dict, str(pdf_path), grobid_url=self.grobid_url
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning(
                    "GROBID解析异常(%s, 第%d/%d次): %s",
                    pdf_path.name,
                    attempt,
                    constants.GROBID_MAX_RETRIES,
                    exc,
                )
                if self._should_refresh_grobid(exc):
                    self.grobid_url = self._resolve_grobid_url()
                if attempt < constants.GROBID_MAX_RETRIES:
                    # 简单退避，给 HuggingFace Space 释放资源
                    await asyncio.sleep(constants.GROBID_RETRY_DELAY_SECONDS)

        logger.error("PDF 解析失败 (%s): %s", pdf_path.name, last_exc)
        return None

    def _should_refresh_grobid(self, exc: Exception) -> bool:
        """判断异常是否来源于 GROBID 网络问题，如是则重新探测服务。"""

        transient_errors = (
            httpx.RequestError,
            requests.RequestException,
            OSError,
        )
        if isinstance(exc, transient_errors):
            return True
        return "SSL" in str(exc).upper()

    def _extract_section_summary(
        self,
        sections: dict[str, str],
        keywords: list[str],
        max_len: int,
    ) -> Optional[str]:
        """从章节字典中提取包含目标关键词的摘要。

        策略：优先根据章节标题匹配关键字，并截断到 max_len 字符。
        """
        for section_name, section_text in sections.items():
            if any(keyword.lower() in section_name.lower() for keyword in keywords):
                return section_text[:max_len]
        return None

    def _extract_urls_from_pdf(
        self, pdf_content: PDFContent
    ) -> dict[str, Optional[str]]:
        """从PDF正文提取 GitHub/数据集/论文 URL。

        优先级：Code/Data Availability -> Evaluation/Dataset -> Intro/Method -> Conclusion -> 其他章节。
        """

        urls: dict[str, Optional[str]] = {
            "github_url": None,
            "dataset_url": None,
            "paper_url": None,
        }

        priority_sections: list[str] = []

        # 章节优先：根据标题关键词挑选
        section_priority_keywords = [
            "code availability",
            "data availability",
            "implementation",
            "experiment",
            "evaluation",
            "dataset",
        ]
        for name, text in pdf_content.sections.items():
            lower = name.lower()
            if any(key in lower for key in section_priority_keywords):
                priority_sections.append(text)

        # 补充摘要/章节总结
        priority_sections.extend(
            filter(
                None,
                [
                    pdf_content.evaluation_summary,
                    pdf_content.dataset_summary,
                    pdf_content.baselines_summary,
                    pdf_content.introduction_summary,
                    pdf_content.method_summary,
                    pdf_content.conclusion_summary,
                ],
            )
        )

        # 回退：拼接全部章节
        if not priority_sections:
            priority_sections = list(pdf_content.sections.values())

        full_text = "\n".join(priority_sections)
        url_pattern = r"https?://[^\s<>\"{}|\\^`\[\]]+"
        found_urls = re.findall(url_pattern, full_text)

        dataset_domains = [
            "huggingface.co/datasets",
            "zenodo.org",
            "kaggle.com/datasets",
            "paperswithcode.com/dataset",
            "drive.google.com",
        ]

        for url in found_urls:
            url_lower = url.lower()

            if not urls["github_url"] and "github.com" in url_lower:
                normalized = self._normalize_github_url(url)
                if normalized:
                    urls["github_url"] = normalized
                    continue

            if not urls["dataset_url"] and any(
                domain in url_lower for domain in dataset_domains
            ):
                urls["dataset_url"] = url
                continue

            if not urls["paper_url"] and "arxiv.org/abs" in url_lower:
                urls["paper_url"] = url

        return urls

    @staticmethod
    def _normalize_github_url(url: str) -> Optional[str]:
        """将 GitHub 链接规范化为 https://github.com/org/repo，过滤 issues/tree/blob 等无关链接。"""

        match = re.search(r"github\.com/([^/]+)/([^/#?\s]+)", url)
        if not match:
            return None

        owner, repo = match.groups()
        if repo.lower() in {"issues", "pulls", "actions"}:
            return None

        # 去掉.git 或多余路径
        repo = repo.replace(".git", "")
        return f"https://github.com/{owner}/{repo}"

    async def _fetch_github_metadata(self, github_url: str) -> dict[str, Any]:
        """从 GitHub API 获取 stars / 许可证 / 活跃度元数据，失败则返回空字典。"""

        if not github_url or "github.com" not in github_url:
            return {}

        match = re.search(r"github\.com/([^/]+)/([^/\s]+)", github_url)
        if not match:
            return {}

        owner, repo = match.groups()
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "BenchScope/1.0",
        }
        token = os.getenv("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            async with httpx.AsyncClient(
                timeout=constants.GITHUB_METADATA_TIMEOUT_SECONDS
            ) as client:
                response = await client.get(api_url, headers=headers)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.debug("GitHub元数据获取失败(%s): %s", github_url, exc)
            return {}

        return {
            "github_stars": data.get("stargazers_count"),
            "license_type": (data.get("license") or {}).get("spdx_id"),
            "github_updated_at": data.get("updated_at"),
            "github_open_issues": data.get("open_issues_count"),
        }

    async def _merge_pdf_content(
        self,
        candidate: RawCandidate,
        pdf_content: PDFContent,
    ) -> RawCandidate:
        """将 PDF 解析结果合并回 RawCandidate。

        处理顺序：
        1. 摘要与机构补全
        2. 章节摘要写入 raw_metadata
        3. 从全文提取 GitHub/数据集/论文 URL 并回填
        4. 可选调用 GitHub API 补齐 stars/许可证
        """
        # 更新摘要：保留信息量更大的版本
        pdf_abstract = pdf_content.abstract or ""
        current_abstract = candidate.abstract or ""
        if len(pdf_abstract) > len(current_abstract):
            candidate.abstract = pdf_abstract

        # 更新机构信息：取前若干个非空机构
        if pdf_content.authors_affiliations:
            institutions = [
                affiliation
                for _, affiliation in pdf_content.authors_affiliations
                if affiliation
            ]
            if institutions:
                candidate.raw_institutions = ", ".join(institutions[:3])

        # 写入增强元数据（全部转为字符串，兼容 RawCandidate.raw_metadata 类型）
        metadata = dict(candidate.raw_metadata or {})
        # Phase 8字段
        metadata["evaluation_summary"] = pdf_content.evaluation_summary or ""
        metadata["dataset_summary"] = pdf_content.dataset_summary or ""
        metadata["baselines_summary"] = pdf_content.baselines_summary or ""
        # Phase PDF Enhancement新增字段
        metadata["introduction_summary"] = pdf_content.introduction_summary or ""
        metadata["method_summary"] = pdf_content.method_summary or ""
        metadata["conclusion_summary"] = pdf_content.conclusion_summary or ""
        metadata["pdf_sections"] = ", ".join(pdf_content.sections.keys())
        metadata["pdf_references_count"] = str(len(pdf_content.references))

        # URL提取与回填
        extracted_urls = self._extract_urls_from_pdf(pdf_content)
        pdf_content.extracted_github_url = extracted_urls.get("github_url")
        pdf_content.extracted_dataset_url = extracted_urls.get("dataset_url")
        pdf_content.extracted_paper_url = extracted_urls.get("paper_url")

        if extracted_urls.get("github_url") and not candidate.github_url:
            candidate.github_url = extracted_urls["github_url"]
            logger.info("从PDF提取GitHub URL: %s", candidate.github_url)

        if extracted_urls.get("dataset_url") and not candidate.dataset_url:
            candidate.dataset_url = extracted_urls["dataset_url"]
            logger.info("从PDF提取数据集URL: %s", candidate.dataset_url)

        if extracted_urls.get("paper_url") and not candidate.paper_url:
            candidate.paper_url = extracted_urls["paper_url"]

        # 可选：GitHub 元数据补充（stars/许可证/活跃度），失败不阻断
        if candidate.github_url and (
            candidate.github_stars is None or candidate.license_type is None
        ):
            github_meta = await self._fetch_github_metadata(candidate.github_url)
            if github_meta:
                candidate.github_stars = candidate.github_stars or github_meta.get(
                    "github_stars"
                )
                candidate.license_type = candidate.license_type or github_meta.get(
                    "license_type"
                )
                if github_meta.get("github_updated_at"):
                    metadata["github_updated_at"] = github_meta["github_updated_at"]
                if github_meta.get("github_open_issues") is not None:
                    metadata["github_open_issues"] = str(
                        github_meta["github_open_issues"]
                    )

        candidate.raw_metadata = metadata

        return candidate

    @staticmethod
    def _extract_arxiv_id(url: str) -> Optional[str]:
        """从 URL 中提取 arXiv ID。

        支持形如:
        - https://arxiv.org/abs/2401.12345
        - https://arxiv.org/abs/2401.12345v2
        """
        if not url:
            return None

        match = re.search(r"(\d{4}\.\d{4,5}(?:v\d+)?)", url)
        if not match:
            return None

        arxiv_id = match.group(1)
        # 去掉版本号后缀 vN
        return arxiv_id.split("v")[0]

    def _resolve_grobid_url(self) -> str:
        """确定可用的 GROBID 服务地址。"""

        env_url = os.getenv("GROBID_URL")
        if env_url:
            return env_url

        if self._is_grobid_alive(constants.GROBID_LOCAL_URL):
            return constants.GROBID_LOCAL_URL

        logger.warning(
            "未检测到本地GROBID服务，自动切换至云端: %s",
            constants.GROBID_CLOUD_URL,
        )
        return constants.GROBID_CLOUD_URL

    def _is_grobid_alive(self, base_url: str) -> bool:
        """通过版本接口探测 GROBID 可用性。"""

        health_url = f"{base_url.rstrip('/')}{constants.GROBID_HEALTH_PATH}"
        try:
            response = httpx.get(
                health_url,
                timeout=constants.GROBID_HEALTH_TIMEOUT,
            )
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError as exc:
            logger.debug("GROBID状态异常(%s): %s", base_url, exc)
        except httpx.RequestError as exc:
            logger.debug("GROBID连接失败(%s): %s", base_url, exc)
        return False
