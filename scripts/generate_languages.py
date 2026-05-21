import os
import glob
import sys
import shutil
import subprocess
from PyQt6 import QtCore


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
translations_path = "anylabeling/resources/translations"

for language in supported_languages:
    # Scan all .py files in the project directory and its subdirectories
    py_files = glob.glob(os.path.join("**", "*.py"), recursive=True)

    # Create a QTranslator object to generate the .ts file
    translator = QtCore.QTranslator()

    # Translate all .ui files into .py files
    ui_files = glob.glob(os.path.join("**", "*.ui"), recursive=True)
    for ui_file in ui_files:
        py_file = os.path.splitext(ui_file)[0] + "_ui.py"
        command = f"pyuic6 -x {ui_file} -o {py_file}"
        os.system(command)

    # Extract translations from the .py file
    command = f"pylupdate6 --no-obsolete {' '.join(py_files)} -ts {translations_path}/{language}.ts"
    os.system(command)

    # Compile the .ts file into a .qm file
    command = f"lrelease {translations_path}/{language}.ts"
    os.system(command)

compile_resources(
    output="anylabeling/resources/resources.py",
    qrc="anylabeling/resources/resources.qrc",
)


"""
功能说明：
    这个脚本用来生成软件的多语言翻译文件。
    它会做这几件事：
    1. 把项目里的 .ui 界面文件转成 Python 代码
    2. 扫描所有 Python 文件，把里面需要翻译的字符串提取出来
    3. 生成 .ts 翻译源文件（供翻译人员填写不同语言的译文）
    4. 用 lrelease 把 .ts 编译成 .qm 二进制文件（软件运行时加载）
    5. 打包所有资源文件到一个 Python 模块里
    支持的语言包括：英文、中文、日文、韩文。

运行命令样例：

  # 在项目根目录下直接运行
  python scripts/generate_languages.py
"""
