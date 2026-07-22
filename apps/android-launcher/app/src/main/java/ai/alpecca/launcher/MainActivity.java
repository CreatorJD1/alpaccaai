package ai.alpecca.launcher;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.PermissionRequest;
import android.webkit.SslErrorHandler;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebStorage;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import androidx.core.content.FileProvider;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.KeyPairGenerator;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.security.PrivateKey;
import java.security.Signature;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

public final class MainActivity extends Activity {
    private static final String PREFS = "alpecca_launcher";
    private static final String PREF_SERVER_URL = "server_url";
    private static final String PREF_MEDIA_ORIGIN = "media_origin";
    private static final String PREF_DEVICE_ID = "trusted_device_id";
    private static final String PREF_LAST_UPDATE_CHECK_MS = "last_update_check_ms";
    private static final String DEVICE_KEY_ALIAS = "alpecca_creator_device_v1";
    private static final int REQUEST_WEB_PERMISSIONS = 4001;
    private static final int REQUEST_FILE = 4002;
    private static final long HEALTH_CHECK_INTERVAL_MS = 30_000L;
    private static final long HEALTH_CHECK_CONFIRM_MS = 4_000L;
    private static final long RECOVERY_RETRY_MAX_MS = 30_000L;
    private static final long UPDATE_CHECK_COOLDOWN_MS = 12L * 60L * 60L * 1000L;
    private static final long MAX_UPDATE_APK_BYTES = 250L * 1024L * 1024L;
    private static final String UPDATE_CACHE_DIR = "updates";
    private static final String APK_MIME_TYPE = "application/vnd.android.package-archive";
    private static final String RELAY_BYPASS_HEADER = "bypass-tunnel-reminder";
    private static final String RELAY_BYPASS_VALUE = "alpecca-android";
    private static final String APP_USER_AGENT = "AlpeccaAndroid/" + BuildConfig.VERSION_NAME;

    private static final int BG = Color.rgb(10, 14, 21);
    private static final int PANEL = Color.rgb(19, 25, 36);
    private static final int PANEL_HIGH = Color.rgb(31, 40, 55);
    private static final int TEXT = Color.rgb(255, 248, 232);
    private static final int MUTED = Color.rgb(160, 174, 194);
    private static final int CYAN = Color.rgb(142, 238, 255);
    private static final int GOLD = Color.rgb(240, 189, 89);

    private final ExecutorService network = Executors.newSingleThreadExecutor();
    private final ExecutorService discoveryNetwork = Executors.newFixedThreadPool(2);
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final Runnable healthCheckTask = this::runForegroundHealthCheck;
    private final Runnable recoveryTask = () -> startDiscovery(DiscoveryMode.RECOVERY);
    private SharedPreferences preferences;
    private FrameLayout root;
    private WebView webView;
    private LinearLayout portal;
    private FrameLayout settingsOverlay;
    private Button nativeMenu;
    private TextView statusBadge;
    private TextView phaseTitle;
    private TextView phaseDetail;
    private TextView endpointLabel;
    private TextView runtimeLabel;
    private ProgressBar progress;
    private EditText serverField;
    private Button reconnectButton;
    private Button updateButton;
    private Button installUpdateButton;
    private TextView updateStatus;
    private ProgressBar updateProgress;
    private ValueCallback<Uri[]> fileCallback;
    private PermissionRequest pendingWebPermission;
    private String[] pendingWebResources = new String[0];
    private boolean pageFailed;
    private int connectionAttempt;
    private int automaticRetryCount;
    private int consecutiveHealthFailures;
    private boolean activityResumed;
    private boolean discoveryRunning;
    private boolean recoveryPending;
    private boolean networkCallbackRegistered;
    private boolean clearHistoryAfterLoad;
    private boolean deviceEnrollmentRunning;
    private boolean updateCheckRunning;
    private boolean updateDownloadRunning;
    private boolean startupUpdateCheckRequested;
    private boolean awaitingInstallPermission;
    private boolean forceSourceRefresh;
    private long trustGeneration;
    private String activeServerUrl = "";
    private UpdateInfo pendingAvailableUpdate;
    private VerifiedUpdate pendingInstallUpdate;
    private Future<?> activeDiscoveryTask;
    private ConnectivityManager connectivityManager;
    private final ConnectivityManager.NetworkCallback networkCallback = new ConnectivityManager.NetworkCallback() {
        @Override
        public void onAvailable(Network network) {
            runOnUiThread(() -> {
                if (activityResumed && recoveryPending && !discoveryRunning) {
                    mainHandler.removeCallbacks(recoveryTask);
                    startDiscovery(DiscoveryMode.RECOVERY);
                }
            });
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(BG);
        getWindow().setNavigationBarColor(BG);
        preferences = getSharedPreferences(PREFS, MODE_PRIVATE);
        root = buildInterface();
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(0, insets.getSystemWindowInsetTop(), 0, insets.getSystemWindowInsetBottom());
            return insets;
        });
        setContentView(root);
        configureWebView();
        registerNetworkRecovery();
        discoverAndConnect();
    }

    private FrameLayout buildInterface() {
        FrameLayout frame = new FrameLayout(this);
        frame.setBackgroundColor(BG);

        webView = new WebView(this);
        webView.setBackgroundColor(BG);
        webView.setVisibility(View.INVISIBLE);
        frame.addView(webView, matchParent());

        portal = buildPortal();
        frame.addView(portal, matchParent());

        nativeMenu = compactButton("...");
        nativeMenu.setContentDescription("Alpecca connection controls");
        nativeMenu.setVisibility(View.GONE);
        nativeMenu.setOnClickListener(view -> showSettings());
        FrameLayout.LayoutParams menuParams = new FrameLayout.LayoutParams(dp(44), dp(40));
        menuParams.gravity = Gravity.TOP | Gravity.CENTER_HORIZONTAL;
        menuParams.topMargin = dp(8);
        frame.addView(nativeMenu, menuParams);

        settingsOverlay = buildSettingsOverlay();
        settingsOverlay.setVisibility(View.GONE);
        frame.addView(settingsOverlay, matchParent());
        return frame;
    }

    private LinearLayout buildPortal() {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setBackgroundColor(BG);

        LinearLayout header = new LinearLayout(this);
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.setPadding(dp(22), dp(14), dp(22), dp(8));

        LinearLayout brand = new LinearLayout(this);
        brand.setOrientation(LinearLayout.VERTICAL);
        TextView name = text("ALPECCA", 24, TEXT, true);
        TextView subtitle = text("MOBILE COMPANION", 10, CYAN, true);
        brand.addView(name);
        brand.addView(subtitle);
        header.addView(brand, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        statusBadge = text("FINDING", 11, CYAN, true);
        statusBadge.setGravity(Gravity.CENTER);
        statusBadge.setPadding(dp(12), dp(7), dp(12), dp(7));
        statusBadge.setBackground(rounded(PANEL_HIGH, dp(20), CYAN));
        header.addView(statusBadge);
        layout.addView(header, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(74)));

        FrameLayout hero = new FrameLayout(this);
        ImageView portrait = new ImageView(this);
        portrait.setImageResource(R.drawable.alpecca_portrait);
        portrait.setScaleType(ImageView.ScaleType.FIT_CENTER);
        portrait.setAdjustViewBounds(true);
        portrait.setContentDescription("Alpecca");
        FrameLayout.LayoutParams portraitParams = new FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.MATCH_PARENT
        );
        portraitParams.gravity = Gravity.CENTER;
        portraitParams.leftMargin = dp(12);
        portraitParams.rightMargin = dp(12);
        hero.addView(portrait, portraitParams);
        layout.addView(hero, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        LinearLayout recovery = new LinearLayout(this);
        recovery.setOrientation(LinearLayout.VERTICAL);
        recovery.setPadding(dp(24), dp(20), dp(24), dp(22));
        recovery.setBackground(rounded(PANEL, dp(8), Color.TRANSPARENT));

        phaseTitle = text("Opening House HQ", 28, TEXT, true);
        recovery.addView(phaseTitle);
        phaseDetail = text("Finding Alpecca's current secure connection.", 14, MUTED, false);
        phaseDetail.setPadding(0, dp(7), 0, dp(12));
        recovery.addView(phaseDetail);

        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setIndeterminate(true);
        progress.getIndeterminateDrawable().setTint(CYAN);
        progress.getProgressDrawable().setTint(CYAN);
        recovery.addView(progress, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(3)));

        endpointLabel = text("Endpoint reconnect: secure discovery not checked yet", 11, MUTED, false);
        endpointLabel.setPadding(0, dp(12), 0, dp(4));
        recovery.addView(endpointLabel);

        runtimeLabel = text(
            "Runtime availability: checking local primary and fenced cloud continuity.",
            11,
            MUTED,
            false
        );
        runtimeLabel.setPadding(0, 0, 0, dp(12));
        recovery.addView(runtimeLabel);

        reconnectButton = primaryButton("Reconnect endpoint");
        reconnectButton.setOnClickListener(view -> rediscoverCurrentEndpoint());
        recovery.addView(reconnectButton, fullButtonParams());

        Button settings = secondaryButton("Connection settings");
        settings.setOnClickListener(view -> showSettings());
        LinearLayout.LayoutParams settingsParams = fullButtonParams();
        settingsParams.topMargin = dp(8);
        recovery.addView(settings, settingsParams);

        LinearLayout.LayoutParams recoveryParams = new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT
        );
        recoveryParams.leftMargin = dp(14);
        recoveryParams.rightMargin = dp(14);
        recoveryParams.bottomMargin = dp(12);
        layout.addView(recovery, recoveryParams);
        return layout;
    }

    private FrameLayout buildSettingsOverlay() {
        FrameLayout overlay = new FrameLayout(this);
        overlay.setBackgroundColor(Color.argb(220, 4, 7, 12));
        overlay.setOnClickListener(view -> hideSettings());

        LinearLayout sheet = new LinearLayout(this);
        sheet.setOrientation(LinearLayout.VERTICAL);
        sheet.setPadding(dp(24), dp(20), dp(24), dp(24));
        sheet.setBackground(rounded(PANEL, dp(8), PANEL_HIGH));
        sheet.setOnClickListener(view -> { });

        TextView title = text("Connection and updates", 24, TEXT, true);
        sheet.addView(title);
        TextView help = text(
            "Reconnect rediscovers Alpecca's current endpoint. A local or fenced cloud runtime must already be available. Use a manual HTTPS address only when needed.",
            13,
            MUTED,
            false
        );
        help.setPadding(0, dp(6), 0, dp(14));
        sheet.addView(help);

        serverField = new EditText(this);
        serverField.setSingleLine(true);
        serverField.setHint("https://alpecca.example.com");
        serverField.setHintTextColor(MUTED);
        serverField.setTextColor(TEXT);
        serverField.setTextSize(14);
        serverField.setPadding(dp(12), 0, dp(12), 0);
        serverField.setBackground(rounded(PANEL_HIGH, dp(6), Color.rgb(66, 82, 105)));
        sheet.addView(serverField, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(52)));

        Button connect = primaryButton("Connect to House HQ");
        connect.setOnClickListener(view -> {
            String entered = serverField.getText().toString();
            hideSettings();
            connectManual(entered);
        });
        LinearLayout.LayoutParams connectParams = fullButtonParams();
        connectParams.topMargin = dp(12);
        sheet.addView(connect, connectParams);

        Button reconnect = secondaryButton("Reconnect current endpoint");
        reconnect.setOnClickListener(view -> rediscoverCurrentEndpoint());
        LinearLayout.LayoutParams reconnectParams = fullButtonParams();
        reconnectParams.topMargin = dp(8);
        sheet.addView(reconnect, reconnectParams);

        Button permissions = secondaryButton("Android camera and microphone settings");
        permissions.setOnClickListener(view -> openAndroidSettings());
        LinearLayout.LayoutParams permissionParams = fullButtonParams();
        permissionParams.topMargin = dp(8);
        sheet.addView(permissions, permissionParams);

        TextView updateTitle = text("ALPECCA APP UPDATES", 11, GOLD, true);
        updateTitle.setPadding(0, dp(18), 0, dp(5));
        sheet.addView(updateTitle);

        updateStatus = text(
            "Alpecca app " + BuildConfig.VERSION_NAME + " is ready to check for updates.",
            13,
            MUTED,
            false
        );
        updateStatus.setPadding(0, 0, 0, dp(8));
        sheet.addView(updateStatus);

        updateProgress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        updateProgress.setIndeterminate(false);
        updateProgress.setMax(100);
        updateProgress.setProgress(0);
        updateProgress.getIndeterminateDrawable().setTint(CYAN);
        updateProgress.getProgressDrawable().setTint(CYAN);
        sheet.addView(
            updateProgress,
            new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(6))
        );

        updateButton = secondaryButton("Check for Alpecca update");
        updateButton.setOnClickListener(view -> {
            checkForUpdates(true);
        });
        LinearLayout.LayoutParams updateParams = fullButtonParams();
        updateParams.topMargin = dp(8);
        sheet.addView(updateButton, updateParams);

        installUpdateButton = primaryButton("Install Alpecca update");
        installUpdateButton.setVisibility(View.GONE);
        installUpdateButton.setOnClickListener(view -> {
            VerifiedUpdate pending = pendingInstallUpdate;
            if (pending != null) {
                openInstallerOrSettings(pending);
            }
        });
        LinearLayout.LayoutParams installParams = fullButtonParams();
        installParams.topMargin = dp(8);
        sheet.addView(installUpdateButton, installParams);

        Button refreshSource = secondaryButton("Refresh House source");
        refreshSource.setOnClickListener(view -> refreshHouseSource());
        LinearLayout.LayoutParams refreshParams = fullButtonParams();
        refreshParams.topMargin = dp(8);
        sheet.addView(refreshSource, refreshParams);

        Button clear = secondaryButton("Clear trusted session");
        clear.setOnClickListener(view -> confirmClearSession());
        LinearLayout.LayoutParams clearParams = fullButtonParams();
        clearParams.topMargin = dp(8);
        sheet.addView(clear, clearParams);

        Button close = compactButton("Close");
        close.setOnClickListener(view -> hideSettings());
        LinearLayout.LayoutParams closeParams = fullButtonParams();
        closeParams.topMargin = dp(8);
        sheet.addView(close, closeParams);

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(false);
        scroll.addView(
            sheet,
            new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            )
        );

        FrameLayout.LayoutParams sheetParams = new FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.MATCH_PARENT
        );
        sheetParams.gravity = Gravity.CENTER;
        sheetParams.leftMargin = dp(12);
        sheetParams.rightMargin = dp(12);
        sheetParams.topMargin = dp(48);
        sheetParams.bottomMargin = dp(8);
        overlay.addView(scroll, sheetParams);
        return overlay;
    }

    private void configureWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(true);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setUserAgentString(settings.getUserAgentString() + " " + APP_USER_AGENT);

        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setAcceptThirdPartyCookies(webView, false);
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri target = request.getUrl();
                if (isConfiguredOrigin(target)) {
                    return false;
                }
                openExternal(target);
                return true;
            }

            @Override
            public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
                cancelHealthCheck();
                pageFailed = false;
                progress.setIndeterminate(false);
                progress.setProgress(12);
                if (url != null && url.contains("/auth/password")) {
                    showHouseSurface();
                } else {
                    showPortal("OPENING", "Opening House HQ", "Securing the trusted phone session.", true);
                }
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                if (!pageFailed) {
                    if (clearHistoryAfterLoad) {
                        view.clearHistory();
                        clearHistoryAfterLoad = false;
                    }
                    recoveryPending = false;
                    automaticRetryCount = 0;
                    consecutiveHealthFailures = 0;
                    showHouseSurface();
                    scheduleHealthCheck(HEALTH_CHECK_INTERVAL_MS);
                    ensureDeviceEnrollment();
                }
                CookieManager.getInstance().flush();
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) {
                    beginAutomaticRecovery("Alpecca's server could not be reached.");
                }
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse response) {
                if (request.isForMainFrame() && response.getStatusCode() >= 500) {
                    beginAutomaticRecovery("Alpecca's server returned " + response.getStatusCode() + ".");
                }
            }

            @Override
            public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
                handler.cancel();
                beginAutomaticRecovery("The server certificate could not be verified.");
            }
        });

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int value) {
                progress.setIndeterminate(false);
                progress.setProgress(value);
            }

            @Override
            public void onPermissionRequest(PermissionRequest request) {
                runOnUiThread(() -> handleWebPermissionRequest(request));
            }

            @Override
            public void onPermissionRequestCanceled(PermissionRequest request) {
                if (request == pendingWebPermission) {
                    clearPendingWebPermission();
                }
            }

            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                Uri current = view.getUrl() == null ? null : Uri.parse(view.getUrl());
                if (!isConfiguredOrigin(current)) {
                    callback.onReceiveValue(null);
                    return false;
                }
                if (fileCallback != null) {
                    fileCallback.onReceiveValue(null);
                }
                fileCallback = callback;
                Intent picker = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                picker.addCategory(Intent.CATEGORY_OPENABLE);
                picker.setType("*/*");
                String[] accepted = params == null ? null : params.getAcceptTypes();
                if (accepted != null && accepted.length > 0 && !accepted[0].trim().isEmpty()) {
                    picker.putExtra(Intent.EXTRA_MIME_TYPES, accepted);
                }
                try {
                    startActivityForResult(picker, REQUEST_FILE);
                    return true;
                } catch (ActivityNotFoundException error) {
                    fileCallback = null;
                    Toast.makeText(MainActivity.this, "No file picker is available.", Toast.LENGTH_LONG).show();
                    return false;
                }
            }
        });
    }

    private void discoverAndConnect() {
        restartDiscovery(DiscoveryMode.STARTUP);
    }

    private void rediscoverCurrentEndpoint() {
        hideSettings();
        restartDiscovery(DiscoveryMode.RECONNECT);
    }

    private void restartDiscovery(DiscoveryMode mode) {
        automaticRetryCount = 0;
        recoveryPending = false;
        pageFailed = false;
        mainHandler.removeCallbacks(recoveryTask);
        cancelHealthCheck();
        connectionAttempt++;
        discoveryRunning = false;
        cancelActiveDiscoveryTask();
        webView.stopLoading();
        startDiscovery(mode);
    }

    private void cancelActiveDiscoveryTask() {
        Future<?> previous = activeDiscoveryTask;
        activeDiscoveryTask = null;
        if (previous != null) {
            previous.cancel(true);
        }
    }

    private void startDiscovery(DiscoveryMode mode) {
        if (discoveryRunning) {
            return;
        }
        mainHandler.removeCallbacks(recoveryTask);
        cancelHealthCheck();
        discoveryRunning = true;
        final int attempt = ++connectionAttempt;
        if (mode == DiscoveryMode.RECONNECT) {
            showPortal(
                "RECONNECTING",
                "Rediscovering endpoint",
                "Refreshing Alpecca's secure endpoint records. Runtime availability is checked separately.",
                true
            );
        } else if (mode == DiscoveryMode.SOURCE_REFRESH) {
            showPortal(
                "UPDATING",
                "Refreshing House source",
                "Clearing stale web assets and finding Alpecca's current fenced endpoint.",
                true
            );
        } else if (mode == DiscoveryMode.RECOVERY) {
            showPortal(
                "RECOVERING",
                "Restoring House HQ",
                "The previous connection stopped responding. Finding Alpecca's current secure endpoint.",
                true
            );
        } else {
            showPortal(
                "FINDING",
                "Opening House HQ",
                "Finding Alpecca's current secure endpoint.",
                true
            );
        }
        endpointLabel.setText("Endpoint reconnect: querying continuity authority and mobile record.");
        runtimeLabel.setText("Runtime availability: checking local primary and fenced cloud continuity.");
        activeDiscoveryTask = discoveryNetwork.submit(() -> {
            List<DiscoveryCandidate> candidates = fetchDiscoveryCandidates();
            String saved = normalizeServerUrl(preferences.getString(PREF_SERVER_URL, ""));
            if (saved != null) {
                addDiscoveryCandidate(
                    candidates,
                    saved,
                    RuntimeLocation.UNKNOWN,
                    "last verified address"
                );
            }
            for (DiscoveryCandidate candidate : candidates) {
                if (attempt != connectionAttempt) {
                    return;
                }
                String origin = serverOrigin(candidate.serverUrl);
                runOnUiThread(() -> {
                    if (attempt != connectionAttempt) {
                        return;
                    }
                    endpointLabel.setText(
                        "Endpoint reconnect: checking " + displayHost(origin) + " from " + candidate.source + "."
                    );
                    runtimeLabel.setText(runtimeCheckingMessage(candidate.runtimeLocation));
                });
                if (probeExactAlpecca(origin)) {
                    runOnUiThread(() -> {
                        if (attempt == connectionAttempt) {
                            activeDiscoveryTask = null;
                            discoveryRunning = false;
                            endpointLabel.setText(
                                "Endpoint: " + displayHost(origin) + " via " + candidate.source + "."
                            );
                            runtimeLabel.setText(runtimeReadyMessage(candidate.runtimeLocation));
                            openServer(candidate.serverUrl, candidate.runtimeLocation, candidate.source);
                        }
                    });
                    return;
                }
            }
            runOnUiThread(() -> {
                if (attempt == connectionAttempt) {
                    activeDiscoveryTask = null;
                    discoveryRunning = false;
                    recoveryPending = true;
                    showPortal(
                        "OFFLINE",
                        "Alpecca is offline",
                        "Waiting for the local runtime or fenced cloud continuity core. This app will reconnect automatically.",
                        false
                    );
                    endpointLabel.setText(
                        saved == null
                            ? "Endpoint reconnect: no live endpoint discovered."
                            : "Endpoint reconnect: no live endpoint; last verified address was " + displayHost(saved) + "."
                    );
                    runtimeLabel.setText(
                        "Runtime availability: no local or fenced cloud runtime answered. "
                            + "The laptop must already be powered on and running Alpecca for local access."
                    );
                    scheduleAutomaticRediscovery();
                }
            });
        });
    }

    private void connectManual(String entered) {
        String normalized = normalizeServerUrl(entered);
        if (normalized == null) {
            Toast.makeText(this, "Enter a credential-free HTTPS address.", Toast.LENGTH_LONG).show();
            showSettings();
            return;
        }
        final int attempt = ++connectionAttempt;
        cancelActiveDiscoveryTask();
        mainHandler.removeCallbacks(recoveryTask);
        cancelHealthCheck();
        discoveryRunning = true;
        recoveryPending = false;
        showPortal("CHECKING", "Checking the server", "Verifying that this address is Alpecca.", true);
        endpointLabel.setText("Endpoint: checking " + displayHost(normalized) + " from manual settings.");
        runtimeLabel.setText(runtimeCheckingMessage(RuntimeLocation.UNKNOWN));
        network.execute(() -> {
            boolean valid = probeExactAlpecca(serverOrigin(normalized));
            runOnUiThread(() -> {
                if (attempt != connectionAttempt) {
                    return;
                }
                discoveryRunning = false;
                if (valid) {
                    endpointLabel.setText("Endpoint: " + displayHost(normalized) + " via manual settings.");
                    runtimeLabel.setText(runtimeReadyMessage(RuntimeLocation.UNKNOWN));
                    openServer(normalized, RuntimeLocation.UNKNOWN, "manual settings");
                } else {
                    showPortal("OFFLINE", "That server did not answer", "The address did not return Alpecca's verified health identity.", false);
                    endpointLabel.setText("Endpoint: " + displayHost(normalized) + " did not answer.");
                    runtimeLabel.setText("Runtime availability: no verified Alpecca runtime answered at this address.");
                }
            });
        });
    }

    private List<DiscoveryCandidate> fetchDiscoveryCandidates() {
        List<DiscoveryCandidate> result = new ArrayList<>();
        fetchContinuityCandidate(result);
        HttpURLConnection connection = null;
        try {
            String separator = BuildConfig.ALPECCA_DISCOVERY_URL.contains("?") ? "&" : "?";
            URL url = new URL(BuildConfig.ALPECCA_DISCOVERY_URL + separator + "t=" + System.currentTimeMillis());
            connection = (HttpURLConnection) url.openConnection();
            connection.setConnectTimeout(7000);
            connection.setReadTimeout(7000);
            connection.setInstanceFollowRedirects(false);
            connection.setUseCaches(false);
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("User-Agent", APP_USER_AGENT);
            applyRelayHeaders(connection);
            if (connection.getResponseCode() == 200) {
                JSONObject payload = new JSONObject(readLimited(connection.getInputStream(), 16 * 1024));
                if ("alpecca-mobile-discovery".equals(payload.optString("service"))
                    && payload.optInt("version") == 1) {
                    long now = System.currentTimeMillis() / 1000L;
                    JSONArray endpoints = payload.optJSONArray("endpoints");
                    List<JSONObject> rows = new ArrayList<>();
                    if (endpoints != null) {
                        for (int index = 0; index < Math.min(8, endpoints.length()); index++) {
                            JSONObject row = endpoints.optJSONObject(index);
                            if (row != null) {
                                rows.add(row);
                            }
                        }
                    }
                    rows.sort(Comparator.comparingInt(row -> row.optInt("priority", 100)));
                    for (JSONObject row : rows) {
                        String kind = row.optString("kind");
                        long expiresAt = row.optLong("expiresAt", 0L);
                        if (!"named".equals(kind) && (!"quick".equals(kind) || expiresAt <= now)) {
                            continue;
                        }
                        addDiscoveryCandidate(
                            result,
                            row.optString("url"),
                            RuntimeLocation.UNKNOWN,
                            "mobile discovery record"
                        );
                    }
                }
            }
        } catch (Exception ignored) {
            // Continuity, cloud wake, saved, and manual paths remain available.
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
        // A request wakes a sleeping free Space. Its standby identity still
        // fails probeExactAlpecca until it acquires and publishes the singleton
        // lease, so the launcher cannot open an unfenced cloud runtime.
        addDiscoveryCandidate(
            result,
            BuildConfig.ALPECCA_CLOUD_STANDBY_URL,
            RuntimeLocation.CLOUD,
            "fenced cloud wake address"
        );
        return result;
    }

    private void addDiscoveryCandidate(
        List<DiscoveryCandidate> result,
        String value,
        RuntimeLocation runtimeLocation,
        String source
    ) {
        String normalized = normalizeServerUrl(value);
        if (normalized == null) {
            return;
        }
        for (int index = 0; index < result.size(); index++) {
            DiscoveryCandidate existing = result.get(index);
            if (!existing.serverUrl.equals(normalized)) {
                continue;
            }
            if (existing.runtimeLocation == RuntimeLocation.UNKNOWN
                && runtimeLocation != RuntimeLocation.UNKNOWN) {
                result.set(index, new DiscoveryCandidate(normalized, runtimeLocation, source));
            }
            return;
        }
        result.add(new DiscoveryCandidate(normalized, runtimeLocation, source));
    }

    private void fetchContinuityCandidate(List<DiscoveryCandidate> result) {
        HttpURLConnection connection = null;
        try {
            URL url = requireHttpsUrl(
                BuildConfig.ALPECCA_CONTINUITY_DISCOVERY_URL,
                "continuity discovery"
            );
            connection = (HttpURLConnection) url.openConnection();
            connection.setConnectTimeout(7000);
            connection.setReadTimeout(7000);
            connection.setInstanceFollowRedirects(false);
            connection.setUseCaches(false);
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("Cache-Control", "no-cache");
            connection.setRequestProperty("User-Agent", APP_USER_AGENT);
            if (connection.getResponseCode() != 200) {
                return;
            }
            JSONObject payload = new JSONObject(
                readLimited(connection.getInputStream(), 16 * 1024)
            );
            JSONObject endpoint = payload.optJSONObject("endpoint");
            if (!payload.optBoolean("ok") || endpoint == null) {
                return;
            }
            String normalized = normalizeServerUrl(endpoint.optString("url"));
            addDiscoveryCandidate(
                result,
                normalized,
                runtimeLocationForHolder(endpoint.optString("holderNodeId")),
                "continuity authority"
            );
        } catch (Exception ignored) {
            // The R2, saved, and manual endpoint paths remain available.
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private RuntimeLocation runtimeLocationForHolder(String holderNodeId) {
        if (holderNodeId.startsWith("local-primary:")) {
            return RuntimeLocation.LOCAL;
        }
        if (holderNodeId.startsWith("cloud-standby:")) {
            return RuntimeLocation.CLOUD;
        }
        return RuntimeLocation.UNKNOWN;
    }

    private String runtimeCheckingMessage(RuntimeLocation runtimeLocation) {
        if (runtimeLocation == RuntimeLocation.LOCAL) {
            return "Runtime availability: local laptop runtime advertised; verifying it is online.";
        }
        if (runtimeLocation == RuntimeLocation.CLOUD) {
            return "Runtime availability: fenced cloud continuity runtime advertised; verifying it is active.";
        }
        return "Runtime availability: verifying an advertised Alpecca runtime.";
    }

    private String runtimeReadyMessage(RuntimeLocation runtimeLocation) {
        if (runtimeLocation == RuntimeLocation.LOCAL) {
            return "Runtime availability: local laptop runtime is online.";
        }
        if (runtimeLocation == RuntimeLocation.CLOUD) {
            return "Runtime availability: fenced cloud continuity runtime is active.";
        }
        return "Runtime availability: verified Alpecca runtime is online.";
    }

    private boolean probeExactAlpecca(String origin) {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(origin + "/healthz").openConnection();
            connection.setConnectTimeout(6000);
            connection.setReadTimeout(6000);
            connection.setInstanceFollowRedirects(false);
            connection.setUseCaches(false);
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("User-Agent", APP_USER_AGENT);
            applyRelayHeaders(connection);
            if (connection.getResponseCode() != 200) {
                return false;
            }
            JSONObject payload = new JSONObject(readLimited(connection.getInputStream(), 1024));
            return "alpecca".equals(payload.optString("service")) && payload.optInt("version") == 1;
        } catch (Exception ignored) {
            return false;
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private String readLimited(InputStream input, int limit) throws Exception {
        try (InputStream source = input; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[1024];
            int total = 0;
            int read;
            while ((read = source.read(buffer)) != -1) {
                total += read;
                if (total > limit) {
                    throw new IllegalArgumentException("response too large");
                }
                output.write(buffer, 0, read);
            }
            return output.toString(StandardCharsets.UTF_8.name());
        }
    }

    private void showUpdateProgress(String message, boolean indeterminate, int value) {
        if (updateStatus != null) {
            updateStatus.setText(message);
        }
        if (updateProgress != null) {
            updateProgress.setIndeterminate(indeterminate);
            if (!indeterminate) {
                updateProgress.setProgress(Math.max(0, Math.min(100, value)));
            }
        }
    }

    private void checkForUpdates(boolean manual) {
        if (updateCheckRunning || updateDownloadRunning) {
            if (manual) {
                Toast.makeText(this, "An update check is already running.", Toast.LENGTH_SHORT).show();
            }
            return;
        }

        long now = System.currentTimeMillis();
        long lastCheck = preferences.getLong(PREF_LAST_UPDATE_CHECK_MS, 0L);
        if (!manual && lastCheck > 0L && now >= lastCheck
            && now - lastCheck < UPDATE_CHECK_COOLDOWN_MS) {
            return;
        }

        preferences.edit().putLong(PREF_LAST_UPDATE_CHECK_MS, now).apply();
        updateCheckRunning = true;
        updateUpdateButtonState();
        showUpdateProgress("Checking Alpecca's signed app release...", true, 0);
        if (manual) {
            Toast.makeText(this, "Checking for an Alpecca update...", Toast.LENGTH_SHORT).show();
        }

        network.execute(() -> {
            UpdateInfo fetched = null;
            String failure = null;
            try {
                fetched = fetchUpdateManifest();
            } catch (Exception error) {
                failure = "Update check failed. Try again later.";
            }
            final UpdateInfo result = fetched;
            final String failureMessage = failure;
            runOnUiThread(() -> {
                updateCheckRunning = false;
                updateUpdateButtonState();
                if (isFinishing() || isDestroyed()) {
                    return;
                }
                if (failureMessage != null) {
                    showUpdateProgress("Update source could not be reached. Try again.", false, 0);
                    if (manual) {
                        Toast.makeText(this, failureMessage, Toast.LENGTH_LONG).show();
                    }
                    return;
                }
                if (result.versionCode <= BuildConfig.VERSION_CODE) {
                    showUpdateProgress(
                        "Alpecca app " + BuildConfig.VERSION_NAME + " is current.",
                        false,
                        100
                    );
                    if (manual) {
                        Toast.makeText(
                            this,
                            "Alpecca " + BuildConfig.VERSION_NAME + " is up to date.",
                            Toast.LENGTH_SHORT
                        ).show();
                    }
                    return;
                }
                pendingAvailableUpdate = result;
                showUpdateProgress(
                    "Alpecca app " + result.versionName + " is available to download.",
                    false,
                    0
                );
                if (activityResumed) {
                    pendingAvailableUpdate = null;
                    showUpdateAvailable(result);
                }
            });
        });
    }

    private UpdateInfo fetchUpdateManifest() throws Exception {
        URL manifestUrl = requireHttpsUrl(
            BuildConfig.ALPECCA_UPDATE_MANIFEST_URL,
            "update manifest"
        );
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) manifestUrl.openConnection();
            connection.setConnectTimeout(7000);
            connection.setReadTimeout(7000);
            connection.setInstanceFollowRedirects(false);
            connection.setUseCaches(false);
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("Cache-Control", "no-cache");
            connection.setRequestProperty("User-Agent", APP_USER_AGENT);
            if (connection.getResponseCode() != 200) {
                throw new IllegalStateException("update manifest unavailable");
            }

            JSONObject payload = new JSONObject(readLimited(connection.getInputStream(), 16 * 1024));
            Object codeValue = payload.opt("versionCode");
            if (!(codeValue instanceof Number)) {
                throw new IllegalArgumentException("update version code missing");
            }
            Number codeNumber = (Number) codeValue;
            long versionCode = codeNumber.longValue();
            if (versionCode <= 0L || versionCode > Integer.MAX_VALUE
                || codeNumber.doubleValue() != (double) versionCode) {
                throw new IllegalArgumentException("update version code invalid");
            }

            String versionName = requiredManifestString(payload, "versionName");
            String apkUrlValue = requiredManifestString(payload, "apkUrl");
            String sha256 = requiredManifestString(payload, "sha256").toLowerCase(Locale.ROOT);
            String packageName = requiredManifestString(payload, "packageName");
            if (!versionName.matches("[0-9A-Za-z][0-9A-Za-z._+-]{0,63}")) {
                throw new IllegalArgumentException("update version name invalid");
            }
            if (!sha256.matches("[0-9a-f]{64}")) {
                throw new IllegalArgumentException("update digest invalid");
            }
            if (!BuildConfig.APPLICATION_ID.equals(packageName)
                || !getPackageName().equals(packageName)) {
                throw new SecurityException("update package mismatch");
            }
            URL apkUrl = requireHttpsUrl(apkUrlValue, "update APK");
            return new UpdateInfo((int) versionCode, versionName, apkUrl, sha256, packageName);
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private String requiredManifestString(JSONObject payload, String key) {
        Object value = payload.opt(key);
        if (!(value instanceof String) || ((String) value).isEmpty()) {
            throw new IllegalArgumentException("update manifest field missing");
        }
        return (String) value;
    }

    private URL requireHttpsUrl(String raw, String label) throws Exception {
        String value = raw == null ? "" : raw.trim();
        URL url = new URL(value);
        if (!"https".equalsIgnoreCase(url.getProtocol())
            || url.getHost() == null || url.getHost().trim().isEmpty()
            || url.getUserInfo() != null || url.getRef() != null) {
            throw new SecurityException(label + " must use credential-free HTTPS");
        }
        return url;
    }

    private void showUpdateAvailable(UpdateInfo update) {
        new AlertDialog.Builder(this)
            .setTitle("Alpecca app " + update.versionName + " is available")
            .setMessage(
                "Download the Alpecca app update over HTTPS? The package will be verified before Android is allowed to open it."
            )
            .setPositiveButton("Download update", (dialog, which) -> downloadAndVerifyUpdate(update))
            .setNegativeButton("Not now", null)
            .show();
    }

    private void downloadAndVerifyUpdate(UpdateInfo update) {
        if (updateDownloadRunning) {
            return;
        }
        updateDownloadRunning = true;
        updateUpdateButtonState();
        showUpdateProgress("Downloading Alpecca app " + update.versionName + "... 0%", false, 0);
        Toast.makeText(this, "Downloading and verifying the update...", Toast.LENGTH_LONG).show();
        network.execute(() -> {
            File downloaded = null;
            String failure = null;
            try {
                downloaded = downloadUpdateApk(update, percent -> runOnUiThread(() -> {
                    if (percent < 0) {
                        showUpdateProgress(
                            "Downloading Alpecca app " + update.versionName + "...",
                            true,
                            0
                        );
                    } else if (percent < 94) {
                        showUpdateProgress(
                            "Downloading Alpecca app " + update.versionName + "... " + percent + "%",
                            false,
                            percent
                        );
                    } else if (percent < 100) {
                        showUpdateProgress("Verifying package and signature...", false, percent);
                    } else {
                        showUpdateProgress("Update verified. Ready to install.", false, 100);
                    }
                }));
            } catch (Exception error) {
                failure = "The update could not be downloaded or verified.";
            }
            final File verifiedApk = downloaded;
            final String failureMessage = failure;
            runOnUiThread(() -> {
                updateDownloadRunning = false;
                updateUpdateButtonState();
                if (isFinishing() || isDestroyed()) {
                    return;
                }
                if (failureMessage != null) {
                    showUpdateProgress("Download or verification failed.", false, 0);
                    Toast.makeText(this, failureMessage, Toast.LENGTH_LONG).show();
                    return;
                }
                VerifiedUpdate verified = new VerifiedUpdate(update, verifiedApk);
                pendingInstallUpdate = verified;
                pendingAvailableUpdate = null;
                showUpdateProgress("Update verified. Ready to install.", false, 100);
                updateUpdateButtonState();
                if (activityResumed) {
                    confirmInstallUpdate(verified);
                }
            });
        });
    }

    private File downloadUpdateApk(UpdateInfo update, UpdateProgressListener listener) throws Exception {
        File updateDir = new File(getCacheDir(), UPDATE_CACHE_DIR);
        if ((!updateDir.exists() && !updateDir.mkdirs()) || !updateDir.isDirectory()) {
            throw new IllegalStateException("update cache unavailable");
        }
        File[] staleFiles = updateDir.listFiles();
        if (staleFiles != null) {
            for (File stale : staleFiles) {
                if (stale.isFile()) {
                    stale.delete();
                }
            }
        }

        File partial = new File(updateDir, "AlpeccaLauncher-" + update.versionCode + ".apk.part");
        File complete = new File(updateDir, "AlpeccaLauncher-" + update.versionCode + ".apk");
        boolean verified = false;
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) update.apkUrl.openConnection();
            connection.setConnectTimeout(10_000);
            connection.setReadTimeout(30_000);
            connection.setInstanceFollowRedirects(false);
            connection.setUseCaches(false);
            connection.setRequestProperty("Accept", APK_MIME_TYPE);
            connection.setRequestProperty("User-Agent", APP_USER_AGENT);
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

    private void verifyDownloadedPackage(File apk, UpdateInfo update) throws Exception {
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
        Set<String> installedSigners = signerDigests(installed);
        Set<String> updateSigners = signerDigests(archive);
        if (installedSigners.isEmpty() || !installedSigners.equals(updateSigners)) {
            throw new SecurityException("downloaded package signer mismatch");
        }
    }

    @SuppressWarnings("deprecation")
    private long packageVersionCode(PackageInfo info) {
        return Build.VERSION.SDK_INT >= Build.VERSION_CODES.P
            ? info.getLongVersionCode()
            : info.versionCode;
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
        Set<String> digests = new LinkedHashSet<>();
        if (signatures != null) {
            for (android.content.pm.Signature signature : signatures) {
                digests.add(toHex(MessageDigest.getInstance("SHA-256").digest(signature.toByteArray())));
            }
        }
        return digests;
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

    private void confirmInstallUpdate(VerifiedUpdate update) {
        new AlertDialog.Builder(this)
            .setTitle("Install Alpecca app " + update.info.versionName + "?")
            .setMessage(
                "The APK passed SHA-256, package, version, and signing checks. Android will show its own installer confirmation next."
            )
            .setPositiveButton("Open installer", (dialog, which) -> openInstallerOrSettings(update))
            .setNegativeButton("Not now", null)
            .show();
    }

    private void openInstallerOrSettings(VerifiedUpdate update) {
        if (!getPackageManager().canRequestPackageInstalls()) {
            showUpdateProgress("Android install permission is required.", false, 100);
            new AlertDialog.Builder(this)
                .setTitle("Allow Alpecca app updates?")
                .setMessage(
                    "Android must allow Alpecca to request package installs. This does not allow silent installation."
                )
                .setPositiveButton("Open Android settings", (dialog, which) -> {
                    pendingInstallUpdate = update;
                    awaitingInstallPermission = true;
                    Intent settings = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES);
                    settings.setData(Uri.parse("package:" + getPackageName()));
                    try {
                        startActivity(settings);
                    } catch (ActivityNotFoundException error) {
                        awaitingInstallPermission = false;
                        pendingInstallUpdate = null;
                        Toast.makeText(this, "Android install settings are unavailable.", Toast.LENGTH_LONG).show();
                    }
                })
                .setNegativeButton("Cancel", null)
                .show();
            return;
        }
        launchPackageInstaller(update);
    }

    private void launchPackageInstaller(VerifiedUpdate update) {
        if (!update.apk.isFile()) {
            Toast.makeText(this, "The verified update file is no longer available.", Toast.LENGTH_LONG).show();
            return;
        }
        try {
            showUpdateProgress("Opening Android's installer...", false, 100);
            Uri apkUri = FileProvider.getUriForFile(
                this,
                getPackageName() + ".updates",
                update.apk
            );
            Intent installer = new Intent(Intent.ACTION_VIEW);
            installer.setDataAndType(apkUri, APK_MIME_TYPE);
            installer.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            startActivity(installer);
            pendingInstallUpdate = null;
            updateUpdateButtonState();
        } catch (ActivityNotFoundException | IllegalArgumentException | SecurityException error) {
            showUpdateProgress("Android's package installer is unavailable.", false, 100);
            Toast.makeText(this, "Android's package installer is unavailable.", Toast.LENGTH_LONG).show();
        }
    }

    private void resumePendingInstallerPermission() {
        if (awaitingInstallPermission) {
            awaitingInstallPermission = false;
            VerifiedUpdate pending = pendingInstallUpdate;
            pendingInstallUpdate = null;
            if (pending != null && getPackageManager().canRequestPackageInstalls()) {
                confirmInstallUpdate(pending);
            } else if (pending != null) {
                showUpdateProgress("Alpecca app update permission was not enabled.", false, 100);
                Toast.makeText(this, "Alpecca app update permission was not enabled.", Toast.LENGTH_LONG).show();
            }
            return;
        }
        if (pendingInstallUpdate != null) {
            VerifiedUpdate pending = pendingInstallUpdate;
            pendingInstallUpdate = null;
            confirmInstallUpdate(pending);
        }
    }

    private void updateUpdateButtonState() {
        if (updateButton == null) {
            return;
        }
        boolean busy = updateCheckRunning || updateDownloadRunning;
        updateButton.setEnabled(!busy);
        updateButton.setText(
            updateDownloadRunning
                ? "Downloading Alpecca update..."
                : updateCheckRunning ? "Checking Alpecca updates..." : "Check for Alpecca update"
        );
        if (installUpdateButton != null) {
            installUpdateButton.setVisibility(
                pendingInstallUpdate == null ? View.GONE : View.VISIBLE
            );
        }
    }

    private interface UpdateProgressListener {
        void onProgress(int percent);
    }

    private enum DiscoveryMode {
        STARTUP,
        RECOVERY,
        RECONNECT,
        SOURCE_REFRESH
    }

    private enum RuntimeLocation {
        LOCAL,
        CLOUD,
        UNKNOWN
    }

    private static final class DiscoveryCandidate {
        final String serverUrl;
        final RuntimeLocation runtimeLocation;
        final String source;

        DiscoveryCandidate(String serverUrl, RuntimeLocation runtimeLocation, String source) {
            this.serverUrl = serverUrl;
            this.runtimeLocation = runtimeLocation;
            this.source = source;
        }
    }

    private static final class UpdateInfo {
        final int versionCode;
        final String versionName;
        final URL apkUrl;
        final String sha256;
        final String packageName;

        UpdateInfo(int versionCode, String versionName, URL apkUrl, String sha256, String packageName) {
            this.versionCode = versionCode;
            this.versionName = versionName;
            this.apkUrl = apkUrl;
            this.sha256 = sha256;
            this.packageName = packageName;
        }
    }

    private static final class VerifiedUpdate {
        final UpdateInfo info;
        final File apk;

        VerifiedUpdate(UpdateInfo info, File apk) {
            this.info = info;
            this.apk = apk;
        }
    }

    private void openServer(String value, RuntimeLocation runtimeLocation, String source) {
        String normalized = normalizeServerUrl(value);
        if (normalized == null) {
            showConnectionFailure("The discovered server address was invalid.");
            return;
        }
        endpointLabel.setText("Endpoint: " + displayHost(normalized) + " via " + source + ".");
        runtimeLabel.setText(runtimeReadyMessage(runtimeLocation));
        String previous = normalizeServerUrl(preferences.getString(PREF_SERVER_URL, ""));
        preferences.edit().putString(PREF_SERVER_URL, normalized).apply();
        serverField.setText(normalized);
        activeServerUrl = normalized;
        recoveryPending = false;
        Uri.Builder houseBuilder = Uri.parse(normalized).buildUpon()
            .clearQuery()
            .appendQueryParameter("embodiment", "vrm")
            .appendQueryParameter("view", "orthographic")
            .appendQueryParameter("client", "android");
        if (forceSourceRefresh) {
            houseBuilder.appendQueryParameter(
                "source_refresh",
                BuildConfig.VERSION_CODE + "-" + System.currentTimeMillis()
            );
            forceSourceRefresh = false;
        }
        Uri house = houseBuilder.build();
        showPortal("OPENING", "Opening House HQ", "The secure server is ready. Loading Alpecca's embodied space.", true);
        webView.stopLoading();
        if (previous != null && !serverOrigin(previous).equals(serverOrigin(normalized))) {
            clearHistoryAfterLoad = true;
        }
        String deviceId = preferences.getString(PREF_DEVICE_ID, "");
        if (!deviceId.isEmpty() && !hasDeviceKey()) {
            preferences.edit().remove(PREF_DEVICE_ID).apply();
            deviceId = "";
        }
        if (!deviceId.isEmpty() && hasDeviceKey()) {
            final int attempt = connectionAttempt;
            final long generation = trustGeneration;
            final String trustedDeviceId = deviceId;
            final String origin = serverOrigin(normalized);
            showPortal("VERIFYING", "Recognizing this phone", "Restoring its trusted CreatorJD session for the current secure address.", true);
            network.execute(() -> {
                DeviceExchangeResult exchange = exchangeDeviceSession(origin, trustedDeviceId);
                runOnUiThread(() -> {
                    if (attempt != connectionAttempt || generation != trustGeneration) {
                        return;
                    }
                    if (exchange.clearRegistration) {
                        clearLocalDeviceRegistration();
                    }
                    installDeviceCookies(
                        origin,
                        exchange.cookies,
                        () -> loadHouseUrl(house.toString())
                    );
                });
            });
            return;
        }
        loadHouseUrl(house.toString());
    }

    private void installDeviceCookies(String origin, List<String> cookies, Runnable completion) {
        if (cookies.isEmpty()) {
            completion.run();
            return;
        }
        installDeviceCookie(origin, cookies, 0, completion);
    }

    private void installDeviceCookie(
        String origin,
        List<String> cookies,
        int index,
        Runnable completion
    ) {
        CookieManager manager = CookieManager.getInstance();
        manager.setCookie(origin, cookies.get(index), accepted -> runOnUiThread(() -> {
            if (index + 1 < cookies.size()) {
                installDeviceCookie(origin, cookies, index + 1, completion);
                return;
            }
            manager.flush();
            completion.run();
        }));
    }

    private void loadHouseUrl(String houseUrl) {
        // LocalTunnel otherwise inserts a browser-only warning page. Normal and
        // Cloudflare origins ignore this header, so discovery has one load path.
        webView.loadUrl(
            houseUrl,
            Collections.singletonMap(RELAY_BYPASS_HEADER, RELAY_BYPASS_VALUE)
        );
    }

    private void applyRelayHeaders(HttpURLConnection connection) {
        // LocalTunnel's reminder page otherwise makes a healthy Alpecca relay
        // fail exact health and native device-session checks. The header is
        // non-secret and ignored by Cloudflare, R2, and direct HTTPS servers.
        connection.setRequestProperty(RELAY_BYPASS_HEADER, RELAY_BYPASS_VALUE);
    }

    private boolean hasDeviceKey() {
        try {
            KeyStore store = KeyStore.getInstance("AndroidKeyStore");
            store.load(null);
            return store.containsAlias(DEVICE_KEY_ALIAS);
        } catch (Exception ignored) {
            return false;
        }
    }

    private byte[] ensureDevicePublicKey() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (!store.containsAlias(DEVICE_KEY_ALIAS)) {
            KeyPairGenerator generator = KeyPairGenerator.getInstance(
                KeyProperties.KEY_ALGORITHM_EC,
                "AndroidKeyStore"
            );
            generator.initialize(new KeyGenParameterSpec.Builder(
                DEVICE_KEY_ALIAS,
                KeyProperties.PURPOSE_SIGN | KeyProperties.PURPOSE_VERIFY
            )
                .setDigests(KeyProperties.DIGEST_SHA256)
                .setAlgorithmParameterSpec(new java.security.spec.ECGenParameterSpec("secp256r1"))
                .setUserAuthenticationRequired(false)
                .build());
            generator.generateKeyPair();
            store.load(null);
        }
        java.security.cert.Certificate certificate = store.getCertificate(DEVICE_KEY_ALIAS);
        if (certificate == null) {
            throw new IllegalStateException("device key certificate unavailable");
        }
        return certificate.getPublicKey().getEncoded();
    }

    private byte[] signDeviceChallenge(byte[] message) throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        PrivateKey key = (PrivateKey) store.getKey(DEVICE_KEY_ALIAS, null);
        if (key == null) {
            throw new IllegalStateException("device key unavailable");
        }
        Signature signer = Signature.getInstance("SHA256withECDSA");
        signer.initSign(key);
        signer.update(message);
        return signer.sign();
    }

    private byte[] validateDeviceChallenge(
        JSONObject challenge,
        String deviceId,
        String origin
    ) throws Exception {
        String challengeId = challenge.optString("challenge_id", "");
        String encoded = challenge.optString("message", "");
        long expiresAt = challenge.optLong("expires_at", 0L);
        if (challengeId.length() < 12 || challengeId.length() > 64
            || encoded.isEmpty() || encoded.length() > 1400) {
            throw new SecurityException("invalid device challenge envelope");
        }
        byte[] message = Base64.decode(
            encoded,
            Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING
        );
        if (message.length == 0 || message.length > 1024) {
            throw new SecurityException("invalid device challenge size");
        }
        String transcript = new String(message, StandardCharsets.UTF_8);
        if (!java.util.Arrays.equals(message, transcript.getBytes(StandardCharsets.UTF_8))) {
            throw new SecurityException("device challenge is not UTF-8");
        }
        String[] lines = transcript.split("\\n", -1);
        if (lines.length != 6
            || !"alpecca-device-auth-v2".equals(lines[0])
            || !deviceId.equals(lines[1])
            || !challengeId.equals(lines[2])
            || !Long.toString(expiresAt).equals(lines[3])
            || !origin.equals(lines[5])) {
            throw new SecurityException("device challenge binding mismatch");
        }
        long now = System.currentTimeMillis() / 1000L;
        if (expiresAt <= now - 30L || expiresAt > now + 180L) {
            throw new SecurityException("device challenge expiry invalid");
        }
        String nonce = lines[4];
        if (nonce.length() != 43) {
            throw new SecurityException("device challenge nonce invalid");
        }
        for (int index = 0; index < nonce.length(); index++) {
            char value = nonce.charAt(index);
            if (!(value >= 'A' && value <= 'Z')
                && !(value >= 'a' && value <= 'z')
                && !(value >= '0' && value <= '9')
                && value != '-' && value != '_') {
                throw new SecurityException("device challenge nonce invalid");
            }
        }
        byte[] decodedNonce = Base64.decode(
            nonce,
            Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING
        );
        if (decodedNonce.length != 32) {
            throw new SecurityException("device challenge nonce invalid");
        }
        return message;
    }

    private void deleteDeviceKey() {
        try {
            KeyStore store = KeyStore.getInstance("AndroidKeyStore");
            store.load(null);
            if (store.containsAlias(DEVICE_KEY_ALIAS)) {
                store.deleteEntry(DEVICE_KEY_ALIAS);
            }
        } catch (Exception ignored) {
            // Clearing the local registration id still prevents future exchange.
        }
    }

    private void clearLocalDeviceRegistration() {
        trustGeneration++;
        preferences.edit().remove(PREF_DEVICE_ID).apply();
        deleteDeviceKey();
    }

    private void ensureDeviceEnrollment() {
        if (deviceEnrollmentRunning || activeServerUrl.isEmpty()
            || !preferences.getString(PREF_DEVICE_ID, "").isEmpty()) {
            return;
        }
        String origin = serverOrigin(activeServerUrl);
        String cookie = CookieManager.getInstance().getCookie(origin);
        if (cookie == null || cookie.isEmpty()) {
            return;
        }
        deviceEnrollmentRunning = true;
        final long generation = trustGeneration;
        final int attempt = connectionAttempt;
        network.execute(() -> {
            String enrolledId = "";
            try {
                byte[] publicKey = ensureDevicePublicKey();
                JSONObject payload = new JSONObject()
                    .put("label", "CreatorJD Android phone")
                    .put("public_key", Base64.encodeToString(
                        publicKey,
                        Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING
                    ));
                HttpResult result = postDeviceJson(origin, "/auth/device/enroll", payload, cookie);
                if (result.status == 200) {
                    enrolledId = new JSONObject(result.body).optString("device_id", "");
                }
            } catch (Exception ignored) {
                enrolledId = "";
            }
            String finalId = enrolledId;
            runOnUiThread(() -> {
                deviceEnrollmentRunning = false;
                if (generation == trustGeneration
                    && attempt == connectionAttempt
                    && origin.equals(serverOrigin(activeServerUrl))
                    && !finalId.isEmpty()) {
                    preferences.edit().putString(PREF_DEVICE_ID, finalId).apply();
                    Toast.makeText(this, "This phone is now trusted across secure address changes.", Toast.LENGTH_SHORT).show();
                }
            });
        });
    }

    private DeviceExchangeResult exchangeDeviceSession(String origin, String deviceId) {
        try {
            HttpResult challengeResult = postDeviceJson(
                origin,
                "/auth/device/challenge",
                new JSONObject().put("device_id", deviceId),
                null
            );
            if (challengeResult.status != 200) {
                return new DeviceExchangeResult(
                    Collections.emptyList(),
                    challengeResult.status == 401 || challengeResult.status == 404
                );
            }
            JSONObject challenge = new JSONObject(challengeResult.body);
            byte[] message = validateDeviceChallenge(challenge, deviceId, origin);
            byte[] signature = signDeviceChallenge(message);
            JSONObject exchange = new JSONObject()
                .put("challenge_id", challenge.optString("challenge_id"))
                .put("signature", Base64.encodeToString(
                    signature,
                    Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING
                ));
            HttpResult exchangeResult = postDeviceJson(origin, "/auth/device/exchange", exchange, null);
            if (exchangeResult.status != 200) {
                return new DeviceExchangeResult(
                    Collections.emptyList(),
                    exchangeResult.status == 401 || exchangeResult.status == 404
                );
            }
            return new DeviceExchangeResult(exchangeResult.cookies, false);
        } catch (Exception ignored) {
            return new DeviceExchangeResult(Collections.emptyList(), !hasDeviceKey());
        }
    }

    private static final class DeviceExchangeResult {
        final List<String> cookies;
        final boolean clearRegistration;

        DeviceExchangeResult(List<String> cookies, boolean clearRegistration) {
            this.cookies = cookies;
            this.clearRegistration = clearRegistration;
        }
    }

    private HttpResult postDeviceJson(String origin, String path, JSONObject payload, String cookie) throws Exception {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(origin + path).openConnection();
            connection.setConnectTimeout(7000);
            connection.setReadTimeout(7000);
            connection.setInstanceFollowRedirects(false);
            connection.setUseCaches(false);
            connection.setRequestMethod("POST");
            connection.setDoOutput(true);
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("Content-Type", "application/json");
            connection.setRequestProperty("Origin", origin);
            connection.setRequestProperty("User-Agent", APP_USER_AGENT);
            applyRelayHeaders(connection);
            if (cookie != null && !cookie.isEmpty()) {
                connection.setRequestProperty("Cookie", cookie);
            }
            byte[] body = payload.toString().getBytes(StandardCharsets.UTF_8);
            if (body.length > 8192) {
                throw new IllegalArgumentException("device request too large");
            }
            connection.setFixedLengthStreamingMode(body.length);
            try (OutputStream output = connection.getOutputStream()) {
                output.write(body);
            }
            int status = connection.getResponseCode();
            InputStream stream = status >= 200 && status < 400
                ? connection.getInputStream()
                : connection.getErrorStream();
            String responseBody = stream == null ? "" : readLimited(stream, 16 * 1024);
            List<String> cookies = new ArrayList<>();
            for (java.util.Map.Entry<String, List<String>> header : connection.getHeaderFields().entrySet()) {
                if (header.getKey() != null && "set-cookie".equalsIgnoreCase(header.getKey())) {
                    cookies.addAll(header.getValue());
                }
            }
            return new HttpResult(status, responseBody, cookies);
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private void revokeDeviceRegistration(
        String origin,
        String deviceId,
        String cookie
    ) throws Exception {
        if (origin.isEmpty() || deviceId.isEmpty() || cookie == null || cookie.isEmpty()) {
            return;
        }
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(
                origin + "/auth/device/" + Uri.encode(deviceId)
            ).openConnection();
            connection.setConnectTimeout(7000);
            connection.setReadTimeout(7000);
            connection.setInstanceFollowRedirects(false);
            connection.setUseCaches(false);
            connection.setRequestMethod("DELETE");
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("Origin", origin);
            connection.setRequestProperty("Cookie", cookie);
            connection.setRequestProperty("User-Agent", APP_USER_AGENT);
            applyRelayHeaders(connection);
            int status = connection.getResponseCode();
            InputStream stream = status >= 200 && status < 400
                ? connection.getInputStream()
                : connection.getErrorStream();
            if (stream != null) {
                readLimited(stream, 16 * 1024);
            }
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private static final class HttpResult {
        final int status;
        final String body;
        final List<String> cookies;

        HttpResult(int status, String body, List<String> cookies) {
            this.status = status;
            this.body = body;
            this.cookies = cookies;
        }
    }

    private String normalizeServerUrl(String entered) {
        String value = entered == null ? "" : entered.trim();
        if (value.isEmpty()) {
            return null;
        }
        if (!value.contains("://")) {
            value = "https://" + value;
        }
        Uri uri = Uri.parse(value);
        if (!"https".equalsIgnoreCase(uri.getScheme()) || uri.getHost() == null || uri.getHost().trim().isEmpty()) {
            return null;
        }
        if (uri.getUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null) {
            return null;
        }
        String path = uri.getPath();
        if (path != null && !path.isEmpty() && !"/".equals(path) && !"/house-hq".equals(path)) {
            return null;
        }
        return uri.buildUpon().path("/house-hq").clearQuery().fragment(null).build().toString();
    }

    private String serverOrigin(String serverUrl) {
        Uri uri = Uri.parse(serverUrl);
        return uri.getScheme() + "://" + uri.getAuthority();
    }

    private String displayHost(String value) {
        Uri uri = Uri.parse(value == null ? "" : value);
        return uri.getHost() == null ? "secure server" : uri.getHost();
    }

    private boolean isConfiguredOrigin(Uri candidate) {
        if (candidate == null || !"https".equalsIgnoreCase(candidate.getScheme())) {
            return false;
        }
        String configured = normalizeServerUrl(preferences.getString(PREF_SERVER_URL, ""));
        if (configured == null) {
            return false;
        }
        Uri expected = Uri.parse(configured);
        int candidatePort = candidate.getPort() == -1 ? 443 : candidate.getPort();
        int expectedPort = expected.getPort() == -1 ? 443 : expected.getPort();
        return expected.getHost() != null
            && expected.getHost().equalsIgnoreCase(candidate.getHost())
            && candidatePort == expectedPort;
    }

    private void showPortal(String badge, String title, String detail, boolean loading) {
        statusBadge.setText(badge);
        statusBadge.setTextColor(loading ? CYAN : GOLD);
        statusBadge.setBackground(rounded(PANEL_HIGH, dp(20), loading ? CYAN : GOLD));
        phaseTitle.setText(title);
        phaseDetail.setText(detail);
        progress.setVisibility(loading ? View.VISIBLE : View.INVISIBLE);
        progress.setIndeterminate(loading);
        portal.setVisibility(View.VISIBLE);
        webView.setVisibility(View.INVISIBLE);
        nativeMenu.setVisibility(View.GONE);
    }

    private void showHouseSurface() {
        portal.setVisibility(View.GONE);
        webView.setVisibility(View.VISIBLE);
        nativeMenu.setVisibility(View.VISIBLE);
    }

    private void showConnectionFailure(String message) {
        pageFailed = true;
        showPortal(
            "OFFLINE",
            "Connection lost",
            message + " Reconnect will rediscover the endpoint after a runtime is available.",
            false
        );
        String saved = preferences.getString(PREF_SERVER_URL, "");
        endpointLabel.setText(
            saved.isEmpty()
                ? "Endpoint reconnect: no verified address is saved."
                : "Endpoint reconnect: last verified address was " + displayHost(saved) + "."
        );
        runtimeLabel.setText(
            "Runtime availability: unavailable. The laptop must already be powered on and running Alpecca for local access."
        );
    }

    private void beginAutomaticRecovery(String message) {
        if (recoveryPending || discoveryRunning) {
            return;
        }
        pageFailed = true;
        recoveryPending = true;
        webView.stopLoading();
        showPortal("RECOVERING", "Restoring House HQ", message + " Looking for Alpecca's latest secure phone link.", true);
        startDiscovery(DiscoveryMode.RECOVERY);
    }

    private void scheduleAutomaticRediscovery() {
        if (!activityResumed || discoveryRunning || !recoveryPending) {
            return;
        }
        long multiplier = 1L << Math.min(automaticRetryCount, 4);
        long delay = Math.min(RECOVERY_RETRY_MAX_MS, 2_000L * multiplier);
        automaticRetryCount++;
        mainHandler.removeCallbacks(recoveryTask);
        mainHandler.postDelayed(recoveryTask, delay);
    }

    private void scheduleHealthCheck(long delayMs) {
        cancelHealthCheck();
        if (activityResumed && !activeServerUrl.isEmpty() && !recoveryPending && !discoveryRunning) {
            mainHandler.postDelayed(healthCheckTask, delayMs);
        }
    }

    private void cancelHealthCheck() {
        mainHandler.removeCallbacks(healthCheckTask);
    }

    private void runForegroundHealthCheck() {
        if (!activityResumed || activeServerUrl.isEmpty() || recoveryPending || discoveryRunning) {
            return;
        }
        String checkedServer = activeServerUrl;
        network.execute(() -> {
            boolean healthy = probeExactAlpecca(serverOrigin(checkedServer));
            runOnUiThread(() -> {
                if (!activityResumed || !checkedServer.equals(activeServerUrl) || recoveryPending || discoveryRunning) {
                    return;
                }
                if (healthy) {
                    consecutiveHealthFailures = 0;
                    scheduleHealthCheck(HEALTH_CHECK_INTERVAL_MS);
                    return;
                }
                consecutiveHealthFailures++;
                if (consecutiveHealthFailures < 2) {
                    scheduleHealthCheck(HEALTH_CHECK_CONFIRM_MS);
                } else {
                    beginAutomaticRecovery("The current secure tunnel stopped responding.");
                }
            });
        });
    }

    private void registerNetworkRecovery() {
        connectivityManager = getSystemService(ConnectivityManager.class);
        if (connectivityManager == null) {
            return;
        }
        try {
            connectivityManager.registerDefaultNetworkCallback(networkCallback);
            networkCallbackRegistered = true;
        } catch (RuntimeException ignored) {
            networkCallbackRegistered = false;
        }
    }

    private void showSettings() {
        serverField.setText(preferences.getString(PREF_SERVER_URL, ""));
        updateUpdateButtonState();
        settingsOverlay.setVisibility(View.VISIBLE);
    }

    private void hideSettings() {
        settingsOverlay.setVisibility(View.GONE);
    }

    private void refreshHouseSource() {
        hideSettings();
        forceSourceRefresh = true;
        clearHistoryAfterLoad = true;
        pageFailed = false;
        recoveryPending = false;
        connectionAttempt++;
        discoveryRunning = false;
        cancelActiveDiscoveryTask();
        webView.stopLoading();
        webView.clearCache(true);
        startDiscovery(DiscoveryMode.SOURCE_REFRESH);
    }

    private void openAndroidSettings() {
        Intent intent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
        intent.setData(Uri.parse("package:" + getPackageName()));
        startActivity(intent);
    }

    private void confirmClearSession() {
        new AlertDialog.Builder(this)
            .setTitle("Clear trusted session?")
            .setMessage("This removes the trusted session and this phone's device key. The creator password will be required again.")
            .setPositiveButton("Clear", (dialog, which) -> clearTrustedSession())
            .setNegativeButton("Cancel", null)
            .show();
    }

    private void clearTrustedSession() {
        final long generation = ++trustGeneration;
        connectionAttempt++;
        deviceEnrollmentRunning = false;
        discoveryRunning = false;
        cancelActiveDiscoveryTask();
        mainHandler.removeCallbacks(recoveryTask);
        cancelHealthCheck();
        webView.stopLoading();

        String configured = normalizeServerUrl(
            activeServerUrl.isEmpty()
                ? preferences.getString(PREF_SERVER_URL, "")
                : activeServerUrl
        );
        String origin = configured == null ? "" : serverOrigin(configured);
        String deviceId = preferences.getString(PREF_DEVICE_ID, "");
        String cookie = origin.isEmpty() ? null : CookieManager.getInstance().getCookie(origin);
        showPortal("CLEARING", "Clearing trusted phone", "Revoking this device and removing its local session.", true);

        network.execute(() -> {
            try {
                revokeDeviceRegistration(origin, deviceId, cookie);
            } catch (Exception ignored) {
                // Local deletion still completes; server-side revocation remains available.
            }
            runOnUiThread(() -> {
                if (generation != trustGeneration) {
                    return;
                }
                CookieManager manager = CookieManager.getInstance();
                manager.removeAllCookies(cleared -> runOnUiThread(() -> {
                    if (generation != trustGeneration) {
                        return;
                    }
                    manager.flush();
                    WebStorage.getInstance().deleteAllData();
                    preferences.edit()
                        .remove(PREF_MEDIA_ORIGIN)
                        .remove(PREF_DEVICE_ID)
                        .apply();
                    deleteDeviceKey();
                    webView.clearCache(true);
                    hideSettings();
                    discoverAndConnect();
                }));
            });
        });
    }

    private void openExternal(Uri uri) {
        if (uri == null || !"https".equalsIgnoreCase(uri.getScheme())) {
            Toast.makeText(this, "Only HTTPS links can be opened.", Toast.LENGTH_SHORT).show();
            return;
        }
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (ActivityNotFoundException error) {
            Toast.makeText(this, "No browser is available for this link.", Toast.LENGTH_LONG).show();
        }
    }

    private void handleWebPermissionRequest(PermissionRequest request) {
        if (!isConfiguredOrigin(request.getOrigin())) {
            request.deny();
            return;
        }
        List<String> allowedResources = new ArrayList<>();
        List<String> androidPermissions = new ArrayList<>();
        for (String resource : request.getResources()) {
            if (PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(resource)) {
                allowedResources.add(resource);
                if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                    androidPermissions.add(Manifest.permission.RECORD_AUDIO);
                }
            } else if (PermissionRequest.RESOURCE_VIDEO_CAPTURE.equals(resource)) {
                allowedResources.add(resource);
                if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                    androidPermissions.add(Manifest.permission.CAMERA);
                }
            }
        }
        if (allowedResources.isEmpty()) {
            request.deny();
            return;
        }
        pendingWebPermission = request;
        pendingWebResources = allowedResources.toArray(new String[0]);
        if (androidPermissions.isEmpty()) {
            confirmWebPermission();
        } else {
            requestPermissions(androidPermissions.toArray(new String[0]), REQUEST_WEB_PERMISSIONS);
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != REQUEST_WEB_PERMISSIONS || pendingWebPermission == null) {
            return;
        }
        List<String> granted = new ArrayList<>();
        for (String resource : pendingWebResources) {
            if (PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(resource)
                && checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                granted.add(resource);
            } else if (PermissionRequest.RESOURCE_VIDEO_CAPTURE.equals(resource)
                && checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
                granted.add(resource);
            }
        }
        if (granted.isEmpty()) {
            pendingWebPermission.deny();
            clearPendingWebPermission();
            return;
        }
        pendingWebResources = granted.toArray(new String[0]);
        confirmWebPermission();
    }

    private void confirmWebPermission() {
        if (pendingWebPermission == null) {
            return;
        }
        String origin = pendingWebPermission.getOrigin().toString();
        String deviceId = preferences.getString(PREF_DEVICE_ID, "");
        if (!deviceId.isEmpty() && hasDeviceKey()) {
            // Device registration already establishes CreatorJD's trusted phone.
            // Android runtime permissions remain the explicit camera/mic gate.
            preferences.edit().putString(PREF_MEDIA_ORIGIN, origin).apply();
            pendingWebPermission.grant(pendingWebResources);
            clearPendingWebPermission();
            return;
        }
        String trustedOrigin = preferences.getString(PREF_MEDIA_ORIGIN, "");
        if (origin.equals(trustedOrigin)) {
            pendingWebPermission.grant(pendingWebResources);
            clearPendingWebPermission();
            return;
        }
        String host = pendingWebPermission.getOrigin().getHost();
        new AlertDialog.Builder(this)
            .setTitle("Allow live media?")
            .setMessage("Allow Alpecca at " + host + " to use this phone's requested microphone or camera access?")
            .setPositiveButton("Allow", (dialog, which) -> {
                preferences.edit().putString(PREF_MEDIA_ORIGIN, origin).apply();
                if (pendingWebPermission != null) {
                    pendingWebPermission.grant(pendingWebResources);
                }
                clearPendingWebPermission();
            })
            .setNegativeButton("Not now", (dialog, which) -> {
                if (pendingWebPermission != null) {
                    pendingWebPermission.deny();
                }
                clearPendingWebPermission();
            })
            .setOnCancelListener(dialog -> {
                if (pendingWebPermission != null) {
                    pendingWebPermission.deny();
                }
                clearPendingWebPermission();
            })
            .show();
    }

    private void clearPendingWebPermission() {
        pendingWebPermission = null;
        pendingWebResources = new String[0];
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQUEST_FILE && fileCallback != null) {
            Uri[] result = WebChromeClient.FileChooserParams.parseResult(resultCode, data);
            fileCallback.onReceiveValue(result);
            fileCallback = null;
        }
    }

    @Override
    public void onBackPressed() {
        if (settingsOverlay.getVisibility() == View.VISIBLE) {
            hideSettings();
        } else if (webView.getVisibility() == View.VISIBLE && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        activityResumed = true;
        webView.onResume();
        if (!startupUpdateCheckRequested) {
            startupUpdateCheckRequested = true;
            checkForUpdates(false);
        }
        resumePendingInstallerPermission();
        if (pendingAvailableUpdate != null) {
            UpdateInfo pending = pendingAvailableUpdate;
            pendingAvailableUpdate = null;
            showUpdateAvailable(pending);
        }
        if (recoveryPending) {
            scheduleAutomaticRediscovery();
        } else if (!activeServerUrl.isEmpty()) {
            scheduleHealthCheck(1_000L);
        }
    }

    @Override
    protected void onPause() {
        activityResumed = false;
        mainHandler.removeCallbacks(recoveryTask);
        cancelHealthCheck();
        CookieManager.getInstance().flush();
        webView.onPause();
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        connectionAttempt++;
        cancelActiveDiscoveryTask();
        mainHandler.removeCallbacksAndMessages(null);
        if (networkCallbackRegistered && connectivityManager != null) {
            try {
                connectivityManager.unregisterNetworkCallback(networkCallback);
            } catch (RuntimeException ignored) {
                // Already unregistered by the platform.
            }
        }
        network.shutdownNow();
        discoveryNetwork.shutdownNow();
        if (fileCallback != null) {
            fileCallback.onReceiveValue(null);
            fileCallback = null;
        }
        if (pendingWebPermission != null) {
            pendingWebPermission.deny();
            clearPendingWebPermission();
        }
        webView.stopLoading();
        webView.destroy();
        super.onDestroy();
    }

    private TextView text(String value, int size, int color, boolean bold) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextColor(color);
        view.setTextSize(size);
        view.setLetterSpacing(0f);
        if (bold) {
            view.setTypeface(view.getTypeface(), android.graphics.Typeface.BOLD);
        }
        return view;
    }

    private Button primaryButton(String label) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextColor(BG);
        button.setTextSize(15);
        button.setAllCaps(false);
        button.setBackground(rounded(CYAN, dp(6), Color.TRANSPARENT));
        return button;
    }

    private Button secondaryButton(String label) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextColor(TEXT);
        button.setTextSize(14);
        button.setAllCaps(false);
        button.setBackground(rounded(PANEL_HIGH, dp(6), Color.rgb(65, 80, 101)));
        return button;
    }

    private Button compactButton(String label) {
        Button button = secondaryButton(label);
        button.setTextSize(13);
        button.setPadding(dp(8), 0, dp(8), 0);
        return button;
    }

    private GradientDrawable rounded(int fill, float radius, int stroke) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(fill);
        drawable.setCornerRadius(radius);
        if (stroke != Color.TRANSPARENT) {
            drawable.setStroke(dp(1), stroke);
        }
        return drawable;
    }

    private LinearLayout.LayoutParams fullButtonParams() {
        return new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(52));
    }

    private FrameLayout.LayoutParams matchParent() {
        return new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
