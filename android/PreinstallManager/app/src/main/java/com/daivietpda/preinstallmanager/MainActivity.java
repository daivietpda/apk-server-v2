package com.daivietpda.preinstallmanager;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.graphics.Color;
import android.os.Bundle;
import android.os.FileObserver;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONObject;

/** UI for the untrusted, display-only status channel published by factoryreset.conf. */
public final class MainActivity extends Activity {
    private static final String TRIGGER_FILE = "run";
    private static final String RUNTIME_DIRECTORY = "preinstall-v2";
    private static final String STATUS_FILE = "status.json";
    private static final String LOG_FILE = "ui.log";
    private static final int MAX_LOG_BYTES = 64 * 1024;
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private TextView statusView;
    private TextView logView;
    private Button runButton;
    private File runtimeDirectory;
    private FileObserver observer;
    private boolean active;
    private String lastRenderKey = "";
    private final Runnable poller = new Runnable() {
        @Override public void run() {
            refreshStatus();
            if (active) mainHandler.postDelayed(this, 2000);
        }
    };

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        File external = getExternalFilesDir(null);
        if (external != null) {
            runtimeDirectory = new File(external, RUNTIME_DIRECTORY);
            runtimeDirectory.mkdirs();
        }
        setContentView(createLayout());
        refreshStatus();
    }

    @Override protected void onResume() {
        super.onResume();
        active = true;
        startObserver();
        mainHandler.removeCallbacks(poller);
        mainHandler.post(poller);
    }

    @Override protected void onPause() {
        active = false;
        mainHandler.removeCallbacks(poller);
        stopObserver();
        super.onPause();
    }

    private View createLayout() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(36, 30, 36, 30);
        root.setBackgroundColor(0xff102027);

        TextView title = text(getString(R.string.title), 27, Color.WHITE);
        title.setGravity(Gravity.CENTER);
        root.addView(title, new LinearLayout.LayoutParams(-1, -2));

        statusView = text(getString(R.string.loading), 16, 0xffe0e0e0);
        LinearLayout.LayoutParams statusParams = new LinearLayout.LayoutParams(-1, -2);
        statusParams.setMargins(0, 20, 0, 16);
        root.addView(statusView, statusParams);

        LinearLayout buttons = new LinearLayout(this);
        buttons.setGravity(Gravity.CENTER);
        buttons.setOrientation(LinearLayout.HORIZONTAL);
        runButton = button(getString(R.string.run_update), v -> triggerUpdate());
        buttons.addView(runButton, buttonParams());
        Button refresh = button(getString(R.string.refresh_status), v -> refreshStatus());
        buttons.addView(refresh, buttonParams());
        Button copy = button(getString(R.string.copy_log), v -> copyLog());
        buttons.addView(copy, buttonParams());
        root.addView(buttons, new LinearLayout.LayoutParams(-1, -2));

        TextView logTitle = text(getString(R.string.live_log), 18, Color.WHITE);
        LinearLayout.LayoutParams logTitleParams = new LinearLayout.LayoutParams(-1, -2);
        logTitleParams.setMargins(0, 24, 0, 8);
        root.addView(logTitle, logTitleParams);

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        logView = text("", 13, 0xffd0d0d0);
        logView.setPadding(18, 18, 18, 18);
        logView.setBackgroundColor(0xff182b32);
        scroll.addView(logView, new ScrollView.LayoutParams(-1, -2));
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1f));
        return root;
    }

    private TextView text(String value, int size, int color) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        return view;
    }

    private Button button(String label, View.OnClickListener listener) {
        Button view = new Button(this);
        view.setText(label);
        view.setTextSize(13);
        view.setOnClickListener(listener);
        view.setOnFocusChangeListener((focused, hasFocus) -> {
            focused.setScaleX(hasFocus ? 1.05f : 1f);
            focused.setScaleY(hasFocus ? 1.05f : 1f);
        });
        return view;
    }

    private LinearLayout.LayoutParams buttonParams() {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, 70, 1f);
        params.setMargins(6, 0, 6, 0);
        return params;
    }

    private void triggerUpdate() {
        runButton.setEnabled(false);
        statusView.setText(getString(R.string.requesting));
        executor.execute(() -> {
            String error = createTriggerMarker();
            mainHandler.post(() -> {
                runButton.setEnabled(true);
                if (error == null) {
                    Toast.makeText(this, R.string.request_sent, Toast.LENGTH_SHORT).show();
                    refreshStatus();
                } else {
                    statusView.setText(getString(R.string.request_failed, error));
                }
            });
        });
    }

    /** Creates only an atomic, parameter-free marker. The listener owns all authority. */
    private String createTriggerMarker() {
        File external = getExternalFilesDir(null);
        if (external == null) return "External storage unavailable";
        File temporary = new File(external, TRIGGER_FILE + ".tmp");
        File marker = new File(external, TRIGGER_FILE);
        try (FileOutputStream output = new FileOutputStream(temporary, false)) {
            output.write((Long.toString(System.currentTimeMillis()) + "\n").getBytes(StandardCharsets.UTF_8));
            output.getFD().sync();
            if (marker.exists() && !marker.delete()) return "Cannot replace previous request";
            if (!temporary.renameTo(marker)) return "Cannot publish request marker";
            return null;
        } catch (Exception error) {
            temporary.delete();
            return error.getClass().getSimpleName();
        }
    }

    private void startObserver() {
        if (runtimeDirectory == null || observer != null) return;
        observer = new FileObserver(runtimeDirectory.getAbsolutePath(), FileObserver.CLOSE_WRITE | FileObserver.MOVED_TO | FileObserver.CREATE) {
            @Override public void onEvent(int event, String path) {
                if (STATUS_FILE.equals(path) || LOG_FILE.equals(path)) mainHandler.post(MainActivity.this::refreshStatus);
            }
        };
        observer.startWatching();
    }

    private void stopObserver() {
        if (observer != null) { observer.stopWatching(); observer = null; }
    }

    private void refreshStatus() {
        executor.execute(() -> {
            StatusSnapshot snapshot = readSnapshot();
            mainHandler.post(() -> render(snapshot));
        });
    }

    private StatusSnapshot readSnapshot() {
        if (runtimeDirectory == null) return new StatusSnapshot("unknown", "storage", "", getString(R.string.storage_unavailable), "", "");
        try {
            File status = new File(runtimeDirectory, STATUS_FILE);
            String raw = status.isFile() ? new String(Files.readAllBytes(status.toPath()), StandardCharsets.UTF_8) : "";
            JSONObject json = raw.isEmpty() ? new JSONObject() : new JSONObject(raw);
            String log = readLimited(new File(runtimeDirectory, LOG_FILE));
            return new StatusSnapshot(json.optString("state", "idle"), json.optString("phase", "idle"), json.optString("packageName", ""), json.optString("message", getString(R.string.no_status)), json.optString("releaseId", ""), log);
        } catch (Exception error) {
            return new StatusSnapshot("unknown", "read-error", "", error.getClass().getSimpleName(), "", "");
        }
    }

    private static String readLimited(File file) throws Exception {
        if (!file.isFile()) return "";
        byte[] all = Files.readAllBytes(file.toPath());
        int start = Math.max(0, all.length - MAX_LOG_BYTES);
        return new String(all, start, all.length - start, StandardCharsets.UTF_8);
    }

    private void render(StatusSnapshot item) {
        String renderKey = item.state + "\u0000" + item.phase + "\u0000" + item.packageName + "\u0000"
                + item.message + "\u0000" + item.releaseId + "\u0000" + item.log;
        if (renderKey.equals(lastRenderKey)) return;
        lastRenderKey = renderKey;
        String packageLine = item.packageName.isEmpty() ? "" : getString(R.string.package_line, item.packageName);
        String releaseLine = item.releaseId.isEmpty() ? "" : getString(R.string.release_line, item.releaseId);
        statusView.setText(getString(R.string.status_summary, localizeState(item.state), localizePhase(item.phase),
                packageLine, releaseLine, localizeMessage(item.message)));
        logView.setText(item.log.isEmpty() ? getString(R.string.no_log) : item.log);
    }

    private String localizeState(String value) {
        switch (value) {
            case "idle": return getString(R.string.state_idle);
            case "running": return getString(R.string.state_running);
            case "complete": return getString(R.string.state_complete);
            case "failed": return getString(R.string.state_failed);
            default: return getString(R.string.state_unknown);
        }
    }

    private String localizePhase(String value) {
        switch (value) {
            case "idle": return getString(R.string.phase_idle);
            case "local-scan": return getString(R.string.phase_local_scan);
            case "manifest": return getString(R.string.phase_manifest);
            case "download-payload": return getString(R.string.phase_download);
            case "verify": return getString(R.string.phase_verify);
            case "install": return getString(R.string.phase_install);
            case "uninstall": return getString(R.string.phase_uninstall);
            case "complete": return getString(R.string.phase_complete);
            case "error":
            case "read-error": return getString(R.string.phase_error);
            default: return value;
        }
    }

    private String localizeMessage(String value) {
        switch (value) {
            case "Starting preinstall": return getString(R.string.message_starting);
            case "Installing local APK": return getString(R.string.message_local_install);
            case "Downloading payload": return getString(R.string.message_download);
            case "Applying uninstall policy": return getString(R.string.message_uninstall);
            case "Installing verified payload": return getString(R.string.message_install);
            case "Preinstall complete": return getString(R.string.message_complete);
            case "Preinstall finished with errors": return getString(R.string.message_failed);
            default: return value;
        }
    }

    private void copyLog() {
        ClipboardManager clipboard = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        clipboard.setPrimaryClip(ClipData.newPlainText(getString(R.string.clipboard_label), logView.getText()));
        Toast.makeText(this, R.string.log_copied, Toast.LENGTH_SHORT).show();
    }

    @Override protected void onDestroy() {
        mainHandler.removeCallbacksAndMessages(null);
        executor.shutdownNow();
        super.onDestroy();
    }

    private static final class StatusSnapshot {
        final String state, phase, packageName, message, releaseId, log;
        StatusSnapshot(String state, String phase, String packageName, String message, String releaseId, String log) {
            this.state = state; this.phase = phase; this.packageName = packageName; this.message = message; this.releaseId = releaseId; this.log = log;
        }
    }
}