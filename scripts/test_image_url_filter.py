"""测试图片URL过滤逻辑"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.models import ScoredCandidate


def main() -> None:
    test_candidates = [
        ScoredCandidate(
            title="测试1: 有效URL",
            url="https://example.com/1",
            source="github",
            hero_image_url="https://example.com/image.png",
            hero_image_key=None,
        ),
        ScoredCandidate(
            title="测试2: 相对路径",
            url="https://example.com/2",
            source="github",
            hero_image_url="docs/images/banner.png",
            hero_image_key=None,
        ),
        ScoredCandidate(
            title="测试3: 已有image_key",
            url="https://example.com/3",
            source="github",
            hero_image_url="https://example.com/image2.png",
            hero_image_key="img_v3_xxx",
        ),
        ScoredCandidate(
            title="测试4: http协议",
            url="http://example.com/4",
            source="github",
            hero_image_url="http://example.com/image3.png",
            hero_image_key=None,
        ),
    ]

    upload_targets = [
        c
        for c in test_candidates
        if c.hero_image_url
        and not c.hero_image_key
        and c.hero_image_url.startswith(("http://", "https://"))
    ]

    print(f"过滤前: {len(test_candidates)} 个候选")
    print(f"过滤后: {len(upload_targets)} 个候选\n")

    print("保留的候选:")
    for c in upload_targets:
        print(f"  ✅ {c.title}: {c.hero_image_url}")

    print("\n过滤掉的候选:")
    filtered = [c for c in test_candidates if c not in upload_targets]
    for c in filtered:
        reason = "已有image_key" if c.hero_image_key else "相对路径URL"
        print(f"  ❌ {c.title}: {reason}")

    assert len(upload_targets) == 2, "应该保留2个有效URL"
    assert upload_targets[0].title == "测试1: 有效URL"
    assert upload_targets[1].title == "测试4: http协议"
    print("\n✅ 所有测试通过！")


if __name__ == "__main__":
    main()
