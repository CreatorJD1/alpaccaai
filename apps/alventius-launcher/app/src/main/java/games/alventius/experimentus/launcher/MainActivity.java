package games.alventius.experimentus.launcher;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import androidx.core.content.FileProvider;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLConnection;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.LinkedHashSet;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Standalone launcher for the separate Alventius Experimentus game. It never
 * reads companion cookies, CoreMind state, or companion continuity storage.
 */
public final class MainActivity extends Activity {
    private static final String PREFS = "alventius_launcher";
    private static final String PREF_LAST_RELEASE_CHECK_MS = "last_release_check_ms";
    private static final long RELEASE_CHECK_COOLDOWN_MS = 6L * 60L * 60L * 1000L;
    private static final long MAX_UPDATE_APK_BYTES = 250L * 1024L * 1024L;
    private static final String UPDATE_CACHE_DIR = "updates";
    private static final String APK_MIME_TYPE = "application/vnd.android.package-archive";
    private static final String APP_USER_AGENT = "AlventiusLauncher/" + BuildConfig.VERSION_NAME;
    private static final int PLAYER_VRM_CHOOSER_REQUEST = 4102;

    private static final int BG = Color.rgb(9, 11, 17);
    private static final int PANEL = Color.rgb(20, 25, 34);
    private static final int PANEL_HIGH = Color.rgb(31, 40, 52);
    private static final int TEXT = Color.rgb(244, 247, 237);
    private static final int MUTED = Color.rgb(166, 178, 181);
    private static final int LIME = Color.rgb(183, 255, 63);
    private static final int CYAN = Color.rgb(114, 230, 242);
    private static final int ERROR = Color.rgb(255, 116, 116);

    private final ExecutorService network = Executors.newSingleThreadExecutor();
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final Runnable periodicReleaseCheck = new Runnable() {
        @Override
        public void run() {
            checkRelease(false);
            mainHandler.postDelayed(this, RELEASE_CHECK_COOLDOWN_MS);
        }
    };
    private SharedPreferences preferences;
    private WebView webView;
    private LinearLayout portal;
    private Button menuButton;
    private TextView statusBadge;
    private TextView statusTitle;
    private TextView statusDetail;
    private TextView connectionLabel;
    private Button launchButton;
    private Button checkButton;
    private Button downloadButton;
    private Button installButton;
    private TextView updateStatus;
    private ProgressBar updateProgress;
    private boolean releaseCheckRunning;
    private boolean updateDownloadRunning;
    private boolean gameLaunchRunning;
    private boolean activeGameReady;
    private boolean pageFailed;
    private ReleaseInfo currentRelease;
    private ReleaseInfo pendingAvailableUpdate;
    private VerifiedUpdate pendingInstallUpdate;
    private String activeGameUrl = "";
    private ValueCallback<Uri[]> playerVrmChooser;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(BG);
        getWindow().setNavigationBarColor(BG);
        preferences = getSharedPreferences(PREFS, MODE_PRIVATE);
        setContentView(buildInterface());
        configureWebView();
        checkRelease(false);
        mainHandler.postDelayed(periodicReleaseCheck, RELEASE_CHECK_COOLDOWN_MS);
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (pendingInstallUpdate != null && getPackageManager().canRequestPackageInstalls()) {
            updateStatus.setText("Verified update is ready. Tap Install update.");
            installButton.setVisibility(View.VISIBLE);
        }
    }

    @Override
    protected void onDestroy() {
        network.shutdownNow();
        mainHandler.removeCallbacks(periodicReleaseCheck);
        if (playerVrmChooser != null) {
            playerVrmChooser.onReceiveValue(null);
            playerVrmChooser = null;
        }
        if (webView != null) {
            webView.destroy();
        }
        super.onDestroy();
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == PLAYER_VRM_CHOOSER_REQUEST) {
            Uri[] selection = null;
            if (resultCode == RESULT_OK && data != null && data.getData() != null) {
                selection = new Uri[] { data.getData() };
            }
            if (playerVrmChooser != null) {
                playerVrmChooser.onReceiveValue(selection);
                playerVrmChooser = null;
            }
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    @Override
    public void onBackPressed() {
        if (webView.getVisibility() == View.VISIBLE && webView.canGoBack()) {
            webView.goBack();
            return;
        }
        if (webView.getVisibility() == View.VISIBLE) {
            showPortal();
            return;
        }
        super.onBackPressed();
    }

    private FrameLayout buildInterface() {
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(BG);

        webView = new WebView(this);
        webView.setBackgroundColor(BG);
        webView.setVisibility(View.INVISIBLE);
        root.addView(webView, matchParent());

        portal = buildPortal();
        root.addView(portal, matchParent());

        menuButton = compactButton("...");
        menuButton.setContentDescription("Open Alventius launcher controls");
        menuButton.setVisibility(View.GONE);
        menuButton.setOnClickListener(view -> showPortal());
        FrameLayout.LayoutParams menuParams = new FrameLayout.LayoutParams(dp(46), dp(42));
        menuParams.gravity = Gravity.TOP | Gravity.CENTER_HORIZONTAL;
        menuParams.topMargin = dp(10);
        root.addView(menuButton, menuParams);
        return root;
    }

    private LinearLayout buildPortal() {
        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setPadding(dp(18), dp(10), dp(18), dp(18));
        page.setBackgroundColor(BG);

        LinearLayout header = new LinearLayout(this);
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.setPadding(0, dp(8), 0, dp(10));
        TextView title = text("ALVENTIUS", 26, TEXT, true);
        TextView subtitle = text("EXPERIMENTUS  /  GAME LAUNCHER", 10, LIME, true);
        LinearLayout brand = new LinearLayout(this);
        brand.setOrientation(LinearLayout.VERTICAL);
        brand.addView(title);
        brand.addView(subtitle);
        header.addView(brand, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        statusBadge = text("CHECKING", 11, CYAN, true);
        statusBadge.setGravity(Gravity.CENTER);
        statusBadge.setPadding(dp(12), dp(7), dp(12), dp(7));
        statusBadge.setBackground(rounded(PANEL_HIGH, dp(18), CYAN));
        header.addView(statusBadge);
        page.addView(header);

        TextView eyebrow = text("RELEASE CHANNEL", 11, LIME, true);
        eyebrow.setPadding(dp(2), dp(16), 0, dp(5));
        page.addView(eyebrow);

        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(18), dp(18), dp(18), dp(18));
        card.setBackground(rounded(PANEL, dp(8), PANEL_HIGH));

        statusTitle = text("Finding the game", 24, TEXT, true);
        card.addView(statusTitle);
        statusDetail = text(
            "Checking the signed release record for the current game service and launcher build.",
            14,
            MUTED,
            false
        );
        statusDetail.setPadding(0, dp(8), 0, dp(12));
        card.addView(statusDetail);

        connectionLabel = text("Game status: awaiting verified release", 12, MUTED, false);
        connectionLabel.setPadding(0, 0, 0, dp(10));
        card.addView(connectionLabel);

        launchButton = primaryButton("Open game");
        launchButton.setOnClickListener(view -> openDiscoveredGame());
        LinearLayout.LayoutParams launchParams = fullButtonParams();
        launchParams.topMargin = dp(10);
        card.addView(launchButton, launchParams);

        checkButton = secondaryButton("Check release and reconnect");
        checkButton.setOnClickListener(view -> checkRelease(true));
        LinearLayout.LayoutParams checkParams = fullButtonParams();
        checkParams.topMargin = dp(8);
        card.addView(checkButton, checkParams);

        TextView updates = text("LAUNCHER UPDATES", 11, LIME, true);
        updates.setPadding(0, dp(20), 0, dp(6));
        card.addView(updates);
        updateStatus = text("Checking this launcher release channel...", 13, MUTED, false);
        updateStatus.setPadding(0, 0, 0, dp(8));
        card.addView(updateStatus);
        updateProgress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        updateProgress.setIndeterminate(false);
        updateProgress.setMax(100);
        updateProgress.setProgress(0);
        updateProgress.getIndeterminateDrawable().setTint(LIME);
        updateProgress.getProgressDrawable().setTint(LIME);
        card.addView(updateProgress, new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, dp(6)
        ));

        downloadButton = secondaryButton("Download launcher update");
        downloadButton.setVisibility(View.GONE);
        downloadButton.setOnClickListener(view -> {
            if (pendingAvailableUpdate != null) {
                downloadAndVerifyUpdate(pendingAvailableUpdate);
            }
        });
        LinearLayout.LayoutParams downloadParams = fullButtonParams();
        downloadParams.topMargin = dp(10);
        card.addView(downloadButton, downloadParams);

        installButton = primaryButton("Install verified update");
        installButton.setVisibility(View.GONE);
        installButton.setOnClickListener(view -> {
            if (pendingInstallUpdate != null) {
                openInstallerOrSettings(pendingInstallUpdate);
            }
        });
        LinearLayout.LayoutParams installParams = fullButtonParams();
        installParams.topMargin = dp(8);
        card.addView(installButton, installParams);

        TextView note = text(
            "Updates are checked automatically at launch. Downloads are verified before Android shows its own install confirmation.",
            12,
            MUTED,
            false
        );
        note.setPadding(0, dp(16), 0, 0);
        card.addView(note);

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        LinearLayout inner = new LinearLayout(this);
        inner.setOrientation(LinearLayout.VERTICAL);
        inner.addView(card, new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ));
        scroll.addView(inner);
        page.addView(scroll, new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f
        ));
        return page;
    }

    private void configureWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setUserAgentString(settings.getUserAgentString() + " " + APP_USER_AGENT);
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(
                WebView view,
                ValueCallback<Uri[]> callback,
                FileChooserParams parameters
            ) {
                if (playerVrmChooser != null) {
                    playerVrmChooser.onReceiveValue(null);
                }
                playerVrmChooser = callback;
                Intent chooser = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                chooser.addCategory(Intent.CATEGORY_OPENABLE);
                chooser.setType("*/*");
                chooser.putExtra(
                    Intent.EXTRA_MIME_TYPES,
                    new String[] { "model/gltf-binary", "application/octet-stream" }
                );
                try {
                    startActivityForResult(chooser, PLAYER_VRM_CHOOSER_REQUEST);
                } catch (ActivityNotFoundException exc) {
                    playerVrmChooser.onReceiveValue(null);
                    playerVrmChooser = null;
                    Toast.makeText(MainActivity.this, "No file picker is available.", Toast.LENGTH_LONG).show();
                }
                return true;
            }
        });

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri target = request.getUrl();
                if (isConfiguredGameOrigin(target)) {
                    return false;
                }
                openExternal(target);
                return true;
            }

            @Override
            public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
                pageFailed = false;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                if (!pageFailed) {
                    showGameSurface();
                }
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) {
                    pageFailed = true;
                    showPortalFailure("The game page could not be reached. Check the release channel or reconnect.");
                }
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse response) {
                if (request.isForMainFrame() && response.getStatusCode() >= 400) {
                    pageFailed = true;
                    showPortalFailure("The game service returned " + response.getStatusCode() + ".");
                }
            }
        });
    }

    private void checkRelease(boolean manual) {
        if (releaseCheckRunning || updateDownloadRunning) {
            if (manual) {
                Toast.makeText(this, "A release check is already running.", Toast.LENGTH_SHORT).show();
            }
            return;
        }
        long now = System.currentTimeMillis();
        long lastCheck = preferences.getLong(PREF_LAST_RELEASE_CHECK_MS, 0L);
        if (!manual && activeGameReady && lastCheck > 0L
            && now - lastCheck < RELEASE_CHECK_COOLDOWN_MS) {
            return;
        }
        preferences.edit().putLong(PREF_LAST_RELEASE_CHECK_MS, now).apply();
        releaseCheckRunning = true;
        updateControls();
        setPortalStatus("CHECKING", CYAN, "Checking release channel", "Looking for the current game and launcher release.");
        showUpdateProgress("Checking release manifest...", true, 0);
        network.execute(() -> {
            ReleaseInfo release = null;
            String failure = null;
            try {
                release = fetchReleaseManifest();
            } catch (Exception error) {
                failure = "The release channel could not be read.";
            }
            ReleaseInfo result = release;
            String failureMessage = failure;
            runOnUiThread(() -> {
                releaseCheckRunning = false;
                updateControls();
                if (isFinishing() || isDestroyed()) {
                    return;
                }
                if (result == null) {
                    showUpdateProgress("Release channel unavailable. Waiting for a verified release.", false, 0);
                    showPortalFailure(failureMessage);
                    return;
                }
                currentRelease = result;
                if (result.versionCode > BuildConfig.VERSION_CODE) {
                    pendingAvailableUpdate = result;
                    downloadButton.setVisibility(View.VISIBLE);
                    showUpdateProgress(
                        "Launcher " + result.versionName + " is available. Download when ready.",
                        false,
                        0
                    );
                } else {
                    pendingAvailableUpdate = null;
                    downloadButton.setVisibility(View.GONE);
                    showUpdateProgress("Launcher " + BuildConfig.VERSION_NAME + " is current.", false, 100);
                }
                updateControls();
                verifyDiscoveredGame(result.gameUrl);
            });
        });
    }

    private ReleaseInfo fetchReleaseManifest() throws Exception {
        URL manifestUrl = requireHttpsUrl(BuildConfig.RELEASE_MANIFEST_URL, "release manifest");
        HttpURLConnection connection = null;
        try {
            connection = openHttps(manifestUrl, "application/json");
            if (connection.getResponseCode() != 200) {
                throw new IllegalStateException("release manifest unavailable");
            }
            JSONObject payload = new JSONObject(readLimited(connection.getInputStream(), 32 * 1024));
            Object codeValue = payload.opt("versionCode");
            if (!(codeValue instanceof Number)) {
                throw new IllegalArgumentException("release version code missing");
            }
            Number number = (Number) codeValue;
            long versionCode = number.longValue();
            if (versionCode <= 0L || versionCode > Integer.MAX_VALUE
                || number.doubleValue() != (double) versionCode) {
                throw new IllegalArgumentException("release version code invalid");
            }
            String versionName = requiredManifestString(payload, "versionName");
            String apkUrl = requiredManifestString(payload, "apkUrl");
            String sha256 = requiredManifestString(payload, "sha256").toLowerCase(Locale.ROOT);
            String packageName = requiredManifestString(payload, "packageName");
            String gameUrl = requiredManifestString(payload, "gameUrl");
            if (!versionName.matches("[0-9A-Za-z][0-9A-Za-z._+-]{0,63}")) {
                throw new IllegalArgumentException("release version name invalid");
            }
            if (!sha256.matches("[0-9a-f]{64}")) {
                throw new IllegalArgumentException("release digest invalid");
            }
            if (!BuildConfig.APPLICATION_ID.equals(packageName) || !getPackageName().equals(packageName)) {
                throw new SecurityException("release package mismatch");
            }
            return new ReleaseInfo(
                (int) versionCode,
                versionName,
                requireHttpsUrl(apkUrl, "release APK"),
                sha256,
                packageName,
                requireHttpsUrl(gameUrl, "game service")
            );
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private void verifyDiscoveredGame(URL candidate) {
        activeGameReady = false;
        updateControls();
        setPortalStatus("CHECKING", CYAN, "Verifying game service", "Checking the discovered game release.");
        network.execute(() -> {
            String error = null;
            try {
                verifyGameHealth(candidate);
            } catch (Exception failure) {
                error = "The game service did not return the expected Alventius identity.";
            }
            String failureMessage = error;
            runOnUiThread(() -> {
                if (isFinishing() || isDestroyed()) {
                    return;
                }
                if (failureMessage != null) {
                    showPortalFailure("Release found, but the game service is not ready yet.");
                    return;
                }
                activeGameUrl = candidate.toExternalForm();
                activeGameReady = true;
                connectionLabel.setText("Game status: ready to launch");
                setPortalStatus("READY", LIME, "Vesper Dome ready", "The current release has been verified.");
                updateControls();
            });
        });
    }

    private void openDiscoveredGame() {
        if (!activeGameReady || activeGameUrl.isEmpty() || gameLaunchRunning) {
            return;
        }
        gameLaunchRunning = true;
        updateControls();
        setPortalStatus("OPENING", CYAN, "Opening Vesper Dome", "Checking the current game service before launch.");
        final URL candidate;
        try {
            candidate = requireHttpsUrl(activeGameUrl, "active game");
        } catch (Exception error) {
            gameLaunchRunning = false;
            showPortalFailure("The verified game release is no longer available.");
            return;
        }
        network.execute(() -> {
            String error = null;
            try {
                verifyGameHealth(candidate);
            } catch (Exception failure) {
                error = "The game service is no longer ready.";
            }
            String failureMessage = error;
            runOnUiThread(() -> {
                gameLaunchRunning = false;
                if (isFinishing() || isDestroyed()) {
                    return;
                }
                if (failureMessage != null) {
                    showPortalFailure(failureMessage);
                    return;
                }
                webView.loadUrl(activeGameUrl);
                updateControls();
            });
        });
    }

    private void verifyGameHealth(URL gameUrl) throws Exception {
        URL health = new URL(gameUrl.toExternalForm().replaceAll("/+$", "") + "/healthz");
        HttpURLConnection connection = null;
        try {
            connection = openHttps(health, "application/json");
            if (connection.getResponseCode() != 200) {
                throw new IllegalStateException("game health unavailable");
            }
            JSONObject payload = new JSONObject(readLimited(connection.getInputStream(), 16 * 1024));
            if (!payload.optBoolean("ok", false)
                || !"agentic-frontier".equals(payload.optString("appId"))
                || !"game".equals(payload.optString("kind"))
                || payload.optBoolean("coreMind", true)) {
                throw new SecurityException("game identity mismatch");
            }
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private void downloadAndVerifyUpdate(ReleaseInfo update) {
        if (updateDownloadRunning) {
            return;
        }
        updateDownloadRunning = true;
        updateControls();
        showUpdateProgress("Downloading launcher " + update.versionName + "... 0%", false, 0);
        network.execute(() -> {
            File downloaded = null;
            String failure = null;
            try {
                downloaded = downloadUpdateApk(update, percent -> runOnUiThread(() -> {
                    if (percent < 0) {
                        showUpdateProgress("Downloading launcher update...", true, 0);
                    } else if (percent < 94) {
                        showUpdateProgress("Downloading launcher update... " + percent + "%", false, percent);
                    } else if (percent < 100) {
                        showUpdateProgress("Verifying package and signer...", false, percent);
                    } else {
                        showUpdateProgress("Update verified. Ready to install.", false, 100);
                    }
                }));
            } catch (Exception error) {
                failure = "Download or verification failed.";
            }
            File verified = downloaded;
            String failureMessage = failure;
            runOnUiThread(() -> {
                updateDownloadRunning = false;
                updateControls();
                if (isFinishing() || isDestroyed()) {
                    return;
                }
                if (failureMessage != null) {
                    showUpdateProgress(failureMessage, false, 0);
                    Toast.makeText(this, failureMessage, Toast.LENGTH_LONG).show();
                    return;
                }
                pendingInstallUpdate = new VerifiedUpdate(update, verified);
                pendingAvailableUpdate = null;
                downloadButton.setVisibility(View.GONE);
                installButton.setVisibility(View.VISIBLE);
                showUpdateProgress("Update verified. Ready to install.", false, 100);
                updateControls();
            });
        });
    }

    private File downloadUpdateApk(ReleaseInfo update, UpdateProgressListener listener) throws Exception {
        File updateDir = new File(getCacheDir(), UPDATE_CACHE_DIR);
        if ((!updateDir.exists() && !updateDir.mkdirs()) || !updateDir.isDirectory()) {
            throw new IllegalStateException("update cache unavailable");
        }
        File[] stale = updateDir.listFiles();
        if (stale != null) {
            for (File file : stale) {
                if (file.isFile()) {
                    file.delete();
                }
            }
        }
        File partial = new File(updateDir, "AlventiusLauncher-" + update.versionCode + ".apk.part");
        File complete = new File(updateDir, "AlventiusLauncher-" + update.versionCode + ".apk");
        boolean verified = false;
        HttpURLConnection connection = null;
        try {
            connection = openHttps(update.apkUrl, APK_MIME_TYPE);
            if (connection.getResponseCode() != 200) {
                throw new IllegalStateException("update APK unavailable");
            }
            long declaredLength = connection.getContentLengthLong();
            if (declaredLength > MAX_UPDATE_APK_BYTES) {
                throw new SecurityException("update APK too large");
            }
            listener.onProgress(declaredLength > 0L ? 0 : -1);
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            long total = 0L;
            int lastPercent = -2;
            try (InputStream input = connection.getInputStream();
                 FileOutputStream output = new FileOutputStream(partial)) {
                byte[] buffer = new byte[32 * 1024];
                int read;
                while ((read = input.read(buffer)) != -1) {
                    total += read;
                    if (total > MAX_UPDATE_APK_BYTES) {
                        throw new SecurityException("update APK too large");
                    }
                    digest.update(buffer, 0, read);
                    output.write(buffer, 0, read);
                    int percent = declaredLength > 0L
                        ? (int) Math.min(92L, (total * 92L) / declaredLength)
                        : -1;
                    if (percent != lastPercent) {
                        lastPercent = percent;
                        listener.onProgress(percent);
                    }
                }
                output.flush();
            }
            if (total <= 0L || (declaredLength >= 0L && declaredLength != total)) {
                throw new SecurityException("update APK length mismatch");
            }
            if (!MessageDigest.isEqual(hexToBytes(update.sha256), digest.digest())) {
                throw new SecurityException("update APK digest mismatch");
            }
            listener.onProgress(96);
            if (!partial.renameTo(complete)) {
                throw new IllegalStateException("update APK could not be finalized");
            }
            verifyDownloadedPackage(complete, update);
            listener.onProgress(100);
            verified = true;
            return complete;
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
            partial.delete();
            if (!verified) {
                complete.delete();
            }
        }
    }

    private void verifyDownloadedPackage(File apk, ReleaseInfo update) throws Exception {
        PackageManager manager = getPackageManager();
        int flags = Build.VERSION.SDK_INT >= Build.VERSION_CODES.P
            ? PackageManager.GET_SIGNING_CERTIFICATES
            : PackageManager.GET_SIGNATURES;
        PackageInfo archive = manager.getPackageArchiveInfo(apk.getAbsolutePath(), flags);
        PackageInfo installed = manager.getPackageInfo(getPackageName(), flags);
        if (archive == null || !update.packageName.equals(archive.packageName)) {
            throw new SecurityException("downloaded package identity mismatch");
        }
        if (packageVersionCode(archive) != update.versionCode
            || !update.versionName.equals(archive.versionName)) {
            throw new SecurityException("downloaded package version mismatch");
        }
        if (!signerDigests(installed).equals(signerDigests(archive)) || signerDigests(installed).isEmpty()) {
            throw new SecurityException("downloaded package signer mismatch");
        }
    }

    @SuppressWarnings("deprecation")
    private long packageVersionCode(PackageInfo info) {
        return Build.VERSION.SDK_INT >= Build.VERSION_CODES.P ? info.getLongVersionCode() : info.versionCode;
    }

    @SuppressWarnings("deprecation")
    private Set<String> signerDigests(PackageInfo info) throws Exception {
        android.content.pm.Signature[] signatures;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            if (info.signingInfo == null) {
                throw new SecurityException("package signer unavailable");
            }
            signatures = info.signingInfo.getApkContentsSigners();
        } else {
            signatures = info.signatures;
        }
        Set<String> result = new LinkedHashSet<>();
        if (signatures != null) {
            for (android.content.pm.Signature signature : signatures) {
                result.add(toHex(MessageDigest.getInstance("SHA-256").digest(signature.toByteArray())));
            }
        }
        return result;
    }

    private void openInstallerOrSettings(VerifiedUpdate update) {
        if (!getPackageManager().canRequestPackageInstalls()) {
            new AlertDialog.Builder(this)
                .setTitle("Allow game launcher updates?")
                .setMessage("Android must allow this launcher to request package installs. It cannot install an update silently.")
                .setPositiveButton("Open Android settings", (dialog, which) -> {
                    Intent settings = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES);
                    settings.setData(Uri.parse("package:" + getPackageName()));
                    try {
                        startActivity(settings);
                    } catch (ActivityNotFoundException error) {
                        Toast.makeText(this, "Android install settings are unavailable.", Toast.LENGTH_LONG).show();
                    }
                })
                .setNegativeButton("Cancel", null)
                .show();
            return;
        }
        if (!update.apk.isFile()) {
            Toast.makeText(this, "The verified update file is no longer available.", Toast.LENGTH_LONG).show();
            return;
        }
        try {
            Uri apkUri = FileProvider.getUriForFile(this, getPackageName() + ".updates", update.apk);
            Intent install = new Intent(Intent.ACTION_VIEW);
            install.setDataAndType(apkUri, APK_MIME_TYPE);
            install.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            install.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(install);
        } catch (ActivityNotFoundException error) {
            Toast.makeText(this, "Android's package installer is unavailable.", Toast.LENGTH_LONG).show();
        }
    }

    private HttpURLConnection openHttps(URL url, String accept) throws Exception {
        URLConnection raw = url.openConnection();
        if (!(raw instanceof HttpURLConnection)) {
            throw new IllegalArgumentException("HTTPS connection unavailable");
        }
        HttpURLConnection connection = (HttpURLConnection) raw;
        connection.setConnectTimeout(10_000);
        connection.setReadTimeout(30_000);
        connection.setInstanceFollowRedirects(false);
        connection.setUseCaches(false);
        connection.setRequestProperty("Accept", accept);
        connection.setRequestProperty("Cache-Control", "no-cache");
        connection.setRequestProperty("User-Agent", APP_USER_AGENT);
        return connection;
    }

    private URL requireHttpsUrl(String raw, String label) throws Exception {
        URL url = new URL(raw == null ? "" : raw.trim());
        if (!"https".equalsIgnoreCase(url.getProtocol())
            || url.getHost() == null || url.getHost().trim().isEmpty()
            || url.getUserInfo() != null || url.getRef() != null) {
            throw new SecurityException(label + " must use credential-free HTTPS");
        }
        return url;
    }

    private String requiredManifestString(JSONObject payload, String key) {
        Object value = payload.opt(key);
        if (!(value instanceof String) || ((String) value).trim().isEmpty()) {
            throw new IllegalArgumentException("release manifest field missing");
        }
        return ((String) value).trim();
    }

    private String readLimited(InputStream input, int limit) throws Exception {
        try (InputStream stream = input; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[4096];
            int total = 0;
            int read;
            while ((read = stream.read(buffer)) != -1) {
                total += read;
                if (total > limit) {
                    throw new IllegalArgumentException("response too large");
                }
                output.write(buffer, 0, read);
            }
            return output.toString(StandardCharsets.UTF_8.name());
        }
    }

    private byte[] hexToBytes(String value) {
        byte[] result = new byte[value.length() / 2];
        for (int index = 0; index < value.length(); index += 2) {
            int high = Character.digit(value.charAt(index), 16);
            int low = Character.digit(value.charAt(index + 1), 16);
            if (high < 0 || low < 0) {
                throw new IllegalArgumentException("digest is not hexadecimal");
            }
            result[index / 2] = (byte) ((high << 4) | low);
        }
        return result;
    }

    private String toHex(byte[] value) {
        StringBuilder result = new StringBuilder(value.length * 2);
        for (byte item : value) {
            result.append(String.format(Locale.ROOT, "%02x", item & 0xff));
        }
        return result.toString();
    }

    private boolean isConfiguredGameOrigin(Uri uri) {
        try {
            URL active = requireHttpsUrl(activeGameUrl, "active game");
            return "https".equalsIgnoreCase(uri.getScheme())
                && active.getHost().equalsIgnoreCase(uri.getHost())
                && active.getPort() == uri.getPort();
        } catch (Exception error) {
            return false;
        }
    }

    private void openExternal(Uri target) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, target));
        } catch (ActivityNotFoundException error) {
            Toast.makeText(this, "No browser is available for that link.", Toast.LENGTH_SHORT).show();
        }
    }

    private void showPortal() {
        portal.setVisibility(View.VISIBLE);
        webView.setVisibility(View.INVISIBLE);
        menuButton.setVisibility(View.GONE);
    }

    private void showGameSurface() {
        portal.setVisibility(View.GONE);
        webView.setVisibility(View.VISIBLE);
        menuButton.setVisibility(View.VISIBLE);
    }

    private void showPortalFailure(String message) {
        gameLaunchRunning = false;
        activeGameReady = false;
        activeGameUrl = "";
        showPortal();
        setPortalStatus("OFFLINE", ERROR, "Game connection unavailable", message);
        connectionLabel.setText("Game status: awaiting verified release");
        updateControls();
    }

    private void setPortalStatus(String badge, int color, String title, String detail) {
        statusBadge.setText(badge);
        statusBadge.setTextColor(color);
        statusBadge.setBackground(rounded(PANEL_HIGH, dp(18), color));
        statusTitle.setText(title);
        statusDetail.setText(detail);
    }

    private void showUpdateProgress(String message, boolean indeterminate, int value) {
        updateStatus.setText(message);
        updateProgress.setIndeterminate(indeterminate);
        if (!indeterminate) {
            updateProgress.setProgress(Math.max(0, Math.min(100, value)));
        }
    }

    private void updateControls() {
        boolean busy = releaseCheckRunning || updateDownloadRunning || gameLaunchRunning;
        checkButton.setEnabled(!busy);
        launchButton.setEnabled(!busy && activeGameReady && !activeGameUrl.isEmpty());
        downloadButton.setEnabled(!busy && pendingAvailableUpdate != null);
        installButton.setEnabled(!busy && pendingInstallUpdate != null);
    }

    private TextView text(String value, int size, int color, boolean bold) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextColor(color);
        view.setTextSize(size);
        if (bold) {
            view.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        }
        return view;
    }

    private Button primaryButton(String label) {
        Button button = new Button(this);
        button.setAllCaps(false);
        button.setText(label);
        button.setTextColor(BG);
        button.setTextSize(15);
        button.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        button.setBackground(rounded(LIME, dp(6), LIME));
        return button;
    }

    private Button secondaryButton(String label) {
        Button button = new Button(this);
        button.setAllCaps(false);
        button.setText(label);
        button.setTextColor(TEXT);
        button.setTextSize(15);
        button.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        button.setBackground(rounded(PANEL_HIGH, dp(6), Color.rgb(66, 80, 91)));
        return button;
    }

    private Button compactButton(String label) {
        Button button = secondaryButton(label);
        button.setTextSize(18);
        return button;
    }

    private GradientDrawable rounded(int fill, int radius, int stroke) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(fill);
        drawable.setCornerRadius(radius);
        drawable.setStroke(dp(1), stroke);
        return drawable;
    }

    private LinearLayout.LayoutParams fullButtonParams() {
        return new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(50));
    }

    private FrameLayout.LayoutParams matchParent() {
        return new FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.MATCH_PARENT
        );
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private interface UpdateProgressListener {
        void onProgress(int percent);
    }

    private static final class ReleaseInfo {
        final int versionCode;
        final String versionName;
        final URL apkUrl;
        final String sha256;
        final String packageName;
        final URL gameUrl;

        ReleaseInfo(int versionCode, String versionName, URL apkUrl, String sha256, String packageName, URL gameUrl) {
            this.versionCode = versionCode;
            this.versionName = versionName;
            this.apkUrl = apkUrl;
            this.sha256 = sha256;
            this.packageName = packageName;
            this.gameUrl = gameUrl;
        }
    }

    private static final class VerifiedUpdate {
        final ReleaseInfo info;
        final File apk;

        VerifiedUpdate(ReleaseInfo info, File apk) {
            this.info = info;
            this.apk = apk;
        }
    }
}
