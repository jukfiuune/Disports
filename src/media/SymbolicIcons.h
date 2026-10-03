#pragma once

#include <QQuickImageProvider>

// Theme (Suru) icons tinted one colour, for rich text, which can't colour
// an image: <img src="image://symbolic/message/3584e4"> (name/RRGGBB).
// MessageFormatter::symbolicIcon() builds the tag.
class SymbolicIcons : public QQuickImageProvider
{
public:
    SymbolicIcons();
    QImage requestImage(const QString& id, QSize* size, const QSize& requestedSize) override;
};
