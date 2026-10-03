#include "SymbolicIcons.h"

#include <QColor>
#include <QImageReader>
#include <QPainter>
#include <QStandardPaths>

SymbolicIcons::SymbolicIcons()
    : QQuickImageProvider(QQuickImageProvider::Image)
{
}

QImage SymbolicIcons::requestImage(const QString& id, QSize* size, const QSize& requestedSize)
{
    const QString name = id.section(QLatin1Char('/'), 0, 0);
    const QColor colour(QLatin1Char('#') + id.section(QLatin1Char('/'), 1, 1));
    const QSize wanted = requestedSize.isValid() ? requestedSize : QSize(32, 32);

    QString file;
    for (const char* group : {"actions", "status", "apps", "devices", "places"}) {
        file = QStandardPaths::locate(QStandardPaths::GenericDataLocation,
                                      QStringLiteral("icons/suru/%1/scalable/%2.svg").arg(QLatin1String(group), name));
        if (!file.isEmpty())
            break;
    }
    QImageReader reader(file);
    reader.setScaledSize(wanted);
    QImage image = reader.read().convertToFormat(QImage::Format_ARGB32_Premultiplied);
    if (image.isNull()) {
        image = QImage(wanted, QImage::Format_ARGB32_Premultiplied);
        image.fill(Qt::transparent);
    } else {
        // Keep the shape, take the colour.
        QPainter painter(&image);
        painter.setCompositionMode(QPainter::CompositionMode_SourceIn);
        painter.fillRect(image.rect(), colour);
    }
    if (size)
        *size = image.size();
    return image;
}
