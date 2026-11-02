// lucifer-desktop — GUI native (GTK3) untuk Lucifer Linux.
//
// Arsitektur: GUI ini tipis. Semua logika bot tetap di Python (lucifer.web);
// aplikasi menyalakan server lokal lalu bicara JSON lewat HTTP loopback.
// Dengan begitu dua antarmuka (web & desktop) memakai satu sumber kebenaran,
// dan tidak ada logika protokol Growtopia yang ditulis dua kali.
//
// Bangun:  cmake -B build -S desktop && cmake --build build -j
// Jalankan: ./build/lucifer-desktop [--port 8787] [--url http://host:port]

#include <gtk/gtk.h>
#include <json-glib/json-glib.h>

#include <arpa/inet.h>
#include <netdb.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

namespace {

constexpr const char *APP_TITLE = "Lucifer Linux";
constexpr const char *APP_VERSION = "2.87.2-native";

// ---------------------------------------------------------------- HTTP ---
// Klien HTTP minimal untuk loopback: cukup request/response biasa, tanpa TLS.
struct HttpResponse {
    int status = 0;
    std::string body;
    bool ok() const { return status >= 200 && status < 300; }
};

class Http {
public:
    explicit Http(std::string base) : base_(std::move(base)) {}

    HttpResponse get(const std::string &path) { return call("GET", path, ""); }

    HttpResponse post(const std::string &path, const std::string &json) {
        return call("POST", path, json);
    }

private:
    HttpResponse call(const std::string &method, const std::string &path,
                      const std::string &body) {
        HttpResponse out;
        std::string host = "127.0.0.1";
        int port = 8787;

        std::string hp = base_;
        const std::string scheme = "http://";
        if (hp.rfind(scheme, 0) == 0) hp = hp.substr(scheme.size());
        auto slash = hp.find('/');
        if (slash != std::string::npos) hp = hp.substr(0, slash);
        auto colon = hp.rfind(':');
        if (colon != std::string::npos) {
            host = hp.substr(0, colon);
            port = std::atoi(hp.c_str() + colon + 1);
        } else if (!hp.empty()) {
            host = hp;
        }

        addrinfo hints{};
        hints.ai_family = AF_UNSPEC;
        hints.ai_socktype = SOCK_STREAM;
        addrinfo *res = nullptr;
        const std::string port_s = std::to_string(port);
        if (getaddrinfo(host.c_str(), port_s.c_str(), &hints, &res) != 0) {
            out.status = 0;
            return out;
        }

        int fd = -1;
        for (addrinfo *p = res; p; p = p->ai_next) {
            fd = ::socket(p->ai_family, p->ai_socktype, p->ai_protocol);
            if (fd < 0) continue;
            if (::connect(fd, p->ai_addr, p->ai_addrlen) == 0) break;
            ::close(fd);
            fd = -1;
        }
        freeaddrinfo(res);
        if (fd < 0) {
            out.status = 0;
            return out;
        }

        std::string req = method + " " + path + " HTTP/1.1\r\n";
        req += "Host: " + host + ":" + port_s + "\r\n";
        req += "Connection: close\r\n";
        req += "Accept: application/json\r\n";
        if (!body.empty() || method == "POST") {
            req += "Content-Type: application/json\r\n";
            req += "Content-Length: " + std::to_string(body.size()) + "\r\n";
        }
        req += "\r\n";
        req += body;

        size_t sent = 0;
        while (sent < req.size()) {
            ssize_t n = ::send(fd, req.data() + sent, req.size() - sent, MSG_NOSIGNAL);
            if (n <= 0) break;
            sent += static_cast<size_t>(n);
        }

        std::string raw;
        char buf[8192];
        for (;;) {
            ssize_t n = ::recv(fd, buf, sizeof buf, 0);
            if (n <= 0) break;
            raw.append(buf, static_cast<size_t>(n));
            if (raw.size() > (8u << 20)) break;  // jaga memori
        }
        ::close(fd);

        auto hdr_end = raw.find("\r\n\r\n");
        if (hdr_end == std::string::npos) {
            out.status = 0;
            return out;
        }
        std::sscanf(raw.c_str(), "HTTP/%*d.%*d %d", &out.status);
        std::string head = raw.substr(0, hdr_end);
        out.body = raw.substr(hdr_end + 4);

        // Transfer-Encoding: chunked (server Python memakainya untuk /api/*)
        if (head.find("chunked") != std::string::npos) out.body = dechunk(out.body);
        return out;
    }

    static std::string dechunk(const std::string &in) {
        std::string out;
        size_t i = 0;
        while (i < in.size()) {
            auto eol = in.find("\r\n", i);
            if (eol == std::string::npos) break;
            long len = std::strtol(in.c_str() + i, nullptr, 16);
            if (len <= 0) break;
            i = eol + 2;
            if (i + static_cast<size_t>(len) > in.size()) break;
            out.append(in, i, static_cast<size_t>(len));
            i += static_cast<size_t>(len) + 2;
        }
        return out.empty() ? in : out;
    }

    std::string base_;
};

// --------------------------------------------------------------- JSON ---
JsonNode *parse(const std::string &text) {
    JsonParser *p = json_parser_new();
    GError *err = nullptr;
    if (!json_parser_load_from_data(p, text.c_str(), static_cast<gssize>(text.size()), &err)) {
        if (err) g_error_free(err);
        g_object_unref(p);
        return nullptr;
    }
    JsonNode *root = json_node_copy(json_parser_get_root(p));
    g_object_unref(p);
    return root;
}

std::string jstr(JsonObject *o, const char *key) {
    if (!o || !json_object_has_member(o, key)) return "";
    JsonNode *n = json_object_get_member(o, key);
    if (!n || JSON_NODE_HOLDS_NULL(n)) return "";
    if (JSON_NODE_HOLDS_VALUE(n)) {
        if (json_node_get_value_type(n) == G_TYPE_STRING) return json_node_get_string(n);
        if (json_node_get_value_type(n) == G_TYPE_BOOLEAN)
            return json_node_get_boolean(n) ? "true" : "false";
        if (json_node_get_value_type(n) == G_TYPE_INT64) {
            char b[32];
            std::snprintf(b, sizeof b, "%" G_GINT64_FORMAT, json_node_get_int(n));
            return b;
        }
        if (json_node_get_value_type(n) == G_TYPE_DOUBLE) {
            char b[32];
            std::snprintf(b, sizeof b, "%.2f", json_node_get_double(n));
            return b;
        }
    }
    return "";
}

// ------------------------------------------------------------- Aplikasi ---
enum BotCol { COL_LABEL, COL_NAME, COL_STATUS, COL_LEVEL, COL_PING, COL_PROXY,
              COL_WORLD, COL_GEMS, COL_N };

class App {
public:
    App(std::string base, bool spawn, std::string repo, int port)
        : http_(std::move(base)), spawn_(spawn), repo_(std::move(repo)), port_(port) {}

    int run(int argc, char **argv) {
        gtk_init(&argc, &argv);
        build_ui();
        if (spawn_) start_backend();
        refresh();
        g_timeout_add(2000, &App::tick, this);
        gtk_main();
        if (child_pid_ > 0) ::kill(child_pid_, SIGTERM);
        return 0;
    }

private:
    // -- pembangunan UI --------------------------------------------------- //
    void build_ui() {
        window_ = gtk_window_new(GTK_WINDOW_TOPLEVEL);
        gtk_window_set_title(GTK_WINDOW(window_), APP_TITLE);
        gtk_window_set_default_size(GTK_WINDOW(window_), 1100, 680);

        GtkWidget *head = gtk_header_bar_new();
        gtk_header_bar_set_title(GTK_HEADER_BAR(head), APP_TITLE);
        gtk_header_bar_set_subtitle(GTK_HEADER_BAR(head), APP_VERSION);
        gtk_header_bar_set_show_close_button(GTK_HEADER_BAR(head), TRUE);
        gtk_window_set_titlebar(GTK_WINDOW(window_), head);

        GtkWidget *status_btn = gtk_label_new("● offline");
        gtk_header_bar_pack_end(GTK_HEADER_BAR(head), status_btn);
        status_label_ = status_btn;

        notebook_ = gtk_notebook_new();
        gtk_container_add(GTK_CONTAINER(window_), notebook_);

        gtk_notebook_append_page(GTK_NOTEBOOK(notebook_), build_bots_tab(),
                                 gtk_label_new("Bots"));
        gtk_notebook_append_page(GTK_NOTEBOOK(notebook_), build_proxy_tab(),
                                 gtk_label_new("Proxy"));
        gtk_notebook_append_page(GTK_NOTEBOOK(notebook_), build_executor_tab(),
                                 gtk_label_new("Executor"));
        gtk_notebook_append_page(GTK_NOTEBOOK(notebook_), build_log_tab(),
                                 gtk_label_new("Log"));

        g_signal_connect(window_, "destroy", G_CALLBACK(+[](GtkWidget *, gpointer d) {
            gtk_main_quit();
            (void)d;
        }), this);
    }

    GtkWidget *toolbar(std::initializer_list<std::pair<const char *, GCallback>> items,
                       std::initializer_list<const char *> labels) {
        GtkWidget *box = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 4);
        gtk_widget_set_margin_start(box, 8);
        gtk_widget_set_margin_end(box, 8);
        gtk_widget_set_margin_top(box, 6);
        gtk_widget_set_margin_bottom(box, 6);
        auto li = labels.begin();
        for (auto &it : items) {
            GtkWidget *b = gtk_button_new_with_label(*li ? *li : it.first);
            gtk_button_set_relief(GTK_BUTTON(b), GTK_RELIEF_NONE);
            g_signal_connect(b, "clicked", it.second, this);
            gtk_box_pack_start(GTK_BOX(box), b, FALSE, FALSE, 0);
            ++li;
        }
        return box;
    }

    GtkWidget *build_bots_tab() {
        GtkWidget *v = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
        GtkWidget *bar = toolbar({
            {"tambah", G_CALLBACK(on_add_bot)},
            {"hapus", G_CALLBACK(on_del_bot)},
            {"connect", G_CALLBACK(on_connect)},
            {"disconnect", G_CALLBACK(on_disconnect)},
            {"segarkan", G_CALLBACK(on_refresh)},
        }, {"Tambah Bot", "Hapus", "Connect", "Disconnect", "Segarkan"});
        gtk_box_pack_start(GTK_BOX(v), bar, FALSE, FALSE, 0);

        store_ = gtk_list_store_new(COL_N, G_TYPE_STRING, G_TYPE_STRING, G_TYPE_STRING,
                                    G_TYPE_STRING, G_TYPE_STRING, G_TYPE_STRING,
                                    G_TYPE_STRING, G_TYPE_STRING);
        GtkWidget *view = gtk_tree_view_new_with_model(GTK_TREE_MODEL(store_));
        const char *judul[COL_N] = {"Label", "Nama", "Status", "Level",
                                    "Ping", "Proxy", "Dunia", "Gems"};
        for (int i = 0; i < COL_N; ++i) {
            GtkCellRenderer *r = gtk_cell_renderer_text_new();
            GtkTreeViewColumn *c = gtk_tree_view_column_new_with_attributes(
                judul[i], r, "text", i, nullptr);
            gtk_tree_view_column_set_resizable(c, TRUE);
            gtk_tree_view_append_column(GTK_TREE_VIEW(view), c);
        }
        g_signal_connect(view, "cursor-changed", G_CALLBACK(on_row_changed), this);

        GtkWidget *scroll = gtk_scrolled_window_new(nullptr, nullptr);
        gtk_container_add(GTK_CONTAINER(scroll), view);
        gtk_box_pack_start(GTK_BOX(v), scroll, TRUE, TRUE, 0);
        bot_view_ = view;

        status_bar_ = gtk_label_new("offline  ·  0 bot");
        gtk_widget_set_halign(status_bar_, GTK_ALIGN_START);
        gtk_widget_set_margin_start(status_bar_, 10);
        gtk_widget_set_margin_bottom(status_bar_, 6);
        gtk_box_pack_start(GTK_BOX(v), status_bar_, FALSE, FALSE, 0);
        return v;
    }

    GtkWidget *build_proxy_tab() {
        GtkWidget *v = gtk_box_new(GTK_ORIENTATION_VERTICAL, 8);
        gtk_widget_set_margin_start(v, 12);
        gtk_widget_set_margin_end(v, 12);
        gtk_widget_set_margin_top(v, 12);

        GtkWidget *judul = gtk_label_new(nullptr);
        gtk_label_set_markup(GTK_LABEL(judul),
                             "<b>Proxy SOCKS5 per bot</b>");
        gtk_widget_set_halign(judul, GTK_ALIGN_START);
        gtk_box_pack_start(GTK_BOX(v), judul, FALSE, FALSE, 0);

        GtkWidget *ket = gtk_label_new(
            "Format: host:port  ·  user:pass@host:port  ·  socks5://host:port");
        gtk_widget_set_halign(ket, GTK_ALIGN_START);
        gtk_style_context_add_class(gtk_widget_get_style_context(ket), "dim-label");
        gtk_box_pack_start(GTK_BOX(v), ket, FALSE, FALSE, 0);

        GtkWidget *baris = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
        gtk_box_pack_start(GTK_BOX(baris), gtk_label_new("Bot"), FALSE, FALSE, 0);
        bot_combo_ = gtk_combo_box_text_new();
        gtk_widget_set_size_request(bot_combo_, 160, -1);
        gtk_box_pack_start(GTK_BOX(baris), bot_combo_, FALSE, FALSE, 0);

        gtk_box_pack_start(GTK_BOX(baris), gtk_label_new("Proxy"), FALSE, FALSE, 0);
        proxy_entry_ = gtk_entry_new();
        gtk_entry_set_placeholder_text(GTK_ENTRY(proxy_entry_),
                                       "user:pass@127.0.0.1:1080");
        gtk_widget_set_hexpand(proxy_entry_, TRUE);
        gtk_box_pack_start(GTK_BOX(baris), proxy_entry_, TRUE, TRUE, 0);

        GtkWidget *uji_btn = gtk_button_new_with_label("Uji");
        GtkWidget *simpan_btn = gtk_button_new_with_label("Simpan");
        GtkWidget *hapus_btn = gtk_button_new_with_label("Hapus");
        g_signal_connect(uji_btn, "clicked", G_CALLBACK(on_test_proxy), this);
        g_signal_connect(simpan_btn, "clicked", G_CALLBACK(on_save_proxy), this);
        g_signal_connect(hapus_btn, "clicked", G_CALLBACK(on_clear_proxy), this);
        gtk_box_pack_start(GTK_BOX(baris), uji_btn, FALSE, FALSE, 0);
        gtk_box_pack_start(GTK_BOX(baris), simpan_btn, FALSE, FALSE, 0);
        gtk_box_pack_start(GTK_BOX(baris), hapus_btn, FALSE, FALSE, 0);
        gtk_box_pack_start(GTK_BOX(v), baris, FALSE, FALSE, 0);

        proxy_result_ = gtk_label_new("—");
        gtk_widget_set_halign(proxy_result_, GTK_ALIGN_START);
        gtk_box_pack_start(GTK_BOX(v), proxy_result_, FALSE, FALSE, 0);

        GtkWidget *peta = gtk_label_new(
            "Proxy dipakai saat connect: ENet menyalurkan seluruh trafik UDP "
            "game lewat SOCKS5 (UDP ASSOCIATE). Ganti proxy lalu Connect ulang.");
        gtk_label_set_line_wrap(GTK_LABEL(peta), TRUE);
        gtk_widget_set_halign(peta, GTK_ALIGN_START);
        gtk_style_context_add_class(gtk_widget_get_style_context(peta), "dim-label");
        gtk_box_pack_start(GTK_BOX(v), peta, FALSE, FALSE, 0);

        gtk_box_pack_start(GTK_BOX(v), gtk_separator_new(GTK_ORIENTATION_HORIZONTAL),
                           FALSE, FALSE, 8);
        proxy_log_ = gtk_label_new("");
        gtk_widget_set_halign(proxy_log_, GTK_ALIGN_START);
        gtk_box_pack_start(GTK_BOX(v), proxy_log_, FALSE, FALSE, 0);
        return v;
    }

    GtkWidget *build_executor_tab() {
        GtkWidget *v = gtk_box_new(GTK_ORIENTATION_VERTICAL, 6);
        gtk_widget_set_margin_start(v, 12);
        gtk_widget_set_margin_end(v, 12);
        gtk_widget_set_margin_top(v, 12);

        GtkWidget *bar = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
        gtk_box_pack_start(GTK_BOX(bar), gtk_label_new("Nama skrip"), FALSE, FALSE, 0);
        script_name_ = gtk_entry_new();
        gtk_entry_set_placeholder_text(GTK_ENTRY(script_name_), "contoh.lua");
        gtk_widget_set_size_request(script_name_, 220, -1);
        gtk_box_pack_start(GTK_BOX(bar), script_name_, FALSE, FALSE, 0);

        GtkWidget *simpan = gtk_button_new_with_label("Simpan");
        GtkWidget *jalankan = gtk_button_new_with_label("Jalankan");
        g_signal_connect(simpan, "clicked", G_CALLBACK(on_save_script), this);
        g_signal_connect(jalankan, "clicked", G_CALLBACK(on_run_script), this);
        gtk_box_pack_start(GTK_BOX(bar), simpan, FALSE, FALSE, 0);
        gtk_box_pack_start(GTK_BOX(bar), jalankan, FALSE, FALSE, 0);
        gtk_box_pack_start(GTK_BOX(v), bar, FALSE, FALSE, 0);

        GtkWidget *scroll = gtk_scrolled_window_new(nullptr, nullptr);
        script_view_ = gtk_text_view_new();
        gtk_text_view_set_monospace(GTK_TEXT_VIEW(script_view_), TRUE);
        gtk_container_add(GTK_CONTAINER(scroll), script_view_);
        gtk_box_pack_start(GTK_BOX(v), scroll, TRUE, TRUE, 0);

        exec_out_ = gtk_label_new("—");
        gtk_widget_set_halign(exec_out_, GTK_ALIGN_START);
        gtk_box_pack_start(GTK_BOX(v), exec_out_, FALSE, FALSE, 0);
        return v;
    }

    GtkWidget *build_log_tab() {
        GtkWidget *scroll = gtk_scrolled_window_new(nullptr, nullptr);
        log_view_ = gtk_text_view_new();
        gtk_text_view_set_editable(GTK_TEXT_VIEW(log_view_), FALSE);
        gtk_text_view_set_monospace(GTK_TEXT_VIEW(log_view_), TRUE);
        gtk_container_add(GTK_CONTAINER(scroll), log_view_);
        return scroll;
    }

    // -- backend ---------------------------------------------------------- //
    void start_backend() {
        // Cari interpreter: .venv repo dulu (punya lupa/requests), lalu python3.
        std::string py = repo_ + "/.venv/bin/python";
        if (access(py.c_str(), X_OK) != 0) py = "python3";

        std::vector<std::string> argv = {
            py, "-m", "lucifer.cli", "web", "--port", std::to_string(port_)};
        std::vector<char *> cargv;
        for (auto &a : argv) cargv.push_back(const_cast<char *>(a.c_str()));
        cargv.push_back(nullptr);

        GError *err = nullptr;
        gchar **envp = g_get_environ();
        gboolean ok = g_spawn_async(repo_.c_str(), cargv.data(), envp,
                                    static_cast<GSpawnFlags>(G_SPAWN_SEARCH_PATH | G_SPAWN_DO_NOT_REAP_CHILD),
                                    nullptr, nullptr, &child_pid_, &err);
        g_strfreev(envp);
        if (!ok) {
            if (err) {
                set_log(std::string("backend gagal dinyalakan: ") + err->message);
                g_error_free(err);
            }
            child_pid_ = 0;
            return;
        }
        set_log("backend Python dinyalakan (port " + std::to_string(port_) + ")");
    }

    // -- pemanggilan API -------------------------------------------------- //
    JsonObject *get_obj(const std::string &path) {
        HttpResponse r = http_.get(path);
        if (!r.ok()) return nullptr;
        JsonNode *n = parse(r.body);
        if (!n) return nullptr;
        JsonObject *o = JSON_NODE_HOLDS_OBJECT(n) ? json_node_get_object(n) : nullptr;
        if (o) json_object_ref(o);
        json_node_unref(n);
        return o;  // pemanggil: json_object_unref
    }

    bool post_ok(const std::string &path, const std::string &json, std::string *pesan) {
        HttpResponse r = http_.post(path, json);
        if (r.status == 0) {
            if (pesan) *pesan = "server lokal tidak menjawab";
            return false;
        }
        JsonNode *n = parse(r.body);
        bool ok = r.ok();
        if (n) {
            if (JSON_NODE_HOLDS_OBJECT(n)) {
                JsonObject *o = json_node_get_object(n);
                if (json_object_has_member(o, "ok"))
                    ok = json_object_get_boolean_member(o, "ok");
                if (pesan) {
                    std::string e = jstr(o, "error");
                    std::string p = jstr(o, "pesan");
                    *pesan = !e.empty() ? e : p;
                }
            }
            json_node_unref(n);
        }
        return ok;
    }

    // -- penyegaran data -------------------------------------------------- //
    static gboolean tick(gpointer data) {
        static_cast<App *>(data)->refresh();
        return G_SOURCE_CONTINUE;
    }

    void refresh() {
        JsonObject *root = get_obj("/api/status");
        if (!root) {
            gtk_label_set_text(GTK_LABEL(status_label_), "● server mati");
            gtk_label_set_text(GTK_LABEL(status_bar_), "backend tidak menjawab");
            return;
        }

        gtk_list_store_clear(store_);
        GtkTreeIter it;
        int online = 0;
        int total = 0;

        if (json_object_has_member(root, "bots")) {
            JsonArray *bots = json_object_get_array_member(root, "bots");
            for (guint i = 0; bots && i < json_array_get_length(bots); ++i) {
                JsonObject *b = json_array_get_object_element(bots, i);
                if (!b) continue;
                std::string status = jstr(b, "status");
                if (status == "online") ++online;
                ++total;
                gtk_list_store_append(store_, &it);
                gtk_list_store_set(store_, &it,
                                   COL_LABEL, jstr(b, "label").c_str(),
                                   COL_NAME, jstr(b, "name").c_str(),
                                   COL_STATUS, status.c_str(),
                                   COL_LEVEL, jstr(b, "level").c_str(),
                                   COL_PING, jstr(b, "ping").c_str(),
                                   COL_PROXY, jstr(b, "proxy").c_str(),
                                   COL_WORLD, jstr(b, "world").c_str(),
                                   COL_GEMS, jstr(b, "gems").c_str(),
                                   -1);
            }
        }
        json_object_unref(root);

        gtk_label_set_text(GTK_LABEL(status_label_),
                           online > 0 ? "● online" : "● offline");
        std::string bar = std::to_string(total) + " bot  ·  " +
                          std::to_string(online) + " online";
        gtk_label_set_text(GTK_LABEL(status_bar_), bar.c_str());
        sync_bot_combo();
        refresh_logs();
    }

    void sync_bot_combo() {
        GtkTreeModel *m = GTK_TREE_MODEL(store_);
        GtkTreeIter it;
        std::vector<std::string> labels;
        if (gtk_tree_model_get_iter_first(m, &it)) {
            do {
                gchar *s = nullptr;
                gtk_tree_model_get(m, &it, COL_LABEL, &s, -1);
                if (s) {
                    labels.emplace_back(s);
                    g_free(s);
                }
            } while (gtk_tree_model_iter_next(m, &it));
        }

        gchar *aktif = gtk_combo_box_text_get_active_text(GTK_COMBO_BOX_TEXT(bot_combo_));
        gtk_combo_box_text_remove_all(GTK_COMBO_BOX_TEXT(bot_combo_));
        int pilih = -1;
        for (size_t i = 0; i < labels.size(); ++i) {
            gtk_combo_box_text_append_text(GTK_COMBO_BOX_TEXT(bot_combo_),
                                           labels[i].c_str());
            if (aktif && labels[i] == aktif) pilih = static_cast<int>(i);
        }
        gtk_combo_box_set_active(GTK_COMBO_BOX(bot_combo_), pilih >= 0 ? pilih
                                                                       : (labels.empty() ? -1 : 0));
        g_free(aktif);
    }

    void refresh_logs() {
        JsonObject *root = get_obj("/api/logs");
        if (!root) return;
        std::string teks;
        if (json_object_has_member(root, "logs")) {
            JsonArray *arr = json_object_get_array_member(root, "logs");
            for (guint i = 0; arr && i < json_array_get_length(arr); ++i) {
                teks += json_array_get_string_element(arr, i);
                teks += "\n";
            }
        }
        json_object_unref(root);
        if (teks.empty()) return;

        GtkTextBuffer *buf = gtk_text_view_get_buffer(GTK_TEXT_VIEW(log_view_));
        gchar *lama = nullptr;
        GtkTextIter a, b;
        gtk_text_buffer_get_bounds(buf, &a, &b);
        lama = gtk_text_buffer_get_text(buf, &a, &b, FALSE);
        bool beda = !lama || teks != lama;
        g_free(lama);
        if (!beda) return;
        gtk_text_buffer_set_text(buf, teks.c_str(), -1);
        gtk_text_buffer_get_end_iter(buf, &a);
        gtk_text_view_scroll_to_iter(GTK_TEXT_VIEW(log_view_), &a, 0.0, FALSE, 0, 0);
    }

    void set_log(const std::string &s) {
        GtkTextBuffer *buf = gtk_text_view_get_buffer(GTK_TEXT_VIEW(log_view_));
        GtkTextIter end;
        gtk_text_buffer_get_end_iter(buf, &end);
        gtk_text_buffer_insert(buf, &end, (s + "\n").c_str(), -1);
    }

    std::string label_terpilih() {
        GtkTreeSelection *sel = gtk_tree_view_get_selection(GTK_TREE_VIEW(bot_view_));
        GtkTreeModel *m = nullptr;
        GtkTreeIter it;
        if (!gtk_tree_selection_get_selected(sel, &m, &it)) {
            gchar *aktif = gtk_combo_box_text_get_active_text(GTK_COMBO_BOX_TEXT(bot_combo_));
            std::string s = aktif ? aktif : "";
            g_free(aktif);
            return s;
        }
        gchar *s = nullptr;
        gtk_tree_model_get(m, &it, COL_LABEL, &s, -1);
        std::string out = s ? s : "";
        g_free(s);
        return out;
    }

    // -- callback --------------------------------------------------------- //
    static void on_add_bot(GtkButton *, gpointer data) {
        static_cast<App *>(data)->dialog_tambah_bot();
    }
    static void on_del_bot(GtkButton *, gpointer data) {
        App *a = static_cast<App *>(data);
        std::string label = a->label_terpilih();
        if (label.empty()) return;
        std::string pesan;
        a->post_ok("/api/account/delete", "{\"label\":\"" + label + "\"}", &pesan);
        a->set_log("hapus akun: " + label);
        a->refresh();
    }
    static void on_connect(GtkButton *, gpointer data) {
        App *a = static_cast<App *>(data);
        std::string label = a->label_terpilih();
        std::string pesan;
        bool ok = a->post_ok("/api/connect", "{\"label\":\"" + label + "\"}", &pesan);
        a->set_log(std::string(ok ? "connect" : "connect gagal") + ": " + label +
                   (pesan.empty() ? "" : " — " + pesan));
        a->refresh();
    }
    static void on_disconnect(GtkButton *, gpointer data) {
        App *a = static_cast<App *>(data);
        std::string label = a->label_terpilih();
        std::string pesan;
        a->post_ok("/api/disconnect", "{\"label\":\"" + label + "\"}", &pesan);
        a->set_log("disconnect: " + label);
        a->refresh();
    }
    static void on_refresh(GtkButton *, gpointer data) {
        static_cast<App *>(data)->refresh();
    }
    static void on_row_changed(GtkTreeView *, gpointer data) {
        App *a = static_cast<App *>(data);
        std::string label = a->label_terpilih();
        if (label.empty()) return;
        // tampilkan proxy bot terpilih di tab Proxy
        GtkTreeSelection *sel = gtk_tree_view_get_selection(GTK_TREE_VIEW(a->bot_view_));
        GtkTreeModel *m = nullptr;
        GtkTreeIter it;
        if (gtk_tree_selection_get_selected(sel, &m, &it)) {
            gchar *px = nullptr;
            gtk_tree_model_get(m, &it, COL_PROXY, &px, -1);
            gtk_entry_set_text(GTK_ENTRY(a->proxy_entry_), px ? px : "");
            g_free(px);
        }
        // pilih bot yang sama di combo executor
        int i = 0;
        for (const auto &l : a->combo_labels()) {
            if (l == label) {
                gtk_combo_box_set_active(GTK_COMBO_BOX(a->bot_combo_), i);
                break;
            }
            ++i;
        }
    }

    std::vector<std::string> combo_labels() {
        std::vector<std::string> out;
        GtkTreeModel *m = GTK_TREE_MODEL(store_);
        GtkTreeIter it;
        if (gtk_tree_model_get_iter_first(m, &it)) {
            do {
                gchar *s = nullptr;
                gtk_tree_model_get(m, &it, COL_LABEL, &s, -1);
                if (s) {
                    out.emplace_back(s);
                    g_free(s);
                }
            } while (gtk_tree_model_iter_next(m, &it));
        }
        return out;
    }

    static void on_test_proxy(GtkButton *, gpointer data) {
        App *a = static_cast<App *>(data);
        std::string px = gtk_entry_get_text(GTK_ENTRY(a->proxy_entry_));
        if (px.empty()) {
            gtk_label_set_text(GTK_LABEL(a->proxy_result_), "isi proxy dulu");
            return;
        }
        std::string pesan;
        bool ok = a->post_ok("/api/proxy", "{\"proxy\":\"" + px + "\"}", &pesan);
        std::string hasil = (ok ? "\u2713 " : "\u2717 ") + pesan;
        gtk_label_set_text(GTK_LABEL(a->proxy_result_), hasil.c_str());
    }

    static void on_save_proxy(GtkButton *, gpointer data) {
        App *a = static_cast<App *>(data);
        std::string label = a->label_terpilih();
        if (label.empty()) {
            gtk_label_set_text(GTK_LABEL(a->proxy_result_), "pilih bot dulu");
            return;
        }
        std::string px = gtk_entry_get_text(GTK_ENTRY(a->proxy_entry_));
        std::string pesan;
        bool ok = a->post_ok("/api/proxy",
                             "{\"label\":\"" + label + "\",\"proxy\":\"" + px + "\"}",
                             &pesan);
        gtk_label_set_text(GTK_LABEL(a->proxy_result_),
                           ok ? ("✓ disimpan untuk " + label).c_str() : ("✗ " + pesan).c_str());
        a->refresh();
    }

    static void on_clear_proxy(GtkButton *, gpointer data) {
        App *a = static_cast<App *>(data);
        std::string label = a->label_terpilih();
        if (label.empty()) return;
        std::string pesan;
        a->post_ok("/api/proxy", "{\"label\":\"" + label + "\",\"proxy\":\"\"}", &pesan);
        gtk_entry_set_text(GTK_ENTRY(a->proxy_entry_), "");
        gtk_label_set_text(GTK_LABEL(a->proxy_result_), "proxy dihapus");
        a->refresh();
    }

    static void on_save_script(GtkButton *, gpointer data) {
        App *a = static_cast<App *>(data);
        std::string nama = gtk_entry_get_text(GTK_ENTRY(a->script_name_));
        if (nama.empty()) {
            gtk_label_set_text(GTK_LABEL(a->exec_out_), "isi nama skrip dulu");
            return;
        }
        GtkTextBuffer *buf = gtk_text_view_get_buffer(GTK_TEXT_VIEW(a->script_view_));
        GtkTextIter s, e;
        gtk_text_buffer_get_bounds(buf, &s, &e);
        gchar *isi = gtk_text_buffer_get_text(buf, &s, &e, FALSE);
        JsonBuilder *b = json_builder_new();
        json_builder_begin_object(b);
        json_builder_set_member_name(b, "name");
        json_builder_add_string_value(b, nama.c_str());
        json_builder_set_member_name(b, "content");
        json_builder_add_string_value(b, isi ? isi : "");
        json_builder_end_object(b);
        JsonGenerator *gen = json_generator_new();
        json_generator_set_root(gen, json_builder_get_root(b));
        gchar *json = json_generator_to_data(gen, nullptr);
        std::string pesan;
        bool ok = a->post_ok("/api/script/save", json, &pesan);
        gtk_label_set_text(GTK_LABEL(a->exec_out_),
                           ok ? "tersimpan" : ("gagal: " + pesan).c_str());
        g_free(json);
        g_object_unref(gen);
        g_object_unref(b);
        g_free(isi);
    }

    static void on_run_script(GtkButton *, gpointer data) {
        App *a = static_cast<App *>(data);
        std::string nama = gtk_entry_get_text(GTK_ENTRY(a->script_name_));
        if (nama.empty()) {
            gtk_label_set_text(GTK_LABEL(a->exec_out_), "isi nama skrip dulu");
            return;
        }
        on_save_script(nullptr, data);
        std::string pesan;
        bool ok = a->post_ok("/api/command",
                             "{\"command\":\"run " + nama + "\"}", &pesan);
        gtk_label_set_text(GTK_LABEL(a->exec_out_),
                           ok ? ("dijalankan: " + nama).c_str() : ("gagal: " + pesan).c_str());
    }

    // Dialog tambah bot: label, ltoken/username, password, proxy.
    void dialog_tambah_bot() {
        GtkWidget *d = gtk_dialog_new_with_buttons(
            "Tambah Bot", GTK_WINDOW(window_),
            static_cast<GtkDialogFlags>(GTK_DIALOG_MODAL | GTK_DIALOG_DESTROY_WITH_PARENT),
            "_Batal", GTK_RESPONSE_CANCEL, "_Tambah", GTK_RESPONSE_ACCEPT, nullptr);
        GtkWidget *grid = gtk_grid_new();
        gtk_grid_set_row_spacing(GTK_GRID(grid), 8);
        gtk_grid_set_column_spacing(GTK_GRID(grid), 8);
        gtk_widget_set_margin_start(grid, 14);
        gtk_widget_set_margin_end(grid, 14);
        gtk_widget_set_margin_top(grid, 14);
        gtk_widget_set_margin_bottom(grid, 14);

        GtkWidget *e_label = gtk_entry_new();
        GtkWidget *e_token = gtk_entry_new();
        GtkWidget *e_user = gtk_entry_new();
        GtkWidget *e_pass = gtk_entry_new();
        GtkWidget *e_proxy = gtk_entry_new();
        gtk_entry_set_placeholder_text(GTK_ENTRY(e_proxy), "opsional — socks5://host:port");
        gtk_entry_set_visibility(GTK_ENTRY(e_pass), FALSE);

        const char *judul[] = {"Label", "ltoken", "GrowID", "Sandi", "Proxy SOCKS5"};
        GtkWidget *entry[] = {e_label, e_token, e_user, e_pass, e_proxy};
        for (int i = 0; i < 5; ++i) {
            gtk_grid_attach(GTK_GRID(grid), gtk_label_new(judul[i]), 0, i, 1, 1);
            gtk_widget_set_hexpand(entry[i], TRUE);
            gtk_widget_set_size_request(entry[i], 320, -1);
            gtk_grid_attach(GTK_GRID(grid), entry[i], 1, i, 1, 1);
        }
        gtk_container_add(GTK_CONTAINER(gtk_dialog_get_content_area(GTK_DIALOG(d))), grid);
        gtk_widget_show_all(d);

        if (gtk_dialog_run(GTK_DIALOG(d)) == GTK_RESPONSE_ACCEPT) {
            JsonBuilder *b = json_builder_new();
            json_builder_begin_object(b);
            auto put = [&](const char *k, GtkWidget *e) {
                json_builder_set_member_name(b, k);
                json_builder_add_string_value(b, gtk_entry_get_text(GTK_ENTRY(e)));
            };
            put("label", e_label);
            put("ltoken", e_token);
            put("username", e_user);
            put("password", e_pass);
            put("proxy", e_proxy);
            json_builder_set_member_name(b, "method");
            json_builder_add_string_value(b, "growid");
            json_builder_set_member_name(b, "connect");
            json_builder_add_boolean_value(b, FALSE);
            json_builder_end_object(b);

            JsonGenerator *gen = json_generator_new();
            json_generator_set_root(gen, json_builder_get_root(b));
            gchar *json = json_generator_to_data(gen, nullptr);
            std::string pesan;
            bool ok = post_ok("/api/login", json, &pesan);
            set_log(ok ? "akun ditambahkan" : ("gagal tambah akun: " + pesan));
            g_free(json);
            g_object_unref(gen);
            g_object_unref(b);
            refresh();
        }
        gtk_widget_destroy(d);
    }

    // -- state ------------------------------------------------------------ //
    Http http_;
    bool spawn_ = false;
    std::string repo_;
    int port_ = 8787;
    GPid child_pid_ = 0;

    GtkWidget *window_ = nullptr;
    GtkWidget *notebook_ = nullptr;
    GtkWidget *status_label_ = nullptr;
    GtkWidget *status_bar_ = nullptr;
    GtkWidget *bot_view_ = nullptr;
    GtkWidget *bot_combo_ = nullptr;
    GtkWidget *proxy_entry_ = nullptr;
    GtkWidget *proxy_result_ = nullptr;
    GtkWidget *proxy_log_ = nullptr;
    GtkWidget *script_name_ = nullptr;
    GtkWidget *script_view_ = nullptr;
    GtkWidget *exec_out_ = nullptr;
    GtkWidget *log_view_ = nullptr;
    GtkListStore *store_ = nullptr;
};

}  // namespace

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

    App app(url, spawn, repo, port);
    return app.run(argc, argv);
}
