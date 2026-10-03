#include "DiscordUrls.h"

#include <QRegularExpression>
#include <QStringList>

#include "discord/network/DiscordAPI.hpp"

namespace DiscordUrls {

QString cdn()
{
    return QString::fromStdString(GetDiscordCDN());
}

QString userAvatar(Snowflake user, const std::string& hash, int size)
{
    if (hash.empty() || hash == "0") {
        // Default avatars are chosen by the new-username-system formula.
        const quint64 index = (quint64(user) >> 22) % 6;
        return cdn() + QStringLiteral("embed/avatars/%1.png").arg(index);
    }
    return cdn() + QStringLiteral("avatars/%1/%2.png?size=%3")
                       .arg(id(user), QString::fromStdString(hash))
                       .arg(size);
}

QString guildIcon(Snowflake guild, const std::string& hash, int size)
{
    if (hash.empty())
        return QString();
    return cdn() + QStringLiteral("icons/%1/%2.png?size=%3")
                       .arg(id(guild), QString::fromStdString(hash))
                       .arg(size);
}

QString channelIcon(Snowflake channel, const std::string& hash, int size)
{
    if (hash.empty())
        return QString();
    return cdn() + QStringLiteral("channel-icons/%1/%2.png?size=%3")
                       .arg(id(channel), QString::fromStdString(hash))
                       .arg(size);
}

QString emoji(Snowflake emojiId, bool, int size)
{
    // Always the still image, even for animated emoji: nothing in the chat
    // animates on its own (and it is a smaller download).
    return cdn() + QStringLiteral("emojis/%1.png?size=%2").arg(id(emojiId)).arg(size);
}

QString sticker(Snowflake stickerId, bool gif, int size)
{
    // GIF stickers are only served by the media proxy.
    QString base = cdn();
    if (gif && base == QLatin1String("https://cdn.discordapp.com/"))
        base = QStringLiteral("https://media.discordapp.net/");
    return base + QStringLiteral("stickers/%1.%2?size=%3")
                      .arg(id(stickerId), gif ? QStringLiteral("gif") : QStringLiteral("png"))
                      .arg(size);
}

QString lottieSticker(Snowflake stickerId)
{
    return cdn() + QStringLiteral("stickers/%1.json").arg(id(stickerId));
}

QString initials(const QString& name)
{
    QString result;
    const QStringList words = name.split(QLatin1Char(' '), Qt::SkipEmptyParts);
    for (const QString& word : words) {
        result += word.at(0);
        if (result.size() == 2)
            break;
    }
    return result.isEmpty() ? name.left(2) : result;
}

const QString& channelLinkPattern()
{
    static const QString pattern(QStringLiteral(
        "https?://(?:(?:ptb|canary|www)\\.)?discord(?:app)?\\.com/channels/(@me|\\d+)/(\\d+)(?:/(\\d+))?/?"));
    return pattern;
}

QString channelLink(Snowflake guild, Snowflake channel, Snowflake message)
{
    QString url = QStringLiteral("https://discord.com/channels/%1/%2")
                      .arg(guild ? id(guild) : QStringLiteral("@me"), id(channel));
    if (message)
        url += QLatin1Char('/') + id(message);
    return url;
}

bool parseChannelLink(const QString& url, ChannelLink& link)
{
    static const QRegularExpression re(QRegularExpression::anchoredPattern(channelLinkPattern()));
    const QRegularExpressionMatch m = re.match(url.trimmed());
    if (!m.hasMatch())
        return false;
    link.channel = fromId(m.captured(2));
    link.message = fromId(m.captured(3));
    return link.channel != 0;
}

}
