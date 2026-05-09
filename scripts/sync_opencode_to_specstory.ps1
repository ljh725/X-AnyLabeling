#!/usr/bin/env pwsh
<#
.SYNOPSIS
    将 opencode 会话同步到 SpecStory history
.DESCRIPTION
    导出当前项目的 opencode 会话，转换为 Markdown 保存到 .specstory/history
#>

param(
    [string]$ProjectDir = (Get-Location).Path,
    [string]$OutputDir = (Join-Path $ProjectDir ".specstory" "history"),
    [int]$MaxSessions = 50
)

# 确保输出目录存在
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

Write-Host "正在获取 opencode 会话列表..."

# 获取会话列表并保存到临时文件（避免编码问题）
$tempFile = [System.IO.Path]::GetTempFileName()
opencode session list --format json 2>$null | Set-Content -Path $tempFile -Encoding UTF8

# 读取并解析 JSON
$jsonContent = Get-Content -Path $tempFile -Raw -Encoding UTF8
Remove-Item $tempFile

try {
    $sessions = $jsonContent | ConvertFrom-Json
} catch {
    Write-Error "解析 opencode 会话列表失败: $_"
    exit 1
}

# 过滤当前项目的会话
$projectDirNormalized = $ProjectDir.TrimEnd('\', '/')
$projectSessions = $sessions | Where-Object { 
    $_.directory -and ($_.directory.TrimEnd('\', '/') -eq $projectDirNormalized)
} | Select-Object -First $MaxSessions

Write-Host "找到 $($projectSessions.Count) 个当前项目的会话"

foreach ($session in $projectSessions) {
    $sessionId = $session.id
    $title = $session.title
    $updated = $session.updated
    
    if (-not $sessionId -or -not $title) { continue }
    
    # 生成文件名（类似 SpecStory 格式）
    $timestamp = [DateTimeOffset]::FromUnixTimeMilliseconds($updated).UtcDateTime.ToString("yyyy-MM-dd_HH-mm-ssZ")
    $safeTitle = ($title -replace '[^\w\-]', '_').Substring(0, [Math]::Min(30, $title.Length))
    $filename = "${timestamp}-${safeTitle}-opencode.md"
    $filepath = Join-Path $OutputDir $filename
    
    # 如果文件已存在且比会话更新时间新，则跳过
    if (Test-Path $filepath) {
        $fileTime = (Get-Item $filepath).LastWriteTimeUtc
        $sessionTime = [DateTimeOffset]::FromUnixTimeMilliseconds($updated).UtcDateTime
        if ($fileTime -ge $sessionTime) {
            Write-Host "  跳过 (已是最新): $title"
            continue
        }
    }
    
    Write-Host "  导出: $title"
    
    # 导出会话到临时文件
    $exportTempFile = [System.IO.Path]::GetTempFileName()
    opencode export $sessionId 2>$null | Set-Content -Path $exportTempFile -Encoding UTF8
    $exportContent = Get-Content -Path $exportTempFile -Raw -Encoding UTF8
    Remove-Item $exportTempFile
    
    if (-not $exportContent) {
        Write-Warning "  无法导出会话: $sessionId"
        continue
    }
    
    try {
        $data = $exportContent | ConvertFrom-Json
    } catch {
        Write-Warning "  解析 JSON 失败: $sessionId"
        continue
    }
    
    # 生成 Markdown
    $md = [System.Collections.Generic.List[string]]::new()
    $md.Add("# $title")
    $md.Add("")
    $md.Add("**Session ID:** ``$sessionId``")
    $md.Add("**Agent:** $($data.info.agent)")
    $md.Add("**Model:** $($data.info.model.id)")
    $md.Add("**Updated:** $([DateTimeOffset]::FromUnixTimeMilliseconds($updated).ToString("yyyy-MM-dd HH:mm:ss"))")
    $md.Add("")
    $md.Add("---")
    $md.Add("")
    
    # 只提取 user 和 assistant 的文本消息
    foreach ($msg in $data.messages) {
        $role = $msg.info.role
        $agent = if ($msg.info.agent) { $msg.info.agent } else { "unknown" }
        $mode = if ($msg.info.mode) { $msg.info.mode } else { $agent }
        
        # 提取文本内容（跳过 redacted 内容）
        $texts = [System.Collections.Generic.List[string]]::new()
        foreach ($part in $msg.parts) {
            if ($part.type -eq "text" -and $part.text -and ($part.text -notmatch '^\[redacted:')) {
                $texts.Add($part.text)
            }
        }
        
        if ($texts.Count -eq 0) { continue }
        
        $content = $texts -join "`n`n"
        
        if ($role -eq "user") {
            $md.Add("## User ($mode)")
            $md.Add("")
            $md.Add($content)
            $md.Add("")
        } elseif ($role -eq "assistant") {
            $md.Add("## Assistant ($mode)")
            $md.Add("")
            $md.Add($content)
            $md.Add("")
        }
    }
    
    # 写入文件
    $mdContent = $md -join "`n"
    [System.IO.File]::WriteAllText($filepath, $mdContent, [System.Text.Encoding]::UTF8)
    Write-Host "  已保存: $filename"
}

Write-Host "`n同步完成！文件保存在: $OutputDir"
