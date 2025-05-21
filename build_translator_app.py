# build_translator_app.py - 同声传译应用打包脚本 (最终版)
import os
import sys
import subprocess
import shutil
import importlib
import time
import platform


def print_step(message):
    """打印带格式的步骤信息"""
    print("\n" + "=" * 80)
    print(f">>> {message}")
    print("=" * 80)


def check_module_installed(module_name):
    """检查模块是否已安装"""
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        return False


def install_dependencies():
    """安装必要的依赖包"""
    print_step("安装必要的依赖包")
    dependencies = [
        "pyinstaller",  # 打包工具
        "funasr",  # 语音识别
        "sounddevice",  # 音频处理
        "numpy",  # 科学计算
        "edge-tts",  # 文本到语音
        "pygame",  # 音频播放
        "httpx",  # HTTP客户端
        "ujson",  # 快速JSON处理
        "requests",  # HTTP请求
        "torch",  # PyTorch (FunASR需要)
        "torchaudio"  # PyTorch音频库 (FunASR需要)
    ]

    # 检查并安装缺失的包
    missing = []
    for package in dependencies:
        package_name = package.split('==')[0].lower()
        if not check_module_installed(package_name):
            missing.append(package)

    if missing:
        print(f"需要安装以下依赖: {', '.join(missing)}")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install"] + missing, check=True)
            print("所有依赖安装完成")
        except subprocess.CalledProcessError as e:
            print(f"安装依赖时出错: {e}")
            return False
    else:
        print("所有依赖已经安装")

    return True


def create_startup_script():
    """创建启动脚本，处理模型下载"""
    print_step("创建应用启动脚本")

    # 使用原始字符串，避免转义问题
    startup_script = r'''# 同声传译应用启动脚本
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk
import time

# 设置环境变量
os.environ["FUNASR_DISABLE_UPDATE"] = "True"

# 设置工作目录为应用程序所在目录
if getattr(sys, 'frozen', False):
    # 如果是打包的应用
    app_dir = os.path.dirname(sys.executable)
else:
    # 如果是开发环境
    app_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(app_dir)

class ModelDownloadWindow:
    """模型首次下载的等待窗口"""
    def __init__(self, parent):
        self.parent = parent
        self.parent.title("同声传译应用 - 初始化")
        self.parent.geometry("400x300")
        self.parent.resizable(False, False)

        # 设置窗口居中
        self.parent.eval('tk::PlaceWindow . center')

        # 创建UI元素
        ttk.Label(parent, text="同声传译应用 - 首次启动", font=("Arial", 14)).pack(pady=15)
        ttk.Label(parent, text="首次运行需要下载语音识别模型，请保持网络连接", font=("Arial", 10)).pack(pady=5)

        self.status_var = tk.StringVar(value="正在初始化...")
        ttk.Label(parent, textvariable=self.status_var, font=("Arial", 10)).pack(pady=5)

        self.progress = ttk.Progressbar(parent, orient="horizontal", length=350, mode="indeterminate")
        self.progress.pack(pady=15)

        self.log_text = tk.Text(parent, height=7, width=45)
        self.log_text.pack(pady=10, padx=20)

        # 启动进度条
        self.progress.start()

        # 启动下载线程
        self.download_complete = False
        self.download_thread = threading.Thread(target=self.download_models)
        self.download_thread.daemon = True
        self.download_thread.start()

        # 定期检查下载状态
        self.check_download_status()

    def add_log(self, message):
        """添加日志到文本框"""
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def download_models(self):
        """下载模型线程"""
        try:
            self.add_log("开始加载FunASR模块...")
            self.status_var.set("加载FunASR模块...")

            # 导入FunASR
            try:
                from FunASR import FastLoadASR
                self.add_log("FunASR模块加载成功")

                # 创建ASR实例，这将触发模型下载
                self.add_log("开始加载语音识别模型...")
                self.status_var.set("下载语音识别模型...")

                # 创建实例（这将触发模型下载）
                asr = FastLoadASR(use_vad=True, use_punc=True)

                # 确保模型加载完成
                self.add_log("等待ASR模型加载完成...")
                asr.ensure_asr_model_loaded()
                self.add_log("ASR主模型加载完成")

                # 加载VAD模型
                self.status_var.set("下载VAD模型...")
                self.add_log("开始加载VAD模型...")
                asr.load_vad_model_if_needed()
                self.add_log("VAD模型加载完成")

                # 加载标点模型
                self.status_var.set("下载标点模型...")
                self.add_log("开始加载标点模型...")
                asr.load_punc_model_if_needed()
                self.add_log("标点模型加载完成")

                self.add_log("所有模型加载完成！")
                self.status_var.set("初始化完成")
                self.download_complete = True

            except ImportError as e:
                self.add_log(f"导入FunASR失败: {e}")
                self.status_var.set("初始化失败")
            except Exception as e:
                self.add_log(f"模型加载失败: {e}")
                self.status_var.set("初始化失败")

        except Exception as e:
            self.add_log(f"初始化过程中出错: {e}")
            self.status_var.set("初始化失败")

    def check_download_status(self):
        """检查下载状态并决定下一步操作"""
        if self.download_complete:
            self.progress.stop()
            self.add_log("准备启动主应用...")
            # 等待1秒让用户看到完成信息
            self.parent.after(1000, self.launch_main_app)
        else:
            # 继续检查
            self.parent.after(500, self.check_download_status)

    def launch_main_app(self):
        """启动主应用"""
        self.parent.destroy()  # 关闭下载窗口

        # 导入并启动主应用
        try:
            from simultaneous_translator_app import SimultaneousTranslatorApp
            import tkinter as tk

            root = tk.Tk()
            app = SimultaneousTranslatorApp(root)
            root.protocol("WM_DELETE_WINDOW", app.on_closing)
            root.mainloop()
        except Exception as e:
            print(f"启动主应用失败: {e}")
            sys.exit(1)

# 主程序入口
if __name__ == "__main__":
    # 检查是否已经下载了模型（简单检查模型目录是否存在）
    model_path = os.path.expanduser('~/.cache/funasr/models')
    paraformer_path = os.path.join(model_path, "paraformer-zh-streaming")

    if os.path.exists(paraformer_path):
        # 模型已下载，直接启动主应用
        try:
            from simultaneous_translator_app import SimultaneousTranslatorApp
            root = tk.Tk()
            app = SimultaneousTranslatorApp(root)
            root.protocol("WM_DELETE_WINDOW", app.on_closing)
            root.mainloop()
        except Exception as e:
            print(f"启动主应用失败: {e}")
            sys.exit(1)
    else:
        # 模型未下载，显示下载窗口
        root = tk.Tk()
        app = ModelDownloadWindow(root)
        root.mainloop()
'''

    with open("app_entry.py", "w", encoding="utf-8") as f:
        f.write(startup_script)

    print("启动脚本创建成功")
    return True


def fix_funasr_code():
    """修复FunASR.py中可能存在的问题"""
    print_step("检查并修复FunASR代码")

    try:
        # 检查FunASR.py是否存在
        if not os.path.exists("FunASR.py"):
            print("错误: 未找到FunASR.py文件")
            return False

        # 读取文件内容
        with open("FunASR.py", "r", encoding="utf-8") as f:
            content = f.read()

        # 检查是否需要修改
        modifications_needed = False

        # 确保有disable_update参数
        if "disable_update=" not in content:
            print("需要修复: 添加disable_update参数")
            modifications_needed = True
            content = content.replace(
                "def __init__(self, use_vad=True, use_punc=True,",
                "def __init__(self, use_vad=True, use_punc=True, disable_update=True,"
            )

        # 如果需要修改，写回文件
        if modifications_needed:
            with open("FunASR.py", "w", encoding="utf-8") as f:
                f.write(content)
            print("FunASR.py已修复")
        else:
            print("FunASR.py无需修复")

        return True
    except Exception as e:
        print(f"修复FunASR.py时出错: {e}")
        return False


def create_hook_files():
    """创建PyInstaller钩子文件"""
    print_step("创建PyInstaller钩子文件")

    # 创建钩子目录
    os.makedirs("hooks", exist_ok=True)

    # 创建torch钩子
    with open(os.path.join("hooks", "hook-torch.py"), "w") as f:
        f.write("""
# PyInstaller hook for torch
from PyInstaller.utils.hooks import collect_all

# Collect everything from torch (binaries, datas, hiddenimports)
datas, binaries, hiddenimports = collect_all('torch')

# Add additional hidden imports
hiddenimports.extend([
    'torch._C',
    'torch.autograd',
    'torch.storage',
    'torch.nn',
    'torch.nn.functional',
    'torch.nn.modules',
    'torch._utils',
    'torch._tensor',
])
""")

    # 创建torchaudio钩子
    with open(os.path.join("hooks", "hook-torchaudio.py"), "w") as f:
        f.write("""
# PyInstaller hook for torchaudio
from PyInstaller.utils.hooks import collect_all

# Collect everything from torchaudio (binaries, datas, hiddenimports)
datas, binaries, hiddenimports = collect_all('torchaudio')

# Add additional hidden imports
hiddenimports.extend([
    'torchaudio._torchaudio',
    'torchaudio.functional',
])
""")

    # 创建funasr钩子
    with open(os.path.join("hooks", "hook-funasr.py"), "w") as f:
        f.write("""
# PyInstaller hook for funasr
from PyInstaller.utils.hooks import collect_all

# Collect everything from funasr (binaries, datas, hiddenimports)
datas, binaries, hiddenimports = collect_all('funasr')

# Add additional hidden imports
hiddenimports.extend([
    'funasr.runtime',
    'funasr.models',
])
""")

    print("钩子文件创建成功")
    return True


def get_torch_dlls():
    """收集torch和torchaudio的DLL文件"""
    print_step("收集PyTorch DLL文件")

    try:
        import torch
        import torchaudio
        import site

        # 创建DLL目录
        dll_dir = "dlls"
        os.makedirs(dll_dir, exist_ok=True)

        # 获取torch和torchaudio的路径
        torch_path = os.path.dirname(torch.__file__)
        torchaudio_path = os.path.dirname(torchaudio.__file__)

        # 可能的DLL路径
        dll_paths = [
            os.path.join(torch_path, "lib"),
            os.path.join(torchaudio_path, "lib"),
        ]

        # 收集DLL文件
        dll_files = []
        for path in dll_paths:
            if os.path.exists(path):
                for file in os.listdir(path):
                    if file.endswith(".dll"):
                        src = os.path.join(path, file)
                        dst = os.path.join(dll_dir, file)
                        shutil.copy2(src, dst)
                        dll_files.append(file)

        print(f"收集到 {len(dll_files)} 个DLL文件")

        # 返回DLL目录和文件列表
        return dll_dir, dll_files
    except Exception as e:
        print(f"收集DLL文件失败: {e}")
        return None, []


def build_direct_with_pyinstaller():
    """直接使用PyInstaller命令行打包，不使用spec文件"""
    print_step("使用PyInstaller直接打包")

    # 创建钩子文件
    create_hook_files()

    # 收集DLL文件
    dll_dir, dll_files = get_torch_dlls()

    # 构建基本命令
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--name=同声传译应用",
        "--windowed",  # 无控制台窗口
        "--onedir",  # 生成文件夹而非单个文件
        f"--paths={os.getcwd()}",  # 添加当前目录到路径
        f"--additional-hooks-dir={os.path.join(os.getcwd(), 'hooks')}",  # 添加钩子目录
    ]

    # 添加数据文件
    data_files = [
        "FunASR.py",
        "translation_module.py",
        "edge_TTS.py",
        "simultaneous_translator_app.py"
    ]

    for file in data_files:
        cmd.append(f"--add-data={file};.")

    # 添加DLL文件
    if dll_dir and os.path.exists(dll_dir):
        for file in os.listdir(dll_dir):
            if file.endswith(".dll"):
                cmd.append(f"--add-binary={os.path.join(dll_dir, file)};.")

    # 添加隐藏导入
    hidden_imports = [
        "torch",
        "torch.nn",
        "torch._C",
        "torchaudio",
        "funasr",
        "numpy",
        "sounddevice",
        "edge_tts",
        "pygame",
        "requests",
        "httpx",
        "ujson",
        "tkinter",
        "tkinter.ttk",
        "tkinter.scrolledtext",
        "queue",
        "threading"
    ]

    for module in hidden_imports:
        cmd.append(f"--hidden-import={module}")

    # 排除不必要的模块
    exclude_modules = [
        "matplotlib",
        "pandas",
        "tensorflow",
        "scipy",
        "sklearn",
        "cv2",
        "PIL"
    ]

    for module in exclude_modules:
        cmd.append(f"--exclude-module={module}")

    # 添加入口脚本
    cmd.append("app_entry.py")

    # 执行命令
    print("执行PyInstaller命令...")
    print(" ".join(cmd))

    try:
        subprocess.run(cmd, check=True)
        print("PyInstaller打包成功")

        # 检查输出目录
        dist_dir = os.path.join("dist", "同声传译应用")
        if os.path.exists(dist_dir):
            print(f"应用文件夹已生成: {dist_dir}")
            return True
        else:
            print("错误: 未找到生成的应用文件夹")
            return False
    except subprocess.CalledProcessError as e:
        print(f"PyInstaller打包失败: {e}")
        return False


def create_readme():
    """创建说明文件"""
    print_step("创建说明文件")

    readme_content = """# 同声传译应用使用说明

## 首次运行
首次运行应用时，将会下载必要的语音识别模型文件。这个过程需要网络连接，请耐心等待。
下载完成后，应用将自动启动。后续启动将不再需要下载模型。

## 使用方法
1. 选择目标语言和音色
2. 点击"开始同传"按钮
3. 对着麦克风说话，应用会自动识别并翻译
4. 翻译结果将显示在界面上并通过声音播放
5. 完成时点击"停止同传"按钮

## 系统要求
- Windows 7/8/10/11
- 麦克风和扬声器
- 网络连接（用于翻译和语音合成）

## 常见问题
- 如果应用无法启动，可能需要安装Microsoft Visual C++ Redistributable最新版
- 如果出现"模型加载失败"，请检查网络连接，并确保应用具有网络访问权限
- 首次运行时，应用需要下载约300MB的模型文件，请确保有足够的磁盘空间和网络带宽

## 联系与支持
如遇到问题，请查看应用窗口中的日志信息，或联系应用开发者获取支持。
"""

    try:
        # 确保dist/同声传译应用目录存在
        dist_dir = os.path.join("dist", "同声传译应用")
        os.makedirs(dist_dir, exist_ok=True)

        with open(os.path.join(dist_dir, "README.txt"), "w", encoding="utf-8") as f:
            f.write(readme_content)
        print("说明文件创建成功")
        return True
    except Exception as e:
        print(f"创建说明文件时出错: {e}")
        return False


def cleanup():
    """清理临时文件"""
    print_step("清理临时文件")

    try:
        # 删除PyInstaller生成的临时文件
        if os.path.exists("build"):
            shutil.rmtree("build")

        # 删除spec文件
        spec_file = "同声传译应用.spec"
        if os.path.exists(spec_file):
            os.remove(spec_file)

        # 删除钩子目录
        if os.path.exists("hooks"):
            shutil.rmtree("hooks")

        # 删除DLL目录
        if os.path.exists("dlls"):
            shutil.rmtree("dlls")

        # 删除临时入口文件
        if os.path.exists("app_entry.py"):
            os.remove("app_entry.py")

        print("临时文件清理完成")
        return True
    except Exception as e:
        print(f"清理临时文件时出错: {e}")
        return False


def create_success_marker():
    """创建打包成功标记文件"""
    try:
        # 确保dist/同声传译应用目录存在
        dist_dir = os.path.join("dist", "同声传译应用")
        os.makedirs(dist_dir, exist_ok=True)

        # 获取当前时间和系统信息
        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
        sys_info = f"{platform.system()} {platform.release()} {platform.version()}"
        python_version = platform.python_version()

        # 创建标记文件
        with open(os.path.join(dist_dir, "build_info.txt"), "w", encoding="utf-8") as f:
            f.write(f"同声传译应用打包信息\n")
            f.write(f"-------------------\n")
            f.write(f"打包时间: {current_time}\n")
            f.write(f"操作系统: {sys_info}\n")
            f.write(f"Python版本: {python_version}\n")
            f.write(f"打包工具: PyInstaller\n")

        print("创建打包成功标记文件")
        return True
    except Exception as e:
        print(f"创建标记文件时出错: {e}")
        return False


def main():
    """主函数"""
    start_time = time.time()

    print("\n" + "*" * 80)
    print(f"{'同声传译应用一键打包工具 (最终版)':^78}")
    print("*" * 80 + "\n")

    print(f"操作系统: {platform.system()} {platform.version()}")
    print(f"Python版本: {platform.python_version()}")
    print(f"当前目录: {os.getcwd()}\n")

    # 检查必要文件
    required_files = ["FunASR.py", "translation_module.py", "edge_TTS.py", "simultaneous_translator_app.py"]
    missing_files = [f for f in required_files if not os.path.exists(f)]

    if missing_files:
        print(f"错误: 缺少以下必要文件: {', '.join(missing_files)}")
        return

    # 执行打包步骤
    steps = [
        ("安装依赖", install_dependencies),
        ("修复FunASR代码", fix_funasr_code),
        ("创建启动脚本", create_startup_script),
        ("使用PyInstaller打包", build_direct_with_pyinstaller),
        ("创建说明文件", create_readme),
        ("创建成功标记", create_success_marker),
        ("清理临时文件", cleanup)
    ]

    success = True
    for step_name, step_func in steps:
        print(f"正在执行: {step_name}...")
        try:
            result = step_func()
            if not result:
                print(f"步骤 '{step_name}' 失败")
                success = False
                break
        except Exception as e:
            print(f"步骤 '{step_name}' 出错: {e}")
            success = False
            break

    # 打印结果
    elapsed = time.time() - start_time
    print("\n" + "-" * 80)

    if success:
        print(f"✅ 打包成功! 用时: {elapsed:.1f}秒")

        # 检查最终文件位置
        folder_path = os.path.abspath(os.path.join('dist', '同声传译应用'))
        print(f"\n应用文件夹位置: {folder_path}")
        print("\n使用说明:")
        print(f"1. 复制'{folder_path}'整个文件夹到目标计算机")
        print("2. 运行文件夹中的'同声传译应用.exe'文件")
        print("3. 首次运行时，应用将下载所需的模型文件")
    else:
        print(f"❌ 打包失败! 用时: {elapsed:.1f}秒")
        print("\n请查看上面的错误信息，修复问题后重试")

    print("-" * 80)


if __name__ == "__main__":
    main()