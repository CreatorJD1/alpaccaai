package ai.alpecca.launcher;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.PermissionRequest;
import android.webkit.SslErrorHandler;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceError;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

public final class MainActivity extends Activity {
    private static final String PREFS = "alpecca_launcher";
    private static final String PREF_SERVER_URL = "server_url";
    private static final String PREF_MEDIA_ORIGIN = "media_origin";
    private static final int REQUEST_WEB_PERMISSIONS = 4001;
    private static final int REQUEST_FILE = 4002;

    private static final int BG = Color.rgb(17, 19, 24);
    private static final int PANEL = Color.rgb(26, 30, 39);
    private static final int PANEL_HIGH = Color.rgb(39, 44, 57);
    private static final int TEXT = Color.rgb(241, 243, 248);
    private static final int MUTED = Color.rgb(164, 171, 186);
    private static final int TEAL = Color.rgb(112, 214, 194);

    private SharedPreferences preferences;
    private WebView webView;
    private TextView connectionStatus;
    private FrameLayout connectionPanel;
    private EditText serverField;
    private ValueCallback<Uri[]> fileCallback;
    private PermissionRequest pendingWebPermission;
    private String[] pendingWebResources = new String[0];
    private boolean pageFailed;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        preferences = getSharedPreferences(PREFS, MODE_PRIVATE);
        setContentView(buildInterface());
        configureWebView();

        String saved = preferences.getString(PREF_SERVER_URL, BuildConfig.DEFAULT_ALPECCA_URL);
        serverField.setText(saved == null ? "" : saved);
        if (saved == null || saved.trim().isEmpty()) {
            showConnectionPanel();
        } else {
            openServer(saved);
        }
    }

    private View buildInterface() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(BG);

        LinearLayout toolbar = new LinearLayout(this);
        toolbar.setGravity(Gravity.CENTER_VERTICAL);
        toolbar.setPadding(dp(16), dp(8), dp(10), dp(8));
        toolbar.setBackgroundColor(PANEL);

        TextView title = new TextView(this);
        title.setText("Alpecca");
        title.setTextColor(TEXT);
        title.setTextSize(20);
        title.setTypeface(title.getTypeface(), android.graphics.Typeface.BOLD);
        toolbar.addView(title, new LinearLayout.LayoutParams(0, dp(48), 1f));

        Button reload = toolbarButton("Reload");
        reload.setOnClickListener(view -> {
            if (webView.getUrl() == null) {
                showConnectionPanel();
            } else {
                webView.reload();
            }
        });
        toolbar.addView(reload);

        Button server = toolbarButton("Server");
        server.setOnClickListener(view -> showConnectionPanel());
        toolbar.addView(server);
        root.addView(toolbar, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(64)));

        connectionStatus = new TextView(this);
        connectionStatus.setText("Starting launcher");
        connectionStatus.setTextColor(MUTED);
        connectionStatus.setTextSize(12);
        connectionStatus.setGravity(Gravity.CENTER_VERTICAL);
        connectionStatus.setPadding(dp(16), 0, dp(16), 0);
        connectionStatus.setBackgroundColor(BG);
        root.addView(connectionStatus, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(30)));

        FrameLayout browserFrame = new FrameLayout(this);
        webView = new WebView(this);
        webView.setBackgroundColor(BG);
        browserFrame.addView(webView, matchParent());

        connectionPanel = buildConnectionPanel();
        browserFrame.addView(connectionPanel, matchParent());
        root.addView(browserFrame, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        return root;
    }

    private FrameLayout buildConnectionPanel() {
        FrameLayout overlay = new FrameLayout(this);
        overlay.setBackgroundColor(BG);

        LinearLayout form = new LinearLayout(this);
        form.setOrientation(LinearLayout.VERTICAL);
        form.setPadding(dp(24), dp(24), dp(24), dp(24));
        form.setBackgroundColor(PANEL);

        TextView heading = new TextView(this);
        heading.setText("Connect this phone");
        heading.setTextColor(TEXT);
        heading.setTextSize(22);
        heading.setTypeface(heading.getTypeface(), android.graphics.Typeface.BOLD);
        form.addView(heading);

        TextView help = new TextView(this);
        help.setText("Enter Alpecca's HTTPS tunnel or stable server address. This phone keeps its trusted session locally.");
        help.setTextColor(MUTED);
        help.setTextSize(14);
        help.setPadding(0, dp(8), 0, dp(18));
        form.addView(help);

        serverField = new EditText(this);
        serverField.setSingleLine(true);
        serverField.setHint("https://alpecca.example.com");
        serverField.setHintTextColor(MUTED);
        serverField.setTextColor(TEXT);
        serverField.setTextSize(15);
        serverField.setPadding(dp(12), dp(12), dp(12), dp(12));
        serverField.setBackgroundColor(PANEL_HIGH);
        form.addView(serverField, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(52)));

        Button connect = new Button(this);
        connect.setText("Open House HQ");
        connect.setTextColor(BG);
        connect.setTextSize(15);
        connect.setAllCaps(false);
        connect.setBackgroundColor(TEAL);
        connect.setOnClickListener(view -> openServer(serverField.getText().toString()));
        LinearLayout.LayoutParams connectParams = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(52));
        connectParams.topMargin = dp(14);
        form.addView(connect, connectParams);

        FrameLayout.LayoutParams formParams = new FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT
        );
        formParams.gravity = Gravity.CENTER;
        formParams.leftMargin = dp(18);
        formParams.rightMargin = dp(18);
        overlay.addView(form, formParams);
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
        settings.setUserAgentString(settings.getUserAgentString() + " AlpeccaAndroidLauncher/1.0");

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
                connectionStatus.setText("Connecting to Alpecca");
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                if (!pageFailed) {
                    connectionStatus.setText("Connected securely");
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
                connectionStatus.setText("TLS validation failed");
                Toast.makeText(MainActivity.this, "The server certificate could not be verified.", Toast.LENGTH_LONG).show();
            }
        });

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int progress) {
                if (progress < 100) {
                    connectionStatus.setText(String.format(Locale.US, "Loading House HQ - %d%%", progress));
                }
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

    private void openServer(String entered) {
        String normalized = normalizeServerUrl(entered);
        if (normalized == null) {
            serverField.setError("Use a valid HTTPS address.");
            showConnectionPanel();
            return;
        }
        preferences.edit().putString(PREF_SERVER_URL, normalized).apply();
        serverField.setText(normalized);
        connectionPanel.setVisibility(View.GONE);
        connectionStatus.setText("Connecting to Alpecca");
        webView.loadUrl(normalized);
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
        if (path == null || path.isEmpty() || "/".equals(path)) {
            uri = uri.buildUpon().path("/house-hq").build();
        }
        return uri.toString();
    }

    private boolean isConfiguredOrigin(Uri candidate) {
        if (candidate == null || !"https".equalsIgnoreCase(candidate.getScheme())) {
            return false;
        }
        String configured = preferences.getString(PREF_SERVER_URL, BuildConfig.DEFAULT_ALPECCA_URL);
        Uri expected = Uri.parse(configured == null ? "" : configured);
        int candidatePort = candidate.getPort() == -1 ? 443 : candidate.getPort();
        int expectedPort = expected.getPort() == -1 ? 443 : expected.getPort();
        return expected.getHost() != null
            && expected.getHost().equalsIgnoreCase(candidate.getHost())
            && candidatePort == expectedPort;
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

    private void showConnectionPanel() {
        String saved = preferences.getString(PREF_SERVER_URL, BuildConfig.DEFAULT_ALPECCA_URL);
        serverField.setText(saved == null ? "" : saved);
        connectionPanel.setVisibility(View.VISIBLE);
        serverField.requestFocus();
    }

    private void showConnectionFailure(String message) {
        pageFailed = true;
        connectionStatus.setText("Offline");
        Toast.makeText(this, message, Toast.LENGTH_LONG).show();
        showConnectionPanel();
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
        if (connectionPanel.getVisibility() == View.VISIBLE) {
            connectionPanel.setVisibility(View.GONE);
        } else if (webView.canGoBack()) {
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

    private Button toolbarButton(String label) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextColor(TEXT);
        button.setTextSize(12);
        button.setAllCaps(false);
        button.setBackgroundColor(PANEL_HIGH);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(dp(78), dp(42));
        params.leftMargin = dp(6);
        button.setLayoutParams(params);
        return button;
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
}
