"""Decode the bundled track and report its low-frequency onset grid (offline)."""

from pathlib import Path

import numpy as np
from PySide6.QtCore import QCoreApplication, QTimer, QUrl
from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat

app = QCoreApplication([])
decoder = QAudioDecoder()
fmt = QAudioFormat()
fmt.setSampleRate(48000)
fmt.setChannelCount(1)
fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
decoder.setAudioFormat(fmt)
chunks = []


def receive():
    buffer = decoder.read()
    chunks.append(np.frombuffer(bytes(buffer.data()), dtype=np.float32).copy())


decoder.bufferReady.connect(receive)
decoder.finished.connect(app.quit)
decoder.error.connect(app.quit)
decoder.setSource(QUrl.fromLocalFile(str(
    Path(__file__).resolve().parents[1] / "src/somniloop/assets/rave/track.mp3"
)))
QTimer.singleShot(15000, app.quit)
decoder.start()
app.exec()
samples = np.concatenate(chunks)
hop, window = 480, 2048
frames = np.lib.stride_tricks.sliding_window_view(samples, window)[::hop]
spectrum = np.abs(np.fft.rfft(frames * np.hanning(window), axis=1))
energy = spectrum[:, 2:10].sum(axis=1)
onset = np.maximum(0, np.diff(energy, prepend=0))
onset /= max(onset.max(), 1)
scores = []
for bpm in np.arange(100, 181, .1):
    period = 60 / bpm / .01
    best = max((sum(np.interp(np.arange(phase, len(onset), period),
                              np.arange(len(onset)), onset)), phase)
               for phase in np.arange(0, period, 1))
    scores.append((best[0], bpm, best[1] * .01))
print("duration", len(samples) / 48000, "best grids", sorted(scores, reverse=True)[:8])
peaks = [i for i in range(2, len(onset) - 2)
         if onset[i] > .18 and onset[i] == max(onset[i-2:i+3])]
print("First strong onset", peaks[0] * .01)
for second in range(0, 44):
    part = samples[second * 48000:(second + 1) * 48000]
    print(second, "RMS", round(float(np.sqrt(np.mean(part ** 2))), 3),
          "bass onset", round(float(onset[second * 100:(second + 1) * 100].max()), 3))
