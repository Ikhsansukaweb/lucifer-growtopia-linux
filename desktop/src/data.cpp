// lucifer/data.cpp — jembatan data: HTTP JSON <-> widget.
//
// Semua fungsi di sini hanya membaca /api/* lalu mengisi model GTK.
// Tak ada logika Growtopia di sisi C++.

#include "ui.h"

#include <unistd.h>

#include <gdk-pixbuf/gdk-pixbuf.h>

#include <cctype>
#include <map>

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
    refresh_scripts();
    refresh_detail();
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

    if (combo_proxy_bot_) isi_combo(combo_proxy_bot_, combo);

    // Tanpa ini tidak ada baris terpilih, jadi Hapus/Connect tidak tahu
    // bot mana yang dimaksud dan diam saja.
    if (view_bots_ && !combo.empty()) {
        GtkTreeSelection *sel = gtk_tree_view_get_selection(GTK_TREE_VIEW(view_bots_));
        GtkTreeModel *model = nullptr;
        GtkTreeIter it;
        if (!gtk_tree_selection_get_selected(sel, &model, &it)) {
            GtkTreeIter first;
            if (gtk_tree_model_get_iter_first(GTK_TREE_MODEL(store_bots_), &first))
                gtk_tree_selection_select_iter(sel, &first);
        }
    }

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

void App::refresh_detail() {
    if (aktif_.empty() || !detail_notebook_) return;
    JsonObject *o = get_obj("/api/bot?label=" + aktif_);
    if (!o) return;

    // ---- kepala ----
    JsonObject *st = json_object_has_member(o, "stats")
                         ? jobj(json_object_get_member(o, "stats"))
                         : nullptr;
    std::string nama = st ? jstr(st, "name") : "";
    std::string dunia = st ? jstr(st, "world") : "";
    std::string status = st ? jstr(st, "status") : "";
    if (detail_judul_) gtk_label_set_text(GTK_LABEL(detail_judul_), aktif_.c_str());
    if (detail_sub_) {
        char buf[256];
        std::snprintf(buf, sizeof buf, "%s · %s · %s", nama.c_str(),
                      status.empty() ? "offline" : status.c_str(),
                      dunia.empty() ? "di luar dunia" : dunia.c_str());
        gtk_label_set_text(GTK_LABEL(detail_sub_), buf);
    }

    // ---- peta dulu: kisi tile butuh posisi player sebagai pusat ----
    refresh_detail_map();

    // ---- mod menu: nilai tiap kontrol dari server ----
    refresh_detail_schema();

    // ---- console bot (bukan log global) ----
    if (view_console_ && json_object_has_member(o, "console")) {
        JsonArray *arr = json_object_get_array_member(o, "console");
        guint n = arr ? json_array_get_length(arr) : 0;
        if (static_cast<int>(n) != console_lines_) {
            console_lines_ = static_cast<int>(n);
            std::string teks;
            for (guint i = 0; i < n; ++i) {
                JsonNode *el = json_array_get_element(arr, i);
                if (el && JSON_NODE_HOLDS_VALUE(el) &&
                    json_node_get_value_type(el) == G_TYPE_STRING) {
                    teks += json_node_get_string(el);
                    teks += "\n";
                }
            }
            isi_textview(view_console_, teks);
            GtkTextIter end;
            GtkTextBuffer *b = gtk_text_view_get_buffer(GTK_TEXT_VIEW(view_console_));
            gtk_text_buffer_get_end_iter(b, &end);
            gtk_text_view_scroll_to_iter(GTK_TEXT_VIEW(view_console_), &end,
                                         0.0, FALSE, 0.0, 0.0);
        }
    }

    refresh_detail_chat();
    refresh_detail_inv();
    if (detail_info_ && st) {
        char buf[1024];
        std::snprintf(buf, sizeof buf,
                      "label      : %s\nnama       : %s\nstatus     : %s\n"
                      "ping       : %ld ms\nserver     : %s\ndunia      : %s (%s)\n"
                      "pemain     : %ld\ntile       : %ld\nlevel      : %ld\n"
                      "gems       : %ld\nproxy      : %s\nwaktu aktif: %s",
                      aktif_.c_str(), nama.c_str(), status.c_str(),
                      jint(st, "ping"), jstr(st, "server").c_str(),
                      dunia.c_str(), jstr(st, "world_size").c_str(),
                      jint(st, "players"), jint(st, "tiles"), jint(st, "level"),
                      jint(st, "gems"),
                      jstr(st, "proxy").empty() ? "—" : jstr(st, "proxy").c_str(),
                      jstr(st, "active_time").c_str());
        gtk_label_set_text(GTK_LABEL(detail_info_), buf);
    }
    json_object_unref(o);
}

void App::refresh_detail_chat() {
    if (aktif_.empty() || !view_chat_) return;
    JsonObject *o = get_obj("/api/chat?label=" + aktif_);
    if (!o) return;
    std::string teks;
    if (json_object_has_member(o, "chat")) {
        JsonArray *arr = json_object_get_array_member(o, "chat");
        guint n = arr ? json_array_get_length(arr) : 0;
        for (guint i = 0; i < n; ++i) {
            JsonObject *c = jobj(json_array_get_element(arr, i));
            if (!c) continue;
            std::string jenis = jstr(c, "jenis");
            teks += jstr(c, "ts");
            teks += "  ";
            if (jenis == "sendiri") teks += "[aku] ";
            teks += jstr(c, "pengirim");
            teks += ": ";
            teks += jstr(c, "teks");
            teks += "\n";
        }
        // hanya tulis ulang kalau jumlah baris berubah
        if (static_cast<int>(n) != chat_lines_) {
            chat_lines_ = static_cast<int>(n);
            isi_textview(view_chat_, teks);
            GtkTextIter end;
            GtkTextBuffer *b = gtk_text_view_get_buffer(GTK_TEXT_VIEW(view_chat_));
            gtk_text_buffer_get_end_iter(b, &end);
            gtk_text_view_scroll_to_iter(GTK_TEXT_VIEW(view_chat_), &end,
                                         0.0, FALSE, 0.0, 0.0);
        }
    }
    json_object_unref(o);
}

void App::refresh_detail_map() {
    if (aktif_.empty() || !peta_area_) return;
    JsonObject *o = get_obj("/api/map?label=" + aktif_);
    if (!o) return;

    peta_tiles_.clear();
    peta_players_.clear();
    peta_w_ = static_cast<int>(jint(o, "w"));
    peta_h_ = static_cast<int>(jint(o, "h"));

    int siap = 0, total = 0;
    if (json_object_has_member(o, "tiles")) {
        JsonArray *arr = json_object_get_array_member(o, "tiles");
        guint n = arr ? json_array_get_length(arr) : 0;
        for (guint i = 0; i < n; ++i) {
            JsonObject *t = jobj(json_array_get_element(arr, i));
            if (!t) continue;
            MTile m{};
            m.x = static_cast<int>(jint(t, "x"));
            m.y = static_cast<int>(jint(t, "y"));
            m.fg = static_cast<int>(jint(t, "fg"));
            m.bg = static_cast<int>(jint(t, "bg"));
            m.seed = jbool(t, "seed");
            m.ready = jbool(t, "ready");
            m.nama = jstr(t, "fg_name");
            if (m.nama.empty()) m.nama = jstr(t, "bg_name");
            if (m.ready) ++siap;
            ++total;
            peta_tiles_.push_back(m);
        }
    }
    if (json_object_has_member(o, "players")) {
        JsonArray *arr = json_object_get_array_member(o, "players");
        guint n = arr ? json_array_get_length(arr) : 0;
        for (guint i = 0; i < n; ++i) {
            JsonObject *p = jobj(json_array_get_element(arr, i));
            if (!p) continue;
            MPlayer mp{};
            mp.x = static_cast<int>(jint(p, "x"));
            mp.y = static_cast<int>(jint(p, "y"));
            mp.lokal = jbool(p, "local");
            mp.nama = jstr(p, "name");
            peta_players_.push_back(mp);
        }
    }

    if (peta_w_ <= 0) peta_w_ = 40;
    if (peta_h_ <= 0) peta_h_ = 20;
    // Dunia nyata bisa 100x1000 (height di Growtopia = 30..~330). Ukuran tile
    // dihitung ulang saat draw supaya seluruh peta masuk viewport.
    gtk_widget_queue_draw(peta_area_);

    if (map_note_ && hover_x_ < 0) {
        char buf[320];
        std::snprintf(buf, sizeof buf,
                      "%s  ·  %dx%d  ·  %d tile berisi  ·  %d siap panen  ·  %zu pemain",
                      jstr(o, "world").empty() ? "(belum masuk dunia)" : jstr(o, "world").c_str(),
                      peta_w_, peta_h_, total, siap, peta_players_.size());
        gtk_label_set_text(GTK_LABEL(map_note_), buf);
    }
    json_object_unref(o);
}

void App::refresh_detail_inv() {
    if (aktif_.empty() || !inv_flow_) return;
    JsonObject *o = get_obj("/api/inventory?label=" + aktif_);
    if (!o) return;

    // tanda isi: bangun ulang hanya kalau berubah
    std::string ttd;
    int total = 0;
    JsonArray *arr = json_object_has_member(o, "items")
                         ? json_object_get_array_member(o, "items") : nullptr;
    guint n = arr ? json_array_get_length(arr) : 0;
    for (guint i = 0; i < n; ++i) {
        JsonObject *it = jobj(json_array_get_element(arr, i));
        if (!it) continue;
        ++total;
        ttd += std::to_string(jint(it, "id")) + ":" +
               std::to_string(jint(it, "count")) + ";";
    }
    if (ttd == inv_ttd_) {
        if (inv_note_) {
            char buf[128];
            std::snprintf(buf, sizeof buf, "%d jenis item  ·  %ld/%ld slot",
                          total, jint(o, "slot_pakai"), jint(o, "slot_total"));
            gtk_label_set_text(GTK_LABEL(inv_note_), buf);
        }
        json_object_unref(o);
        return;
    }
    inv_ttd_ = ttd;

    // kosongkan lalu isi ulang dengan kotak bergambar
    std::vector<GtkWidget *> buang;
    gtk_container_foreach(GTK_CONTAINER(inv_flow_),
                          [](GtkWidget *w, gpointer d) {
                              static_cast<std::vector<GtkWidget *> *>(d)->push_back(w);
                          }, &buang);
    for (GtkWidget *w : buang) gtk_widget_destroy(w);

    for (guint i = 0; i < n; ++i) {
        JsonObject *it = jobj(json_array_get_element(arr, i));
        if (!it) continue;
        int id = static_cast<int>(jint(it, "id"));
        int jml = static_cast<int>(jint(it, "count"));
        std::string nama = jstr(it, "name");

        // kotak: gambar 48 px + angka jumlah di kanan-bawah
        GtkWidget *kotak = gtk_overlay_new();
        gtk_widget_set_size_request(kotak, 64, 64);
        GtkStyleContext *kc = gtk_widget_get_style_context(kotak);
        gtk_style_context_add_class(kc, jbool(it, "active") ? "invon" : "invoff");

        GtkWidget *gambar = gtk_image_new();
        GdkPixbuf *pb = sprite(id);
        if (pb) {
            GdkPixbuf *kcl = gdk_pixbuf_scale_simple(pb, 48, 48, GDK_INTERP_BILINEAR);
            gtk_image_set_from_pixbuf(GTK_IMAGE(gambar), kcl);
            if (kcl) g_object_unref(kcl);
        } else {
            gtk_image_set_from_icon_name(GTK_IMAGE(gambar), "image-missing",
                                         GTK_ICON_SIZE_DIALOG);
        }
        gtk_widget_set_halign(gambar, GTK_ALIGN_CENTER);
        gtk_widget_set_valign(gambar, GTK_ALIGN_CENTER);
        gtk_container_add(GTK_CONTAINER(kotak), gambar);

        GtkWidget *angka = gtk_label_new(std::to_string(jml).c_str());
        gtk_widget_set_halign(angka, GTK_ALIGN_END);
        gtk_widget_set_valign(angka, GTK_ALIGN_END);
        gtk_widget_set_margin_end(angka, 3);
        gtk_widget_set_margin_bottom(angka, 1);
        GtkStyleContext *ac = gtk_widget_get_style_context(angka);
        gtk_style_context_add_class(ac, "invjml");
        gtk_overlay_add_overlay(GTK_OVERLAY(kotak), angka);

        // tooltip: nama + id
        std::string tip = nama + "  (#" + std::to_string(id) + ")";
        gtk_widget_set_tooltip_text(kotak, tip.c_str());

        gtk_flow_box_insert(GTK_FLOW_BOX(inv_flow_), kotak, -1);
    }
    gtk_widget_show_all(inv_flow_);

    if (inv_note_) {
        char buf[128];
        std::snprintf(buf, sizeof buf, "%d jenis item  ·  %ld/%ld slot",
                      total, jint(o, "slot_pakai"), jint(o, "slot_total"));
        gtk_label_set_text(GTK_LABEL(inv_note_), buf);
    }
    json_object_unref(o);
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
std::string App::selected_bot() {
    std::string l = pilih_teks(view_bots_, 0);
    return l.empty() ? aktif_ : l;
}
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

// Pilih baris bot -> langsung buka halaman detail bot itu.
void App::on_open_bot(GtkTreeView *, gpointer self) {
    auto *a = static_cast<App *>(self);
    std::string nama = a->selected_bot();
    if (nama.empty()) return;
    if (nama == a->aktif_ && a->bot_stack_ &&
        std::string(gtk_stack_get_visible_child_name(GTK_STACK(a->bot_stack_))) == "detail")
        return;

    std::string err;
    a->post_ok("/api/bot/switch", "{\"label\":\"" + jesc(nama) + "\"}", &err);
    a->aktif_ = nama;
    a->chat_lines_ = 0;
    if (a->bot_stack_) gtk_stack_set_visible_child_name(GTK_STACK(a->bot_stack_), "detail");
    a->refresh_detail();
}

void App::on_back_bots(GtkButton *, gpointer self) {
    auto *a = static_cast<App *>(self);
    if (a->bot_stack_) gtk_stack_set_visible_child_name(GTK_STACK(a->bot_stack_), "daftar");
}

void App::on_token_hp(GtkButton *, gpointer self) {
    auto *a = static_cast<App *>(self);
    GtkWidget *d = gtk_dialog_new_with_buttons(
        "Ambil Token dari HP", GTK_WINDOW(a->window_), GTK_DIALOG_MODAL,
        "Batal", GTK_RESPONSE_CANCEL, "Ambil", GTK_RESPONSE_ACCEPT, nullptr);
    GtkWidget *area = gtk_dialog_get_content_area(GTK_DIALOG(d));
    gtk_container_set_border_width(GTK_CONTAINER(area), 16);

    GtkWidget *info = gtk_label_new(
        "Tarik save.dat dari HP lewat adb, ambil refreshToken,\n"
        "tukar jadi ltoken, lalu login. HP harus tersambung USB\n"
        "dan debugging USB aktif.");
    gtk_label_set_xalign(GTK_LABEL(info), 0.0);
    gtk_box_pack_start(GTK_BOX(area), info, FALSE, FALSE, 0);

    GtkWidget *grid = gtk_grid_new();
    gtk_grid_set_row_spacing(GTK_GRID(grid), 8);
    gtk_grid_set_column_spacing(GTK_GRID(grid), 10);
    GtkWidget *e_label = gtk_entry_new();
    gtk_entry_set_text(GTK_ENTRY(e_label), "hp");
    GtkWidget *e_pkg = gtk_entry_new();
    gtk_entry_set_placeholder_text(GTK_ENTRY(e_pkg), "com.rtsoft.growtopia (kosong = bawaan)");
    gtk_widget_set_size_request(e_pkg, 300, -1);
    GtkWidget *l1 = gtk_label_new("Label akun");
    GtkWidget *l2 = gtk_label_new("Paket aplikasi");
    gtk_grid_attach(GTK_GRID(grid), l1, 0, 0, 1, 1);
    gtk_grid_attach(GTK_GRID(grid), e_label, 1, 0, 1, 1);
    gtk_grid_attach(GTK_GRID(grid), l2, 0, 1, 1, 1);
    gtk_grid_attach(GTK_GRID(grid), e_pkg, 1, 1, 1, 1);
    gtk_box_pack_start(GTK_BOX(area), grid, FALSE, FALSE, 10);
    gtk_widget_show_all(d);

    if (gtk_dialog_run(GTK_DIALOG(d)) == GTK_RESPONSE_ACCEPT) {
        std::string label = isi_entry(e_label);
        std::string pkg = isi_entry(e_pkg);
        if (!label.empty()) {
            std::string body = "{\"label\":\"" + jesc(label) + "\"";
            if (!pkg.empty()) body += ",\"pkg\":\"" + jesc(pkg) + "\"";
            body += ",\"connect\":false}";
            std::string err;
            if (!a->post_ok("/api/login/hp", body, &err)) {
                GtkWidget *e = gtk_message_dialog_new(
                    GTK_WINDOW(a->window_), GTK_DIALOG_MODAL, GTK_MESSAGE_ERROR,
                    GTK_BUTTONS_OK, "%s", err.c_str());
                gtk_dialog_run(GTK_DIALOG(e));
                gtk_widget_destroy(e);
            }
            a->refresh();
        }
    }
    gtk_widget_destroy(d);
}

void App::on_send_chat(GtkButton *, gpointer self) {
    auto *a = static_cast<App *>(self);
    std::string teks = isi_entry(a->entry_chat_);
    if (teks.empty() || a->aktif_.empty()) return;
    std::string err;
    a->post_ok("/api/command",
               "{\"label\":\"" + jesc(a->aktif_) +
                   "\",\"command\":\"" + jesc("say " + teks) + "\"}",
               &err);
    gtk_entry_set_text(GTK_ENTRY(a->entry_chat_), "");
    a->refresh_detail_chat();
}

void App::on_chat_enter(GtkEntry *, gpointer self) {
    on_send_chat(nullptr, self);
}

void App::on_add_bot(GtkButton *, gpointer self) {
    static_cast<App *>(self)->dialog_add_bot();
}

void App::on_del_bot(GtkButton *, gpointer self) {
    auto *a = static_cast<App *>(self);
    std::string label = a->selected_bot();
    if (label.empty()) {
        a->append_console("[hapus] pilih bot dulu di tabel");
        return;
    }

    GtkWidget *d = gtk_message_dialog_new(
        GTK_WINDOW(a->window_), GTK_DIALOG_MODAL, GTK_MESSAGE_QUESTION,
        GTK_BUTTONS_NONE, "Hapus bot \"%s\"?", label.c_str());
    gtk_message_dialog_format_secondary_text(
        GTK_MESSAGE_DIALOG(d), "Akun dan bot akan dihapus dari accounts.json.");
    gtk_dialog_add_buttons(GTK_DIALOG(d), "Batal", GTK_RESPONSE_CANCEL,
                           "Hapus", GTK_RESPONSE_ACCEPT, nullptr);
    gint jawab = gtk_dialog_run(GTK_DIALOG(d));
    gtk_widget_destroy(d);
    if (jawab != GTK_RESPONSE_ACCEPT) return;

    std::string err;
    if (!a->post_ok("/api/account/delete",
                    "{\"label\":\"" + jesc(label) + "\"}", &err))
        a->append_console("[hapus] " + label + ": " + err);
    else
        a->append_console("[hapus] " + label + " dihapus");
    if (a->aktif_ == label) a->aktif_.clear();
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
    std::string label = a->aktif_;
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
    std::string label = a->aktif_;
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

gboolean App::bootstrap(gpointer self) {
    auto *a = static_cast<App *>(self);
    // Backend Python butuh ~1-3 dtk. Coba ulang sampai hidup.
    if (++a->boot_tries_ > 40) return FALSE;
    Resp r = a->http_.get("/health");
    if (!r.ok()) return TRUE;
    a->refresh();
    a->refresh_items("");
    if (a->set_url_) gtk_label_set_text(GTK_LABEL(a->set_url_), a->http_.base().c_str());
    if (!a->auto_bot_.empty()) {
        std::string nama = a->auto_bot_;
        a->auto_bot_.clear();
        a->aktif_ = nama;
        a->chat_lines_ = 0;
        if (a->bot_stack_)
            gtk_stack_set_visible_child_name(GTK_STACK(a->bot_stack_), "detail");
        a->refresh_detail();
        if (const char *dt = g_getenv("LUCIFER_DTAB"))
            if (a->detail_notebook_)
                gtk_notebook_set_current_page(GTK_NOTEBOOK(a->detail_notebook_),
                                              std::atoi(dt));
    }
    return FALSE;
}

gboolean App::on_tick(gpointer self) {
    auto *a = static_cast<App *>(self);
    a->refresh_bots();
    a->refresh_detail_chat();
    if (++a->tick_n_ % 4 == 0) a->refresh_detail_map();
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
    GtkWidget *e_tok = gtk_entry_new();
    gtk_entry_set_placeholder_text(GTK_ENTRY(e_tok), "tempel ltoken (lebih andal dari sandi)");

    const char *nama[] = {"Label", "GrowID", "Password", "ltoken", "Proxy"};
    GtkWidget *isi[] = {e_label, e_grow, e_pass, e_tok, e_proxy};
    for (int i = 0; i < 5; ++i) {
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
        if (label.empty()) label = isi_entry(e_grow);
        if (label.empty()) {
            append_console("[tambah] label atau GrowID wajib diisi");
        } else {
            std::string err;
            bool ok = post_ok("/api/login",
                              "{\"label\":\"" + jesc(label) +
                                  "\",\"username\":\"" + jesc(isi_entry(e_grow)) +
                                  "\",\"password\":\"" + jesc(isi_entry(e_pass)) +
                                  "\",\"ltoken\":\"" + jesc(isi_entry(e_tok)) +
                                  "\",\"proxy\":\"" + jesc(isi_entry(e_proxy)) + "\"}",
                              &err);
            append_console(ok ? "[tambah] " + label + " ditambahkan"
                              : "[tambah] " + label + ": " + err);
            if (!ok) {
                GtkWidget *md = gtk_message_dialog_new(
                    GTK_WINDOW(window_), GTK_DIALOG_MODAL, GTK_MESSAGE_ERROR,
                    GTK_BUTTONS_OK, "Gagal menambah bot");
                gtk_message_dialog_format_secondary_text(GTK_MESSAGE_DIALOG(md),
                                                        "%s", err.c_str());
                gtk_dialog_run(GTK_DIALOG(md));
                gtk_widget_destroy(md);
            }
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


// ------------------------------------------------------- mod menu ---
// Sidebar dari /api/features/schema (satu sumber di Python). Tiap fitur punya
// halaman sendiri: saklar, angka, pilihan, teks, pemilih item/tile, tombol.
// Nilai awal dibaca dari `nilai` supaya form menampilkan keadaan server.
namespace {

// warna latar baris sidebar
void gaya_baris(GtkWidget *row) {
    GtkStyleContext *c = gtk_widget_get_style_context(row);
    gtk_style_context_add_class(c, "navrow");
}

}  // namespace

void App::build_sidebar(const std::string &pilih) {
    if (!detail_list_) return;
    GList *anak = gtk_container_get_children(GTK_CONTAINER(detail_list_));
    for (GList *it = anak; it; it = it->next) gtk_widget_destroy(GTK_WIDGET(it->data));
    g_list_free(anak);

    for (auto &kv : halaman_fitur_) {
        GtkWidget *row = gtk_list_box_row_new();
        GtkWidget *l = gtk_label_new(kv.first.c_str());
        gtk_widget_set_halign(l, GTK_ALIGN_START);
        gtk_widget_set_margin_start(l, 10);
        gtk_widget_set_margin_end(l, 10);
        gtk_widget_set_margin_top(l, 7);
        gtk_widget_set_margin_bottom(l, 7);
        gtk_container_add(GTK_CONTAINER(row), l);
        gaya_baris(row);
        g_object_set_data_full(G_OBJECT(row), "fitur", g_strdup(kv.first.c_str()), g_free);
        gtk_list_box_insert(GTK_LIST_BOX(detail_list_), row, -1);
    }
    gtk_widget_show_all(detail_list_);

    std::string target = pilih;
    if (const char *env = g_getenv("LUCIFER_FITUR")) target = env;
    if (!target.empty()) {
        GList *rows = gtk_container_get_children(GTK_CONTAINER(detail_list_));
        for (GList *it = rows; it; it = it->next) {
            const char *f = static_cast<const char *>(
                g_object_get_data(G_OBJECT(it->data), "fitur"));
            if (f && target == f) {
                gtk_list_box_select_row(GTK_LIST_BOX(detail_list_),
                                        GTK_LIST_BOX_ROW(it->data));
                gtk_stack_set_visible_child_name(GTK_STACK(detail_stack_), f);
                break;
            }
        }
        g_list_free(rows);
    }
}

void App::build_feature_page(const std::string &nama, const std::string &ket,
                             const std::string &fitur, JsonArray *kontrol,
                             JsonObject *nilai) {
    kunci_fitur_[nama] = fitur;

    GtkWidget *scroll = gtk_scrolled_window_new(nullptr, nullptr);
    gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(scroll),
                                   GTK_POLICY_NEVER, GTK_POLICY_AUTOMATIC);
    GtkStyleContext *sc_ctx = gtk_widget_get_style_context(scroll);
    gtk_style_context_add_class(sc_ctx, "plain");

    GtkWidget *isi = gtk_box_new(GTK_ORIENTATION_VERTICAL, 12);
    gtk_container_set_border_width(GTK_CONTAINER(isi), 2);
    gtk_container_add(GTK_CONTAINER(scroll), isi);

    // ---- kepala ----
    GtkWidget *kepala = gtk_box_new(GTK_ORIENTATION_VERTICAL, 4);
    GtkWidget *t = gtk_label_new(nama.c_str());
    gtk_widget_set_halign(t, GTK_ALIGN_START);
    gtk_widget_set_name(t, "botjudul");
    gtk_box_pack_start(GTK_BOX(kepala), t, FALSE, FALSE, 0);
    if (!ket.empty()) {
        GtkWidget *k = gtk_label_new(ket.c_str());
        gtk_widget_set_halign(k, GTK_ALIGN_START);
        GtkStyleContext *kc = gtk_widget_get_style_context(k);
        gtk_style_context_add_class(kc, "dim");
        gtk_box_pack_start(GTK_BOX(kepala), k, FALSE, FALSE, 0);
    }
    GtkWidget *bar = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    GtkWidget *b_start = toolbtn("Nyalakan", G_CALLBACK(on_fitur_start), "primary");
    g_object_set_data_full(G_OBJECT(b_start), "fitur", g_strdup(nama.c_str()), g_free);
    GtkWidget *b_stop = toolbtn("Matikan", G_CALLBACK(on_fitur_stop), "ghost");
    g_object_set_data_full(G_OBJECT(b_stop), "fitur", g_strdup(nama.c_str()), g_free);
    GtkWidget *b_save = toolbtn("Simpan", G_CALLBACK(on_fitur_simpan), "ghost");
    g_object_set_data_full(G_OBJECT(b_save), "fitur", g_strdup(nama.c_str()), g_free);
    GtkWidget *note = gtk_label_new("mati");
    gtk_widget_set_halign(note, GTK_ALIGN_START);
    GtkStyleContext *nc = gtk_widget_get_style_context(note);
    gtk_style_context_add_class(nc, "dim");
    g_object_set_data_full(G_OBJECT(detail_stack_), fitur.c_str(), note, nullptr);
    gtk_box_pack_start(GTK_BOX(bar), b_start, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(bar), b_stop, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(bar), b_save, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(bar), note, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(kepala), bar, FALSE, FALSE, 8);
    gtk_box_pack_start(GTK_BOX(isi), card(nullptr, kepala), FALSE, FALSE, 0);

    // ---- kontrol ----
    GtkWidget *grid = gtk_grid_new();
    gtk_grid_set_row_spacing(GTK_GRID(grid), 9);
    gtk_grid_set_column_spacing(GTK_GRID(grid), 14);
    guint baris = 0;
    guint n = kontrol ? json_array_get_length(kontrol) : 0;
    for (guint i = 0; i < n; ++i) {
        JsonObject *k = jobj(json_array_get_element(kontrol, i));
        if (!k) continue;
        std::string kunci = jstr(k, "kunci");
        std::string tipe = jstr(k, "tipe");
        std::string label = jstr(k, "label");
        if (kunci.empty()) continue;

        GtkWidget *w = nullptr;
        if (tipe == "tombol") {
            const char *gaya = jstr(k, "gaya").empty() ? "ghost" : nullptr;
            std::string cls = jstr(k, "gaya");
            if (cls.empty()) cls = "ghost";
            w = gtk_button_new_with_label(label.c_str());
            GtkStyleContext *c = gtk_widget_get_style_context(w);
            gtk_style_context_add_class(c, cls.c_str());
            g_object_set_data_full(G_OBJECT(w), "fitur", g_strdup(nama.c_str()), g_free);
            g_object_set_data_full(G_OBJECT(w), "aksi",
                                   g_strdup(jstr(k, "aksi").c_str()), g_free);
            g_signal_connect(w, "clicked", G_CALLBACK(on_replay_aksi), this);
            (void)gaya;
            gtk_widget_set_halign(w, GTK_ALIGN_START);
            gtk_grid_attach(GTK_GRID(grid), w, 0, baris, 2, 1);
            ++baris;
            continue;
        }
        if (tipe == "toggle") {
            w = gtk_switch_new();
            gtk_widget_set_valign(w, GTK_ALIGN_CENTER);
            gtk_widget_set_halign(w, GTK_ALIGN_START);
            if (nilai && json_object_has_member(nilai, kunci.c_str()))
                gtk_switch_set_active(GTK_SWITCH(w),
                                      jbool(nilai, kunci.c_str()));
        } else if (tipe == "angka" || tipe == "pecahan") {
            double min = 0, maks = 100000, langkah = 1;
            if (json_object_has_member(k, "min")) min = static_cast<double>(jint(k, "min"));
            if (json_object_has_member(k, "maks")) maks = static_cast<double>(jint(k, "maks"));
            if (json_object_has_member(k, "langkah")) {
                JsonNode *ln = json_object_get_member(k, "langkah");
                if (ln && JSON_NODE_HOLDS_VALUE(ln) &&
                    json_node_get_value_type(ln) == G_TYPE_DOUBLE)
                    langkah = json_node_get_double(ln);
                else
                    langkah = static_cast<double>(jint(k, "langkah"));
            }
            if (maks <= min) maks = min + 1;
            if (langkah <= 0) langkah = 1;
            GtkAdjustment *adj = gtk_adjustment_new(min, min, maks, langkah,
                                                    langkah * 10, 0);
            w = gtk_spin_button_new(adj, langkah, tipe == "pecahan" ? 2 : 0);
            gtk_widget_set_size_request(w, 130, -1);
            gtk_widget_set_hexpand(w, FALSE);
            gtk_widget_set_halign(w, GTK_ALIGN_START);
            if (nilai && json_object_has_member(nilai, kunci.c_str())) {
                JsonNode *vn = json_object_get_member(nilai, kunci.c_str());
                double v = 0;
                if (vn && JSON_NODE_HOLDS_VALUE(vn)) {
                    GType vt = json_node_get_value_type(vn);
                    if (vt == G_TYPE_DOUBLE) v = json_node_get_double(vn);
                    else if (vt == G_TYPE_INT64) v = static_cast<double>(json_node_get_int(vn));
                    else if (vt == G_TYPE_STRING) v = std::atof(json_node_get_string(vn));
                }
                gtk_spin_button_set_value(GTK_SPIN_BUTTON(w), v);
            }
        } else if (tipe == "pilihan") {
            w = gtk_combo_box_text_new();
            std::string sekarang;
            if (nilai && json_object_has_member(nilai, kunci.c_str()))
                sekarang = jstr(nilai, kunci.c_str());
            int pilih = 0, idx = 0;
            if (json_object_has_member(k, "opsi")) {
                JsonArray *opsi = json_object_get_array_member(k, "opsi");
                guint m = opsi ? json_array_get_length(opsi) : 0;
                for (guint j = 0; j < m; ++j) {
                    JsonNode *el = json_array_get_element(opsi, j);
                    if (el && JSON_NODE_HOLDS_VALUE(el) &&
                        json_node_get_value_type(el) == G_TYPE_STRING) {
                        const char *teks = json_node_get_string(el);
                        gtk_combo_box_text_append_text(GTK_COMBO_BOX_TEXT(w), teks);
                        if (!sekarang.empty() && sekarang == teks) pilih = idx;
                        ++idx;
                    }
                }
            }
            gtk_combo_box_set_active(GTK_COMBO_BOX(w), pilih);
            gtk_widget_set_size_request(w, 160, -1);
        } else if (tipe == "teks_panjang") {
            w = gtk_text_view_new();
            gtk_text_view_set_wrap_mode(GTK_TEXT_VIEW(w), GTK_WRAP_WORD_CHAR);
            GtkWidget *sc = gtk_scrolled_window_new(nullptr, nullptr);
            gtk_widget_set_size_request(sc, -1, 96);
            gtk_container_add(GTK_CONTAINER(sc), w);
            gtk_widget_set_hexpand(sc, TRUE);
            if (nilai && json_object_has_member(nilai, kunci.c_str())) {
                std::string teks = jstr(nilai, kunci.c_str());
                if (!teks.empty())
                    gtk_text_buffer_set_text(
                        gtk_text_view_get_buffer(GTK_TEXT_VIEW(w)), teks.c_str(), -1);
            }
            GtkWidget *l = gtk_label_new(label.c_str());
            gtk_widget_set_halign(l, GTK_ALIGN_START);
            gtk_widget_set_valign(l, GTK_ALIGN_START);
            GtkStyleContext *lc = gtk_widget_get_style_context(l);
            gtk_style_context_add_class(lc, "dim");
            gtk_grid_attach(GTK_GRID(grid), l, 0, baris, 1, 1);
            gtk_grid_attach(GTK_GRID(grid), sc, 1, baris, 1, 1);
            ctrls_.push_back({nama, fitur, kunci, tipe, w, nullptr});
            ++baris;
            continue;
        } else if (tipe == "tile") {
            GtkWidget *e = nullptr;
            w = kisi_tile(kunci, k, nilai, &e);
            GtkWidget *l = gtk_label_new(label.c_str());
            gtk_widget_set_halign(l, GTK_ALIGN_START);
            gtk_widget_set_valign(l, GTK_ALIGN_START);
            GtkStyleContext *lc = gtk_widget_get_style_context(l);
            gtk_style_context_add_class(lc, "dim");
            gtk_grid_attach(GTK_GRID(grid), l, 0, baris, 1, 1);
            gtk_grid_attach(GTK_GRID(grid), w, 1, baris, 1, 1);
            ctrls_.push_back({nama, fitur, kunci, tipe, e, nullptr});
            ++baris;
            continue;
        } else {
            w = gtk_entry_new();
            gtk_widget_set_hexpand(w, TRUE);
            gtk_entry_set_placeholder_text(
                GTK_ENTRY(w), tipe == "item" ? "ID item, mis. 964" : "");
            if (nilai && json_object_has_member(nilai, kunci.c_str())) {
                std::string teks;
                if (tipe == "item") {
                    teks = std::to_string(jint(nilai, kunci.c_str()));
                    if (teks == "0") teks.clear();
                } else {
                    teks = jstr(nilai, kunci.c_str());
                }
                if (!teks.empty()) gtk_entry_set_text(GTK_ENTRY(w), teks.c_str());
            }
        }

        GtkWidget *l = gtk_label_new(label.c_str());
        gtk_widget_set_halign(l, GTK_ALIGN_START);
        GtkStyleContext *lc = gtk_widget_get_style_context(l);
        gtk_style_context_add_class(lc, "dim");
        gtk_grid_attach(GTK_GRID(grid), l, 0, baris, 1, 1);
        gtk_grid_attach(GTK_GRID(grid), w, 1, baris, 1, 1);
        ctrls_.push_back({nama, fitur, kunci, tipe, w, nullptr});
        ++baris;
    }
    gtk_box_pack_start(GTK_BOX(isi), card("Pengaturan", grid), FALSE, FALSE, 0);

    GtkWidget *kosong = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    gtk_widget_set_vexpand(kosong, TRUE);
    gtk_box_pack_start(GTK_BOX(isi), kosong, TRUE, TRUE, 0);

    halaman_fitur_[nama] = scroll;
    gtk_stack_add_named(GTK_STACK(detail_stack_), scroll, nama.c_str());
    // GtkStack hanya memilih child yang visible; halaman dibuat setelah
    // window di-show, jadi harus di-show di sini.
    gtk_widget_show_all(scroll);
}

void App::refresh_detail_schema() {
    if (!detail_stack_ || aktif_.empty()) return;
    JsonObject *o = get_obj("/api/features/schema?label=" + aktif_);
    if (!o) return;

    JsonObject *nilai = json_object_has_member(o, "nilai")
                            ? jobj(json_object_get_member(o, "nilai"))
                            : nullptr;

    if (!skema_siap_) {
        JsonArray *skema = json_object_has_member(o, "skema")
                               ? json_object_get_array_member(o, "skema")
                               : nullptr;
        guint n = skema ? json_array_get_length(skema) : 0;
        std::string pertama;
        for (guint i = 0; i < n; ++i) {
            JsonObject *k = jobj(json_array_get_element(skema, i));
            if (!k) continue;
            std::string nama = jstr(k, "nama");
            std::string fitur = jstr(k, "fitur");
            if (nama.empty()) continue;
            if (pertama.empty()) pertama = nama;
            JsonArray *kontrol = json_object_has_member(k, "kontrol")
                                     ? json_object_get_array_member(k, "kontrol")
                                     : nullptr;
            JsonObject *isi = (nilai && json_object_has_member(nilai, fitur.c_str()))
                                  ? jobj(json_object_get_member(nilai, fitur.c_str()))
                                  : nullptr;
            build_feature_page(nama, jstr(k, "keterangan"), fitur, kontrol, isi);
        }
        skema_siap_ = true;
        build_sidebar(pertama);
    }
    // status nyala/mati tiap fitur
    JsonObject *aktif = json_object_has_member(o, "aktif")
                            ? jobj(json_object_get_member(o, "aktif"))
                            : nullptr;
    if (aktif) {
        for (auto &kv : kunci_fitur_) {
            GtkWidget *note = static_cast<GtkWidget *>(
                g_object_get_data(G_OBJECT(detail_stack_), kv.second.c_str()));
            if (!note) continue;
            bool on = jbool(aktif, kv.second.c_str());
            gtk_label_set_text(GTK_LABEL(note), on ? "● aktif" : "○ mati");
            GtkStyleContext *c = gtk_widget_get_style_context(note);
            gtk_style_context_remove_class(c, "ok");
            gtk_style_context_remove_class(c, "dim");
            gtk_style_context_add_class(c, on ? "ok" : "dim");
        }
    }
    json_object_unref(o);
}

// Nilai semua kontrol satu halaman fitur sebagai opts JSON.
std::string App::opts_fitur(const std::string &fitur) {
    std::string out = "{";
    bool pertama = true;
    for (auto &c : ctrls_) {
        if (c.fitur != fitur || !c.w) continue;
        if (c.tipe == "tombol" || c.tipe == "teks_panjang") {
            if (c.tipe == "teks_panjang") {
                GtkTextBuffer *b = gtk_text_view_get_buffer(GTK_TEXT_VIEW(c.w));
                GtkTextIter s0, s1;
                gtk_text_buffer_get_bounds(b, &s0, &s1);
                gchar *teks = gtk_text_buffer_get_text(b, &s0, &s1, FALSE);
                if (!pertama) out += ",";
                out += "\"" + c.kunci + "\":\"" + jesc(teks ? teks : "") + "\"";
                g_free(teks);
                pertama = false;
            }
            continue;
        }
        std::string key = c.kunci;
        std::string val;
        if (c.tipe == "toggle") {
            val = gtk_switch_get_active(GTK_SWITCH(c.w)) ? "true" : "false";
        } else if (c.tipe == "angka" || c.tipe == "pecahan") {
            double v = gtk_spin_button_get_value(GTK_SPIN_BUTTON(c.w));
            char b[48];
            if (c.tipe == "pecahan")
                std::snprintf(b, sizeof b, "%.3f", v);
            else
                std::snprintf(b, sizeof b, "%ld", static_cast<long>(v));
            val = b;
        } else if (c.tipe == "pilihan") {
            gchar *akt = gtk_combo_box_text_get_active_text(GTK_COMBO_BOX_TEXT(c.w));
            val = "\"" + jesc(akt ? akt : "") + "\"";
            g_free(akt);
        } else if (c.tipe == "tile") {
            std::string tiles = isi_entry(c.w);
            std::string arr;
            size_t i = 0;
            while (i < tiles.size()) {
                while (i < tiles.size() &&
                       !std::isdigit(static_cast<unsigned char>(tiles[i])))
                    ++i;
                if (i >= tiles.size()) break;
                long x = std::strtol(tiles.c_str() + i, nullptr, 10);
                while (i < tiles.size() &&
                       std::isdigit(static_cast<unsigned char>(tiles[i])))
                    ++i;
                size_t j = i;
                while (j < tiles.size() && (tiles[j] == ' ' || tiles[j] == ',')) ++j;
                std::string ys;
                while (j < tiles.size() &&
                       std::isdigit(static_cast<unsigned char>(tiles[j]))) {
                    ys += tiles[j];
                    ++j;
                }
                if (ys.empty()) break;
                if (!arr.empty()) arr += ",";
                arr += "{\"x\":" + std::to_string(x) + ",\"y\":" + ys + "}";
                i = j;
            }
            if (c.kunci == "target_tiles") key = "target_tile";
            val = "[" + arr + "]";
        } else if (c.tipe == "item") {
            val = std::to_string(std::atol(isi_entry(c.w).c_str()));
        } else {
            val = "\"" + jesc(isi_entry(c.w)) + "\"";
        }
        if (!pertama) out += ",";
        out += "\"" + key + "\":" + val;
        pertama = false;
    }
    out += "}";
    return out;
}

void App::simpan_fitur(const std::string &halaman, bool nyalakan) {
    if (aktif_.empty() || halaman.empty()) return;
    auto it = kunci_fitur_.find(halaman);
    std::string kunci = (it != kunci_fitur_.end()) ? it->second : halaman;

    std::string body = "{\"label\":\"" + jesc(aktif_) + "\",\"feature\":\"" +
                       jesc(kunci) + "\",\"action\":\"" +
                       (nyalakan ? "start" : "atur") + "\",\"opts\":" +
                       opts_fitur(kunci) + "}";
    std::string err;
    if (!post_ok("/api/feature", body, &err)) append_console("[mod] " + err);
}

void App::on_detail_row(GtkListBox *, GtkListBoxRow *row, gpointer self) {
    auto *a = static_cast<App *>(self);
    if (!row || !a->detail_stack_) return;
    const char *f = static_cast<const char *>(g_object_get_data(G_OBJECT(row), "fitur"));
    if (!f) return;
    if (a->halaman_fitur_.count(f))
        gtk_stack_set_visible_child_name(GTK_STACK(a->detail_stack_), f);
}

void App::on_fitur_simpan(GtkButton *b, gpointer self) {
    auto *a = static_cast<App *>(self);
    const char *f = static_cast<const char *>(g_object_get_data(G_OBJECT(b), "fitur"));
    if (f) a->simpan_fitur(f, false);
}

void App::on_fitur_start(GtkButton *b, gpointer self) {
    auto *a = static_cast<App *>(self);
    const char *f = static_cast<const char *>(g_object_get_data(G_OBJECT(b), "fitur"));
    if (f) a->simpan_fitur(f, true);
}

void App::on_fitur_stop(GtkButton *b, gpointer self) {
    auto *a = static_cast<App *>(self);
    const char *f = static_cast<const char *>(g_object_get_data(G_OBJECT(b), "fitur"));
    if (!f || a->aktif_.empty()) return;
    auto it = a->kunci_fitur_.find(f);
    std::string kunci = (it != a->kunci_fitur_.end()) ? it->second : f;
    std::string err;
    a->post_ok("/api/feature",
               "{\"label\":\"" + jesc(a->aktif_) + "\",\"feature\":\"" +
                   jesc(kunci) + "\",\"action\":\"stop\"}",
               &err);
}

void App::on_replay_aksi(GtkButton *b, gpointer self) {
    auto *a = static_cast<App *>(self);
    const char *f = static_cast<const char *>(g_object_get_data(G_OBJECT(b), "fitur"));
    const char *aksi = static_cast<const char *>(g_object_get_data(G_OBJECT(b), "aksi"));
    if (!f || !aksi || a->aktif_.empty()) return;
    auto it = a->kunci_fitur_.find(f);
    std::string kunci = (it != a->kunci_fitur_.end()) ? it->second : f;
    std::string err;
    a->post_ok("/api/feature",
               "{\"label\":\"" + jesc(a->aktif_) + "\",\"feature\":\"" +
                   jesc(kunci) + "\",\"action\":\"" + jesc(aksi) +
                   "\",\"opts\":" + a->opts_fitur(kunci) + "}",
               &err);
}

// --------------------------------------------------------------- peta ---
GdkPixbuf *App::sprite(int id) {
    if (id <= 0) return nullptr;
    auto it = sprite_cache_.find(id);
    if (it != sprite_cache_.end()) return it->second;
    Resp r = http_.get("/api/sprite?id=" + std::to_string(id));
    GdkPixbuf *pb = nullptr;
    if (r.ok() && !r.body.empty()) {
        GdkPixbufLoader *l = gdk_pixbuf_loader_new();
        if (gdk_pixbuf_loader_write(l, reinterpret_cast<const guchar *>(r.body.data()),
                                    r.body.size(), nullptr) &&
            gdk_pixbuf_loader_close(l, nullptr)) {
            // pixbuf baru ada setelah loader ditutup
            pb = gdk_pixbuf_loader_get_pixbuf(l);
            if (pb) g_object_ref(pb);
        } else {
            gdk_pixbuf_loader_close(l, nullptr);
        }
        g_object_unref(l);
    }
    sprite_cache_[id] = pb;
    return pb;
}

gboolean App::on_map_motion(GtkWidget *w, GdkEventMotion *ev, gpointer self) {
    auto *a = static_cast<App *>(self);
    double S = a->peta_S_ > 0 ? a->peta_S_ : 32;
    int hx = static_cast<int>((ev->x - a->peta_offx_) / S);
    int hy = static_cast<int>((ev->y - a->peta_offy_) / S);
    if (hx == a->hover_x_ && hy == a->hover_y_) return FALSE;
    a->hover_x_ = hx;
    a->hover_y_ = hy;
    if (a->map_note_) {
        const App::MTile *t = nullptr;
        for (auto &m : a->peta_tiles_)
            if (m.x == hx && m.y == hy) { t = &m; break; }
        char buf[320];
        if (t) {
            std::snprintf(buf, sizeof buf, "(%d,%d)  %s%s%s  ·  latar %d",
                          hx, hy,
                          t->nama.empty() ? "—" : t->nama.c_str(),
                          t->seed ? (t->ready ? "  ·  SIAP PANEN" : "  ·  bibit") : "",
                          "", t->bg);
        } else {
            std::snprintf(buf, sizeof buf, "(%d,%d)  kosong", hx, hy);
        }
        gtk_label_set_text(GTK_LABEL(a->map_note_), buf);
    }
    gtk_widget_queue_draw(w);
    return FALSE;
}

gboolean App::on_map_draw(GtkWidget *w, cairo_t *cr, gpointer self) {
    auto *a = static_cast<App *>(self);
    GtkAllocation al{};
    gtk_widget_get_allocation(w, &al);
    // pas-kan seluruh dunia ke viewport, jangan lebih dari 32 px
    double sx = al.width > 0 ? static_cast<double>(al.width) / a->peta_w_ : 32;
    double sy = al.height > 0 ? static_cast<double>(al.height) / a->peta_h_ : 32;
    double S = std::min(std::min(sx, sy), 32.0);
    if (S < 1) S = 1;
    a->peta_S_ = S;
    // pusatkan peta di dalam viewport
    a->peta_offx_ = (al.width - a->peta_w_ * S) / 2.0;
    a->peta_offy_ = (al.height - a->peta_h_ * S) / 2.0;
    cairo_translate(cr, a->peta_offx_, a->peta_offy_);

    // latar papan kosong
    cairo_set_source_rgb(cr, 0.055, 0.066, 0.086);
    cairo_paint(cr);

    // kisi halus
    cairo_set_source_rgba(cr, 1, 1, 1, 0.04);
    cairo_set_line_width(cr, 1);
    double wpx = a->peta_w_ * S, hpx = a->peta_h_ * S;
    if (S >= 6) {   // kisi hanya berguna kalau tile cukup besar
        for (int x = 0; x <= a->peta_w_; ++x) {
            cairo_move_to(cr, x * S + .5, 0);
            cairo_line_to(cr, x * S + .5, hpx);
        }
        for (int y = 0; y <= a->peta_h_; ++y) {
            cairo_move_to(cr, 0, y * S + .5);
            cairo_line_to(cr, wpx, y * S + .5);
        }
        cairo_stroke(cr);
    }

    // tile: latar dulu, lalu blok di atasnya
    for (auto &t : a->peta_tiles_) {
        double px = t.x * S, py = t.y * S;
        if (t.bg) {
            GdkPixbuf *pb = a->sprite(t.bg);
            if (pb) {
                cairo_save(cr);
                cairo_translate(cr, px, py);
                cairo_scale(cr, S / 32.0, S / 32.0);
                gdk_cairo_set_source_pixbuf(cr, pb, 0, 0);
                cairo_rectangle(cr, 0, 0, 32, 32);
                cairo_fill(cr);
                cairo_restore(cr);
            } else {
                cairo_set_source_rgb(cr, 0.13, 0.15, 0.18);
                cairo_rectangle(cr, px, py, S, S);
                cairo_fill(cr);
            }
        }
    }
    for (auto &t : a->peta_tiles_) {
        double px = t.x * S, py = t.y * S;
        if (!t.fg) continue;
        GdkPixbuf *pb = a->sprite(t.fg);
        if (pb) {
            cairo_save(cr);
            cairo_translate(cr, px, py);
            cairo_scale(cr, S / 32.0, S / 32.0);
            gdk_cairo_set_source_pixbuf(cr, pb, 0, 0);
            cairo_rectangle(cr, 0, 0, 32, 32);
            cairo_fill(cr);
            cairo_restore(cr);
        } else {
            cairo_set_source_rgb(cr, 0.35, 0.28, 0.2);
            cairo_rectangle(cr, px, py, S, S);
            cairo_fill(cr);
        }
        if (S >= 8 && t.ready) {  // tanda siap panen
            cairo_set_source_rgba(cr, 0.25, 0.73, 0.31, 0.9);
            cairo_arc(cr, px + S - S * 0.16, py + S * 0.16, S * 0.11, 0, 6.2832);
            cairo_fill(cr);
        } else if (S >= 8 && t.seed) {
            cairo_set_source_rgba(cr, 0.82, 0.6, 0.13, 0.9);
            cairo_arc(cr, px + S - S * 0.16, py + S * 0.16, S * 0.11, 0, 6.2832);
            cairo_fill(cr);
        }
    }

    // sorotan tile di bawah kursor
    if (a->hover_x_ >= 0 && a->hover_x_ < a->peta_w_ &&
        a->hover_y_ >= 0 && a->hover_y_ < a->peta_h_) {
        cairo_set_source_rgba(cr, 0.9, 0.28, 0.3, 0.85);
        cairo_set_line_width(cr, 2);
        cairo_rectangle(cr, a->hover_x_ * S + 1, a->hover_y_ * S + 1, S - 2, S - 2);
        cairo_stroke(cr);
    }

    // pemain
    for (auto &p : a->peta_players_) {
        double px = p.x * S, py = p.y * S;
        cairo_set_source_rgba(cr, p.lokal ? 0.9 : 0.35, p.lokal ? 0.28 : 0.6,
                              p.lokal ? 0.3 : 0.95, 0.85);
        cairo_rectangle(cr, px + 2, py + 2, std::max(4.0, S - 4),
                        std::max(4.0, S - 4));
        cairo_fill(cr);
        if (S >= 15) {
            cairo_set_source_rgb(cr, 1, 1, 1);
            cairo_select_font_face(cr, "DejaVu Sans", CAIRO_FONT_SLANT_NORMAL,
                                   CAIRO_FONT_WEIGHT_BOLD);
            cairo_set_font_size(cr, std::max(7.0, S * 0.28));
            cairo_move_to(cr, px + S * 0.12, py + S * 0.78);
            cairo_show_text(cr, p.lokal ? "aku" : p.nama.substr(0, 4).c_str());
        }
    }
    (void)w;
    return FALSE;
}


// ----------------------------- kisi tile (tile_select ala deltaX) ---
// deltaX: count x count kotak polos, indeks = baris*count + kolom, dipusatkan
// ke player. Bukan peta dunia, bukan dialog.

std::pair<int, int> App::tile_player() const {
    for (auto &p : peta_players_)
        if (p.lokal) return {p.x, p.y};
    if (peta_w_ > 0) return {peta_w_ / 2, peta_h_ / 2};
    return {0, 0};
}

namespace {

void warnai_sel(App::GridSel *g, GtkWidget *b, int idx) {
    GtkStyleContext *c = gtk_widget_get_style_context(b);
    gtk_style_context_remove_class(c, "tileoff");
    gtk_style_context_remove_class(c, "tileon");
    gtk_style_context_add_class(c, g->aktif.count(idx) ? "tileon" : "tileoff");
}

}  // namespace

void App::isi_grid(GridSel *g) {
    auto p = tile_player();
    int sisi = g->sisi, tgh = sisi / 2;
    std::string teks;
    int n = 0;
    for (int i : g->aktif) {
        int r = i / sisi, c = i % sisi;
        if (!teks.empty()) teks += " ";
        teks += std::to_string(p.first + c - tgh) + "," +
                std::to_string(p.second + r - tgh);
        ++n;
    }
    if (g->entry) gtk_entry_set_text(GTK_ENTRY(g->entry), teks.c_str());
    if (g->info) {
        char buf[32];
        std::snprintf(buf, sizeof buf, "%d/%d", n, sisi * sisi);
        gtk_label_set_text(GTK_LABEL(g->info), buf);
    }
}

void App::on_grid_cell(GtkButton *b, gpointer self) {
    auto *g = static_cast<GridSel *>(self);
    int idx = GPOINTER_TO_INT(g_object_get_data(G_OBJECT(b), "idx"));
    if (g->aktif.count(idx)) g->aktif.erase(idx);
    else g->aktif.insert(idx);
    warnai_sel(g, GTK_WIDGET(b), idx);
    auto *a = static_cast<App *>(g_object_get_data(G_OBJECT(b), "app"));
    if (a) a->isi_grid(g);
}

GtkWidget *App::kisi_tile(const std::string &kunci, JsonObject *k, JsonObject *nilai,
                          GtkWidget **entry_out) {
    // penyimpan: entry tersembunyi berisi "x,y x,y" absolut
    GtkWidget *entry = gtk_entry_new();
    gtk_widget_set_no_show_all(entry, TRUE);
    gtk_widget_set_visible(entry, FALSE);

    auto *g = new GridSel();
    g->sisi = json_object_has_member(k, "count")
                  ? static_cast<int>(jint(k, "count")) : 5;
    if (g->sisi < 1) g->sisi = 1;
    g->entry = entry;

    GtkWidget *boks = gtk_box_new(GTK_ORIENTATION_VERTICAL, 4);
    GtkWidget *kepala = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    g->info = gtk_label_new("");
    GtkStyleContext *ic = gtk_widget_get_style_context(g->info);
    gtk_style_context_add_class(ic, "dim");
    gtk_box_pack_start(GTK_BOX(kepala), entry, TRUE, TRUE, 0);
    gtk_box_pack_end(GTK_BOX(kepala), g->info, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(boks), kepala, FALSE, FALSE, 0);

    g->kisi = gtk_grid_new();
    gtk_grid_set_row_spacing(GTK_GRID(g->kisi), 3);
    gtk_grid_set_column_spacing(GTK_GRID(g->kisi), 3);
    // 11x11 harus muat di kolom kanan (~250 px) tanpa menggulir
    int sel_px = g->sisi >= 9 ? 20 : 26;
    for (int r = 0; r < g->sisi; ++r) {
        for (int c = 0; c < g->sisi; ++c) {
            GtkWidget *sel = gtk_button_new();
            gtk_widget_set_size_request(sel, sel_px, sel_px);
            gtk_button_set_relief(GTK_BUTTON(sel), GTK_RELIEF_NONE);
            g_object_set_data(G_OBJECT(sel), "idx", GINT_TO_POINTER(r * g->sisi + c));
            g_object_set_data(G_OBJECT(sel), "app", this);
            GtkStyleContext *sc = gtk_widget_get_style_context(sel);
            gtk_style_context_add_class(sc, "tileoff");
            g_signal_connect(sel, "clicked", G_CALLBACK(on_grid_cell), g);
            gtk_grid_attach(GTK_GRID(g->kisi), sel, c, r, 1, 1);
            g->sel.push_back(sel);
        }
    }
    gtk_box_pack_start(GTK_BOX(boks), g->kisi, FALSE, FALSE, 0);

    // muat nilai awal: array {x,y} absolut -> indeks relatif player
    if (nilai && json_object_has_member(nilai, kunci.c_str())) {
        JsonNode *vn = json_object_get_member(nilai, kunci.c_str());
        JsonArray *arr = (vn && JSON_NODE_HOLDS_ARRAY(vn)) ? json_node_get_array(vn) : nullptr;
        guint m = arr ? json_array_get_length(arr) : 0;
        auto p = tile_player();
        int tgh = g->sisi / 2;
        for (guint j = 0; j < m; ++j) {
            JsonObject *t2 = jobj(json_array_get_element(arr, j));
            if (!t2) continue;
            int c = static_cast<int>(jint(t2, "x")) - p.first + tgh;
            int r = static_cast<int>(jint(t2, "y")) - p.second + tgh;
            if (c < 0 || r < 0 || c >= g->sisi || r >= g->sisi) continue;
            g->aktif.insert(r * g->sisi + c);
        }
    }
    for (int r = 0; r < g->sisi; ++r)
        for (int c = 0; c < g->sisi; ++c)
            warnai_sel(g, g->sel[r * g->sisi + c], r * g->sisi + c);
    isi_grid(g);   // isi entry + penghitung "n/total"

    g_object_set_data_full(G_OBJECT(boks), "grid", g, [](gpointer p) {
        delete static_cast<GridSel *>(p);
    });
    if (entry_out) *entry_out = entry;
    return boks;
}

}  // namespace lucifer
