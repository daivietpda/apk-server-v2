package com.daivietpda.preinstallmanager;

import android.app.Activity;
import android.graphics.Color;
import android.graphics.drawable.Drawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private static final String TRIGGER_FILE = "run";
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private TextView status;
    private Button runButton;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(48, 48, 48, 48);

        // Top/Center content container
        LinearLayout mainContent = new LinearLayout(this);
        mainContent.setOrientation(LinearLayout.VERTICAL);
        mainContent.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams mainParams = new LinearLayout.LayoutParams(-1, 0, 1.0f);
        root.addView(mainContent, mainParams);

        TextView title = new TextView(this);
        title.setText(R.string.title); title.setTextColor(Color.WHITE); title.setTextSize(28); title.setGravity(Gravity.CENTER);
        mainContent.addView(title, new LinearLayout.LayoutParams(-1, -2));
        status = new TextView(this);
        status.setTextColor(0xffdddddd); status.setTextSize(18); status.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams statusParams = new LinearLayout.LayoutParams(-1, -2);
        statusParams.setMargins(0, 32, 0, 32); mainContent.addView(status, statusParams);

        runButton = new Button(this);
        runButton.setText(R.string.run_update);
        runButton.setOnClickListener(v -> triggerUpdate());
        setupButtonFocus(runButton);
        mainContent.addView(runButton, new LinearLayout.LayoutParams(420, 80));

        Button refresh = new Button(this);
        refresh.setText(R.string.refresh_status);
        refresh.setOnClickListener(v -> refreshStatus());
        setupButtonFocus(refresh);
        LinearLayout.LayoutParams refreshParams = new LinearLayout.LayoutParams(420, 80);
        refreshParams.setMargins(0, 20, 0, 0); mainContent.addView(refresh, refreshParams);

        // Bottom description
        TextView runUpdateDesc = new TextView(this);
        runUpdateDesc.setText(R.string.run_update_desc);
        runUpdateDesc.setTextColor(0xffaaaaaa);
        runUpdateDesc.setTextSize(14);
        runUpdateDesc.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams descParams = new LinearLayout.LayoutParams(-1, -2);
        descParams.setMargins(0, 20, 0, 0);
        root.addView(runUpdateDesc, descParams);

        TextView customFooter = new TextView(this);
        customFooter.setText(R.string.custom_footer_text);
        customFooter.setTextColor(0xffaaaaaa);
        customFooter.setTextSize(14);
        customFooter.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams footerParams = new LinearLayout.LayoutParams(-1, -2);
        footerParams.setMargins(0, 8, 0, 40);
        root.addView(customFooter, footerParams);

        setContentView(root); refreshStatus();
    }

    private void setupButtonFocus(Button button) {
        Drawable originalBg = button.getBackground();
        int originalTextColor = button.getCurrentTextColor();
        button.setOnFocusChangeListener((View v, boolean hasFocus) -> {
            if (hasFocus) {
                v.setScaleX(1.08f);
                v.setScaleY(1.08f);
                v.setBackgroundColor(Color.WHITE);
                ((Button) v).setTextColor(0xFF00695C);
            } else {
                v.setScaleX(1.0f);
                v.setScaleY(1.0f);
                v.setBackground(originalBg);
                ((Button) v).setTextColor(originalTextColor);
            }
        });
    }

    private void triggerUpdate() {
        runButton.setEnabled(false); status.setText(R.string.requesting);
        executor.execute(() -> {
            CommandResult result = createTriggerMarker();
            mainHandler.post(() -> {
                runButton.setEnabled(true);
                if (result.exitCode == 0) { status.setText(R.string.request_sent); mainHandler.postDelayed(this::refreshStatus, 1200); }
                else status.setText(getString(R.string.request_failed, result.output));
            });
        });
    }

    private CommandResult createTriggerMarker() {
        File externalDir = getExternalFilesDir(null);
        if (externalDir == null) return new CommandResult(1, "External storage is unavailable");
        File temporary = new File(externalDir, TRIGGER_FILE + ".tmp");
        File marker = new File(externalDir, TRIGGER_FILE);
        try (FileOutputStream output = new FileOutputStream(temporary, false)) {
            output.write(Long.toString(System.currentTimeMillis()).getBytes(StandardCharsets.UTF_8));
            output.write('\n');
            output.getFD().sync();
        } catch (Exception error) {
            temporary.delete();
            return new CommandResult(1, error.toString());
        }
        if (marker.exists() && !marker.delete()) {
            temporary.delete();
            return new CommandResult(1, "Cannot replace existing request");
        }
        if (!temporary.renameTo(marker)) {
            temporary.delete();
            return new CommandResult(1, "Cannot publish request marker");
        }
        return new CommandResult(0, marker.getAbsolutePath());
    }

    private void refreshStatus() {
        executor.execute(() -> {
            CommandResult result = command("/system/bin/getprop", "init.svc.factoryreset");
            String value = result.output.trim();
            if (value.isEmpty()) value = getString(R.string.unknown);
            final String serviceState = value;
            mainHandler.post(() -> status.setText(getString(R.string.service_status, serviceState)));
        });
    }

    private static CommandResult command(String... args) {
        StringBuilder output = new StringBuilder(); int code = -1;
        try {
            Process process = new ProcessBuilder(args).redirectErrorStream(true).start();
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
                String line; while ((line = reader.readLine()) != null) output.append(line).append('\n');
            }
            code = process.waitFor();
        } catch (Exception error) { output.append(error); }
        return new CommandResult(code, output.toString().trim());
    }
    @Override protected void onDestroy() { executor.shutdownNow(); super.onDestroy(); }
    private static final class CommandResult {
        final int exitCode; final String output;
        CommandResult(int exitCode, String output) { this.exitCode = exitCode; this.output = output; }
    }
}
