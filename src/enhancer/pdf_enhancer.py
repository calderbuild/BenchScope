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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import arxiv
from scipdf.pdf import parse_pdf_to_dict  # type: ignore[import]

from src.models import RawCandidate

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PDFContent:
    """PDF 解析结果容器。"""

    title: str
    abstract: str  # 完整摘要（预期 500-1000 字）
    sections: Dict[str, str]  # {"Introduction": "...", "Methods": "...", ...}
    authors_affiliations: List[Tuple[str, str]]  # [("Alice Zhang", "Stanford University"), ...]
    references: List[str]  # 引用文献列表（原始字符串）
    evaluation_summary: Optional[str] = None  # Evaluation 部分摘要（最多 2000 字）
    dataset_summary: Optional[str] = None  # Dataset 部分摘要（最多 1000 字）
    baselines_summary: Optional[str] = None  # Baselines 部分摘要（最多 1000 字）


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
        self.cache_dir = Path(cache_dir or "/tmp/arxiv_pdf_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # 从环境变量读取 GROBID URL，默认使用本地服务
        self.grobid_url = os.getenv("GROBID_URL", "http://localhost:8070")

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

            enhanced = self._merge_pdf_content(candidate, pdf_content)
            logger.info("PDF 增强成功: %s (%s)", candidate.title[:80], arxiv_id)
            return enhanced
        except Exception as exc:  # noqa: BLE001
            # 任何异常都不应中断主流程，而是降级为返回原始 candidate
            logger.error("PDF 增强失败 (%s): %s", arxiv_id, exc)
            return candidate

    async def enhance_batch(self, candidates: List[RawCandidate]) -> List[RawCandidate]:
        """批量增强候选项。

        为避免触发 arXiv 限流，这里采用串行处理并在请求间加入短暂延迟。
        如果后续需要性能优化，可在此处实现更精细的并发控制与速率限制。
        """
        enhanced: List[RawCandidate] = []
        for candidate in candidates:
            result = await self.enhance_candidate(candidate)
            enhanced.append(result)
            # 短暂 sleep，降低对 arXiv 的瞬时压力
            await asyncio.sleep(0.5)

        return enhanced

    async def _download_pdf(self, arxiv_id: str) -> Optional[Path]:
        """下载 arXiv PDF（带缓存）。

        下载逻辑放入线程池，以避免阻塞事件循环。
        """
        pdf_path = self.cache_dir / f"{arxiv_id}.pdf"

        if pdf_path.exists():
            logger.debug("命中 PDF 缓存: %s", arxiv_id)
            return pdf_path

        try:
            search = arxiv.Search(id_list=[arxiv_id])
            paper = next(search.results())

            # arxiv 库为同步 API，这里用 to_thread 放到线程池执行
            await asyncio.to_thread(
                paper.download_pdf,
                dirpath=str(self.cache_dir),
                filename=f"{arxiv_id}.pdf",
            )

            if pdf_path.exists():
                logger.info("PDF 下载成功: %s", arxiv_id)
                return pdf_path

            logger.warning("PDF 下载后文件不存在: %s", arxiv_id)
            return None
        except StopIteration:
            logger.warning("未找到对应 arXiv 论文: %s", arxiv_id)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.error("PDF 下载异常 (%s): %s", arxiv_id, exc)
            return None

    async def _parse_pdf(self, pdf_path: Path) -> Optional[PDFContent]:
        """使用 scipdf_parser 解析 PDF。

        解析会调用 GROBID 服务，耗时相对较长，因此同样放入线程池执行。
        """
        try:
            # 解析结果为通用 dict，需要在使用前做类型防御
            article_dict = await asyncio.to_thread(
                parse_pdf_to_dict, str(pdf_path), grobid_url=self.grobid_url
            )
            if not isinstance(article_dict, dict):
                logger.warning("PDF解析结果非字典类型: %s", type(article_dict))
                return None

            sections: Dict[str, str] = {}
            raw_sections: Any = article_dict.get("sections") or []
            for section in raw_sections:
                if not isinstance(section, dict):
                    continue
                heading = (section.get("heading") or "").strip()
                text = (section.get("text") or "").strip()
                if heading and text:
                    sections[heading] = text

            authors_affiliations: List[Tuple[str, str]] = []
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

            evaluation_summary = self._extract_section_summary(
                sections,
                keywords=["evaluation", "experiments", "results", "performance"],
                max_len=2000,
            )
            dataset_summary = self._extract_section_summary(
                sections,
                keywords=["dataset", "data", "benchmark", "corpus"],
                max_len=1000,
            )
            baselines_summary = self._extract_section_summary(
                sections,
                keywords=["baselines", "comparison", "related work", "prior work"],
                max_len=1000,
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
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("PDF 解析失败 (%s): %s", pdf_path.name, exc)
            return None

    def _extract_section_summary(
        self,
        sections: Dict[str, str],
        keywords: List[str],
        max_len: int,
    ) -> Optional[str]:
        """从章节字典中提取包含目标关键词的摘要。

        策略：优先根据章节标题匹配关键字，并截断到 max_len 字符。
        """
        for section_name, section_text in sections.items():
            if any(keyword.lower() in section_name.lower() for keyword in keywords):
                return section_text[:max_len]
        return None

    def _merge_pdf_content(
        self,
        candidate: RawCandidate,
        pdf_content: PDFContent,
    ) -> RawCandidate:
        """将 PDF 解析结果合并回 RawCandidate。

        - 若 PDF 摘要更长，则覆盖原摘要
        - 根据作者机构信息补充 raw_institutions
        - 将 Evaluation / Dataset / Baselines 摘要写入 raw_metadata
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
        metadata["evaluation_summary"] = pdf_content.evaluation_summary or ""
        metadata["dataset_summary"] = pdf_content.dataset_summary or ""
        metadata["baselines_summary"] = pdf_content.baselines_summary or ""
        metadata["pdf_sections"] = ", ".join(pdf_content.sections.keys())
        metadata["pdf_references_count"] = str(len(pdf_content.references))
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
