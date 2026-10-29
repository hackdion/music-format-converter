import csv
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = os.environ.get('TEST_FFMPEG', 'ffmpeg')
FFPROBE = os.environ.get('TEST_FFPROBE', 'ffprobe')

class ConverterIntegrationTest(unittest.TestCase):
    def test_qmc_node_matches_reference_data_layer(self):
        sys.path.insert(0, str(ROOT))
        from vendor.qmc2 import RC4, map_decrypt
        for key in (bytes(range(1, 101)), bytes([i % 255 + 1 for i in range(512)])):
            data = bytes((i * 73) & 255 for i in range(13000))
            expected = bytearray(data)
            if len(key) > 300: RC4(key).decrypt_into(expected, 0)
            else: map_decrypt(expected, key)
            with tempfile.TemporaryDirectory() as folder:
                source = Path(folder) / 'source'; output = Path(folder) / 'output'
                source.write_bytes(data)
                payload = json.dumps({'key':base64.b64encode(key).decode(), 'length':len(data)})
                subprocess.run(['node', str(ROOT/'qmc-data.cjs'), str(source), str(output)], input=payload, text=True, check=True)
                self.assertEqual(output.read_bytes(), bytes(expected))

    def test_batch_copy_encode_collision_and_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); source = base / 'input'; output = base / 'output'
            source.mkdir(); output.mkdir()
            wav = source / 'tone.wav'; mp3 = source / 'existing.mp3'
            subprocess.run([FFMPEG, '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', str(wav)], check=True)
            subprocess.run([FFMPEG, '-v', 'error', '-i', str(wav), '-c:a', 'libmp3lame', str(mp3)], check=True)
            (source / 'broken.ncm').write_bytes(b'CTENFDAMbroken')
            (output / 'tone.mp3').write_bytes(b'existing sentinel')
            before = hashlib.sha256(mp3.read_bytes()).hexdigest()
            command = [sys.executable, str(ROOT / 'converter.py'), str(source), str(output), '--ffmpeg', FFMPEG, '--ffprobe', FFPROBE]
            result = subprocess.run(command, capture_output=True, encoding='utf-8', errors='replace')
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual((output / 'tone.mp3').read_bytes(), b'existing sentinel')
            self.assertTrue((output / 'tone (2).mp3').exists())
            self.assertEqual(hashlib.sha256((output / 'existing.mp3').read_bytes()).hexdigest(), before)
            with (output / 'conversion-report.csv').open(encoding='utf-8-sig', newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(sorted(row['status'] for row in rows), ['FAIL', 'OK', 'OK'])
            self.assertTrue(wav.exists())

    def test_ncm_synthetic_round_trip(self):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        sys.path.insert(0, str(ROOT))
        from converter import decode_ncm
        import struct
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); wav = base / 'tone.wav'; ncm = base / 'tone.ncm'; decoded = base / 'decoded.wav'
            subprocess.run([FFMPEG, '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=880:duration=1', str(wav)], check=True)
            key = b'synthetic-test-key'; data = b'neteasecloudmusic' + key
            pad = 16 - len(data) % 16; data += bytes([pad]) * pad
            enc = Cipher(algorithms.AES(bytes.fromhex('687A4852416D736F356B496E62617857')), modes.ECB()).encryptor()
            encrypted = bytes(x ^ 0x64 for x in (enc.update(data) + enc.finalize()))
            box = list(range(256)); j = 0
            for i in range(256):
                j = (j + box[i] + key[i % len(key)]) & 255; box[i], box[j] = box[j], box[i]
            pattern = bytes(box[(box[i] + box[(i + box[i]) & 255]) & 255] for i in range(256))
            payload = wav.read_bytes(); cipher = bytes(value ^ pattern[(i + 1) & 255] for i, value in enumerate(payload))
            ncm.write_bytes(b'CTENFDAM' + b'\0\0' + struct.pack('<I', len(encrypted)) + encrypted + struct.pack('<I', 0) + b'\0'*5 + struct.pack('<II', 0, 0) + cipher)
            decode_ncm(ncm, decoded)
            self.assertEqual(decoded.read_bytes(), payload)

if __name__ == '__main__':
    unittest.main()
