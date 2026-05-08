#include "voiceaudio.h"

#include <QQmlEngine>
#include <QQmlExtensionPlugin>
#include <qqml.h>

// ---------------------------------------------------------------------------
// DisportsVoicePlugin
//   Registers VoiceAudio as a singleton QML type under the Disports 1.0
//   import URI.  QML files can then write:
//
//       import Disports 1.0
//       ...
//       VoiceAudio.startAudio()
// ---------------------------------------------------------------------------

class DisportsVoicePlugin : public QQmlExtensionPlugin {
    Q_OBJECT
    Q_PLUGIN_METADATA(IID QQmlExtensionInterface_iid)

public:
    void registerTypes(const char *uri) override {
        Q_ASSERT(QLatin1String(uri) == QLatin1String("Disports"));
        qmlRegisterSingletonType<VoiceAudio>(
            uri, 1, 0, "VoiceAudio",
            [](QQmlEngine *, QJSEngine *) -> QObject * {
                return new VoiceAudio();
            }
        );
    }
};

#include "plugin.moc"
