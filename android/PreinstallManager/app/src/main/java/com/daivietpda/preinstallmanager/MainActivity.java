package com.daivietpda.preinstallmanager;

import android.app.Activity;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;



import android.content.res.ColorStateList;
import android.graphics.Color;
import android.os.Bundle;
import android.os.FileObserver;
import android.os.Handler;
import android.os.Looper;
import android.os.Build;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TableLayout;
import android.widget.TableRow;
import android.widget.TextView;
import android.widget.Toast;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.text.Collator;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
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
    private TextView logTitle;
    private TextView logView;
    private ScrollView logScrollView;
    private TextView appsTitle;
    private TextView appsSummary;
    private ScrollView appsScrollView;
    private TableLayout appsTable;
    private Button runButton;
    private Button viewAppsButton;
    private File runtimeDirectory;
    private FileObserver observer;
    private boolean active;
    private boolean showingApps;
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
        Button refresh = button(getString(R.string.refresh_status), v -> {
            refreshStatus();
            if (showingApps) refreshInstalledApps(); else scrollLogToBottom();
        });
        buttons.addView(refresh, buttonParams());
        viewAppsButton = button(getString(R.string.view_apps), v -> {
            if (showingApps) showLiveLog(); else showInstalledApps();
        });
        buttons.addView(viewAppsButton, buttonParams());
        root.addView(buttons, new LinearLayout.LayoutParams(-1, -2));

        LinearLayout contentPanel = new LinearLayout(this);
        contentPanel.setOrientation(LinearLayout.VERTICAL);
        root.addView(contentPanel, new LinearLayout.LayoutParams(-1, 0, 1f));

        logTitle = text(getString(R.string.live_log), 18, Color.WHITE);
        LinearLayout.LayoutParams logTitleParams = new LinearLayout.LayoutParams(-1, -2);
        logTitleParams.setMargins(0, 24, 0, 8);
        contentPanel.addView(logTitle, logTitleParams);

        logScrollView = new ScrollView(this);
        logScrollView.setFillViewport(true);
        logView = text("", 13, 0xffd0d0d0);
        logView.setPadding(18, 18, 18, 18);
        logView.setBackgroundColor(0xff182b32);
        logScrollView.addView(logView, new ScrollView.LayoutParams(-1, -2));
        contentPanel.addView(logScrollView, new LinearLayout.LayoutParams(-1, 0, 1f));

        appsTitle = text(getString(R.string.installed_apps_title), 18, Color.WHITE);
        appsTitle.setVisibility(View.GONE);
        LinearLayout.LayoutParams appsTitleParams = new LinearLayout.LayoutParams(-1, -2);
        appsTitleParams.setMargins(0, 24, 0, 8);
        contentPanel.addView(appsTitle, appsTitleParams);

        appsSummary = text(getString(R.string.installed_apps_loading), 14, 0xffd0d0d0);
        appsSummary.setVisibility(View.GONE);
        contentPanel.addView(appsSummary, new LinearLayout.LayoutParams(-1, -2));

        appsScrollView = new ScrollView(this);
        appsScrollView.setFillViewport(true);
        appsTable = new TableLayout(this);
        appsTable.setStretchAllColumns(false);
        appsTable.setShrinkAllColumns(false);
        appsScrollView.addView(appsTable, new ScrollView.LayoutParams(-1, -2));
        appsScrollView.setVisibility(View.GONE);
        contentPanel.addView(appsScrollView, new LinearLayout.LayoutParams(-1, 0, 1f));
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
        view.setBackgroundResource(R.drawable.tv_button_background);
        view.setBackgroundTintList(null);
        view.setTextColor(new ColorStateList(
                new int[][] {
                        new int[] { android.R.attr.state_focused },
                        new int[] { android.R.attr.state_pressed },
                        new int[] {}
                },
                new int[] { Color.BLACK, Color.BLACK, Color.WHITE }));
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
                    if (showingApps) refreshInstalledApps();
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

    private void showInstalledApps() {
        showingApps = true;
        logTitle.setVisibility(View.GONE);
        logScrollView.setVisibility(View.GONE);
        appsTitle.setVisibility(View.VISIBLE);
        appsSummary.setVisibility(View.VISIBLE);
        appsScrollView.setVisibility(View.VISIBLE);
        viewAppsButton.setText(R.string.live_log);
        refreshInstalledApps();
    }

    private void showLiveLog() {
        showingApps = false;
        appsTitle.setVisibility(View.GONE);
        appsSummary.setVisibility(View.GONE);
        appsScrollView.setVisibility(View.GONE);
        logTitle.setVisibility(View.VISIBLE);
        logScrollView.setVisibility(View.VISIBLE);
        viewAppsButton.setText(R.string.view_apps);
        scrollLogToBottom();
    }

    private void refreshInstalledApps() {
        appsSummary.setText(R.string.installed_apps_loading);
        executor.execute(() -> {
            try {
                List<AppEntry> entries = loadInstalledApps();
                mainHandler.post(() -> renderInstalledApps(entries));
            } catch (Throwable error) {
                mainHandler.post(() -> {
                    appsSummary.setText(getString(R.string.installed_apps_error, error.toString()));
                    appsTable.removeAllViews();
                });
            }
        });
    }

    private List<AppEntry> loadInstalledApps() {
        PackageManager packageManager = getPackageManager();
        List<PackageInfo> packages = packageManager.getInstalledPackages(0);
        List<AppEntry> entries = new ArrayList<>();
        for (PackageInfo packageInfo : packages) {
            ApplicationInfo applicationInfo = packageInfo.applicationInfo;
            if (applicationInfo == null || packageInfo.packageName == null) continue;
            CharSequence label = packageManager.getApplicationLabel(applicationInfo);
            String labelText = label == null ? packageInfo.packageName : label.toString().trim();
            if (labelText.isEmpty()) labelText = packageInfo.packageName;
            long versionCode = Build.VERSION.SDK_INT >= 28
                    ? packageInfo.getLongVersionCode() : packageInfo.versionCode;
            String versionName = packageInfo.versionName == null || packageInfo.versionName.trim().isEmpty()
                    ? getString(R.string.unknown) : packageInfo.versionName.trim();
            boolean system = (applicationInfo.flags & ApplicationInfo.FLAG_SYSTEM) != 0;
            entries.add(new AppEntry(labelText, packageInfo.packageName, versionName, versionCode, system));
        }
        Collator collator = Collator.getInstance();
        Collections.sort(entries, (left, right) -> {
            if (left.system != right.system) return left.system ? 1 : -1;
            int labelCompare = collator.compare(left.label, right.label);
            return labelCompare != 0 ? labelCompare : left.packageName.compareToIgnoreCase(right.packageName);
        });
        return entries;
    }

    private void renderInstalledApps(List<AppEntry> entries) {
        appsTable.removeAllViews();
        appsSummary.setText(getString(R.string.installed_apps_summary, entries.size()));
        if (entries.isEmpty()) {
            TextView empty = text(getString(R.string.installed_apps_empty), 15, 0xffd0d0d0);
            empty.setPadding(12, 16, 12, 16);
            appsTable.addView(empty, new TableLayout.LayoutParams(-1, -2));
            return;
        }

        TableRow header = new TableRow(this);
        header.setBackgroundColor(0xff00695c);
        addTableCell(header, getString(R.string.app_column_name), 220, true);
        addTableCell(header, getString(R.string.app_column_package), 390, true);
        addTableCell(header, getString(R.string.app_column_version), 180, true);
        addTableCell(header, getString(R.string.app_column_type), 150, true);
        appsTable.addView(header, new TableLayout.LayoutParams(-1, -2));

        int rowIndex = 0;
        for (AppEntry entry : entries) {
            TableRow row = new TableRow(this);
            row.setBackgroundColor(rowIndex++ % 2 == 0 ? 0xff182b32 : 0xff20363f);
            addTableCell(row, entry.label, 220, false);
            addTableCell(row, entry.packageName, 390, false);
            addTableCell(row, entry.versionName + " (" + entry.versionCode + ")", 180, false);
            addTableCell(row, getString(entry.system ? R.string.app_type_system : R.string.app_type_user), 150, false);
            appsTable.addView(row, new TableLayout.LayoutParams(-1, -2));
        }
    }

    private void addTableCell(TableRow row, String value, int width, boolean header) {
        TextView cell = text(value, header ? 14 : 13, header ? Color.WHITE : 0xffeeeeee);
        cell.setGravity(Gravity.CENTER_VERTICAL);
        cell.setPadding(12, 12, 12, 12);
        cell.setMaxLines(2);
        row.addView(cell, new TableRow.LayoutParams(width, -2));
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
        scrollLogToBottom();
    }

    /**
     * Wait until the updated TextView has been measured, then show its tail.
     * scrollTo() deliberately preserves DPAD focus on the current action button.
     */
    private void scrollLogToBottom() {
        if (logScrollView == null || logView == null) return;
        logScrollView.post(() -> {
            int bottom = Math.max(0, logView.getHeight() - logScrollView.getHeight());
            logScrollView.scrollTo(0, bottom);
        });
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


    @Override protected void onDestroy() {
        mainHandler.removeCallbacksAndMessages(null);
        executor.shutdownNow();
        super.onDestroy();
    }

    private static final class AppEntry {
        final String label;
        final String packageName;
        final String versionName;
        final long versionCode;
        final boolean system;

        AppEntry(String label, String packageName, String versionName, long versionCode, boolean system) {
            this.label = label;
            this.packageName = packageName;
            this.versionName = versionName;
            this.versionCode = versionCode;
            this.system = system;
        }
    }
    private static final class StatusSnapshot {
        final String state, phase, packageName, message, releaseId, log;
        StatusSnapshot(String state, String phase, String packageName, String message, String releaseId, String log) {
            this.state = state; this.phase = phase; this.packageName = packageName; this.message = message; this.releaseId = releaseId; this.log = log;
        }
    }
}