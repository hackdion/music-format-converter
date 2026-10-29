// QMC2 data-layer port from the project's qmunlock/qmc2.py.
// The derived key is received through stdin and is never saved.
const fs = require('node:fs');
const request = JSON.parse(fs.readFileSync(0, 'utf8'));
const key = Buffer.from(request.key, 'base64');
const input = fs.readFileSync(process.argv[2]);
const audio = input.subarray(0, request.length);
const n = key.length;
if (n <= 300 || request.forceMap) {
  for (let i = 0; i < audio.length; i++) {
    const off = i > 0x7fff ? i % 0x7fff : i;
    const idx = (off * off + 71214) % n;
    const value = key[idx];
    const shift = ((idx & 7) + 4) % 8;
    audio[i] ^= shift ? ((value << shift) | (value >> shift)) & 255 : value;
  }
} else {
  const box = Uint8Array.from({length: n}, (_, i) => i & 255);
  let j = 0;
  for (let i = 0; i < n; i++) {
    j = (j + box[i] + key[i % n]) % n;
    [box[i], box[j]] = [box[j], box[i]];
  }
  let hash = 1;
  for (const value of key) {
    if (value === 0) continue;
    const next = Math.imul(hash, value) >>> 0;
    if (next === 0 || next <= hash) break;
    hash = next;
  }
  const skip = id => key[id % n] === 0 ? 0 : Math.floor((hash / ((id + 1) * key[id % n])) * 100) % n;
  const first = Math.min(128, audio.length);
  for (let i = 0; i < first; i++) audio[i] ^= key[skip(i)];
  let offset = first;
  while (offset < audio.length) {
    const length = Math.min(audio.length - offset, 5120 - offset % 5120);
    const state = box.slice();
    let a = 0, b = 0;
    const skipLength = offset % 5120 + skip(Math.floor(offset / 5120));
    for (let i = -skipLength; i < length; i++) {
      a = (a + 1) % n;
      b = (b + state[a]) % n;
      [state[a], state[b]] = [state[b], state[a]];
      if (i >= 0) audio[offset + i] ^= state[(state[a] + state[b]) % n];
    }
    offset += length;
  }
}
fs.writeFileSync(process.argv[3], audio, {flag: 'wx'});
