#include "MessageListModel.h"

#include <QDateTime>
#include <QVariantMap>

#include <list>

#include "discord/DiscordInstance.hpp"
#include "discord/state/MessageCache.hpp"

#include "DiscordUrls.h"
#include "MessageFormatter.h"
#include "models/MessageContent.h"

namespace {

// Messages from the same author within this window share one header.
constexpr time_t GroupWindowSeconds = 7 * 60;

QString str(const std::string& s)
{
    return QString::fromStdString(s);
}

bool isSystem(const Message& message)
{
    return !MessageFormatter::systemMessage(message, 0).text.isEmpty();
}

bool sameRows(const std::vector<MessagePtr>& a, size_t aFrom,
              const std::vector<MessagePtr>& b, size_t bFrom, size_t count)
{
    for (size_t i = 0; i < count; ++i) {
        if (a[aFrom + i]->m_snowflake != b[bFrom + i]->m_snowflake)
            return false;
    }
    return true;
}

}

int MessageListModel::rowCount(const QModelIndex& parent) const
{
    return parent.isValid() ? 0 : int(m_rows.size());
}

QVariant MessageListModel::data(const QModelIndex& index, int role) const
{
    if (!index.isValid() || index.row() >= int(m_rows.size()))
        return QVariant();

    const Row& row = m_rows[size_t(index.row())];
    const Message& m = *row.message;
    const MessageFormatter::SystemMessage system = MessageFormatter::systemMessage(m, m_guild);
    const bool systemRow = !system.text.isEmpty();

    switch (role) {
    case MessageIdRole: return DiscordUrls::id(m.m_snowflake);
    // Webhooks post under a name, not as a user with a profile.
    case AuthorIdRole:  return m.IsWebHook() ? QString() : DiscordUrls::id(m.m_author_snowflake);
    // Server nicknames, as they are now (see Session::requestMissingMembers).
    case AuthorRole:
        return m.IsWebHook() ? QString::fromStdString(m.m_author)
                             : MessageFormatter::displayName(m.m_author_snowflake, m_guild, QString::fromStdString(m.m_author));
    case AvatarUrlRole: return DiscordUrls::userAvatar(m.m_author_snowflake, m.m_avatar);
    case BodyRole: {
        auto one = [](const QString& text) {
            return QVariantList{QVariantMap{{QStringLiteral("text"), text}, {QStringLiteral("quote"), false}}};
        };
        if (systemRow)
            return one(system.text);
        if (m.m_type == MessageType::THREAD_STARTER_MESSAGE && !m.m_pReferencedMessage)
            return one(QStringLiteral("<i>Sorry, we couldn't load the first message in this thread.</i>"));
        return MessageContent::bodyIsEmbedLink(m) ? QVariantList() : richBody(m);
    }
    case PlainBodyRole:
        if (systemRow)
            return MessageFormatter::systemText(m, m_guild);
        if (m.m_bIsForward && m.m_pReferencedMessage)
            return str(m.m_pReferencedMessage->m_message);
        return str(m.m_message);
    case TimestampRole: {
        if (m.m_type == MessageType::SENDING_MESSAGE)
            return QStringLiteral("Sending...");
        if (!m.m_dateTime)
            return QString::fromStdString(m.m_dateCompact);
        // The time today, the date and time before.
        const QDateTime when = QDateTime::fromSecsSinceEpoch(qint64(m.m_dateTime));
        return when.date() == QDate::currentDate() ? when.toString(QStringLiteral("HH:mm"))
                                                   : when.toString(QStringLiteral("yyyy-MM-dd HH:mm"));
    }
    case EditedRole:    return m.m_timeEdited != 0;
    case IsOwnRole:     return m_ownUser != 0 && m.m_author_snowflake == m_ownUser;
    case IsPendingRole: return m.m_type == MessageType::SENDING_MESSAGE;
    case IsSystemRole:  return systemRow;
    case SystemIconRole: return system.icon;
    case GroupedRole:   return row.grouped;
    case SeparatedRole: return row.separated;
    case ReplyIdRole:
        return m.IsReply() && m.m_refMessageSnowflake
               && (m.m_refMessageChannel == 0 || m.m_refMessageChannel == m_channel)
                   ? DiscordUrls::id(m.m_refMessageSnowflake) : QString();
    case BlockedRole: {
        DiscordInstance* instance = GetDiscordInstance();
        return instance && instance->IsUserBlocked(m.m_author_snowflake);
    }
    case HasReplyRole:  return m.IsReply() && m.m_type != MessageType::THREAD_STARTER_MESSAGE && !systemRow;
    case ReplyAuthorRole:
        return !m.m_pReferencedMessage ? QString()
             : (m.m_pReferencedMessage->m_webhook_id != 0) ? QString::fromStdString(m.m_pReferencedMessage->m_author)
             : MessageFormatter::displayName(m.m_pReferencedMessage->m_author_snowflake, m_guild,
                                             QString::fromStdString(m.m_pReferencedMessage->m_author));
    case ReplyBodyRole:
        return m.m_pReferencedMessage
                   ? MessageFormatter::plainText(QString::fromStdString(m.m_pReferencedMessage->m_message), m_guild)
                   : QString();
    // System messages carry their data in embeds (AutoMod, poll results);
    // their line already says it all.
    case MediaRole:     return systemRow ? QVariantList() : MessageContent::media(m);
    case ReactionsRole: return MessageContent::reactions(m);
    case EmbedsRole:
        return systemRow ? QVariantList() : MessageContent::embeds(m, m_guild, m_emojiSize, m_revealedSpoilers.value(m.m_snowflake));
    case InteractionRole:
        if (m.m_interactionName.empty() || m.m_interactionUserName.empty())
            return QString();
        return m.m_type == MessageType::CONTEXT_MENU_COMMAND
                   ? QStringLiteral("<b>%1</b> used %2").arg(str(m.m_interactionUserName).toHtmlEscaped(),
                                                             str(m.m_interactionName).toHtmlEscaped())
                   : QStringLiteral("<b>%1</b> used <b>/%2</b>").arg(str(m.m_interactionUserName).toHtmlEscaped(),
                                                                     str(m.m_interactionName).toHtmlEscaped());
    case ForwardedRole: return m.m_bIsForward;
    case FirstNewRole:  return index.row() == m_firstNew;
    case StickersRole:  return systemRow ? QVariantList() : MessageContent::stickers(m);
    case PollRole:      return MessageContent::poll(m);
    case JumboRole:     return !systemRow && !m.m_bIsForward && isJumbo(m);
    }
    return QVariant();
}

QHash<int, QByteArray> MessageListModel::roleNames() const
{
    return {
        {MessageIdRole, "messageId"},
        {AuthorIdRole, "authorId"},
        {AuthorRole, "author"},
        {AvatarUrlRole, "avatarUrl"},
        {BodyRole, "body"},
        {PlainBodyRole, "plainBody"},
        {TimestampRole, "timestamp"},
        {EditedRole, "edited"},
        {IsOwnRole, "isOwn"},
        {IsPendingRole, "isPending"},
        {IsSystemRole, "isSystem"},
        {GroupedRole, "grouped"},
        {HasReplyRole, "hasReply"},
        {ReplyAuthorRole, "replyAuthor"},
        {ReplyBodyRole, "replyBody"},
        {MediaRole, "media"},
        {ReactionsRole, "reactions"},
        {EmbedsRole, "embeds"},
        {SystemIconRole, "systemIcon"},
        {InteractionRole, "interaction"},
        {ForwardedRole, "forwarded"},
        {StickersRole, "stickers"},
        {PollRole, "poll"},
        {JumboRole, "jumbo"},
        {SeparatedRole, "separated"},
        {BlockedRole, "blocked"},
        {ReplyIdRole, "replyId"},
        {FirstNewRole, "firstNew"},
    };
}

void MessageListModel::setChannel(Snowflake guild, Snowflake channel)
{
    if (m_channel == channel && m_guild == guild)
        return;
    m_guild = guild;
    m_channel = channel;
    m_newSince = 0;
    clear();
    sync();
}

void MessageListModel::clear()
{
    beginResetModel();
    m_rows.clear();
    m_bodyCache.clear();
    m_revealedSpoilers.clear();
    endResetModel();
    m_olderGap = 0;
    m_reachedStart = false;
    emit countChanged();
    emit hasOlderChanged();
    updateFirstNew();
}

std::vector<MessageListModel::Row> MessageListModel::readCache(Snowflake& olderGap, bool& reachedStart) const
{
    olderGap = 0;
    reachedStart = false;
    std::vector<Row> rows;
    if (!m_channel)
        return rows;

    std::list<MessagePtr> cached;
    GetMessageCache()->GetLoadedMessages(m_channel, m_guild, cached);

    // The cache is ordered oldest first; rows are newest first.
    for (auto it = cached.rbegin(); it != cached.rend(); ++it) {
        const MessagePtr& message = *it;
        if (message->m_type == MessageType::GAP_UP) {
            // Keep the oldest gap: that is where older history continues.
            olderGap = message->m_snowflake;
            continue;
        }
        if (message->m_type == MessageType::CHANNEL_HEADER) {
            reachedStart = true;
            continue;
        }
        if (message->IsLoadGap())
            continue;
        rows.push_back(Row{message, false});
    }
    computeGrouping(rows);
    return rows;
}

void MessageListModel::computeGrouping(std::vector<Row>& rows)
{
    for (size_t i = 0; i < rows.size(); ++i) {
        rows[i].grouped = false;
        // A separator wherever a message is not grouped with the one above
        // it: another author, or the same one after a while (or a reply).
        rows[i].separated = i + 1 < rows.size();
        if (i + 1 >= rows.size())
            continue;
        const Message& current = *rows[i].message;
        const Message& older = *rows[i + 1].message;
        if (current.m_author_snowflake != older.m_author_snowflake)
            continue;
        if (current.IsReply() || isSystem(current) || isSystem(older))
            continue;
        if (current.m_dateTime - older.m_dateTime > GroupWindowSeconds)
            continue;
        rows[i].grouped = true;
        rows[i].separated = false;
    }
}

void MessageListModel::sync()
{
    Snowflake olderGap = 0;
    bool reachedStart = false;
    std::vector<Row> fresh = readCache(olderGap, reachedStart);

    std::vector<MessagePtr> oldIds, newIds;
    for (const Row& row : m_rows)
        oldIds.push_back(row.message);
    for (const Row& row : fresh)
        newIds.push_back(row.message);

    const size_t oldCount = oldIds.size();
    const size_t newCount = newIds.size();

    // Work out where the old rows sit inside the new list, so that new
    // messages (front) and older history (back) are inserted instead of
    // resetting the view.
    size_t front = 0;
    bool aligned = false;
    if (oldCount > 0 && newCount >= oldCount) {
        for (size_t offset = 0; offset + oldCount <= newCount; ++offset) {
            if (newIds[offset]->m_snowflake == oldIds[0]->m_snowflake) {
                if (sameRows(newIds, offset, oldIds, 0, oldCount)) {
                    front = offset;
                    aligned = true;
                }
                break;
            }
        }
    }

    // Only deletions: the new list is the old one with some rows missing.
    bool onlyRemovals = false;
    if (!aligned && oldCount > 0 && newCount < oldCount) {
        size_t j = 0;
        for (size_t i = 0; i < oldCount && j < newCount; ++i) {
            if (oldIds[i]->m_snowflake == newIds[j]->m_snowflake)
                ++j;
        }
        onlyRemovals = j == newCount;
    }

    if (onlyRemovals) {
        size_t j = 0;
        for (size_t i = 0; i < m_rows.size();) {
            if (j < fresh.size() && m_rows[i].message->m_snowflake == fresh[j].message->m_snowflake) {
                m_rows[i] = fresh[j];
                ++i;
                ++j;
                continue;
            }
            beginRemoveRows(QModelIndex(), int(i), int(i));
            m_bodyCache.remove(m_rows[i].message->m_snowflake);
            m_rows.erase(m_rows.begin() + long(i));
            endRemoveRows();
        }
        if (!m_rows.empty())
            emit dataChanged(index(0), index(int(m_rows.size()) - 1), {GroupedRole, SeparatedRole});
        emit countChanged();
    } else if (!aligned) {
        beginResetModel();
        m_rows = std::move(fresh);
        endResetModel();
        emit countChanged();
    } else {
        const size_t back = newCount - oldCount - front;
        if (front > 0) {
            beginInsertRows(QModelIndex(), 0, int(front) - 1);
            m_rows.insert(m_rows.begin(), fresh.begin(), fresh.begin() + long(front));
            endInsertRows();
        }
        if (back > 0) {
            const int first = int(m_rows.size());
            beginInsertRows(QModelIndex(), first, first + int(back) - 1);
            m_rows.insert(m_rows.end(), fresh.end() - long(back), fresh.end());
            endInsertRows();
        }
        // Content (edits, embeds, grouping) may have changed for existing
        // rows; message objects are replaced on edit, so refresh them all.
        for (size_t i = 0; i < m_rows.size(); ++i) {
            if (m_rows[i].message != fresh[i].message)
                m_bodyCache.remove(fresh[i].message->m_snowflake);
            m_rows[i] = fresh[i];
        }
        if (!m_rows.empty())
            emit dataChanged(index(0), index(int(m_rows.size()) - 1));
        if (front > 0 || back > 0)
            emit countChanged();
    }

    if (olderGap != m_olderGap || reachedStart != m_reachedStart) {
        m_olderGap = olderGap;
        m_reachedStart = reachedStart;
        emit hasOlderChanged();
    }
    updateFirstNew();
}

void MessageListModel::setNewSince(Snowflake message)
{
    if (m_newSince == message)
        return;
    m_newSince = message;
    updateFirstNew();
}

// The oldest message after m_newSince that someone else sent. When it is
// the oldest one loaded and there is more history, the line can't be placed
// yet: the first new one may be further back.
void MessageListModel::updateFirstNew()
{
    int first = -1;
    bool any = false;
    if (m_newSince) {
        for (int i = int(m_rows.size()) - 1; i >= 0; --i) {
            const Message& m = *m_rows[size_t(i)].message;
            if (m.m_snowflake <= m_newSince || m.m_type == MessageType::SENDING_MESSAGE
                || (m_ownUser && m.m_author_snowflake == m_ownUser))
                continue;
            any = true;
            if (i < int(m_rows.size()) - 1 || !m_olderGap)
                first = i;
            break;
        }
    }
    if (first == m_firstNew && any == m_hasNew)
        return;
    const int old = m_firstNew;
    m_firstNew = first;
    m_hasNew = any;
    for (int row : {old, first}) {
        if (row >= 0 && row < int(m_rows.size()))
            emit dataChanged(index(row), index(row), {FirstNewRole});
    }
    emit firstNewChanged();
}

MessagePtr MessageListModel::olderGap() const
{
    if (!m_olderGap || !m_channel)
        return nullptr;
    return GetMessageCache()->GetLoadedMessage(m_channel, m_olderGap);
}

int MessageListModel::indexOfMessage(const QString& id) const
{
    const Snowflake message = DiscordUrls::fromId(id);
    for (size_t i = 0; i < m_rows.size(); ++i) {
        if (m_rows[i].message->m_snowflake == message)
            return int(i);
    }
    return -1;
}

Snowflake MessageListModel::newestMessageId() const
{
    for (const Row& row : m_rows) {
        if (row.message->m_type != MessageType::SENDING_MESSAGE)
            return row.message->m_snowflake;
    }
    return 0;
}

bool MessageListModel::isJumbo(const Message& message)
{
    const int count = MessageFormatter::emojiOnlyCount(QString::fromStdString(message.m_message));
    return count > 0 && count <= 3;
}

void MessageListModel::setEmojiSize(int size)
{
    if (size <= 0 || m_emojiSize == size)
        return;
    m_emojiSize = size;
    refreshBodies();
}

void MessageListModel::setJumboEmojiSize(int size)
{
    if (size <= 0 || m_jumboEmojiSize == size)
        return;
    m_jumboEmojiSize = size;
    refreshBodies();
}

// Members' names changed (nicknames arrived): authors, replies, and the
// mentions baked into the rich text.
void MessageListModel::refreshNames()
{
    m_bodyCache.clear();
    if (!m_rows.empty())
        emit dataChanged(index(0), index(int(m_rows.size()) - 1), {AuthorRole, ReplyAuthorRole, BodyRole});
}

std::set<Snowflake> MessageListModel::unknownMembers() const
{
    std::set<Snowflake> unknown;
    if (!m_guild)
        return unknown;
    auto consider = [this, &unknown](Snowflake user) {
        if (!user)
            return;
        Profile* profile = GetProfileCache()->LookupProfile(user, "", "", "", false);
        if (!profile || !profile->HasGuildMemberProfile(m_guild))
            unknown.insert(user);
    };
    for (const Row& row : m_rows) {
        const Message& m = *row.message;
        if (m.IsWebHook() || m.m_type >= MessageType::GAP_UP)
            continue;
        consider(m.m_author_snowflake);
        if (m.m_pReferencedMessage && !(m.m_pReferencedMessage->m_webhook_id != 0))
            consider(m.m_pReferencedMessage->m_author_snowflake);
        for (Snowflake user : m.m_userMentions)
            consider(user);
    }
    return unknown;
}

// The emoji sizes are baked into the rich text; render it again.
void MessageListModel::refreshBodies()
{
    m_bodyCache.clear();
    emit emojiSizeChanged();
    if (!m_rows.empty())
        emit dataChanged(index(0), index(int(m_rows.size()) - 1), {BodyRole});
}

// Forwards and thread starters show the message they carry.
QVariantList MessageListModel::richBody(const Message& message) const
{
    auto it = m_bodyCache.constFind(message.m_snowflake);
    if (it != m_bodyCache.constEnd())
        return *it;
    const bool carried = (message.m_bIsForward || message.m_type == MessageType::THREAD_STARTER_MESSAGE)
                         && message.m_pReferencedMessage;
    const std::string& content = carried ? message.m_pReferencedMessage->m_message : message.m_message;
    const QVariantList body = MessageFormatter::richBlocks(QString::fromStdString(content), m_guild,
                                                           isJumbo(message) ? m_jumboEmojiSize : m_emojiSize,
                                                           m_revealedSpoilers.value(message.m_snowflake));
    m_bodyCache.insert(message.m_snowflake, body);
    return body;
}

void MessageListModel::revealSpoiler(const QString& messageId, int spoiler)
{
    const Snowflake id = DiscordUrls::fromId(messageId);
    m_revealedSpoilers[id].insert(spoiler);
    m_bodyCache.remove(id);
    const int row = indexOfMessage(messageId);
    if (row >= 0)
        emit dataChanged(index(row), index(row), {BodyRole, EmbedsRole});
}

void MessageListModel::setPalette(const QVariantMap& palette)
{
    if (m_palette == palette)
        return;
    m_palette = palette;
    MessageFormatter::Palette colours;
    colours.muted = palette.value(QStringLiteral("muted"), colours.muted).toString();
    colours.code = palette.value(QStringLiteral("code"), colours.code).toString();
    colours.spoiler = palette.value(QStringLiteral("spoiler"), colours.spoiler).toString();
    colours.text = palette.value(QStringLiteral("text"), colours.text).toString();
    MessageFormatter::setPalette(colours);
    emit paletteChanged();
    m_bodyCache.clear();
    if (!m_rows.empty())
        emit dataChanged(index(0), index(int(m_rows.size()) - 1), {BodyRole, EmbedsRole});
}
