"""Run against the API: python examples/import_knowledge.py [--base-url URL]."""
import argparse
import os
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1")
    args = parser.parse_args()
    payload = {
        "source_key": "mathpilot-demo-calculus",
        "source_title": "MathPilot 自编导数示例（非教材摘录）",
        "source_version": "1",
        "format": "markdown",
        "text": Path(__file__).with_name("knowledge.md").read_text(encoding="utf-8"),
    }
    if not os.environ.get('ADMIN_API_KEY'):
        parser.error('请设置 ADMIN_API_KEY；知识库导入现为受保护的管理操作')
    with httpx.Client(base_url=args.base_url, timeout=30, headers={'X-Admin-Key':os.environ['ADMIN_API_KEY']}) as client:
        first = client.post("/knowledge/imports", json=payload)
        first.raise_for_status()
        print(first.text)
        second = client.post("/knowledge/imports", json=payload)
        second.raise_for_status()
        result = second.json()
        assert result["duplicate"] is True
        assert result["created_points"] == result["created_revisions"] == 0
        print("重复导入验证通过：未增加知识点或修订。")
        print("资料保持待审核；请查看 /knowledge/revisions 和知识点详情。")


if __name__ == "__main__":
    main()
