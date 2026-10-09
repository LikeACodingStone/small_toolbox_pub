# AMD GPU / ROCm + faster-whisper 环境搭建笔记

目标：让 `podcast_ai` 项目里的 `faster-whisper` / `CTranslate2` 使用 AMD GPU，通过 ROCm 加速 Whisper `large-v3` 转写。

## 1. 机器与 GPU 信息

通过 `rocm-smi` 和 `rocminfo` 确认：

```bash
rocm-smi
/opt/rocm/bin/hipcc --version
/opt/rocm/bin/rocminfo | grep -E "gfx|Marketing Name|Name:" | head -80
```

实际信息：

```text
GPU: AMD Radeon RX 7800 XT
GPU Arch: gfx1101
ROCm: 6.4.2
HIP version: 6.4.43484
AMD clang: 19.0.0git
CPU: AMD Ryzen 7 5700X
```

结论：ROCm 驱动和 HIP 编译器可用，GPU 可用于 ROCm 计算。

## 2. 项目 Python 环境

项目目录：

```bash
/home/dpc/usr/bin/podcast_ai
```

虚拟环境：

```bash
source /home/dpc/usr/bin/podcast_ai/venv/bin/activate
```

初始检查：

```bash
python - <<'PY'
import sys
import faster_whisper
import ctranslate2

print("python:", sys.executable)
print("faster_whisper:", faster_whisper.__version__)
print("ctranslate2:", ctranslate2.__version__)
print("ctranslate2 file:", ctranslate2.__file__)
print("cuda device count:", ctranslate2.get_cuda_device_count())
PY
```

初始结果：

```text
faster_whisper: 1.2.1
ctranslate2: 4.7.1
cuda device count: 0
```

说明：venv 里的 `ctranslate2` 是普通 pip wheel，不是 ROCm/HIP 构建版。

## 3. 最初遇到的问题

程序日志：

```text
Loading WhisperModel large-v3 device=cuda compute_type=float16 cpu_threads=1
RuntimeError: CUDA failed with error CUDA driver version is insufficient for CUDA runtime version
```

原因：

- `faster-whisper` 底层用 `CTranslate2`
- 普通 pip 安装的 `ctranslate2` GPU wheel 走 NVIDIA CUDA 路径
- AMD GPU 没有 NVIDIA CUDA driver
- 所以 `device="cuda"` 会误走 CUDA 运行时并失败

解决方向：

- 保留业务代码中的 `device="cuda"`
- 但把 `ctranslate2` 换成 ROCm/HIP 编译版
- ROCm 版 CTranslate2 仍然通过 `device="cuda"` 这个入口使用 AMD GPU

## 4. 安装编译工具链

```bash
sudo apt update
sudo apt install -y build-essential cmake ninja-build git python3-dev libopenblas-dev
sudo apt install -y rocm-cmake rocblas-dev hipblas-dev
```

后续还需要：

```bash
sudo apt install -y libomp-dev
```

Python 构建工具：

```bash
cd /home/dpc/usr/bin/podcast_ai
source venv/bin/activate

pip install -U pip setuptools wheel build
```

## 5. 获取 CTranslate2 源码

```bash
mkdir -p ~/src ~/opt
cd ~/src

git clone --recursive https://github.com/OpenNMT/CTranslate2.git
cd CTranslate2
git checkout v4.7.1
git submodule update --init --recursive
```

### 问题：GitHub clone 失败

错误：

```text
Failed to connect to 10.4.103.85 port 8080
```

原因：

- 系统或 Git 配置了代理 `10.4.103.85:8080`
- 代理不可达

调试命令：

```bash
env | grep -Ei 'http_proxy|https_proxy|all_proxy|no_proxy'
git config --global --get http.proxy
git config --global --get https.proxy
```

如果不需要代理：

```bash
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY
git config --global --unset http.proxy
git config --global --unset https.proxy
```

然后重新 clone。

## 6. 编译 CTranslate2 ROCm 版

### 问题：Intel OpenMP 缺失

错误：

```text
Intel OpenMP runtime libiomp5 not found
```

原因：

- CTranslate2 默认尝试找 Intel OpenMP
- AMD/ROCm 路线不需要 Intel OpenMP

修复：cmake 增加：

```bash
-DOPENMP_RUNTIME=COMP
```

### 问题：用了 `/usr/bin/c++` 编译 HIP

错误：

```text
c++: error: unrecognized command-line option '--offload-arch=gfx1101'
```

原因：

- CMake 使用了系统 GCC `/usr/bin/c++`
- GCC 不认识 ROCm HIP 的 `--offload-arch`

修复：显式指定 ROCm 编译器：

```bash
export ROCM_PATH=/opt/rocm
export PATH=/opt/rocm/bin:/opt/rocm/llvm/bin:$PATH
export CC=/opt/rocm/llvm/bin/clang
export CXX=/opt/rocm/bin/hipcc
```

### 问题：ROCm 6.4 API 兼容

错误 1：

```text
error: use of undeclared identifier '__syncwarp'
```

错误 2：

```text
no known conversion from 'hipDataType' to 'hipblasDatatype_t'
```

原因：

- CTranslate2 v4.7.1 的 HIP/CUDA 兼容层和 ROCm 6.4 的部分 API 有差异
- `__syncwarp` 在该编译环境下不可用
- hipBLAS 新接口需要 `HIPBLAS_V2`

修复 1：给 `src/cuda/helpers.h` 加兼容定义。

```bash
cd ~/src/CTranslate2

python3 - <<'PY'
from pathlib import Path

path = Path("src/cuda/helpers.h")
text = path.read_text()

patch = """\
#if defined(__HIP_PLATFORM_AMD__) && !defined(__syncwarp)
#define __syncwarp(mask) __builtin_amdgcn_wave_barrier()
#endif

"""

if "__builtin_amdgcn_wave_barrier" not in text:
    text = text.replace("namespace ctranslate2 {", patch + "namespace ctranslate2 {", 1)
    path.write_text(text)
    print("patched helpers.h")
else:
    print("helpers.h already patched")
PY
```

修复 2：cmake 增加：

```bash
-DCMAKE_CXX_FLAGS="-DHIPBLAS_V2"
-DCMAKE_HIP_FLAGS="-DHIPBLAS_V2"
```

### 最终 cmake 命令

```bash
cd ~/src/CTranslate2
rm -rf build

export ROCM_PATH=/opt/rocm
export PATH=/opt/rocm/bin:/opt/rocm/llvm/bin:$PATH
export CC=/opt/rocm/llvm/bin/clang
export CXX=/opt/rocm/bin/hipcc

cmake -S . -B build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX=$HOME/opt/ctranslate2-rocm \
  -DCMAKE_C_COMPILER=/opt/rocm/llvm/bin/clang \
  -DCMAKE_CXX_COMPILER=/opt/rocm/bin/hipcc \
  -DCMAKE_CXX_FLAGS="-DHIPBLAS_V2" \
  -DCMAKE_HIP_FLAGS="-DHIPBLAS_V2" \
  -DWITH_HIP=ON \
  -DWITH_CUDA=OFF \
  -DWITH_CUDNN=OFF \
  -DWITH_MKL=OFF \
  -DWITH_OPENBLAS=ON \
  -DOPENMP_RUNTIME=COMP \
  -DBUILD_TESTS=OFF \
  -DCMAKE_PREFIX_PATH=/opt/rocm \
  -DCMAKE_HIP_ARCHITECTURES=gfx1101
```

编译和安装：

```bash
cmake --build build -j$(nproc)
cmake --install build
```

## 7. 构建并安装 Python wheel

```bash
cd /home/dpc/usr/bin/podcast_ai
source venv/bin/activate

pip uninstall -y ctranslate2
```

构建 wheel：

```bash
cd ~/src/CTranslate2/python

rm -rf build dist *.egg-info

export CTRANSLATE2_ROOT=$HOME/opt/ctranslate2-rocm
export LD_LIBRARY_PATH=$HOME/opt/ctranslate2-rocm/lib:/opt/rocm/lib:$LD_LIBRARY_PATH
export CMAKE_PREFIX_PATH=$HOME/opt/ctranslate2-rocm:/opt/rocm

python -m build --wheel
```

成功结果：

```text
Successfully built ctranslate2-4.7.1-cp312-cp312-linux_x86_64.whl
```

安装：

```bash
pip install --force-reinstall dist/ctranslate2-4.7.1-cp312-cp312-linux_x86_64.whl
```

## 8. 运行时库问题

### 问题：缺少 `libomp.so`

错误：

```text
ImportError: libomp.so: cannot open shared object file: No such file or directory
```

安装：

```bash
sudo apt install -y libomp-dev
```

查找库：

```bash
find /usr /opt/rocm -name 'libomp.so*' 2>/dev/null
```

结果：

```text
/usr/lib/x86_64-linux-gnu/libomp.so.5
/usr/lib/llvm-18/lib/libomp.so
/usr/lib/llvm-18/lib/libomp.so.5
```

修复：把 `/usr/lib/llvm-18/lib` 加入 `LD_LIBRARY_PATH`。

```bash
export LD_LIBRARY_PATH=/usr/lib/llvm-18/lib:$HOME/opt/ctranslate2-rocm/lib:/opt/rocm/lib:$LD_LIBRARY_PATH
```

写入 venv 自动激活：

```bash
grep -q "ctranslate2-rocm" /home/dpc/usr/bin/podcast_ai/venv/bin/activate || cat >> /home/dpc/usr/bin/podcast_ai/venv/bin/activate <<'EOF'

export LD_LIBRARY_PATH=/usr/lib/llvm-18/lib:$HOME/opt/ctranslate2-rocm/lib:/opt/rocm/lib:$LD_LIBRARY_PATH
EOF
```

## 9. 验证 CTranslate2 是否识别 AMD GPU

```bash
cd /home/dpc/usr/bin/podcast_ai
source venv/bin/activate

python - <<'PY'
import ctranslate2
print("ctranslate2:", ctranslate2.__version__)
print("file:", ctranslate2.__file__)
print("device count:", ctranslate2.get_cuda_device_count())
PY
```

成功结果：

```text
ctranslate2: 4.7.1
device count: 1
```

说明 ROCm 版 CTranslate2 已识别 AMD GPU。

## 10. 验证 faster-whisper

测试 tiny：

```bash
cd /home/dpc/usr/bin/podcast_ai
source venv/bin/activate

python - <<'PY'
from faster_whisper import WhisperModel

print("loading tiny on AMD GPU...")
model = WhisperModel("tiny", device="cuda", compute_type="float16")
print("tiny loaded ok")
PY
```

结果：

```text
loading tiny on AMD GPU...
tiny loaded ok
```

测试 large-v3：

```bash
python - <<'PY'
from faster_whisper import WhisperModel

print("loading large-v3 on AMD GPU...")
model = WhisperModel("large-v3", device="cuda", compute_type="float16")
print("large-v3 loaded ok")
PY
```

结果：

```text
loading large-v3 on AMD GPU...
large-v3 loaded ok
```

结论：`faster-whisper large-v3` 已经可以通过 ROCm 在 AMD RX 7800 XT 上加载。

## 11. podcast_ai 运行配置

项目代码已经支持以下环境变量：

```bash
JOEROGAN_WHISPER_DEVICE
JOEROGAN_WHISPER_COMPUTE_TYPE
JOEROGAN_WHISPER_CPU_THREADS
JOEROGAN_MAX_WORKERS
```

推荐启动：

```bash
cd /home/dpc/usr/bin/podcast_ai
source venv/bin/activate

export JOEROGAN_WHISPER_DEVICE=cuda
export JOEROGAN_WHISPER_COMPUTE_TYPE=float16
export JOEROGAN_WHISPER_CPU_THREADS=1
export JOEROGAN_MAX_WORKERS=1

python main_batch.py
```

另开窗口观察 GPU：

```bash
watch -n 1 rocm-smi
```

日志里如果看到：

```text
Loading WhisperModel large-v3 device=cuda compute_type=float16
```

并且没有 fallback 到 CPU，同时 `rocm-smi` 中 `VRAM%` / `GPU%` 上升，就说明主流程已经使用 AMD GPU。

## 12. 最终工具链总结

核心组件：

```text
GPU: AMD Radeon RX 7800 XT
GPU Arch: gfx1101
ROCm: 6.4.2
HIP: 6.4.43484
Compiler: /opt/rocm/bin/hipcc
CTranslate2: 4.7.1, source build with HIP/ROCm
faster-whisper: 1.2.1
Python: 3.12 venv
Build tools: cmake, ninja, git, python build, setuptools, wheel
BLAS: OpenBLAS
Runtime: libomp from /usr/lib/llvm-18/lib
```

关键修复点：

```text
1. 普通 pip ctranslate2 不支持 AMD GPU，需要源码编译 ROCm/HIP 版
2. GitHub clone 失败是代理问题
3. Intel OpenMP 缺失，用 -DOPENMP_RUNTIME=COMP
4. GCC 不认识 --offload-arch，必须使用 /opt/rocm/bin/hipcc
5. ROCm 6.4 下 __syncwarp 需要兼容补丁
6. hipBLAS datatype API 需要 -DHIPBLAS_V2
7. Python import 缺 libomp.so，需要把 /usr/lib/llvm-18/lib 加入 LD_LIBRARY_PATH
8. 最终 ctranslate2.get_cuda_device_count() == 1 表示 ROCm GPU 可用
```
