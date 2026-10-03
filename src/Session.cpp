#include "Session.h"

#include <QDateTime>
#include <QDir>
#include <QGuiApplication>
#include <QStandardPaths>

#include <algorithm>
#include <utility>

#include "discord/DiscordInstance.hpp"
#include "discord/config/DiscordClientConfig.hpp"
#include "discord/config/LocalSettings.hpp"
#include "discord/state/MessageCache.hpp"
#include "discord/state/ProfileCache.hpp"

#include "ChannelInfo.h"
#include "DiscordUrls.h"
#include "Log.h"
#include "Migration.h"
#include "backend/CoreGlobals.h"
#include "backend/QtFrontend.h"
#include "backend/QtHttpClient.h"
#include "backend/QtWebsocketClient.h"
#include "media/GstVideoPlayer.h"

namespace {

Snowflake guildOfChannel(DiscordInstance* instance, Snowflake channel)
{
    if (instance->m_dmGuild.GetChannel(channel))
        return 0;
    for (Guild& guild : instance->m_guilds) {
        if (guild.GetChannel(channel))
            return guild.m_snowflake;
    }
    return 0;
}

}

Session::Session(QObject* parent)
    : QObject(parent)
{
    m_http = new QtHttpClient(this);
    m_sockets = new QtWebsocketClient(this);
    m_frontend = std::make_unique<QtFrontend>(this);
    CoreGlobals::setHttpClient(m_http);
    CoreGlobals::setWebsocketClient(m_sockets);
    CoreGlobals::setFrontend(m_frontend.get());

    m_connection = new GatewayConnection(this, m_sockets);
    m_permissions = new ChannelPermissions(this);
    m_sender = new MessageSender(this);
    m_typing = new TypingIndicator(this);
    m_mentions = new MentionSuggester(this);
    m_guilds = new GuildListModel(this);
    m_channels = new ChannelListModel(this);
    m_messages = new MessageListModel(this);
    m_unreadDms = new UnreadDmListModel(this);
    m_preferences = new Preferences(this);
    m_emoji = new EmojiPickerModel(this);
    m_offline = new OfflineCache(this);

    m_voiceStates = new VoiceStates(this);
    m_guilds->setVoiceStates(m_voiceStates);
    m_channels->setVoiceStates(m_voiceStates);
    connect(m_voiceStates, &VoiceStates::changed, this, [this](Snowflake, Snowflake channel) {
        m_guilds->refreshCalls();
        if (channel)
            m_channels->refreshChannel(channel);
        else
            m_channels->refreshAll();
        updateCurrentCall();
    });
    m_callClock.setInterval(1000);
    connect(&m_callClock, &QTimer::timeout, this, &Session::currentCallChanged);

    m_call = new CallManager(this);
    connect(m_call, &CallManager::callFailed, this, &Session::showNotice);
    connect(m_call, &CallManager::notice, this, &Session::showNotice);

    m_captcha = new CaptchaPrompt(this);
    m_http->setCaptchaPrompt(m_captcha);
    m_qrLogin = new RemoteAuth(m_http->networkAccessManager(), this);
    m_qrLogin->setCaptchaPrompt(m_captcha);
    connect(m_qrLogin, &RemoteAuth::tokenReceived, this, &Session::loginWithToken);
    m_passwordLogin = new PasswordLogin(m_http->networkAccessManager(), m_captcha, this);
    connect(m_passwordLogin, &PasswordLogin::tokenReceived, this, &Session::loginWithToken);
    connect(m_passwordLogin, &PasswordLogin::signedInNotice, this, &Session::showNotice);

    m_noticeTimer.setSingleShot(true);
    m_noticeTimer.setInterval(6000);
    connect(&m_noticeTimer, &QTimer::timeout, this, &Session::clearNotice);

    connect(qGuiApp, &QGuiApplication::applicationStateChanged, this, [this](Qt::ApplicationState state) {
        if (state == Qt::ApplicationActive)
            markCurrentChannelRead();
    });
}

Session::~Session()
{
    m_qrLogin->stop();
    destroyInstance();
    CoreGlobals::setFrontend(nullptr);
    CoreGlobals::setHttpClient(nullptr);
    CoreGlobals::setWebsocketClient(nullptr);
}

QString Session::configPath() const
{
    return QStandardPaths::writableLocation(QStandardPaths::AppDataLocation) + QStringLiteral("/settings.json");
}

bool Session::applicationActive() const
{
    return QGuiApplication::applicationState() == Qt::ApplicationActive;
}

QString Session::userAgent() const
{
    return QString::fromStdString(GetClientConfig()->GetUserAgent());
}

QNetworkAccessManager* Session::networkAccessManager() const
{
    return m_http->networkAccessManager();
}

void Session::setServerUrls(const QString& api, const QString& cdn)
{
    m_apiUrl = api;
    m_cdnUrl = cdn;
}

void Session::start()
{
    GetLocalSettings()->Load();
    if (!m_apiUrl.isEmpty())
        GetLocalSettings()->SetDiscordAPI(m_apiUrl.toStdString());
    if (!m_cdnUrl.isEmpty())
        GetLocalSettings()->SetDiscordCDN(m_cdnUrl.toStdString());
    // Coming from 0.8: its sign-in and settings.
    if (Migration::fromVersion08(m_preferences)) {
        m_updatedFromOldVersion = true;
        emit updatedFromOldVersionChanged();
    }

    const std::string token = GetLocalSettings()->GetToken();
    if (token.empty()) {
        setPhase(LoggedOut);
        return;
    }
    createInstance(token);
    loadCachedState();
    // With cached data the app opens as it does while reconnecting: the
    // connection banner instead of the splash screen.
    setPhase(m_cachedStart ? Ready : Connecting);
    m_connection->open();
}

void Session::loadCachedState()
{
    nlohmann::json ready, supplemental;
    if (!m_instance || !m_offline->loadReady(ready, supplemental))
        return;
    try {
        m_instance->LoadCachedReady(ready, supplemental.is_object() ? &supplemental : nullptr);
    } catch (const std::exception& e) {
        // Written by another version: start without it.
        qCWarning(lcCore, "offline cache: %s; clearing it", e.what());
        m_offline->clear();
        destroyInstance();
        createInstance(GetLocalSettings()->GetToken());
        return;
    }
    m_cachedStart = true;
    m_messages->setOwnUserId(m_instance->GetUserID());
    emit profileChanged();
    selectDirectMessages();
}

// State

void Session::setPhase(Phase phase)
{
    if (m_phase == phase)
        return;
    m_phase = phase;
    emit phaseChanged();
}

void Session::setErrorText(const QString& text)
{
    if (m_errorText == text)
        return;
    m_errorText = text;
    emit errorTextChanged();
}

void Session::showNotice(const QString& text)
{
    m_noticeText = text;
    emit noticeTextChanged();
    m_noticeTimer.start();
}

void Session::clearNotice()
{
    if (m_noticeText.isEmpty())
        return;
    m_noticeText.clear();
    emit noticeTextChanged();
}

void Session::setLoadingMessages(bool loading)
{
    if (m_loadingMessages == loading)
        return;
    m_loadingMessages = loading;
    emit loadingMessagesChanged();
}

void Session::setChatVisible(bool visible)
{
    if (m_chatVisible == visible)
        return;
    m_chatVisible = visible;
    emit chatVisibleChanged();
    if (visible) {
        ensureMessagesLoaded();
        markCurrentChannelRead();
    }
}

void Session::setAtNewest(bool atNewest)
{
    if (m_atNewest == atNewest)
        return;
    m_atNewest = atNewest;
    emit atNewestChanged();
    if (atNewest)
        markCurrentChannelRead();
}

void Session::setAutoSelectChannel(bool autoSelect)
{
    if (m_autoSelectChannel == autoSelect)
        return;
    m_autoSelectChannel = autoSelect;
    emit autoSelectChannelChanged();
}

bool Session::videoPlaybackAvailable() const
{
    return GstVideoPlayer::isAvailable();
}

// Signing in and out

void Session::createInstance(const std::string& token)
{
    m_instance = new DiscordInstance(token);
    CoreGlobals::setInstance(m_instance);
    m_openAfterReady.clear();
    m_fetchedChannels.clear();
    m_requestedMembers.clear();
    m_firstReadyPending = true;
    m_cachedStart = false;
}

void Session::destroyInstance()
{
    m_connection->close();
    m_http->StopAllRequests();
    m_call->gatewayLost();
    m_voiceStates->clear();
    if (m_instance) {
        m_instance->CloseGatewaySession();
        CoreGlobals::setInstance(nullptr);
        delete m_instance;
        m_instance = nullptr;
    }
    GetMessageCache()->ClearAllChannels();

    m_messages->setChannel(0, 0);
    m_channels->clear();
    m_guilds->clear();
    m_unreadDms->clear();
    m_fetchedChannels.clear();
    m_requestedMembers.clear();
    m_typing->clear();
    m_sender->clear();
    setLoadingMessages(false);
    emit currentGuildChanged();
    emit currentChannelChanged();
    m_permissions->update();
    updateCurrentCall();
    emit profileChanged();
}

void Session::loginWithToken(const QString& token)
{
    const std::string trimmed = token.trimmed().toStdString();
    if (trimmed.empty())
        return;

    m_qrLogin->stop();
    setErrorText(QString());
    m_newToken = true;
    destroyInstance();
    GetLocalSettings()->SetToken(trimmed);
    GetLocalSettings()->Save();
    // Another account's cache must not show up.
    m_offline->clear();
    createInstance(trimmed);
    setPhase(Connecting);
    m_connection->open();
}

void Session::logout()
{
    m_captcha->cancelAll();
    m_newToken = false;
    destroyInstance();
    m_offline->clear();
    // The pictures are this account's contacts and servers.
    QDir(QStandardPaths::writableLocation(QStandardPaths::CacheLocation) + QStringLiteral("/pictures")).removeRecursively();
    GetLocalSettings()->SetToken("");
    GetLocalSettings()->Save();
    setPhase(LoggedOut);
}

void Session::coreLoggedOut()
{
    // The token was rejected: one just entered, or the saved one.
    const bool newToken = m_newToken;
    logout();
    setErrorText(newToken ? tr("Discord didn't accept this token. Make sure you copied all of it, and that it's "
                               "still valid (signing out of Discord makes it invalid).")
                          : tr("Your session has expired. Please sign in again."));
}

void Session::coreConnected()
{
    // READY: everything fetched before may be stale. This runs before the
    // core handles READY, which selects its first server, so remember what
    // the cached state had open to go back to it.
    const bool restore = m_firstReadyPending && m_cachedStart && m_instance;
    const QString guild = restore && m_instance->GetCurrentGuildID() ? DiscordUrls::id(m_instance->GetCurrentGuildID()) : QString();
    const QString channel = restore && m_instance->GetCurrentChannelID() ? DiscordUrls::id(m_instance->GetCurrentChannelID()) : QString();
    m_cachedStart = false;
    m_newToken = false;
    m_fetchedChannels.clear();
    m_requestedMembers.clear();
    setErrorText(QString());
    m_connection->setConnected(true);
    setPhase(Ready);
    m_messages->setOwnUserId(m_instance ? m_instance->GetUserID() : 0);

    // After the core is done with READY.
    QTimer::singleShot(0, this, [this, restore, guild, channel]() {
        if (m_firstReadyPending) {
            m_firstReadyPending = false;
            if (restore && m_openAfterReady.isEmpty())
                restoreAfterReady(guild, channel);
            else
                restoreAfterReady(QString(), std::exchange(m_openAfterReady, QString()));
        }
        ensureMessagesLoaded();
    });
}

// The core opens the first server, as on a desktop; the app starts on
// direct messages, or on what was open or asked for.
void Session::restoreAfterReady(const QString& guild, const QString& channel)
{
    if (!channel.isEmpty())
        openChannel(channel);
    else if (!guild.isEmpty())
        selectGuild(guild);
    else
        selectDirectMessages();
}

// Profile and navigation

QString Session::userId() const
{
    return m_instance ? DiscordUrls::id(m_instance->GetUserID()) : QString();
}

QString Session::username() const
{
    Profile* profile = m_instance && m_instance->GetUserID() ? m_instance->GetProfile() : nullptr;
    if (!profile)
        return QString();
    return QString::fromStdString(!profile->m_globalName.empty() ? profile->m_globalName : profile->m_name);
}

QString Session::avatarUrl() const
{
    Profile* profile = m_instance && m_instance->GetUserID() ? m_instance->GetProfile() : nullptr;
    return profile ? DiscordUrls::userAvatar(profile->m_snowflake, profile->m_avatarlnk) : QString();
}

bool Session::inDirectMessages() const
{
    return !m_instance || m_instance->GetCurrentGuildID() == 0;
}

QString Session::currentGuildId() const
{
    return m_instance ? DiscordUrls::id(m_instance->GetCurrentGuildID()) : QString();
}

QString Session::currentGuildName() const
{
    if (inDirectMessages())
        return tr("Direct messages");
    Guild* guild = m_instance->GetCurrentGuild();
    return guild ? QString::fromStdString(guild->m_name) : QString();
}

QString Session::currentChannelId() const
{
    if (!m_instance || !m_instance->GetCurrentChannelID())
        return QString();
    return DiscordUrls::id(m_instance->GetCurrentChannelID());
}

QString Session::currentChannelName() const
{
    Channel* channel = m_instance ? m_instance->GetCurrentChannel() : nullptr;
    return channel ? ChannelListModel::displayName(*channel) : QString();
}

QString Session::currentChannelTopic() const
{
    Channel* channel = m_instance ? m_instance->GetCurrentChannel() : nullptr;
    return channel ? QString::fromStdString(channel->m_topic) : QString();
}

QVariantMap Session::channelInfo(const QString& channelId) const
{
    Channel* channel = m_instance ? m_instance->GetChannel(DiscordUrls::fromId(channelId)) : nullptr;
    if (!channel)
        return QVariantMap();
    // A 1:1 DM shows the other person's profile.
    if (channel->m_channelType == Channel::DM && !channel->m_recipients.empty())
        userInfo(DiscordUrls::id(channel->GetDMRecipient()));
    return describeChannel(*m_instance, *channel);
}

QVariantMap Session::userInfo(const QString& userId) const
{
    const Snowflake user = DiscordUrls::fromId(userId);
    if (!m_instance || !user)
        return QVariantMap();
    // Bio and pronouns: the full profile, fetched once (the page refreshes
    // on profileChanged).
    Profile* profile = GetProfileCache()->LookupProfile(user, "", "", "", false);
    if (profile && !profile->m_bExtraDataFetched)
        GetProfileCache()->RequestExtraData(user, 0, false, false);
    return describeUser(*m_instance, user);
}

QString Session::directMessageWith(const QString& userId) const
{
    const Snowflake user = DiscordUrls::fromId(userId);
    Guild* dms = m_instance ? m_instance->GetGuild(0) : nullptr;
    if (!dms || !user)
        return QString();
    for (const Channel& channel : dms->m_channels) {
        if (channel.m_channelType == Channel::DM && channel.GetDMRecipient() == user)
            return DiscordUrls::id(channel.m_snowflake);
    }
    return QString();
}

void Session::selectDirectMessages()
{
    if (!m_instance)
        return;
    m_instance->OnSelectGuild(0);
    afterGuildSelected();
}

void Session::selectGuild(const QString& guildId)
{
    if (!m_instance)
        return;
    m_instance->OnSelectGuild(DiscordUrls::fromId(guildId));
    afterGuildSelected();
}

void Session::afterGuildSelected()
{
    // The core opens the server's first channel; on a phone the channel
    // list shows instead.
    if (!m_autoSelectChannel && m_instance->GetCurrentChannelID())
        m_instance->OnSelectChannel(0);
}

void Session::openChannel(const QString& channelId)
{
    if (!m_instance)
        return;
    if (m_firstReadyPending && !m_cachedStart) {
        // The core is still setting up the session and would undo this.
        m_openAfterReady = channelId;
        return;
    }
    const Snowflake channel = DiscordUrls::fromId(channelId);
    const Snowflake guild = guildOfChannel(m_instance, channel);
    if (guild != m_instance->GetCurrentGuildID()) {
        m_instance->OnSelectGuild(guild, channel);
    } else if (channel != m_instance->GetCurrentChannelID()) {
        m_instance->OnSelectChannel(channel);
    } else if (Channel* current = m_instance->GetCurrentChannel(); current && current->HasUnreadMessages()) {
        // Back into the same channel (a phone's channel list), with new
        // messages since: opens at them like another channel would.
        startUnreadView();
        emit channelOpened();
    }

    ensureMessagesLoaded();
    markCurrentChannelRead();
}

// What was read before (never read: everything there now): the "Unread
// messages" bar goes after it. With unread messages the chat opens at the
// bar and only marks them read once scrolled down.
void Session::startUnreadView()
{
    const Channel* channel = m_instance ? m_instance->GetCurrentChannel() : nullptr;
    m_messages->setNewSince(!channel ? 0 : channel->m_lastViewedMsg ? channel->m_lastViewedMsg : channel->m_lastSentMsg);
    m_atNewest = !channel || !channel->HasUnreadMessages();
    emit atNewestChanged();
}

bool Session::openChannelLink(const QString& url)
{
    DiscordUrls::ChannelLink link;
    if (!m_instance || !DiscordUrls::parseChannelLink(url, link))
        return false;
    Channel* channel = m_instance->GetChannel(link.channel);
    if (!channel || (!channel->IsDM() && !channel->HasPermission(PERM_VIEW_CHANNEL))) {
        showNotice(tr("You don't have access to this channel."));
        return true;
    }
    openChannel(DiscordUrls::id(link.channel));
    if (link.message)
        emit messageRequested(DiscordUrls::id(link.message));
    return true;
}

void Session::coreSelectedGuildChanged()
{
    m_channels->reload();
    m_emoji->reloadServerEmoji();
    emit currentGuildChanged();
}

void Session::coreSelectedChannelChanged()
{
    if (!m_instance)
        return;
    m_instance->HandledChannelSwitch();
    m_messages->setChannel(m_instance->GetCurrentGuildID(), m_instance->GetCurrentChannelID());
    startUnreadView();
    m_typing->clear();
    emit currentChannelChanged();
    m_permissions->update();
    updateCurrentCall();
    ensureMessagesLoaded();
    emit channelOpened();
}

void Session::coreChannelListChanged()
{
    // Also after role, member and overwrite changes.
    m_channels->reload();
    refreshUnread();
    m_permissions->update();
}

void Session::coreChannelAcknowledged(Snowflake channel)
{
    m_channels->refreshChannel(channel);
    refreshUnread();
}

void Session::refreshUnread()
{
    m_guilds->refreshUnread();
    m_unreadDms->reload();
}

void Session::coreGuildListChanged()
{
    m_guilds->reload();
    m_unreadDms->reload();
    m_channels->reload();
    if (m_instance)
        m_messages->setOwnUserId(m_instance->GetUserID());
    emit currentGuildChanged();
    emit currentChannelChanged();
    m_permissions->update();
    updateCurrentCall();
    emit profileChanged();
}

void Session::coreProfileChanged()
{
    if (m_instance)
        m_messages->setOwnUserId(m_instance->GetUserID());
    emit profileChanged();
}

void Session::coreUserChanged()
{
    // Names, pictures and presence in the lists.
    m_channels->refreshAll();
    if (m_messages->channel())
        m_messages->sync();
}

void Session::coreMembersChanged()
{
    // Server nicknames: messages, replies, mentions, typing, voice channels.
    m_messages->refreshNames();
    m_typing->refresh();
    m_channels->refreshAll();
    emit membersChanged();
}

void Session::coreError(const QString& message)
{
    qCWarning(lcCore, "%s", qPrintable(message));
    if (m_loadingMessages) {
        setLoadingMessages(false);
        if (m_instance)
            m_fetchedChannels.remove(m_instance->GetCurrentChannelID());
    }
    // The core's errors can include the whole response.
    showNotice(message.section(QLatin1Char('\n'), 0, 0));
}

// Messages

void Session::ensureMessagesLoaded()
{
    if (!m_instance)
        return;
    const Snowflake channel = m_instance->GetCurrentChannelID();

    // Nothing loaded yet: show the offline cache's messages until the first
    // fetch replaces them.
    if (channel && !GetMessageCache()->HasMessages(channel)) {
        nlohmann::json cached = m_offline->messages(channel);
        if (!cached.empty()) {
            Channel* info = m_instance->GetChannel(channel);
            GetMessageCache()->LoadCachedMessages(channel, cached, info ? info->GetTypeSymbol() + info->m_name : std::string());
            m_messages->sync();
        }
    }

    if (!connected() || !m_chatVisible || !channel || m_fetchedChannels.contains(channel))
        return;
    // Without "Read Message History" Discord sends nothing.
    if (!m_permissions->canReadHistory())
        return;

    m_fetchedChannels.insert(channel);
    setLoadingMessages(true);
    // The core only clears its "initial load in progress" flag on a channel
    // switch; clear it so a failed load can be retried.
    m_instance->HandledChannelSwitch();
    m_instance->RequestMessages(channel, ScrollDir::BEFORE, 0, 0);
}

void Session::loadOlderMessages()
{
    if (!m_instance || m_loadingMessages || !m_permissions->canReadHistory())
        return;
    const MessagePtr gap = m_messages->olderGap();
    if (!gap)
        return;
    setLoadingMessages(true);
    // Allow retrying an anchor whose earlier request failed.
    m_instance->m_messageRequestsInProgress.erase(gap->m_anchor);
    m_instance->RequestMessages(m_messages->channel(), ScrollDir::BEFORE, gap->m_anchor, gap->m_snowflake);
}

void Session::coreMessagesRefreshed()
{
    setLoadingMessages(false);
    m_messages->sync();
    requestMissingMembers();
    markCurrentChannelRead();
}

void Session::markCurrentChannelRead()
{
    if (!m_instance || !connected() || !m_chatVisible || !applicationActive() || !m_atNewest)
        return;
    Channel* channel = m_instance->GetCurrentChannel();
    if (!channel || m_messages->channel() != channel->m_snowflake)
        return;
    Snowflake newest = m_messages->newestMessageId();
    // Once fetched, the newest messages are all here; the channel's last
    // message can still be newer when it was deleted, and would stay unread.
    if (m_fetchedChannels.contains(channel->m_snowflake) && !m_loadingMessages)
        newest = std::max(newest, channel->m_lastSentMsg);
    if (!newest)
        return;
    if (channel->m_lastViewedMsg >= newest && channel->m_mentionCount == 0)
        return;

    m_instance->RequestAcknowledgeMessages(channel->m_snowflake, newest);
    // Clear the unread marker now; the gateway confirms it later.
    channel->m_lastViewedMsg = newest;
    channel->m_mentionCount = 0;
    coreChannelAcknowledged(channel->m_snowflake);
}

void Session::coreMessageAdded(Snowflake channel, const Message& message)
{
    if (channel == m_messages->channel()) {
        // Arriving while the newest messages are on screen: seen, no
        // "Unread messages" bar above it (unless there is one already).
        if (m_atNewest && applicationActive() && m_chatVisible && !m_messages->hasNew())
            m_messages->setNewSince(message.m_snowflake);
        m_messages->sync();
        m_typing->userSent(message.m_author_snowflake);
        markCurrentChannelRead();
    }
    // Conversations are ordered by activity.
    if (inDirectMessages() && m_instance && m_instance->m_dmGuild.GetChannel(channel))
        m_channels->reload();
    else
        m_channels->refreshChannel(channel);
    refreshUnread();
}

void Session::coreMessageUpdated(Snowflake channel)
{
    if (channel == m_messages->channel())
        m_messages->sync();
}

void Session::coreMessageDeleted()
{
    if (m_messages->channel())
        m_messages->sync();
}

void Session::coreFailedToSend(Snowflake channel, Snowflake nonce)
{
    GetMessageCache()->DeleteMessage(channel, nonce);
    if (channel == m_messages->channel())
        m_messages->sync();
}

bool Session::editMessage(const QString& messageId, const QString& text)
{
    const QString content = text.trimmed();
    if (!m_instance || !connected() || content.isEmpty())
        return false;
    if (!m_instance->EditMessageInCurrentChannel(content.toStdString(), DiscordUrls::fromId(messageId))) {
        showNotice(tr("The message could not be edited."));
        return false;
    }
    return true;
}

void Session::deleteMessage(const QString& messageId)
{
    if (m_instance && connected() && m_messages->channel())
        m_instance->RequestDeleteMessage(m_messages->channel(), DiscordUrls::fromId(messageId));
}

void Session::addReaction(const QString& messageId, const QString& emoji)
{
    toggleReaction(messageId, emoji, false);
}

void Session::toggleReaction(const QString& messageId, const QString& emoji, bool reacted)
{
    if (!m_instance || !connected() || emoji.isEmpty() || !m_messages->channel() || !m_permissions->canUseReactions())
        return;
    const Snowflake message = DiscordUrls::fromId(messageId);
    if (reacted)
        m_instance->RequestRemoveReaction(m_messages->channel(), message, emoji.toStdString());
    else
        m_instance->RequestAddReaction(m_messages->channel(), message, emoji.toStdString());
}

void Session::votePoll(const QString& messageId, const QVariantList& answerIds)
{
    if (!m_instance || !connected() || !m_messages->channel())
        return;
    std::vector<int> ids;
    for (const QVariant& id : answerIds)
        ids.push_back(id.toInt());
    m_instance->RequestPollVote(m_messages->channel(), DiscordUrls::fromId(messageId), ids);
}

void Session::requestMissingMembers()
{
    const Snowflake guild = m_messages->guild();
    if (!m_instance || !connected() || !guild)
        return;
    // Discord takes up to 100 ids a request.
    constexpr size_t BatchSize = 100;
    std::set<Snowflake> batch;
    for (Snowflake user : m_messages->unknownMembers()) {
        const auto key = qMakePair(guild, user);
        if (m_requestedMembers.contains(key))
            continue;
        m_requestedMembers.insert(key);
        batch.insert(user);
        if (batch.size() == BatchSize) {
            m_instance->RequestGuildMembers(guild, batch);
            batch.clear();
        }
    }
    if (!batch.empty())
        m_instance->RequestGuildMembers(guild, batch);
}

// Calls in the open conversation

bool Session::currentChannelHasCall() const
{
    return m_instance && m_voiceStates->hasCall(m_instance->GetCurrentChannelID());
}

QString Session::currentCallElapsed() const
{
    const qint64 started = m_instance ? m_voiceStates->callStartedMs(m_instance->GetCurrentChannelID()) : 0;
    if (!started || !currentChannelHasCall())
        return QString();
    const qint64 seconds = qMax<qint64>(0, (QDateTime::currentMSecsSinceEpoch() - started) / 1000);
    const QString minutes = QStringLiteral("%1:%2").arg(seconds / 60 % 60, 2, 10, QLatin1Char('0'))
                                                   .arg(seconds % 60, 2, 10, QLatin1Char('0'));
    return seconds >= 3600 ? QStringLiteral("%1:%2").arg(seconds / 3600).arg(minutes) : minutes;
}

void Session::updateCurrentCall()
{
    if (currentChannelHasCall())
        m_callClock.start();
    else
        m_callClock.stop();
    emit currentCallChanged();
}
