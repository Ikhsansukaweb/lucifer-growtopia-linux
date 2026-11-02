// lucifer/ui.cpp — implementasi GUI Lucifer Linux.
//
// Prinsip: GUI ini tipis. Semua logika Growtopia tetap di Python
// (lucifer.web). Aplikasi menyalakan server lokal lalu bicara JSON lewat
// HTTP loopback, jadi tak ada protokol yang ditulis dua kali.

#include "ui.h"

#include <gtk/gtk.h>

#include <csignal>
#include <unistd.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

namespace lucifer {

// ---------------------------------------------------------------- JSON ---
std::string jstr(JsonObject *o, const char *k) {
    if (!o || !json_object_has_member(o, k)) return "";
    JsonNode *n = json_object_get_member(o, k);
    if (!n || JSON_NODE_HOLDS_NULL(n)) return "";
    if (JSON_NODE_HOLDS_VALUE(n)) {
        GType t = json_node_get_value_type(n);
        if (t == G_TYPE_STRING) return json_node_get_string(n);
        if (t == G_TYPE_BOOLEAN) return json_node_get_boolean(n) ? "true" : "false";
        if (t == G_TYPE_INT64) {
            char b[32];
            std::snprintf(b, sizeof b, "%" G_GINT64_FORMAT, json_node_get_int(n));
            return b;
        }
        if (t == G_TYPE_DOUBLE) {
            char b[32];
            std::snprintf(b, sizeof b, "%.0f", json_node_get_double(n));
            return b;
        }
    }
    return "";
}

long jint(JsonObject *o, const char *k) {
    if (!o || !json_object_has_member(o, k)) return 0;
    JsonNode *n = json_object_get_member(o, k);
    if (!n || !JSON_NODE_HOLDS_VALUE(n)) return 0;
    GType t = json_node_get_value_type(n);
    if (t == G_TYPE_INT64) return static_cast<long>(json_node_get_int(n));
    if (t == G_TYPE_DOUBLE) return static_cast<long>(json_node_get_double(n));
    if (t == G_TYPE_STRING) return std::atol(json_node_get_string(n));
    if (t == G_TYPE_BOOLEAN) return json_node_get_boolean(n) ? 1 : 0;
    return 0;
}

bool jbool(JsonObject *o, const char *k) {
    if (!o || !json_object_has_member(o, k)) return false;
    JsonNode *n = json_object_get_member(o, k);
    if (!n || !JSON_NODE_HOLDS_VALUE(n)) return false;
    GType t = json_node_get_value_type(n);
    if (t == G_TYPE_BOOLEAN) return json_node_get_boolean(n);
    if (t == G_TYPE_INT64) return json_node_get_int(n) != 0;
    return false;
}

JsonObject *jobj(JsonNode *n) {
    return (n && JSON_NODE_HOLDS_OBJECT(n)) ? json_node_get_object(n) : nullptr;
}

// ----------------------------------------------------------------- CSS ---
static const char *kCss = R"CSS(
* {
  font-family: Cantarell, "Noto Sans", "DejaVu Sans", sans-serif;
  font-size: 13px;
  -gtk-outline-radius: 6px;
}
window, .background { background-color: #0c0e11; color: #e7e9ee; }

headerbar {
  background-image: none;
  background-color: #101318;
  border-bottom: 1px solid #232931;
  box-shadow: none;
  min-height: 46px;
  padding: 0 8px;
}
headerbar .title { font-weight: 700; letter-spacing: .6px; color: #e7e9ee; }
headerbar .subtitle { color: #79828f; font-size: 11px; }

headerbar button.titlebutton {
  background-image: none;
  background-color: transparent;
  border: none;
  border-radius: 6px;
  box-shadow: none;
  color: #8b93a1;
  padding: 4px 8px;
  min-width: 18px;
  min-height: 18px;
}
headerbar button.titlebutton:hover { background-color: #232931; color: #e7e9ee; }
headerbar button.titlebutton.close:hover { background-color: #e5484d; color: #ffffff; }

#brand { font-weight: 800; font-size: 15px; letter-spacing: 2px; color: #e5484d; }
#brand span { color: #e7e9ee; font-weight: 600; letter-spacing: .4px; }
#statuspill {
  background-color: #171b21;
  border: 1px solid #262c35;
  border-radius: 99px;
  padding: 3px 12px;
  font-size: 11.5px;
  color: #8b93a1;
}
.status-online { color: #3fb950; }

/* ---- notebook ---- */
notebook > header {
  background-color: #101318;
  border-bottom: 1px solid #232931;
  border-radius: 0;
  padding: 0 6px;
}
notebook > header > tabs > tab {
  background-color: transparent;
  background-image: none;
  border: none;
  border-radius: 0;
  border-bottom: 2px solid transparent;
  box-shadow: none;
  padding: 9px 18px;
  color: #79828f;
  font-weight: 600;
  font-size: 12.5px;
}
notebook > header > tabs > tab:hover { color: #c8ced8; background-color: #15191f; }
notebook > header > tabs > tab:checked {
  color: #ffffff;
  border-bottom: 2px solid #e5484d;
  background-color: #15191f;
}
notebook stack { background-color: #0c0e11; }

/* ---- kartu ---- */
.pane { padding: 14px; }
.card {
  background-color: #14171c;
  border: 1px solid #232931;
  border-radius: 10px;
  padding: 14px 16px;
}
.cardtitle {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1.4px;
  color: #6f7885;
}

/* ---- tombol ---- */
button {
  background-image: none;
  background-color: #1b1f26;
  border: 1px solid #2a313a;
  border-radius: 7px;
  color: #d7dbe2;
  padding: 5px 13px;
  font-weight: 600;
  font-size: 12.5px;
  box-shadow: none;
  text-shadow: none;
}
button:hover { background-color: #222831; border-color: #37404b; color: #ffffff; }
button:active { background-color: #171b21; }
button.primary { background-color: #e5484d; border-color: #e5484d; color: #ffffff; }
button.primary:hover { background-color: #f05a5f; border-color: #f05a5f; }
button.ghost { background-color: transparent; border-color: #2a313a; color: #9aa3b0; }
button.ghost:hover { color: #ffffff; background-color: #1b1f26; }
button.danger { background-color: transparent; border-color: #57262a; color: #f85149; }
button.danger:hover { background-color: #2a1417; border-color: #f85149; }
button.flat { background-color: transparent; border: none; padding: 4px 8px; }

entry, searchentry {
  background-image: none;
  background-color: #101318;
  border: 1px solid #262c35;
  border-radius: 7px;
  color: #e7e9ee;
  padding: 5px 10px;
  min-height: 22px;
  box-shadow: none;
}
entry:focus, searchentry:focus { border-color: #e5484d; }
entry placeholder { color: #5c6673; }

/* ---- tabel ---- */
treeview.view {
  background-color: #101318;
  color: #cfd5de;
  border: none;
}
treeview.view:hover { background-color: #161b22; }
treeview.view:selected { background-color: #25303d; color: #ffffff; }
treeview.view header button {
  background-color: #171b21;
  border: none;
  border-bottom: 1px solid #262c35;
  border-right: 1px solid #1d232b;
  border-radius: 0;
  color: #7b8493;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .8px;
  padding: 6px 8px;
}
treeview.view header button:hover { color: #ffffff; }
scrolledwindow { border: 1px solid #232931; border-radius: 8px; background-color: #101318; }

/* ---- teks ---- */
textview, textview text {
  background-color: #0a0c0f;
  color: #c3cbd6;
  font-family: "DejaVu Sans Mono", monospace;
  font-size: 12px;
}
.dim { color: #6f7885; font-size: 11.5px; }
.mono { font-family: "DejaVu Sans Mono", monospace; }
.pill {
  border-radius: 99px;
  padding: 1px 9px;
  font-size: 10.5px;
  font-weight: 700;
}
.ok { color: #3fb950; }
.warn { color: #d29922; }
.bad { color: #f85149; }

.empty-title { font-size: 14px; font-weight: 700; color: #6f7885; }

separator { background-color: #232931; min-height: 1px; }

switch {
  background-color: #232931;
  border-radius: 99px;
  border: 1px solid #2f3742;
  min-width: 42px;
  min-height: 22px;
}
switch:checked { background-color: #e5484d; border-color: #e5484d; }
switch slider { background-color: #6f7885; border-radius: 99px; min-width: 18px; min-height: 18px; }
switch:checked slider { background-color: #ffffff; }

progressbar trough { background-color: #171b21; border-radius: 99px; min-height: 6px; }
progressbar progress { background-color: #e5484d; border-radius: 99px; min-height: 6px; }

.dialog { background-color: #14171c; }
.dialog .dim { color: #79828f; }
)CSS";

// --------------------------------------------------------------- App ---
App::App(std::string base, bool spawn, std::string repo, int port)
    : http_(std::move(base)), spawn_(spawn), repo_(std::move(repo)), port_(port) {}

void App::apply_css() {
    GtkCssProvider *p = gtk_css_provider_new();
    GError *err = nullptr;
    gtk_css_provider_load_from_data(p, kCss, -1, &err);
    if (err) {
        std::fprintf(stderr, "CSS: %s\n", err->message);
        g_error_free(err);
    }
    gtk_style_context_add_provider_for_screen(
        gdk_screen_get_default(), GTK_STYLE_PROVIDER(p),
        GTK_STYLE_PROVIDER_PRIORITY_APPLICATION);
    g_object_unref(p);
}

GtkWidget *App::toolbtn(const char *label, GCallback cb, const char *cls) {
    GtkWidget *b = gtk_button_new_with_label(label);
    if (cls) {
        GtkStyleContext *c = gtk_widget_get_style_context(b);
        for (auto tok = std::strtok(strdup(cls), " "); tok; tok = std::strtok(nullptr, " "))
            gtk_style_context_add_class(c, tok);
    }
    if (cb) g_signal_connect(b, "clicked", cb, this);
    return b;
}

GtkWidget *App::card(const char *title, GtkWidget *child) {
    GtkWidget *box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 10);
    GtkStyleContext *c = gtk_widget_get_style_context(box);
    gtk_style_context_add_class(c, "card");
    if (title) {
        GtkWidget *l = gtk_label_new(title);
        gtk_widget_set_halign(l, GTK_ALIGN_START);
        GtkStyleContext *lc = gtk_widget_get_style_context(l);
        gtk_style_context_add_class(lc, "cardtitle");
        gtk_box_pack_start(GTK_BOX(box), l, FALSE, FALSE, 0);
    }
    gtk_box_pack_start(GTK_BOX(box), child, TRUE, TRUE, 0);
    return box;
}

GtkWidget *App::field(const char *label, GtkWidget *w) {
    GtkWidget *b = gtk_box_new(GTK_ORIENTATION_VERTICAL, 4);
    GtkWidget *l = gtk_label_new(label);
    gtk_widget_set_halign(l, GTK_ALIGN_START);
    GtkStyleContext *c = gtk_widget_get_style_context(l);
    gtk_style_context_add_class(c, "dim");
    gtk_box_pack_start(GTK_BOX(b), l, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(b), w, FALSE, FALSE, 0);
    return b;
}

// ------------------------------------------------------------- header ---
GtkWidget *App::make_header() {
    GtkWidget *hb = gtk_header_bar_new();
    gtk_header_bar_set_show_close_button(GTK_HEADER_BAR(hb), TRUE);
    // tombol jendela di kanan, gaya Windows seperti screenshot Lucifer
    gtk_header_bar_set_decoration_layout(GTK_HEADER_BAR(hb), ":minimize,maximize,close");

    GtkWidget *brand = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    GtkWidget *logo = gtk_label_new("LUCIFER");
    gtk_widget_set_name(logo, "brand");
    GtkWidget *ver = gtk_label_new("Linux 2.88");
    GtkStyleContext *vc = gtk_widget_get_style_context(ver);
    gtk_style_context_add_class(vc, "dim");
    gtk_box_pack_start(GTK_BOX(brand), logo, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(brand), ver, FALSE, FALSE, 0);
    gtk_header_bar_set_custom_title(GTK_HEADER_BAR(hb), brand);

    header_status_ = gtk_label_new("●  offline");
    gtk_widget_set_name(header_status_, "statuspill");
    gtk_header_bar_pack_end(GTK_HEADER_BAR(hb), header_status_);

    header_sub_ = gtk_label_new("0 bot");
    GtkStyleContext *sc = gtk_widget_get_style_context(header_sub_);
    gtk_style_context_add_class(sc, "dim");
    gtk_header_bar_pack_end(GTK_HEADER_BAR(hb), header_sub_);
    return hb;
}

// --------------------------------------------------------------- Bots ---
static void add_col(GtkWidget *view, const char *title, int idx, int width) {
    GtkCellRenderer *r = gtk_cell_renderer_text_new();
    g_object_set(r, "xpad", 8, "ypad", 5, nullptr);
    GtkTreeViewColumn *c = gtk_tree_view_column_new_with_attributes(
        title, r, "text", idx, nullptr);
    gtk_tree_view_column_set_resizable(c, TRUE);
    gtk_tree_view_column_set_min_width(c, width);
    gtk_tree_view_append_column(GTK_TREE_VIEW(view), c);
}

GtkWidget *App::tab_bots() {
    GtkWidget *v = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    GtkStyleContext *pc = gtk_widget_get_style_context(v);
    gtk_style_context_add_class(pc, "pane");

    GtkWidget *bar = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
    gtk_box_pack_start(GTK_BOX(bar), toolbtn("+ Tambah Bot", G_CALLBACK(on_add_bot), "primary"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(bar), toolbtn("Connect", G_CALLBACK(on_connect), "ghost"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(bar), toolbtn("Disconnect", G_CALLBACK(on_disconnect), "ghost"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(bar), toolbtn("Hapus", G_CALLBACK(on_del_bot), "danger"), FALSE, FALSE, 0);

    GtkWidget *spacer = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    gtk_widget_set_hexpand(spacer, TRUE);
    gtk_box_pack_start(GTK_BOX(bar), spacer, TRUE, TRUE, 0);

    search_bots_ = gtk_search_entry_new();
    gtk_entry_set_placeholder_text(GTK_ENTRY(search_bots_), "Cari bot…");
    gtk_widget_set_size_request(search_bots_, 220, -1);
    g_signal_connect(search_bots_, "search-changed", G_CALLBACK(on_refresh), this);
    gtk_box_pack_start(GTK_BOX(bar), search_bots_, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(bar), toolbtn("Segarkan", G_CALLBACK(on_refresh), "ghost"), FALSE, FALSE, 0);

    gtk_box_pack_start(GTK_BOX(v), bar, FALSE, FALSE, 0);

    GtkWidget *body = gtk_paned_new(GTK_ORIENTATION_HORIZONTAL);
    gtk_paned_set_position(GTK_PANED(body), 190);
    gtk_box_pack_start(GTK_BOX(v), body, TRUE, TRUE, 12);

    // ---- panel kiri ala Lucifer ----
    GtkWidget *kiri = gtk_box_new(GTK_ORIENTATION_VERTICAL, 6);
    gtk_widget_set_size_request(kiri, 178, -1);
    GtkStyleContext *kc = gtk_widget_get_style_context(kiri);
    gtk_style_context_add_class(kc, "card");

    const char *judul_kiri = "AKSI";
    GtkWidget *lk = gtk_label_new(judul_kiri);
    gtk_widget_set_halign(lk, GTK_ALIGN_START);
    GtkStyleContext *lkc = gtk_widget_get_style_context(lk);
    gtk_style_context_add_class(lkc, "cardtitle");
    gtk_box_pack_start(GTK_BOX(kiri), lk, FALSE, FALSE, 0);

    GtkWidget *b_all = toolbtn("Pilih Semua", G_CALLBACK(on_refresh), "ghost");
    gtk_widget_set_hexpand(b_all, TRUE);
    gtk_box_pack_start(GTK_BOX(kiri), b_all, FALSE, FALSE, 0);

    GtkWidget *multi = gtk_check_button_new_with_label("Multi-Select");
    GtkStyleContext *mc = gtk_widget_get_style_context(multi);
    gtk_style_context_add_class(mc, "dim");
    gtk_box_pack_start(GTK_BOX(kiri), multi, FALSE, FALSE, 0);

    GtkWidget *sep = gtk_separator_new(GTK_ORIENTATION_HORIZONTAL);
    gtk_box_pack_start(GTK_BOX(kiri), sep, FALSE, FALSE, 4);

    const char *judul_akun = "AKUN";
    GtkWidget *la = gtk_label_new(judul_akun);
    gtk_widget_set_halign(la, GTK_ALIGN_START);
    GtkStyleContext *lac = gtk_widget_get_style_context(la);
    gtk_style_context_add_class(lac, "cardtitle");
    gtk_box_pack_start(GTK_BOX(kiri), la, FALSE, FALSE, 0);

    GtkWidget *b_add = toolbtn("Tambah Bot", G_CALLBACK(on_add_bot), "ghost");
    gtk_widget_set_hexpand(b_add, TRUE);
    gtk_box_pack_start(GTK_BOX(kiri), b_add, FALSE, FALSE, 0);
    GtkWidget *b_del = toolbtn("Hapus Bot", G_CALLBACK(on_del_bot), "ghost");
    gtk_widget_set_hexpand(b_del, TRUE);
    gtk_box_pack_start(GTK_BOX(kiri), b_del, FALSE, FALSE, 0);

    GtkWidget *fill = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    gtk_widget_set_vexpand(fill, TRUE);
    gtk_box_pack_start(GTK_BOX(kiri), fill, TRUE, TRUE, 0);
    gtk_paned_pack1(GTK_PANED(body), kiri, FALSE, FALSE);

    // ---- tabel ----
    GtkWidget *kanan = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    gtk_widget_set_margin_start(kanan, 4);
    gtk_paned_pack2(GTK_PANED(body), kanan, TRUE, FALSE);

    store_bots_ = gtk_list_store_new(9, G_TYPE_STRING, G_TYPE_STRING, G_TYPE_STRING,
                                     G_TYPE_STRING, G_TYPE_STRING, G_TYPE_STRING,
                                     G_TYPE_STRING, G_TYPE_STRING, G_TYPE_STRING);
    view_bots_ = gtk_tree_view_new_with_model(GTK_TREE_MODEL(store_bots_));
    gtk_tree_view_set_grid_lines(GTK_TREE_VIEW(view_bots_), GTK_TREE_VIEW_GRID_LINES_NONE);
    const char *judul[] = {"BOT", "NAMA", "LEVEL", "PING", "STATUS", "PROXY",
                           "DUNIA", "POSISI", "GEMS"};
    const int lebar[] = {110, 130, 52, 58, 110, 170, 120, 70, 62};
    for (int i = 0; i < 9; ++i) add_col(view_bots_, judul[i], i, lebar[i]);
    g_signal_connect(view_bots_, "cursor-changed", G_CALLBACK(on_bot_row), this);

    GtkWidget *scroll = gtk_scrolled_window_new(nullptr, nullptr);
    gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(scroll),
                                   GTK_POLICY_AUTOMATIC, GTK_POLICY_AUTOMATIC);
    gtk_container_add(GTK_CONTAINER(scroll), view_bots_);
    gtk_box_pack_start(GTK_BOX(kanan), scroll, TRUE, TRUE, 0);

    bots_bar_ = gtk_label_new("Online 0   ·   Offline 0   ·   Total 0   ·   Gems 0");
    gtk_widget_set_halign(bots_bar_, GTK_ALIGN_START);
    GtkStyleContext *bc = gtk_widget_get_style_context(bots_bar_);
    gtk_style_context_add_class(bc, "dim");
    gtk_box_pack_start(GTK_BOX(kanan), bots_bar_, FALSE, FALSE, 8);
    return v;
}

// ------------------------------------------------------------ Console ---
GtkWidget *App::tab_console() {
    GtkWidget *v = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    GtkStyleContext *pc = gtk_widget_get_style_context(v);
    gtk_style_context_add_class(pc, "pane");

    GtkWidget *bar = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
    GtkWidget *lbl = gtk_label_new("Bot");
    GtkStyleContext *lc = gtk_widget_get_style_context(lbl);
    gtk_style_context_add_class(lc, "dim");
    gtk_box_pack_start(GTK_BOX(bar), lbl, FALSE, FALSE, 0);

    combo_console_bot_ = gtk_combo_box_text_new();
    gtk_widget_set_size_request(combo_console_bot_, 170, -1);
    gtk_box_pack_start(GTK_BOX(bar), combo_console_bot_, FALSE, FALSE, 0);

    GtkWidget *sp = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    gtk_widget_set_hexpand(sp, TRUE);
    gtk_box_pack_start(GTK_BOX(bar), sp, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(bar), toolbtn("Bersihkan", G_CALLBACK(on_clear_log), "ghost"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(v), bar, FALSE, FALSE, 0);

    view_console_ = gtk_text_view_new();
    gtk_text_view_set_editable(GTK_TEXT_VIEW(view_console_), FALSE);
    gtk_text_view_set_cursor_visible(GTK_TEXT_VIEW(view_console_), FALSE);
    gtk_text_view_set_wrap_mode(GTK_TEXT_VIEW(view_console_), GTK_WRAP_WORD_CHAR);
    gtk_text_view_set_left_margin(GTK_TEXT_VIEW(view_console_), 10);
    gtk_text_view_set_top_margin(GTK_TEXT_VIEW(view_console_), 8);
    GtkWidget *scroll = gtk_scrolled_window_new(nullptr, nullptr);
    gtk_container_add(GTK_CONTAINER(scroll), view_console_);
    gtk_box_pack_start(GTK_BOX(v), scroll, TRUE, TRUE, 12);

    GtkWidget *bar2 = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
    entry_cmd_ = gtk_entry_new();
    gtk_entry_set_placeholder_text(GTK_ENTRY(entry_cmd_),
                                   "say halo  ·  warp WORLD  ·  run skrip.lua");
    g_signal_connect(entry_cmd_, "activate", G_CALLBACK(on_cmd_enter), this);
    gtk_box_pack_start(GTK_BOX(bar2), entry_cmd_, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(bar2), toolbtn("Kirim", G_CALLBACK(on_send_cmd), "primary"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(v), bar2, FALSE, FALSE, 0);
    return v;
}

// ----------------------------------------------------------- Executor ---
GtkWidget *App::tab_executor() {
    GtkWidget *v = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    GtkStyleContext *pc = gtk_widget_get_style_context(v);
    gtk_style_context_add_class(pc, "pane");

    GtkWidget *bar = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
    entry_script_name_ = gtk_entry_new();
    gtk_entry_set_placeholder_text(GTK_ENTRY(entry_script_name_), "nama_skrip.lua");
    gtk_widget_set_size_request(entry_script_name_, 230, -1);
    gtk_box_pack_start(GTK_BOX(bar), entry_script_name_, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(bar), toolbtn("Baru", G_CALLBACK(on_new_script), "ghost"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(bar), toolbtn("Simpan", G_CALLBACK(on_save_script), "ghost"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(bar), toolbtn("Jalankan", G_CALLBACK(on_run_script), "primary"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(bar), toolbtn("Hapus", G_CALLBACK(on_del_script), "danger"), FALSE, FALSE, 0);

    GtkWidget *sp = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    gtk_widget_set_hexpand(sp, TRUE);
    gtk_box_pack_start(GTK_BOX(bar), sp, TRUE, TRUE, 0);
    exec_note_ = gtk_label_new("—");
    GtkStyleContext *nc = gtk_widget_get_style_context(exec_note_);
    gtk_style_context_add_class(nc, "dim");
    gtk_box_pack_start(GTK_BOX(bar), exec_note_, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(v), bar, FALSE, FALSE, 0);

    GtkWidget *paned = gtk_paned_new(GTK_ORIENTATION_HORIZONTAL);
    gtk_paned_set_position(GTK_PANED(paned), 260);
    gtk_box_pack_start(GTK_BOX(v), paned, TRUE, TRUE, 12);

    store_scripts_ = gtk_list_store_new(2, G_TYPE_STRING, G_TYPE_STRING);
    view_scripts_ = gtk_tree_view_new_with_model(GTK_TREE_MODEL(store_scripts_));
    add_col(view_scripts_, "SKRIP", 0, 150);
    add_col(view_scripts_, "BARIS", 1, 50);
    g_signal_connect(view_scripts_, "cursor-changed", G_CALLBACK(on_script_row), this);
    GtkWidget *sc1 = gtk_scrolled_window_new(nullptr, nullptr);
    gtk_container_add(GTK_CONTAINER(sc1), view_scripts_);
    gtk_paned_pack1(GTK_PANED(paned), sc1, TRUE, FALSE);

    editor_ = gtk_text_view_new();
    gtk_text_view_set_monospace(GTK_TEXT_VIEW(editor_), TRUE);
    gtk_text_view_set_left_margin(GTK_TEXT_VIEW(editor_), 10);
    gtk_text_view_set_top_margin(GTK_TEXT_VIEW(editor_), 8);
    GtkWidget *sc2 = gtk_scrolled_window_new(nullptr, nullptr);
    gtk_container_add(GTK_CONTAINER(sc2), editor_);
    gtk_paned_pack2(GTK_PANED(paned), sc2, TRUE, FALSE);
    return v;
}

// -------------------------------------------------------------- Proxy ---
GtkWidget *App::tab_proxy() {
    GtkWidget *v = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    GtkStyleContext *pc = gtk_widget_get_style_context(v);
    gtk_style_context_add_class(pc, "pane");

    GtkWidget *bar = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
    gtk_box_pack_start(GTK_BOX(bar), toolbtn("+ Tambah Proxy", G_CALLBACK(on_add_proxy), "primary"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(bar), toolbtn("Uji semua", G_CALLBACK(on_check_proxy), "ghost"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(bar), toolbtn("Hapus", G_CALLBACK(on_del_proxy), "danger"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(bar), toolbtn("Buang yang mati", G_CALLBACK(on_purge_proxy), "ghost"), FALSE, FALSE, 0);

    GtkWidget *sp = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    gtk_widget_set_hexpand(sp, TRUE);
    gtk_box_pack_start(GTK_BOX(bar), sp, TRUE, TRUE, 0);

    GtkWidget *lbl = gtk_label_new("Pakai untuk");
    GtkStyleContext *lc = gtk_widget_get_style_context(lbl);
    gtk_style_context_add_class(lc, "dim");
    gtk_box_pack_start(GTK_BOX(bar), lbl, FALSE, FALSE, 0);
    combo_proxy_bot_ = gtk_combo_box_text_new();
    gtk_widget_set_size_request(combo_proxy_bot_, 150, -1);
    gtk_box_pack_start(GTK_BOX(bar), combo_proxy_bot_, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(bar), toolbtn("Pasang", G_CALLBACK(on_use_proxy), "ghost"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(v), bar, FALSE, FALSE, 0);

    store_proxies_ = gtk_list_store_new(5, G_TYPE_STRING, G_TYPE_STRING,
                                        G_TYPE_STRING, G_TYPE_STRING, G_TYPE_STRING);
    view_proxies_ = gtk_tree_view_new_with_model(GTK_TREE_MODEL(store_proxies_));
    const char *judul[] = {"HOST", "PORT", "USER", "STATUS", "LATENSI"};
    const int lebar[] = {220, 80, 140, 190, 90};
    for (int i = 0; i < 5; ++i) add_col(view_proxies_, judul[i], i, lebar[i]);

    GtkWidget *scroll = gtk_scrolled_window_new(nullptr, nullptr);
    GtkWidget *overlay = gtk_overlay_new();
    gtk_container_add(GTK_CONTAINER(scroll), view_proxies_);
    gtk_container_add(GTK_CONTAINER(overlay), scroll);

    // empty state: tampil saat daftar kosong
    GtkWidget *kosong = gtk_box_new(GTK_ORIENTATION_VERTICAL, 6);
    gtk_widget_set_valign(kosong, GTK_ALIGN_CENTER);
    gtk_widget_set_halign(kosong, GTK_ALIGN_CENTER);
    GtkWidget *kt = gtk_label_new("Belum ada proxy");
    GtkWidget *ks = gtk_label_new("klik “+ Tambah Proxy”, satu entri per baris");
    GtkStyleContext *k1 = gtk_widget_get_style_context(kt);
    GtkStyleContext *k2 = gtk_widget_get_style_context(ks);
    gtk_style_context_add_class(k1, "empty-title");
    gtk_style_context_add_class(k2, "dim");
    gtk_box_pack_start(GTK_BOX(kosong), kt, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(kosong), ks, FALSE, FALSE, 0);
    gtk_overlay_add_overlay(GTK_OVERLAY(overlay), kosong);
    proxy_kosong_ = kosong;

    gtk_box_pack_start(GTK_BOX(v), overlay, TRUE, TRUE, 12);

    proxy_note_ = gtk_label_new("Total proxy: 0   ·   0 hidup");
    gtk_widget_set_halign(proxy_note_, GTK_ALIGN_START);
    GtkStyleContext *nc = gtk_widget_get_style_context(proxy_note_);
    gtk_style_context_add_class(nc, "dim");
    gtk_box_pack_start(GTK_BOX(v), proxy_note_, FALSE, FALSE, 0);
    return v;
}

// ------------------------------------------------------------- Switch ---
GtkWidget *App::tab_switch() {
    GtkWidget *v = gtk_box_new(GTK_ORIENTATION_VERTICAL, 14);
    GtkStyleContext *pc = gtk_widget_get_style_context(v);
    gtk_style_context_add_class(pc, "pane");

    auto kartu = [this](const char *judul, const char *ket, const char *kunci,
                        GtkWidget **simpan) {
        GtkWidget *row = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 12);
        GtkWidget *teks = gtk_box_new(GTK_ORIENTATION_VERTICAL, 2);
        GtkWidget *t = gtk_label_new(judul);
        gtk_widget_set_halign(t, GTK_ALIGN_START);
        GtkWidget *k = gtk_label_new(ket);
        gtk_widget_set_halign(k, GTK_ALIGN_START);
        GtkStyleContext *kc = gtk_widget_get_style_context(k);
        gtk_style_context_add_class(kc, "dim");
        gtk_box_pack_start(GTK_BOX(teks), t, FALSE, FALSE, 0);
        gtk_box_pack_start(GTK_BOX(teks), k, FALSE, FALSE, 0);
        gtk_box_pack_start(GTK_BOX(row), teks, TRUE, TRUE, 0);

        GtkWidget *sw = gtk_switch_new();
        gtk_widget_set_valign(sw, GTK_ALIGN_CENTER);
        g_object_set_data_full(G_OBJECT(sw), "kunci", g_strdup(kunci), g_free);
        g_signal_connect(sw, "state-set", G_CALLBACK(on_switch), this);
        gtk_box_pack_start(GTK_BOX(row), sw, FALSE, FALSE, 0);
        *simpan = sw;
        return row;
    };

    GtkWidget *grid = gtk_grid_new();
    gtk_grid_set_row_spacing(GTK_GRID(grid), 10);
    gtk_grid_set_column_spacing(GTK_GRID(grid), 10);

    struct Item { const char *judul; const char *ket; const char *kunci; GtkWidget **slot; };
    Item daftar[] = {
        {"Auto Farm", "panen, tanam, pukul otomatis", "autofarm", &sw_autofarm_},
        {"Auto Collect", "ambil item jatuh di radius", "autocollect", &sw_collect_},
        {"Spammer", "kirim teks berulang", "spammer", &sw_spam_},
        {"Auto Drop", "buang item saat inventori penuh", "autodrop", &sw_drop_},
        {"Path Finder", "jalan otomatis ke koordinat", "pathfinder", &sw_path_},
        {"Replay", "rekam & putar ulang gerakan", "replay", &sw_replay_},
    };
    for (int i = 0; i < 6; ++i) {
        GtkWidget *kartu_w = card(nullptr, kartu(daftar[i].judul,
                                                 daftar[i].ket,
                                                 daftar[i].kunci,
                                                 daftar[i].slot));
        gtk_widget_set_hexpand(kartu_w, TRUE);
        gtk_grid_attach(GTK_GRID(grid), kartu_w, i % 3, i / 3, 1, 1);
    }
    gtk_box_pack_start(GTK_BOX(v), grid, FALSE, FALSE, 0);

    switch_note_ = gtk_label_new("pilih bot di tab Bots dulu");
    gtk_widget_set_halign(switch_note_, GTK_ALIGN_START);
    GtkStyleContext *nc = gtk_widget_get_style_context(switch_note_);
    gtk_style_context_add_class(nc, "dim");
    gtk_box_pack_start(GTK_BOX(v), switch_note_, FALSE, FALSE, 0);
    return v;
}

// ----------------------------------------------------------- Database ---
GtkWidget *App::tab_database() {
    GtkWidget *v = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    GtkStyleContext *pc = gtk_widget_get_style_context(v);
    gtk_style_context_add_class(pc, "pane");

    GtkWidget *bar = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
    GtkWidget *cari = gtk_search_entry_new();
    gtk_entry_set_placeholder_text(GTK_ENTRY(cari), "Cari item (nama atau ID)…");
    gtk_widget_set_size_request(cari, 300, -1);
    g_signal_connect(cari, "search-changed", G_CALLBACK(on_item_search), this);
    gtk_box_pack_start(GTK_BOX(bar), cari, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(v), bar, FALSE, FALSE, 0);

    store_items_ = gtk_list_store_new(5, G_TYPE_STRING, G_TYPE_STRING,
                                      G_TYPE_STRING, G_TYPE_STRING, G_TYPE_STRING);
    view_items_ = gtk_tree_view_new_with_model(GTK_TREE_MODEL(store_items_));
    const char *judul[] = {"ID", "NAMA", "RARITY", "TIPE", "GROW"};
    const int lebar[] = {80, 300, 80, 80, 90};
    for (int i = 0; i < 5; ++i) add_col(view_items_, judul[i], i, lebar[i]);
    GtkWidget *scroll = gtk_scrolled_window_new(nullptr, nullptr);
    gtk_container_add(GTK_CONTAINER(scroll), view_items_);
    gtk_box_pack_start(GTK_BOX(v), scroll, TRUE, TRUE, 12);

    items_note_ = gtk_label_new("—");
    gtk_widget_set_halign(items_note_, GTK_ALIGN_START);
    GtkStyleContext *nc = gtk_widget_get_style_context(items_note_);
    gtk_style_context_add_class(nc, "dim");
    gtk_box_pack_start(GTK_BOX(v), items_note_, FALSE, FALSE, 0);
    return v;
}

// ----------------------------------------------------------- Settings ---
GtkWidget *App::tab_settings() {
    GtkWidget *v = gtk_box_new(GTK_ORIENTATION_VERTICAL, 12);
    GtkStyleContext *pc = gtk_widget_get_style_context(v);
    gtk_style_context_add_class(pc, "pane");

    GtkWidget *grid = gtk_grid_new();
    gtk_grid_set_row_spacing(GTK_GRID(grid), 8);
    gtk_grid_set_column_spacing(GTK_GRID(grid), 24);

    auto baris = [&grid](int r, const char *k, const char *awal, GtkWidget **simpan) {
        GtkWidget *lk = gtk_label_new(k);
        gtk_widget_set_halign(lk, GTK_ALIGN_START);
        GtkStyleContext *c = gtk_widget_get_style_context(lk);
        gtk_style_context_add_class(c, "dim");
        GtkWidget *lv = gtk_label_new(awal);
        gtk_widget_set_halign(lv, GTK_ALIGN_START);
        gtk_grid_attach(GTK_GRID(grid), lk, 0, r, 1, 1);
        gtk_grid_attach(GTK_GRID(grid), lv, 1, r, 1, 1);
        *simpan = lv;
    };
    baris(0, "Uptime", "—", &set_uptime_);
    baris(1, "Item dimuat", "—", &set_items_);
    baris(2, "Skrip", "—", &set_scripts_);
    baris(3, "Akun", "—", &set_accounts_);
    baris(4, "Server lokal", "—", &set_url_);
    baris(5, "Versi", "Lucifer Linux 2.88", &set_versi_);
    baris(6, "Protokol", "225 · GT 5.58", &set_proto_);
    baris(7, "Folder data", "data/", &set_data_dir_);
    gtk_box_pack_start(GTK_BOX(v), card("Status backend", grid), FALSE, FALSE, 0);

    GtkWidget *aksi = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
    gtk_box_pack_start(GTK_BOX(aksi), toolbtn("Muat ulang data", G_CALLBACK(on_refresh), "primary"), FALSE, FALSE, 0);
    GtkWidget *ket = gtk_label_new("item, skrip, dan status ditarik ulang dari backend");
    gtk_widget_set_halign(ket, GTK_ALIGN_START);
    GtkStyleContext *kc = gtk_widget_get_style_context(ket);
    gtk_style_context_add_class(kc, "dim");
    gtk_box_pack_start(GTK_BOX(aksi), ket, FALSE, FALSE, 6);
    gtk_box_pack_start(GTK_BOX(v), card("Aksi", aksi), FALSE, FALSE, 0);
    return v;
}

// ----------------------------------------------------------------- UI ---
void App::build_ui() {
    apply_css();
    window_ = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    gtk_window_set_title(GTK_WINDOW(window_), "Lucifer Linux");
    gtk_window_set_default_size(GTK_WINDOW(window_), 1180, 720);
    gtk_window_set_titlebar(GTK_WINDOW(window_), make_header());
    g_signal_connect(window_, "destroy", G_CALLBACK(on_destroy), this);

    notebook_ = gtk_notebook_new();
    gtk_notebook_set_show_border(GTK_NOTEBOOK(notebook_), FALSE);
    gtk_container_add(GTK_CONTAINER(window_), notebook_);

    gtk_notebook_append_page(GTK_NOTEBOOK(notebook_), tab_bots(), gtk_label_new("Bots"));
    gtk_notebook_append_page(GTK_NOTEBOOK(notebook_), tab_console(), gtk_label_new("Console"));
    gtk_notebook_append_page(GTK_NOTEBOOK(notebook_), tab_executor(), gtk_label_new("Executor"));
    gtk_notebook_append_page(GTK_NOTEBOOK(notebook_), tab_proxy(), gtk_label_new("Proxy"));
    gtk_notebook_append_page(GTK_NOTEBOOK(notebook_), tab_switch(), gtk_label_new("Switch"));
    gtk_notebook_append_page(GTK_NOTEBOOK(notebook_), tab_database(), gtk_label_new("Database"));
    gtk_notebook_append_page(GTK_NOTEBOOK(notebook_), tab_settings(), gtk_label_new("Settings"));
    gtk_widget_show_all(window_);
    gtk_notebook_set_current_page(GTK_NOTEBOOK(notebook_), tab_awal_);
}

void App::start_backend() {
    std::string py = repo_ + "/.venv/bin/python";
    if (access(py.c_str(), X_OK) != 0) py = "python3";
    std::vector<std::string> argv = {
        py, "-m", "lucifer.cli", "web", "--port", std::to_string(port_)};
    std::vector<char *> cargv;
    for (auto &a : argv) cargv.push_back(const_cast<char *>(a.c_str()));
    cargv.push_back(nullptr);

    GError *err = nullptr;
    gchar **envp = g_get_environ();
    gboolean ok = g_spawn_async(
        repo_.c_str(), cargv.data(), envp,
        static_cast<GSpawnFlags>(G_SPAWN_SEARCH_PATH | G_SPAWN_DO_NOT_REAP_CHILD),
        nullptr, nullptr, &child_pid_, &err);
    g_strfreev(envp);
    if (!ok) {
        if (err) g_error_free(err);
        child_pid_ = 0;
    }
}

int App::run(int argc, char **argv) {
    gtk_init(&argc, &argv);
    build_ui();
    if (spawn_) start_backend();
    g_timeout_add(600, &App::bootstrap, this);
    g_timeout_add(1500, &App::on_tick, this);
    gtk_main();
    if (child_pid_ > 0) ::kill(child_pid_, SIGTERM);
    return 0;
}

}  // namespace lucifer

// ---------------------------------------------------------------- main ---
int main(int argc, char **argv) {
    std::string url = "http://127.0.0.1:8787";
    int port = 8787;
    bool spawn = true;
    std::string repo = ".";

    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "--url" && i + 1 < argc) {
            url = argv[++i];
            spawn = false;
        } else if (a == "--port" && i + 1 < argc) {
            port = std::atoi(argv[++i]);
            url = "http://127.0.0.1:" + std::to_string(port);
        } else if (a == "--repo" && i + 1 < argc) {
            repo = argv[++i];
        } else if (a == "--no-spawn") {
            spawn = false;
        } else if (a == "-h" || a == "--help") {
            std::printf(
                "lucifer-desktop — GUI native Lucifer Linux\n"
                "  --repo DIR    folder repo (cari .venv & modul lucifer)\n"
                "  --port N      port dashboard lokal (default 8787)\n"
                "  --url URL     pakai server yang sudah jalan (tanpa spawn)\n"
                "  --no-spawn    jangan nyalakan backend\n");
            return 0;
        }
    }
    lucifer::App app(url, spawn, repo, port);
    if (const char *tab = std::getenv("LUCIFER_TAB")) {
    
        app.tab_awal(std::atoi(tab));
    }
    return app.run(argc, argv);
}
