#include "voiceaudio.h"
#include <QAudioDeviceInfo>
#include <QDebug>
#include <algorithm>
#include <cstring>

// ============================================================================
// RingBuffer
// ============================================================================

RingBuffer::RingBuffer(int capacity)
    : _buf(new char[capacity]), _cap(capacity), _head(0), _tail(0), _used(0) {}

RingBuffer::~RingBuffer() { delete[] _buf; }

int RingBuffer::write(const char *data, int len) {
    QMutexLocker lk(&_mutex);
    int n = std::min(len, _cap - _used);
    if (n <= 0) return 0;
    if (_tail + n <= _cap) {
        std::memcpy(_buf + _tail, data, n);
    } else {
        int first = _cap - _tail;
        std::memcpy(_buf + _tail, data, first);
        std::memcpy(_buf, data + first, n - first);
    }
    _tail = (_tail + n) % _cap;
    _used += n;
    _cond.wakeAll();
    return n;
}

bool RingBuffer::readExact(char *out, int len, bool &stop) {
    QMutexLocker lk(&_mutex);
    while (_used < len) {
        if (stop) return false;
        _cond.wait(&_mutex, 50);
        if (stop) return false;
    }
    if (_head + len <= _cap) {
        std::memcpy(out, _buf + _head, len);
    } else {
        int first = _cap - _head;
        std::memcpy(out, _buf + _head, first);
        std::memcpy(out + first, _buf, len - first);
    }
    _head = (_head + len) % _cap;
    _used -= len;
    return true;
}

int RingBuffer::tryRead(char *out, int len) {
    QMutexLocker lk(&_mutex);
    int n = std::min(len, _used);
    if (n <= 0) return 0;
    if (_head + n <= _cap) {
        std::memcpy(out, _buf + _head, n);
    } else {
        int first = _cap - _head;
        std::memcpy(out, _buf + _head, first);
        std::memcpy(out + first, _buf, n - first);
    }
    _head = (_head + n) % _cap;
    _used -= n;
    return n;
}

int RingBuffer::available() const {
    QMutexLocker lk(&_mutex);
    return _used;
}

void RingBuffer::clear() {
    QMutexLocker lk(&_mutex);
    _head = _tail = _used = 0;
}

void RingBuffer::wakeAll() {
    QMutexLocker lk(&_mutex);
    _cond.wakeAll();
}

// ============================================================================
// PlaybackDevice
// ============================================================================

PlaybackDevice::PlaybackDevice(RingBuffer *ring, QObject *parent)
    : QIODevice(parent), _ring(ring) {}

void PlaybackDevice::start() { open(QIODevice::ReadOnly); }
void PlaybackDevice::stop()  { close(); }

qint64 PlaybackDevice::readData(char *data, qint64 maxSize) {
    int got = _ring->tryRead(data, static_cast<int>(maxSize));
    if (got < static_cast<int>(maxSize))
        std::memset(data + got, 0, static_cast<size_t>(maxSize - got));
    return maxSize;
}

// ============================================================================
// CaptureDevice
// ============================================================================

CaptureDevice::CaptureDevice(RingBuffer *ring, QObject *parent)
    : QIODevice(parent), _ring(ring) {}

void CaptureDevice::start() { _muted = false; open(QIODevice::WriteOnly); }
void CaptureDevice::stop()  { close(); }

void CaptureDevice::setMuted(bool m) {
    QMutexLocker lk(&_mutedLock);
    _muted = m;
}

qint64 CaptureDevice::writeData(const char *data, qint64 len) {
    QMutexLocker lk(&_mutedLock);
    if (_muted) {
        QByteArray silence(static_cast<int>(len), '\0');
        _ring->write(silence.constData(), static_cast<int>(len));
    } else {
        _ring->write(data, static_cast<int>(len));
    }
    return len;
}

// ============================================================================
// VoiceAudio
// ============================================================================

VoiceAudio::VoiceAudio(QObject *parent) : QObject(parent) {
    _pipe.play   = new RingBuffer(kPlayRingSize);
    _pipe.cap    = new RingBuffer(kCapRingSize);
    _pipe.capStop = false;
    _setupFormat();
}

VoiceAudio::~VoiceAudio() {
    stopAudio();
    delete _pipe.play;
    delete _pipe.cap;
}

void VoiceAudio::_setupFormat() {
    _playFmt.setSampleRate(48000);
    _playFmt.setChannelCount(2);
    _playFmt.setSampleSize(16);
    _playFmt.setCodec("audio/pcm");
    _playFmt.setByteOrder(QAudioFormat::LittleEndian);
    _playFmt.setSampleType(QAudioFormat::SignedInt);

    _capFmt.setSampleRate(48000);
    _capFmt.setChannelCount(1);
    _capFmt.setSampleSize(16);
    _capFmt.setCodec("audio/pcm");
    _capFmt.setByteOrder(QAudioFormat::LittleEndian);
    _capFmt.setSampleType(QAudioFormat::SignedInt);
}

void VoiceAudio::_log(const QString &msg) {
    qDebug() << "[VoiceAudio]" << msg;
    emit audioLog(msg);
}

void VoiceAudio::_applyMediaRole(bool speakerphone) {
    QByteArray props = "media.role=phone filter.want=echo-cancel";
    if (speakerphone) props += " sink.port=output-speaker";
    qputenv("PULSE_PROP_OVERRIDE", props);
    _log(speakerphone ? "media.role=phone sink.port=output-speaker"
                      : "media.role=phone (earpiece)");
}

// ---------------------------------------------------------------------------
// getAudioPipeCapsule
//   Returns a PyCapsule wrapping the AudioPipe*.  Python stores this and
//   calls the free functions below (write_playback / read_capture) on it
//   directly from its worker threads — zero Qt involvement.
// ---------------------------------------------------------------------------
QVariant VoiceAudio::getAudioPipeCapsule() {
    // Return the raw pointer address as a 64-bit integer.
    // This is much more robust for cross-thread marshaling than PyCapsule.
    return QVariant::fromValue(reinterpret_cast<qlonglong>(&_pipe));
}

// ---------------------------------------------------------------------------
// startAudio / stopAudio
// ---------------------------------------------------------------------------
void VoiceAudio::startAudio() {
    if (_running) return;
    _running = true;
    _pipe.capStop = false;
    _applyMediaRole(false);
    _startPlayback();
    _startCapture();
    emit activeChanged();
    emit statusChanged();
}

void VoiceAudio::stopAudio() {
    if (!_running) return;
    _running      = false;
    _pipe.capStop = true;
    _pipe.cap->wakeAll();   // unblock any Python thread in readExact()
    _stopPlayback();
    _stopCapture();
    emit activeChanged();
    emit statusChanged();
}

void VoiceAudio::_startPlayback() {
    QAudioDeviceInfo dev = QAudioDeviceInfo::defaultOutputDevice();
    if (dev.isNull()) { _log("ERROR: no output device — playback disabled"); return; }

    QAudioFormat fmt = _playFmt;
    if (!dev.isFormatSupported(fmt)) fmt = dev.nearestFormat(fmt);
    if (!fmt.isValid() || fmt.sampleRate() <= 0) {
        _log("ERROR: no valid output format — playback disabled"); return;
    }
    _playFmt = fmt;

    _playDev = new PlaybackDevice(_pipe.play, this);
    _playDev->start();
    _audioOut = new QAudioOutput(_playFmt, this);
    _audioOut->setBufferSize(_playFmt.bytesForDuration(100000));
    connect(_audioOut, &QAudioOutput::stateChanged, this, [this](QAudio::State s) {
        _log(QString("Playback state: %1").arg(s));
        if (s == QAudio::ActiveState) { _playbackReady = true; emit statusChanged(); }
    });
    _audioOut->start(_playDev);
    _log(QString("Playback: %1 Hz %2 ch").arg(_playFmt.sampleRate()).arg(_playFmt.channelCount()));
}

void VoiceAudio::_startCapture() {
    QAudioDeviceInfo dev = QAudioDeviceInfo::defaultInputDevice();
    if (dev.isNull()) { _log("ERROR: no input device — capture disabled"); return; }

    QAudioFormat fmt = _capFmt;
    if (!dev.isFormatSupported(fmt)) fmt = dev.nearestFormat(fmt);
    if (!fmt.isValid() || fmt.sampleRate() <= 0) {
        _log("ERROR: no valid input format — capture disabled"); return;
    }
    _capFmt = fmt;

    _capDev = new CaptureDevice(_pipe.cap, this);
    _capDev->start();
    _audioIn = new QAudioInput(_capFmt, this);
    _audioIn->setBufferSize(_capFmt.bytesForDuration(40000));
    connect(_audioIn, &QAudioInput::stateChanged, this, [this](QAudio::State s) {
        _log(QString("Capture state: %1").arg(s));
        if (s == QAudio::ActiveState) { _captureReady = true; emit statusChanged(); }
    });
    _audioIn->start(_capDev);
    _log(QString("Capture: %1 Hz %2 ch").arg(_capFmt.sampleRate()).arg(_capFmt.channelCount()));
}

void VoiceAudio::_stopPlayback() {
    if (_audioOut) { _audioOut->stop(); delete _audioOut; _audioOut = nullptr; }
    if (_playDev)  { _playDev->stop();  delete _playDev;  _playDev  = nullptr; }
    _playbackReady = false;
    _pipe.play->clear();
}

void VoiceAudio::_stopCapture() {
    if (_audioIn) { _audioIn->stop(); delete _audioIn; _audioIn = nullptr; }
    if (_capDev)  { _capDev->stop();  delete _capDev;  _capDev  = nullptr; }
    _captureReady = false;
    _pipe.cap->clear();
}

void VoiceAudio::setMuted(bool m) {
    if (_muted == m) return;
    _muted = m;
    if (_capDev) _capDev->setMuted(m);
    _log(m ? "Microphone muted" : "Microphone unmuted");
    emit mutedChanged();
}

void VoiceAudio::setSpeakerphone(bool s) {
    if (_speakerphone == s) return;
    _speakerphone = s;
    if (_running) { _stopPlayback(); _applyMediaRole(s); _startPlayback(); }
    _log(s ? "Routing: speakerphone" : "Routing: earpiece");
    emit speakerphoneChanged();
}

// ============================================================================
// Plain C exports — called directly from Python via ctypes.
// These operate on AudioPipe* with NO Qt involvement — safe from any thread.
// ============================================================================
extern "C" {

// Write PCM into the playback ring buffer.
// Python calls this from its receive/decode thread.
int disports_pipe_write(void *pipe_ptr, const char *data, int len) {
    if (!pipe_ptr || !data || len <= 0) return 0;
    auto *pipe = static_cast<AudioPipe *>(pipe_ptr);
    if (!pipe->play) return 0;
    return pipe->play->write(data, len);
}

// Read exactly `len` bytes from the capture ring buffer.
// Blocks until data is available or capStop is set.
// Returns `len` on success, 0 on shutdown.
int disports_pipe_read(void *pipe_ptr, char *out, int len) {
    if (!pipe_ptr || !out || len <= 0) return 0;
    auto *pipe = static_cast<AudioPipe *>(pipe_ptr);
    if (!pipe->cap) return 0;
    bool ok = pipe->cap->readExact(out, len, pipe->capStop);
    return ok ? len : 0;
}

// Returns 1 if the capture ring is active (capStop == false), else 0.
int disports_pipe_cap_ready(void *pipe_ptr) {
    if (!pipe_ptr) return 0;
    auto *pipe = static_cast<AudioPipe *>(pipe_ptr);
    return pipe->capStop ? 0 : 1;
}

} // extern "C"
