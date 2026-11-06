// lucifer/ui.cpp — implementasi GUI Lucifer Linux.
//
// Prinsip: GUI ini tipis. Semua logika Growtopia tetap di Python
// (lucifer.web). Aplikasi menyalakan server lokal lalu bicara JSON lewat
// HTTP loopback, jadi tak ada protokol yang ditulis dua kali.

#include "ui.h"

#include <gtk/gtk.h>

#include <csignal>
#include <unistd.h>

#include <gdk-pixbuf/gdk-pixbuf.h>

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
#botjudul { font-size: 15px; font-weight: 800; color: #ffffff; }
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
.invoff { background-color: #161a20; border: 1px solid #262d36; border-radius: 8px; }
.invon { background-color: #1d2129; border: 1px solid #e01b2e; border-radius: 8px; }
.invjml { color: #ffffff; font-size: 11px; font-weight: 800;
          background-color: rgba(0,0,0,0.65); padding: 0 3px; border-radius: 3px; }
.mapbingkai { background-color: #0b0e12; border: 1px solid #222831; border-radius: 10px; }
button.tileoff { background-color: #1b2027; border: 1px solid #2c333d; border-radius: 3px; min-width: 0; min-height: 0; padding: 0; }
button.tileoff:hover { background-color: #232a33; }
button.tileon { background-color: #e01b2e; border: 1px solid #e01b2e; border-radius: 3px; min-width: 0; min-height: 0; padding: 0; }
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
  background-image: none;
  background-color: #232931;
  border-radius: 99px;
  border: 1px solid #2f3742;
  min-width: 44px;
  min-height: 24px;
  box-shadow: none;
}
switch:checked { background-image: none; background-color: #e5484d; border-color: #e5484d; }
switch slider {
  background-image: none;
  background-color: #59616e;
  border: none;
  border-radius: 99px;
  min-width: 18px;
  min-height: 18px;
  box-shadow: none;
}
switch:checked slider { background-image: none; background-color: #ffffff; }

progressbar trough { background-color: #171b21; border-radius: 99px; min-height: 6px; }
progressbar progress { background-color: #e5484d; border-radius: 99px; min-height: 6px; }

/* ---- sidebar mod menu ---- */
list.navrow, row.navrow { background-color: transparent; }
/* judul grup (Automation / World): tidak bisa dipilih, jadi jangan
   diberi hover/sorotan seperti baris fitur. */
list > row:nth-child(n) label.sectitle {
  color: #6b7482;
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.7px;
}
row:selected label.sectitle { color: #6b7482; }
list { background-color: transparent; }
list > row {
  border-radius: 7px;
  border: 1px solid transparent;
  color: #9aa3b0;
  font-size: 12.5px;
  font-weight: 600;
}
list > row:hover { background-color: #1b1f26; color: #ffffff; }
list > row:selected {
  background-color: #24181b;
  border: 1px solid #4a2226;
  color: #ff8c90;
}
scrolledwindow.plain { border: none; background-color: transparent; }
spinbutton { background-image: none; background-color: #101318;
  border: 1px solid #262c35; border-radius: 7px; color: #e7e9ee; }
spinbutton:focus { border-color: #e5484d; }
combobox button { background-color: #101318; border: 1px solid #262c35;
  border-radius: 7px; color: #e7e9ee; }

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
    bot_stack_ = gtk_stack_new();
    gtk_stack_set_transition_type(GTK_STACK(bot_stack_),
                                  GTK_STACK_TRANSITION_TYPE_CROSSFADE);
    gtk_stack_set_transition_duration(GTK_STACK(bot_stack_), 140);

    // ================= halaman 1: daftar bot =================
    GtkWidget *v = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    GtkStyleContext *pc = gtk_widget_get_style_context(v);
    gtk_style_context_add_class(pc, "pane");

    GtkWidget *bar = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
    gtk_box_pack_start(GTK_BOX(bar), toolbtn("+ Tambah Bot", G_CALLBACK(on_add_bot), "primary"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(bar), toolbtn("Ambil Token HP", G_CALLBACK(on_token_hp), "ghost"), FALSE, FALSE, 0);
    GtkWidget *spacer = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    gtk_widget_set_hexpand(spacer, TRUE);
    gtk_box_pack_start(GTK_BOX(bar), spacer, TRUE, TRUE, 0);

    search_bots_ = gtk_search_entry_new();
    gtk_entry_set_placeholder_text(GTK_ENTRY(search_bots_), "Cari bot…");
    gtk_widget_set_size_request(search_bots_, 220, -1);
    g_signal_connect(search_bots_, "search-changed", G_CALLBACK(on_refresh), this);
    gtk_box_pack_start(GTK_BOX(bar), search_bots_, FALSE, FALSE, 0);
    header_sub_ = gtk_label_new("0 bot");
    gtk_style_context_add_class(gtk_widget_get_style_context(header_sub_), "dim");
    gtk_box_pack_start(GTK_BOX(bar), header_sub_, FALSE, FALSE, 6);
    header_status_ = gtk_label_new("â  offline");
    gtk_widget_set_name(header_status_, "statuspill");
    gtk_box_pack_start(GTK_BOX(bar), header_status_, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(bar), toolbtn("Segarkan", G_CALLBACK(on_refresh), "ghost"), FALSE, FALSE, 0);
    // Tanpa headerbar: Hyprland tidak memakai dekorasi server-side, jadi
    // tombol minimize/exit disediakan sendiri di toolbar.
    // Ikon simbolik, bukan karakter teks: font sistem sering tak punya
    // glyph "—"/"✕" sehingga tampil kotak tofu.
    GtkWidget *b_min = gtk_button_new_from_icon_name("window-minimize-symbolic",
                                                     GTK_ICON_SIZE_BUTTON);
    GtkWidget *b_close = gtk_button_new_from_icon_name("window-close-symbolic",
                                                       GTK_ICON_SIZE_BUTTON);
    gtk_style_context_add_class(gtk_widget_get_style_context(b_min), "ghost");
    gtk_style_context_add_class(gtk_widget_get_style_context(b_close), "danger");
    g_signal_connect(b_min, "clicked", G_CALLBACK(on_minimize), this);
    g_signal_connect(b_close, "clicked", G_CALLBACK(on_quit), this);
    gtk_box_pack_start(GTK_BOX(bar), b_min, FALSE, FALSE, 8);
    gtk_box_pack_start(GTK_BOX(bar), b_close, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(v), bar, FALSE, FALSE, 0);

    GtkWidget *body = gtk_paned_new(GTK_ORIENTATION_HORIZONTAL);
    gtk_paned_set_position(GTK_PANED(body), 258);
    gtk_box_pack_start(GTK_BOX(v), body, TRUE, TRUE, 12);

    // ---- panel kiri ala Lucifer ----
    GtkWidget *kiri = gtk_box_new(GTK_ORIENTATION_VERTICAL, 6);
    gtk_widget_set_size_request(kiri, -1, -1);
    GtkStyleContext *kc = gtk_widget_get_style_context(kiri);
    gtk_style_context_add_class(kc, "card");

    GtkWidget *lk = gtk_label_new("AKSI");
    gtk_widget_set_halign(lk, GTK_ALIGN_START);
    GtkStyleContext *lkc = gtk_widget_get_style_context(lk);
    gtk_style_context_add_class(lkc, "cardtitle");
    gtk_box_pack_start(GTK_BOX(kiri), lk, FALSE, FALSE, 0);

    GtkWidget *b_all = toolbtn("Pilih Semua", G_CALLBACK(on_pilih_semua), "ghost");
    gtk_widget_set_hexpand(b_all, TRUE);
    gtk_box_pack_start(GTK_BOX(kiri), b_all, FALSE, FALSE, 0);

    GtkWidget *multi = gtk_check_button_new_with_label("Multi-Select");
    GtkStyleContext *mc = gtk_widget_get_style_context(multi);
    gtk_style_context_add_class(mc, "dim");
    g_signal_connect(multi, "toggled", G_CALLBACK(on_multi_select), this);
    gtk_box_pack_start(GTK_BOX(kiri), multi, FALSE, FALSE, 0);

    gtk_box_pack_start(GTK_BOX(kiri), gtk_separator_new(GTK_ORIENTATION_HORIZONTAL),
                       FALSE, FALSE, 4);

    GtkWidget *lac0 = gtk_label_new("KONTROL");
    gtk_widget_set_halign(lac0, GTK_ALIGN_START);
    GtkStyleContext *lac0c = gtk_widget_get_style_context(lac0);
    gtk_style_context_add_class(lac0c, "cardtitle");
    gtk_box_pack_start(GTK_BOX(kiri), lac0, FALSE, FALSE, 0);

    GtkWidget *b_conn = toolbtn("Connect", G_CALLBACK(on_connect), "ghost");
    GtkWidget *b_disc = toolbtn("Disconnect", G_CALLBACK(on_disconnect), "ghost");
    GtkWidget *b_conn_all = toolbtn("Connect Semua", G_CALLBACK(on_connect_semua), "ghost");
    GtkWidget *b_disc_all = toolbtn("Disconnect Semua", G_CALLBACK(on_disconnect_semua), "ghost");
    // Dua kolom: panel kiri dulu setinggi > layar 768 sehingga tombol bawah
    // tidak kelihatan. Grid 2x2 memotong tinggi hampir separuh.
    GtkWidget *grid_kontrol = gtk_grid_new();
    gtk_grid_set_row_spacing(GTK_GRID(grid_kontrol), 6);
    gtk_grid_set_column_spacing(GTK_GRID(grid_kontrol), 6);
    gtk_grid_set_column_homogeneous(GTK_GRID(grid_kontrol), TRUE);
    gtk_widget_set_hexpand(b_conn, TRUE);
    gtk_widget_set_hexpand(b_disc, TRUE);
    gtk_widget_set_hexpand(b_conn_all, TRUE);
    gtk_widget_set_hexpand(b_disc_all, TRUE);
    gtk_grid_attach(GTK_GRID(grid_kontrol), b_conn, 0, 0, 1, 1);
    gtk_grid_attach(GTK_GRID(grid_kontrol), b_disc, 1, 0, 1, 1);
    gtk_grid_attach(GTK_GRID(grid_kontrol), b_conn_all, 0, 1, 1, 1);
    gtk_grid_attach(GTK_GRID(grid_kontrol), b_disc_all, 1, 1, 1, 1);
    gtk_box_pack_start(GTK_BOX(kiri), grid_kontrol, FALSE, FALSE, 0);

    // Grid arah gerak: satu klik = satu langkah tile bot terpilih.
    GtkWidget *grid = gtk_grid_new();
    gtk_grid_set_row_spacing(GTK_GRID(grid), 2);
    gtk_grid_set_column_spacing(GTK_GRID(grid), 2);
    struct { const char *lbl; const char *arah; int cx, cy; } panah[] = {
        {"↑", "up", 1, 0}, {"←", "left", 0, 1},
        {"↓", "down", 1, 1}, {"→", "right", 2, 1},
    };
    for (auto &p : panah) {
        GtkWidget *b = toolbtn(p.lbl, G_CALLBACK(on_move), "ghost");
        gtk_widget_set_size_request(b, 46, 32);
        g_object_set_data_full(G_OBJECT(b), "arah", g_strdup(p.arah), g_free);
        gtk_grid_attach(GTK_GRID(grid), b, p.cx, p.cy, 1, 1);
    }
    gtk_widget_set_halign(grid, GTK_ALIGN_CENTER);
    gtk_box_pack_start(GTK_BOX(kiri), grid, FALSE, FALSE, 2);

    // Warp: nama dunia di ketik, Enter / tombol = kirim ke bot terpilih.
    GtkWidget *bwarp = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 4);
    entry_warp_ = gtk_entry_new();
    gtk_entry_set_placeholder_text(GTK_ENTRY(entry_warp_), "nama dunia");
    g_signal_connect(entry_warp_, "activate", G_CALLBACK(on_warp), this);
    gtk_box_pack_start(GTK_BOX(bwarp), entry_warp_, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(bwarp), toolbtn("Warp", G_CALLBACK(on_warp), "ghost"),
                       FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(kiri), bwarp, FALSE, FALSE, 0);

    // Respawn + ambil objek di badan. Respawn = `action|respawn`, paket yang
    // sama dengan tombol respawn di klien asli.
    GtkWidget *baksi = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 4);
    GtkWidget *b_resp = toolbtn("Respawn", G_CALLBACK(on_respawn), "ghost");
    GtkWidget *b_coll = toolbtn("Collect", G_CALLBACK(on_collect), "ghost");
    GtkWidget *b_prof = toolbtn("Profil", G_CALLBACK(on_profil), "ghost");
    gtk_widget_set_hexpand(b_resp, TRUE);
    gtk_widget_set_hexpand(b_coll, TRUE);
    gtk_widget_set_hexpand(b_prof, TRUE);
    gtk_box_pack_start(GTK_BOX(baksi), b_resp, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(baksi), b_coll, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(baksi), b_prof, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(kiri), baksi, FALSE, FALSE, 0);

    gtk_box_pack_start(GTK_BOX(kiri), gtk_separator_new(GTK_ORIENTATION_HORIZONTAL),
                       FALSE, FALSE, 4);

    GtkWidget *la = gtk_label_new("AKUN");
    gtk_widget_set_halign(la, GTK_ALIGN_START);
    GtkStyleContext *lac = gtk_widget_get_style_context(la);
    gtk_style_context_add_class(lac, "cardtitle");
    gtk_box_pack_start(GTK_BOX(kiri), la, FALSE, FALSE, 0);

    GtkWidget *b_add = toolbtn("Tambah Bot", G_CALLBACK(on_add_bot), "ghost");
    GtkWidget *b_del = toolbtn("Hapus Bot", G_CALLBACK(on_del_bot), "ghost");
    GtkWidget *b_tok = toolbtn("Token dari HP", G_CALLBACK(on_token_hp), "ghost");
    GtkWidget *grid_akun = gtk_grid_new();
    gtk_grid_set_row_spacing(GTK_GRID(grid_akun), 6);
    gtk_grid_set_column_spacing(GTK_GRID(grid_akun), 6);
    gtk_grid_set_column_homogeneous(GTK_GRID(grid_akun), TRUE);
    gtk_widget_set_hexpand(b_add, TRUE);
    gtk_widget_set_hexpand(b_del, TRUE);
    gtk_widget_set_hexpand(b_tok, TRUE);
    gtk_grid_attach(GTK_GRID(grid_akun), b_add, 0, 0, 1, 1);
    gtk_grid_attach(GTK_GRID(grid_akun), b_del, 1, 0, 1, 1);
    gtk_grid_attach(GTK_GRID(grid_akun), b_tok, 0, 1, 2, 1);
    gtk_box_pack_start(GTK_BOX(kiri), grid_akun, FALSE, FALSE, 0);

    // Panel kiri isinya banyak (AKSI/KONTROL/AKUN); tanpa scroll, tinggi
    // natural-nya memaksa window lebih tinggi dari layar sehingga tombol
    // paling bawah terpotong. ScrolledWindow = tinggi minimum kecil.
    GtkWidget *kiri_sc = gtk_scrolled_window_new(nullptr, nullptr);
    gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(kiri_sc),
                                   GTK_POLICY_NEVER, GTK_POLICY_AUTOMATIC);
    gtk_scrolled_window_set_propagate_natural_height(GTK_SCROLLED_WINDOW(kiri_sc), FALSE);
    gtk_container_add(GTK_CONTAINER(kiri_sc), kiri);
    gtk_paned_pack1(GTK_PANED(body), kiri_sc, FALSE, FALSE);

    // ---- tabel ----
    GtkWidget *kanan = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    gtk_widget_set_margin_start(kanan, 4);
    gtk_paned_pack2(GTK_PANED(body), kanan, TRUE, FALSE);

    // Kolom terakhir (10) = boolean centang, bukan teks.
    store_bots_ = gtk_list_store_new(11, G_TYPE_STRING, G_TYPE_STRING, G_TYPE_STRING,
                                     G_TYPE_STRING, G_TYPE_STRING, G_TYPE_STRING,
                                     G_TYPE_STRING, G_TYPE_STRING, G_TYPE_STRING,
                                     G_TYPE_STRING, G_TYPE_BOOLEAN);
    view_bots_ = gtk_tree_view_new_with_model(GTK_TREE_MODEL(store_bots_));
    gtk_tree_view_set_grid_lines(GTK_TREE_VIEW(view_bots_), GTK_TREE_VIEW_GRID_LINES_NONE);
    // MALADY sengaja tepat di sebelah LEVEL: status sakit (surgeon) hanya
    // masuk akal dibaca bersama level karakter.
    const char *judul[] = {"BOT", "NAMA", "LEVEL", "MALADY", "PING", "STATUS",
                           "PROXY", "DUNIA", "POSISI", "GEMS"};
    const int lebar[] = {110, 130, 52, 130, 58, 110, 170, 120, 70, 62};
    // Kolom centang paling kiri: penanda bot mana yang ikut dikontrol.
    {
        GtkCellRenderer *r = gtk_cell_renderer_toggle_new();
        g_signal_connect(r, "toggled", G_CALLBACK(on_toggle_bot), this);
        GtkTreeViewColumn *c = gtk_tree_view_column_new_with_attributes(
            "PILIH", r, "active", 10, nullptr);
        gtk_tree_view_column_set_min_width(c, 54);
        gtk_tree_view_append_column(GTK_TREE_VIEW(view_bots_), c);
    }
    for (int i = 0; i < 10; ++i) add_col(view_bots_, judul[i], i, lebar[i]);
    // Klik = pilih bot (bisa banyak). Dobel-klik / Enter = buka halaman detail.
    // Dulu `cursor-changed` langsung membuka detail, jadi mustahil memilih
    // beberapa bot sekaligus untuk dikontrol bersama.
    g_signal_connect(view_bots_, "row-activated", G_CALLBACK(on_open_bot), this);
    g_signal_connect(view_bots_, "cursor-changed", G_CALLBACK(on_bot_select), this);

    GtkWidget *scroll = gtk_scrolled_window_new(nullptr, nullptr);
    gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(scroll),
                                   GTK_POLICY_AUTOMATIC, GTK_POLICY_AUTOMATIC);
    gtk_container_add(GTK_CONTAINER(scroll), view_bots_);
    gtk_box_pack_start(GTK_BOX(kanan), scroll, TRUE, TRUE, 0);

    bots_bar_ = gtk_label_new("Online 0   ·   Offline 0   ·   Total 0   ·   Gems 0");
    gtk_widget_set_halign(bots_bar_, GTK_ALIGN_START);
    GtkStyleContext *bc = gtk_widget_get_style_context(bots_bar_);
    gtk_style_context_add_class(bc, "dim");
    gtk_widget_set_margin_start(bots_bar_, 2);
    gtk_widget_set_margin_top(bots_bar_, 8);
    gtk_box_pack_start(GTK_BOX(kanan), bots_bar_, FALSE, FALSE, 0);

    gtk_stack_add_named(GTK_STACK(bot_stack_), v, "daftar");
    gtk_stack_add_named(GTK_STACK(bot_stack_), detail_page(), "detail");
    gtk_stack_set_visible_child_name(GTK_STACK(bot_stack_), "daftar");
    return bot_stack_;
}

// ------------------------------------------------------ detail satu bot ---
GtkWidget *App::detail_page() {
    GtkWidget *v = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    GtkStyleContext *pc = gtk_widget_get_style_context(v);
    gtk_style_context_add_class(pc, "pane");

    // ---- kepala: kembali + nama bot + tombol ----
    GtkWidget *bar = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    gtk_box_pack_start(GTK_BOX(bar), toolbtn("← Bots", G_CALLBACK(on_back_bots), "ghost"),
                       FALSE, FALSE, 0);

    detail_judul_ = gtk_label_new("—");
    gtk_widget_set_name(detail_judul_, "botjudul");
    gtk_box_pack_start(GTK_BOX(bar), detail_judul_, FALSE, FALSE, 4);

    detail_sub_ = gtk_label_new("");
    GtkStyleContext *sc = gtk_widget_get_style_context(detail_sub_);
    gtk_style_context_add_class(sc, "dim");
    gtk_box_pack_start(GTK_BOX(bar), detail_sub_, FALSE, FALSE, 0);

    GtkWidget *sp = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    gtk_widget_set_hexpand(sp, TRUE);
    gtk_box_pack_start(GTK_BOX(bar), sp, TRUE, TRUE, 0);

    gtk_box_pack_start(GTK_BOX(bar), toolbtn("Connect", G_CALLBACK(on_connect), "ghost"),
                       FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(bar), toolbtn("Disconnect", G_CALLBACK(on_disconnect), "ghost"),
                       FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(bar), toolbtn("Hapus", G_CALLBACK(on_del_bot), "danger"),
                       FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(v), bar, FALSE, FALSE, 0);

    detail_notebook_ = gtk_notebook_new();
    gtk_notebook_set_show_border(GTK_NOTEBOOK(detail_notebook_), FALSE);
    gtk_box_pack_start(GTK_BOX(v), detail_notebook_, TRUE, TRUE, 12);

    gtk_notebook_append_page(GTK_NOTEBOOK(detail_notebook_), detail_fitur(),
                             gtk_label_new("Mod Menu"));
    gtk_notebook_append_page(GTK_NOTEBOOK(detail_notebook_), detail_map(),
                             gtk_label_new("Dunia"));
    gtk_notebook_append_page(GTK_NOTEBOOK(detail_notebook_), detail_console(),
                             gtk_label_new("Console"));
    gtk_notebook_append_page(GTK_NOTEBOOK(detail_notebook_), detail_chat(),
                             gtk_label_new("Chat"));
    gtk_notebook_append_page(GTK_NOTEBOOK(detail_notebook_), detail_inv(),
                             gtk_label_new("Inventaris"));
    gtk_notebook_append_page(GTK_NOTEBOOK(detail_notebook_), detail_paket(),
                             gtk_label_new("Paket"));
    gtk_notebook_append_page(GTK_NOTEBOOK(detail_notebook_), detail_info(),
                             gtk_label_new("Info"));
    return v;
}

// ------------------------------------ detail: tab Mod Menu (kiri/kanan) ---
// Kiri = daftar fitur (sidebar). Kanan = halaman pengaturan fitur terpilih.
// Halaman dibangun dari skema server, jadi tiap fitur punya form lengkap
// sendiri, bukan cuma saklar on/off.
GtkWidget *App::detail_fitur() {
    GtkWidget *v = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    GtkStyleContext *pc = gtk_widget_get_style_context(v);
    gtk_style_context_add_class(pc, "pane");

    GtkWidget *paned = gtk_paned_new(GTK_ORIENTATION_HORIZONTAL);
    gtk_paned_set_position(GTK_PANED(paned), 208);
    gtk_box_pack_start(GTK_BOX(v), paned, TRUE, TRUE, 0);

    // ---- sidebar ----
    GtkWidget *kiri = gtk_box_new(GTK_ORIENTATION_VERTICAL, 8);
    GtkStyleContext *kc = gtk_widget_get_style_context(kiri);
    gtk_style_context_add_class(kc, "card");
    gtk_widget_set_size_request(kiri, 200, -1);

    GtkWidget *judul = gtk_label_new("MOD MENU");
    gtk_widget_set_halign(judul, GTK_ALIGN_START);
    GtkStyleContext *jc = gtk_widget_get_style_context(judul);
    gtk_style_context_add_class(jc, "cardtitle");
    gtk_box_pack_start(GTK_BOX(kiri), judul, FALSE, FALSE, 0);

    GtkWidget *scl = gtk_scrolled_window_new(nullptr, nullptr);
    gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(scl),
                                   GTK_POLICY_NEVER, GTK_POLICY_AUTOMATIC);
    GtkStyleContext *sc_c = gtk_widget_get_style_context(scl);
    gtk_style_context_add_class(sc_c, "plain");
    detail_list_ = gtk_list_box_new();
    gtk_list_box_set_selection_mode(GTK_LIST_BOX(detail_list_), GTK_SELECTION_SINGLE);
    g_signal_connect(detail_list_, "row-selected", G_CALLBACK(on_detail_row), this);
    gtk_container_add(GTK_CONTAINER(scl), detail_list_);
    gtk_box_pack_start(GTK_BOX(kiri), scl, TRUE, TRUE, 0);
    gtk_paned_pack1(GTK_PANED(paned), kiri, FALSE, FALSE);

    // ---- kanan: halaman per fitur ----
    detail_stack_ = gtk_stack_new();
    gtk_stack_set_transition_type(GTK_STACK(detail_stack_),
                                  GTK_STACK_TRANSITION_TYPE_CROSSFADE);
    gtk_stack_set_transition_duration(GTK_STACK(detail_stack_), 120);
    GtkWidget *kosong = gtk_label_new("Pilih fitur di kiri");
    GtkStyleContext *ec = gtk_widget_get_style_context(kosong);
    gtk_style_context_add_class(ec, "empty-title");
    gtk_stack_add_named(GTK_STACK(detail_stack_), kosong, "kosong");
    gtk_stack_set_visible_child_name(GTK_STACK(detail_stack_), "kosong");
    GtkWidget *kanan = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    gtk_widget_set_margin_start(kanan, 10);
    gtk_box_pack_start(GTK_BOX(kanan), detail_stack_, TRUE, TRUE, 0);
    gtk_paned_pack2(GTK_PANED(paned), kanan, TRUE, FALSE);
    return v;
}

// ------------------------------------------------------------ tabel tile ---
// ------------------------------------------------ detail: tab Chat ---
GtkWidget *App::detail_chat() {
    GtkWidget *v = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    GtkStyleContext *pc = gtk_widget_get_style_context(v);
    gtk_style_context_add_class(pc, "pane");

    view_chat_ = gtk_text_view_new();
    gtk_text_view_set_editable(GTK_TEXT_VIEW(view_chat_), FALSE);
    gtk_text_view_set_cursor_visible(GTK_TEXT_VIEW(view_chat_), FALSE);
    gtk_text_view_set_wrap_mode(GTK_TEXT_VIEW(view_chat_), GTK_WRAP_WORD_CHAR);
    gtk_text_view_set_left_margin(GTK_TEXT_VIEW(view_chat_), 10);
    gtk_text_view_set_top_margin(GTK_TEXT_VIEW(view_chat_), 8);
    GtkWidget *sc = gtk_scrolled_window_new(nullptr, nullptr);
    gtk_container_add(GTK_CONTAINER(sc), view_chat_);
    gtk_box_pack_start(GTK_BOX(v), sc, TRUE, TRUE, 0);

    GtkWidget *bar = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
    entry_chat_ = gtk_entry_new();
    gtk_entry_set_placeholder_text(GTK_ENTRY(entry_chat_), "tulis chat ke dunia…");
    g_signal_connect(entry_chat_, "activate", G_CALLBACK(on_chat_enter), this);
    gtk_box_pack_start(GTK_BOX(bar), entry_chat_, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(bar), toolbtn("Kirim", G_CALLBACK(on_send_chat), "primary"),
                       FALSE, FALSE, 0);
    gtk_widget_set_margin_top(bar, 8);
    gtk_box_pack_start(GTK_BOX(v), bar, FALSE, FALSE, 0);
    return v;
}

// --------------------------------------------- detail: tab Console ---
GtkWidget *App::detail_console() {
    GtkWidget *v = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    GtkStyleContext *pc = gtk_widget_get_style_context(v);
    gtk_style_context_add_class(pc, "pane");

    view_console_ = gtk_text_view_new();
    gtk_text_view_set_editable(GTK_TEXT_VIEW(view_console_), FALSE);
    gtk_text_view_set_cursor_visible(GTK_TEXT_VIEW(view_console_), FALSE);
    gtk_text_view_set_wrap_mode(GTK_TEXT_VIEW(view_console_), GTK_WRAP_WORD_CHAR);
    gtk_text_view_set_left_margin(GTK_TEXT_VIEW(view_console_), 10);
    gtk_text_view_set_top_margin(GTK_TEXT_VIEW(view_console_), 8);
    GtkWidget *sc = gtk_scrolled_window_new(nullptr, nullptr);
    gtk_container_add(GTK_CONTAINER(sc), view_console_);
    gtk_box_pack_start(GTK_BOX(v), sc, TRUE, TRUE, 0);

    GtkWidget *bar = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
    entry_cmd_ = gtk_entry_new();
    gtk_entry_set_placeholder_text(GTK_ENTRY(entry_cmd_),
                                   "say halo  ·  warp WORLD  ·  run skrip.lua");
    g_signal_connect(entry_cmd_, "activate", G_CALLBACK(on_cmd_enter), this);
    gtk_box_pack_start(GTK_BOX(bar), entry_cmd_, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(bar), toolbtn("Kirim", G_CALLBACK(on_send_cmd), "primary"),
                       FALSE, FALSE, 0);
    gtk_widget_set_margin_top(bar, 8);
    gtk_box_pack_start(GTK_BOX(v), bar, FALSE, FALSE, 0);
    return v;
}

// ---------------------------------------------- detail: tab Dunia ---
// Peta digambar dari sprite asli `tiles_pageN.rttex` (lewat /api/sprite),
// jadi tiap koordinat tampil sebagai gambar bloknya sendiri.
GtkWidget *App::detail_map() {
    GtkWidget *v = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    GtkStyleContext *pc = gtk_widget_get_style_context(v);
    gtk_style_context_add_class(pc, "pane");

    // Tanpa scrolled window: seluruh dunia dipaskan ke viewport, jadi tidak
    // ada kanvas 3200x32000 seperti sebelumnya.
    GtkWidget *bingkai = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    gtk_style_context_add_class(gtk_widget_get_style_context(bingkai), "mapbingkai");
    gtk_widget_set_margin_start(bingkai, 10);
    gtk_widget_set_margin_end(bingkai, 10);
    gtk_widget_set_margin_top(bingkai, 10);

    peta_area_ = gtk_drawing_area_new();
    gtk_widget_set_hexpand(peta_area_, TRUE);
    gtk_widget_set_vexpand(peta_area_, TRUE);
    g_signal_connect(peta_area_, "draw", G_CALLBACK(on_map_draw), this);
    gtk_widget_add_events(peta_area_, GDK_POINTER_MOTION_MASK | GDK_LEAVE_NOTIFY_MASK);
    g_signal_connect(peta_area_, "motion-notify-event", G_CALLBACK(on_map_motion), this);
    gtk_box_pack_start(GTK_BOX(bingkai), peta_area_, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(v), bingkai, TRUE, TRUE, 0);

    GtkWidget *bar = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 10);
    gtk_widget_set_margin_top(bar, 8);
    map_note_ = gtk_label_new("—");
    gtk_widget_set_halign(map_note_, GTK_ALIGN_START);
    GtkStyleContext *nc = gtk_widget_get_style_context(map_note_);
    gtk_style_context_add_class(nc, "dim");
    gtk_box_pack_start(GTK_BOX(bar), map_note_, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(bar),
                       toolbtn("Segarkan Peta", G_CALLBACK(on_refresh), "ghost"),
                       FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(v), bar, FALSE, FALSE, 0);
    return v;
}

// ------------------------------------------ detail: tab Inventaris ---
GtkWidget *App::detail_inv() {
    GtkWidget *v = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    GtkStyleContext *pc = gtk_widget_get_style_context(v);
    gtk_style_context_add_class(pc, "pane");

    GtkWidget *scroll = gtk_scrolled_window_new(nullptr, nullptr);
    gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(scroll),
                                   GTK_POLICY_NEVER, GTK_POLICY_AUTOMATIC);
    gtk_style_context_add_class(gtk_widget_get_style_context(scroll), "plain");

    // Tiap item = satu kotak tile 64 px: gambar item + jumlah di sudut.
    inv_flow_ = gtk_flow_box_new();
    gtk_flow_box_set_selection_mode(GTK_FLOW_BOX(inv_flow_), GTK_SELECTION_NONE);
    gtk_flow_box_set_max_children_per_line(GTK_FLOW_BOX(inv_flow_), 40);
    gtk_flow_box_set_min_children_per_line(GTK_FLOW_BOX(inv_flow_), 1);
    gtk_flow_box_set_row_spacing(GTK_FLOW_BOX(inv_flow_), 8);
    gtk_flow_box_set_column_spacing(GTK_FLOW_BOX(inv_flow_), 8);
    gtk_widget_set_margin_start(inv_flow_, 12);
    gtk_widget_set_margin_end(inv_flow_, 12);
    gtk_widget_set_margin_top(inv_flow_, 12);
    gtk_widget_set_halign(inv_flow_, GTK_ALIGN_FILL);
    gtk_widget_set_valign(inv_flow_, GTK_ALIGN_START);
    gtk_widget_set_hexpand(inv_flow_, TRUE);
    gtk_flow_box_set_homogeneous(GTK_FLOW_BOX(inv_flow_), TRUE);
    gtk_container_add(GTK_CONTAINER(scroll), inv_flow_);
    gtk_box_pack_start(GTK_BOX(v), scroll, TRUE, TRUE, 0);

    inv_note_ = gtk_label_new("—");
    gtk_widget_set_halign(inv_note_, GTK_ALIGN_START);
    GtkStyleContext *nc = gtk_widget_get_style_context(inv_note_);
    gtk_style_context_add_class(nc, "dim");
    gtk_widget_set_margin_top(inv_note_, 8);
    gtk_widget_set_margin_start(inv_note_, 12);
    gtk_box_pack_start(GTK_BOX(v), inv_note_, FALSE, FALSE, 0);
    return v;
}

// ------------------------------------------------ detail: tab Info ---
GtkWidget *App::detail_info() {
    GtkWidget *v = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    GtkStyleContext *pc = gtk_widget_get_style_context(v);
    gtk_style_context_add_class(pc, "pane");

    detail_info_ = gtk_label_new("—");
    gtk_label_set_xalign(GTK_LABEL(detail_info_), 0.0);
    gtk_label_set_yalign(GTK_LABEL(detail_info_), 0.0);
    gtk_label_set_selectable(GTK_LABEL(detail_info_), TRUE);
    gtk_label_set_line_wrap(GTK_LABEL(detail_info_), TRUE);
    GtkStyleContext *c = gtk_widget_get_style_context(detail_info_);
    gtk_style_context_add_class(c, "mono");
    // Harus di dalam scrolled window: GtkNotebook memakai min-height
    // TERBESAR dari semua halaman, dan label panjang tanpa scroll membuat
    // window dipaksa lebih tinggi dari layar (isi bawah terpotong).
    GtkWidget *sc = gtk_scrolled_window_new(nullptr, nullptr);
    gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(sc),
                                   GTK_POLICY_NEVER, GTK_POLICY_AUTOMATIC);
    gtk_container_add(GTK_CONTAINER(sc), detail_info_);
    gtk_box_pack_start(GTK_BOX(v), sc, TRUE, TRUE, 0);
    return v;
}

// ------------------------------------------------ detail: tab Paket ---
// Jurnal paket masuk/keluar. Untuk debugging: drop item di badan bot lalu
// lihat paket type 14 (ItemChangeObject) yang dikirim server.
GtkWidget *App::detail_paket() {
    GtkWidget *v = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    GtkStyleContext *pc = gtk_widget_get_style_context(v);
    gtk_style_context_add_class(pc, "pane");

    view_paket_ = gtk_text_view_new();
    gtk_text_view_set_editable(GTK_TEXT_VIEW(view_paket_), FALSE);
    gtk_text_view_set_cursor_visible(GTK_TEXT_VIEW(view_paket_), FALSE);
    gtk_text_view_set_wrap_mode(GTK_TEXT_VIEW(view_paket_), GTK_WRAP_WORD_CHAR);
    gtk_text_view_set_left_margin(GTK_TEXT_VIEW(view_paket_), 10);
    gtk_text_view_set_top_margin(GTK_TEXT_VIEW(view_paket_), 8);
    gtk_text_view_set_monospace(GTK_TEXT_VIEW(view_paket_), TRUE);
    GtkWidget *sc = gtk_scrolled_window_new(nullptr, nullptr);
    gtk_container_add(GTK_CONTAINER(sc), view_paket_);
    gtk_box_pack_start(GTK_BOX(v), sc, TRUE, TRUE, 0);

    GtkWidget *bar = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
    gtk_widget_set_margin_top(bar, 8);
    gtk_widget_set_margin_start(bar, 10);
    gtk_box_pack_start(GTK_BOX(bar),
                       toolbtn("Segarkan", G_CALLBACK(on_refresh), "ghost"),
                       FALSE, FALSE, 0);
    GtkWidget *note = gtk_label_new(
        "in = dari server, out = dari bot. type 14 = ItemChangeObject (item jatuh).");
    GtkStyleContext *nc = gtk_widget_get_style_context(note);
    gtk_style_context_add_class(nc, "dim");
    gtk_box_pack_start(GTK_BOX(bar), note, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(v), bar, FALSE, FALSE, 0);
    return v;
}

// ------------------------------------------------------------ Console ---
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

    // Kolom 0 = pixbuf sprite item, supaya daftar kelihatan seperti database
    // deltaX (gambar + nama), bukan tabel teks kosong.
    store_items_ = gtk_list_store_new(6, GDK_TYPE_PIXBUF, G_TYPE_STRING,
                                      G_TYPE_STRING, G_TYPE_STRING, G_TYPE_STRING,
                                      G_TYPE_STRING);
    view_items_ = gtk_tree_view_new_with_model(GTK_TREE_MODEL(store_items_));
    gtk_tree_view_set_grid_lines(GTK_TREE_VIEW(view_items_), GTK_TREE_VIEW_GRID_LINES_NONE);
    {
        GtkCellRenderer *r = gtk_cell_renderer_pixbuf_new();
        g_object_set(r, "xpad", 6, "ypad", 3, nullptr);
        GtkTreeViewColumn *c = gtk_tree_view_column_new_with_attributes(
            "", r, "pixbuf", 0, nullptr);
        gtk_tree_view_column_set_min_width(c, 46);
        gtk_tree_view_append_column(GTK_TREE_VIEW(view_items_), c);
    }
    const char *judul[] = {"ID", "NAMA", "RARITY", "TIPE", "GROW"};
    const int lebar[] = {80, 300, 80, 80, 90};
    for (int i = 0; i < 5; ++i) add_col(view_items_, judul[i], i + 1, lebar[i]);
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
    // Ukuran awal = workarea monitor. `gtk_window_maximize` saja tidak cukup:
    // di beberapa WM/Wayland window tetap dipetakan seukuran default_size
    // (di layar 1366x768 tampak "cuma setengah layar").
    {
        int w = 1180, h = 720;
        GdkDisplay *d = gdk_display_get_default();
        GdkMonitor *mon = d ? gdk_display_get_primary_monitor(d) : nullptr;
        if (!mon && d) mon = gdk_display_get_monitor(d, 0);
        if (mon) {
            GdkRectangle wa{};
            gdk_monitor_get_workarea(mon, &wa);
            // Headerbar + dekorasi WM tidak termasuk workarea, jadi kurangi
            // sedikit supaya window tidak menjorok keluar layar.
            if (wa.width > 200) w = wa.width - 8;
            if (wa.height > 200) h = wa.height - 8;
        }
        gtk_window_set_default_size(GTK_WINDOW(window_), w, h);
    }
    // Ikon dock/taskbar (WM_CLASS diset lewat g_set_prgname di main).
    {
        const char *home = g_getenv("HOME");
        std::string ic = repo_ + "/deploy/icons/lucifer.png";
        if (access(ic.c_str(), R_OK) != 0 && home)
            ic = std::string(home) + "/.local/share/icons/hicolor/256x256/apps/lucifer.png";
        if (access(ic.c_str(), R_OK) == 0)
            gtk_window_set_icon_from_file(GTK_WINDOW(window_), ic.c_str(), nullptr);
    }
    g_signal_connect(window_, "destroy", G_CALLBACK(on_destroy), this);

    notebook_ = gtk_notebook_new();
    gtk_notebook_set_show_border(GTK_NOTEBOOK(notebook_), FALSE);
    gtk_container_add(GTK_CONTAINER(window_), notebook_);

    gtk_notebook_append_page(GTK_NOTEBOOK(notebook_), tab_bots(), gtk_label_new("Bots"));
    gtk_notebook_append_page(GTK_NOTEBOOK(notebook_), tab_executor(), gtk_label_new("Executor"));
    gtk_notebook_append_page(GTK_NOTEBOOK(notebook_), tab_proxy(), gtk_label_new("Proxy"));
    gtk_notebook_append_page(GTK_NOTEBOOK(notebook_), tab_database(), gtk_label_new("Database"));
    gtk_notebook_append_page(GTK_NOTEBOOK(notebook_), tab_settings(), gtk_label_new("Settings"));
    gtk_widget_show_all(window_);
    // Layar penuh sejak awal: maximize (bukan fullscreen) supaya titlebar
    // dan tombol window tetap ada. Di Wayland beberapa WM mengabaikan
    // maximize sebelum window dipetakan, jadi diulang lewat idle.
    gtk_window_maximize(GTK_WINDOW(window_));
    g_idle_add([](gpointer w) -> gboolean {
        gtk_window_maximize(GTK_WINDOW(w));
        return G_SOURCE_REMOVE;
    }, window_);
    gtk_notebook_set_current_page(GTK_NOTEBOOK(notebook_), tab_awal_);
}

void App::start_backend() {
    // Sudah ada server di port ini? Jangan nyalakan kedua (bind error).
    if (http_.get("/health").ok()) return;
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
// Folder repo ditebak dari lokasi binary: <repo>/desktop/build/lucifer-desktop
// atau <repo>/bin/lucifer-desktop, supaya .desktop bisa jalan dari mana saja.
static std::string tebak_repo() {
    char exe[4096];
    ssize_t n = ::readlink("/proc/self/exe", exe, sizeof exe - 1);
    if (n <= 0) return ".";
    exe[n] = 0;
    std::string dir(exe);
    // Cari ke atas sampai 6 tingkat: binary hasil `pasang-desktop.sh` ada di
    // ~/.local/bin, jadi repo tidak akan ketemu kalau hanya naik 3 tingkat.
    for (int naik = 0; naik < 6; ++naik) {
        size_t slash = dir.find_last_of('/');
        if (slash == std::string::npos) break;
        dir.erase(slash);
        if (access((dir + "/lucifer/__init__.py").c_str(), R_OK) == 0) return dir;
    }
    // Fallback: lokasi lazim repo, supaya backend tetap menemukan data/.
    const char *home = g_getenv("HOME");
    if (home) {
        std::string c = std::string(home) + "/Documents/lucifer-linux";
        if (access((c + "/lucifer/__init__.py").c_str(), R_OK) == 0) return c;
    }
    return ".";
}

int main(int argc, char **argv) {
    // WM_CLASS = "lucifer-desktop" — dipakai StartupWMClass di lucifer.desktop
    // supaya ikon dock menempel ke launcher, bukan ikon generik.
    g_set_prgname("lucifer-desktop");
    g_set_application_name("Lucifer Linux");
    gdk_set_program_class("LuciferLinux");
    std::string url = "http://127.0.0.1:8787";
    int port = 8787;
    bool spawn = true;
    std::string repo = tebak_repo();

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
    if (const char *tab = std::getenv("LUCIFER_TAB"))
        app.tab_awal(std::atoi(tab));
    if (const char *bot = std::getenv("LUCIFER_BOT"))
        app.bot_awal(bot);
    return app.run(argc, argv);
}
