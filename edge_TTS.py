# 导入所需的库
import asyncio
import edge_tts
import pygame
import io
from pygame import mixer
import sys


async def play_audio_from_memory(audio_data):
    """直接从内存播放音频数据"""
    # 初始化pygame混音器
    mixer.init()

    # 创建内存缓冲区并加载音频数据
    audio_io = io.BytesIO(audio_data)

    # 加载和播放
    print("正在播放语音...")
    mixer.music.load(audio_io)
    mixer.music.play()

    # 等待播放完成
    while mixer.music.get_busy():
        await asyncio.sleep(0.1)

    # 显式关闭以确保资源被释放
    mixer.music.unload()
    print("播放完成！")


async def get_available_languages():
    """获取所有可用的语言"""
    print("正在获取可用语言列表...")
    voices = await edge_tts.VoicesManager.create()

    # 提取语言代码和区域
    languages = {}
    for voice in voices.voices:
        lang_code = voice["Locale"]
        if lang_code not in languages:
            languages[lang_code] = True

    # 转换为列表并排序
    language_list = sorted(languages.keys())
    return language_list


async def list_voices_by_language(language_code):
    """列出指定语言的所有可用音色"""
    voices = await edge_tts.VoicesManager.create()

    # 筛选指定语言的音色
    filtered_voices = [v for v in voices.voices if v["Locale"] == language_code]

    if not filtered_voices:
        print(f"没有找到语言代码为 {language_code} 的音色")
        return None

    print(f"\n可用的 {language_code} 语音音色：")
    print("-" * 80)
    print(f"{'编号':<5}{'语音名称':<25}{'性别':<8}{'友好名称':<30}")
    print("-" * 80)

    for i, voice in enumerate(filtered_voices, 1):
        print(f"{i:<5}{voice['ShortName']:<25}{voice['Gender']:<8}{voice.get('FriendlyName', ''):<30}")

    return filtered_voices


async def text_to_speech(text, voice):
    """将文本转换为语音并直接播放（不保存文件）"""
    print(f"正在使用音色 {voice} 生成语音...")

    try:
        # 创建通信对象
        communicate = edge_tts.Communicate(text, voice)

        # 收集音频数据
        audio_data = bytes()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]

        if not audio_data:
            print("警告：未生成音频数据，可能是文本或语音选择有问题")
            return False

        print("语音生成完成，准备播放...")

        # 直接从内存播放音频
        await play_audio_from_memory(audio_data)
        return True

    except edge_tts.exceptions.NoAudioReceived:
        print("错误：未收到音频数据。可能的原因：")
        print("1. 所选语音不支持输入的文本")
        print("2. 网络连接问题")
        print("3. 请尝试不同的语音或更简短的文本")
        return False
    except Exception as e:
        print(f"错误：生成语音时发生异常: {str(e)}")
        return False


async def main():
    """主函数，交互式运行TTS"""
    print("=== Edge TTS 交互式演示程序 ===")

    while True:
        # 1. 获取用户输入的文本
        text = input("请输入要转换为语音的文本 (输入'退出'结束程序): ")
        if text.lower() in ['退出', 'exit', 'quit']:
            print("程序已退出。")
            break

        # 2. 获取所有可用语言
        languages = await get_available_languages()

        print("\n可用的语言:")
        for i, lang_code in enumerate(languages, 1):
            print(f"{i}. {lang_code}")

        # 3. 让用户选择语言
        while True:
            try:
                language_choice = int(input("\n请选择语言编号: "))
                if 1 <= language_choice <= len(languages):
                    selected_language = languages[language_choice - 1]
                    break
                else:
                    print("无效的选择，请重试")
            except ValueError:
                print("请输入数字")
            except KeyboardInterrupt:
                print("\n程序已中断。")
                sys.exit(0)

        # 4. 列出所选语言的可用音色
        voices = await list_voices_by_language(selected_language)

        if not voices:
            print("没有可用的音色，请选择其他语言")
            continue

        # 5. 让用户选择音色
        while True:
            try:
                voice_choice = int(input("\n请选择音色编号: "))
                if 1 <= voice_choice <= len(voices):
                    selected_voice = voices[voice_choice - 1]["ShortName"]
                    break
                else:
                    print("无效的选择，请重试")
            except ValueError:
                print("请输入数字")
            except KeyboardInterrupt:
                print("\n程序已中断。")
                sys.exit(0)

        # 6. 执行文本到语音转换并播放
        success = await text_to_speech(text, selected_voice)

        if success:
            # 询问是否要继续
            choice = input("\n是否继续使用其他语音或文本? (y/n): ")
            if choice.lower() not in ['y', 'yes', '是', 'continue', '继续']:
                print("程序已退出。")
                break
        else:
            print("尝试其他语音或文本...")


if __name__ == "__main__":
    try:
        # 运行主异步函数
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序已被用户中断。")
    except Exception as e:
        print(f"程序发生错误: {str(e)}")