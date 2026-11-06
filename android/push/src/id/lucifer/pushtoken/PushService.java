package id.lucifer.pushtoken;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

/**
 * Pantau save.dat Growtopia. Setiap kali berkasnya berubah (artinya ada
 * login/akun baru), ambil refreshToken lalu kirim ke Lucifer lewat tunnel.
 *
 * ponytail: cek tiap 5 detik dengan membandingkan lastModified — cukup untuk
 * satu berkas. Ganti ke FileObserver kalau perlu hemat baterai.
 */
public class PushService extends Service {

    static final String SAVEDAT = "/sdcard/Android/data/com.rtsoft.growtopia/files/save.dat";
    static final int NOTIF = 41;
    static final String CHAN = "push";

    /** Dipakai tombol "Kirim sekarang". */
    static void kirimSekarang(Context c) {
        new Thread(() -> {
            String r = sekali(c, true);
            MainActivity.log(r);
        }).start();
    }

    private final Handler h = new Handler(Looper.getMainLooper());
    static long lastMtime = -1;
    static String lastToken = "";
    private volatile boolean jalan = true;

    private final Runnable tik = new Runnable() {
        @Override public void run() {
            new Thread(() -> {
                String r = sekali(PushService.this, false);
                if (!r.isEmpty()) MainActivity.log(r);
            }).start();
            if (jalan) h.postDelayed(this, 5000);
        }
    };

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel ch = new NotificationChannel(
                    CHAN, "Lucifer", NotificationManager.IMPORTANCE_MIN);
            getSystemService(NotificationManager.class).createNotificationChannel(ch);
            Notification n = new Notification.Builder(this, CHAN)
                    .setContentTitle("Lucifer Token Push")
                    .setContentText("memantau save.dat Growtopia")
                    .setSmallIcon(android.R.drawable.stat_sys_upload)
                    .setOngoing(true).build();
            startForeground(NOTIF, n);
        }
        jalan = true;
        h.removeCallbacks(tik);
        h.post(tik);
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        jalan = false;
        h.removeCallbacks(tik);
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent i) { return null; }

    /** Baca save.dat, kirim kalau token berubah. Return pesan untuk log. */
    static String sekali(Context c, boolean paksa) {
        SharedPreferences p = c.getSharedPreferences(MainActivity.PREFS, Context.MODE_PRIVATE);
        String base = p.getString(MainActivity.KEY_URL, "").trim();
        if (base.isEmpty()) return "URL belum diisi";

        if (c.checkSelfPermission(android.Manifest.permission.READ_EXTERNAL_STORAGE)
                != PackageManager.PERMISSION_GRANTED) {
            return "izin penyimpanan belum diberikan";
        }

        File f = new File(SAVEDAT);
        if (!f.exists()) return "save.dat tidak ada — buka Growtopia dulu";
        long mtime = f.lastModified();

        String isi;
        try {
            isi = new String(Files.readAllBytes(f.toPath()), StandardCharsets.ISO_8859_1);
        } catch (Exception e) {
            return "gagal baca: " + e.getClass().getSimpleName();
        }

        String token = nilai(isi, "Token");
        String tankid = nilai(isi, "tankid_name");
        String rid = nilai(isi, "rid");
        if (token.isEmpty()) return "Token tidak ada di save.dat";

        if (!paksa && token.equals(lastToken) && mtime == lastMtime) return "";
        lastToken = token;
        lastMtime = mtime;

        try {
            JSONObject o = new JSONObject();
            o.put("refresh", token);
            o.put("tankid", tankid);
            o.put("rid", rid);

            URL u = new URL(base.replaceAll("/+$", "") + "/api/push/ltoken");
            HttpURLConnection k = (HttpURLConnection) u.openConnection();
            k.setRequestMethod("POST");
            k.setConnectTimeout(15000);
            k.setReadTimeout(25000);
            k.setDoOutput(true);
            k.setRequestProperty("Content-Type", "application/json");
            byte[] body = o.toString().getBytes(StandardCharsets.UTF_8);
            try (OutputStream os = k.getOutputStream()) { os.write(body); }

            int kode = k.getResponseCode();
            InputStream in = kode < 400 ? k.getInputStream() : k.getErrorStream();
            String balas = baca(in);
            k.disconnect();

            if (kode == 200) return "terkirim: " + tankid + " — " + potong(balas);
            return "HTTP " + kode + " — " + potong(balas);
        } catch (Exception e) {
            return "gagal kirim: " + e.getClass().getSimpleName() + " " + e.getMessage();
        }
    }

    private static String baca(InputStream in) throws Exception {
        if (in == null) return "";
        ByteArrayOutputStream o = new ByteArrayOutputStream();
        byte[] b = new byte[4096];
        int n;
        while ((n = in.read(b)) > 0) o.write(b, 0, n);
        return new String(o.toByteArray(), StandardCharsets.UTF_8);
    }

    private static String potong(String s) {
        s = s.replace('\n', ' ');
        return s.length() > 160 ? s.substring(0, 160) : s;
    }

    /**
     * Ambil nilai field dari save.dat.
     *
     * Format: &lt;u32 tipe&gt;&lt;u32 panjang nama&gt;&lt;nama&gt;&lt;u32 panjang&gt;&lt;nilai&gt;.
     * Dicari dengan memindai nama lalu membaca panjang di belakangnya, sama
     * seperti `token_dari_savedat()` di Python.
     */
    static String nilai(String isi, String field) {
        int dari = 0;
        while (true) {
            int i = isi.indexOf(field, dari);
            if (i < 0) return "";
            dari = i + 1;
            // FCMToken bukan field "Token"
            if (field.equals("Token") && i >= 3 && isi.startsWith("FCM", i - 3)) continue;
            for (int off = field.length(); off <= field.length() + 5; off++) {
                if (i + off + 4 > isi.length()) break;
                long n = (long) (isi.charAt(i + off) & 0xff)
                        | (long) (isi.charAt(i + off + 1) & 0xff) << 8
                        | (long) (isi.charAt(i + off + 2) & 0xff) << 16
                        | (long) (isi.charAt(i + off + 3) & 0xff) << 24;
                if (n > 0 && n < 4000 && i + off + 4 + n <= isi.length()) {
                    return isi.substring(i + off + 4, (int) (i + off + 4 + n));
                }
            }
        }
    }
}
