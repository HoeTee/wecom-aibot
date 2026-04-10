from __future__ import annotations


def needs_rag_query_rewrite(function_name: str, args_dict: dict[str, object]) -> bool:
    query = args_dict.get("query")
    return (
        function_name.endswith("llamaindex_rag_query")
        and isinstance(query, str)
        and bool(query.strip())
    )


def rewrite_rag_query(query: str) -> str:
    rewritten = str(query or "").strip()
    if not rewritten:
        return rewritten

    replacements = {
        "重新生成一份企业微信文档": "生成一份基于来源材料的文档内容",
        "生成一份企业微信文档": "生成一份基于来源材料的文档内容",
        "给刚才那份文档": "",
        "给刚才那个文档": "",
        "不要新建文档": "",
        "回复要简洁，并明确告诉我是否已经创建文档。": "",
        "回复要简洁，并明确告诉我是否已经创建文档": "",
        "回复要简洁。": "",
        "回复要简洁": "",
    }
    for old, new in replacements.items():
        rewritten = rewritten.replace(old, new)

    filtered_lines: list[str] = []
    for raw_line in rewritten.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "明确告诉我是否已经创建文档" in line:
            continue
        if line.startswith("回复要"):
            continue
        filtered_lines.append(line)

    rewritten = "\n".join(filtered_lines).strip()
    return rewritten or str(query).strip()
