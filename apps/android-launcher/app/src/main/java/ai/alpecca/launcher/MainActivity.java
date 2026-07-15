package ai.alpecca.launcher;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Bundle;
import android.provider.Settings;
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
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private static final String PREFS = "alpecca_launcher";
    private static final String PREF_SERVER_URL = "server_url";
    private static final String PREF_MEDIA_ORIGIN = "media_origin";
    private static final int REQUEST_WEB_PERMISSIONS = 4001;
    private static final int REQUEST_FILE = 4002;

    private static final int BG = Color.rgb(10, 14, 21);
    private static final int PANEL = Color.rgb(19, 25, 36);
    private static final int PANEL_HIGH = Color.rgb(31, 40, 55);
    private static final int TEXT = Color.rgb(255, 248, 232);
    private static final int MUTED = Color.rgb(160, 174, 194);
    private static final int CYAN = Color.rgb(142, 238, 255);
    private static final int GOLD = Color.rgb(240, 189, 89);

    private final ExecutorService network = Executors.newSingleThreadExecutor();
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
    private ProgressBar progress;
    private EditText serverField;
    private ValueCallback<Uri[]> fileCallback;
    private PermissionRequest pendingWebPermission;
    private String[] pendingWebResources = new String[0];
    private boolean pageFailed;
    private int connectionAttempt;

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

        endpointLabel = text("Discovery: secure mobile record", 11, MUTED, false);
        endpointLabel.setPadding(0, dp(12), 0, dp(12));
        recovery.addView(endpointLabel);

        Button retry = primaryButton("Reconnect");
        retry.setOnClickListener(view -> discoverAndConnect());
        recovery.addView(retry, fullButtonParams());

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

        TextView title = text("Connection", 24, TEXT, true);
        sheet.addView(title);
        TextView help = text(
            "The app normally discovers Alpecca automatically. Use a manual HTTPS address only when needed.",
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

        Button permissions = secondaryButton("Android camera and microphone settings");
        permissions.setOnClickListener(view -> openAndroidSettings());
        LinearLayout.LayoutParams permissionParams = fullButtonParams();
        permissionParams.topMargin = dp(8);
        sheet.addView(permissions, permissionParams);

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

        FrameLayout.LayoutParams sheetParams = new FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT
        );
        sheetParams.gravity = Gravity.BOTTOM;
        sheetParams.leftMargin = dp(12);
        sheetParams.rightMargin = dp(12);
        sheetParams.bottomMargin = dp(8);
        overlay.addView(sheet, sheetParams);
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
        settings.setUserAgentString(settings.getUserAgentString() + " AlpeccaAndroid/2.0");

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
                    showHouseSurface();
                }
                CookieManager.getInstance().flush();
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) {
                    showConnectionFailure("Alpecca's server could not be reached.");
                }
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse response) {
                if (request.isForMainFrame() && response.getStatusCode() >= 500) {
                    showConnectionFailure("Alpecca's server returned " + response.getStatusCode() + ".");
                }
            }

            @Override
            public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
                handler.cancel();
                showConnectionFailure("The server certificate could not be verified.");
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
        final int attempt = ++connectionAttempt;
        showPortal("FINDING", "Opening House HQ", "Finding Alpecca's current secure connection.", true);
        endpointLabel.setText("Discovery: secure mobile record");
        network.execute(() -> {
            List<String> discovered = fetchDiscoveryCandidates();
            Set<String> candidates = new LinkedHashSet<>(discovered);
            String saved = normalizeServerUrl(preferences.getString(PREF_SERVER_URL, ""));
            if (saved != null) {
                candidates.add(saved);
            }
            for (String candidate : candidates) {
                if (attempt != connectionAttempt) {
                    return;
                }
                String origin = serverOrigin(candidate);
                runOnUiThread(() -> endpointLabel.setText("Checking " + displayHost(origin)));
                if (probeExactAlpecca(origin)) {
                    runOnUiThread(() -> {
                        if (attempt == connectionAttempt) {
                            openServer(candidate);
                        }
                    });
                    return;
                }
            }
            runOnUiThread(() -> {
                if (attempt == connectionAttempt) {
                    showPortal(
                        "OFFLINE",
                        "Alpecca is offline",
                        "Start Alpecca on the laptop, then reconnect. This app will discover her latest secure phone link automatically.",
                        false
                    );
                    endpointLabel.setText(saved == null ? "No live endpoint discovered" : "Last server: " + displayHost(saved));
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
        showPortal("CHECKING", "Checking the server", "Verifying that this address is Alpecca.", true);
        endpointLabel.setText(displayHost(normalized));
        network.execute(() -> {
            boolean valid = probeExactAlpecca(serverOrigin(normalized));
            runOnUiThread(() -> {
                if (attempt != connectionAttempt) {
                    return;
                }
                if (valid) {
                    openServer(normalized);
                } else {
                    showPortal("OFFLINE", "That server did not answer", "The address did not return Alpecca's verified health identity.", false);
                    endpointLabel.setText(displayHost(normalized));
                }
            });
        });
    }

    private List<String> fetchDiscoveryCandidates() {
        List<String> result = new ArrayList<>();
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
            connection.setRequestProperty("User-Agent", "AlpeccaAndroid/2.0");
            if (connection.getResponseCode() != 200) {
                return result;
            }
            JSONObject payload = new JSONObject(readLimited(connection.getInputStream(), 16 * 1024));
            if (!"alpecca-mobile-discovery".equals(payload.optString("service")) || payload.optInt("version") != 1) {
                return result;
            }
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
                String normalized = normalizeServerUrl(row.optString("url"));
                if (normalized != null && !result.contains(normalized)) {
                    result.add(normalized);
                }
            }
        } catch (Exception ignored) {
            // The saved/manual endpoint fallback remains available.
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
        return result;
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
            connection.setRequestProperty("User-Agent", "AlpeccaAndroid/2.0");
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

    private void openServer(String value) {
        String normalized = normalizeServerUrl(value);
        if (normalized == null) {
            showConnectionFailure("The discovered server address was invalid.");
            return;
        }
        preferences.edit().putString(PREF_SERVER_URL, normalized).apply();
        serverField.setText(normalized);
        Uri house = Uri.parse(normalized).buildUpon()
            .clearQuery()
            .appendQueryParameter("embodiment", "vrm")
            .appendQueryParameter("view", "orthographic")
            .appendQueryParameter("client", "android")
            .build();
        showPortal("OPENING", "Opening House HQ", "The secure server is ready. Loading Alpecca's embodied space.", true);
        webView.loadUrl(house.toString());
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
        showPortal("OFFLINE", "Connection lost", message + " Reconnect after Alpecca is running.", false);
        String saved = preferences.getString(PREF_SERVER_URL, "");
        endpointLabel.setText(saved.isEmpty() ? "No server saved" : "Last server: " + displayHost(saved));
    }

    private void showSettings() {
        serverField.setText(preferences.getString(PREF_SERVER_URL, ""));
        settingsOverlay.setVisibility(View.VISIBLE);
    }

    private void hideSettings() {
        settingsOverlay.setVisibility(View.GONE);
    }

    private void openAndroidSettings() {
        Intent intent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
        intent.setData(Uri.parse("package:" + getPackageName()));
        startActivity(intent);
    }

    private void confirmClearSession() {
        new AlertDialog.Builder(this)
            .setTitle("Clear trusted session?")
            .setMessage("This removes the trusted-device cookie from this phone. The creator password will be required again.")
            .setPositiveButton("Clear", (dialog, which) -> {
                CookieManager.getInstance().removeAllCookies(null);
                CookieManager.getInstance().flush();
                WebStorage.getInstance().deleteAllData();
                preferences.edit().remove(PREF_MEDIA_ORIGIN).apply();
                webView.clearCache(true);
                hideSettings();
                discoverAndConnect();
            })
            .setNegativeButton("Cancel", null)
            .show();
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
    protected void onPause() {
        CookieManager.getInstance().flush();
        webView.onPause();
        super.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        webView.onResume();
    }

    @Override
    protected void onDestroy() {
        connectionAttempt++;
        network.shutdownNow();
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
