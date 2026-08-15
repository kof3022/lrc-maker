# 歌词时间戳 · LRC Maker

> 给 MP3 音乐 + 歌词自动生成带时间戳的 LRC 文件 · 本地离线识别 / 千问在线识别 · 极简网页界面

输入 MP3 音乐和歌词文字，自动为每一行歌词加上时间戳，一键导出 LRC 文件。
界面极简、本地运行，支持**本地离线识别**和**千问（百炼）在线识别**两种引擎。

## 功能特性

- 词级语音识别：本地 faster-whisper（离线）或千问 `paraformer-realtime-v2`（在线，WebSocket 实时推流）
- 歌词智能对齐：Needleman-Wunsch 序列对齐 + 拼音相似度 + 模糊匹配，副歌重复行自动按顺序匹配，同音字也能对上
- 三级标注：**已匹配** / **低置信** / **估算**，一眼看出哪些行需要人工核对
- 在线识别增强：歌词热词表自动引导识别（整句权重最高），识别完成自动删除；已针对歌曲调参（标点预测、词级时间戳校准、保留语气词）
- 手动修正：点击歌词行跳转试听，选中行按空格或「设为当前时间」即可修正
- 免安装打包：PyInstaller 打包为 Windows 单文件夹版，双击即用

## 环境要求

- Python 3.10+（Windows / macOS / Linux）
- 在线识别需可访问 `dashscope.aliyuncs.com`（阿里云百炼）

## 快速开始（源码运行）

```powershell
# 1. 创建虚拟环境并安装依赖
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 2. 启动（自动打开浏览器 http://127.0.0.1:8766）
.venv\Scripts\python server.py
```

也可以直接双击项目根目录的 `start.bat`：首次运行会自动创建虚拟环境并安装依赖，之后每次双击即可启动。

首次使用本地识别会自动下载模型（数百 MB，之后离线可用）；使用在线识别需在「设置」中填写百炼 API Key。

## 使用说明

1. 拖入 MP3（或点击选择音频，支持 mp3 / wav / m4a / flac / ogg / aac）
2. 粘贴歌词（每行一句）
3. 点击「生成时间戳」，等待识别完成
4. 预览：点击歌词行可跳转试听；选中行按空格或点「设为当前时间」手动修正
5. 点击「导出 LRC」保存，或「复制」到剪贴板

结果每行有三个标注：**已匹配**（可靠）、**低置信**（误差较大，建议试听核对）、**估算**（未识别到，按前后行推算，仅供参考）。

## 识别引擎

右上角「设置」中可切换：

- **本地识别（provider = local）**：faster-whisper，完全离线，音频不出本机。`model_size` 支持 small / base / medium，越大越准越慢。
- **千问在线识别（provider = dashscope）**：音频先本地解码为 16kHz 单声道 PCM，再通过实时 WebSocket 推送给 `paraformer-realtime-v2`，返回词级时间戳。识别更准，需填写百炼 API Key（只保存在本机 `config.local.json`，不会上传到任何第三方）。
  - 已内置有节奏推流与自动重试（连接中断/超时/限流时自动重试 2 次），对服务端临时限流更健壮
  - 开启「歌词热词增强」（`hotword_boost`）后，会自动把歌词文本做成临时热词表引导识别，识别完成即删除

## 配置

复制 `config.example.json` 为 `config.local.json`（后者已加入 `.gitignore`，只保存在本机，**切勿提交 API Key**）：

```json
{
  "model_size": "medium",
  "language": "zh",
  "initial_prompt": "以下是歌曲的歌词。",
  "no_speech_threshold": 0.75,
  "provider": "local",
  "api_key": "",
  "hotword_boost": true
}
```

| 字段 | 说明 |
| --- | --- |
| `provider` | 识别引擎：`local` 本地离线 / `dashscope` 千问在线 |
| `model_size` | 本地引擎模型：small / base / medium |
| `language` | zh / en / 空（自动检测） |
| `initial_prompt` | 本地引擎识别提示词 |
| `no_speech_threshold` | 无语音判定阈值，越大越倾向跳过纯音乐/静音 |
| `api_key` | 百炼 API Key（在线识别必填，仅本机保存） |
| `hotword_boost` | 歌词热词增强开关 |

## 打包免安装版（Windows）

```powershell
.venv\Scripts\python -m PyInstaller lrc-maker.spec --noconfirm --clean
```

产物在 `dist\LrcMaker\`，可整体拷贝到任意 64 位 Windows 电脑，双击「start.bat」即用，无需安装 Python。

## 原理

1. 对音频做词级转写（本地或在线），得到每个词的开始时间；
2. 把词按标点切分为「人声单元」；
3. 用 Needleman-Wunsch 序列对齐 + 模糊匹配（文本比例 / 部分匹配 / 拼音相似度），把歌词行与人声单元按时间顺序配对（副歌重复行自动按顺序匹配，同音字也能对上）；
4. 未匹配的行做词级「救援匹配」：在前一行起点到后一行起点的时间窗口内，找最接近的连续词片段（容忍同音/漏字）；
5. 仍匹配不上的行按前后已匹配行「估算填补」时间，并标记为估算；
6. 每行取其开始时间，生成标准 LRC（含 `[ti:]` / `[ar:]` 元数据）。

## 开发辅助脚本

```powershell
# 把音频转写结果缓存为 JSON（避免反复识别，便于调对齐）
.venv\Scripts\python scripts\dump_segments.py <mp3> data\segments.json

# 用缓存结果离线对齐并生成 LRC（秒级）
.venv\Scripts\python scripts\align_offline.py data\segments.json <歌词txt> <歌名> data\out.lrc

# 命令行跑完整流程（识别 + 对齐 + 保存）
.venv\Scripts\python scripts\run_song.py <mp3> <歌词txt> <歌名> data\out.lrc
```

## 测试

```powershell
.venv\Scripts\python scripts\test_lyrics.py
.venv\Scripts\python scripts\test_aligner.py
.venv\Scripts\python scripts\test_lrc.py
.venv\Scripts\python scripts\test_server.py
```

## 隐私与安全

- 本地识别：音频完全不出本机
- 在线识别：仅把音频推流给阿里云百炼实时识别接口；API Key 只保存在本机 `config.local.json`，不会出现在任何日志或上传请求之外
- 提交代码前请确认 `config.local.json` 未被纳入版本控制（已列入 `.gitignore`）

## 已知限制

- 歌曲识别存在同音字/漏字，「低置信」行的时间可能偏差，建议试听核对；
- 「估算」行是纯推算（如轻声结尾没识别到），时间仅供参考；
- 歌词与演唱版本不一致（如少了一段副歌）时，多余歌词行也会被估算覆盖，建议先核对歌词再生成；
- 纯音乐前奏/间奏没有匹配行属正常现象，首句时间会落在前奏之后。

## 反馈与贡献

欢迎通过 GitHub Issue / Pull Request 反馈问题或提交改进。
开发相关说明见「开发辅助脚本」与「测试」小节。

## 开源协议

本项目使用 [MIT License](LICENSE)。
