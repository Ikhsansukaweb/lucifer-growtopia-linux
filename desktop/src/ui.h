// lucifer/ui.h — kerangka GUI Lucifer Linux (GTK3).
#pragma once

#include <gtk/gtk.h>
#include <json-glib/json-glib.h>

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

private:
    // -- pembangunan --
    void build_ui();
    void apply_css();
    void start_backend();
    GtkWidget *make_header();
    GtkWidget *tab_bots();
    GtkWidget *tab_console();
    GtkWidget *tab_executor();
    GtkWidget *tab_proxy();
    GtkWidget *tab_switch();
    GtkWidget *tab_database();
    GtkWidget *tab_settings();

    // -- util widget --
    GtkWidget *toolbtn(const char *label, GCallback cb, const char *cls = nullptr);
    GtkWidget *card(const char *title, GtkWidget *child);
    GtkWidget *field(const char *label, GtkWidget *w);

    // -- data --
    void refresh();
    void refresh_bots();
    void refresh_logs();
    void refresh_scripts();
    void refresh_items(const std::string &q);
    void refresh_proxies();
    void refresh_switch();
    void refresh_console();

    void set_console(const std::string &teks);
    void append_console(const std::string &teks);
    std::string selected_bot();
    std::string selected_script();
    std::string selected_proxy_key();
    std::string proxy_host_port();

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
    static gboolean on_switch(GtkSwitch *, gboolean, gpointer);
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

    // console
    GtkWidget *view_console_ = nullptr;
    GtkWidget *combo_console_bot_ = nullptr;
    GtkWidget *entry_cmd_ = nullptr;

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

    // switch
    GtkWidget *sw_autofarm_ = nullptr;
    GtkWidget *sw_collect_ = nullptr;
    GtkWidget *sw_spam_ = nullptr;
    GtkWidget *sw_drop_ = nullptr;
    GtkWidget *sw_path_ = nullptr;
    GtkWidget *sw_replay_ = nullptr;
    GtkWidget *switch_note_ = nullptr;
    bool switch_sync_ = false;

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
