#pragma once

#include <QSet>
#include <QString>
#include <QVariantList>

#include "discord/models/Snowflake.hpp"

class Message;

// Renders Discord message content as Qt rich text (the subset QML's Text
// supports): markdown emphasis, code, spoilers, links, mentions, custom
// emoji and timestamps.
namespace MessageFormatter {

// Server nickname, else display name, else username; `fallback` when the
// user isn't known.
QString displayName(Snowflake user, Snowflake guild, const QString& fallback = QString());

// The theme's colours ("#rrggbb"), set from QML (MessageListModel.palette):
// subtext, code backgrounds, hidden spoilers and text.
struct Palette {
    QString muted = QStringLiteral("#888888");
    QString code = QStringLiteral("#e8e8e8");
    QString spoiler = QStringLiteral("#888888");
    QString text = QStringLiteral("#333333");
    QString link = QStringLiteral("#19b6ee");
};
void setPalette(const Palette& palette);

// emojiSize: pixel size of custom emoji images. Spoilers are links to
// "spoiler:<n>", numbered from `firstSpoiler`, hidden unless in `revealed`.
// Quotes are indented (see richBlocks() for the message view's bars).
QString richText(const QString& content, Snowflake guild, int emojiSize = 20,
                 const QSet<int>& revealed = {}, int firstSpoiler = 0);

// The same in blocks for the message view, which draws quotes' bars:
// [{text, quote}].
QVariantList richBlocks(const QString& content, Snowflake guild, int emojiSize = 20,
                        const QSet<int>& revealed = {});

// How many emoji the content is, when it is nothing but emoji (and spaces);
// else 0.
int emojiOnlyCount(const QString& content);

// Plain, single-line text for reply previews and notifications.
QString plainText(const QString& content, Snowflake guild);

// Joins, pins, calls, boosts and the like: one line of rich text naming
// the author, with a Suru icon. Empty text for regular messages.
struct SystemMessage {
    QString icon;
    QString text;
};
SystemMessage systemMessage(const Message& message, Snowflake guild);

// The same as plain text.
QString systemText(const Message& message, Snowflake guild);

}
