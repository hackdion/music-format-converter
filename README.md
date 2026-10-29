# Music Format Converter

一个基于 Python、FFmpeg 的本地音乐格式转换工具，以及多次批处理任务的中文复盘。支持普通音频、已验证的一类网易云 NCM 文件，以及在用户**自行提供对应密钥**时的部分 QQ 音乐 STag / musicex QMC2 文件。

源文件只读；输出保存到单独目录。输出同名时自动添加编号，不覆盖已有文件。音频已是 MP3 时提取或复制，其他可识别音频转为 320 kbps MP3。每个输出都会检查实际编码、时长，并完整解码验证；结果写入 CSV。

## 环境

- Python 3.11 或以上；安装 `requirements.txt` 中的依赖。
- FFmpeg 和 FFprobe，且能够通过 PATH 运行；也可使用参数指定可执行文件。
- 处理 QMC2 文件时还需 Node.js，以及由用户自行取得的、与文件匹配的 ekey。工具不读取客户端令牌、不联网取钥，也不下载替代歌曲。

在项目目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python converter.py "./input-music" "./output-mp3" --dry-run
.\.venv\Scripts\python converter.py "./input-music" "./output-mp3"
```

macOS / Linux 使用 `.venv/bin/python`。输入和输出目录必须互不包含；`--dry-run` 只显示候选文件。工具按文件逐个处理，失败不会中断其余文件，退出码为 1 表示存在失败项。CSV 报告保存在输出目录中，包含源路径，请自行决定是否分享。

指定程序位置：

```powershell
python converter.py "./input-music" "./output-mp3" --ffmpeg "./tools/ffmpeg.exe" --ffprobe "./tools/ffprobe.exe"
```

### 手动提供 QQ 音乐密钥

此路线仅用于用户持有文件并有权使用对应密钥的情况。请将**单个** QQ 加密文件放入一个输入目录，将对应的 ekey 写入本机私密文本文件，然后运行：

```powershell
python converter.py "./one-qq-file" "./output-mp3" --qmc-key-file "../private-key.txt"
```

目前仅识别 `.mgg`、`.mflac` 以及名称含 `.mgg0/.mgg1/.mgg2/.mflac0/.mflac4` 且后缀为 `.flac` 的输入，并支持所实现的 `STag` 和 `musicex` 尾部。若密钥与文件头不匹配、文件变体不受支持或解码出错，该项会标记失败。不要提交或分享密钥文件。此工具不会自动调用 QQ 客户端或获取密钥；实际兼容性取决于文件与密钥。

## 边界

- MP3 是有损格式；320 kbps 不会使已有有损音频变成无损。
- 直接保存的 MP3 保持原音频参数，不一定是 320 kbps。NCM 的封面、歌词和所有元数据不保证保留。
- 完整解码和时长检查并不证明听感、歌曲版本或两个同名文件的身份完全相同。
- 默认处理所有支持的输入文件；工具**不自动判断是否与其他音乐库重复**。请使用 CSV 审核结果。
- 部分损坏音频、带额外尾部数据的 FLAC、其他加密变体可能需要额外诊断；工具将严格报错，保留源文件。
- 运行需要与音乐规模相应的磁盘空间；中间文件位于系统临时目录。请勿将私人音乐、CSV、账号信息或密钥提交到公开仓库。

## 经验与来源

详见 [音乐转换知识与实践](docs/music-conversion-knowledge.md)。QMC2 参考实现来自 [QM Unlock](https://github.com/mary20050520/qmunlock)，许可证及版权声明保存在 [vendor/QM_UNLOCK_LICENSE.txt](vendor/QM_UNLOCK_LICENSE.txt)。NCM 算法参考 [ncmdump](https://github.com/taurusxin/ncmdump) 和 [ncm-converter](https://github.com/Taoluxiaobai/ncm-converter)。FFmpeg 与 Node.js 由用户自行安装，本仓库不分发这些二进制文件。
