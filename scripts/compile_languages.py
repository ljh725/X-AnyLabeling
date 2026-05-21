import os
import sys
import shutil
import subprocess


def compile_resources(output: str, qrc: str) -> None:
    """Compile a .qrc file to a PyQt6-compatible resources.py."""

    def normalize_imports(path: str) -> None:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace("from PySide6", "from PyQt6")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def add_rcc_commands(commands, base_command, needs_rewrite):
        # Force zlib resources when supported. Newer RCC builds may emit zstd
        # entries by default, which are not readable in some Windows Qt runtimes.
        commands.append(
            (
                [*base_command, "--compress-algo", "zlib", "-o", output, qrc],
                needs_rewrite,
            )
        )
        commands.append(([*base_command, "-o", output, qrc], needs_rewrite))

    commands = []
    add_rcc_commands(
        commands, [sys.executable, "-m", "PyQt6.pyrcc_main"], False
    )
    add_rcc_commands(commands, ["pyrcc6"], False)
    add_rcc_commands(commands, ["pyside6-rcc"], True)
    add_rcc_commands(commands, ["rcc", "-g", "python"], True)
    lrelease = shutil.which("lrelease")
    if lrelease:
        sibling_rcc = os.path.join(os.path.dirname(lrelease), "rcc")
        add_rcc_commands(commands, [sibling_rcc, "-g", "python"], True)
    for command, needs_rewrite in commands:
        executable = command[0]
        if executable != sys.executable and not shutil.which(executable):
            continue
        result = subprocess.run(command, stderr=subprocess.DEVNULL)
        if result.returncode != 0:
            continue
        if needs_rewrite:
            normalize_imports(output)
        return
    print(
        "Error: no Qt resource compiler found. Tried python -m PyQt6.pyrcc_main, pyrcc6, pyside6-rcc, rcc -g python, and lrelease-sibling rcc."
    )


supported_languages = ["en_US", "zh_CN", "ja_JP", "ko_KR"]

for language in supported_languages:
    command = f"lrelease anylabeling/resources/translations/{language}.ts"
    os.system(command)

compile_resources(
    output="anylabeling/resources/resources.py",
    qrc="anylabeling/resources/resources.qrc",
)


"""
功能说明：
    这个脚本用来编译翻译文件和资源文件。
    先用 lrelease 把 .ts 翻译文件转成 .qm 二进制文件，
    再用 RCC 工具把 .qrc 资源文件打包成 Python 模块（resources.py），
    这样软件运行时就能加载多语言翻译和内置资源了。

运行命令样例：

  # 在项目根目录下直接运行
  python scripts/compile_languages.py
"""
