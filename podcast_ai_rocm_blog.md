# 用 AMD GPU 加速播客转写：一次 ROCm + faster-whisper 工程实践

这个项目的目标很简单：批量处理 Joe Rogan 播客音频，完成英文转写、难词提取、中文释义生成，并把释义语音插回原音频。原始流程基于 `faster-whisper`、`Ollama`、`edge-tts`、`ffmpeg` 和 Python 批处理脚本，CPU 模式能跑，但长音频吞吐偏慢。

## 技术栈

- Python 3.12：主流程、文件扫描、任务调度
- faster-whisper：Whisper `large-v3` 转写
- CTranslate2：Whisper 推理后端
- ROCm/HIP：AMD GPU 计算栈
- AMD Radeon RX 7800 XT：`gfx1101`
- Ollama + `qwen2.5:7b`：难词中文释义
- edge-tts：中文释义语音合成
- ffmpeg / ffprobe：音频切片、探测、合成
- pydub：音频片段处理

## 关键难点

第一个坑是 `device="cuda"`。在 CTranslate2 里，ROCm 版也沿用 `cuda` 这个设备入口，但普通 pip 安装的 `ctranslate2` 实际走的是 NVIDIA CUDA wheel。AMD GPU 上会报：

```text
CUDA driver version is insufficient for CUDA runtime version
```

解决方式是从源码编译 ROCm/HIP 版 CTranslate2，并安装到项目 venv。

第二个坑是编译。ROCm 6.4 + CTranslate2 4.7.1 需要几个补丁和参数：

- 指定 `/opt/rocm/bin/hipcc`
- `-DOPENMP_RUNTIME=COMP`
- `-DHIPBLAS_V2`
- 给 `__syncwarp` 加 HIP 兼容定义
- 把 `/usr/lib/llvm-18/lib` 加到 `LD_LIBRARY_PATH`，解决 `libomp.so`

最终验证：

```python
import ctranslate2
print(ctranslate2.get_cuda_device_count())  # 1
```

并且 `WhisperModel("large-v3", device="cuda", compute_type="float16")` 能成功加载。

第三个坑是 ROCm + 多进程。即使 `max_workers=1`，`ProcessPoolExecutor` 仍会 fork 子进程，而 HIP runtime 对 fork 很敏感，出现过 `BrokenProcessPool` 和 native abort。修复方式是：GPU 模式默认完全不用进程池，主进程串行跑；CPU 模式才保留多进程。

第四个坑是超长音频。连续处理几个 2 小时以上文件后，ROCm 报：

```text
Memory access fault by GPU node-1
```

fault log 显示崩在 `faster_whisper.transcribe.generate_with_fallback`，不是 TTS 或 ffmpeg。最终方案是 GPU 模式默认分块转写：先用 ffmpeg 按 10-15 分钟切片，每块单独 transcribe，再把时间戳加回原音频偏移。

## 最终运行方式

```bash
export JOEROGAN_WHISPER_DEVICE=cuda
export JOEROGAN_WHISPER_COMPUTE_TYPE=float16
export JOEROGAN_WHISPER_CPU_THREADS=1
export JOEROGAN_MAX_WORKERS=1
export JOEROGAN_WHISPER_CHUNK_SECONDS=600
python main_batch.py
```

## 结果

最终流程变成了：GPU 负责 Whisper 转写，Ollama 负责释义，edge-tts 负责语音，ffmpeg 负责切片和合成。通过“ROCm 版 CTranslate2 + 禁用 GPU fork + 长音频分块”，项目从 CPU 单路处理升级为可稳定使用 AMD GPU 的批处理流水线。
