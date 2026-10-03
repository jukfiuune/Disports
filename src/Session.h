#pragma once

#include <QObject>
#include <QSet>
#include <QString>
#include <QTimer>

#include <memory>

#include "discord/models/Snowflake.hpp"

// Complete types: moc needs them for the QObject* properties below.
#include "Captcha.h"
#include "ChannelPermissions.h"
#include "GatewayConnection.h"
#include "MentionSuggester.h"
#include "MessageSender.h"
#include "OfflineCache.h"
#include "PasswordLogin.h"
#include "Preferences.h"
#include "RemoteAuth.h"
#include "TypingIndicator.h"
#include "models/ChannelListModel.h"
#include "models/EmojiPickerModel.h"
#include "models/GuildListModel.h"
#include "models/MessageListModel.h"
#include "models/UnreadDmListModel.h"
#include "voice/CallManager.h"
#include "voice/VoiceStates.h"

class Channel;
class DiscordInstance;
class Message;
class QNetworkAccessManager;
class QtFrontend;
class QtHttpClient;
class QtWebsocketClient;

// The app's state for QML: signing in and out, the Discord client core
// (DiscordInstance) with its Qt transports, what is open, and the models
// and helpers for it. Everything runs on the main thread.
class Session : public QObject
{
    Q_OBJECT

    Q_PROPERTY(Phase phase READ phase NOTIFY phaseChanged)
    Q_PROPERTY(QString errorText READ errorText NOTIFY errorTextChanged)
    Q_PROPERTY(QString noticeText READ noticeText NOTIFY noticeTextChanged)

    Q_PROPERTY(QString userId READ userId NOTIFY profileChanged)
    Q_PROPERTY(QString username READ username NOTIFY profileChanged)
    Q_PROPERTY(QString avatarUrl READ avatarUrl NOTIFY profileChanged)

    Q_PROPERTY(bool inDirectMessages READ inDirectMessages NOTIFY currentGuildChanged)
    Q_PROPERTY(QString currentGuildId READ currentGuildId NOTIFY currentGuildChanged)
    Q_PROPERTY(QString currentGuildName READ currentGuildName NOTIFY currentGuildChanged)
    Q_PROPERTY(QString currentChannelId READ currentChannelId NOTIFY currentChannelChanged)
    Q_PROPERTY(QString currentChannelName READ currentChannelName NOTIFY currentChannelChanged)
    Q_PROPERTY(QString currentChannelTopic READ currentChannelTopic NOTIFY currentChannelChanged)
    // Someone's call in the open conversation, and for how long ("12:34").
    Q_PROPERTY(bool currentChannelHasCall READ currentChannelHasCall NOTIFY currentCallChanged)
    Q_PROPERTY(QString currentCallElapsed READ currentCallElapsed NOTIFY currentCallChanged)
    Q_PROPERTY(bool loadingMessages READ loadingMessages NOTIFY loadingMessagesChanged)

    // Set by the UI: a chat is on screen (fetch history, mark it read), and
    // whether picking a server also opens its first channel (wide layout)
    // or only shows its channel list (phone).
    Q_PROPERTY(bool chatVisible READ chatVisible WRITE setChatVisible NOTIFY chatVisibleChanged)
    Q_PROPERTY(bool autoSelectChannel READ autoSelectChannel WRITE setAutoSelectChannel NOTIFY autoSelectChannelChanged)
    // Set by the chat: it shows the newest messages, so they are seen and
    // the channel is marked read. False when a channel with unread messages
    // opens, until the chat has scrolled down to them.
    Q_PROPERTY(bool atNewest READ atNewest WRITE setAtNewest NOTIFY atNewestChanged)

    Q_PROPERTY(GatewayConnection* connection READ connection CONSTANT)
    Q_PROPERTY(ChannelPermissions* permissions READ permissions CONSTANT)
    Q_PROPERTY(MessageSender* sender READ sender CONSTANT)
    Q_PROPERTY(TypingIndicator* typing READ typing CONSTANT)
    Q_PROPERTY(MentionSuggester* mentions READ mentions CONSTANT)
    Q_PROPERTY(GuildListModel* guilds READ guilds CONSTANT)
    Q_PROPERTY(ChannelListModel* channels READ channels CONSTANT)
    Q_PROPERTY(MessageListModel* messages READ messages CONSTANT)
    Q_PROPERTY(UnreadDmListModel* unreadDirectMessages READ unreadDirectMessages CONSTANT)
    Q_PROPERTY(Preferences* preferences READ preferences CONSTANT)
    Q_PROPERTY(EmojiPickerModel* emoji READ emoji CONSTANT)
    Q_PROPERTY(RemoteAuth* qrLogin READ qrLogin CONSTANT)
    Q_PROPERTY(PasswordLogin* passwordLogin READ passwordLogin CONSTANT)
    // Captchas Discord wants solved (qml/CaptchaPage.qml).
    Q_PROPERTY(CaptchaPrompt* captcha READ captcha CONSTANT)
    // Updated from 0.8 just now: tell about the new version (qml/UpdateNotice.qml).
    Q_PROPERTY(bool updatedFromOldVersion READ updatedFromOldVersion NOTIFY updatedFromOldVersionChanged)
    Q_PROPERTY(CallManager* call READ call CONSTANT)

public:
    enum Phase {
        Starting,   // loading settings
        LoggedOut,  // show the login page
        Connecting, // signed in, waiting for the first READY
        Ready,      // READY received at least once
    };
    Q_ENUM(Phase)

    explicit Session(QObject* parent = nullptr);
    ~Session() override;

    // Another server than Discord's; before start().
    void setServerUrls(const QString& api, const QString& cdn);
    // Loads the saved settings and signs in if a token is stored.
    void start();

    Phase phase() const { return m_phase; }
    bool connected() const { return m_connection->connected(); }
    QString errorText() const { return m_errorText; }
    QString noticeText() const { return m_noticeText; }

    QString userId() const;
    QString username() const;
    QString avatarUrl() const;

    bool inDirectMessages() const;
    QString currentGuildId() const;
    QString currentGuildName() const;
    QString currentChannelId() const;
    QString currentChannelName() const;
    QString currentChannelTopic() const;
    bool currentChannelHasCall() const;
    QString currentCallElapsed() const;
    bool loadingMessages() const { return m_loadingMessages; }
    bool chatVisible() const { return m_chatVisible; }
    void setChatVisible(bool visible);
    bool autoSelectChannel() const { return m_autoSelectChannel; }
    void setAutoSelectChannel(bool autoSelect);
    bool atNewest() const { return m_atNewest; }
    void setAtNewest(bool atNewest);

    GatewayConnection* connection() const { return m_connection; }
    ChannelPermissions* permissions() const { return m_permissions; }
    MessageSender* sender() const { return m_sender; }
    TypingIndicator* typing() const { return m_typing; }
    MentionSuggester* mentions() const { return m_mentions; }
    GuildListModel* guilds() const { return m_guilds; }
    ChannelListModel* channels() const { return m_channels; }
    MessageListModel* messages() const { return m_messages; }
    UnreadDmListModel* unreadDirectMessages() const { return m_unreadDms; }
    Preferences* preferences() const { return m_preferences; }
    EmojiPickerModel* emoji() const { return m_emoji; }
    RemoteAuth* qrLogin() const { return m_qrLogin; }
    PasswordLogin* passwordLogin() const { return m_passwordLogin; }
    CaptchaPrompt* captcha() const { return m_captcha; }
    bool updatedFromOldVersion() const { return m_updatedFromOldVersion; }
    CallManager* call() const { return m_call; }
    OfflineCache* offlineCache() const { return m_offline; }
    VoiceStates* voiceStates() const { return m_voiceStates; }
    QNetworkAccessManager* networkAccessManager() const;
    // The browser Disports says it is, for the captcha page.
    Q_INVOKABLE QString userAgent() const;
    DiscordInstance* instance() const { return m_instance; }

    Q_INVOKABLE void loginWithToken(const QString& token);
    Q_INVOKABLE void logout();

    Q_INVOKABLE void selectDirectMessages();
    Q_INVOKABLE void selectGuild(const QString& guildId);
    Q_INVOKABLE void openChannel(const QString& channelId);
    // A discord.com/channels/... link (DiscordUrls::parseChannelLink):
    // opens the channel, and goes to the message if it names one, as the
    // official client does. False when it isn't one, for the browser.
    Q_INVOKABLE bool openChannelLink(const QString& url);
    Q_INVOKABLE void loadOlderMessages();
    Q_INVOKABLE void markCurrentChannelRead();
    // See describeChannel() in ChannelInfo.h.
    Q_INVOKABLE QVariantMap channelInfo(const QString& channelId) const;
    // See describeUser() in ChannelInfo.h; fetches the full profile once
    // (profileChanged follows).
    Q_INVOKABLE QVariantMap userInfo(const QString& userId) const;
    // Our 1:1 DM with someone, or "" when there is none yet.
    Q_INVOKABLE QString directMessageWith(const QString& userId) const;

    // Actions on messages of the open channel. Own messages only for
    // editing; false when it can't be done.
    Q_INVOKABLE bool editMessage(const QString& messageId, const QString& text);
    Q_INVOKABLE void deleteMessage(const QString& messageId);
    // `emoji` is a Unicode emoji or "name:id", as the emoji picker and a
    // message's reactions give it.
    Q_INVOKABLE void addReaction(const QString& messageId, const QString& emoji);
    Q_INVOKABLE void toggleReaction(const QString& messageId, const QString& emoji, bool reacted);
    // Replaces our votes on a poll; an empty list removes them.
    Q_INVOKABLE void votePoll(const QString& messageId, const QVariantList& answerIds);

    // A short message at the bottom of the screen, gone after a few seconds.
    Q_INVOKABLE void showNotice(const QString& text);
    Q_INVOKABLE void clearNotice();
    Q_INVOKABLE bool videoPlaybackAvailable() const;

    // From the core (through QtFrontend).
    void coreConnected();
    void coreLoggedOut();
    void coreMessageAdded(Snowflake channel, const Message& message);
    void coreMessageUpdated(Snowflake channel);
    void coreMessageDeleted();
    void coreFailedToSend(Snowflake channel, Snowflake nonce);
    void coreSelectedGuildChanged();
    void coreSelectedChannelChanged();
    void coreChannelListChanged();
    void coreChannelAcknowledged(Snowflake channel);
    void coreGuildListChanged();
    void coreProfileChanged();
    void coreUserChanged();
    void coreMessagesRefreshed();
    void coreMembersChanged();
    void coreError(const QString& message);

    QString configPath() const;
    bool applicationActive() const;

signals:
    void phaseChanged();
    void errorTextChanged();
    void updatedFromOldVersionChanged();
    void noticeTextChanged();
    void profileChanged();
    void currentGuildChanged();
    void currentChannelChanged();
    void currentCallChanged();
    void loadingMessagesChanged();
    void chatVisibleChanged();
    void autoSelectChannelChanged();
    void atNewestChanged();
    // Another channel was opened (currentChannelChanged also comes with
    // other changes). messages.firstNewIndex says where its new ones start.
    void channelOpened();
    // Show this message of the open channel (a link to it was opened).
    void messageRequested(const QString& messageId);
    void membersChanged();

private:
    void setPhase(Phase phase);
    void setErrorText(const QString& text);
    void setLoadingMessages(bool loading);

    void createInstance(const std::string& token);
    void destroyInstance();
    // Shows the offline cache while connecting; see OfflineCache.
    void loadCachedState();
    void restoreAfterReady(const QString& guild, const QString& channel);
    void ensureMessagesLoaded();
    void afterGuildSelected();
    void refreshUnread();
    void updateCurrentCall();
    // Asks Discord for the server members behind the messages shown whose
    // nicknames aren't known (history carries no member objects).
    void requestMissingMembers();

    Phase m_phase = Starting;
    QString m_apiUrl;
    QString m_cdnUrl;
    QString m_errorText;
    QString m_noticeText;
    QTimer m_noticeTimer;
    bool m_loadingMessages = false;
    bool m_chatVisible = false;
    bool m_autoSelectChannel = false;
    bool m_atNewest = true;
    // Until the core has set up the first READY; see coreConnected().
    bool m_firstReadyPending = false;
    // Showing the offline cache's state until the real READY arrives.
    bool m_cachedStart = false;
    QString m_openAfterReady; // asked for before the first READY was handled
    QSet<Snowflake> m_fetchedChannels; // history requested since READY
    QSet<QPair<Snowflake, Snowflake>> m_requestedMembers; // (server, user) since READY

    QtHttpClient* m_http = nullptr;
    QtWebsocketClient* m_sockets = nullptr;
    std::unique_ptr<QtFrontend> m_frontend;
    DiscordInstance* m_instance = nullptr;

    GatewayConnection* m_connection = nullptr;
    ChannelPermissions* m_permissions = nullptr;
    MessageSender* m_sender = nullptr;
    TypingIndicator* m_typing = nullptr;
    MentionSuggester* m_mentions = nullptr;
    GuildListModel* m_guilds = nullptr;
    ChannelListModel* m_channels = nullptr;
    MessageListModel* m_messages = nullptr;
    UnreadDmListModel* m_unreadDms = nullptr;
    Preferences* m_preferences = nullptr;
    EmojiPickerModel* m_emoji = nullptr;
    OfflineCache* m_offline = nullptr;
    RemoteAuth* m_qrLogin = nullptr;
    PasswordLogin* m_passwordLogin = nullptr;
    CaptchaPrompt* m_captcha = nullptr;
    // A token entered just now, not yet accepted by Discord.
    bool m_newToken = false;
    bool m_updatedFromOldVersion = false;
    CallManager* m_call = nullptr;
    VoiceStates* m_voiceStates = nullptr;
    QTimer m_callClock; // ticks currentCallElapsed
};
