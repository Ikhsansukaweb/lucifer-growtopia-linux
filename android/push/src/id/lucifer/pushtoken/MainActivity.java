package id.lucifer.pushtoken;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

/** Satu layar: URL tunnel, tombol nyala/mati, kotak log. */
public class MainActivity extends Activity {

    static final String PREFS = "lucifer";
    static final String KEY_URL = "url";

    static TextView logView;
    static final Handler UI = new Handler(Looper.getMainLooper());

    static void log(String s) {
        UI.post(() -> {
            if (logView == null) return;
            logView.append(s + "\n");
            android.text.Layout l = logView.getLayout();
            if (l != null) {
                int y = l.getLineTop(logView.getLineCount()) - logView.getHeight();
                logView.scrollTo(0, Math.max(0, y));
            }
        });
    }

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        SharedPreferences p = getSharedPreferences(PREFS, MODE_PRIVATE);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (16 * getResources().getDisplayMetrics().density);
        root.setPadding(pad, pad, pad, pad);

        TextView judul = new TextView(this);
        judul.setText("Lucifer Token Push");
        judul.setTextSize(20);
        root.addView(judul);

        EditText url = new EditText(this);
        url.setHint("https://xxxx.trycloudflare.com");
        url.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        url.setSingleLine(true);
        url.setText(p.getString(KEY_URL, ""));
        root.addView(url);

        Button simpan = new Button(this);
        simpan.setText("Simpan");
        root.addView(simpan);

        Button nyala = new Button(this);
        nyala.setText("Nyalakan pemantau");
        root.addView(nyala);

        Button mati = new Button(this);
        mati.setText("Matikan");
        root.addView(mati);

        Button kirim = new Button(this);
        kirim.setText("Kirim sekarang");
        root.addView(kirim);

        logView = new TextView(this);
        logView.setTextSize(11);
        logView.setGravity(Gravity.TOP);
        ScrollView sc = new ScrollView(this);
        sc.addView(logView, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f);
        lp.topMargin = pad;
        root.addView(sc, lp);

        setContentView(root);

        simpan.setOnClickListener(v -> {
            p.edit().putString(KEY_URL, url.getText().toString().trim()).apply();
            log("disimpan");
        });

        nyala.setOnClickListener(v -> {
            p.edit().putString(KEY_URL, url.getText().toString().trim()).apply();
            startForegroundService(new Intent(this, PushService.class));
            log("pemantau nyala");
        });

        mati.setOnClickListener(v -> {
            stopService(new Intent(this, PushService.class));
            log("pemantau mati");
        });

        kirim.setOnClickListener(v -> {
            p.edit().putString(KEY_URL, url.getText().toString().trim()).apply();
            PushService.kirimSekarang(this);
        });
    }
}
