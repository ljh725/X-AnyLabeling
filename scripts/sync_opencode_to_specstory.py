#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将 opencode 会话同步到 SpecStory history

用法:
    python sync_opencode_to_specstory.py
    python sync_opencode_to_specstory.py --max-sessions 10
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def run_opencode_command(args):
    """运行 opencode 命令并返回输出"""
    # 尝试找到 opencode 命令
    opencode_cmd = "opencode"
    if sys.platform == "win32":
        # Windows 上优先使用 opencode.cmd
        for cmd_name in ["opencode.cmd", "opencode"]:
            try:
                subprocess.run([cmd_name, "--version"], capture_output=True, check=False)
                opencode_cmd = cmd_name
                break
            except FileNotFoundError:
                continue
    
    cmd = [opencode_cmd] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        if result.returncode != 0:
            print(f"警告: opencode 命令失败: {result.stderr}", file=sys.stderr)
            return None
        return result.stdout
    except Exception as e:
        print(f"错误: 运行 opencode 失败: {e}", file=sys.stderr)
        return None


def get_sessions():
    """获取 opencode 会话列表"""
    output = run_opencode_command(["session", "list", "--format", "json"])
    if not output:
        return []
    
    try:
        sessions = json.loads(output)
        return sessions if isinstance(sessions, list) else []
    except json.JSONDecodeError as e:
        print(f"错误: 解析会话列表失败: {e}", file=sys.stderr)
        return []


def export_session(session_id):
    """导出单个会话"""
    output = run_opencode_command(["export", session_id])
    if not output:
        return None
    
    try:
        return json.loads(output)
    except json.JSONDecodeError as e:
        print(f"警告: 解析会话 {session_id} 失败: {e}", file=sys.stderr)
        return None


def extract_text_messages(messages):
    """从消息中提取 user 和 assistant 的文本内容"""
    extracted = []
    
    for msg in messages:
        info = msg.get("info", {})
        role = info.get("role", "")
        agent = info.get("agent", "unknown")
        mode = info.get("mode", agent)
        
        # 提取文本内容
        texts = []
        for part in msg.get("parts", []):
            if part.get("type") == "text":
                text = part.get("text", "")
                # 跳过被 redacted 的内容
                if text and not text.startswith("[redacted:"):
                    texts.append(text)
        
        if not texts:
            continue
        
        content = "\n\n".join(texts)
        
        if role == "user":
            extracted.append({
                "role": "user",
                "mode": mode,
                "content": content
            })
        elif role == "assistant":
            extracted.append({
                "role": "assistant",
                "mode": mode,
                "content": content
            })
    
    return extracted


def generate_markdown(session_info, messages):
    """生成 Markdown 内容"""
    title = session_info.get("title", "Untitled")
    session_id = session_info.get("id", "")
    agent = session_info.get("agent", "unknown")
    model = session_info.get("model", {}).get("id", "unknown")
    updated = session_info.get("updated", 0)
    
    # 转换时间戳
    updated_str = ""
    if updated:
        try:
            dt = datetime.fromtimestamp(updated / 1000, tz=timezone.utc)
            updated_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except:
            pass
    
    lines = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"**Session ID:** `{session_id}`")
    lines.append(f"**Agent:** {agent}")
    lines.append(f"**Model:** {model}")
    if updated_str:
        lines.append(f"**Updated:** {updated_str}")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # 添加消息
    for msg in messages:
        role = msg["role"]
        mode = msg["mode"]
        content = msg["content"]
        
        if role == "user":
            lines.append(f"## User ({mode})")
        elif role == "assistant":
            lines.append(f"## Assistant ({mode})")
        
        lines.append("")
        lines.append(content)
        lines.append("")
    
    return "\n".join(lines)


def sanitize_filename(title, max_length=30):
    """生成安全的文件名"""
    # 替换不安全字符
    safe = re.sub(r'[^\w\-]', '_', title)
    # 限制长度
    if len(safe) > max_length:
        safe = safe[:max_length]
    # 去除尾部下划线
    safe = safe.rstrip('_')
    # 确保不为空
    if not safe:
        safe = "untitled"
    return safe


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="将 opencode 会话同步到 SpecStory history"
    )
    parser.add_argument(
        "--project-dir",
        default=os.getcwd(),
        help="项目目录 (默认: 当前目录)"
    )
    parser.add_argument(
        "--output-dir",
        help="输出目录 (默认: PROJECT_DIR/.specstory/history)"
    )
    parser.add_argument(
        "--max-sessions",
        type=int,
        default=50,
        help="最大同步会话数 (默认: 50)"
    )
    args = parser.parse_args()
    
    project_dir = Path(args.project_dir).resolve()
    output_dir = Path(args.output_dir) if args.output_dir else project_dir / ".specstory" / "history"
    
    # 确保输出目录存在
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"正在获取 opencode 会话列表...")
    sessions = get_sessions()
    
    # 过滤当前项目的会话
    project_dir_str = str(project_dir)
    project_sessions = [
        s for s in sessions
        if s.get("directory") and (
            s["directory"] == project_dir_str or
            s["directory"].replace("/", "\\") == project_dir_str
        )
    ][:args.max_sessions]
    
    print(f"找到 {len(project_sessions)} 个当前项目的会话")
    
    synced_count = 0
    skipped_count = 0
    
    for session in project_sessions:
        session_id = session.get("id", "")
        title = session.get("title", "Untitled")
        updated = session.get("updated", 0)
        
        if not session_id:
            continue
        
        # 生成文件名
        timestamp = ""
        if updated:
            try:
                dt = datetime.fromtimestamp(updated / 1000, tz=timezone.utc)
                timestamp = dt.strftime("%Y-%m-%d_%H-%M-%SZ")
            except:
                pass
        
        if not timestamp:
            timestamp = "unknown"
        
        safe_title = sanitize_filename(title)
        filename = f"{timestamp}-{safe_title}-opencode.md"
        filepath = output_dir / filename
        
        # 检查是否需要更新
        if filepath.exists() and updated:
            file_mtime = filepath.stat().st_mtime
            session_time = updated / 1000
            if file_mtime >= session_time:
                print(f"  跳过 (已是最新): {title}")
                skipped_count += 1
                continue
        
        print(f"  导出: {title}")
        
        # 导出会话
        data = export_session(session_id)
        if not data:
            continue
        
        # 提取消息
        messages = extract_text_messages(data.get("messages", []))
        if not messages:
            print(f"    警告: 没有找到可导出的消息")
            continue
        
        # 生成 Markdown
        info = data.get("info", {})
        info["id"] = session_id
        info["title"] = title
        info["updated"] = updated
        
        md_content = generate_markdown(info, messages)
        
        # 写入文件
        filepath.write_text(md_content, encoding="utf-8")
        print(f"  已保存: {filename}")
        synced_count += 1
    
    print(f"\n同步完成!")
    print(f"  新同步: {synced_count}")
    print(f"  跳过 (已是最新): {skipped_count}")
    print(f"  输出目录: {output_dir}")


if __name__ == "__main__":
    main()
