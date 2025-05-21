"""
高效加载版实时语音识别 Demo - FunASR
----------------------------
本程序采用FunASR.py的高效模型加载方式，同时保留了VAD和标点恢复功能。
通过延迟加载和预缓存策略，大幅提高了启动速度。

使用方法:
- 按回车开始录音
- 对着麦克风说话
- 再次按回车停止录音

依赖库:
- funasr
- sounddevice
- numpy
"""

from funasr import AutoModel
import sounddevice as sd
import numpy as np
import threading
import time
import queue
import os


class FastLoadASR:
    def __init__(self, use_vad=True, use_punc=True, disable_update=True, text_output_callback=None, max_segment_duration_seconds=7.0):
        """
        初始化快速加载版语音识别系统

        参数:
            use_vad: 是否使用语音端点检测
            use_punc: 是否使用标点恢复
            disable_update: 是否禁用FunASR更新检查(加速启动)
            text_output_callback: 识别文本输出的回调函数
            max_segment_duration_seconds: 最大语音片段时长（秒），用于强制分段 (新增)
        """
        # 功能开关
        self.use_vad = use_vad
        self.use_punc = use_punc
        self.disable_update = disable_update
        self.text_output_callback = text_output_callback
        self.max_segment_duration_seconds = max_segment_duration_seconds # 新增

        # 语音识别参数设置
        self.sample_rate = 16000  # 采样率(Hz)

        # ASR参数
        self.asr_chunk_size = [0, 10, 5]  # 流式设置：[0, 10, 5] = 600ms
        self.encoder_chunk_look_back = 4
        self.decoder_chunk_look_back = 1

        # VAD参数
        self.vad_chunk_duration_ms = 200  # VAD每个音频块的持续时间(毫秒)
        self.vad_chunk_samples = int(self.sample_rate * self.vad_chunk_duration_ms / 1000)

        # ASR参数
        self.asr_chunk_duration_ms = 600  # 每个ASR音频块的持续时间(毫秒)
        self.asr_chunk_samples = int(self.sample_rate * self.asr_chunk_duration_ms / 1000)

        # 运行时变量
        self.running = False
        self.audio_queue = queue.Queue()
        self.complete_transcript = "" # 每次识别会话（start->stop)的完整记录
        self.current_sentence_transcript = "" # 当前正在形成的句子
        self.raw_transcript = ""
        self.is_speaking = False
        self.speech_buffer = np.array([], dtype=np.float32)
        self.current_segment_start_time = None # 新增：用于追踪当前（VAD定义的）语音片段开始时间
        self.last_forced_segment_time = 0 # 新增: 用于记录上次强制分段的时间

        # 模型变量
        self.asr_model = None
        self.vad_model = None
        self.punc_model = None
        self.vad_cache = {}
        self.asr_cache = {}

        # 设置环境变量以加快加载
        if self.disable_update:
            os.environ["FUNASR_DISABLE_UPDATE"] = "True"

        # 异步预加载ASR模型
        print("开始加载ASR模型...")
        self.asr_load_thread = threading.Thread(target=self.load_asr_model)
        self.asr_load_thread.daemon = True
        self.asr_load_thread.start()

    def load_asr_model(self):
        """加载ASR模型的线程函数"""
        try:
            # 使用与FunASR.py相同的加载方式
            self.asr_model = AutoModel(model="paraformer-zh-streaming")
            print("ASR模型加载完成!")
        except Exception as e:
            print(f"ASR模型加载失败: {e}")

    def ensure_asr_model_loaded(self):
        """确保ASR模型已加载"""
        if self.asr_model is None:
            print("等待ASR模型加载完成...")
            if hasattr(self, 'asr_load_thread'):
                self.asr_load_thread.join()

            # 如果线程结束后模型仍未加载，再次尝试加载
            if self.asr_model is None:
                print("重新尝试加载ASR模型...")
                try:
                    self.asr_model = AutoModel(model="paraformer-zh-streaming")
                    print("ASR模型加载完成!")
                except Exception as e:
                    print(f"ASR模型加载失败: {e}")
                    return False
        return True

    def load_vad_model_if_needed(self):
        """仅在需要时加载VAD模型"""
        if self.use_vad and self.vad_model is None:
            print("加载VAD模型...")
            try:
                self.vad_model = AutoModel(model="fsmn-vad")
                print("VAD模型加载完成!")
                return True
            except Exception as e:
                print(f"VAD模型加载失败: {e}")
                return False
        return True

    def load_punc_model_if_needed(self):
        """仅在需要时加载标点恢复模型"""
        if self.use_punc and self.punc_model is None:
            print("加载标点恢复模型...")
            try:
                self.punc_model = AutoModel(model="ct-punc")
                print("标点恢复模型加载完成!")
                return True
            except Exception as e:
                print(f"标点恢复模型加载失败: {e}")
                return False
        return True

    def audio_callback(self, indata, frames, time, status):
        """音频流回调函数"""
        if status:
            print(f"音频状态: {status}")
        # 将音频数据放入队列
        self.audio_queue.put(indata.copy())

    def process_audio_thread(self):
        """音频处理线程"""
        vad_buffer = np.array([], dtype=np.float32)

        while self.running:
            try:
                audio_chunk_processed_this_loop = False
                while not self.audio_queue.empty() and self.running:
                    chunk = self.audio_queue.get_nowait()
                    audio_chunk_processed_this_loop = True
                    if self.use_vad:
                        vad_buffer = np.append(vad_buffer, chunk.flatten())
                    else:
                        # 不使用VAD时，直接将音频块添加到语音缓冲区
                        self.speech_buffer = np.append(self.speech_buffer, chunk.flatten())
                        if self.current_segment_start_time is None: # For non-VAD, start timing on first audio
                            self.current_segment_start_time = time.time()

                # 使用VAD处理
                if self.use_vad and self.vad_model is not None:
                    while len(vad_buffer) >= self.vad_chunk_samples and self.running:
                        # 提取一个VAD音频块
                        vad_chunk = vad_buffer[:self.vad_chunk_samples]
                        vad_buffer = vad_buffer[self.vad_chunk_samples:]
                        audio_chunk_processed_this_loop = True

                        # 使用VAD模型处理
                        vad_res = self.vad_model.generate(
                            input=vad_chunk,
                            cache=self.vad_cache,
                            is_final=False,
                            chunk_size=self.vad_chunk_duration_ms
                        )

                        # 处理VAD结果
                        if len(vad_res[0]["value"]):
                            # 有语音活动检测结果
                            for segment_info in vad_res[0]["value"]:
                                if segment_info[0] != -1 and segment_info[1] == -1:
                                    # 检测到语音开始
                                    if not self.is_speaking: # Check to only set start_time once per segment
                                        self.is_speaking = True
                                        self.current_segment_start_time = time.time()
                                        # self.last_forced_segment_time = self.current_segment_start_time # Reset forced time
                                        print("\n检测到语音开始 (VAD)...")
                                elif segment_info[0] == -1 and segment_info[1] != -1:
                                    # 检测到语音结束
                                    if self.is_speaking: # Process only if we were speaking
                                        self.is_speaking = False
                                        self.current_segment_start_time = None # Reset segment start time
                                        print("\n检测到语音结束 (VAD)...")
                                        if len(self.speech_buffer) > 0:
                                            print("VAD结束，处理剩余ASR缓冲区...")
                                            self.process_asr_buffer(is_final=True)
                        # 如果正在说话，将当前块添加到语音缓冲区
                        if self.is_speaking:
                            self.speech_buffer = np.append(self.speech_buffer, vad_chunk)
                else:
                    # 不使用VAD时，总是处于"说话"状态
                    if len(self.speech_buffer) > 0 and self.current_segment_start_time is None:
                         self.current_segment_start_time = time.time() # Start timing if buffer has data
                    self.is_speaking = True

                # 如果语音缓冲区足够大，进行ASR处理
                if len(self.speech_buffer) >= self.asr_chunk_samples:
                    self.process_asr_buffer()
                    audio_chunk_processed_this_loop = True

                # Max segment duration check (only if speaking or if no VAD and buffer exists)
                if self.is_speaking and self.current_segment_start_time is not None:
                    current_time = time.time()
                    segment_duration = current_time - self.current_segment_start_time
                    # Also consider time since last forced segment to avoid rapid successive forced cuts
                    time_since_last_force = current_time - self.last_forced_segment_time 

                    if segment_duration > self.max_segment_duration_seconds and time_since_last_force > self.max_segment_duration_seconds / 2.0: # Ensure not too close forced cuts
                        print(f"\n片段达到最大时长 ({segment_duration:.2f}s > {self.max_segment_duration_seconds}s)，强制结束当前片段...")
                        if len(self.speech_buffer) > 0:
                            self.process_asr_buffer(is_final=True) # Process current buffer as final
                        # Reset timing for the *next* segment, which starts now conceptually
                        self.current_segment_start_time = time.time() 
                        self.last_forced_segment_time = current_time
                        # If using VAD, is_speaking might still be true. We don't reset it here,
                        # VAD should eventually detect silence or another forced cut will occur.
                        # If not using VAD, this effectively restarts the segment timer.

                if not audio_chunk_processed_this_loop:
                    time.sleep(0.01) # Sleep if no audio was processed in this loop iteration
            except queue.Empty:
                if self.running: # Only sleep if running and queue is empty
                    time.sleep(0.01)
                continue
            except Exception as e:
                print(f"\n音频处理错误: {e}")
                if not self.running: break
                time.sleep(0.1) # Avoid busy loop on other errors

    def process_asr_buffer(self, is_final=False):
        """处理语音缓冲区进行ASR识别"""
        if self.asr_model is None:
            return

        try:
            # 如果没有足够的样本而且不是最终处理，则返回
            # 或者说，如果是final，即使样本不足也要处理完剩余的
            if len(self.speech_buffer) == 0 and is_final:
                 # 如果是最后一块，且buffer为空，可能VAD已经处理过最后一块，直接判断是否有未发送的 current_sentence
                if self.current_sentence_transcript and self.text_output_callback:
                    print(f"ASR Final (empty buffer, pending sentence): {self.current_sentence_transcript}")
                    # Force punctuation on this pending sentence if is_final and punc enabled
                    final_text_to_send = self.current_sentence_transcript
                    if self.use_punc and self.punc_model is not None:
                        punc_res = self.punc_model.generate(input=self.current_sentence_transcript)
                        if punc_res and punc_res[0]["text"]:
                            final_text_to_send = punc_res[0]["text"]
                    self.text_output_callback(final_text_to_send, final_text_to_send, True)
                    self.complete_transcript += final_text_to_send + " "
                self.current_sentence_transcript = "" # Always reset on final with empty buffer
                self.asr_cache = {} # Reset ASR cache on final segment
                return
            
            if len(self.speech_buffer) < self.asr_chunk_samples and not is_final:
                return

            # 如果不是最终处理，提取一个ASR块
            if not is_final:
                asr_chunk = self.speech_buffer[:self.asr_chunk_samples]
                self.speech_buffer = self.speech_buffer[self.asr_chunk_samples:]
            else:
                # 如果是最终处理，使用整个缓冲区
                asr_chunk = self.speech_buffer
                self.speech_buffer = np.array([], dtype=np.float32)

            # 使用ASR模型处理
            if len(asr_chunk) > 0:
                asr_res = self.asr_model.generate(
                    input=asr_chunk,
                    cache=self.asr_cache,
                    is_final=is_final, # 重要：告知ASR模型是否为最后一块
                    chunk_size=self.asr_chunk_size,
                    encoder_chunk_look_back=self.encoder_chunk_look_back,
                    decoder_chunk_look_back=self.decoder_chunk_look_back
                )

                # 如果有识别结果，处理并应用标点
                if asr_res and asr_res[0]["text"]:
                    segment_text = asr_res[0]["text"]
                    
                    # 流式输出时，ASR可能返回不完整的片段
                    # 标点模型通常需要更完整的句子上下文
                    # 我们这里将 segment_text 认为是当前识别到的新片段

                    if self.use_punc and self.punc_model is not None and is_final:
                        # 仅在is_final时对累积的current_sentence_transcript应用标点
                        # 或者如果asr_res表明这是一个完整的句子结束点 (FunASR的流式模型可能不会明确给这个信息)
                        # 这里简化处理：is_final 才用标点，或者当检测到语音结束时 (VAD驱动的is_final)
                        full_input_for_punc = self.current_sentence_transcript + segment_text
                        punc_res = self.punc_model.generate(input=full_input_for_punc)
                        if punc_res and punc_res[0]["text"]:
                            final_text_segment = punc_res[0]["text"]
                            if self.text_output_callback:
                                # 回调参数：当前处理好的片段，完整的当前句子，是否句子结束
                                self.text_output_callback(final_text_segment, final_text_segment, True)
                            self.complete_transcript += final_text_segment + (" " if final_text_segment else "")
                            self.current_sentence_transcript = "" # 重置当前句子
                        else:
                            # 标点失败，回退到无标点文本
                            final_text_segment = full_input_for_punc
                            if self.text_output_callback:
                                self.text_output_callback(final_text_segment, final_text_segment, True)
                            self.complete_transcript += final_text_segment + (" " if final_text_segment else "")
                            self.current_sentence_transcript = "" # 重置当前句子
                    elif not is_final:
                        # 非最终块，累积到 current_sentence_transcript
                        self.current_sentence_transcript += segment_text
                        if self.text_output_callback: # 实时反馈（可能是未标点的）
                             self.text_output_callback(segment_text, self.current_sentence_transcript, False)
                    else: # is_final and no punctuation
                        final_text_segment = self.current_sentence_transcript + segment_text
                        if self.text_output_callback:
                            self.text_output_callback(final_text_segment, final_text_segment, True)
                        self.complete_transcript += final_text_segment + (" " if final_text_segment else "")
                        self.current_sentence_transcript = ""

            elif is_final and self.current_sentence_transcript: # 如果asr_chunk为空，但is_final且有累积的句子
                # 这通常发生在VAD检测到语音结束，且speech_buffer中剩余部分不足一个asr_chunk_samples
                # 或者asr_chunk处理后没有新文本，但仍需处理累积的句子
                if self.use_punc and self.punc_model is not None:
                    punc_res = self.punc_model.generate(input=self.current_sentence_transcript)
                    if punc_res and punc_res[0]["text"]:
                        final_text_segment = punc_res[0]["text"]
                    else:
                        final_text_segment = self.current_sentence_transcript # 标点失败
                else:
                    final_text_segment = self.current_sentence_transcript
                
                if self.text_output_callback:
                    self.text_output_callback(final_text_segment, final_text_segment, True)
                self.complete_transcript += final_text_segment + (" " if final_text_segment else "")
                self.current_sentence_transcript = ""

        except Exception as e:
            print(f"\nASR处理错误: {e}")

    def start(self):
        """开始录音和识别"""
        if not self.ensure_asr_model_loaded():
            print("ASR模型未加载，无法启动。")
            return
        
        # 按需加载VAD和PUNC模型 (如果应用在启动时没有预加载)
        if self.use_vad and not self.vad_model:
            if not self.load_vad_model_if_needed():
                print("警告: VAD模型加载失败，将不使用VAD功能。")
                self.use_vad = False # Fallback to no VAD
        if self.use_punc and not self.punc_model:
            if not self.load_punc_model_if_needed():
                print("警告: 标点模型加载失败，将不使用标点恢复功能。")
                self.use_punc = False # Fallback to no punctuation

        print("\n按回车键开始/停止录音...")
        # 清空之前的状态
        self.audio_queue = queue.Queue() # 清空音频队列
        self.speech_buffer = np.array([], dtype=np.float32)
        self.vad_cache = {} # 重置VAD缓存
        self.asr_cache = {} # 重置ASR缓存
        self.complete_transcript = "" # 重置完整转录
        self.current_sentence_transcript = "" # 重置当前句子
        self.is_speaking = False if self.use_vad else True # Start as speaking if no VAD
        self.current_segment_start_time = None if self.use_vad else time.time() # Init time if no VAD
        self.last_forced_segment_time = time.time() # Initialize to current time to allow first segment up to max_duration

        self.running = True

        # 启动音频处理线程
        self.process_audio_thread_instance = threading.Thread(target=self.process_audio_thread)
        self.process_audio_thread_instance.daemon = True
        self.process_audio_thread_instance.start()

        # 启动音频录制
        try:
            self.stream = sd.InputStream(
                callback=self.audio_callback,
                channels=1,
                samplerate=self.sample_rate,
                dtype='float32'
            )
            self.stream.start()
            print("录音设备已启动，正在聆听...")
        except Exception as e:
            print(f"启动录音设备失败: {e}")
            self.running = False # 无法启动则停止运行
            if hasattr(self, 'process_audio_thread_instance') and self.process_audio_thread_instance.is_alive():
                self.process_audio_thread_instance.join() # 等待线程结束
            return

    def stop(self):
        """停止录音和识别"""
        print("正在停止录音和识别...")
        self.running = False

        # 停止音频流
        if hasattr(self, 'stream') and self.stream:
            try:
                if not self.stream.stopped:
                    self.stream.stop()
                self.stream.close()
                print("录音设备已停止并关闭。")
            except Exception as e:
                print(f"停止或关闭录音设备时出错: {e}")
            del self.stream

        # 等待音频处理线程结束
        if hasattr(self, 'process_audio_thread_instance') and self.process_audio_thread_instance.is_alive():
            print("等待音频处理线程结束...")
            self.process_audio_thread_instance.join(timeout=2)
            if self.process_audio_thread_instance.is_alive():
                print("警告: 音频处理线程超时未结束。")

        # 处理剩余的音频数据 (确保最后一块被处理)
        print("处理任何剩余的音频数据...")
        if len(self.speech_buffer) > 0 or self.current_sentence_transcript:
            self.process_asr_buffer(is_final=True)
        
        # 清理资源 (模型可以不清，以便下次快速启动，但缓存需要)
        self.vad_cache = {}
        self.asr_cache = {}
        print("FunASR已停止。")


if __name__ == "__main__":
    def demo_callback(segment, full_sentence, is_sentence_end):
        if is_sentence_end:
            print(f"\n[FINAL]: {full_sentence}")
        else:
            # 实时反馈可以更细致，例如只打印segment，或者更新同一行
            print(f"[REALTIME]: {full_sentence} ...", end='\r')

    # Test with a shorter max segment duration
    asr_system = FastLoadASR(use_vad=True, use_punc=True, 
                              text_output_callback=demo_callback, 
                              max_segment_duration_seconds=5.0) 
    
    try:
        print("FunASR 命令行测试 (带回调和5s强制分段)。按Ctrl+C退出。")
        asr_system.start()
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n用户请求中断...")
    finally:
        if asr_system.running:
            asr_system.stop()
        print("程序退出。")