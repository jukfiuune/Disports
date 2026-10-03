#include "MessageFormatter.h"

#include <QDateTime>
#include <QLocale>
#include <QRegularExpression>
#include <QStringList>
#include <QTextBoundaryFinder>
#include <QTextDocumentFragment>

#include <algorithm>

#include "discord/DiscordInstance.hpp"
#include "discord/models/Message.hpp"
#include "discord/state/ProfileCache.hpp"

#include "DiscordUrls.h"
#include "models/ChannelListModel.h"

namespace {

QString userName(Snowflake user, Snowflake guild)
{
    return MessageFormatter::displayName(user, guild, QStringLiteral("user"));
}

QString channelName(Snowflake channel)
{
    DiscordInstance* instance = GetDiscordInstance();
    if (!instance)
        return QStringLiteral("channel");
    return QString::fromStdString(instance->LookupChannelNameGlobally(channel));
}

// A channel the account can open, named as the official client names it in
// a link ("#general", "@Alice"); empty when it can't be opened.
QString channelLinkLabel(Snowflake id, Snowflake* guild = nullptr)
{
    DiscordInstance* instance = GetDiscordInstance();
    Channel* channel = instance ? instance->GetChannel(id) : nullptr;
    if (!channel || (!channel->IsDM() && !channel->HasPermission(PERM_VIEW_CHANNEL)))
        return QString();
    if (guild)
        *guild = channel->m_parentGuild;
    const QString name = ChannelListModel::displayName(*channel);
    if (channel->m_channelType == Channel::DM)
        return QLatin1Char('@') + name;
    if (channel->m_channelType == Channel::GROUPDM)
        return name;
    return QLatin1Char('#') + name;
}

QString roleName(Snowflake role, Snowflake guild)
{
    DiscordInstance* instance = GetDiscordInstance();
    if (!instance)
        return QStringLiteral("role");
    return QString::fromStdString(instance->LookupRoleName(role, guild));
}

QString formatTimestamp(qint64 seconds, const QString& style)
{
    const QDateTime time = QDateTime::fromSecsSinceEpoch(seconds);
    const QLocale locale;
    if (style == QLatin1String("t"))
        return locale.toString(time.time(), QLocale::ShortFormat);
    if (style == QLatin1String("T"))
        return locale.toString(time.time(), QLocale::LongFormat);
    if (style == QLatin1String("d"))
        return locale.toString(time.date(), QLocale::ShortFormat);
    if (style == QLatin1String("D"))
        return locale.toString(time.date(), QLocale::LongFormat);
    if (style == QLatin1String("R")) {
        const qint64 diff = QDateTime::currentSecsSinceEpoch() - seconds;
        const qint64 abs = qAbs(diff);
        QString amount;
        if (abs < 60)
            amount = QStringLiteral("%1 seconds").arg(abs);
        else if (abs < 3600)
            amount = QStringLiteral("%1 minutes").arg(abs / 60);
        else if (abs < 86400)
            amount = QStringLiteral("%1 hours").arg(abs / 3600);
        else
            amount = QStringLiteral("%1 days").arg(abs / 86400);
        return diff >= 0 ? amount + QStringLiteral(" ago") : QStringLiteral("in ") + amount;
    }
    return locale.toString(time, QLocale::ShortFormat);
}

// Generated HTML is swapped for placeholders while the markdown rules run,
// so they cannot rewrite URLs or names inside it.
struct Protected {
    QStringList html;

    QString add(const QString& fragment)
    {
        html.append(fragment);
        return QChar(0xE000) + QString::number(html.size() - 1) + QChar(0xE001);
    }

    QString restore(QString text) const
    {
        static const QRegularExpression placeholder(QStringLiteral("\\x{E000}(\\d+)\\x{E001}"));
        QString out;
        qsizetype last = 0;
        auto it = placeholder.globalMatch(text);
        while (it.hasNext()) {
            const QRegularExpressionMatch m = it.next();
            out += text.mid(last, m.capturedStart() - last);
            out += html.value(m.captured(1).toInt());
            last = m.capturedEnd();
        }
        out += text.mid(last);
        return out;
    }
};

MessageFormatter::Palette s_palette;

// Links, mentions, custom emoji and timestamps, applied to HTML-escaped text
// (so "<" and ">" appear as entities). In rich mode the generated HTML is
// kept in `store`.
QString replaceTokens(QString text, Snowflake guild, bool rich, Protected* store = nullptr, int emojiSize = 20)
{
    static const QRegularExpression user(QStringLiteral("&lt;@!?(\\d+)&gt;"));
    static const QRegularExpression channel(QStringLiteral("&lt;#(\\d+)&gt;"));
    static const QRegularExpression role(QStringLiteral("&lt;@&amp;(\\d+)&gt;"));
    static const QRegularExpression emoji(QStringLiteral("&lt;(a?):(\\w+):(\\d+)&gt;"));
    static const QRegularExpression timestamp(QStringLiteral("&lt;t:(-?\\d+)(?::([tTdDfFR]))?&gt;"));

    auto replaceAll = [&text](const QRegularExpression& re, auto&& make) {
        QString out;
        qsizetype last = 0;
        auto it = re.globalMatch(text);
        while (it.hasNext()) {
            const QRegularExpressionMatch m = it.next();
            out += text.mid(last, m.capturedStart() - last);
            out += make(m);
            last = m.capturedEnd();
        }
        out += text.mid(last);
        text = out;
    };

    static const QRegularExpression link(QStringLiteral("https?://[^\\s<]+[^\\s<.,:;\"')\\]]"));

    auto html = [store](const QString& fragment) {
        return store ? store->add(fragment) : fragment;
    };
    auto mention = [rich, &html](const QString& label) {
        return rich ? html(QStringLiteral("<b>%1</b>").arg(label.toHtmlEscaped())) : label;
    };

    // Masked links, [label](https://...), used a lot by embeds and bots.
    static const QRegularExpression maskedLink(
        QStringLiteral("\\[([^\\]\\n]+)\\]\\((?:&lt;)?(https?://[^\\s)<>&]+(?:&amp;[^\\s)<>&]+)*)(?:&gt;)?\\)"));
    replaceAll(maskedLink, [&](const QRegularExpressionMatch& m) {
        return rich ? html(QStringLiteral("<a href=\"%1\">%2</a>").arg(m.captured(2), m.captured(1)))
                    : m.captured(1);
    });

    // Links to channels and messages the account can open show as the
    // channel's name (and a speech bubble for a message), and open it in the app
    // (Session::openChannelLink); others stay links for the browser.
    auto channelLink = [&](const QString& url, const QString& label) {
        return rich ? html(QStringLiteral("<a href=\"%1\" style=\"text-decoration:none\"><b>%2</b></a>")
                               .arg(url, label.toHtmlEscaped()))
                    : label;
    };
    static const QRegularExpression discordLink(DiscordUrls::channelLinkPattern());
    replaceAll(discordLink, [&](const QRegularExpressionMatch& m) {
        QString label = channelLinkLabel(DiscordUrls::fromId(m.captured(2)));
        if (label.isEmpty())
            return m.captured(0);
        if (m.captured(3).isEmpty())
            return channelLink(m.captured(0), label);
        // A message: "#general › " and a speech bubble, as the official
        // client shows it.
        label += QStringLiteral(" \u203A ");
        if (!rich)
            return label + QStringLiteral("message");
        const int iconSize = qMax(12, emojiSize);
        return html(QStringLiteral("<a href=\"%1\" style=\"text-decoration:none\"><b>%2</b>"
                                   "<img src=\"image://symbolic/message/%3\" width=\"%4\" height=\"%4\" align=\"middle\"></a>")
                        .arg(m.captured(0), label.toHtmlEscaped(), QString(s_palette.link).remove(QLatin1Char('#')))
                        .arg(iconSize));
    });

    if (rich) {
        replaceAll(link, [&](const QRegularExpressionMatch& m) {
            return html(QStringLiteral("<a href=\"%1\">%1</a>").arg(m.captured(0)));
        });
    }

    replaceAll(user, [&](const QRegularExpressionMatch& m) {
        return mention(QLatin1Char('@') + userName(DiscordUrls::fromId(m.captured(1)), guild));
    });
    replaceAll(role, [&](const QRegularExpressionMatch& m) {
        return mention(QLatin1Char('@') + roleName(DiscordUrls::fromId(m.captured(1)), guild));
    });
    replaceAll(channel, [&](const QRegularExpressionMatch& m) {
        const Snowflake id = DiscordUrls::fromId(m.captured(1));
        Snowflake channelGuild = 0;
        const QString label = channelLinkLabel(id, &channelGuild);
        if (label.isEmpty())
            return mention(QLatin1Char('#') + channelName(id));
        return channelLink(DiscordUrls::channelLink(channelGuild, id), label);
    });
    replaceAll(emoji, [&](const QRegularExpressionMatch& m) {
        if (!rich)
            return QStringLiteral(":%1:").arg(m.captured(2));
        const bool animated = !m.captured(1).isEmpty();
        return html(QStringLiteral("<img src=\"%1\" width=\"%2\" height=\"%2\">")
                        .arg(DiscordUrls::emoji(DiscordUrls::fromId(m.captured(3)), animated,
                                                emojiSize > 24 ? 96 : 48))
                        .arg(emojiSize));
    });
    replaceAll(timestamp, [&](const QRegularExpressionMatch& m) {
        const QString formatted = formatTimestamp(m.captured(1).toLongLong(), m.captured(2));
        return rich ? html(QStringLiteral("<b>%1</b>").arg(formatted.toHtmlEscaped())) : formatted;
    });
    return text;
}

// Quotes are marked while the text is built, and cut out or indented at
// the end (richBlocks(), richText()).
const QChar QuoteStart(0xE003);
const QChar QuoteEnd(0xE004);

// Emphasis, strike and spoilers on escaped text without code. Spoilers are
// numbered per message (`spoilers`) and hidden until tapped: links to
// "spoiler:<n>".
QString applyInline(QString text, int& spoilers, const QSet<int>& revealed)
{
    static const QRegularExpression bold(QStringLiteral("\\*\\*(.+?)\\*\\*"));
    static const QRegularExpression underline(QStringLiteral("__(.+?)__"));
    static const QRegularExpression italicStar(QStringLiteral("(?<![\\w*])\\*(?!\\s)(.+?)(?<!\\s)\\*(?![\\w*])"));
    static const QRegularExpression italicUnderscore(QStringLiteral("(?<![\\w_])_(?!\\s)(.+?)(?<!\\s)_(?![\\w_])"));
    static const QRegularExpression strike(QStringLiteral("~~(.+?)~~"));
    static const QRegularExpression spoiler(QStringLiteral("\\|\\|(.+?)\\|\\|"));

    text.replace(bold, QStringLiteral("<b>\\1</b>"));
    text.replace(underline, QStringLiteral("<u>\\1</u>"));
    text.replace(italicStar, QStringLiteral("<i>\\1</i>"));
    text.replace(italicUnderscore, QStringLiteral("<i>\\1</i>"));
    text.replace(strike, QStringLiteral("<s>\\1</s>"));
    QString out;
    qsizetype last = 0;
    auto it = spoiler.globalMatch(text);
    while (it.hasNext()) {
        const QRegularExpressionMatch m = it.next();
        out += text.mid(last, m.capturedStart() - last);
        const int n = spoilers++;
        const bool shown = revealed.contains(n);
        out += QStringLiteral("<a href=\"spoiler:%1\" style=\"text-decoration:none\">"
                              "<span style=\"background-color:%2;color:%3\">%4</span></a>")
                   .arg(n)
                   .arg(shown ? s_palette.code : s_palette.spoiler, shown ? s_palette.text : s_palette.spoiler,
                        m.captured(1));
        last = m.capturedEnd();
    }
    return out + text.mid(last);
}

// A line of markdown blocks: headings, subtext and list bullets.
QString formatLine(const QString& line)
{
    if (line.startsWith(QLatin1String("### ")))
        return QStringLiteral("<b>%1</b>").arg(line.mid(4));
    if (line.startsWith(QLatin1String("## ")))
        return QStringLiteral("<b><big>%1</big></b>").arg(line.mid(3));
    if (line.startsWith(QLatin1String("# ")))
        return QStringLiteral("<b><big><big>%1</big></big></b>").arg(line.mid(2));
    if (line.startsWith(QLatin1String("-# ")))
        return QStringLiteral("<font size=\"2\" color=\"%1\">%2</font>").arg(s_palette.muted, line.mid(3));
    if (line.startsWith(QLatin1String("- ")) || line.startsWith(QLatin1String("* ")))
        return QStringLiteral("• %1").arg(line.mid(2));
    if (line.startsWith(QLatin1String("  - ")) || line.startsWith(QLatin1String("  * ")))
        return QStringLiteral("&nbsp;&nbsp;&nbsp;&nbsp;◦ %1").arg(line.mid(4));
    return line;
}

// A block quote, marked for richBlocks() (a bar on the left, as on
// Discord) or richText() (indented).
QString quoteBlock(const QStringList& lines)
{
    return QuoteStart + lines.join(QStringLiteral("<br>")) + QuoteEnd;
}

// Headings, subtext, lists and block quotes, per line. Lines after "> "
// are quoted together; ">>> " quotes the rest of the text.
QString applyBlocks(const QString& text)
{
    QString out;
    QStringList quote;
    bool quoteRest = false;
    bool afterLine = false; // a line was written: a break before the next
    auto flushQuote = [&]() {
        if (quote.isEmpty())
            return;
        // A table is a block of its own: no breaks around it.
        out += quoteBlock(quote);
        quote.clear();
        afterLine = false;
    };
    for (const QString& line : text.split(QLatin1Char('\n'))) {
        if (quoteRest) {
            quote.append(formatLine(line));
        } else if (line.startsWith(QLatin1String("&gt;&gt;&gt; "))) {
            quoteRest = true;
            quote.append(formatLine(line.mid(13)));
        } else if (line.startsWith(QLatin1String("&gt; ")) || line == QLatin1String("&gt;")) {
            quote.append(formatLine(line.mid(5)));
        } else {
            flushQuote();
            if (afterLine)
                out += QStringLiteral("<br>");
            out += formatLine(line);
            afterLine = true;
        }
    }
    flushQuote();
    return out;
}

}

namespace MessageFormatter {

QString displayName(Snowflake user, Snowflake guild, const QString& fallback)
{
    Profile* profile = user ? GetProfileCache()->LookupProfile(user, "", "", "", false) : nullptr;
    if (!profile)
        return fallback;
    if (guild) {
        auto member = profile->m_guildMembers.find(guild);
        if (member != profile->m_guildMembers.end() && !member->second.m_nick.empty())
            return QString::fromStdString(member->second.m_nick);
    }
    if (!profile->m_globalName.empty())
        return QString::fromStdString(profile->m_globalName);
    if (!profile->GetUsername().empty())
        return QString::fromStdString(profile->GetUsername());
    return fallback;
}

namespace {

// Whether a grapheme cluster is an emoji: pictographs, symbols that have an
// emoji presentation, flags, keycaps and ZWJ sequences.
bool isEmojiCluster(const QString& cluster)
{
    bool pictograph = false;
    for (const char32_t cp : cluster.toUcs4()) {
        if (cp == 0xFE0F || cp == 0x20E3)          // emoji presentation, keycap
            return true;
        if ((cp >= 0x1F000 && cp <= 0x1FAFF)       // pictographs, flags, faces
            || (cp >= 0x2600 && cp <= 0x27BF)      // misc symbols, dingbats
            || (cp >= 0x2B00 && cp <= 0x2BFF)      // arrows, stars
            || (cp >= 0x2300 && cp <= 0x23FF)      // watch, hourglass, ...
            || (cp >= 0x2190 && cp <= 0x21FF)      // arrows
            || cp == 0x00A9 || cp == 0x00AE || cp == 0x203C || cp == 0x2049
            || cp == 0x2122 || cp == 0x2139 || cp == 0x3030 || cp == 0x303D
            || cp == 0x3297 || cp == 0x3299 || cp == 0x24C2)
            pictograph = true;
        else if (cp != 0x200D && !(cp >= 0x1F3FB && cp <= 0x1F3FF) && !(cp >= 0xE0020 && cp <= 0xE007F))
            return false;                          // anything else: text
    }
    return pictograph;
}

}

int emojiOnlyCount(const QString& content)
{
    static const QRegularExpression custom(QStringLiteral("<a?:\\w+:\\d+>"));
    int count = 0;
    QString rest = content;
    rest.replace(custom, QStringLiteral(" "));
    count += int(content.count(custom));

    rest = rest.simplified().remove(QLatin1Char(' '));
    QTextBoundaryFinder finder(QTextBoundaryFinder::Grapheme, rest);
    qsizetype start = 0;
    while (finder.toNextBoundary() != -1) {
        const qsizetype end = finder.position();
        if (!isEmojiCluster(rest.mid(start, end - start)))
            return 0;
        ++count;
        start = end;
    }
    return count;
}

void setPalette(const Palette& palette)
{
    s_palette = palette;
}

namespace {

// Rich text with quotes marked (QuoteStart, QuoteEnd).
QString markedText(const QString& content, Snowflake guild, int emojiSize, const QSet<int>& revealed,
                   int firstSpoiler)
{
    // Split out code first so nothing inside it is formatted.
    static const QRegularExpression code(QStringLiteral("```(?:[\\w+-]*\\n)?([\\s\\S]*?)```|`([^`\\n]+)`"));

    QString result;
    qsizetype last = 0;
    int spoilers = firstSpoiler;
    auto flushText = [&](qsizetype end) {
        Protected store;
        const QString escaped = content.mid(last, end - last).toHtmlEscaped();
        result += store.restore(
            applyBlocks(applyInline(replaceTokens(escaped, guild, true, &store, emojiSize), spoilers, revealed)));
    };
    const QString mono = QStringLiteral("<font face=\"Ubuntu Mono,monospace\">%1</font>");

    auto it = code.globalMatch(content);
    while (it.hasNext()) {
        const QRegularExpressionMatch m = it.next();
        const bool block = m.capturedLength(1) > 0 || m.captured(0).startsWith(QLatin1String("```"));
        // A block is a box of its own line: not the line break before it.
        qsizetype end = m.capturedStart();
        if (block && end > last && content.at(end - 1) == QLatin1Char('\n'))
            --end;
        flushText(end);
        if (block) {
            QString lines = m.captured(1).toHtmlEscaped();
            if (lines.endsWith(QLatin1Char('\n')))
                lines.chop(1);
            lines.replace(QLatin1Char('\n'), QStringLiteral("<br>"));
            lines.replace(QLatin1Char(' '), QStringLiteral("&nbsp;"));
            result += QStringLiteral("<table width=\"100%\" cellspacing=\"0\" cellpadding=\"6\" bgcolor=\"%1\">"
                                     "<tr><td>%2</td></tr></table>").arg(s_palette.code, mono.arg(lines));
        } else {
            result += QStringLiteral("<span style=\"background-color:%1\">%2</span>")
                          .arg(s_palette.code, mono.arg(QStringLiteral("&nbsp;") + m.captured(2).toHtmlEscaped()
                                                        + QStringLiteral("&nbsp;")));
        }
        last = m.capturedEnd();
        // Nor the one after it.
        if (block && last < content.size() && content.at(last) == QLatin1Char('\n'))
            ++last;
    }
    flushText(content.size());
    return result;
}

}

QString richText(const QString& content, Snowflake guild, int emojiSize, const QSet<int>& revealed, int firstSpoiler)
{
    QString text = markedText(content, guild, emojiSize, revealed, firstSpoiler);
    text.replace(QuoteStart, QStringLiteral("<blockquote>"));
    text.replace(QuoteEnd, QStringLiteral("</blockquote>"));
    return text;
}

QVariantList richBlocks(const QString& content, Snowflake guild, int emojiSize, const QSet<int>& revealed)
{
    const QString text = markedText(content, guild, emojiSize, revealed, 0);
    QVariantList blocks;
    auto add = [&blocks](const QString& part, bool quote) {
        if (!part.isEmpty())
            blocks.append(QVariantMap{{QStringLiteral("text"), part}, {QStringLiteral("quote"), quote}});
    };
    qsizetype last = 0;
    while (true) {
        const qsizetype start = text.indexOf(QuoteStart, last);
        if (start < 0)
            break;
        const qsizetype end = text.indexOf(QuoteEnd, start);
        add(text.mid(last, start - last), false);
        add(text.mid(start + 1, (end < 0 ? text.size() : end) - start - 1), true);
        last = end < 0 ? text.size() : end + 1;
    }
    add(text.mid(last), false);
    return blocks;
}

QString plainText(const QString& content, Snowflake guild)
{
    QString text = replaceTokens(content.toHtmlEscaped(), guild, false);
    // Undo the escaping: the result is shown as plain text.
    text.replace(QLatin1String("&lt;"), QLatin1String("<"));
    text.replace(QLatin1String("&gt;"), QLatin1String(">"));
    text.replace(QLatin1String("&quot;"), QLatin1String("\""));
    text.replace(QLatin1String("&amp;"), QLatin1String("&"));
    text.replace(QLatin1Char('\n'), QLatin1Char(' '));
    return text;
}

namespace {

QString bold(const QString& text)
{
    return QStringLiteral("<b>%1</b>").arg(text.toHtmlEscaped());
}

// "a few seconds", "5 minutes", "2 hours", like Discord's call durations.
QString humanDuration(qint64 seconds)
{
    if (seconds < 60)
        return QStringLiteral("a few seconds");
    if (seconds < 3600) {
        const qint64 minutes = seconds / 60;
        return minutes == 1 ? QStringLiteral("a minute") : QStringLiteral("%1 minutes").arg(minutes);
    }
    const qint64 hours = seconds / 3600;
    return hours == 1 ? QStringLiteral("an hour") : QStringLiteral("%1 hours").arg(hours);
}

QString guildName(Snowflake guild)
{
    DiscordInstance* instance = GetDiscordInstance();
    Guild* g = instance && guild ? instance->GetGuild(guild) : nullptr;
    return g ? QString::fromStdString(g->m_name) : QStringLiteral("the server");
}

// A field of an embed, by name; system embeds (poll results, AutoMod)
// carry their data this way.
QString embedField(const Message& m, const char* name)
{
    for (const RichEmbed& e : m.m_embeds)
        for (const RichEmbedField& f : e.m_fields)
            if (f.m_title == name)
                return QString::fromStdString(f.m_value);
    return QString();
}

// Discord's USER_JOIN greetings; which one is picked by the message's
// timestamp in milliseconds, modulo 13.
const char* const JoinMessages[] = {
    "%1 joined the party.",
    "%1 is here.",
    "Welcome, %1. We hope you brought pizza.",
    "A wild %1 appeared.",
    "%1 just landed.",
    "%1 just slid into the server.",
    "%1 just showed up!",
    "Welcome %1. Say hi!",
    "%1 hopped into the server.",
    "Everyone welcome %1!",
    "Glad you're here, %1.",
    "Good to see you, %1.",
    "Yay you made it, %1!",
};

}

SystemMessage systemMessage(const Message& m, Snowflake guild)
{
    using namespace MessageType;
    const QString author = bold(m.IsWebHook() ? QString::fromStdString(m.m_author)
                                              : displayName(m.m_author_snowflake, guild, QString::fromStdString(m.m_author)));
    const QString content = QString::fromStdString(m.m_message);
    const QString mention = m.m_userMentions.empty()
                                ? QStringLiteral("someone")
                                : bold(userName(*m.m_userMentions.begin(), guild));
    const QString place = guild ? QStringLiteral("the thread") : QStringLiteral("the group");
    auto line = [](const char* icon, const QString& text) {
        return SystemMessage{QString::fromLatin1(icon), text};
    };

    switch (m.m_type) {
    case RECIPIENT_ADD:
        return line("contact-new", QStringLiteral("%1 added %2 to %3.").arg(author, mention, place));
    case RECIPIENT_REMOVE:
        if (!m.m_userMentions.empty() && *m.m_userMentions.begin() == m.m_author_snowflake)
            return line("remove-from-group", QStringLiteral("%1 left %2.").arg(author, place));
        return line("remove-from-group", QStringLiteral("%1 removed %2 from %3.").arg(author, mention, place));
    case CALL: {
        DiscordInstance* instance = GetDiscordInstance();
        const Snowflake me = instance ? instance->GetUserID() : 0;
        if (!m.m_bHasCall || m.m_callEnded == 0)
            return line("call-start", QStringLiteral("%1 started a call.").arg(author));
        const QString duration = humanDuration(qint64(m.m_callEnded) - qint64(m.m_dateTime));
        const bool joined = std::find(m.m_callParticipants.begin(), m.m_callParticipants.end(), me)
                            != m.m_callParticipants.end();
        if (!joined && m.m_author_snowflake != me)
            return line("missed-call", QStringLiteral("You missed a call from %1 that lasted %2.").arg(author, duration));
        return line("call-end", QStringLiteral("%1 started a call that lasted %2.").arg(author, duration));
    }
    case CHANNEL_NAME_CHANGE:
        if (content.isEmpty())
            return line("edit", QStringLiteral("%1 removed the custom group name.").arg(author));
        return line("edit", QStringLiteral("%1 changed the channel name: %2").arg(author, bold(content)));
    case CHANNEL_ICON_CHANGE:
        return line("insert-image", QStringLiteral("%1 changed the channel icon.").arg(author));
    case CHANNEL_PINNED_MESSAGE:
        return line("pinned", QStringLiteral("%1 pinned a message to this channel.").arg(author));
    case USER_JOIN: {
        const quint64 ms = (quint64(m.m_snowflake) >> 22) + 1420070400000ULL;
        return line("contact-new", QString::fromLatin1(JoinMessages[ms % 13]).arg(author));
    }
    case GUILD_BOOST:
    case GUILD_BOOST_TIER_1:
    case GUILD_BOOST_TIER_2:
    case GUILD_BOOST_TIER_3: {
        QString text = content.toInt() > 1
                           ? QStringLiteral("%1 just boosted the server %2 times!").arg(author, bold(content))
                           : QStringLiteral("%1 just boosted the server!").arg(author);
        if (m.m_type != GUILD_BOOST)
            text += QStringLiteral(" %1 has achieved %2!")
                        .arg(bold(guildName(guild)), bold(QStringLiteral("Level %1").arg(int(m.m_type) - int(GUILD_BOOST))));
        return line("starred", text);
    }
    case CHANNEL_FOLLOW_ADD:
        return line("share", QStringLiteral("%1 has added %2 to this channel. Its most important updates will show up here.")
                                 .arg(author, bold(content)));
    case GUILD_STREAM:
        return line("stock_video", QStringLiteral("%1 started streaming.").arg(author));
    case GUILD_DISCOVERY_DISQUALIFIED:
        return line("info", QStringLiteral("This server has been removed from Server Discovery because it no longer "
                                           "passes all the requirements."));
    case GUILD_DISCOVERY_REQUALIFIED:
        return line("info", QStringLiteral("This server is eligible for Server Discovery again and has been "
                                           "automatically relisted!"));
    case GUILD_DISCOVERY_GRACE_PERIOD_INITIAL_WARNING:
        return line("dialog-warning-symbolic", QStringLiteral("This server has failed Discovery activity requirements for 1 week."));
    case GUILD_DISCOVERY_GRACE_PERIOD_FINAL_WARNING:
        return line("dialog-warning-symbolic", QStringLiteral("This server has failed Discovery activity requirements "
                                                              "for 3 weeks in a row."));
    case THREAD_CREATED:
        return line("message", QStringLiteral("%1 started a thread: %2").arg(author, bold(content)));
    case GUILD_INVITE_REMINDER:
        return line("contact-group", QStringLiteral("Wondering who to invite? Start by inviting anyone who can help "
                                                    "you build the server!"));
    case AUTO_MODERATION_ACTION: {
        const QString rule = embedField(m, "rule_name");
        const QString blocked = m.m_embeds.empty() ? QString()
                                                   : QString::fromStdString(m.m_embeds.front().m_description);
        QString text = QStringLiteral("AutoMod blocked a message from %1").arg(author);
        if (!rule.isEmpty())
            text += QStringLiteral(" (%1)").arg(rule.toHtmlEscaped());
        if (!blocked.isEmpty())
            text += QStringLiteral(": <i>%1</i>").arg(blocked.toHtmlEscaped());
        return line("security-alert", text);
    }
    case ROLE_SUBSCRIPTION_PURCHASE: {
        const int months = qMax(1, m.m_roleSubscriptionMonths);
        return line("starred", QStringLiteral("%1 %2 %3 and has been a subscriber of %4 for %5 %6!")
                                   .arg(author,
                                        m.m_bRoleSubscriptionRenewal ? QStringLiteral("renewed") : QStringLiteral("joined"),
                                        bold(QString::fromStdString(m.m_roleSubscriptionTier)),
                                        bold(guildName(guild)))
                                   .arg(months)
                                   .arg(months == 1 ? QStringLiteral("month") : QStringLiteral("months")));
    }
    case STAGE_START:
        return line("speaker", QStringLiteral("%1 started %2").arg(author, bold(content)));
    case STAGE_END:
        return line("speaker", QStringLiteral("%1 ended %2").arg(author, bold(content)));
    case STAGE_SPEAKER:
        return line("audio-input-microphone-high-symbolic", QStringLiteral("%1 is now a speaker.").arg(author));
    case STAGE_RAISE_HAND:
        return line("dialog-question-symbolic", QStringLiteral("%1 requested to speak.").arg(author));
    case STAGE_TOPIC:
        return line("speaker", QStringLiteral("%1 changed the Stage topic: %2").arg(author, bold(content)));
    case GUILD_APPLICATION_PREMIUM_SUBSCRIPTION:
        return line("starred", QStringLiteral("%1 upgraded an app to premium for this server!").arg(author));
    case PRIVATE_CHANNEL_INTEGRATION_ADDED:
        return line("stock_application", QStringLiteral("%1 added an app to %2.").arg(author, place));
    case PRIVATE_CHANNEL_INTEGRATION_REMOVED:
        return line("stock_application", QStringLiteral("%1 removed an app from %2.").arg(author, place));
    case GUILD_INCIDENT_ALERT_MODE_ENABLED: {
        const QDateTime until = QDateTime::fromString(content, Qt::ISODateWithMs);
        const QString when = until.isValid() ? QLocale().toString(until.toLocalTime(), QLocale::ShortFormat) : content;
        return line("lock", QStringLiteral("%1 enabled security actions until %2.").arg(author, bold(when)));
    }
    case GUILD_INCIDENT_ALERT_MODE_DISABLED:
        return line("lock-broken", QStringLiteral("%1 disabled security actions.").arg(author));
    case GUILD_INCIDENT_REPORT_RAID:
        return line("security-alert", QStringLiteral("%1 reported a raid in %2.").arg(author, bold(guildName(guild))));
    case GUILD_INCIDENT_REPORT_FALSE_ALARM:
        return line("security-alert", QStringLiteral("%1 reported a false alarm in %2.").arg(author, bold(guildName(guild))));
    case PURCHASE_NOTIFICATION:
        return line("stock_store", QStringLiteral("%1 made a purchase in the server shop!").arg(author));
    case POLL_RESULT: {
        const QString question = embedField(m, "poll_question_text");
        const QString winner = embedField(m, "victor_answer_text");
        const QString votes = embedField(m, "victor_answer_votes");
        const QString total = embedField(m, "total_votes");
        QString text = QStringLiteral("%1's poll %2 has closed.").arg(author, bold(question));
        if (!winner.isEmpty())
            text += QStringLiteral(" Winner: %1 (%2 of %3 votes)").arg(bold(winner), votes, total);
        else
            text += total.toInt() > 0 ? QStringLiteral(" It ended in a tie.") : QStringLiteral(" Nobody voted.");
        return line("ok", text);
    }
    case IN_GAME_MESSAGE_NUX:
        return line("stock_application", QStringLiteral("%1 messaged you from a game.").arg(author));
    case GUILD_JOIN_REQUEST_ACCEPT_NOTIFICATION:
        return line("contact-new", QStringLiteral("An application to %1 was approved! Welcome!").arg(bold(content)));
    case GUILD_JOIN_REQUEST_REJECT_NOTIFICATION:
        return line("remove-from-group", QStringLiteral("An application to %1 was rejected.").arg(bold(content)));
    case GUILD_JOIN_REQUEST_WITHDRAWN_NOTIFICATION:
        return line("remove-from-group", QStringLiteral("An application to %1 has been withdrawn.").arg(bold(content)));
    case HD_STREAMING_UPGRADED:
        return line("stock_video", QStringLiteral("%1 activated HD streaming.").arg(author));
    case CHAT_WALLPAPER_SET:
        return line("preferences-desktop-wallpaper-symbolic", QStringLiteral("%1 changed the DM wallpaper.").arg(author));
    case CHAT_WALLPAPER_REMOVE:
        return line("preferences-desktop-wallpaper-symbolic", QStringLiteral("%1 removed the DM wallpaper.").arg(author));
    case REPORT_TO_MOD_DELETED_MESSAGE:
        return line("security-alert", QStringLiteral("%1 deleted the message.").arg(author));
    case REPORT_TO_MOD_TIMEOUT_USER:
        return line("security-alert", QStringLiteral("%1 timed out %2.").arg(author, mention));
    case REPORT_TO_MOD_KICK_USER:
        return line("security-alert", QStringLiteral("%1 kicked %2.").arg(author, mention));
    case REPORT_TO_MOD_BAN_USER:
        return line("security-alert", QStringLiteral("%1 banned %2.").arg(author, mention));
    case REPORT_TO_MOD_CLOSED_REPORT:
        return line("security-alert", QStringLiteral("%1 resolved this flag.").arg(author));
    case EMOJI_ADDED:
        return line("ayatana-indicator-keyboard-emoji",
                    QStringLiteral("%1 added a new emoji, %2").arg(author, richText(content, guild)));
    case VOICE_SESSION:
        return line("speaker", QStringLiteral("%1 started a voice hangout.").arg(author));
    case FRIEND_REQUEST_ACCEPTED:
        return line("contact", QStringLiteral("%1 accepted your friend request.").arg(author));
    // Messages Discord draws as a special card (gifts, Nitro offers, invites
    // to hang out): not supported yet, say so instead of showing nothing.
    case CUSTOM_GIFT:
    case VOICE_HANGOUT_INVITE:
    case NITRO_NOTIFICATION:
    case GIFTING_PROMPT:
    case PREMIUM_GROUP_INVITE:
    case GUILD_BOOST_UPSELL:
        if (!content.isEmpty())
            return {};
        return line("info", QStringLiteral("%1 sent a message Disports can't show yet.").arg(author));
    default:
        // Types newer than this list, when there is nothing else to show.
        if (int(m.m_type) > int(MEDIA_MENTION_MESSAGE) && int(m.m_type) < int(GAP_UP)
                && content.isEmpty() && m.m_attachments.empty() && m.m_embeds.empty())
            return line("info", QStringLiteral("%1 sent a message Disports can't show yet.").arg(author));
        return {};
    }
}

QString systemText(const Message& message, Snowflake guild)
{
    const SystemMessage system = systemMessage(message, guild);
    if (system.text.isEmpty())
        return QString();
    return QTextDocumentFragment::fromHtml(system.text).toPlainText();
}

}
