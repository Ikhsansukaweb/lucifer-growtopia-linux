package id.lucifer.pushtoken;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;

/** Nyalakan pemantau otomatis setelah HP boot / app di-update. */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context c, Intent i) {
        SharedPreferences p = c.getSharedPreferences(MainActivity.PREFS, Context.MODE_PRIVATE);
        if (p.getString(MainActivity.KEY_URL, "").isEmpty()) return;
        c.startForegroundService(new Intent(c, PushService.class));
    }
}
