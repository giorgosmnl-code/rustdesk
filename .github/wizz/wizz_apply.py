# ===== Wizz: zoom limit =====
p = 'flutter/lib/models/model.dart'
s = open(p).read()
def zrep(a, b):
    global s
    assert s.count(a) == 1, a
    s = s.replace(a, b)
# zoom-out stops when the remote screen fits the view (like AnyDesk)
zrep('return min(xscale, yscale) / 1.5;', 'return min(xscale, yscale);')
# keep the view inside the remote screen when panning
zrep('  panX(double dx) {\n    _x += dx;\n', '  panX(double dx) {\n    _x += dx;\n    if (isMobile) _wizzClampOffset();\n')
zrep('  panY(double dy) {\n    _y += dy;\n', '  panY(double dy) {\n    _y += dy;\n    if (isMobile) _wizzClampOffset();\n')
zrep('    _y = focalPoint.dy - adjust - (focalPoint.dy - _y - adjust) / s * _scale;\n',
    '    _y = focalPoint.dy - adjust - (focalPoint.dy - _y - adjust) / s * _scale;\n    _wizzClampOffset();\n')
# smaller than the view: centered left-right, stuck to the top; larger: no dragging past the edges
zrep('  // mobile only\n  updateScale(', '''  void _wizzClampOffset() {
    final vs = getSize();
    final dw = getDisplayWidth() * _scale;
    final dh = getDisplayHeight() * _scale;
    _x = dw > vs.width ? _x.clamp(vs.width - dw, 0.0).toDouble() : (vs.width - dw) / 2;
    _y = dh > vs.height ? _y.clamp(vs.height - dh, 0.0).toDouble() : 0.0;
  }

  // mobile only
  updateScale(''')
open(p, 'w').write(s)

# ===== Wizz: Ctrl+A (select all) next to Ctrl+C in the extra keys row =====
p = 'flutter/lib/mobile/pages/remote_page.dart'
s = open(p).read()
zrep("""      wrap(isMac ? 'Cmd+C' : 'Ctrl+C', () {
        sendPrompt(isMac, 'VK_C');
      }),""", """      wrap(isMac ? 'Cmd+A' : 'Ctrl+A', () {
        sendPrompt(isMac, 'VK_A');
      }),
      wrap(isMac ? 'Cmd+C' : 'Ctrl+C', () {
        sendPrompt(isMac, 'VK_C');
      }),""")
open(p, 'w').write(s)

# ===== Wizz: multi-session =====
import os, re, sys

if os.environ.get('WIZZ_MULTI', '1') != '1':
    print('multi-session skipped (WIZZ_MULTI != 1)')
    raise SystemExit(0)

WIZZ_SESSIONS_DART = r'''// Wizz: multiple remote sessions (up to kWizzMaxSessions) on mobile.
// Each session gets its own FFI; the first one reuses gFFI so that
// features which still use the global model (chat etc.) keep working there.
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:get/get.dart';
import 'package:provider/provider.dart';
import 'package:uuid/uuid.dart';

import '../../common.dart';
import '../../models/model.dart';
import '../../models/state_model.dart';
import 'remote_page.dart';

const int kWizzMaxSessions = 3;

class WizzSession {
  final String id;
  final FFI ffi;
  final String loginMethod;
  final String? password;
  final bool? isSharedPassword;
  final bool? forceRelay;
  final Key key = UniqueKey();

  WizzSession(this.id, this.ffi,
      {this.loginMethod = '',
      this.password,
      this.isSharedPassword,
      this.forceRelay});

  String get title {
    final pi = ffi.ffiModel.pi;
    if (pi.hostname.isNotEmpty) return pi.hostname;
    return id;
  }
}

class WizzSessions {
  WizzSessions._();
  static final WizzSessions to = WizzSessions._();

  final RxList<WizzSession> sessions = <WizzSession>[].obs;
  final RxInt current = 0.obs;
  bool hostMounted = false;

  bool get isMulti => hostMounted && sessions.length > 1;

  // Extra FFIs are reused (each one owns timers that never stop), but only a
  // few seconds after their last session closed, so an old close() can't wipe
  // a new session that starts on the same FFI.
  final List<FFI> _pool = [];
  final Map<FFI, DateTime> _freedAt = {};

  bool _usable(FFI f) {
    if (sessions.any((s) => identical(s.ffi, f))) return false;
    // First session of a fresh remote screen: reuse gFFI right away like the
    // original app does.
    if (identical(f, gFFI) && sessions.isEmpty) return true;
    final t = _freedAt[f];
    return t == null || DateTime.now().difference(t).inSeconds >= 5;
  }

  FFI _allocFfi() {
    for (final f in [gFFI, ..._pool]) {
      if (_usable(f)) return f;
    }
    final f = FFI(Uuid().v4obj());
    _pool.add(f);
    return f;
  }

  void _markFreed(WizzSession s) => _freedAt[s.ffi] = DateTime.now();

  /// Adds a session (or switches to it if already open). Returns false if full.
  bool add(String id,
      {String loginMethod = '',
      String? password,
      bool? isSharedPassword,
      bool? forceRelay}) {
    final existing = sessions.indexWhere((s) => s.id == id);
    if (existing >= 0) {
      current.value = existing;
      return true;
    }
    if (sessions.length >= kWizzMaxSessions) {
      showToast('Maximum $kWizzMaxSessions PCs open. Close one first.');
      return false;
    }
    sessions.add(WizzSession(id, _allocFfi(),
        loginMethod: loginMethod,
        password: password,
        isSharedPassword: isSharedPassword,
        forceRelay: forceRelay));
    current.value = sessions.length - 1;
    return true;
  }

  void switchTo(int i) {
    if (i >= 0 && i < sessions.length) current.value = i;
  }

  int indexOfSessionId(SessionID? sessionId) {
    if (sessionId == null) return -1;
    return sessions.indexWhere((s) => s.ffi.sessionId == sessionId);
  }

  /// Closes one session. The last one closes the whole remote screen.
  void closeAt(int i) {
    if (i < 0 || i >= sessions.length) return;
    if (sessions.length == 1) {
      wizzPopToHome();
      return;
    }
    final cur = current.value;
    _markFreed(sessions[i]);
    sessions.removeAt(i);
    if (i < cur) {
      current.value = cur - 1;
    } else if (cur >= sessions.length) {
      current.value = sessions.length - 1;
    } else {
      current.refresh();
    }
  }

  void clear() {
    for (final s in sessions) {
      _markFreed(s);
    }
    sessions.clear();
    current.value = 0;
  }
}

/// Original mobile behaviour of closeConnection(): back to the home page.
void wizzPopToHome() {
  () async {
    await SystemChrome.setEnabledSystemUIMode(SystemUiMode.manual,
        overlays: SystemUiOverlay.values);
    gFFI.chatModel.hideChatOverlay();
    Navigator.popUntil(globalKey.currentContext!, ModalRoute.withName("/"));
    stateGlobal.isInMainPage = true;
  }();
}

/// Called from closeConnection() on mobile. Returns true if it closed just
/// one of several open sessions (so the remote screen must stay open).
bool wizzCloseSession({String? id, SessionID? sessionId}) {
  final m = WizzSessions.to;
  if (!m.isMulti) return false;
  var i = m.indexOfSessionId(sessionId);
  if (i < 0 && id != null) i = m.sessions.indexWhere((s) => s.id == id);
  if (i < 0) i = m.current.value;
  m.closeAt(i);
  return true;
}

/// Replaces the mobile `Navigator.push(RemotePage)` in connect().
void wizzConnectMobile(BuildContext context, String id,
    {String loginMethod = '',
    String? password,
    bool? isSharedPassword,
    bool? forceRelay}) {
  final m = WizzSessions.to;
  if (m.hostMounted) {
    m.add(id,
        loginMethod: loginMethod,
        password: password,
        isSharedPassword: isSharedPassword,
        forceRelay: forceRelay);
    return;
  }
  m.clear();
  m.add(id,
      loginMethod: loginMethod,
      password: password,
      isSharedPassword: isSharedPassword,
      forceRelay: forceRelay);
  Navigator.push(
    context,
    MaterialPageRoute(builder: (BuildContext context) => WizzRemoteHost()),
  );
}

class WizzRemoteHost extends StatefulWidget {
  WizzRemoteHost({Key? key}) : super(key: key);

  @override
  State<WizzRemoteHost> createState() => _WizzRemoteHostState();
}

class _WizzRemoteHostState extends State<WizzRemoteHost> {
  final m = WizzSessions.to;

  @override
  void initState() {
    super.initState();
    m.hostMounted = true;
  }

  @override
  void dispose() {
    m.hostMounted = false;
    m.clear();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Obx(() {
      final list = m.sessions.toList();
      final cur = m.current.value.clamp(0, list.isEmpty ? 0 : list.length - 1);
      if (list.isEmpty) {
        return Container(color: Colors.black);
      }
      return IndexedStack(
        index: cur,
        children: [
          for (var i = 0; i < list.length; i++)
            MultiProvider(
              key: list[i].key,
              providers: [
                ChangeNotifierProvider.value(value: list[i].ffi.ffiModel),
                ChangeNotifierProvider.value(value: list[i].ffi.imageModel),
                ChangeNotifierProvider.value(value: list[i].ffi.cursorModel),
                ChangeNotifierProvider.value(value: list[i].ffi.canvasModel),
              ],
              child: RemotePage(
                id: list[i].id,
                ffi: list[i].ffi,
                active: i == cur,
                loginMethod: list[i].loginMethod,
                password: list[i].password,
                isSharedPassword: list[i].isSharedPassword,
                forceRelay: list[i].forceRelay,
              ),
            ),
        ],
      );
    });
  }
}

/// Toolbar icon: stacked screens with the number of open sessions.
Widget wizzSessionsIcon() {
  return Obx(() {
    final n = WizzSessions.to.sessions.length;
    final icon = Icon(Icons.filter_none, color: Colors.white);
    if (n <= 1) return icon;
    return Badge(label: Text('$n'), child: icon);
  });
}

void showWizzSessionsMenu(BuildContext context) {
  final m = WizzSessions.to;
  showModalBottomSheet(
    context: context,
    builder: (ctx) => SafeArea(
      child: Obx(() {
        final list = m.sessions.toList();
        final cur = m.current.value;
        return Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 4),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text('Open PCs (${list.length}/$kWizzMaxSessions)',
                    style: const TextStyle(fontWeight: FontWeight.bold)),
              ),
            ),
            for (var i = 0; i < list.length; i++)
              ListTile(
                leading: Icon(i == cur
                    ? Icons.radio_button_checked
                    : Icons.desktop_windows_outlined),
                title: Text(list[i].title),
                subtitle: list[i].title != list[i].id ? Text(list[i].id) : null,
                selected: i == cur,
                onTap: () {
                  Navigator.pop(ctx);
                  m.switchTo(i);
                },
                trailing: IconButton(
                  icon: const Icon(Icons.close),
                  tooltip: 'Disconnect',
                  onPressed: () {
                    Navigator.pop(ctx);
                    m.closeAt(i);
                  },
                ),
              ),
            if (list.length < kWizzMaxSessions)
              ListTile(
                leading: const Icon(Icons.add),
                title: const Text('Connect another PC'),
                onTap: () {
                  Navigator.pop(ctx);
                  showWizzConnectDialog(context);
                },
              )
            else
              const ListTile(
                enabled: false,
                leading: Icon(Icons.block),
                title: Text('Maximum $kWizzMaxSessions PCs open'),
              ),
          ],
        );
      }),
    ),
  );
}

void showWizzConnectDialog(BuildContext context) {
  final m = WizzSessions.to;
  final ctrl = TextEditingController();
  final open = m.sessions.map((s) => s.id).toSet();
  final recent = gFFI.recentPeersModel.peers
      .map((p) => p.id)
      .where((id) => !open.contains(id))
      .take(6)
      .toList();
  // The remote page turns the Android soft keyboard off; we need it here.
  gFFI.invokeMethod("enable_soft_keyboard", true);
  var started = false;
  showDialog(
    context: context,
    builder: (ctx) {
      void go(String raw) {
        final id = raw.replaceAll(' ', '').trim();
        if (id.isEmpty) return;
        started = true;
        Navigator.pop(ctx);
        connect(context, id);
      }

      return AlertDialog(
        title: const Text('Connect another PC'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              controller: ctrl,
              autofocus: true,
              decoration: const InputDecoration(hintText: 'Remote ID'),
              textInputAction: TextInputAction.go,
              onSubmitted: go,
            ),
            if (recent.isNotEmpty) const SizedBox(height: 12),
            if (recent.isNotEmpty)
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  for (final id in recent)
                    ActionChip(label: Text(id), onPressed: () => go(id)),
                ],
              ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () => go(ctrl.text),
            child: const Text('Connect'),
          ),
        ],
      );
    },
  ).then((_) {
    if (!started) gFFI.invokeMethod("enable_soft_keyboard", false);
  });
}
'''


def load(p):
    return open(p).read()


def save(p, s):
    open(p, 'w').write(s)


def rep(s, a, b, count=1):
    n = s.count(a)
    assert n == count, f'expected {count}x, found {n}x: {a[:120]!r}'
    return s.replace(a, b)


def slice_replace(s, start_marker, end_marker, old, new):
    i = s.index(start_marker)
    j = s.index(end_marker, i)
    return s[:i] + s[i:j].replace(old, new) + s[j:]


# ---------------------------------------------------------------- remote_page
p = 'flutter/lib/mobile/pages/remote_page.dart'
s = load(p)

s = rep(s, "import '../widgets/custom_scale_widget.dart';\n",
        "import '../widgets/custom_scale_widget.dart';\nimport 'wizz_sessions.dart';\n")

# widget: optional per-session FFI + active flag
s = rep(s, """      this.isSharedPassword,
      this.forceRelay})
      : super(key: key);

  final String id;""", """      this.isSharedPassword,
      this.forceRelay,
      this.ffi,
      this.active = true})
      : super(key: key);

  final FFI? ffi;
  final bool active;
  final String id;""")
s = rep(s, "State<RemotePage> createState() => _RemotePageState(id);",
        "State<RemotePage> createState() => _RemotePageState(id, ffi ?? gFFI);")
s = rep(s, "  _RemotePageState(String id) {\n",
        "  final FFI _ffi;\n\n  _RemotePageState(String id, this._ffi) {\n")

# every gFFI inside the page state -> this session's FFI
s = slice_replace(s, 'class _RemotePageState', 'class KeyHelpTools', 'gFFI', '_ffi')

# only the visible session owns the back button
s = rep(s, """      onWillPop: () async {
        clientClose(sessionId, _ffi);
        return false;
      },""", """      onWillPop: widget.active
          ? () async {
              clientClose(sessionId, _ffi);
              return false;
            }
          : null,""")

# hidden sessions must not show global overlays
s = rep(s, """                          _ffi.ffiModel.tryShowAndroidActionsOverlay();
                          return Offstage();""", """                          if (widget.active) {
                            _ffi.ffiModel.tryShowAndroidActionsOverlay();
                          }
                          return Offstage();""")
s = rep(s, """                                  _ffi.dialogManager
                                      .resetMobileActionsOverlay(ffi: _ffi);""", """                                  if (widget.active) {
                                    _ffi.dialogManager
                                        .resetMobileActionsOverlay(ffi: _ffi);
                                  }""")
s = rep(s, "  void onSoftKeyboardChanged(bool visible) {\n",
        "  void onSoftKeyboardChanged(bool visible) {\n    if (!widget.active) return;\n")

# switching sessions
s = rep(s, "  @override\n  Future<void> dispose() async {\n", """  @override
  void didUpdateWidget(covariant RemotePage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.active == widget.active) return;
    if (widget.active) {
      _ffi.ffiModel.updateEventListener(sessionId, widget.id);
      _physicalFocusNode.requestFocus();
      _ffi.canvasModel.updateViewStyle();
      // copy on one PC, switch, paste on the other
      _ffi.invokeMethod("wizz_force_sync_clipboard");
    } else {
      _showEdit = false;
      _mobileFocusNode.unfocus();
      _physicalFocusNode.unfocus();
      _ffi.dialogManager.hideMobileActionsOverlay(store: false);
    }
  }

  @override
  Future<void> dispose() async {
""")

# toolbar: options menu uses this session, plus the new sessions button
s = rep(s, """                        showOptions(context, widget.id, _ffi.dialogManager);
                      },
                    )
                  ] +""", """                        showOptions(context, widget.id, _ffi.dialogManager,
                            ffiOverride: _ffi);
                      },
                    ),
                    IconButton(
                      color: Colors.white,
                      icon: wizzSessionsIcon(),
                      onPressed: () {
                        setState(() => _showEdit = false);
                        showWizzSessionsMenu(context);
                      },
                    ),
                  ] +""")

# chat still uses the global chat model: only offer it on the gFFI session
s = rep(s, """                  (isWeb
                      ? []
                      : <Widget>[
                          futureBuilder(""", """                  (isWeb || !identical(_ffi, gFFI)
                      ? []
                      : <Widget>[
                          futureBuilder(""")

# KeyHelpTools gets the session FFI
s = rep(s, "              return KeyHelpTools(\n", "              return KeyHelpTools(\n                  ffi: _ffi,\n")
s = rep(s, """  KeyHelpTools(
      {required this.keyboardIsVisible, required this.showGestureHelp});""", """  final FFI? ffi;

  KeyHelpTools(
      {required this.keyboardIsVisible,
      required this.showGestureHelp,
      this.ffi});""")
s = rep(s, "class _KeyHelpToolsState extends State<KeyHelpTools> {\n",
        "class _KeyHelpToolsState extends State<KeyHelpTools> {\n  FFI get _ffi => widget.ffi ?? gFFI;\n")
s = slice_replace(s, 'class _KeyHelpToolsState', 'class ImagePaint', 'gFFI', '_ffi')
s = slice_replace(s, 'class _KeyHelpToolsState', 'class ImagePaint', "sendPrompt(isMac, '", "sendPrompt(isMac, ffi: _ffi, '")
# the getter line itself must keep gFFI as the fallback
s = rep(s, "  FFI get _ffi => widget.ffi ?? _ffi;\n", "  FFI get _ffi => widget.ffi ?? gFFI;\n")

# showOptions / sendPrompt take an optional FFI
s = rep(s, """void showOptions(
    BuildContext context, String id, OverlayDialogManager dialogManager) async {
""", """void showOptions(
    BuildContext context, String id, OverlayDialogManager dialogManager,
    {FFI? ffiOverride}) async {
  final wffi = ffiOverride ?? gFFI;
""")
s = slice_replace(s, 'void showOptions(', 'TTextMenu? getVirtualDisplayMenu', 'gFFI', 'wffi')
s = rep(s, "  final wffi = ffiOverride ?? wffi;\n", "  final wffi = ffiOverride ?? gFFI;\n")
s = rep(s, "void sendPrompt(bool isMac, String key) {\n",
        "void sendPrompt(bool isMac, String key, {FFI? ffi}) {\n  final wffi = ffi ?? gFFI;\n")
s = slice_replace(s, 'void sendPrompt(', 'class FABLocation', 'gFFI', 'wffi')
s = rep(s, "  final wffi = ffi ?? wffi;\n", "  final wffi = ffi ?? gFFI;\n")
save(p, s)

# ------------------------------------------- clipboard only on the visible PC
p = 'flutter/lib/mobile/pages/remote_page.dart'
s = load(p)
# returning to the app: only the visible PC checks the phone clipboard
s = rep(s, """    if (state == AppLifecycleState.resumed) {
      trySyncClipboard();""", """    if (state == AppLifecycleState.resumed) {
      if (!widget.active) return;
      trySyncClipboard();""")
# background PCs get their clipboard switched off, the visible one back on.
# A local flag remembers which PCs Wizz switched off, so a manual
# "Disable clipboard" stays as the user set it and a crash is undone next time.
s = rep(s, """  @override
  void didUpdateWidget(covariant RemotePage oldWidget) {""", """  String get _wizzClipKey => 'wizz-clipoff-${widget.id}';

  Future<void> _wizzSetClipboard(bool on) async {
    final off = bind.sessionGetToggleOptionSync(
        sessionId: sessionId, arg: 'disable-clipboard');
    if (on) {
      if (off && bind.mainGetLocalOption(key: _wizzClipKey) == 'Y') {
        await bind.sessionToggleOption(
            sessionId: sessionId, value: 'disable-clipboard');
      }
      await bind.mainSetLocalOption(key: _wizzClipKey, value: '');
    } else if (!off) {
      await bind.mainSetLocalOption(key: _wizzClipKey, value: 'Y');
      await bind.sessionToggleOption(
          sessionId: sessionId, value: 'disable-clipboard');
    }
  }

  @override
  void didUpdateWidget(covariant RemotePage oldWidget) {""")
s = rep(s, """      // copy on one PC, switch, paste on the other
      _ffi.invokeMethod("wizz_force_sync_clipboard");""", """      // copy on one PC, switch, paste on the other
      () async {
        await _wizzSetClipboard(true);
        await Future.delayed(const Duration(milliseconds: 300));
        if (mounted && widget.active) {
          _ffi.invokeMethod("wizz_force_sync_clipboard");
        }
      }();""")
s = rep(s, """      _ffi.dialogManager.hideMobileActionsOverlay(store: false);
    }
  }""", """      _ffi.dialogManager.hideMobileActionsOverlay(store: false);
      _wizzSetClipboard(false);
    }
  }""")
# a new connection undoes a switch-off left over from before
s = rep(s, """      forceRelay: widget.forceRelay,
    );
    WidgetsBinding.instance.addPostFrameCallback((_) {""", """      forceRelay: widget.forceRelay,
    );
    _wizzSetClipboard(true);
    WidgetsBinding.instance.addPostFrameCallback((_) {""")
# bottom bar: with the extra sessions button the icons no longer fit on
# narrow phones, so the left group shrinks a little instead of being cut off
s = rep(s, """        children: <Widget>[
          Row(
              children: <Widget>[
                    IconButton(
                      color: Colors.white,
                      icon: Icon(Icons.clear),""", """        children: <Widget>[
          Expanded(
            child: FittedBox(
              fit: BoxFit.scaleDown,
              alignment: Alignment.centerLeft,
              child: Row(
              children: <Widget>[
                    IconButton(
                      color: Colors.white,
                      icon: Icon(Icons.clear),""")
s = rep(s, """                  ]),
          Obx(() => IconButton(
                color: Colors.white,
                icon: Icon(Icons.expand_more),""", """                  ]),
            ),
          ),
          Obx(() => IconButton(
                color: Colors.white,
                icon: Icon(Icons.expand_more),""")
save(p, s)

# ----------------------------------------------------------------- common.dart
p = 'flutter/lib/common.dart'
s = load(p)
s = rep(s, "import 'mobile/pages/remote_page.dart';\n",
        "import 'mobile/pages/remote_page.dart';\nimport 'mobile/pages/wizz_sessions.dart';\n")
s = rep(s, """closeConnection({String? id}) {
  if (isAndroid || isIOS) {
""", """closeConnection({String? id, SessionID? sessionId}) {
  if (isAndroid || isIOS) {
    if (wizzCloseSession(id: id, sessionId: sessionId)) return;
""")
# msgBox knows which session it belongs to
s = rep(s, """      dialogManager.dismissAll();
      closeConnection();
    }

    void continueSession() {""", """      dialogManager.dismissAll();
      closeConnection(sessionId: sessionId);
    }

    void continueSession() {""")
s = rep(s, """      if (!type.contains("custom") && desktopType != DesktopType.portForward) {
        closeConnection();
      }""", """      if (!type.contains("custom") && desktopType != DesktopType.portForward) {
        closeConnection(sessionId: sessionId);
      }""")
# mobile connect goes through the session manager
s = rep(s, """        Navigator.push(
          context,
          MaterialPageRoute(
            builder: (BuildContext context) => RemotePage(
                id: id,
                loginMethod: loginMethod,
                password: password,
                isSharedPassword: isSharedPassword,
                forceRelay: forceRelay),
          ),
        );""", """        wizzConnectMobile(context, id,
            loginMethod: loginMethod,
            password: password,
            isSharedPassword: isSharedPassword,
            forceRelay: forceRelay);""")
save(p, s)

# --------------------------------------------------------------- model.dart
# FfiModel dialogs: close the session they belong to
p = 'flutter/lib/models/model.dart'
s = load(p)
s = rep(s, """    dialogManager.show(tag: '$sessionId-$type', (setState, close, context) {
      onClose() {
        closeConnection();
        close();
      }""", """    dialogManager.show(tag: '$sessionId-$type', (setState, close, context) {
      onClose() {
        closeConnection(sessionId: sessionId);
        close();
      }""")
s = rep(s, """      SessionID sessionId, String type, String title, String text) {
    onClose() {
      closeConnection();
    }""", """      SessionID sessionId, String type, String title, String text) {
    onClose() {
      closeConnection(sessionId: sessionId);
    }""")
save(p, s)

# ------------------------------------------------- clipboard between sessions
p = 'flutter/android/app/src/main/kotlin/com/carriez/flutter_hbb/RdClipboardManager.kt'
s = load(p)
s = rep(s, "    fun syncClipboard(isClient: Boolean) {\n",
        "    // Wizz: send the phone clipboard to the PCs even if it came from a PC\n"
        "    fun wizzForceSyncClient() {\n"
        "        lastUpdatedClipData = null\n"
        "        syncClipboard(true)\n"
        "    }\n\n"
        "    fun syncClipboard(isClient: Boolean) {\n")
save(p, s)
p = 'flutter/android/app/src/main/kotlin/com/carriez/flutter_hbb/MainActivity.kt'
s = load(p)
s = rep(s, '                "try_sync_clipboard" -> {\n',
        '                "wizz_force_sync_clipboard" -> {\n'
        '                    rdClipboardManager?.wizzForceSyncClient()\n'
        '                    result.success(true)\n'
        '                }\n'
        '                "try_sync_clipboard" -> {\n')
save(p, s)

# ---------------------------------------------------------- new session file
if WIZZ_SESSIONS_DART is not None:
    save('flutter/lib/mobile/pages/wizz_sessions.dart', WIZZ_SESSIONS_DART)

print('wizz multi-session patch applied')
