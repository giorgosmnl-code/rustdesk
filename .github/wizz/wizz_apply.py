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

WIZZ_SESSIONS_DART = r'''// Wizz: multiple remote sessions on mobile (no limit).
// Each session gets its own FFI; the first one reuses gFFI so that
// features which still use the global model (chat etc.) keep working there.
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:get/get.dart';
import 'package:provider/provider.dart';
import 'package:uuid/uuid.dart';

import '../../common.dart';
import '../../models/model.dart';
import '../../models/platform_model.dart';
import '../../models/state_model.dart';
import 'remote_page.dart';


class WizzSession {
  final String id;
  final FFI ffi;
  final String loginMethod;
  final String? password;
  final bool? isSharedPassword;
  final bool? forceRelay;
  final Key key = UniqueKey();
  // the connection dropped while this PC was not on screen
  final RxBool dropped = false.obs;

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

/// Error boxes of PCs that are not on screen: mark the PC as dropped instead of
/// showing the box over the visible PC. Returns true if the box was handled.
bool wizzOnMsgBox(SessionID sessionId, String type, String title) {
  final m = WizzSessions.to;
  if (!m.hostMounted) return false;
  final i = m.indexOfSessionId(sessionId);
  if (i < 0) return false;
  if (!type.contains('error')) return false;
  m.sessions[i].dropped.value = true;
  return i != m.current.value;
}

/// Switching to a PC whose connection dropped: reconnect it. Returns true if so.
bool wizzReconnectIfDropped(SessionID sessionId) {
  final m = WizzSessions.to;
  final i = m.indexOfSessionId(sessionId);
  if (i < 0 || !m.sessions[i].dropped.value) return false;
  final s = m.sessions[i];
  s.dropped.value = false;
  s.ffi.ffiModel.reconnect(s.ffi.dialogManager, s.ffi.sessionId, false);
  return true;
}

// ---- files from the phone (picker or Android share menu) -> paste on a PC
List<String> _wizzPendingPhoneFiles = [];

void wizzSendPhoneFiles(List<String> paths) {
  if (paths.isEmpty) return;
  _wizzPendingPhoneFiles = paths;
  wizzFlushPhoneFiles();
}

/// Hands waiting phone files to the visible PC (they are pasted with Ctrl+V).
void wizzFlushPhoneFiles() {
  final m = WizzSessions.to;
  if (_wizzPendingPhoneFiles.isEmpty || !m.hostMounted || m.sessions.isEmpty) {
    return;
  }
  final s = m.sessions[m.current.value.clamp(0, m.sessions.length - 1)];
  final sid = s.ffi.sessionId;
  final n = bind.sessionGetCommonSync(
          sessionId: sid,
          key: 'wizz-clip-phone-files',
          param: _wizzPendingPhoneFiles.join('\n')) ??
      '0';
  _wizzPendingPhoneFiles = [];
  if (n == '0' || n.isEmpty) {
    showToast('Could not read those files');
    return;
  }
  final code =
      bind.sessionGetCommonSync(sessionId: sid, key: 'wizz-clip-offer', param: '') ??
          '0';
  showToast(code == '1'
      ? 'Phone files ready: press Ctrl+V on this PC'
      : 'Phone files ready: paste on a PC with Ctrl+V');
}

Future<void> wizzPickPhoneFiles() async {
  final r = await gFFI.invokeMethodWithResult<List<dynamic>>('wizz_pick_files');
  wizzSendPhoneFiles((r ?? []).map((e) => e.toString()).toList());
}

/// Files shared to the app from another app (Gallery, Files...).
Future<void> wizzTakeSharedFiles() async {
  final r = await gFFI.invokeMethodWithResult<List<dynamic>>('wizz_take_shared');
  wizzSendPhoneFiles((r ?? []).map((e) => e.toString()).toList());
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
  // counts as open right away, so the next PC of a multi-connect joins it
  m.hostMounted = true;
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

  Worker? _keepAlive;

  @override
  void initState() {
    super.initState();
    m.hostMounted = true;
    // Android keeps the network of an app with a foreground notification, so
    // the PCs stay connected while another app is open.
    gFFI.invokeMethod("wizz_keepalive", m.sessions.length);
    _keepAlive = ever(m.sessions, (List<WizzSession> l) {
      gFFI.invokeMethod("wizz_keepalive", l.length);
    });
  }

  @override
  void dispose() {
    _keepAlive?.dispose();
    gFFI.invokeMethod("wizz_keepalive", 0);
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
                child: Text('Open PCs (${list.length})',
                    style: const TextStyle(fontWeight: FontWeight.bold)),
              ),
            ),
            Flexible(
              child: ListView(
                shrinkWrap: true,
                children: [
            for (var i = 0; i < list.length; i++)
              ListTile(
                leading: list[i].dropped.value
                    ? const Icon(Icons.link_off, color: Colors.red)
                    : Icon(i == cur
                        ? Icons.radio_button_checked
                        : Icons.desktop_windows_outlined),
                title: Text(list[i].title),
                subtitle: list[i].dropped.value
                    ? const Text('Disconnected · tap to reconnect',
                        style: TextStyle(color: Colors.red))
                    : (list[i].title != list[i].id ? Text(list[i].id) : null),
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
                ],
              ),
            ),
            ListTile(
              leading: const Icon(Icons.upload_file),
              title: const Text('Send files from phone'),
              subtitle: const Text('Then paste on the PC with Ctrl+V'),
              onTap: () {
                Navigator.pop(ctx);
                wizzPickPhoneFiles();
              },
            ),
            ListTile(
              leading: const Icon(Icons.add),
              title: const Text('Connect more PCs'),
              onTap: () {
                Navigator.pop(ctx);
                showWizzConnectDialog(context);
              },
            ),
          ],
        );
      }),
    ),
  );
}

/// Connects several PCs one after another; the first one picked is shown.
Future<void> wizzConnectMany(BuildContext context, List<String> ids) async {
  final m = WizzSessions.to;
  final todo = <String>[];
  for (final id in ids) {
    if (id.isNotEmpty && !todo.contains(id)) todo.add(id);
  }
  if (todo.isEmpty) return;
  for (final id in todo) {
    await connect(context, id);
  }
  final first = m.sessions.indexWhere((s) => s.id == todo.first);
  if (first >= 0) m.switchTo(first);
}

/// Pick one or more PCs: tap recent ones to select them and/or type IDs
/// (several IDs separated by commas).
void showWizzConnectDialog(BuildContext context) {
  final m = WizzSessions.to;
  final inRemote = m.hostMounted;
  final ctrl = TextEditingController();
  final open = inRemote ? m.sessions.map((s) => s.id).toSet() : <String>{};
  final recent = gFFI.recentPeersModel.peers
      .map((p) => p.id)
      .where((id) => !open.contains(id))
      .take(8)
      .toList();
  final picked = <String>[];
  // The remote page turns the Android soft keyboard off; we need it here.
  if (inRemote) gFFI.invokeMethod("enable_soft_keyboard", true);
  var started = false;
  List<String> typed() => ctrl.text
      .split(RegExp(r'[,;\n]'))
      .map((e) => e.replaceAll(' ', '').trim())
      .where((e) => e.isNotEmpty)
      .toList();
  showDialog(
    context: context,
    builder: (ctx) => StatefulBuilder(builder: (ctx, setState) {
      final all = <String>[...picked];
      for (final id in typed()) {
        if (!all.contains(id)) all.add(id);
      }
      void go() {
        if (all.isEmpty) return;
        started = true;
        Navigator.pop(ctx);
        wizzConnectMany(context, all);
      }

      return AlertDialog(
        title: Text(inRemote ? 'Connect more PCs' : 'Connect several PCs'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              controller: ctrl,
              autofocus: recent.isEmpty,
              decoration: const InputDecoration(
                  hintText: 'Remote ID (several: 123, 456)'),
              textInputAction: TextInputAction.go,
              onChanged: (_) => setState(() {}),
              onSubmitted: (_) => go(),
            ),
            if (recent.isNotEmpty) const SizedBox(height: 12),
            if (recent.isNotEmpty)
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  for (final id in recent)
                    FilterChip(
                      label: Text(id),
                      selected: picked.contains(id),
                      onSelected: (on) => setState(() {
                        if (on) {
                          picked.add(id);
                        } else {
                          picked.remove(id);
                        }
                      }),
                    ),
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
            onPressed: all.isEmpty ? null : go,
            child: Text(all.length > 1 ? 'Connect ${all.length}' : 'Connect'),
          ),
        ],
      );
    }),
  ).then((_) {
    if (inRemote && !started) {
      gFFI.invokeMethod("enable_soft_keyboard", false);
    }
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
      sessionRefreshVideo(sessionId, _ffi.ffiModel.pi);
      trySyncClipboard();
      wizzTakeSharedFiles();""")
# background PCs get their clipboard switched off, the visible one back on.
# A local flag remembers which PCs Wizz switched off, so a manual
# "Disable clipboard" stays as the user set it and a crash is undone next time.
s = rep(s, """  @override
  void didUpdateWidget(covariant RemotePage oldWidget) {""", """  // Background PCs: clipboard off, sound off and 1 frame per second; the
  // visible PC gets everything back. Local flags remember what Wizz changed,
  // so the user's own settings stay and a crash is undone on the next connect.
  String _wizzKey(String what) => 'wizz-bg-$what-${widget.id}';

  Future<void> _wizzSetOff(String option, bool off) async {
    final key = _wizzKey(option);
    final isOff =
        bind.sessionGetToggleOptionSync(sessionId: sessionId, arg: option);
    if (off) {
      if (!isOff) {
        await bind.mainSetLocalOption(key: key, value: 'Y');
        await bind.sessionToggleOption(sessionId: sessionId, value: option);
      }
    } else {
      if (isOff && bind.mainGetLocalOption(key: key) == 'Y') {
        await bind.sessionToggleOption(sessionId: sessionId, value: option);
      }
      await bind.mainSetLocalOption(key: key, value: '');
    }
  }

  // calls run one after another so quick switches can't mix up the flags
  Future<void> _wizzBgQueue = Future.value();
  Future<void> _wizzBackground(bool bg) {
    _wizzBgQueue = _wizzBgQueue
        .then((_) => _wizzSetBackground(bg))
        .catchError((e) => debugPrint('wizz background: $e'));
    return _wizzBgQueue;
  }

  Future<void> _wizzSetBackground(bool bg) async {
    await _wizzSetOff('disable-clipboard', bg);
    await _wizzSetOff('disable-audio', bg);
    final fpsKey = _wizzKey('fps');
    final saved = bind.mainGetLocalOption(key: fpsKey);
    if (bg) {
      if (saved.isEmpty) {
        final cur =
            await bind.sessionGetOption(sessionId: sessionId, arg: 'custom-fps');
        await bind.mainSetLocalOption(
            key: fpsKey, value: (cur == null || cur.isEmpty) ? '30' : cur);
      }
      await bind.sessionSetCustomFps(sessionId: sessionId, fps: 1);
    } else if (saved.isNotEmpty) {
      await bind.sessionSetCustomFps(
          sessionId: sessionId, fps: int.tryParse(saved) ?? 30);
      await bind.mainSetLocalOption(key: fpsKey, value: '');
    }
  }

  @override
  void didUpdateWidget(covariant RemotePage oldWidget) {""")
s = rep(s, """      // copy on one PC, switch, paste on the other
      _ffi.invokeMethod("wizz_force_sync_clipboard");""", """      // copy on one PC, switch, paste on the other
      if (wizzReconnectIfDropped(sessionId)) {
        return;
      }
      () async {
        await wizzTakeSharedFiles();
        await _wizzBackground(false);
        // fresh picture right away instead of the last 1 fps frame
        sessionRefreshVideo(sessionId, _ffi.ffiModel.pi);
        await Future.delayed(const Duration(milliseconds: 300));
        if (mounted && widget.active) {
          _ffi.invokeMethod("wizz_force_sync_clipboard");
        }
      }();""")
s = rep(s, """      _ffi.dialogManager.hideMobileActionsOverlay(store: false);
    }
  }""", """      _ffi.dialogManager.hideMobileActionsOverlay(store: false);
      _wizzBackground(true);
    }
  }""")
# a new connection undoes a switch-off left over from before
s = rep(s, """      forceRelay: widget.forceRelay,
    );
    WidgetsBinding.instance.addPostFrameCallback((_) {""", """      forceRelay: widget.forceRelay,
    );
    _wizzBackground(false);
    // a PC opened in the background (multi-connect) only gets the settings
    // once it is connected, so apply them again on its first picture
    _ffi.imageModel.addCallbackOnFirstImage((_) {
      if (mounted && !widget.active) _wizzBackground(true);
    });
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

# ------------------------------------------------ connect several PCs at once
p = 'flutter/lib/mobile/pages/remote_page.dart'
s = load(p)
s = rep(s, ".showLoading(translate('Connecting...'), onCancel: closeConnection);",
        ".showLoading(translate('Connecting...'),\n              onCancel: () => closeConnection(sessionId: sessionId));")
save(p, s)
# file copy & paste: banner on the visible PC, files offered to the next PC
p = 'flutter/lib/mobile/pages/remote_page.dart'
s = load(p)
s = rep(s, "import 'dart:async';\n",
        "import 'dart:async';\nimport 'dart:convert';\n\nimport 'package:path_provider/path_provider.dart';\n")
s = rep(s, "  // Background PCs: clipboard off", r"""  // ---- file copy & paste: copy files on a PC, download them to the phone,
  // then paste them on another PC with Ctrl+V.
  Timer? _wizzClipTimer;
  Map<String, dynamic> _wizzClip = const {};
  int _wizzClipHiddenSeq = -1;
  String _wizzClipHiddenState = '';

  String _wizzClipCall(String key, [String param = '']) =>
      bind.sessionGetCommonSync(sessionId: sessionId, key: key, param: param) ??
      '';

  void _wizzClipPoll() {
    if (!mounted || !widget.active) return;
    try {
      final m = jsonDecode(_wizzClipCall('wizz-clip-status'));
      if (m is Map<String, dynamic> && m.toString() != _wizzClip.toString()) {
        setState(() => _wizzClip = m);
        _wizzNotify(m);
      }
    } catch (_) {}
  }

  // download progress in the notification area
  String _wizzNotifyKey = 'idle';

  void _wizzNotify(Map<String, dynamic> m) {
    final st = (m['state'] ?? 'idle').toString();
    final bytes = (m['bytes'] ?? 0) as num;
    final done = (m['done'] ?? 0) as num;
    final pct = bytes > 0 ? (done * 100 / bytes).floor().clamp(0, 100) : 0;
    final names = ((m['names'] ?? []) as List);
    final count = (m['count'] ?? 0) as int;
    final what =
        count == 1 && names.isNotEmpty ? names.first.toString() : '$count items';
    final saved = ((m['saved'] ?? []) as List);
    final single = (m['msg'] ?? '') == 'single' && saved.length == 1;
    final dir = (m['dir'] ?? '').toString().replaceFirst('/storage/emulated/0/', '');
    String key;
    Map<String, dynamic> args;
    switch (st) {
      case 'downloading':
        key = 'd$pct';
        args = {
          'state': 'downloading',
          'title': 'Downloading $what',
          'text': '$pct% · ${_wizzSize(done)} / ${_wizzSize(bytes)}',
          'progress': pct,
          'path': '',
        };
        break;
      case 'done':
        key = 'done${m['seq']}';
        args = {
          'state': 'done',
          'title': 'Downloaded $what',
          'text': 'Saved to $dir · tap to open',
          'progress': 100,
          'path': single ? saved.first.toString() : '',
        };
        break;
      case 'error':
        key = 'err${m['seq']}';
        args = {
          'state': 'error',
          'title': 'Download failed',
          'text': (m['msg'] ?? '').toString(),
          'progress': -1,
          'path': '',
        };
        break;
      default:
        key = 'idle';
        args = {'state': 'clear', 'title': '', 'text': '', 'progress': -1, 'path': ''};
    }
    if (key == _wizzNotifyKey) return;
    _wizzNotifyKey = key;
    _ffi.invokeMethod("wizz_dl_notify", args);
  }

  Future<void> _wizzClipDownload() async {
    var fallback = '';
    try {
      final d = await getExternalStorageDirectory();
      if (d != null) fallback = '${d.path}/RustDesk';
    } catch (_) {}
    _wizzClipCall('wizz-clip-download',
        '/storage/emulated/0/Download/RustDesk\n$fallback');
    _wizzClipPoll();
  }

  String _wizzSize(num b) {
    if (b < 1024) return '$b B';
    if (b < 1024 * 1024) return '${(b / 1024).toStringAsFixed(0)} KB';
    if (b < 1024 * 1024 * 1024) {
      return '${(b / 1024 / 1024).toStringAsFixed(1)} MB';
    }
    return '${(b / 1024 / 1024 / 1024).toStringAsFixed(2)} GB';
  }

  Widget _wizzClipBanner() {
    final st = (_wizzClip['state'] ?? 'idle').toString();
    final seq = (_wizzClip['seq'] ?? 0) as int;
    if (st == 'idle' ||
        (seq == _wizzClipHiddenSeq && st == _wizzClipHiddenState)) {
      return const SizedBox.shrink();
    }
    final count = (_wizzClip['count'] ?? 0) as int;
    final bytes = (_wizzClip['bytes'] ?? 0) as num;
    final done = (_wizzClip['done'] ?? 0) as num;
    final names = ((_wizzClip['names'] ?? []) as List).cast<dynamic>();
    final dir = (_wizzClip['dir'] ?? '')
        .toString()
        .replaceFirst('/storage/emulated/0/', '');
    final msg = (_wizzClip['msg'] ?? '').toString();
    String text;
    double? progress;
    final actions = <Widget>[];
    switch (st) {
      case 'offered':
        text = count == 1 && names.isNotEmpty
            ? 'Copied on PC: ${names.first} (${_wizzSize(bytes)})'
            : 'Copied on PC: $count items (${_wizzSize(bytes)})';
        actions.add(TextButton(
            onPressed: _wizzClipDownload, child: const Text('Download')));
        break;
      case 'downloading':
        final pv = bytes > 0 ? (done / bytes).clamp(0.0, 1.0).toDouble() : 0.0;
        progress = bytes > 0 ? pv : null;
        final pct = bytes > 0 ? '${(pv * 100).toStringAsFixed(0)}% · ' : '';
        text = 'Downloading $pct${_wizzSize(done)} / ${_wizzSize(bytes)}';
        actions.add(TextButton(
            onPressed: () => _wizzClipCall('wizz-clip-cancel'),
            child: const Text('Cancel')));
        break;
      case 'done':
        final saved = ((_wizzClip['saved'] ?? []) as List).cast<dynamic>();
        final single = msg == 'single' && saved.length == 1;
        text = 'Saved to $dir';
        actions.add(TextButton(
            onPressed: () {
              if (single) {
                _ffi.invokeMethod("wizz_open_file", saved.first.toString());
              } else {
                _ffi.invokeMethod("wizz_show_downloads");
              }
            },
            child: Text(single ? 'Open' : 'Show')));
        actions.add(TextButton(
            onPressed: () {
              _wizzClipCall('wizz-clip-delete');
              showToast('Deleted from the phone');
              _wizzClipPoll();
            },
            child: const Text('Delete')));
        break;
      default:
        text = 'Download failed: $msg';
    }
    return Positioned(
      top: 8,
      left: 8,
      right: 8,
      child: Material(
        color: Colors.black.withOpacity(0.55),
        borderRadius: BorderRadius.circular(10),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 4, 4, 4),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                children: [
                  const Icon(Icons.file_copy, color: Colors.white, size: 18),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(text,
                        style: const TextStyle(color: Colors.white),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis),
                  ),
                  ...actions,
                  IconButton(
                    icon: const Icon(Icons.close, color: Colors.white),
                    onPressed: () {
                      if (st != 'downloading') {
                        _wizzClipCall('wizz-clip-dismiss');
                      }
                      setState(() {
                        _wizzClipHiddenSeq = seq;
                        _wizzClipHiddenState = st;
                      });
                    },
                  ),
                ],
              ),
              if (st == 'downloading')
                Padding(
                  padding: const EdgeInsets.only(right: 8, bottom: 6),
                  child: LinearProgressIndicator(value: progress),
                ),
            ],
          ),
        ),
      ),
    );
  }

  // Background PCs: clipboard off""")
s = rep(s, """              child: QualityMonitor(_ffi.qualityMonitorModel),
            ),
""", """              child: QualityMonitor(_ffi.qualityMonitorModel),
            ),
            if (widget.active) _wizzClipBanner(),
""")
# poll while shown; stop on close
s = rep(s, "    _wizzBackground(false);\n    // a PC opened", "    _wizzClipTimer = Timer.periodic(\n        const Duration(seconds: 1), (_) => _wizzClipPoll());\n    _wizzBackground(false);\n    // a PC opened")
s = rep(s, "  Future<void> dispose() async {\n", "  Future<void> dispose() async {\n    _wizzClipTimer?.cancel();\n")
# switching to a PC: offer downloaded files there first, else the text clipboard
s = rep(s, """        if (mounted && widget.active) {
          _ffi.invokeMethod("wizz_force_sync_clipboard");
        }""", """        if (mounted && widget.active) {
          final code = _wizzClipCall('wizz-clip-offer');
          if (code == '1') {
            showToast('Copied files are ready here: paste with Ctrl+V');
          } else if (code == '0') {
            _ffi.invokeMethod("wizz_force_sync_clipboard");
          }
        }""")
save(p, s)

# home screen: long-press PCs (any tab, address book included), then the arrow
p = 'flutter/lib/mobile/pages/connection_page.dart'
s = load(p)
s = rep(s, "import 'home_page.dart';\n", "import 'home_page.dart';\nimport 'wizz_sessions.dart';\n")
s = rep(s, """  void onConnect() {
    var id = _idController.id;""", """  void onConnect() {
    // PCs ticked in the list (long-press): connect them all
    final ptm = gFFI.peerTabModel;
    if (ptm.multiSelectionMode && ptm.selectedPeers.isNotEmpty) {
      final ids = ptm.selectedPeers.map((e) => e.id).toList();
      ptm.setMultiSelectionMode(false);
      wizzConnectMany(context, ids);
      return;
    }
    var id = _idController.id;""")
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

# ------------------------------------------ dropped PCs: no dialog when hidden
p = 'flutter/lib/models/model.dart'
s = load(p)
s = rep(s, "import 'package:flutter_hbb/utils/scale.dart';\n",
        "import 'package:flutter_hbb/utils/scale.dart';\nimport '../mobile/pages/wizz_sessions.dart';\n")
s = rep(s, """  handleMsgBox(Map<String, dynamic> evt, SessionID sessionId, String peerId) {
    if (parent.target == null) return;
""", """  handleMsgBox(Map<String, dynamic> evt, SessionID sessionId, String peerId) {
    if (parent.target == null) return;
    if (isMobile &&
        wizzOnMsgBox(sessionId, (evt['type'] ?? '').toString(),
            (evt['title'] ?? '').toString())) {
      return;
    }
""")
save(p, s)

# ------------------------------- Android: keep-alive service, open downloads
kt = 'flutter/android/app/src/main/kotlin/com/carriez/flutter_hbb/'
save(kt + 'WizzKeepAliveService.kt', """package com.carriez.flutter_hbb

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder

// Wizz: a quiet notification while remote PCs are open, so Android keeps the
// app's network and the sessions survive switching to another app.
class WizzKeepAliveService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val n = intent?.getIntExtra("count", 1) ?: 1
        val channelId = "wizz_sessions"
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            nm.createNotificationChannel(
                NotificationChannel(channelId, "Remote sessions", NotificationManager.IMPORTANCE_LOW)
            )
        }
        val open = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, channelId)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }
        val notification = builder
            .setSmallIcon(R.mipmap.ic_stat_logo)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(if (n == 1) "Connected to 1 PC" else "Connected to $n PCs")
            .setContentIntent(open)
            .setOngoing(true)
            .build()
        try {
            if (Build.VERSION.SDK_INT >= 34) {
                startForeground(7301, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
            } else {
                startForeground(7301, notification)
            }
        } catch (e: Exception) {
            stopSelf()
        }
        return START_NOT_STICKY
    }
}
""")
save(kt + 'WizzFiles.kt', """package com.carriez.flutter_hbb

import android.app.Activity
import android.app.DownloadManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.OpenableColumns
import android.util.Log
import android.webkit.MimeTypeMap
import android.widget.Toast
import androidx.core.content.FileProvider
import io.flutter.plugin.common.MethodCall
import java.io.File
import java.io.FileOutputStream
import kotlin.concurrent.thread

// Wizz: files from the phone to paste on a PC, and the download notification.
object WizzFiles {
    fun copyToCache(ctx: Context, uris: List<Uri>): List<String> {
        val dir = File(ctx.cacheDir, "wizz_send")
        dir.deleteRecursively()
        dir.mkdirs()
        val out = mutableListOf<String>()
        for (u in uris) {
            try {
                var name = queryName(ctx, u) ?: u.lastPathSegment ?: "file"
                name = name.replace('/', '_').replace('\\\\', '_')
                var f = File(dir, name)
                var k = 1
                while (f.exists()) {
                    f = File(dir, "${k}_$name")
                    k++
                }
                ctx.contentResolver.openInputStream(u)?.use { inp ->
                    FileOutputStream(f).use { inp.copyTo(it) }
                }
                if (f.exists()) out.add(f.absolutePath)
            } catch (e: Exception) {
                Log.e("Wizz", "copy: $e")
            }
        }
        return out
    }

    private fun queryName(ctx: Context, u: Uri): String? = try {
        ctx.contentResolver.query(u, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
            ?.use { c -> if (c.moveToFirst()) c.getString(0) else null }
    } catch (e: Exception) {
        null
    }

    fun viewIntent(ctx: Context, path: String): Intent {
        val f = File(path)
        val uri = FileProvider.getUriForFile(ctx, "${ctx.packageName}.wizzfiles", f)
        val mime = MimeTypeMap.getSingleton().getMimeTypeFromExtension(f.extension.lowercase()) ?: "*/*"
        return Intent(Intent.ACTION_VIEW).setDataAndType(uri, mime)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
    }

    fun notifyDownload(ctx: Context, call: MethodCall) {
        val nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val state = call.argument<String>("state") ?: "clear"
        if (state == "clear") {
            nm.cancel(7302)
            return
        }
        val channelId = "wizz_downloads"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            nm.createNotificationChannel(
                NotificationChannel(channelId, "File downloads", NotificationManager.IMPORTANCE_LOW)
            )
        }
        val b = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(ctx, channelId)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(ctx)
        }
        b.setSmallIcon(R.mipmap.ic_stat_logo)
            .setContentTitle(call.argument<String>("title") ?: "")
            .setContentText(call.argument<String>("text") ?: "")
        val flags = PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        if (state == "downloading") {
            val progress = (call.argument<Int>("progress") ?: 0).coerceIn(0, 100)
            b.setOngoing(true).setOnlyAlertOnce(true).setProgress(100, progress, false)
            b.setContentIntent(PendingIntent.getActivity(ctx, 7303,
                Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP), flags))
        } else {
            b.setAutoCancel(true)
            val path = call.argument<String>("path") ?: ""
            val target = try {
                if (path.isNotEmpty()) viewIntent(ctx, path)
                else Intent(DownloadManager.ACTION_VIEW_DOWNLOADS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            } catch (e: Exception) {
                Intent(DownloadManager.ACTION_VIEW_DOWNLOADS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            b.setContentIntent(PendingIntent.getActivity(ctx, 7302, target, flags))
        }
        try {
            nm.notify(7302, b.build())
        } catch (e: Exception) {
            Log.e("Wizz", "notify: $e")
        }
    }
}

// Share menu target: "Paste on PC". Copies the shared files and returns to the app.
class WizzShareActivity : Activity() {
    companion object {
        private val pending = mutableListOf<String>()
        fun take(): List<String> = synchronized(pending) {
            val l = pending.toList()
            pending.clear()
            l
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val uris = mutableListOf<Uri>()
        try {
            @Suppress("DEPRECATION")
            when (intent?.action) {
                Intent.ACTION_SEND -> intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM)?.let { uris.add(it) }
                Intent.ACTION_SEND_MULTIPLE ->
                    intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)?.let { uris.addAll(it) }
            }
            if (uris.isEmpty()) {
                intent?.clipData?.let { c -> for (k in 0 until c.itemCount) c.getItemAt(k).uri?.let { uris.add(it) } }
            }
        } catch (e: Exception) {
            Log.e("Wizz", "share: $e")
        }
        if (uris.isEmpty()) {
            finish()
            return
        }
        Toast.makeText(this, "Preparing files for the PC…", Toast.LENGTH_SHORT).show()
        thread {
            val paths = WizzFiles.copyToCache(applicationContext, uris)
            synchronized(pending) {
                pending.clear()
                pending.addAll(paths)
            }
            runOnUiThread {
                startActivity(Intent(this, MainActivity::class.java).addFlags(
                    Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP))
                finish()
            }
        }
    }
}
""")
p = kt + 'MainActivity.kt'
s = load(p)
s = rep(s, "    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {\n        super.onActivityResult(requestCode, resultCode, data)\n",
        """    private var wizzPickResult: MethodChannel.Result? = null

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == 7310) {
            val r = wizzPickResult ?: return
            wizzPickResult = null
            if (resultCode != Activity.RESULT_OK || data == null) {
                r.success(emptyList<String>())
                return
            }
            val uris = mutableListOf<Uri>()
            data.data?.let { uris.add(it) }
            data.clipData?.let { c -> for (k in 0 until c.itemCount) uris.add(c.getItemAt(k).uri) }
            thread {
                val paths = WizzFiles.copyToCache(this, uris.distinct())
                runOnUiThread { r.success(paths) }
            }
            return
        }
""")
s = rep(s, '                "try_sync_clipboard" -> {\n', """                "wizz_pick_files" -> {
                    wizzPickResult = result
                    val i = Intent(Intent.ACTION_OPEN_DOCUMENT)
                        .addCategory(Intent.CATEGORY_OPENABLE)
                        .setType("*/*")
                        .putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
                    try {
                        startActivityForResult(i, 7310)
                    } catch (e: Exception) {
                        wizzPickResult = null
                        result.success(emptyList<String>())
                    }
                }
                "wizz_take_shared" -> result.success(WizzShareActivity.take())
                "wizz_dl_notify" -> {
                    WizzFiles.notifyDownload(this, call)
                    result.success(true)
                }
                "try_sync_clipboard" -> {
""")
s = rep(s, '                "try_sync_clipboard" -> {\n', """                "wizz_keepalive" -> {
                    try {
                        val n = (call.arguments as? Int) ?: 0
                        val i = Intent(this, WizzKeepAliveService::class.java)
                        if (n > 0) {
                            i.putExtra("count", n)
                            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(i) else startService(i)
                        } else {
                            stopService(i)
                        }
                    } catch (e: Exception) {
                        Log.e("Wizz", "keepalive: $e")
                    }
                    result.success(true)
                }
                "wizz_open_file" -> {
                    try {
                        val f = File(call.arguments as String)
                        val uri = androidx.core.content.FileProvider.getUriForFile(this, "$packageName.wizzfiles", f)
                        val mime = MimeTypeMap.getSingleton()
                            .getMimeTypeFromExtension(f.extension.lowercase()) ?: "*/*"
                        val i = Intent(Intent.ACTION_VIEW).setDataAndType(uri, mime)
                            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
                        startActivity(Intent.createChooser(i, f.name).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                        result.success(true)
                    } catch (e: Exception) {
                        Log.e("Wizz", "open file: $e")
                        result.success(false)
                    }
                }
                "wizz_show_downloads" -> {
                    try {
                        startActivity(Intent(android.app.DownloadManager.ACTION_VIEW_DOWNLOADS)
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                        result.success(true)
                    } catch (e: Exception) {
                        result.success(false)
                    }
                }
                "try_sync_clipboard" -> {
""")
save(p, s)
p = 'flutter/android/app/src/main/AndroidManifest.xml'
s = load(p)
s = rep(s, """        <service
            android:name=".FloatingWindowService"
            android:enabled="true" />
""", """        <service
            android:name=".FloatingWindowService"
            android:enabled="true" />

        <service
            android:name=".WizzKeepAliveService"
            android:enabled="true"
            android:exported="false"
            android:foregroundServiceType="specialUse">
            <property
                android:name="android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE"
                android:value="Keeps remote desktop sessions connected" />
        </service>

        <activity
            android:name=".WizzShareActivity"
            android:exported="true"
            android:excludeFromRecents="true"
            android:noHistory="true"
            android:label="Paste on PC"
            android:theme="@style/Transparent">
            <intent-filter>
                <action android:name="android.intent.action.SEND" />
                <category android:name="android.intent.category.DEFAULT" />
                <data android:mimeType="*/*" />
            </intent-filter>
            <intent-filter>
                <action android:name="android.intent.action.SEND_MULTIPLE" />
                <category android:name="android.intent.category.DEFAULT" />
                <data android:mimeType="*/*" />
            </intent-filter>
        </activity>

        <provider
            android:name="androidx.core.content.FileProvider"
            android:authorities="${applicationId}.wizzfiles"
            android:exported="false"
            android:grantUriPermissions="true">
            <meta-data
                android:name="android.support.FILE_PROVIDER_PATHS"
                android:resource="@xml/wizz_file_paths" />
        </provider>
""")
save(p, s)
save('flutter/android/app/src/main/res/xml/wizz_file_paths.xml', """<?xml version="1.0" encoding="utf-8"?>
<paths>
    <external-path name="ext" path="." />
    <external-files-path name="extfiles" path="." />
</paths>
""")

print('wizz multi-session patch applied')
