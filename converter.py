"""Batch audio conversion with explicit inputs and non-destructive outputs."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile

import numpy as np
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

SUPPORTED = {'.mp3', '.flac', '.ogg', '.wav', '.m4a', '.aac', '.ncm', '.mgg', '.mflac'}

def run(args):
    return subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=1800)

def probe(path, binary):
    result = run([binary, '-v', 'error', '-select_streams', 'a:0', '-show_entries',
                  'format=duration:stream=codec_name', '-of', 'json', str(path)])
    if result.returncode:
        raise RuntimeError('音频读取失败: ' + result.stderr[-500:])
    data = json.loads(result.stdout)
    if not data.get('streams') or float(data.get('format', {}).get('duration', 0)) <= 0:
        raise RuntimeError('没有可读取的音频流或时长')
    return data['streams'][0]['codec_name'], float(data['format']['duration'])

def decode_ncm(source, target):
    with source.open('rb') as src, target.open('xb') as dst:
        if src.read(8) != b'CTENFDAM':
            raise RuntimeError('不是可识别的 NCM 文件')
        src.read(2)
        key_size = struct.unpack('<I', src.read(4))[0]
        if not 16 <= key_size <= 65536 or key_size % 16:
            raise RuntimeError('NCM 密钥区域长度异常')
        encrypted = bytes(value ^ 0x64 for value in src.read(key_size))
        decoder = Cipher(algorithms.AES(bytes.fromhex('687A4852416D736F356B496E62617857')), modes.ECB()).decryptor()
        plain = decoder.update(encrypted) + decoder.finalize()
        pad = plain[-1]
        if not 1 <= pad <= 16 or plain[-pad:] != bytes([pad]) * pad:
            raise RuntimeError('NCM 密钥填充无效')
        key = plain[:-pad]
        if not key.startswith(b'neteasecloudmusic'):
            raise RuntimeError('NCM 密钥头无效')
        key = key[17:]
        if not key:
            raise RuntimeError('NCM 密钥为空')
        box = list(range(256)); j = 0
        for i in range(256):
            j = (j + box[i] + key[i % len(key)]) & 255
            box[i], box[j] = box[j], box[i]
        pattern = np.array([box[(box[i] + box[(i + box[i]) & 255]) & 255] for i in range(256)], dtype=np.uint8)
        metadata_size = struct.unpack('<I', src.read(4))[0]
        if metadata_size > source.stat().st_size:
            raise RuntimeError('NCM 元数据长度异常')
        src.seek(metadata_size + 5, 1)
        cover_space = struct.unpack('<I', src.read(4))[0]
        cover_size = struct.unpack('<I', src.read(4))[0]
        if cover_size > cover_space or cover_space > source.stat().st_size:
            raise RuntimeError('NCM 封面区域异常')
        src.seek(cover_space, 1)
        offset = 0
        while block := src.read(1024 * 1024):
            data = np.frombuffer(block, dtype=np.uint8)
            index = (np.arange(len(data), dtype=np.uint32) + offset + 1) & 255
            dst.write(np.bitwise_xor(data, pattern[index]).tobytes())
            offset += len(data)

def decode_qmc(source, target, key_file, node):
    if not key_file:
        raise RuntimeError('QQ 加密文件需要手动提供对应 ekey；请查看 README')
    from vendor.qmc2 import decrypt_qmc2, derive_key
    key = Path(key_file).read_text(encoding='utf-8').strip()
    with source.open('rb') as stream:
        head = stream.read(25000)
        stream.seek(-16, 2)
        tail = stream.read(16)
    if tail[-4:] == b'STag':
        length = source.stat().st_size - 8 - int.from_bytes(tail[-8:-4], 'big')
    elif tail[-8:] == b'musicex\0':
        length = source.stat().st_size - int.from_bytes(tail[-16:-12], 'little')
    else:
        raise RuntimeError('仅支持 STag 或 musicex 尾部')
    if length <= 0 or length > source.stat().st_size:
        raise RuntimeError('加密音频长度异常')
    reference, kind = decrypt_qmc2(head, key)
    if kind not in ('ogg', 'flac', 'mp3'):
        raise RuntimeError('提供的密钥与文件头不匹配')
    import base64
    request = json.dumps({'key': base64.b64encode(derive_key(key)).decode(), 'length': length})
    result = subprocess.run([node, str(Path(__file__).parent / 'qmc-data.cjs'), str(source), str(target)],
                            input=request, capture_output=True, text=True, timeout=1800)
    if result.returncode:
        raise RuntimeError('QMC 音频解密失败')
    with target.open('rb') as stream:
        if stream.read(len(reference)) != reference:
            raise RuntimeError('解密结果与参考算法不一致')

def convert(source, output, options):
    before = source.stat()
    with tempfile.TemporaryDirectory(prefix='audio-convert-') as tmp:
        audio = Path(tmp) / 'input.audio'
        with source.open('rb') as f:
            header = f.read(8)
        if header == b'CTENFDAM':
            decode_ncm(source, audio)
        elif header[:4] not in (b'fLaC', b'OggS') and header[:3] != b'ID3' and (source.suffix.lower() in ('.mgg', '.mflac') or source.stem.lower().endswith(('.mgg0', '.mgg1', '.mgg2', '.mflac0', '.mflac4'))):
            decode_qmc(source, audio, options.qmc_key_file, options.node)
        else:
            shutil.copyfile(source, audio)
        codec, duration = probe(audio, options.ffprobe)
        partial = Path(tmp) / 'output.mp3'
        if codec == 'mp3':
            shutil.copyfile(audio, partial)
            method = 'extract-or-copy-mp3'
        else:
            result = run([options.ffmpeg, '-hide_banner', '-nostdin', '-loglevel', 'error', '-xerror', '-n',
                          '-i', str(audio), '-map', '0:a:0', '-map_metadata', '0', '-c:a', 'libmp3lame',
                          '-b:a', '320k', '-ar', '44100', '-id3v2_version', '3', str(partial)])
            if result.returncode:
                raise RuntimeError('编码失败: ' + result.stderr[-500:])
            method = 'transcode-320k'
        out_codec, out_duration = probe(partial, options.ffprobe)
        if out_codec != 'mp3' or abs(duration - out_duration) > 0.2:
            raise RuntimeError('输出编码或时长检查失败')
        verify = run([options.ffmpeg, '-hide_banner', '-nostdin', '-loglevel', 'error', '-xerror',
                      '-i', str(partial), '-map', '0:a:0', '-f', 'null', '-'])
        if verify.returncode:
            raise RuntimeError('完整解码检查失败: ' + verify.stderr[-500:])
        if (source.stat().st_size, source.stat().st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            raise RuntimeError('源文件在处理期间发生变化')
        with partial.open('rb') as stream:
            sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        try:
            with output.open('xb') as destination:
                try:
                    with partial.open('rb') as stream:
                        shutil.copyfileobj(stream, destination)
                except Exception:
                    destination.close()
                    output.unlink(missing_ok=True)
                    raise
        except FileExistsError:
            raise RuntimeError('目标已存在，未覆盖') from None
        return {'status': 'OK', 'source': str(source), 'output': str(output), 'method': method,
                'source_seconds': duration, 'output_seconds': out_duration, 'output_sha256': sha, 'error': ''}

def main():
    parser = argparse.ArgumentParser(description='将指定目录里的音频转为 MP3，不修改源文件')
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--ffmpeg', default='ffmpeg')
    parser.add_argument('--ffprobe', default='ffprobe')
    parser.add_argument('--node', default='node')
    parser.add_argument('--qmc-key-file', help='单个 QQ 音频对应的 ekey 文本文件；不自动读取账号信息')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    src = args.source.resolve(); out = args.output.resolve()
    if not src.is_dir():
        parser.error('输入必须是存在的目录')
    if src == out or src in out.parents or out in src.parents:
        parser.error('输入和输出目录必须互不包含')
    files = sorted(p for p in src.rglob('*') if p.is_file() and p.suffix.lower() in SUPPORTED)
    if args.qmc_key_file and sum(p.suffix.lower() in ('.mgg', '.mflac') or p.stem.lower().endswith(('.mgg0', '.mgg1', '.mgg2', '.mflac0', '.mflac4')) for p in files) > 1:
        parser.error('单个密钥文件仅适用于一个 QQ 加密文件；请为每首单独运行')
    if args.dry_run:
        for source in files:
            print(source)
        print(f'共 {len(files)} 个候选文件')
        return 0
    out.mkdir(parents=True, exist_ok=True)
    reserved = {p.name.casefold() for p in out.iterdir()}
    results = []
    for source in files:
        stem = source.stem
        for suffix in ('.mgg0', '.mgg1', '.mgg2', '.mflac0', '.mflac4'):
            if stem.lower().endswith(suffix):
                stem = stem[:-len(suffix)]
                break
        if len(stem) > 110:
            stem = stem[:95].rstrip() + ' [' + hashlib.sha256(source.name.encode()).hexdigest()[:8] + ']'
        name = stem + '.mp3'; i = 2
        while name.casefold() in reserved:
            name = f'{stem} ({i}).mp3'; i += 1
        reserved.add(name.casefold()); destination = out / name
        try:
            row = convert(source, destination, args)
        except Exception as exc:
            row = {'status': 'FAIL', 'source': str(source), 'output': '', 'method': '',
                   'source_seconds': '', 'output_seconds': '', 'output_sha256': '', 'error': str(exc)}
        results.append(row)
        print(f"{len(results)}/{len(files)} {row['status']} {source.name}", flush=True)
    report = out / 'conversion-report.csv'; index = 2
    while report.exists():
        report = out / f'conversion-report ({index}).csv'; index += 1
    with report.open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['status','source','output','method','source_seconds','output_seconds','output_sha256','error'])
        writer.writeheader(); writer.writerows(results)
    print(f'报告: {report}')
    return 1 if any(row['status'] != 'OK' for row in results) else 0

if __name__ == '__main__':
    sys.exit(main())
