// lucifer/ui.h — kerangka GUI Lucifer Linux (GTK3).
#pragma once

#include <gtk/gtk.h>
#include <json-glib/json-glib.h>
#include <gdk-pixbuf/gdk-pixbuf.h>

#include <map>
#include <set>
#include <string>
#include <vector>

#include "http.h"

namespace lucifer {

// Palet & tipografi. Satu tempat, dipakai CSS dan kode.
struct Theme {
    static constexpr const char *bg = "#0c0e11";
    static constexpr const char *panel = "#14171c";
    static constexpr const char *panel2 = "#191d23";
    static constexpr const char *line = "#262c35";
    static constexpr const char *text = "#e7e9ee";
    static constexpr const char *dim = "#8b93a1";
    static constexpr const char *accent = "#e5484d";
    static constexpr const char *ok = "#3fb950";
    static constexpr const char *warn = "#d29922";
    static constexpr const char *bad = "#f85149";
    static constexpr const char *font_ui =
        "Cantarell, Noto Sans, DejaVu Sans, sans-serif";
    static constexpr const char *font_mono =
        "DejaVu Sans Mono, Noto Sans Mono, monospace";
};

// Helpers JSON (null-safe).
std::string jstr(JsonObject *o, const char *k);
long jint(JsonObject *o, const char *k);
bool jbool(JsonObject *o, const char *k);
JsonObject *jobj(JsonNode *n);

class App {
public:
    App(std::string base, bool spawn, std::string repo, int port);
    int run(int argc, char **argv);
    void tab_awal(int i) { tab_awal_ = i; }
    void bot_awal(std::string s) { bot_awal_ = std::move(s); auto_bot_ = bot_awal_; }

    // Dipakai juga oleh helper pemilih tile (fungsi bebas di data.cpp).
    GdkPixbuf *sprite(int id);

    struct MTile { int x, y, fg, bg; bool seed, ready; std::string nama; };
    struct MPlayer { int x, y; bool lokal; std::string nama; };

    // Kisi tile gaya deltaX `tile_select`: count x count kotak polos,
    // indeks = baris*count + kolom, dipusatkan ke player.
    struct GridSel {
        int sisi = 5;
        std::set<int> aktif;
        GtkWidget *entry = nullptr;
        GtkWidget *info = nullptr;
        GtkWidget *kisi = nullptr;
        std::vector<GtkWidget *> sel;   // tombol per indeks
    };

    // Dialog pemilih tile: grid kotak yang bisa diklik.

private:
    // -- pembangunan --
    void build_ui();
    void apply_css();
    void start_backend();
    GtkWidget *make_header();
    GtkWidget *tab_bots();
    GtkWidget *tab_executor();
    GtkWidget *tab_proxy();
    GtkWidget *tab_database();
    GtkWidget *tab_settings();
    GtkWidget *detail_page();
    GtkWidget *detail_fitur();
    void build_sidebar(const std::string &pilih);
    void build_feature_page(const std::string &nama, const std::string &ket,
                            const std::string &fitur, JsonArray *kontrol,
                            JsonObject *nilai);
    GtkWidget *detail_chat();
    GtkWidget *detail_console();
    GtkWidget *detail_map();
    GtkWidget *detail_inv();
    GtkWidget *detail_info();

    // -- util widget --
    GtkWidget *toolbtn(const char *label, GCallback cb, const char *cls = nullptr);
    GtkWidget *card(const char *title, GtkWidget *child);
    GtkWidget *field(const char *label, GtkWidget *w);

    // -- data --
    void refresh();
    void refresh_bots();
    void refresh_scripts();
    void refresh_items(const std::string &q);
    void refresh_proxies();
    void refresh_detail();
    void refresh_detail_schema();
    void refresh_detail_chat();
    void refresh_detail_map();
    void refresh_detail_inv();

    void set_console(const std::string &teks);
    void append_console(const std::string &teks);
    std::string selected_bot();
    std::string selected_script();
    std::string selected_proxy_key();
    std::string proxy_host_port();
    std::string opts_fitur(const std::string &fitur);
    void simpan_fitur(const std::string &fitur, bool nyalakan);

    bool post_ok(const std::string &path, const std::string &json, std::string *err);
    JsonObject *get_obj(const std::string &path);

    // -- callback --
    static void on_add_bot(GtkButton *, gpointer);
    static void on_del_bot(GtkButton *, gpointer);
    static void on_connect(GtkButton *, gpointer);
    static void on_disconnect(GtkButton *, gpointer);
    static void on_refresh(GtkButton *, gpointer);
    static void on_clear_log(GtkButton *, gpointer);
    static void on_bot_row(GtkTreeView *, gpointer);
    static void on_send_cmd(GtkButton *, gpointer);
    static void on_cmd_enter(GtkEntry *, gpointer);
    static void on_send_chat(GtkButton *, gpointer);
    static void on_chat_enter(GtkEntry *, gpointer);
    static void on_simpan_autofarm(GtkButton *, gpointer);
    static void on_fitur_simpan(GtkButton *, gpointer);
    static void on_fitur_start(GtkButton *, gpointer);
    static void on_fitur_stop(GtkButton *, gpointer);
    static void on_replay_aksi(GtkButton *, gpointer);
    static void on_detail_row(GtkListBox *, GtkListBoxRow *, gpointer);
    static gboolean on_map_draw(GtkWidget *, cairo_t *, gpointer);
    static gboolean on_map_motion(GtkWidget *, GdkEventMotion *, gpointer);
    static void on_grid_cell(GtkButton *, gpointer);
    GtkWidget *kisi_tile(const std::string &kunci, JsonObject *k, JsonObject *nilai,
                         GtkWidget **entry_out);
    void isi_grid(GridSel *g);
    std::pair<int, int> tile_player() const;
    static void on_open_bot(GtkTreeView *, gpointer);
    static void on_back_bots(GtkButton *, gpointer);
    static void on_token_hp(GtkButton *, gpointer);
    static void on_save_script(GtkButton *, gpointer);
    static void on_run_script(GtkButton *, gpointer);
    static void on_del_script(GtkButton *, gpointer);
    static void on_new_script(GtkButton *, gpointer);
    static void on_script_row(GtkTreeView *, gpointer);
    static void on_script_search(GtkSearchEntry *, gpointer);
    static void on_item_search(GtkSearchEntry *, gpointer);
    static void on_add_proxy(GtkButton *, gpointer);
    static void on_del_proxy(GtkButton *, gpointer);
    static void on_check_proxy(GtkButton *, gpointer);
    static void on_use_proxy(GtkButton *, gpointer);
    static void on_purge_proxy(GtkButton *, gpointer);
    static gboolean on_tick(gpointer);
    static gboolean bootstrap(gpointer);
    static void on_destroy(GtkWidget *, gpointer);

    void dialog_add_bot();
    void dialog_add_proxy();

    // -- state --
    Http http_;
    bool spawn_ = false;
    std::string repo_;
    int port_ = 8787;
    int child_pid_ = 0;
    long online_ = 0;
    int boot_tries_ = 0;
    int tab_awal_ = 0;
    std::string bot_awal_;
    std::string auto_bot_;
    std::string last_log_;

    GtkWidget *window_ = nullptr;
    GtkWidget *notebook_ = nullptr;
    GtkWidget *header_status_ = nullptr;
    GtkWidget *header_sub_ = nullptr;

    // bots
    GtkListStore *store_bots_ = nullptr;
    GtkWidget *view_bots_ = nullptr;
    GtkWidget *bots_bar_ = nullptr;
    GtkWidget *search_bots_ = nullptr;

    // detail bot
    std::string aktif_;              // label bot yang sedang dibuka
    GtkWidget *bot_stack_ = nullptr;  // GtkStack: daftar <-> detail
    GtkWidget *detail_judul_ = nullptr;
    GtkWidget *detail_sub_ = nullptr;
    GtkWidget *detail_notebook_ = nullptr;
    GtkWidget *detail_stack_ = nullptr;
    GtkWidget *detail_list_ = nullptr;
    GtkWidget *view_chat_ = nullptr;
    GtkWidget *entry_chat_ = nullptr;
    GtkWidget *view_console_ = nullptr;
    GtkWidget *entry_cmd_ = nullptr;
    GtkListStore *store_map_ = nullptr;
    GtkWidget *view_map_ = nullptr;
    GtkWidget *map_note_ = nullptr;
    GtkListStore *store_inv_ = nullptr;
    GtkWidget *view_inv_ = nullptr;
    GtkWidget *inv_note_ = nullptr;
    GtkWidget *detail_info_ = nullptr;
    int chat_lines_ = 0;
    int console_lines_ = 0;
    int tick_n_ = 0;

    // executor
    GtkListStore *store_scripts_ = nullptr;
    GtkWidget *view_scripts_ = nullptr;
    GtkWidget *editor_ = nullptr;
    GtkWidget *entry_script_name_ = nullptr;
    GtkWidget *exec_note_ = nullptr;

    // proxy
    GtkListStore *store_proxies_ = nullptr;
    GtkWidget *view_proxies_ = nullptr;
    GtkWidget *proxy_note_ = nullptr;
    GtkWidget *proxy_kosong_ = nullptr;
    GtkWidget *combo_proxy_bot_ = nullptr;

    // fitur (di dalam detail bot): sidebar <-> halaman
    struct Ctrl {
        std::string halaman;   // label di sidebar ("Autofarm")
        std::string fitur;     // kunci API ("autofarm")
        std::string kunci;     // nama atribut ("punch_count")
        std::string tipe;
        GtkWidget *w = nullptr;
        JsonObject *obj = nullptr;  // objek fitur di server (untuk baca nilai)
    };
    std::vector<Ctrl> ctrls_;
    std::map<std::string, GtkWidget *> halaman_fitur_;
    std::map<std::string, std::string> kunci_fitur_;  // label -> kunci API
    bool skema_siap_ = false;

    // peta
    std::vector<MTile> peta_tiles_;
    std::vector<MPlayer> peta_players_;
    int peta_w_ = 0, peta_h_ = 0;
    int hover_x_ = -1, hover_y_ = -1;
    double peta_S_ = 32;   // ukuran tile di layar (menyesuaikan viewport)
    double peta_offx_ = 0, peta_offy_ = 0;   // geser peta supaya tengah
    GtkWidget *peta_area_ = nullptr;
    GtkWidget *peta_scroll_ = nullptr;
    std::map<int, GdkPixbuf *> sprite_cache_;

    // database
    GtkListStore *store_items_ = nullptr;
    GtkWidget *view_items_ = nullptr;
    GtkWidget *items_note_ = nullptr;

    // settings
    GtkWidget *set_uptime_ = nullptr;
    GtkWidget *set_items_ = nullptr;
    GtkWidget *set_scripts_ = nullptr;
    GtkWidget *set_accounts_ = nullptr;
    GtkWidget *set_url_ = nullptr;
    GtkWidget *set_versi_ = nullptr;
    GtkWidget *set_proto_ = nullptr;
    GtkWidget *set_data_dir_ = nullptr;
};

}  // namespace lucifer
