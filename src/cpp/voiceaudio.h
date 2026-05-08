#pragma once

#include <QObject>
#include <QVariant>
#include <QAudioInput>
#include <QAudioOutput>
#include <QAudioFormat>
#include <QIODevice>
#include <QMutex>
#include <QWaitCondition>
#include <QByteArray>
#include <QAudioDeviceInfo>
#include <QString>

// ---------------------------------------------------------------------------
// RingBuffer
//   Thread-safe circular buffer.  The internal cond is signalled on every
//   write so readExact() truly blocks with zero polling.
//
//   Exposed to Python as a raw pointer (via AudioPipe below) so Python
//   threads can call read/write WITHOUT going through the Qt main thread.
// ---------------------------------------------------------------------------
class RingBuffer {
public:
    explicit RingBuffer(int capacity);
    ~RingBuffer();

    // Write up to len bytes. Signals cond so blocked readers wake.
    int  write(const char *data, int len);

    // Block until exactly len bytes are ready, or stop becomes true.
    bool readExact(char *out, int len, bool &stop);

    // Non-blocking; returns bytes actually read.
    int  tryRead(char *out, int len);

    int  available() const;
    void clear();
    void wakeAll();   // unblock any readExact() waiter — call before stop=true

private:
    char           *_buf;
    int             _cap, _head, _tail, _used;
    mutable QMutex  _mutex;
    QWaitCondition  _cond;
};

// ---------------------------------------------------------------------------
// AudioPipe  — a plain C struct wrapping two RingBuffers.
//
// Python holds a PyCapsule pointing to an AudioPipe*.  All audio data
// transfers happen through this pointer: no QObject, no Qt signal, no
// pyotherside marshal.  The Qt main thread is never touched by audio I/O.
// ---------------------------------------------------------------------------
struct AudioPipe {
    RingBuffer *play;    // Python writes → QAudioOutput reads
    RingBuffer *cap;     // QAudioInput writes → Python reads (blocking)
    bool        capStop; // set true by VoiceAudio::stopAudio() to unblock readers

    AudioPipe() : play(nullptr), cap(nullptr), capStop(false) {}
};

// ---------------------------------------------------------------------------
// PlaybackDevice  (pull model — readData called on Qt audio thread)
// ---------------------------------------------------------------------------
class PlaybackDevice : public QIODevice {
    Q_OBJECT
public:
    explicit PlaybackDevice(RingBuffer *ring, QObject *parent = nullptr);
    void start();
    void stop();
protected:
    qint64 readData(char *data, qint64 maxSize) override;
    qint64 writeData(const char *, qint64) override { return -1; }
private:
    RingBuffer *_ring;
};

// ---------------------------------------------------------------------------
// CaptureDevice  (push model — writeData called on Qt audio thread)
// ---------------------------------------------------------------------------
class CaptureDevice : public QIODevice {
    Q_OBJECT
public:
    explicit CaptureDevice(RingBuffer *ring, QObject *parent = nullptr);
    void start();
    void stop();
    void setMuted(bool m);
protected:
    qint64 readData(char *, qint64) override { return -1; }
    qint64 writeData(const char *data, qint64 len) override;
private:
    RingBuffer *_ring;
    QMutex      _mutedLock;
    bool        _muted = false;
};

// ---------------------------------------------------------------------------
// VoiceAudio  — QML singleton (import Disports 1.0)
//
// Control path  : QML ↔ C++ via Q_INVOKABLE / properties (main thread only)
// Data path     : Python ↔ AudioPipe raw pointer (never touches main thread)
//
// Python obtains the AudioPipe* via getAudioPipeCapsule(), which returns
// a PyCapsule.  All subsequent audio I/O uses that capsule directly.
// ---------------------------------------------------------------------------
class VoiceAudio : public QObject {
    Q_OBJECT
    Q_PROPERTY(bool active       READ active       NOTIFY activeChanged)
    Q_PROPERTY(bool playbackReady READ playbackReady NOTIFY statusChanged)
    Q_PROPERTY(bool captureReady  READ captureReady  NOTIFY statusChanged)
    Q_PROPERTY(bool muted         READ muted   WRITE setMuted        NOTIFY mutedChanged)
    Q_PROPERTY(bool speakerphone  READ speakerphone WRITE setSpeakerphone NOTIFY speakerphoneChanged)

public:
    explicit VoiceAudio(QObject *parent = nullptr);
    ~VoiceAudio() override;

    Q_INVOKABLE void startAudio();
    Q_INVOKABLE void stopAudio();

    // Returns a PyCapsule("AudioPipe") pointing to the internal AudioPipe.
    // Python calls this ONCE during setup and keeps the capsule.
    Q_INVOKABLE QVariant getAudioPipeCapsule();

    bool active()        const { return _running;        }
    bool playbackReady() const { return _playbackReady;  }
    bool captureReady()  const { return _captureReady;   }
    bool muted()         const { return _muted;          }
    bool speakerphone()  const { return _speakerphone;   }

    Q_INVOKABLE void setMuted(bool m);
    Q_INVOKABLE void setSpeakerphone(bool s);

signals:
    void activeChanged();
    void statusChanged();
    void mutedChanged();
    void speakerphoneChanged();
    void audioLog(const QString &message);

private:
    void _setupFormat();
    void _startPlayback();
    void _startCapture();
    void _stopPlayback();
    void _stopCapture();
    void _applyMediaRole(bool speakerphone);
    void _log(const QString &msg);

    QAudioFormat _playFmt;
    QAudioFormat _capFmt;

    static constexpr int kPlayRingSize = 48000;
    static constexpr int kCapRingSize  = 24000;

    AudioPipe       _pipe;           // owns the two ring buffers
    PlaybackDevice *_playDev  = nullptr;
    CaptureDevice  *_capDev   = nullptr;
    QAudioOutput   *_audioOut = nullptr;
    QAudioInput    *_audioIn  = nullptr;

    bool _playbackReady = false;
    bool _captureReady  = false;
    bool _muted         = false;
    bool _speakerphone  = false;
    bool _running       = false;
};
