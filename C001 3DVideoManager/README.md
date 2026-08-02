# AV1 3D Video Batch Converter

一个基于 PyQt5 + FFmpeg 的 Windows 视频检测和 AV1 批量转码工具。

## 运行

```powershell
python av1_3d_video_tool.py
```

需要：

- Python
- PyQt5
- FFmpeg / ffprobe，并且已经加入 `PATH`
- 推荐 FFmpeg 带 `libsvtav1`

## 基本流程

1. 点击 `添加视频` 或 `添加文件夹`。
2. 点击 `开始检测`，工具会用 ffprobe 读取视频信息。
3. 如果自动 3D 判断不准，选中视频，在右侧 `3D 类型修正` 里改成 `SBS Full`、`SBS Half` 等。
4. 选择输出目录和 AV1 参数。
5. 点击 `开始转换`。

默认参数已经按高画质 3D 电影设置：

```text
尺寸模式：保持原尺寸
编码器：libsvtav1
CRF：20
Preset：5
音频：copy
```

这个默认档会比小体积参数慢很多，输出文件也会更大。如果想稍微减小体积，可以把 CRF 调到 `22` 或 `24`。

检测详情里会显示有效视频码率、码率来源、编码器设置、片源质量估计、以及降噪/锐化痕迹判断。其中 CRF/QP/Preset 和滤镜处理只能在源文件元数据保留相关信息时读取，否则会显示为未记录或无法可靠判断。

顶部菜单栏的 `语言` 可以切换中文、日语和英文。

右键视频列表中的条目，可以选择 `从列表删除` 或 `永久删除文件...`。永久删除会先弹出确认框。

## 转码输出

输出视频默认写到：

```text
converted/
```

转换报告统一写到输出目录下的专门文件夹：

```text
converted/transfer_reports/
```

每个输出视频会生成一个 Markdown 报告：

```text
xxx_av1.transfer.md
```

报告会记录输入/输出文件名、路径、文件大小、编码、分辨率、帧率、码率、BPP、CRF/Preset、音频处理、质量判断和体积变化。

## 3D SBS 建议

如果原视频是 `3840x2160` 的 SBS 3D，但文件名没有 SBS/3D 标记，ffprobe 通常无法自动知道它是 3D。

这种情况请手动修正为：

```text
SBS Full
```

如果要高画质保留原始 4K 3D，请使用默认的：

```text
保持原尺寸
```

如果你明确想把 SBS 高度降到 1080，再手动选择：

```text
3D SBS 高度转 1080（宽度保持）
```
