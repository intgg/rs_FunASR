import tkinter as tk
from tkinter import ttk, scrolledtext
import asyncio
import threading
import queue
import time # Added for sleep in worker threads on error

# 尝试导入现有模块
try:
    from FunASR import FastLoadASR
    # Placeholder for FunASR modification: FunASR will need a way to callback/put results to this app
except ImportError:
    print("警告: FunASR.py 未找到或无法导入。语音识别功能将不可用。")
    FastLoadASR = None

try:
    from translation_module import TranslationModule, LANGUAGE_CODES, LANGUAGE_NAMES
    # TODO: Replace with your actual API keys for translation_module
    TRANSLATION_APP_ID = "86c79fb7"  # <--- 在此处替换您的 APPID
    TRANSLATION_API_SECRET = "MDY3ZGFkYWEyZDBiOTJkOGIyOTllOWMz" # <--- 在此处替换您的 API_SECRET
    TRANSLATION_API_KEY = "f4369644e37eddd43adfe436e7904cf1"   # <--- 在此处替换您的 API_KEY
except ImportError:
    print("警告: translation_module.py 未找到或无法导入。翻译功能将不可用。")
    TranslationModule = None
    LANGUAGE_CODES = {"中文": "cn", "英语": "en"} # Fallback
    LANGUAGE_NAMES = {"cn": "中文", "en": "英语"} # Fallback

try:
    import edge_TTS
    # We will call edge_TTS.get_available_languages() and edge_TTS.list_voices_by_language()
    # and edge_TTS.text_to_speech()
except ImportError:
    print("警告: edge_TTS.py 未找到或无法导入。语音合成功能将不可用。")
    edge_TTS = None

class SimultaneousTranslatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("同声传译应用")
        self.root.geometry("800x700")

        self.is_running = False
        # self.asr_instance = None # Will be initialized below
        self.translation_instance = None

        # Initialize Translation Module
        if TranslationModule and TRANSLATION_APP_ID != "YOUR_APP_ID" and TRANSLATION_API_KEY != "YOUR_API_KEY" and TRANSLATION_API_SECRET != "YOUR_API_SECRET":
            self.translation_instance = TranslationModule(
                app_id=TRANSLATION_APP_ID,
                api_secret=TRANSLATION_API_SECRET,
                api_key=TRANSLATION_API_KEY
            )
        else:
            print("警告: 翻译模块API密钥未配置或模块导入失败。翻译功能将不可用。")
            if TRANSLATION_APP_ID == "YOUR_APP_ID":
                print("请在 simultaneous_translator_app.py 中设置 TRANSLATION_APP_ID, TRANSLATION_API_SECRET, 和 TRANSLATION_API_KEY")

        self.asr_output_queue = queue.Queue()
        self.translation_output_queue = queue.Queue()

        self.current_recognized_sentence = ""
        self.last_final_asr_text = ""
        self.recognized_text_has_interim = False

        # --- UI Elements ---
        control_frame = ttk.Frame(root, padding="10")
        control_frame.pack(fill=tk.X)

        lang_frame = ttk.Frame(control_frame)
        lang_frame.pack(fill=tk.X)

        ttk.Label(lang_frame, text="源语言:").pack(side=tk.LEFT, padx=(0,5))
        self.source_lang_var = tk.StringVar(value="中文 (FunASR)")
        ttk.Entry(lang_frame, textvariable=self.source_lang_var, state="readonly", width=15).pack(side=tk.LEFT, padx=(0,10))

        ttk.Label(lang_frame, text="目标语言:").pack(side=tk.LEFT, padx=(0,5))
        self.target_lang_var = tk.StringVar()
        self.target_lang_dropdown = ttk.Combobox(lang_frame, textvariable=self.target_lang_var, state="readonly", width=12)
        self.target_lang_dropdown.pack(side=tk.LEFT, padx=(0,10))
        self.target_lang_dropdown.bind("<<ComboboxSelected>>", self.on_target_language_selected)

        ttk.Label(lang_frame, text="目标音色:").pack(side=tk.LEFT, padx=(0,5))
        self.tts_voice_var = tk.StringVar()
        self.tts_voice_dropdown = ttk.Combobox(lang_frame, textvariable=self.tts_voice_var, state="readonly", width=35)
        self.tts_voice_dropdown.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0,10))

        self.start_stop_button = ttk.Button(control_frame, text="开始同传", command=self.toggle_translation, width=12)
        self.start_stop_button.pack(side=tk.RIGHT, padx=(10,0))
        
        text_frame = ttk.Frame(root, padding="5")
        text_frame.pack(fill=tk.BOTH, expand=True)
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(1, weight=1)
        text_frame.rowconfigure(3, weight=1)
        text_frame.rowconfigure(5, weight=1)

        ttk.Label(text_frame, text="识别结果 (源语言):").grid(row=0, column=0, sticky=tk.W, padx=5, pady=(5,0))
        self.recognized_text_area = scrolledtext.ScrolledText(text_frame, height=8, wrap=tk.WORD, state="disabled")
        self.recognized_text_area.grid(row=1, column=0, sticky="nsew", padx=5, pady=(0,5))

        ttk.Label(text_frame, text="翻译结果 (目标语言):").grid(row=2, column=0, sticky=tk.W, padx=5, pady=(5,0))
        self.translated_text_area = scrolledtext.ScrolledText(text_frame, height=8, wrap=tk.WORD, state="disabled")
        self.translated_text_area.grid(row=3, column=0, sticky="nsew", padx=5, pady=(0,5))
        
        ttk.Label(text_frame, text="日志与状态:").grid(row=4, column=0, sticky=tk.W, padx=5, pady=(10,0))
        self.log_text_area = scrolledtext.ScrolledText(text_frame, height=6, wrap=tk.WORD, state="disabled")
        self.log_text_area.grid(row=5, column=0, sticky="nsew", padx=5, pady=(0,5))
        # --- End of UI Elements from previous version ---

        self.async_loop_thread = None
        self.async_loop = None
        if edge_TTS:
            self.start_asyncio_loop()

        self.populate_target_languages()
        self.root.after(100, self.process_ui_updates)
        self.log_message("应用已初始化。")

        # Initialize ASR Instance and load models once
        self.asr_instance = None
        if FastLoadASR:
            self.log_message("正在初始化 FunASR 实例...")
            try:
                # Pass the callback here if FunASR supports it in __init__
                # The current FunASR takes text_output_callback in __init__
                self.asr_instance = FastLoadASR(
                    use_vad=True,
                    use_punc=True,
                    text_output_callback=self.asr_text_callback
                    # Add max_speech_segment_duration_seconds if we implement it in FunASR
                )
                # Asynchronously ensure ASR model is loaded
                # FunASR's __init__ already starts loading asr_model in a thread.
                # ensure_asr_model_loaded will wait for it if not done.
                # We might want a separate thread for all model checks if they block UI.
                threading.Thread(target=self._initial_model_load, daemon=True).start()
            except Exception as e:
                self.log_message(f"创建FunASR实例失败: {e}")
                self.asr_instance = None
        else:
            self.log_message("错误: FunASR 模块未找到，语音识别不可用。", True)


    def _initial_model_load(self):
        if self.asr_instance:
            self.log_message("正在加载ASR主模型 (如果尚未加载)...")
            if not self.asr_instance.ensure_asr_model_loaded():
                self.log_message("ASR主模型加载失败。", True)
                # self.asr_instance = None # Or handle error appropriately
                return # Stop further model loading if main one fails

            self.log_message("ASR主模型已就绪或正在加载。") # ensure_asr_model_loaded blocks until loaded or failed

            if self.asr_instance.use_vad:
                self.log_message("正在加载VAD模型 (如果需要)...")
                if not self.asr_instance.load_vad_model_if_needed():
                    self.log_message("VAD模型加载失败。", True)
                else:
                    self.log_message("VAD模型已就绪或已加载。")
            
            if self.asr_instance.use_punc:
                self.log_message("正在加载标点模型 (如果需要)...")
                if not self.asr_instance.load_punc_model_if_needed():
                    self.log_message("标点模型加载失败。", True)
                else:
                    self.log_message("标点模型已就绪或已加载。")
            self.log_message("所有配置的ASR相关模型已检查/加载。")
        else:
            self.log_message("ASR实例未创建，无法加载模型。")

    def log_message(self, message, is_status=True):
        print(message) 
        self.root.after(0, self._update_log_area, message + "\n")
        if is_status:
             pass 

    def _update_log_area(self, message):
        self.log_text_area.config(state="normal")
        self.log_text_area.insert(tk.END, message)
        self.log_text_area.see(tk.END)
        self.log_text_area.config(state="disabled")

    def start_asyncio_loop(self):
        def loop_runner():
            self.async_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.async_loop)
            try:
                self.async_loop.run_forever()
            finally:
                self.async_loop.close()
        self.async_loop_thread = threading.Thread(target=loop_runner, daemon=True)
        self.async_loop_thread.start()
        self.log_message("Asyncio事件循环已启动。")

    def run_async_task(self, coro):
        if not self.async_loop or not self.async_loop.is_running():
            self.log_message("错误: Asyncio事件循环未运行。")
            return None
        return asyncio.run_coroutine_threadsafe(coro, self.async_loop)

    def populate_target_languages(self):
        if TranslationModule and LANGUAGE_CODES:
            self.target_lang_dropdown['values'] = list(LANGUAGE_CODES.keys())
            if self.target_lang_dropdown['values']:
                self.target_lang_var.set(self.target_lang_dropdown['values'][0])
                self.on_target_language_selected(None)
        else:
            self.log_message("翻译模块或语言代码不可用，无法加载目标语言。")
            self.target_lang_dropdown['values'] = ["N/A"]
            self.target_lang_var.set("N/A")

    async def _fetch_voices_async(self, lang_code_for_tts):
        if not edge_TTS:
            self.log_message("edge_TTS模块不可用。")
            return []
        self.log_message(f"正在为语言代码 {lang_code_for_tts} 获取音色...")
        tts_lang_map = {
            "cn": "zh-CN", "en": "en-US", "ja": "ja-JP", "es": "es-ES",
            "fr": "fr-FR", "de": "de-DE", "ko": "ko-KR", "ru": "ru-RU",
        }
        effective_lang_code = tts_lang_map.get(lang_code_for_tts.lower(), lang_code_for_tts)
        try:
            voices_list = await edge_TTS.list_voices_by_language(effective_lang_code)
            if not voices_list and "-" not in effective_lang_code: 
                 voices_list = await edge_TTS.list_voices_by_language(lang_code_for_tts)
            if voices_list:
                voice_names = [v['ShortName'] for v in voices_list]
                self.log_message(f"为 {effective_lang_code} 找到 {len(voice_names)} 个音色。")
                return voice_names
            else:
                self.log_message(f"未找到语言代码 {effective_lang_code} (或 {lang_code_for_tts}) 的音色。")
                return []
        except Exception as e:
            self.log_message(f"获取音色时出错 ({effective_lang_code}): {e}")
            return []

    def on_target_language_selected(self, event):
        selected_language_name = self.target_lang_var.get()
        if not TranslationModule or not edge_TTS or not selected_language_name or selected_language_name == "N/A":
            self.tts_voice_dropdown['values'] = []
            self.tts_voice_var.set("")
            return
        lang_code = LANGUAGE_CODES.get(selected_language_name)
        if not lang_code:
            self.log_message(f"未知目标语言名称: {selected_language_name}")
            return
        future = self.run_async_task(self._fetch_voices_async(lang_code))
        if future:
            def update_voices_ui(f):
                try:
                    voice_names = f.result()
                    self.tts_voice_dropdown['values'] = voice_names
                    if voice_names:
                        self.tts_voice_var.set(voice_names[0])
                    else:
                        self.tts_voice_var.set("")
                except Exception as e:
                    self.log_message(f"更新音色UI时出错: {e}")
            self._check_future_for_ui(future, update_voices_ui)

    def _check_future_for_ui(self, future, callback):
        if future.done():
            self.root.after(0, lambda: callback(future))
        else:
            self.root.after(100, self._check_future_for_ui, future, callback)

    def toggle_translation(self):
        if self.is_running:
            self.stop_translation_process()
        else:
            self.start_translation_process()

    def start_translation_process(self):
        if not self.asr_instance: # Check if ASR instance was created
            self.log_message("错误：FunASR实例未初始化，无法开始。", True)
            return
        if not self.translation_instance:
            self.log_message("错误：翻译模块未初始化（请检查API密钥），无法开始。", True)
            return
        if not edge_TTS:
            self.log_message("错误：edge_TTS模块未加载，无法开始。", True)
            return
        if not self.target_lang_var.get() or self.target_lang_var.get() == "N/A" or not self.tts_voice_var.get():
            self.log_message("错误：请选择有效的目标语言和音色。", True)
            return
        
        # Ensure models are loaded before starting session (if not already by _initial_model_load)
        # This check might be redundant if _initial_model_load is guaranteed to finish and succeed.
        # However, it's a safeguard.
        if not self.asr_instance.asr_model: # Check if the main ASR model is loaded
            self.log_message("ASR主模型尚未加载完成，请稍候...", True)
            # Optionally, could try to trigger load again or just wait.
            # For now, we assume _initial_model_load handles this.
            # A more robust way would be to disable start button until models are ready.
            if not self.asr_instance.ensure_asr_model_loaded(): # blocking call
                 self.log_message("ASR主模型加载失败，无法启动。", True)
                 return


        self.is_running = True
        self.start_stop_button.config(text="停止同传")
        self.log_message("正在启动同声传译服务...", True)
        
        self._update_text_area(self.recognized_text_area, "", clear_all=True)
        self._update_text_area(self.translated_text_area, "", clear_all=True)
        self.current_recognized_sentence = ""
        self.last_final_asr_text = ""
        self.recognized_text_has_interim = False

        # Start ASR instance (this should reset its internal state, not reload models)
        try:
            # FunASR's start method should handle starting the recording and processing threads.
            # It should also reset internal states like buffers and caches.
            threading.Thread(target=self.asr_instance.start, daemon=True).start()
            self.log_message("同声传译已启动。 FunASR正在聆听...", True)
        except Exception as e:
            self.log_message(f"启动FunASR失败: {e}", True)
            self.is_running = False
            self.start_stop_button.config(text="开始同传")
            return
        
        # Start worker threads for translation and TTS
        threading.Thread(target=self.translation_worker, daemon=True).start()
        threading.Thread(target=self.tts_worker, daemon=True).start()

    def stop_translation_process(self):
        self.log_message("正在停止同声传译服务...", True)
        if self.asr_instance and self.is_running: 
            try:
                self.asr_instance.stop() # This should stop recording and processing in FunASR
            except Exception as e:
                self.log_message(f"停止FunASR时出错: {e}")
        
        self.is_running = False # Set to false to signal worker threads to stop
        self.start_stop_button.config(text="开始同传")
        
        # Clear queues after stopping ASR and setting is_running to false
        # Give a moment for worker threads to see is_running=False and process remaining queue items
        self.root.after(100, self._clear_queues)
        self.log_message("同声传译已停止。", True)

    def _clear_queues(self):
        for q in [self.asr_output_queue, self.translation_output_queue]:
            while not q.empty():
                try: q.get_nowait()
                except queue.Empty: break
        self.log_message("处理队列已清空。")

    def asr_text_callback(self, recognized_segment, current_full_sentence, is_sentence_end):
        if not self.is_running: return

        if is_sentence_end:
            final_text = current_full_sentence.strip()
            if final_text and final_text != self.last_final_asr_text:
                self.log_message(f"ASR (Final): {final_text}")
                self.last_final_asr_text = final_text
                update_mode = 'replace_interim_with_final' if self.recognized_text_has_interim else 'append_final'
                self.root.after(0, lambda: self._update_text_area(self.recognized_text_area, final_text + "\n", mode=update_mode))
                self.asr_output_queue.put(final_text)
                self.recognized_text_has_interim = False
            elif not final_text:
                 self.log_message(f"ASR (Final Empty Ignored)")
                 if self.recognized_text_has_interim:
                    self.root.after(0, lambda: self._update_text_area(self.recognized_text_area, "", mode='clear_interim'))
                 self.recognized_text_has_interim = False
            else: 
                self.log_message(f"ASR (Duplicate Final Ignored): {final_text}")
            self.current_recognized_sentence = "" 
        else: 
            self.current_recognized_sentence = current_full_sentence
            self.log_message(f"ASR (Interim): {recognized_segment}")
            self.root.after(0, lambda: self._update_text_area(self.recognized_text_area, self.current_recognized_sentence, mode='update_interim'))
            self.recognized_text_has_interim = True

    def translation_worker(self):
        while True: 
            try:
                source_text = self.asr_output_queue.get(timeout=0.5)
                if not self.is_running and self.asr_output_queue.empty(): break 
                if not source_text or not self.translation_instance:
                    if not self.is_running: break
                    continue
                from_lang_code = "cn" 
                target_lang_name = self.target_lang_var.get()
                to_lang_code = LANGUAGE_CODES.get(target_lang_name)
                if not to_lang_code:
                    self.log_message(f"翻译错误：无效目标语言 {target_lang_name}")
                    if not self.is_running: break
                    continue
                self.log_message(f"开始翻译: {source_text[:30]}... -> {to_lang_code}")
                try:
                    translated_text = self.translation_instance.translate(
                        text=source_text,
                        from_lang=from_lang_code,
                        to_lang=to_lang_code
                    )
                    if translated_text:
                        self.log_message(f"翻译完成: {translated_text[:30]}...")
                        self.translation_output_queue.put(translated_text)
                        self.root.after(0, lambda t=translated_text: self._update_text_area(self.translated_text_area, t + "\n", mode='append_final'))
                    else:
                        self.log_message(f"翻译结果为空 for: {source_text[:30]}")
                except Exception as e:
                    self.log_message(f"翻译API调用失败: {e}")
                self.asr_output_queue.task_done()
            except queue.Empty:
                if not self.is_running: break
                continue 
            except Exception as e:
                self.log_message(f"翻译线程异常: {e}")
                if not self.is_running: break
                time.sleep(0.1) 
        self.log_message("翻译线程已停止。")

    def tts_worker(self):
        while True:
            try:
                translated_text = self.translation_output_queue.get(timeout=0.5)
                if not self.is_running and self.translation_output_queue.empty(): break
                if not translated_text or not edge_TTS:
                    if not self.is_running: break
                    continue
                selected_voice = self.tts_voice_var.get()
                if not selected_voice:
                    self.log_message("TTS错误: 未选择音色。语音无法合成。")
                    if not self.is_running: break
                    continue
                self.log_message(f"开始语音合成: {translated_text[:30]}... (音色: {selected_voice})")
                future = self.run_async_task(
                    edge_TTS.text_to_speech(translated_text, selected_voice)
                )
                if future:
                    try:
                        success = future.result(timeout=30) 
                        if success:
                            self.log_message(f"语音播放成功: {translated_text[:30]}...")
                        else:
                             self.log_message(f"语音合成或播放失败: {translated_text[:30]}")
                    except asyncio.TimeoutError:
                        self.log_message(f"TTS任务超时: {translated_text[:30]}")
                    except Exception as e:
                        self.log_message(f"TTS播放时发生错误: {e}")
                else:
                    self.log_message("无法调度TTS任务进行播放。")
                self.translation_output_queue.task_done()
            except queue.Empty:
                if not self.is_running: break
                continue
            except Exception as e:
                self.log_message(f"TTS线程异常: {e}")
                if not self.is_running: break
                time.sleep(0.1)
        self.log_message("TTS线程已停止。")

    def _update_text_area(self, area, text, mode='append_final', clear_all=False):
        area.config(state="normal")
        if clear_all:
            area.delete(1.0, tk.END)
        elif mode == 'append_final':
            area.insert(tk.END, text)
        elif mode == 'update_interim':
            current_content = area.get(1.0, tk.END).rstrip('\n')
            last_newline_idx = current_content.rfind('\n')
            if not self.recognized_text_has_interim: 
                if current_content and not current_content.endswith('\n'):
                    area.insert(tk.END, "\n") 
                area.insert(tk.END, text) 
            elif last_newline_idx == -1: 
                area.delete(1.0, tk.END)
                area.insert(1.0, text)
            else: 
                area.delete(f"1.0 + {last_newline_idx + 1}c", tk.END) 
                area.insert(tk.END, text) 
        elif mode == 'replace_interim_with_final':
            current_content = area.get(1.0, tk.END).rstrip('\n')
            last_newline_idx = current_content.rfind('\n')
            if last_newline_idx == -1:
                area.delete(1.0, tk.END)
            else:
                area.delete(f"1.0 + {last_newline_idx + 1}c", tk.END)
            current_content_after_delete = area.get(1.0, tk.END).rstrip('\n')
            if current_content_after_delete and not current_content_after_delete.endswith('\n'):
                 area.insert(tk.END, "\n")
            area.insert(tk.END, text) 
        elif mode == 'clear_interim':
            current_content = area.get(1.0, tk.END).rstrip('\n')
            last_newline_idx = current_content.rfind('\n')
            if self.recognized_text_has_interim:
                if last_newline_idx == -1: 
                    area.delete(1.0, tk.END)
                else: 
                    area.delete(f"1.0 + {last_newline_idx + 1}c", tk.END)
        area.see(tk.END)
        area.config(state="disabled")

    def process_ui_updates(self):
        self.root.after(200, self.process_ui_updates) 

    def on_closing(self):
        self.log_message("应用正在关闭...", True)
        self.stop_translation_process() 
        if self.async_loop and self.async_loop.is_running():
            self.log_message("正在停止Asyncio事件循环...")
            self.async_loop.call_soon_threadsafe(self.async_loop.stop)
        if self.async_loop_thread and self.async_loop_thread.is_alive():
            self.log_message("等待Asyncio线程结束...")
            self.async_loop_thread.join(timeout=2)
            if self.async_loop_thread.is_alive():
                self.log_message("警告: Asyncio线程超时未结束。", True)
            else:
                self.log_message("Asyncio线程已停止。")
        self.log_message("正在销毁UI...")
        self.root.destroy()
        print("应用已关闭。")

if __name__ == '__main__':
    root = tk.Tk()
    app = SimultaneousTranslatorApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        print("用户通过Ctrl+C中断mainloop。")
        app.on_closing() 