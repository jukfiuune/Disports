#pragma once
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

// Creates a new DAVE session
void* disports_dave_create(uint64_t channel_id, uint64_t user_id);
void  disports_dave_destroy(void* session);

void disports_dave_init(void* session, uint16_t protocol_version);
void disports_dave_reset(void* session);
void disports_dave_set_local_ssrc(void* session, uint32_t ssrc);

// Updates the map of SSRC to user IDs.
void disports_dave_update_roster(void* session, uint32_t* ssrcs, uint64_t* user_ids, int count);
void disports_dave_add_connected_user(void* session, uint64_t user_id);

// Callbacks for network sending
typedef void (*disports_dave_send_binary_cb)(int opcode, const uint8_t* data, size_t size, void* user_data);
typedef void (*disports_dave_send_json_cb)(int opcode, int transition_id, bool ok, void* user_data);
void disports_dave_set_callbacks(void* session, disports_dave_send_binary_cb bin_cb, disports_dave_send_json_cb json_cb, void* user_data);

// Network event handlers
void disports_dave_process_welcome(void* session, int transition_id, const uint8_t* data, size_t size);
void disports_dave_process_commit(void* session, int transition_id, const uint8_t* data, size_t size);
void disports_dave_process_proposals(void* session, const uint8_t* data, size_t size);
void disports_dave_set_external_sender(void* session, const uint8_t* data, size_t size);

void disports_dave_execute_transition(void* session, int transition_id);
void disports_dave_prepare_epoch(void* session, int epoch);
void disports_dave_prepare_transition(void* session, int transition_id, int protocol_version);

// Audio Processing
size_t disports_dave_encrypt(void* session, uint32_t ssrc, const uint8_t* opus_frame, size_t opus_size, uint8_t* out, size_t out_size);
size_t disports_dave_decrypt(void* session, uint32_t ssrc, const uint8_t* encrypted_frame, size_t enc_size, uint8_t* out, size_t out_size);

size_t disports_dave_get_max_ciphertext_size(void* session, size_t frame_size);
size_t disports_dave_get_max_plaintext_size(void* session, uint32_t ssrc, size_t frame_size);

bool disports_dave_is_ready(void* session);

#ifdef __cplusplus
}
#endif
