// lucifer/data.cpp — jembatan data: HTTP JSON <-> widget.
//
// Semua fungsi di sini hanya membaca /api/* lalu mengisi model GTK.
// Tak ada logika Growtopia di sisi C++.

#include "ui.h"

#include <unistd.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <string>

namespace lucifer {

// ------------------------------------------------------------ bantuan ---
namespace {

JsonNode *parse(const std::string &teks) {
    JsonParser *p = json_parser_new();
    if (!json_parser_load_from_data(p, teks.c_str(), static_cast<gssize>(teks.size()), nullptr)) {
        g_object_unref(p);
        return nullptr;
    }
    JsonNode *n = json_node_copy(json_parser_get_root(p));
    g_object_unref(p);
    return n;
}

void kosongkan(GtkListStore *s) { gtk_list_store_clear(s); }

void baris(GtkListStore *s, const std::vector<std::string> &v) {
    GtkTreeIter it;
    gtk_list_store_append(s, &it);
    for (size_t i = 0; i < v.size(); ++i) {
        gtk_list_store_set(s, &it, static_cast<int>(i), v[i].c_str(), -1);
    }
}

std::string pilih_teks(GtkWidget *view, int kolom) {
    GtkTreeSelection *sel = gtk_tree_view_get_selection(GTK_TREE_VIEW(view));
    GtkTreeModel *model = nullptr;
    GtkTreeIter it;
    if (!gtk_tree_selection_get_selected(sel, &model, &it)) return "";
    gchar *t = nullptr;
    gtk_tree_model_get(model, &it, kolom, &t, -1);
    std::string out = t ? t : "";
    g_free(t);
    return out;
}

std::string isi_entry(GtkWidget *e) {
    return gtk_entry_get_text(GTK_ENTRY(e)) ? gtk_entry_get_text(GTK_ENTRY(e)) : "";
}

// Isi combo dengan daftar label; kembalikan label yang sedang aktif.
void isi_combo(GtkWidget *combo, const std::vector<std::string> &label) {
    gtk_combo_box_text_remove_all(GTK_COMBO_BOX_TEXT(combo));
    for (const auto &s : label) gtk_combo_box_text_append_text(GTK_COMBO_BOX_TEXT(combo), s.c_str());
    if (!label.empty()) gtk_combo_box_set_active(GTK_COMBO_BOX(combo), 0);
}

std::string combo_aktif(GtkWidget *combo) {
    gchar *t = gtk_combo_box_text_get_active_text(GTK_COMBO_BOX_TEXT(combo));
    std::string out = t ? t : "";
    g_free(t);
    return out;
}

// Isi kotak teks multi-baris.
void isi_textview(GtkWidget *tv, const std::string &teks) {
    GtkTextBuffer *b = gtk_text_view_get_buffer(GTK_TEXT_VIEW(tv));
    gtk_text_buffer_set_text(b, teks.c_str(), static_cast<gint>(teks.size()));
}

std::string baca_textview(GtkWidget *tv) {
    GtkTextBuffer *b = gtk_text_view_get_buffer(GTK_TEXT_VIEW(tv));
    GtkTextIter a, z;
    gtk_text_buffer_get_bounds(b, &a, &z);
    gchar *t = gtk_text_buffer_get_text(b, &a, &z, FALSE);
    std::string out = t ? t : "";
    g_free(t);
    return out;
}

}  // namespace

// -------------------------------------------------------------- akses ---
JsonObject *App::get_obj(const std::string &path) {
    Resp r = http_.get(path);
    if (!r.ok()) return nullptr;
    JsonNode *n = parse(r.body);
    if (!n) return nullptr;
    JsonObject *o = jobj(n);
    if (o) json_object_ref(o);
    json_node_unref(n);
    return o;
}

bool App::post_ok(const std::string &path, const std::string &json, std::string *err) {
    Resp r = http_.post(path, json);
    if (!r.ok()) {
        if (err) *err = "HTTP " + std::to_string(r.status);
        return false;
    }
    JsonNode *n = parse(r.body);
    bool ok = true;
    std::string msg;
    if (n) {
        JsonObject *o = jobj(n);
        if (o) {
            ok = !json_object_has_member(o, "ok") || jbool(o, "ok");
            msg = jstr(o, "error");
        }
        json_node_unref(n);
    }
    if (!ok && err) *err = msg.empty() ? "ditolak server" : msg;
    return ok;
}

// -------------------------------------------------------------- refresh ---
void App::refresh() {
    refresh_bots();
    refresh_proxies();
    refresh_switch();
    refresh_console();
    refresh_scripts();
}

void App::refresh_bots() {
    std::string filter = search_bots_ ? isi_entry(search_bots_) : "";
    JsonObject *o = get_obj("/api/status");
    if (!o) {
        if (header_status_) gtk_label_set_text(GTK_LABEL(header_status_), "●  offline");
        return;
    }

    // snapshot(): {bots:[...], accounts, items_loaded, uptime}
    std::vector<std::string> combo;
    kosongkan(store_bots_);

    long total = 0;
    long gems = 0;
    online_ = 0;
    if (json_object_has_member(o, "bots")) {
        JsonArray *arr = json_object_get_array_member(o, "bots");
        if (arr) {
            guint n = json_array_get_length(arr);
            for (guint i = 0; i < n; ++i) {
                JsonObject *b = jobj(json_array_get_element(arr, i));
                if (!b) continue;
                ++total;
                gems += jint(b, "gems");
                std::string label = jstr(b, "label");
                std::string nama = jstr(b, "name");
                std::string status = jstr(b, "status");
                if (status == "online") {
                    ++online_;
                    status = "Online";
                } else if (status == "connecting") {
                    status = "Connecting";
                } else if (status == "offline") {
                    status = "Offline";
                } else if (status.empty()) {
                    status = "Offline";
                } else {
                    // ganti '_' jadi spasi, kapital di awal
                    for (auto &c : status)
                        if (c == '_') c = ' ';
                    status[0] = static_cast<char>(g_ascii_toupper(status[0]));
                }

                if (!filter.empty()) {
                    gchar *l = g_utf8_strdown(label.c_str(), -1);
                    gchar *f = g_utf8_strdown(filter.c_str(), -1);
                    bool cocok = std::strstr(l, f) != nullptr;
                    g_free(l);
                    g_free(f);
                    if (!cocok) continue;
                }
                combo.push_back(label);
                std::string pos = jstr(b, "world_size");
                baris(store_bots_, {
                    label, nama,
                    jint(b, "level") ? std::to_string(jint(b, "level")) : "-",
                    jint(b, "ping") ? std::to_string(jint(b, "ping")) + " ms" : "-",
                    status,
                    jstr(b, "proxy").empty() ? "—" : jstr(b, "proxy"),
                    jstr(b, "world").empty() ? "—" : jstr(b, "world"),
                    pos.empty() ? "—" : pos,
                    std::to_string(jint(b, "gems")),
                });
            }
        }
    }

    if (combo_console_bot_) isi_combo(combo_console_bot_, combo);
    if (combo_proxy_bot_) isi_combo(combo_proxy_bot_, combo);

    char buf[256];
    std::snprintf(buf, sizeof buf, "Online %ld   ·   Offline %ld   ·   Total %ld   ·   Gems %ld",
                  online_, total > online_ ? total - online_ : 0, total, gems);
    if (bots_bar_) gtk_label_set_text(GTK_LABEL(bots_bar_), buf);

    if (header_status_) {
        gtk_label_set_text(GTK_LABEL(header_status_),
                           online_ > 0 ? "●  online" : "●  offline");
    }
    if (header_sub_) {
        std::snprintf(buf, sizeof buf, "%ld bot", total);
        gtk_label_set_text(GTK_LABEL(header_sub_), buf);
    }
    if (set_uptime_) {
        std::snprintf(buf, sizeof buf, "%ld dtk", jint(o, "uptime"));
        gtk_label_set_text(GTK_LABEL(set_uptime_), buf);
    }
    if (set_accounts_) {
        std::snprintf(buf, sizeof buf, "%ld", total);
        gtk_label_set_text(GTK_LABEL(set_accounts_), buf);
    }
    json_object_unref(o);
}

void App::refresh_proxies() {
    if (!store_proxies_) return;
    kosongkan(store_proxies_);
    JsonObject *o = get_obj("/api/proxies");
    if (!o) return;
    int total = 0, hidup = 0;
    if (json_object_has_member(o, "proxies")) {
        JsonArray *arr = json_object_get_array_member(o, "proxies");
        guint n = arr ? json_array_get_length(arr) : 0;
        for (guint i = 0; i < n; ++i) {
            JsonObject *p = jobj(json_array_get_element(arr, i));
            if (!p) continue;
            ++total;
            bool ok = jbool(p, "ok");
            bool pernah = jint(p, "checked") > 0;
            std::string status = jstr(p, "error");
            if (status.empty()) status = pernah ? (ok ? "Hidup" : "Mati") : "Belum diuji";
            if (ok) ++hidup;
            baris(store_proxies_, {
                jstr(p, "host"),
                std::to_string(jint(p, "port")),
                jstr(p, "user"),
                status,
                jint(p, "ms") ? std::to_string(jint(p, "ms")) + " ms" : "—",
            });
        }
    }
    if (proxy_note_) {
        char buf[160];
        std::snprintf(buf, sizeof buf, "Total proxy: %d   ·   %d hidup", total, hidup);
        gtk_label_set_text(GTK_LABEL(proxy_note_), buf);
    }
    if (proxy_kosong_) gtk_widget_set_visible(proxy_kosong_, total == 0);
    json_object_unref(o);
}

void App::refresh_switch() {
    if (!switch_note_) return;
    JsonObject *o = get_obj("/api/switch");
    if (!o) {
        gtk_label_set_text(GTK_LABEL(switch_note_), "backend belum siap");
        return;
    }
    struct Pasangan { GtkWidget *sw; const char *kunci; };
    Pasangan daftar[] = {
        {sw_autofarm_, "autofarm"}, {sw_collect_, "autocollect"},
        {sw_spam_, "spammer"},      {sw_drop_, "autodrop"},
        {sw_path_, "pathfinder"},   {sw_replay_, "replay"},
    };
    JsonObject *saklar = json_object_has_member(o, "switch")
                             ? jobj(json_object_get_member(o, "switch"))
                             : nullptr;
    switch_sync_ = true;
    int aktif = 0;
    for (auto &p : daftar) {
        if (!p.sw) continue;
        bool nyala = saklar && jbool(saklar, p.kunci);
        if (nyala) ++aktif;
        gtk_switch_set_active(GTK_SWITCH(p.sw), nyala);
    }
    switch_sync_ = false;
    char buf[160];
    std::snprintf(buf, sizeof buf, "%d fitur aktif · sasaran: %s", aktif,
                  jstr(o, "label").empty() ? "belum pilih bot" : jstr(o, "label").c_str());
    gtk_label_set_text(GTK_LABEL(switch_note_), buf);
    json_object_unref(o);
}

void App::refresh_console() {
    if (!view_console_) return;
    Resp r = http_.get("/api/logs");
    if (!r.ok()) return;
    JsonNode *root = parse(r.body);
    if (!root) return;
    JsonObject *o = jobj(root);
    if (o && json_object_has_member(o, "logs")) {
        JsonArray *arr = json_object_get_array_member(o, "logs");
        guint n = arr ? json_array_get_length(arr) : 0;
        std::vector<std::string> baris_log;
        baris_log.reserve(n);
        for (guint i = 0; i < n; ++i) {
            JsonNode *el = json_array_get_element(arr, i);
            if (el && JSON_NODE_HOLDS_VALUE(el) && json_node_get_value_type(el) == G_TYPE_STRING)
                baris_log.emplace_back(json_node_get_string(el));
        }

        // Cari baris terakhir yang sudah tampil. Kalau hilang (buffer geser),
        // tampilkan ulang semuanya.
        size_t mulai = 0;
        if (!last_log_.empty()) {
            for (size_t i = baris_log.size(); i > 0; --i) {
                if (baris_log[i - 1] == last_log_) {
                    mulai = i;
                    break;
                }
            }
            if (mulai == 0) isi_textview(view_console_, "");
        }
        if (mulai < baris_log.size()) {
            std::string teks;
            for (size_t i = mulai; i < baris_log.size(); ++i) {
                teks += baris_log[i];
                teks += "\n";
            }
            last_log_ = baris_log.back();
            append_console(teks.substr(0, teks.size() - 1));
        }
    }
    json_node_unref(root);
}

void App::refresh_scripts() {
    if (!store_scripts_) return;
    kosongkan(store_scripts_);
    Resp r = http_.get("/api/scripts");
    if (!r.ok()) return;
    JsonNode *root = parse(r.body);
    if (!root) return;
    JsonObject *o = jobj(root);
    if (o && json_object_has_member(o, "scripts")) {
        JsonArray *arr = json_object_get_array_member(o, "scripts");
        guint n = arr ? json_array_get_length(arr) : 0;
        for (guint i = 0; i < n; ++i) {
            JsonObject *s = jobj(json_array_get_element(arr, i));
            if (!s) continue;
            baris(store_scripts_, {jstr(s, "name"),
                                   std::to_string(jint(s, "lines"))});
        }
    }
    if (set_scripts_) {
        char buf[32];
        std::snprintf(buf, sizeof buf, "%u", o && json_object_has_member(o, "scripts")
                                               ? json_array_get_length(json_object_get_array_member(o, "scripts"))
                                               : 0u);
        gtk_label_set_text(GTK_LABEL(set_scripts_), buf);
    }
    json_node_unref(root);
}

void App::refresh_items(const std::string &q) {
    if (!store_items_) return;
    kosongkan(store_items_);
    std::string path = "/api/items?q=";
    for (char c : q) {
        if (g_ascii_isalnum(c)) path += c;
        else {
            char b[4];
            std::snprintf(b, sizeof b, "%%%02X", static_cast<unsigned char>(c));
            path += b;
        }
    }
    JsonObject *o = get_obj(path);
    if (!o) return;
    if (json_object_has_member(o, "items")) {
        JsonArray *arr = json_object_get_array_member(o, "items");
        guint n = arr ? json_array_get_length(arr) : 0;
        for (guint i = 0; i < n; ++i) {
            JsonObject *it = jobj(json_array_get_element(arr, i));
            if (!it) continue;
            baris(store_items_, {
                std::to_string(jint(it, "id")),
                jstr(it, "name"),
                jstr(it, "rarity"),
                jstr(it, "type"),
                jint(it, "grow") ? std::to_string(jint(it, "grow")) + " dtk" : "—",
            });
        }
        if (items_note_) {
            char buf[96];
            std::snprintf(buf, sizeof buf, "%u item ditampilkan", n);
            gtk_label_set_text(GTK_LABEL(items_note_), buf);
        }
    }
    if (set_items_) {
        char buf[32];
        std::snprintf(buf, sizeof buf, "%ld", jint(o, "total"));
        gtk_label_set_text(GTK_LABEL(set_items_), buf);
    }
    json_object_unref(o);
}

// --------------------------------------------------------------- pilih ---
std::string App::selected_bot() { return pilih_teks(view_bots_, 0); }
std::string App::selected_script() { return pilih_teks(view_scripts_, 0); }
std::string App::proxy_host_port() {
    std::string h = pilih_teks(view_proxies_, 0);
    std::string p = pilih_teks(view_proxies_, 1);
    return h.empty() ? "" : h + ":" + p;
}

void App::set_console(const std::string &teks) { isi_textview(view_console_, teks); }

void App::append_console(const std::string &teks) {
    GtkTextBuffer *b = gtk_text_view_get_buffer(GTK_TEXT_VIEW(view_console_));
    GtkTextIter end;
    gtk_text_buffer_get_end_iter(b, &end);
    gtk_text_buffer_insert(b, &end, teks.c_str(), -1);
    gtk_text_buffer_insert(b, &end, "\n", -1);
    gtk_text_view_scroll_to_iter(GTK_TEXT_VIEW(view_console_), &end, 0.0, FALSE, 0.0, 0.0);
}

// ----------------------------------------------------------- callback ---
void App::on_refresh(GtkButton *, gpointer self) {
    auto *a = static_cast<App *>(self);
    a->refresh();
    a->refresh_items("");
}

void App::on_clear_log(GtkButton *, gpointer self) {
    auto *a = static_cast<App *>(self);
    isi_textview(a->view_console_, "");
    a->last_log_.clear();
}

void App::on_bot_row(GtkTreeView *, gpointer self) {
    auto *a = static_cast<App *>(self);
    std::string label = a->selected_bot();
    if (label.empty()) return;
    std::string err;
    a->post_ok("/api/bot/switch", "{\"label\":\"" + jesc(label) + "\"}", &err);
    a->refresh_switch();
}

void App::on_add_bot(GtkButton *, gpointer self) {
    static_cast<App *>(self)->dialog_add_bot();
}

void App::on_del_bot(GtkButton *, gpointer self) {
    auto *a = static_cast<App *>(self);
    std::string label = a->selected_bot();
    if (label.empty()) return;
    std::string err;
    a->post_ok("/api/account/delete", "{\"label\":\"" + jesc(label) + "\"}", &err);
    a->refresh();
}

void App::on_connect(GtkButton *, gpointer self) {
    auto *a = static_cast<App *>(self);
    std::string label = a->selected_bot();
    if (label.empty()) return;
    std::string err;
    if (!a->post_ok("/api/connect", "{\"label\":\"" + jesc(label) + "\"}", &err))
        a->append_console("[connect] " + label + ": " + err);
    a->refresh_bots();
}

void App::on_disconnect(GtkButton *, gpointer self) {
    auto *a = static_cast<App *>(self);
    std::string label = a->selected_bot();
    if (label.empty()) return;
    std::string err;
    if (!a->post_ok("/api/disconnect", "{\"label\":\"" + jesc(label) + "\"}", &err))
        a->append_console("[disconnect] " + label + ": " + err);
    a->refresh_bots();
}

void App::on_send_cmd(GtkButton *, gpointer self) {
    auto *a = static_cast<App *>(self);
    std::string label = combo_aktif(a->combo_console_bot_);
    std::string cmd = isi_entry(a->entry_cmd_);
    if (cmd.empty()) return;
    std::string err;
    if (!a->post_ok("/api/command",
                    "{\"label\":\"" + jesc(label) + "\",\"command\":\"" + jesc(cmd) + "\"}",
                    &err)) {
        a->append_console("[cmd] " + err);
    } else {
        a->append_console("> " + cmd);
    }
    gtk_entry_set_text(GTK_ENTRY(a->entry_cmd_), "");
    a->refresh();
}

void App::on_cmd_enter(GtkEntry *, gpointer self) {
    on_send_cmd(nullptr, self);
}

void App::on_script_row(GtkTreeView *, gpointer self) {
    auto *a = static_cast<App *>(self);
    std::string nama = a->selected_script();
    if (nama.empty()) return;
    JsonObject *o = a->get_obj("/api/script?name=" + nama);
    if (o) {
        isi_textview(a->editor_, jstr(o, "content"));
        gtk_entry_set_text(GTK_ENTRY(a->entry_script_name_), nama.c_str());
        if (a->exec_note_) {
            std::string info = jstr(o, "folder");
            gtk_label_set_text(GTK_LABEL(a->exec_note_), info.c_str());
        }
        json_object_unref(o);
    }
}

void App::on_new_script(GtkButton *, gpointer self) {
    auto *a = static_cast<App *>(self);
    isi_textview(a->editor_, "-- skrip baru\n");
    gtk_entry_set_text(GTK_ENTRY(a->entry_script_name_), "baru.lua");
    gtk_widget_grab_focus(a->editor_);
}

void App::on_save_script(GtkButton *, gpointer self) {
    auto *a = static_cast<App *>(self);
    std::string nama = isi_entry(a->entry_script_name_);
    if (nama.empty()) nama = "baru.lua";
    std::string isi = baca_textview(a->editor_);
    std::string err;
    if (!a->post_ok("/api/script/save",
                    "{\"name\":\"" + jesc(nama) + "\",\"content\":\"" + jesc(isi) + "\"}",
                    &err)) {
        if (a->exec_note_) gtk_label_set_text(GTK_LABEL(a->exec_note_), err.c_str());
    } else {
        if (a->exec_note_) gtk_label_set_text(GTK_LABEL(a->exec_note_), "tersimpan");
        a->refresh_scripts();
    }
}

void App::on_run_script(GtkButton *, gpointer self) {
    auto *a = static_cast<App *>(self);
    std::string label = combo_aktif(a->combo_console_bot_);
    std::string nama = isi_entry(a->entry_script_name_);
    if (nama.empty()) return;
    std::string err;
    if (!a->post_ok("/api/command",
                    "{\"label\":\"" + jesc(label) + "\",\"command\":\"" +
                        jesc("run " + nama) + "\"}",
                    &err)) {
        a->append_console("[run] " + err);
    } else {
        a->append_console("[run] " + nama + " @ " + label);
    }
}

void App::on_del_script(GtkButton *, gpointer self) {
    auto *a = static_cast<App *>(self);
    std::string nama = isi_entry(a->entry_script_name_);
    if (nama.empty()) nama = a->selected_script();
    if (nama.empty()) return;
    std::string err;
    a->post_ok("/api/script/delete", "{\"name\":\"" + jesc(nama) + "\"}", &err);
    a->refresh_scripts();
    isi_textview(a->editor_, "");
}

void App::on_script_search(GtkSearchEntry *, gpointer self) {
    static_cast<App *>(self)->refresh_scripts();
}

void App::on_item_search(GtkSearchEntry *e, gpointer self) {
    auto *a = static_cast<App *>(self);
    a->refresh_items(gtk_entry_get_text(GTK_ENTRY(e)) ? gtk_entry_get_text(GTK_ENTRY(e)) : "");
}

// ---- proxy ---- lokasi kolom: 0 host, 1 port
void App::on_add_proxy(GtkButton *, gpointer self) {
    static_cast<App *>(self)->dialog_add_proxy();
}

void App::on_del_proxy(GtkButton *, gpointer self) {
    auto *a = static_cast<App *>(self);
    std::string host = pilih_teks(a->view_proxies_, 0);
    std::string port = pilih_teks(a->view_proxies_, 1);
    if (host.empty()) return;
    std::string err;
    a->post_ok("/api/proxies",
               "{\"action\":\"hapus\",\"host\":\"" + jesc(host) +
                   "\",\"port\":" + (port.empty() ? "0" : port) + "}",
               &err);
    a->refresh_proxies();
}

void App::on_check_proxy(GtkButton *, gpointer self) {
    auto *a = static_cast<App *>(self);
    std::string err;
    a->post_ok("/api/proxies", "{\"action\":\"cek\",\"batas\":0}", &err);
    a->refresh_proxies();
}

void App::on_purge_proxy(GtkButton *, gpointer self) {
    auto *a = static_cast<App *>(self);
    std::string err;
    a->post_ok("/api/proxies", "{\"action\":\"hapus_gagal\"}", &err);
    a->refresh_proxies();
}

void App::on_use_proxy(GtkButton *, gpointer self) {
    auto *a = static_cast<App *>(self);
    std::string host = pilih_teks(a->view_proxies_, 0);
    std::string port = pilih_teks(a->view_proxies_, 1);
    std::string label = combo_aktif(a->combo_proxy_bot_);
    if (host.empty() || label.empty()) return;
    std::string err;
    if (!a->post_ok("/api/proxies",
                    "{\"action\":\"pakai\",\"host\":\"" + jesc(host) +
                        "\",\"port\":" + (port.empty() ? "0" : port) +
                        ",\"label\":\"" + jesc(label) + "\"}",
                    &err)) {
        a->append_console("[proxy] " + err);
    } else {
        a->append_console("[proxy] " + label + " -> " + host + ":" + port);
    }
    a->refresh_bots();
}

gboolean App::on_switch(GtkSwitch *sw, gboolean state, gpointer self) {
    auto *a = static_cast<App *>(self);
    if (a->switch_sync_) return FALSE;
    const char *kunci = static_cast<const char *>(g_object_get_data(G_OBJECT(sw), "kunci"));
    if (!kunci) return FALSE;
    std::string label = a->selected_bot();
    std::string err;
    char json[384];
    std::snprintf(json, sizeof json,
                  "{\"feature\":\"%s\",\"label\":\"%s\",\"action\":\"%s\"}",
                  kunci, label.c_str(), state ? "start" : "stop");
    a->post_ok("/api/feature", json, &err);
    return FALSE;
}

gboolean App::bootstrap(gpointer self) {
    auto *a = static_cast<App *>(self);
    // Backend Python butuh ~1-3 dtk. Coba ulang sampai hidup.
    if (++a->boot_tries_ > 40) return FALSE;
    Resp r = a->http_.get("/health");
    if (!r.ok()) return TRUE;
    a->refresh();
    a->refresh_items("");
    if (a->set_url_) gtk_label_set_text(GTK_LABEL(a->set_url_), a->http_.base().c_str());
    return FALSE;
}

gboolean App::on_tick(gpointer self) {
    auto *a = static_cast<App *>(self);
    a->refresh_bots();
    a->refresh_console();
    return TRUE;
}

void App::on_destroy(GtkWidget *, gpointer) { gtk_main_quit(); }

// -------------------------------------------------------------- dialog ---
void App::dialog_add_bot() {
    GtkWidget *d = gtk_dialog_new_with_buttons(
        "Tambah Bot", GTK_WINDOW(window_), GTK_DIALOG_MODAL,
        "Batal", GTK_RESPONSE_CANCEL, "Tambah", GTK_RESPONSE_ACCEPT, nullptr);
    GtkWidget *area = gtk_dialog_get_content_area(GTK_DIALOG(d));
    gtk_container_set_border_width(GTK_CONTAINER(area), 16);
    GtkWidget *grid = gtk_grid_new();
    gtk_grid_set_row_spacing(GTK_GRID(grid), 8);
    gtk_grid_set_column_spacing(GTK_GRID(grid), 10);

    GtkWidget *e_label = gtk_entry_new();
    GtkWidget *e_grow = gtk_entry_new();
    GtkWidget *e_pass = gtk_entry_new();
    gtk_entry_set_visibility(GTK_ENTRY(e_pass), FALSE);
    GtkWidget *e_proxy = gtk_entry_new();
    gtk_entry_set_placeholder_text(GTK_ENTRY(e_proxy), "socks5://user:pass@host:port (opsional)");

    const char *nama[] = {"Label", "GrowID", "Password", "Proxy"};    GtkWidget *isi[] = {e_label, e_grow, e_pass, e_proxy};
    for (int i = 0; i < 4; ++i) {
        GtkWidget *l = gtk_label_new(nama[i]);
        gtk_widget_set_halign(l, GTK_ALIGN_END);
        gtk_grid_attach(GTK_GRID(grid), l, 0, i, 1, 1);
        gtk_widget_set_size_request(isi[i], 280, -1);
        gtk_grid_attach(GTK_GRID(grid), isi[i], 1, i, 1, 1);
    }
    gtk_container_add(GTK_CONTAINER(area), grid);
    gtk_widget_show_all(d);

    if (gtk_dialog_run(GTK_DIALOG(d)) == GTK_RESPONSE_ACCEPT) {
        std::string label = isi_entry(e_label);
        if (!label.empty()) {
            std::string err;
            post_ok("/api/login",
                    "{\"label\":\"" + jesc(label) +
                        "\",\"username\":\"" + jesc(isi_entry(e_grow)) +
                        "\",\"password\":\"" + jesc(isi_entry(e_pass)) +
                        "\",\"proxy\":\"" + jesc(isi_entry(e_proxy)) + "\"}",
                    &err);
            refresh();
        }
    }
    gtk_widget_destroy(d);
}

void App::dialog_add_proxy() {
    GtkWidget *d = gtk_dialog_new_with_buttons(
        "Tambah Proxy", GTK_WINDOW(window_), GTK_DIALOG_MODAL,
        "Batal", GTK_RESPONSE_CANCEL, "Tambah", GTK_RESPONSE_ACCEPT, nullptr);
    gtk_window_set_default_size(GTK_WINDOW(d), 460, 320);
    GtkWidget *area = gtk_dialog_get_content_area(GTK_DIALOG(d));
    gtk_container_set_border_width(GTK_CONTAINER(area), 16);

    GtkWidget *l = gtk_label_new("Satu proxy per baris: host:port atau user:pass@host:port");
    gtk_widget_set_halign(l, GTK_ALIGN_START);
    gtk_box_pack_start(GTK_BOX(area), l, FALSE, FALSE, 0);

    GtkWidget *tv = gtk_text_view_new();
    gtk_text_view_set_monospace(GTK_TEXT_VIEW(tv), TRUE);
    GtkWidget *sc = gtk_scrolled_window_new(nullptr, nullptr);
    gtk_widget_set_size_request(sc, -1, 200);
    gtk_container_add(GTK_CONTAINER(sc), tv);
    gtk_box_pack_start(GTK_BOX(area), sc, TRUE, TRUE, 8);
    gtk_widget_show_all(d);

    if (gtk_dialog_run(GTK_DIALOG(d)) == GTK_RESPONSE_ACCEPT) {
        std::string teks = baca_textview(tv);
        if (!teks.empty()) {
            std::string err;
            post_ok("/api/proxies",
                    "{\"action\":\"tambah\",\"text\":\"" + jesc(teks) + "\"}", &err);
            refresh_proxies();
        }
    }
    gtk_widget_destroy(d);
}

}  // namespace lucifer
