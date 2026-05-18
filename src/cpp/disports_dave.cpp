#include "disports_dave.h"
#include <dave/dave_interfaces.h>
#include <dave/logger.h>
#include <string>
#include <unordered_map>
#include <set>
#include <vector>
#include <memory>
#include <iostream>
#include <mutex>
#include <optional>

using namespace discord::dave;

class DisportsDaveSession {
public:
    DisportsDaveSession(uint64_t channel_id, uint64_t user_id)
        : m_channel_id(channel_id), m_user_id(user_id) {
        
        static std::once_flag log_sink_once;
        std::call_once(log_sink_once, [] {
            discord::dave::SetLogSink([](discord::dave::LoggingSeverity severity,
                                         const char* file, int line,
                                         const std::string& message) {
                std::cout << "[DAVE_CPP] " << file << ":" << line << " " << message << std::endl;
            });
        });

        m_mls_session = mls::CreateSession(nullptr, "", [this](const std::string& reason, const std::string& detail) {
            std::cout << "[DAVE_CPP] MLS failure: " << reason << " " << detail << std::endl;
        });
    }

    ~DisportsDaveSession() = default;

    void set_callbacks(disports_dave_send_binary_cb bin_cb, disports_dave_send_json_cb json_cb, void* user_data) {
        std::lock_guard<std::mutex> lock(m_mutex);
        m_bin_cb = bin_cb;
        m_json_cb = json_cb;
        m_user_data = user_data;
    }

    void init(uint16_t version) {
        disports_dave_send_binary_cb bin_cb = nullptr;
        void* user_data = nullptr;
        std::vector<uint8_t> key_package;
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            m_protocol_version = version;
            m_pending_protocol_version = version;
            key_package = reinit();
            bin_cb = m_bin_cb;
            user_data = m_user_data;
        }
        if (!key_package.empty() && bin_cb) {
            bin_cb(26, key_package.data(), key_package.size(), user_data);
        }
    }

    void reset() {
        std::lock_guard<std::mutex> lock(m_mutex);
        m_mls_session->Reset();
        m_enabled = false;
        m_decryptors.clear();
        m_encryptor.reset();
    }

    void set_local_ssrc(uint32_t ssrc) {
        std::lock_guard<std::mutex> lock(m_mutex);
        m_local_ssrc = ssrc;
        if (m_encryptor) {
            m_encryptor->AssignSsrcToCodec(m_local_ssrc, Codec::Opus);
        }
    }

    void update_roster(uint32_t* ssrcs, uint64_t* user_ids, int count) {
        std::lock_guard<std::mutex> lock(m_mutex);
        std::unordered_map<uint32_t, uint64_t> new_ssrc_user_map;
        m_connected_users.insert(std::to_string(m_user_id));
        for (int i = 0; i < count; i++) {
            new_ssrc_user_map[ssrcs[i]] = user_ids[i];
            m_connected_users.insert(std::to_string(user_ids[i]));
        }

        for (auto it = m_decryptors.begin(); it != m_decryptors.end();) {
            auto mapped = new_ssrc_user_map.find(it->first);
            auto old = m_ssrc_user_map.find(it->first);
            if (mapped == new_ssrc_user_map.end() ||
                old == m_ssrc_user_map.end() ||
                old->second != mapped->second) {
                it = m_decryptors.erase(it);
            } else {
                ++it;
            }
        }

        m_ssrc_user_map = std::move(new_ssrc_user_map);
        if (m_enabled) {
            for (const auto& [ssrc, uid] : m_ssrc_user_map) {
                if (m_decryptors.find(ssrc) == m_decryptors.end()) {
                    refresh_decryptor_for_ssrc(ssrc, uid);
                }
            }
        }
    }

    void add_connected_user(uint64_t user_id) {
        std::lock_guard<std::mutex> lock(m_mutex);
        m_connected_users.insert(std::to_string(user_id));
    }

    void process_proposals(const uint8_t* data, size_t size) {
        disports_dave_send_binary_cb bin_cb = nullptr;
        void* user_data = nullptr;
        std::optional<std::vector<uint8_t>> response;
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            std::vector<uint8_t> payload(data, data + size);
            response = m_mls_session->ProcessProposals(std::move(payload), m_connected_users);
            bin_cb = m_bin_cb;
            user_data = m_user_data;
        }
        if (response && bin_cb) {
            bin_cb(28, response->data(), response->size(), user_data);
        }
    }

    void process_commit(int transition_id, const uint8_t* data, size_t size) {
        disports_dave_send_json_cb json_cb = nullptr;
        void* user_data = nullptr;
        int response_opcode = 0;
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            m_pending_transition_id = transition_id;
            std::vector<uint8_t> payload(data, data + size);
            auto result = m_mls_session->ProcessCommit(std::move(payload));

            if (auto* roster = std::get_if<RosterMap>(&result)) {
                m_pending_transition_ready = true;
                response_opcode = 23;
                if (transition_id == 0) complete_transition();
            } else if (std::holds_alternative<failed_t>(result)) {
                response_opcode = 31;
            }
            json_cb = m_json_cb;
            user_data = m_user_data;
        }
        if (response_opcode && json_cb) {
            json_cb(response_opcode, transition_id, response_opcode == 23, user_data);
        }
    }

    void process_welcome(int transition_id, const uint8_t* data, size_t size) {
        disports_dave_send_json_cb json_cb = nullptr;
        void* user_data = nullptr;
        int response_opcode = 31;
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            m_pending_transition_id = transition_id;
            std::vector<uint8_t> payload(data, data + size);
            auto roster = m_mls_session->ProcessWelcome(std::move(payload), m_connected_users);

            if (roster) {
                m_pending_transition_ready = true;
                response_opcode = 23;
                if (transition_id == 0) complete_transition();
            }
            json_cb = m_json_cb;
            user_data = m_user_data;
        }
        if (json_cb) {
            json_cb(response_opcode, transition_id, response_opcode == 23, user_data);
        }
    }

    void set_external_sender(const uint8_t* data, size_t size) {
        std::lock_guard<std::mutex> lock(m_mutex);
        std::vector<uint8_t> payload(data, data + size);
        m_mls_session->SetExternalSender(payload);
    }

    void execute_transition(int transition_id) {
        disports_dave_send_binary_cb bin_cb = nullptr;
        void* user_data = nullptr;
        std::vector<uint8_t> key_package;
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            if (m_pending_protocol_version != m_protocol_version) {
                m_protocol_version = m_pending_protocol_version;
                if (m_protocol_version == 0) {
                    m_enabled = false;
                    return;
                }
            }
            if (!m_pending_transition_ready) {
                key_package = reinit();
                bin_cb = m_bin_cb;
                user_data = m_user_data;
            } else {
                complete_transition();
            }
        }
        if (!key_package.empty() && bin_cb) {
            bin_cb(26, key_package.data(), key_package.size(), user_data);
        }
    }

    void prepare_epoch(int epoch) {
        disports_dave_send_binary_cb bin_cb = nullptr;
        void* user_data = nullptr;
        std::vector<uint8_t> key_package;
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            if (epoch == 1) {
                key_package = reinit();
                bin_cb = m_bin_cb;
                user_data = m_user_data;
            }
        }
        if (!key_package.empty() && bin_cb) {
            bin_cb(26, key_package.data(), key_package.size(), user_data);
        }
    }

    void prepare_transition(int transition_id, int protocol_version) {
        disports_dave_send_json_cb json_cb = nullptr;
        void* user_data = nullptr;
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            m_pending_transition_id = transition_id;
            m_pending_protocol_version = protocol_version;
            json_cb = m_json_cb;
            user_data = m_user_data;
        }
        if (json_cb) {
            json_cb(23, transition_id, true, user_data);
        }
    }

    size_t encrypt(uint32_t ssrc, const uint8_t* opus_frame, size_t opus_size, uint8_t* out, size_t out_size) {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (!m_enabled || !m_encryptor) return 0;
        size_t written = 0;
        auto result = m_encryptor->Encrypt(MediaType::Audio, ssrc, MakeArrayView(opus_frame, opus_size), MakeArrayView(out, out_size), &written);
        if (result == 0) return written;
        return 0;
    }

    size_t decrypt(uint32_t ssrc, const uint8_t* enc_frame, size_t enc_size, uint8_t* out, size_t out_size) {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (!m_enabled) return 0;
        auto it = m_decryptors.find(ssrc);
        if (it == m_decryptors.end()) {
            auto uid_it = m_ssrc_user_map.find(ssrc);
            if (uid_it == m_ssrc_user_map.end()) return 0;
            refresh_decryptor_for_ssrc(ssrc, uid_it->second);
            it = m_decryptors.find(ssrc);
            if (it == m_decryptors.end()) return 0;
        }
        size_t written = 0;
        auto result = it->second->Decrypt(MediaType::Audio, MakeArrayView(enc_frame, enc_size), MakeArrayView(out, out_size), &written);
        if (result == 0) return written;
        return 0;
    }

    size_t max_ciphertext_size(size_t frame_size) {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (!m_encryptor) return frame_size + 64;
        return m_encryptor->GetMaxCiphertextByteSize(MediaType::Audio, frame_size);
    }

    size_t max_plaintext_size(uint32_t ssrc, size_t frame_size) {
        std::lock_guard<std::mutex> lock(m_mutex);
        auto it = m_decryptors.find(ssrc);
        if (it == m_decryptors.end()) return frame_size;
        return it->second->GetMaxPlaintextByteSize(MediaType::Audio, frame_size);
    }

    bool is_ready() const {
        std::lock_guard<std::mutex> lock(m_mutex);
        return m_enabled;
    }

private:
    std::vector<uint8_t> reinit() {
        m_enabled = false;
        auto self_id = std::to_string(m_user_id);
        m_connected_users.insert(self_id);
        m_mls_session->Init(m_protocol_version, m_channel_id, self_id, m_transient_key);
        m_decryptors.clear();
        m_pending_transition_ready = false;
        m_encryptor = discord::dave::CreateEncryptor();
        if (m_local_ssrc != 0) {
            m_encryptor->AssignSsrcToCodec(m_local_ssrc, Codec::Opus);
        }

        return m_mls_session->GetMarshalledKeyPackage();
    }

    void complete_transition() {
        if (!m_pending_transition_ready) return;
        m_pending_transition_ready = false;

        auto selfRatchet = m_mls_session->GetKeyRatchet(std::to_string(m_user_id));
        if (selfRatchet) {
            m_encryptor->SetKeyRatchet(std::move(selfRatchet));
        }

        for (const auto& [ssrc, uid] : m_ssrc_user_map) {
            refresh_decryptor_for_ssrc(ssrc, uid);
        }

        m_enabled = true;
        m_pending_transition_id = -1;
    }

    void refresh_decryptor_for_ssrc(uint32_t ssrc, uint64_t uid) {
        if (uid == m_user_id || !m_mls_session) return;
        auto ratchet = m_mls_session->GetKeyRatchet(std::to_string(uid));
        if (!ratchet) return;
        if (m_decryptors.find(ssrc) == m_decryptors.end()) {
            m_decryptors[ssrc] = CreateDecryptor();
        }
        m_decryptors[ssrc]->TransitionToKeyRatchet(std::move(ratchet));
    }

    uint64_t m_channel_id;
    uint64_t m_user_id;
    uint16_t m_protocol_version = 0;
    uint16_t m_pending_protocol_version = 0;
    int m_pending_transition_id = -1;
    uint32_t m_local_ssrc = 0;
    bool m_enabled = false;
    bool m_pending_transition_ready = false;

    std::unordered_map<uint32_t, uint64_t> m_ssrc_user_map;
    std::set<std::string> m_connected_users;

    std::unique_ptr<discord::dave::mls::ISession> m_mls_session;
    std::unique_ptr<discord::dave::IEncryptor> m_encryptor;
    std::unordered_map<uint32_t, std::unique_ptr<discord::dave::IDecryptor>> m_decryptors;
    std::shared_ptr<::mlspp::SignaturePrivateKey> m_transient_key;

    disports_dave_send_binary_cb m_bin_cb = nullptr;
    disports_dave_send_json_cb m_json_cb = nullptr;
    void* m_user_data = nullptr;
    mutable std::mutex m_mutex;
};

// C API bindings
void* disports_dave_create(uint64_t channel_id, uint64_t user_id) {
    return new DisportsDaveSession(channel_id, user_id);
}
void disports_dave_destroy(void* session) {
    delete static_cast<DisportsDaveSession*>(session);
}
void disports_dave_init(void* session, uint16_t protocol_version) {
    static_cast<DisportsDaveSession*>(session)->init(protocol_version);
}
void disports_dave_reset(void* session) {
    static_cast<DisportsDaveSession*>(session)->reset();
}
void disports_dave_set_local_ssrc(void* session, uint32_t ssrc) {
    static_cast<DisportsDaveSession*>(session)->set_local_ssrc(ssrc);
}
void disports_dave_update_roster(void* session, uint32_t* ssrcs, uint64_t* user_ids, int count) {
    static_cast<DisportsDaveSession*>(session)->update_roster(ssrcs, user_ids, count);
}
void disports_dave_add_connected_user(void* session, uint64_t user_id) {
    static_cast<DisportsDaveSession*>(session)->add_connected_user(user_id);
}
void disports_dave_set_callbacks(void* session, disports_dave_send_binary_cb bin_cb, disports_dave_send_json_cb json_cb, void* user_data) {
    static_cast<DisportsDaveSession*>(session)->set_callbacks(bin_cb, json_cb, user_data);
}
void disports_dave_process_welcome(void* session, int transition_id, const uint8_t* data, size_t size) {
    static_cast<DisportsDaveSession*>(session)->process_welcome(transition_id, data, size);
}
void disports_dave_process_commit(void* session, int transition_id, const uint8_t* data, size_t size) {
    static_cast<DisportsDaveSession*>(session)->process_commit(transition_id, data, size);
}
void disports_dave_process_proposals(void* session, const uint8_t* data, size_t size) {
    static_cast<DisportsDaveSession*>(session)->process_proposals(data, size);
}
void disports_dave_set_external_sender(void* session, const uint8_t* data, size_t size) {
    static_cast<DisportsDaveSession*>(session)->set_external_sender(data, size);
}
void disports_dave_execute_transition(void* session, int transition_id) {
    static_cast<DisportsDaveSession*>(session)->execute_transition(transition_id);
}
void disports_dave_prepare_epoch(void* session, int epoch) {
    static_cast<DisportsDaveSession*>(session)->prepare_epoch(epoch);
}
void disports_dave_prepare_transition(void* session, int transition_id, int protocol_version) {
    static_cast<DisportsDaveSession*>(session)->prepare_transition(transition_id, protocol_version);
}
size_t disports_dave_encrypt(void* session, uint32_t ssrc, const uint8_t* opus_frame, size_t opus_size, uint8_t* out, size_t out_size) {
    return static_cast<DisportsDaveSession*>(session)->encrypt(ssrc, opus_frame, opus_size, out, out_size);
}
size_t disports_dave_decrypt(void* session, uint32_t ssrc, const uint8_t* enc_frame, size_t enc_size, uint8_t* out, size_t out_size) {
    return static_cast<DisportsDaveSession*>(session)->decrypt(ssrc, enc_frame, enc_size, out, out_size);
}
size_t disports_dave_get_max_ciphertext_size(void* session, size_t frame_size) {
    return static_cast<DisportsDaveSession*>(session)->max_ciphertext_size(frame_size);
}
size_t disports_dave_get_max_plaintext_size(void* session, uint32_t ssrc, size_t frame_size) {
    return static_cast<DisportsDaveSession*>(session)->max_plaintext_size(ssrc, frame_size);
}
bool disports_dave_is_ready(void* session) {
    return static_cast<DisportsDaveSession*>(session)->is_ready();
}
