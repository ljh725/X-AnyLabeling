#!/usr/bin/env python3
"""Convert opencode exported JSON sessions to Markdown conversation logs."""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def kebab_case_slug(text: str, max_len: int = 40) -> str:
    """Convert title to kebab-case slug for filenames."""
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    text = text.lower()
    if len(text) > max_len:
        text = text[:max_len].rsplit("-", 1)[0]
    return text


def format_timestamp(iso_str: str) -> str:
    """Convert ISO timestamp to local format."""
    iso_str = iso_str.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return iso_str


def render_user_block(item: Dict[str, Any]) -> List[str]:
    """Render a user message item."""
    lines = []
    ts = format_timestamp(item.get("timestamp", ""))
    lines.append("### 👤 User")
    lines.append(f"*{ts}*")
    lines.append("")

    for block in item.get("blocks", []):
        if block.get("type") == "text":
            raw = block.get("metadata", {}).get("raw", {})
            text = raw.get("text", "") if isinstance(raw, dict) else block.get("text", "")
            if text:
                lines.append(text)
    lines.append("")
    return lines


def render_reasoning_block(block: Dict[str, Any]) -> List[str]:
    """Render reasoning block with details tag."""
    raw = block.get("raw", {})
    text = raw.get("text", "") if isinstance(raw, dict) else ""

    return [
        "💭 **Reasoning:**",
        "",
        "<details>",
        "<summary>Click to expand reasoning</summary>",
        "",
        text,
        "",
        "</details>",
        "",
    ]


def render_tool_result(block: Dict[str, Any]) -> List[str]:
    """Render tool result block."""
    tool_name = block.get("tool_name", "unknown")
    content = block.get("content", "")
    metadata_raw = block.get("metadata", {}).get("raw", {})
    state = metadata_raw.get("state", {}) if isinstance(metadata_raw, dict) else {}

    lines = [
        f"#### 🔧 Tool: {tool_name}",
        "",
        f'**Status:** {state.get("status", "completed")}',
    ]

    title = state.get("title", "")
    if title:
        lines.append(f"**Title:** {title}")

    # Input
    input_data = state.get("input", {})
    if input_data:
        lines.append("")
        lines.append("**Input:**")
        lines.append("```json")
        lines.append(json.dumps(input_data, indent=2, ensure_ascii=False))
        lines.append("```")

    # Output / Content
    output = state.get("output", "") or content
    if output:
        lines.append("")
        lines.append("**Output:**")
        lines.append("```")
        lines.append(str(output))
        lines.append("```")

    lines.append("")
    return lines


def render_patch_ref(block: Dict[str, Any]) -> List[str]:
    """Render patch reference block."""
    files = block.get("files", [])
    if not files:
        return []

    lines = [
        "📝 **Code Changes:**",
        "",
    ]
    for f in files:
        lines.append(f"- `{f}`")
    lines.append("")
    return lines


def render_assistant_block(item: Dict[str, Any]) -> List[str]:
    """Render an assistant message item."""
    lines = []
    ts = format_timestamp(item.get("timestamp", ""))
    lines.append("### 🤖 Assistant")
    lines.append(f"*{ts}*")
    lines.append("")

    in_step = False

    for block in item.get("blocks", []):
        btype = block.get("type")

        if btype == "step":
            status = block.get("status", "")
            raw = block.get("metadata", {}).get("raw", {})
            step_type = raw.get("type", "") if isinstance(raw, dict) else ""

            if status == "start" or step_type == "step-start":
                lines.append("*[step-start part]*")
                lines.append("")
                in_step = True
            elif status == "finish" or step_type == "step-finish":
                if in_step:
                    lines.append("*[step-finish part]*")
                    lines.append("")
                in_step = False

        elif btype == "raw":
            raw_data = block.get("raw", {})
            if isinstance(raw_data, dict):
                raw_type = raw_data.get("type", "")
                if raw_type == "reasoning":
                    lines.extend(render_reasoning_block(block))

        elif btype == "text":
            raw = block.get("metadata", {}).get("raw", {})
            text = raw.get("text", "") if isinstance(raw, dict) else block.get("text", "")
            if text:
                lines.append(text)
                lines.append("")

        elif btype == "tool_result":
            lines.extend(render_tool_result(block))

        elif btype == "patch_ref":
            lines.extend(render_patch_ref(block))

    return lines


def convert_session(data: Dict[str, Any]) -> str:
    """Convert opencode JSON session to Markdown string."""
    session = data.get("session", {})
    title = session.get("title", "Untitled Session")
    created_at = session.get("created_at", "")

    created_str = ""
    if created_at:
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            created_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            created_str = created_at

    lines = [
        f"# Session: {title}",
        "",
        f"**Created:** {created_str}",
        "",
        "---",
        "",
        "## Conversation",
        "",
    ]

    for item in data.get("items", []):
        role = item.get("role", "")
        if role == "user":
            lines.extend(render_user_block(item))
        elif role == "assistant":
            lines.extend(render_assistant_block(item))

    return "\n".join(lines)


def generate_output_filename(session: Dict[str, Any]) -> str:
    """Generate output filename from session metadata."""
    created_at = session.get("created_at", "")
    title = session.get("title", "untitled")

    date_str = ""
    if created_at:
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            date_str = dt.strftime("%Y%m%d-%H-%M-%S")
        except ValueError:
            date_str = datetime.now().strftime("%Y%m%d-%H-%M-%S")
    else:
        date_str = datetime.now().strftime("%Y%m%d-%H-%M-%S")

    slug = kebab_case_slug(title)
    return f"{date_str}-{slug}.md"


def main():
    parser = argparse.ArgumentParser(
        description="Convert opencode exported JSON to Markdown conversation logs."
    )
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="Input JSON file or directory containing exported opencode sessions.",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        default="conversations",
        help="Output directory for Markdown files. Default: conversations/",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if input_path.is_file():
        json_files = [input_path]
    else:
        json_files = list(input_path.glob("*.json"))

    if not json_files:
        print(f"No JSON files found in {input_path}")
        return

    for json_file in json_files:
        print(f"Processing: {json_file}")

        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        md_content = convert_session(data)
        output_filename = generate_output_filename(data.get("session", {}))
        output_path = output_dir / output_filename

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        print(f"  → {output_path}")


if __name__ == "__main__":
    main()


"""
功能说明：
    这个脚本用来把 opencode 导出的 JSON 会话文件转成 Markdown 格式的对话记录。
    它可以处理单个 JSON 文件，也可以批量处理一整个文件夹里的所有 JSON 文件。
    转换后的 Markdown 会保留对话的时间戳、用户提问、AI 回复、工具调用结果、
    推理过程以及代码修改记录，方便你阅读和存档。
    输出文件名会自动根据会话标题和创建时间生成。

运行命令样例：

  # 转换单个 JSON 文件
  python scripts/convert_opencode_json_to_md.py \
      --input ./session.json \
      --output-dir ./conversations

  # 批量转换整个目录下的所有 JSON 文件
  python scripts/convert_opencode_json_to_md.py \
      --input ./exported_sessions \
      --output-dir ./conversations

  # 使用短参数
  python scripts/convert_opencode_json_to_md.py \
      -i ./session.json \
      -o ./output
"""
