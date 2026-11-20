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

# ===== Wizz: hidden keyboard box padded with invisible blanks, not "1111…" =====
p = 'flutter/lib/mobile/pages/remote_page.dart'
s = open(p).read()
zrep("final initText = '1' * 1024;", "final initText = '\\u2800' * 1024;")
zrep("    for (; i >= 0 && newValue[i] != '1'; --i) {}", "    for (; i >= 0 && newValue[i] != initText[0]; --i) {}")
zrep("    for (; j >= 0 && oldValue[j] != '1'; --j) {}", "    for (; j >= 0 && oldValue[j] != initText[0]; --j) {}")
zrep("        oldValue[0] == '1' &&\n        newValue[0] != '1') {", "        oldValue[0] == initText[0] &&\n        newValue[0] != initText[0]) {")
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
import '../../common/widgets/toolbar.dart';
import '../../common/shared_state.dart';
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

// ---- privacy mode per PC from the sessions screen
const _kWizzPrivacyHelp = [
  'Blacks out the PC monitor. Works on most PCs.',
  'Uses a virtual display. Needs the RustDesk display driver on the PC.',
];

Widget wizzPrivacyButton(BuildContext context, WizzSession s) {
  final state = PrivacyModeState.find(s.id);
  return Obx(() {
    final on = state.value.isNotEmpty;
    final toggles = toolbarPrivacyMode(state, context, s.id, s.ffi);
    final usable = toggles.any((t) => t.onChanged != null);
    // no tooltip: on Android a tooltip takes the long-press for itself
    return InkResponse(
      radius: 24,
      onTap: usable
          ? () => _wizzTogglePrivacy(context, state, toggles)
          : () => showToast('Privacy mode is not available on this PC'),
      onLongPress: usable
          ? () => _wizzChoosePrivacy(context, toggles, remember: true)
          : null,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Icon(on ? Icons.shield : Icons.shield_outlined,
            color: on
                ? MyTheme.accent
                : (usable ? Colors.grey : Colors.grey.withOpacity(0.35))),
      ),
    );
  });
}

void _wizzTogglePrivacy(
    BuildContext context, RxString state, List<TToggleMenu> toggles) {
  if (state.value.isNotEmpty) {
    for (final t in toggles) {
      if (t.value) {
        t.onChanged?.call(false);
        return;
      }
    }
    toggles.first.onChanged?.call(false);
    return;
  }
  if (toggles.length == 1) {
    toggles.first.onChanged?.call(true);
    return;
  }
  final saved = int.tryParse(bind.mainGetLocalOption(key: 'wizz-privacy-mode'));
  if (saved != null &&
      saved >= 0 &&
      saved < toggles.length &&
      toggles[saved].onChanged != null) {
    toggles[saved].onChanged!(true);
    return;
  }
  _wizzChoosePrivacy(context, toggles, remember: true);
}

/// Mode 1 or Mode 2; the choice is remembered (long-press the shield to change).
void _wizzChoosePrivacy(BuildContext context, List<TToggleMenu> toggles,
    {bool remember = true}) {
  showDialog(
    context: context,
    builder: (ctx) => AlertDialog(
      title: const Text('Privacy mode'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          for (var i = 0; i < toggles.length; i++)
            ListTile(
              enabled: toggles[i].onChanged != null,
              title: toggles[i].child,
              subtitle: i < _kWizzPrivacyHelp.length
                  ? Text(_kWizzPrivacyHelp[i])
                  : null,
              trailing: toggles[i].value
                  ? const Icon(Icons.check, color: Colors.green)
                  : null,
              onTap: () async {
                Navigator.pop(ctx);
                if (remember) {
                  bind.mainSetLocalOption(
                      key: 'wizz-privacy-mode', value: i.toString());
                }
                if (toggles[i].value) return;
                // another mode is on: turn it off first, then switch
                for (final t in toggles) {
                  if (t.value) {
                    t.onChanged?.call(false);
                    await Future.delayed(const Duration(milliseconds: 800));
                  }
                }
                toggles[i].onChanged?.call(true);
              },
            ),
        ],
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
      ],
    ),
  );
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
                trailing: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    wizzPrivacyButton(context, list[i]),
                    IconButton(
                      icon: const Icon(Icons.close),
                      tooltip: 'Disconnect',
                      onPressed: () {
                        Navigator.pop(ctx);
                        m.closeAt(i);
                      },
                    ),
                  ],
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


WIZZ_SWITCHER_DART = r'''// Wizz: hold the sessions button to see every open PC as a live preview
// (like hovering over the Windows taskbar). Slide onto one and let go, or let
// go first and tap one. Optional: swipe the bottom toolbar to change PC.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:get/get.dart';

import '../../common.dart';
import '../../models/platform_model.dart';
import '../../common/shared_state.dart';
import '../../models/model.dart';
import '../../models/state_model.dart';
import 'home_page.dart';
import 'wizz_sessions.dart';
import 'wizz_settings.dart';

class WizzSessionsButton extends StatefulWidget {
  final void Function()? onTap;
  final double padding;
  final Color? color;
  const WizzSessionsButton(
      {Key? key, required this.onTap, this.padding = 12, this.color = Colors.white})
      : super(key: key);

  @override
  State<WizzSessionsButton> createState() => _WizzSessionsButtonState();
}

class _WizzSessionsButtonState extends State<WizzSessionsButton> {
  OverlayEntry? _entry;
  final _strip = GlobalKey<_WizzStripState>();
  bool _dragged = false;

  void _open() {
    if (WizzSessions.to.sessions.isEmpty) return;
    HapticFeedback.mediumImpact();
    final box = context.findRenderObject() as RenderBox?;
    final top = box == null ? 120.0 : box.localToGlobal(Offset.zero).dy;
    _dragged = false;
    _entry = OverlayEntry(
        builder: (_) => _WizzStrip(key: _strip, bottomEdge: top, onClose: _close));
    Overlay.of(context).insert(_entry!);
  }

  void _close() {
    _entry?.remove();
    _entry = null;
  }

  @override
  void dispose() {
    _close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: widget.onTap,
      onLongPressStart: (_) => _open(),
      onLongPressMoveUpdate: (d) {
        _dragged = true;
        _strip.currentState?.hover(d.globalPosition);
      },
      onLongPressEnd: (d) {
        // slid onto a PC: switch. Otherwise keep the strip open for a tap.
        final s = _strip.currentState;
        if (s == null) return;
        if (_dragged && s.pickAt(d.globalPosition)) return;
        s.hover(null);
      },
      child: Padding(
        padding: EdgeInsets.all(widget.padding),
        child: wizzSessionsIcon(color: widget.color),
      ),
    );
  }
}

class _WizzStrip extends StatefulWidget {
  final double bottomEdge; // top of the sessions button, in screen pixels
  final void Function() onClose;
  const _WizzStrip({Key? key, required this.bottomEdge, required this.onClose})
      : super(key: key);

  @override
  State<_WizzStrip> createState() => _WizzStripState();
}

class _WizzStripState extends State<_WizzStrip> {
  final List<GlobalKey> _cards = [];
  int _hover = -1;

  int _indexAt(Offset p) {
    for (var i = 0; i < _cards.length; i++) {
      final b = _cards[i].currentContext?.findRenderObject() as RenderBox?;
      if (b == null || !b.attached) continue;
      final r = b.localToGlobal(Offset.zero) & b.size;
      if (r.contains(p)) return i;
    }
    return -1;
  }

  void hover(Offset? p) {
    final i = p == null ? -1 : _indexAt(p);
    if (i != _hover) {
      if (i >= 0) HapticFeedback.selectionClick();
      setState(() => _hover = i);
    }
  }

  bool pickAt(Offset p) {
    final i = _indexAt(p);
    if (i < 0) return false;
    _pick(i);
    return true;
  }

  void _pick(int i) {
    final m = WizzSessions.to;
    widget.onClose();
    if (i >= m.sessions.length) {
      final ctx = globalKey.currentContext;
      if (ctx != null) showWizzConnectDialog(ctx);
    } else {
      m.switchTo(i);
      wizzReturnToSessions();
    }
  }

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.of(context).size;
    final wide = size.width > 700; // Fold inner screen, tablets
    final cardW = wide ? 200.0 : 150.0;
    return Stack(children: [
      Positioned.fill(
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: widget.onClose,
          child: Container(color: Colors.black26),
        ),
      ),
      Positioned(
        left: 0,
        right: 0,
        bottom: size.height - widget.bottomEdge + 8,
        child: Obx(() {
          final m = WizzSessions.to;
          final list = m.sessions.toList();
          final cur = m.current.value;
          while (_cards.length < list.length + 1) {
            _cards.add(GlobalKey());
          }
          final cards = <Widget>[
            for (var i = 0; i < list.length; i++)
              _WizzCard(
                key: _cards[i],
                s: list[i],
                width: cardW,
                current: i == cur,
                hover: i == _hover,
                onTap: () => _pick(i),
              ),
            _WizzAddCard(
                key: _cards[list.length],
                width: cardW * 0.5,
                hover: _hover == list.length,
                onTap: () => _pick(list.length)),
          ];
          if (wide) {
            return ConstrainedBox(
              constraints: BoxConstraints(maxHeight: size.height * 0.6),
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(8),
                child: Wrap(
                    alignment: WrapAlignment.center,
                    spacing: 8,
                    runSpacing: 8,
                    children: cards),
              ),
            );
          }
          return SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 8),
            child: Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  for (final c in cards)
                    Padding(padding: const EdgeInsets.only(right: 8), child: c)
                ]),
          );
        }),
      ),
    ]);
  }
}

class WizzPreviewPainter extends CustomPainter {
  final ImageModel model;
  WizzPreviewPainter(this.model) : super(repaint: model);

  @override
  void paint(Canvas canvas, Size size) {
    final img = model.image;
    if (img == null) return;
    final src = Rect.fromLTWH(0, 0, img.width.toDouble(), img.height.toDouble());
    final fitted = applyBoxFit(BoxFit.contain, src.size, size);
    final dst = Alignment.center.inscribe(fitted.destination, Offset.zero & size);
    canvas.drawImageRect(img, src, dst,
        Paint()..filterQuality = FilterQuality.medium);
  }

  @override
  bool shouldRepaint(WizzPreviewPainter old) => old.model != model;
}

class _WizzCard extends StatelessWidget {
  final WizzSession s;
  final double width;
  final bool current;
  final bool hover;
  final void Function() onTap;
  const _WizzCard(
      {Key? key,
      required this.s,
      required this.width,
      required this.current,
      required this.hover,
      required this.onTap})
      : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Obx(() {
      final dropped = s.dropped.value;
      final privacy = PrivacyModeState.find(s.id).value.isNotEmpty;
      final border = dropped
          ? Colors.red
          : hover
              ? Colors.white
              : current
                  ? Colors.lightBlueAccent
                  : Colors.white24;
      return GestureDetector(
        onTap: onTap,
        onLongPress: () => showToast(
            s.title == s.id ? s.id : '${s.title}\n${s.id}'),
        child: AnimatedScale(
          scale: hover ? 1.06 : 1.0,
          duration: const Duration(milliseconds: 100),
          child: Container(
            width: width,
            decoration: BoxDecoration(
              color: const Color(0xEE202020),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: border, width: hover || current || dropped ? 2.5 : 1),
            ),
            padding: const EdgeInsets.all(6),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              AspectRatio(
                aspectRatio: 16 / 9,
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(6),
                  child: Stack(fit: StackFit.expand, children: [
                    Container(color: Colors.black),
                    CustomPaint(painter: WizzPreviewPainter(s.ffi.imageModel)),
                    if (dropped)
                      Container(
                        color: Colors.black54,
                        alignment: Alignment.center,
                        child: const Icon(Icons.link_off, color: Colors.red, size: 28),
                      ),
                    if (privacy)
                      const Positioned(
                        right: 4,
                        top: 4,
                        child: Icon(Icons.shield,
                            size: 16, color: Colors.lightGreenAccent, shadows: kWizzTextOutline),
                      ),
                  ]),
                ),
              ),
              const SizedBox(height: 4),
              Text(s.title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                      color: dropped ? Colors.redAccent : Colors.white,
                      fontSize: 12,
                      fontWeight: current ? FontWeight.bold : FontWeight.normal)),
            ]),
          ),
        ),
      );
    });
  }
}

class _WizzAddCard extends StatelessWidget {
  final double width;
  final bool hover;
  final void Function() onTap;
  const _WizzAddCard(
      {Key? key, required this.width, required this.hover, required this.onTap})
      : super(key: key);

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: width,
        height: width * 1.2,
        decoration: BoxDecoration(
          color: const Color(0xEE202020),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: hover ? Colors.white : Colors.white24, width: hover ? 2.5 : 1),
        ),
        child: const Icon(Icons.add, color: Colors.white, size: 30),
      ),
    );
  }
}

/// Swipe the bottom toolbar left/right to go to the next/previous PC
/// (Settings → Multiview → Switching).
Widget wizzSwipeSwitch(Widget toolbar) {
  if (!WizzPrefs.swipeSwitch) return toolbar;
  return GestureDetector(
    onHorizontalDragEnd: (d) {
      final v = d.primaryVelocity ?? 0;
      if (v.abs() < 300) return;
      final m = WizzSessions.to;
      if (m.sessions.length < 2) return;
      final n = m.sessions.length;
      final i = (m.current.value + (v < 0 ? 1 : -1) + n) % n;
      HapticFeedback.selectionClick();
      m.switchTo(i);
      showToast(m.sessions[i].title);
    },
    child: toolbar,
  );
}

// ---------------------------------------------------------------- minimize
// The PCs keep running in the background while the home screen is shown on
// top of them; tapping PCs (or a connected PC, or the notification) returns.
Route<dynamic>? _wizzMiniRoute;

void wizzMinimize() {
  final m = WizzSessions.to;
  final nav = globalKey.currentState;
  if (!m.hostMounted || m.minimized.value || nav == null) return;
  m.minimized.value = true;
  stateGlobal.isInMainPage = true;
  SystemChrome.setEnabledSystemUIMode(SystemUiMode.manual,
      overlays: SystemUiOverlay.values);
  final r = MaterialPageRoute(builder: (_) => HomePage(wizzMini: true));
  _wizzMiniRoute = r;
  nav.push(r).then((_) {
    if (identical(_wizzMiniRoute, r)) {
      _wizzMiniRoute = null;
      _wizzBackToSessions();
    }
  });
  if (bind.mainGetLocalOption(key: 'wizz-mini-tip') != 'Y') {
    bind.mainSetLocalOption(key: 'wizz-mini-tip', value: 'Y');
    showToast('PCs kept in the background. Tap PCs to return');
  }
}

void _wizzBackToSessions() {
  final m = WizzSessions.to;
  if (!m.minimized.value) return;
  m.minimized.value = false;
  stateGlobal.isInMainPage = false;
  if (m.hostMounted) {
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.manual, overlays: []);
  }
}

/// Back to the open PCs (if the home screen is showing on top of them).
void wizzReturnToSessions() {
  final r = _wizzMiniRoute;
  _wizzMiniRoute = null;
  if (r != null && r.isActive) {
    final nav = globalKey.currentState;
    if (r.isCurrent) {
      nav?.pop();
    } else {
      nav?.removeRoute(r);
    }
  }
  _wizzBackToSessions();
}

void wizzResetMinimized() {
  _wizzMiniRoute = null;
  WizzSessions.to.minimized.value = false;
}

/// Taps on the keep-alive notification (open / "Disconnect all").
Future<void> wizzTakeNotificationAction() async {
  final a =
      await gFFI.invokeMethodWithResult<String>('wizz_take_action') ?? '';
  if (a.isEmpty) return;
  WizzLock.to.afterUnlock(() {
    if (!WizzSessions.to.hostMounted) return;
    if (a == 'return') {
      wizzReturnToSessions();
    } else if (a == 'closeall') {
      wizzPopToHome();
    }
  });
}

/// X in the toolbar: with several PCs open, choose this one or all.
void wizzCloseTapped(BuildContext context, void Function() closeOne) {
  final m = WizzSessions.to;
  if (m.sessions.length < 2) {
    closeOne();
    return;
  }
  final cur = m.current.value.clamp(0, m.sessions.length - 1);
  final title = m.sessions[cur].title;
  showModalBottomSheet(
    context: context,
    builder: (ctx) => SafeArea(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        ListTile(
          leading: const Icon(Icons.close),
          title: Text('Close $title'),
          onTap: () {
            Navigator.pop(ctx);
            m.closeAt(m.current.value);
          },
        ),
        ListTile(
          leading: const Icon(Icons.clear_all, color: Colors.redAccent),
          title: Text('Close all ${m.sessions.length} PCs',
              style: const TextStyle(color: Colors.redAccent)),
          onTap: () {
            Navigator.pop(ctx);
            wizzPopToHome();
          },
        ),
      ]),
    ),
  );
}

// ------------------------------------------------------- session toolbar
Widget wizzTb(String id, Widget w) =>
    KeyedSubtree(key: ValueKey<String>('wztb-$id'), child: w);

String? _wizzTbId(Widget w) {
  final k = w.key;
  if (k is ValueKey<String> && k.value.startsWith('wztb-')) {
    return k.value.substring(5);
  }
  return null;
}

/// Orders the toolbar buttons as set in Settings; hidden ones go under ⋮.
List<Widget> wizzArrange(
    BuildContext context, void Function() onMore, List<Widget> all) {
  final byId = <String, Widget>{};
  final other = <Widget>[];
  for (final w in all) {
    final id = _wizzTbId(w);
    if (id == null) {
      other.add(w);
    } else {
      byId[id] = w;
    }
  }
  byId.remove('more');
  final hiddenIds = WizzPrefs.tbHidden;
  final visible = <Widget>[];
  final hidden = <MapEntry<String, Widget>>[];
  for (final id in WizzPrefs.tbOrder) {
    final w = byId.remove(id);
    if (w == null) continue;
    if (hiddenIds.contains(id)) {
      hidden.add(MapEntry(id, w));
    } else {
      visible.add(w);
    }
  }
  visible.addAll(byId.values);
  visible.addAll(other);
  visible.add(IconButton(
    color: Colors.white,
    icon: const Icon(Icons.more_vert),
    onPressed: () {
      if (hidden.isEmpty && WizzSessions.to.sessions.length < 2) {
        onMore();
      } else {
        _wizzMoreSheet(context, hidden, onMore);
      }
    },
  ));
  return visible;
}

void _wizzMoreSheet(BuildContext context, List<MapEntry<String, Widget>> hidden,
    void Function() onMore) {
  const white = TextStyle(color: Colors.white);
  showModalBottomSheet(
    context: context,
    backgroundColor: wizzToolbarColor(opaque: true),
    builder: (ctx) {
      final route = ModalRoute.of(ctx);
      void closeSheet() {
        Future.microtask(() {
          if (route != null && route.isActive) {
            Navigator.of(ctx).removeRoute(route);
          }
        });
      }

      return SafeArea(
        child: IconTheme.merge(
          data: const IconThemeData(color: Colors.white),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            if (hidden.isNotEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(8, 12, 8, 4),
                child: Wrap(spacing: 12, runSpacing: 8, children: [
                  for (final e in hidden)
                    Listener(
                      onPointerUp: (_) => closeSheet(),
                      child: Column(mainAxisSize: MainAxisSize.min, children: [
                        e.value,
                        Text(kWizzTbLabels[e.key] ?? e.key,
                            style: const TextStyle(
                                color: Colors.white, fontSize: 11)),
                      ]),
                    ),
                ]),
              ),
            if (WizzSessions.to.sessions.length > 1)
              ListTile(
                leading: const Icon(Icons.clear_all),
                title: Text('Disconnect all ${WizzSessions.to.sessions.length} PCs',
                    style: white),
                onTap: () {
                  Navigator.pop(ctx);
                  wizzPopToHome();
                },
              ),
            ListTile(
              leading: const Icon(Icons.more_horiz),
              title: const Text('More options', style: white),
              onTap: () {
                Navigator.pop(ctx);
                onMore();
              },
            ),
          ]),
        ),
      );
    },
  );
}

// ------------------------------------------------- home: PCs tab, previews
class WizzPcsTab extends StatelessWidget implements PageShape {
  WizzPcsTab({Key? key}) : super(key: key);

  @override
  final String title = 'PCs';

  @override
  final Widget icon = const WizzSessionsButton(onTap: null, padding: 0, color: null);

  @override
  final List<Widget> appBarActions = const [];

  @override
  Widget build(BuildContext context) => const SizedBox.shrink();
}

/// The platform square in the PC list: a live picture when that PC is open.
Widget wizzPeerTile(String id, double size, Widget fallback) {
  if (!isAndroid) return fallback;
  return Obx(() {
    final m = WizzSessions.to;
    final i = m.sessions.indexWhere((s) => s.id == id);
    if (i < 0) return fallback;
    final s = m.sessions[i];
    final dropped = s.dropped.value;
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: Colors.black,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
            color: dropped ? Colors.red : Colors.greenAccent, width: 2),
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(6),
        child: Stack(fit: StackFit.expand, children: [
          CustomPaint(painter: WizzPreviewPainter(s.ffi.imageModel)),
          if (dropped)
            Container(
              color: Colors.black54,
              alignment: Alignment.center,
              child: const Icon(Icons.link_off, color: Colors.red, size: 18),
            )
          else
            Positioned(
              right: 2,
              bottom: 2,
              child: Container(
                width: 8,
                height: 8,
                decoration: BoxDecoration(
                    color: Colors.greenAccent,
                    shape: BoxShape.circle,
                    border: Border.all(color: Colors.black, width: 1)),
              ),
            ),
        ]),
      ),
    );
  });
}
'''

WIZZ_SETTINGS_DART = r'''// Wizz: Multiview settings (app lock, favourite keys, file copy & paste),
// the app lock itself and the favourite-keys catalogue.
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:get/get.dart';
import 'package:path_provider/path_provider.dart';
import 'package:settings_ui/settings_ui.dart';

import '../../common.dart';
import '../../models/model.dart';
import '../../models/platform_model.dart';
import 'remote_page.dart' show sendPrompt;

// ------------------------------------------------------------------ prefs
class WizzPrefs {
  static String _get(String k, String d) {
    final v = bind.mainGetLocalOption(key: 'wizz-$k');
    return v.isEmpty ? d : v;
  }

  static void _set(String k, String v) =>
      bind.mainSetLocalOption(key: 'wizz-$k', value: v);

  static int _int(String k, int d) => int.tryParse(_get(k, '$d')) ?? d;

  // file copy & paste
  static int get barSeeThrough => _int('bar-see', 60);
  static set barSeeThrough(int v) => _set('bar-see', '$v');
  static bool get barBottom => _get('bar-pos', 'top') == 'bottom';
  static set barBottom(bool v) => _set('bar-pos', v ? 'bottom' : 'top');
  static int get autoHide => _int('bar-hide', 0);
  static set autoHide(int v) => _set('bar-hide', '$v');
  static String get saveFolder => _get('save-folder', 'dl_rd');
  static set saveFolder(String v) => _set('save-folder', v);
  static String get customTree => _get('save-tree', '');
  static set customTree(String v) => _set('save-tree', v);
  static String get customTreeName => _get('save-tree-name', '');
  static set customTreeName(String v) => _set('save-tree-name', v);
  static bool get askEach => _get('save-ask', 'N') == 'Y';
  static set askEach(bool v) => _set('save-ask', v ? 'Y' : 'N');
  static int get autoDeleteHours => _int('auto-delete', 0);
  static set autoDeleteHours(int v) => _set('auto-delete', '$v');

  // session toolbar
  static List<String> get tbOrder {
    final saved = _get('tb-order', '').split(',')
      ..removeWhere((e) => !kWizzTbLabels.containsKey(e));
    for (final id in kWizzTbDefault) {
      if (!saved.contains(id)) saved.add(id);
    }
    return saved;
  }

  static set tbOrder(List<String> v) => _set('tb-order', v.join(','));
  static List<String> get tbHidden =>
      _get('tb-hidden', '').split(',')..removeWhere((e) => e.isEmpty);
  static set tbHidden(List<String> v) => _set('tb-hidden', v.join(','));
  static String get tbColor => _get('tb-color', 'blue');
  static set tbColor(String v) => _set('tb-color', v);
  static bool get tbFloat => _get('tb-float', 'N') == 'Y';
  static set tbFloat(bool v) => _set('tb-float', v ? 'Y' : 'N');
  static int get tbSeeThrough => _int('tb-see', 40);
  static set tbSeeThrough(int v) => _set('tb-see', '$v');

  // home screen tabs
  static bool get homePcs => _get('home-pcs', 'Y') == 'Y';
  static set homePcs(bool v) => _set('home-pcs', v ? 'Y' : 'N');
  static bool get homeChat => _get('home-chat', 'Y') == 'Y';
  static set homeChat(bool v) => _set('home-chat', v ? 'Y' : 'N');
  static bool get homeShare => _get('home-share', 'Y') == 'Y';
  static set homeShare(bool v) => _set('home-share', v ? 'Y' : 'N');

  // switching PCs
  static bool get swipeSwitch => _get('swipe-switch', 'N') == 'Y';
  static set swipeSwitch(bool v) => _set('swipe-switch', v ? 'Y' : 'N');

  // keys
  static int get keysSeeThrough => _int('keys-see', 33);
  static set keysSeeThrough(int v) => _set('keys-see', '$v');
  static List<String> get favKeys =>
      _get('fav-keys', kWizzDefaultKeys.join(',')).split(',')
        ..removeWhere((e) => !kWizzKeys.containsKey(e));
  static set favKeys(List<String> v) => _set('fav-keys', v.join(','));

  // lock
  static bool get lockOn => _get('lock', 'N') == 'Y';
  static set lockOn(bool v) => _set('lock', v ? 'Y' : 'N');
  static String get lockHash => _get('lock-pin', '');
  static set lockHash(String v) => _set('lock-pin', v);
  static int get lockAfter => _int('lock-after', 60);
  static set lockAfter(int v) => _set('lock-after', '$v');
}

String wizzPinHash(String pin) =>
    sha256.convert(utf8.encode('wizz-multiview:$pin')).toString();

/// Labels that stay readable on any background (used with see-through bars).
const List<Shadow> kWizzTextOutline = [
  Shadow(blurRadius: 2, color: Colors.black),
  Shadow(offset: Offset(1, 1), blurRadius: 1, color: Colors.black),
  Shadow(offset: Offset(-1, -1), blurRadius: 1, color: Colors.black),
];

Color wizzBarColor(int seeThroughPercent) =>
    Colors.black.withOpacity((100 - seeThroughPercent.clamp(0, 100)) / 100.0);

// -------------------------------------------------------- session toolbar
const Map<String, String> kWizzTbLabels = {
  'close': 'Disconnect',
  'display': 'Display',
  'pcs': 'PCs',
  'minimize': 'Minimize',
  'keyboard': 'Keyboard',
  'touch': 'Mouse / touch',
  'chat': 'Chat',
};
const List<String> kWizzTbDefault = [
  'close', 'display', 'pcs', 'minimize', 'keyboard', 'touch', 'chat'
];
const Map<String, IconData> kWizzTbIcons = {
  'close': Icons.clear,
  'display': Icons.tv,
  'pcs': Icons.filter_none,
  'minimize': Icons.minimize,
  'keyboard': Icons.keyboard,
  'touch': Icons.mouse,
  'chat': Icons.message,
};

final Map<String, Color> kWizzTbColors = {
  'blue': MyTheme.accent,
  'black': Colors.black,
  'grey': const Color(0xFF2E2E2E),
  'purple': const Color(0xFF6A1B9A),
  'green': const Color(0xFF2E7D32),
  'teal': const Color(0xFF00796B),
  'red': const Color(0xFFC62828),
  'orange': const Color(0xFFEF6C00),
};

Color wizzToolbarColor({bool opaque = false}) {
  final c = kWizzTbColors[WizzPrefs.tbColor] ?? MyTheme.accent;
  if (opaque || !WizzPrefs.tbFloat) return c;
  return c.withOpacity((100 - WizzPrefs.tbSeeThrough.clamp(0, 100)) / 100.0);
}

/// Bumped when the home tabs change, so open home screens rebuild.
final RxInt wizzHomeRev = 0.obs;

// ------------------------------------------------------- favourite keys
class WizzKey {
  final String label;
  final IconData? icon;
  final bool modifier; // Ctrl/Alt/Shift/Win: toggles
  final void Function(FFI ffi, bool isMac) run;
  const WizzKey(this.label, this.run, {this.icon, this.modifier = false});
}

void _wizzKey(FFI f, String k) => f.inputModel.inputKey(k);

void _wizzChord(FFI f, String key, {bool ctrl = false, bool alt = false, bool shift = false}) {
  final im = f.inputModel;
  final c = im.ctrl, a = im.alt, s = im.shift;
  if (ctrl) im.ctrl = true;
  if (alt) im.alt = true;
  if (shift) im.shift = true;
  im.inputKey(key);
  im.ctrl = c;
  im.alt = a;
  im.shift = s;
}

final Map<String, WizzKey> kWizzKeys = {
  'ctrl': WizzKey('Ctrl', (f, m) => f.inputModel.ctrl = !f.inputModel.ctrl, modifier: true),
  'alt': WizzKey('Alt', (f, m) => f.inputModel.alt = !f.inputModel.alt, modifier: true),
  'shift': WizzKey('Shift', (f, m) => f.inputModel.shift = !f.inputModel.shift, modifier: true),
  'win': WizzKey('Win', (f, m) => f.inputModel.command = !f.inputModel.command, modifier: true),
  'left': WizzKey('←', (f, m) => _wizzKey(f, 'VK_LEFT'), icon: Icons.keyboard_arrow_left),
  'up': WizzKey('↑', (f, m) => _wizzKey(f, 'VK_UP'), icon: Icons.keyboard_arrow_up),
  'down': WizzKey('↓', (f, m) => _wizzKey(f, 'VK_DOWN'), icon: Icons.keyboard_arrow_down),
  'right': WizzKey('→', (f, m) => _wizzKey(f, 'VK_RIGHT'), icon: Icons.keyboard_arrow_right),
  'esc': WizzKey('Esc', (f, m) => _wizzKey(f, 'VK_ESCAPE')),
  'tab': WizzKey('Tab', (f, m) => _wizzKey(f, 'VK_TAB')),
  'enter': WizzKey('Enter', (f, m) => _wizzKey(f, 'VK_ENTER')),
  'del': WizzKey('Del', (f, m) => _wizzKey(f, 'VK_DELETE')),
  'home': WizzKey('Home', (f, m) => _wizzKey(f, 'VK_HOME')),
  'end': WizzKey('End', (f, m) => _wizzKey(f, 'VK_END')),
  'pgup': WizzKey('PgUp', (f, m) => _wizzKey(f, 'VK_PRIOR')),
  'pgdn': WizzKey('PgDn', (f, m) => _wizzKey(f, 'VK_NEXT')),
  'f5': WizzKey('F5', (f, m) => _wizzKey(f, 'VK_F5')),
  'prtscr': WizzKey('PrtScr', (f, m) => _wizzKey(f, 'VK_SNAPSHOT')),
  'ctrl_a': WizzKey('Ctrl+A', (f, m) => sendPrompt(m, 'VK_A', ffi: f)),
  'ctrl_c': WizzKey('Ctrl+C', (f, m) => sendPrompt(m, 'VK_C', ffi: f)),
  'ctrl_v': WizzKey('Ctrl+V', (f, m) => sendPrompt(m, 'VK_V', ffi: f)),
  'ctrl_x': WizzKey('Ctrl+X', (f, m) => sendPrompt(m, 'VK_X', ffi: f)),
  'ctrl_z': WizzKey('Ctrl+Z', (f, m) => sendPrompt(m, 'VK_Z', ffi: f)),
  'ctrl_s': WizzKey('Ctrl+S', (f, m) => sendPrompt(m, 'VK_S', ffi: f)),
  'alt_tab': WizzKey('Alt+Tab', (f, m) => _wizzChord(f, 'VK_TAB', alt: true)),
  'alt_f4': WizzKey('Alt+F4', (f, m) => _wizzChord(f, 'VK_F4', alt: true)),
  'task_mgr': WizzKey('Ctrl+Shift+Esc',
      (f, m) => _wizzChord(f, 'VK_ESCAPE', ctrl: true, shift: true)),
  'cad': WizzKey('Ctrl+Alt+Del', (f, m) => bind.sessionCtrlAltDel(sessionId: f.sessionId)),
};

const List<String> kWizzDefaultKeys = [
  'left', 'up', 'down', 'right', 'ctrl_a', 'ctrl_c', 'ctrl_v', 'esc', 'enter'
];

// ------------------------------------------------------- save locations
const Map<String, String> kWizzFolders = {
  'dl_rd': 'Download/RustDesk',
  'dl': 'Download',
  'docs': 'Documents/RustDesk',
  'pics': 'Pictures/RustDesk',
};

class WizzSaveTarget {
  final String path; // where the download is written
  final String tree; // custom folder (Android document tree), or ''
  final String label;
  WizzSaveTarget(this.path, this.tree, this.label);
}

Future<WizzSaveTarget?> _wizzTargetFor(String key) async {
  if (key == 'custom') {
    if (WizzPrefs.customTree.isEmpty) return null;
    final d = await getExternalStorageDirectory();
    final dir = Directory('${d?.path ?? '/storage/emulated/0/Android'}/wizz_dl');
    try {
      if (dir.existsSync()) dir.deleteSync(recursive: true);
    } catch (_) {}
    return WizzSaveTarget(dir.path, WizzPrefs.customTree, WizzPrefs.customTreeName);
  }
  final rel = kWizzFolders[key] ?? kWizzFolders['dl_rd']!;
  return WizzSaveTarget('/storage/emulated/0/$rel', '', rel);
}

Future<bool> wizzPickCustomFolder() async {
  final r = await gFFI.invokeMethodWithResult<Map<dynamic, dynamic>>('wizz_pick_tree');
  if (r == null || (r['uri'] ?? '').toString().isEmpty) return false;
  WizzPrefs.customTree = r['uri'].toString();
  WizzPrefs.customTreeName = (r['name'] ?? 'Custom folder').toString();
  return true;
}

/// Where to save a download: the saved choice, or asks if the user wants that.
Future<WizzSaveTarget?> wizzChooseSaveTarget(BuildContext context) async {
  if (!WizzPrefs.askEach) {
    final t = await _wizzTargetFor(WizzPrefs.saveFolder);
    if (t != null) return t;
    return _wizzTargetFor('dl_rd');
  }
  final key = await showModalBottomSheet<String>(
    context: context,
    builder: (ctx) => SafeArea(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        const ListTile(title: Text('Save to', style: TextStyle(fontWeight: FontWeight.bold))),
        for (final e in kWizzFolders.entries)
          ListTile(
            leading: const Icon(Icons.folder_outlined),
            title: Text(e.value),
            trailing: WizzPrefs.saveFolder == e.key ? const Icon(Icons.check) : null,
            onTap: () => Navigator.pop(ctx, e.key),
          ),
        if (WizzPrefs.customTree.isNotEmpty)
          ListTile(
            leading: const Icon(Icons.folder_special_outlined),
            title: Text(WizzPrefs.customTreeName),
            trailing: WizzPrefs.saveFolder == 'custom' ? const Icon(Icons.check) : null,
            onTap: () => Navigator.pop(ctx, 'custom'),
          ),
        ListTile(
          leading: const Icon(Icons.create_new_folder_outlined),
          title: const Text('Other folder…'),
          onTap: () => Navigator.pop(ctx, 'pick'),
        ),
      ]),
    ),
  );
  if (key == null) return null;
  if (key == 'pick') {
    if (!await wizzPickCustomFolder()) return null;
    return _wizzTargetFor('custom');
  }
  return _wizzTargetFor(key);
}

// ------------------------------------------------ auto-delete of downloads
void wizzRememberDownload(List<String> items, {bool uris = false}) {
  final now = DateTime.now().millisecondsSinceEpoch;
  final list = _wizzHistory();
  for (final i in items) {
    list.add({'k': uris ? 'u' : 'p', 'v': i, 't': now});
  }
  bind.mainSetLocalOption(key: 'wizz-dl-history', value: jsonEncode(list));
}

List<Map<String, dynamic>> _wizzHistory() {
  try {
    final v = bind.mainGetLocalOption(key: 'wizz-dl-history');
    if (v.isEmpty) return [];
    return (jsonDecode(v) as List).cast<Map<String, dynamic>>();
  } catch (_) {
    return [];
  }
}

/// Deletes downloads older than the chosen limit (never, 24 h, 7 days).
Future<void> wizzAutoDeleteDownloads() async {
  final hours = WizzPrefs.autoDeleteHours;
  if (hours <= 0) return;
  final limit = DateTime.now().millisecondsSinceEpoch - hours * 3600 * 1000;
  final keep = <Map<String, dynamic>>[];
  final uris = <String>[];
  for (final e in _wizzHistory()) {
    if ((e['t'] as num) > limit) {
      keep.add(e);
      continue;
    }
    final v = e['v'].toString();
    if (e['k'] == 'u') {
      uris.add(v);
    } else {
      try {
        final t = FileSystemEntity.typeSync(v);
        if (t == FileSystemEntityType.directory) {
          Directory(v).deleteSync(recursive: true);
        } else if (t == FileSystemEntityType.file) {
          File(v).deleteSync();
        }
      } catch (_) {}
    }
  }
  if (uris.isNotEmpty) {
    await gFFI.invokeMethodWithResult('wizz_tree_delete', uris);
  }
  bind.mainSetLocalOption(key: 'wizz-dl-history', value: jsonEncode(keep));
}

// ------------------------------------------------------------- app lock
class WizzLock with WidgetsBindingObserver {
  static final WizzLock to = WizzLock._();
  WizzLock._();
  bool _started = false;
  bool _locked = false;
  DateTime? _away;
  final List<void Function()> _afterUnlock = [];

  bool get isLocked => _locked;

  /// Runs now, or once the app is unlocked.
  void afterUnlock(void Function() f) {
    if (_locked) {
      _afterUnlock.add(f);
    } else {
      f();
    }
  }

  void start() {
    if (_started) return;
    _started = true;
    WidgetsBinding.instance.addObserver(this);
    wizzAutoDeleteDownloads();
    if (WizzPrefs.lockOn) {
      WidgetsBinding.instance.addPostFrameCallback((_) => lock());
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused || state == AppLifecycleState.hidden) {
      _away ??= DateTime.now();
    } else if (state == AppLifecycleState.resumed) {
      final away = _away;
      _away = null;
      if (!WizzPrefs.lockOn || _locked || away == null) return;
      // "immediately" still allows a few seconds (file pickers, the share menu)
      final limit = WizzPrefs.lockAfter <= 0 ? 10 : WizzPrefs.lockAfter;
      if (DateTime.now().difference(away).inSeconds >= limit) lock();
    }
  }

  void lock() {
    if (_locked) return;
    final nav = globalKey.currentState;
    if (nav == null) return;
    _locked = true;
    nav
        .push(MaterialPageRoute(
            fullscreenDialog: true, builder: (_) => const WizzLockPage()))
        .then((_) {
      _locked = false;
      final l = List.of(_afterUnlock);
      _afterUnlock.clear();
      for (final f in l) {
        f();
      }
    });
  }
}

/// Fingerprint first, PIN as the fallback. Returns true when unlocked.
class WizzLockPage extends StatefulWidget {
  final bool verifyOnly;
  const WizzLockPage({Key? key, this.verifyOnly = false}) : super(key: key);

  @override
  State<WizzLockPage> createState() => _WizzLockPageState();
}

class _WizzLockPageState extends State<WizzLockPage> {
  final _pin = TextEditingController();
  String _error = '';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _fingerprint());
  }

  Future<void> _fingerprint() async {
    final ok = await gFFI.invokeMethodWithResult<bool>('wizz_biometric') ?? false;
    if (ok && mounted) Navigator.pop(context, true);
  }

  void _check() {
    if (wizzPinHash(_pin.text) == WizzPrefs.lockHash) {
      Navigator.pop(context, true);
    } else {
      setState(() {
        _error = 'Wrong PIN';
        _pin.clear();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return WillPopScope(
      onWillPop: () async => widget.verifyOnly,
      child: Scaffold(
        body: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(32),
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                const Icon(Icons.lock_outline, size: 64),
                const SizedBox(height: 16),
                Text(widget.verifyOnly ? 'Confirm it\'s you' : 'RustDesk Multiview is locked',
                    style: const TextStyle(fontSize: 18)),
                const SizedBox(height: 24),
                SizedBox(
                  width: 220,
                  child: TextField(
                    controller: _pin,
                    autofocus: false,
                    obscureText: true,
                    keyboardType: TextInputType.number,
                    textAlign: TextAlign.center,
                    maxLength: 8,
                    decoration: InputDecoration(
                        hintText: 'PIN', errorText: _error.isEmpty ? null : _error),
                    onSubmitted: (_) => _check(),
                  ),
                ),
                const SizedBox(height: 8),
                ElevatedButton(onPressed: _check, child: const Text('Unlock')),
                const SizedBox(height: 16),
                TextButton.icon(
                    onPressed: _fingerprint,
                    icon: const Icon(Icons.fingerprint),
                    label: const Text('Use fingerprint')),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}

Future<bool> _wizzVerify(BuildContext context) async {
  if (WizzPrefs.lockHash.isEmpty) return true;
  final r = await Navigator.push<bool>(context,
      MaterialPageRoute(builder: (_) => const WizzLockPage(verifyOnly: true)));
  return r == true;
}

Future<String?> _wizzAskNewPin(BuildContext context) async {
  final a = TextEditingController(), b = TextEditingController();
  String err = '';
  return showDialog<String>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, setState) => AlertDialog(
        title: const Text('Set a PIN'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(
              controller: a,
              obscureText: true,
              keyboardType: TextInputType.number,
              maxLength: 8,
              decoration: const InputDecoration(labelText: 'New PIN (4-8 digits)')),
          TextField(
              controller: b,
              obscureText: true,
              keyboardType: TextInputType.number,
              maxLength: 8,
              decoration: InputDecoration(
                  labelText: 'Repeat PIN', errorText: err.isEmpty ? null : err)),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
          ElevatedButton(
              onPressed: () {
                if (!RegExp(r'^\d{4,8}$').hasMatch(a.text)) {
                  setState(() => err = 'Use 4 to 8 digits');
                } else if (a.text != b.text) {
                  setState(() => err = 'The PINs don\'t match');
                } else {
                  Navigator.pop(ctx, a.text);
                }
              },
              child: const Text('Save')),
        ],
      ),
    ),
  );
}

// ------------------------------------------------------------ settings UI
SettingsSection wizzSettingsSection(BuildContext context, void Function() refresh) {
  String lockLabel() {
    if (!WizzPrefs.lockOn) return 'Off';
    final a = WizzPrefs.lockAfter;
    return a <= 0 ? 'On · immediately' : 'On · after ${a ~/ 60} min';
  }

  return SettingsSection(title: const Text('Multiview'), tiles: [
    SettingsTile(
      title: const Text('App lock'),
      value: Text(lockLabel()),
      leading: const Icon(Icons.lock_outline),
      onPressed: (c) async {
        await Navigator.push(c, MaterialPageRoute(builder: (_) => const WizzLockSettingsPage()));
        refresh();
      },
    ),
    SettingsTile.switchTile(
      title: const Text('Swipe the toolbar to switch PC'),
      description: const Text('Swipe the bottom bar left or right for the next or previous PC'),
      leading: const Icon(Icons.swipe),
      initialValue: WizzPrefs.swipeSwitch,
      onToggle: (v) {
        WizzPrefs.swipeSwitch = v;
        refresh();
      },
    ),
    SettingsTile(
      title: const Text('Extra keys'),
      value: const Text('Favourites and transparency'),
      leading: const Icon(Icons.keyboard_outlined),
      onPressed: (c) => Navigator.push(c, MaterialPageRoute(builder: (_) => const WizzKeysSettingsPage())),
    ),
    SettingsTile(
      title: const Text('Session toolbar'),
      value: const Text('Buttons, colour, transparency'),
      leading: const Icon(Icons.view_week_outlined),
      onPressed: (c) => Navigator.push(c, MaterialPageRoute(builder: (_) => const WizzToolbarSettingsPage())),
    ),
    SettingsTile(
      title: const Text('Home screen tabs'),
      value: const Text('PCs, Chat, Share screen'),
      leading: const Icon(Icons.tab_outlined),
      onPressed: (c) => Navigator.push(c, MaterialPageRoute(builder: (_) => const WizzHomeTabsSettingsPage())),
    ),
    SettingsTile(
      title: const Text('File copy & paste'),
      value: const Text('Download bar, save folder, auto-delete'),
      leading: const Icon(Icons.file_copy_outlined),
      onPressed: (c) => Navigator.push(c, MaterialPageRoute(builder: (_) => const WizzFilesSettingsPage())),
    ),
  ]);
}

class WizzLockSettingsPage extends StatefulWidget {
  const WizzLockSettingsPage({Key? key}) : super(key: key);
  @override
  State<WizzLockSettingsPage> createState() => _WizzLockSettingsPageState();
}

class _WizzLockSettingsPageState extends State<WizzLockSettingsPage> {
  @override
  Widget build(BuildContext context) {
    const times = {0: 'Immediately', 60: 'After 1 minute', 300: 'After 5 minutes', 900: 'After 15 minutes'};
    return Scaffold(
      appBar: AppBar(title: const Text('App lock')),
      body: ListView(children: [
        SwitchListTile(
          title: const Text('Lock the app'),
          subtitle: const Text('Fingerprint, with your PIN as a backup'),
          value: WizzPrefs.lockOn,
          onChanged: (v) async {
            if (v) {
              final pin = await _wizzAskNewPin(context);
              if (pin == null) return;
              WizzPrefs.lockHash = wizzPinHash(pin);
              WizzPrefs.lockOn = true;
            } else {
              if (!await _wizzVerify(context)) return;
              WizzPrefs.lockOn = false;
            }
            setState(() {});
          },
        ),
        if (WizzPrefs.lockOn) ...[
          ListTile(
            title: const Text('Change PIN'),
            leading: const Icon(Icons.pin_outlined),
            onTap: () async {
              if (!await _wizzVerify(context)) return;
              final pin = await _wizzAskNewPin(context);
              if (pin == null) return;
              WizzPrefs.lockHash = wizzPinHash(pin);
              showToast('PIN changed');
            },
          ),
          const ListTile(title: Text('Lock again when away'), dense: true),
          for (final e in times.entries)
            RadioListTile<int>(
              title: Text(e.value),
              value: e.key,
              groupValue: WizzPrefs.lockAfter,
              onChanged: (v) => setState(() => WizzPrefs.lockAfter = v ?? 60),
            ),
          const Padding(
            padding: EdgeInsets.all(16),
            child: Text('Open PCs stay connected while the app is locked.'),
          ),
        ],
      ]),
    );
  }
}

class _WizzSlider extends StatelessWidget {
  final String title;
  final int value;
  final ValueChanged<int> onChanged;
  final String sample;
  const _WizzSlider(this.title, this.value, this.onChanged, this.sample);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('$title: $value% see-through'),
        Slider(
            value: value.toDouble(),
            min: 0,
            max: 100,
            divisions: 20,
            label: '$value%',
            onChanged: (v) => onChanged(v.round())),
        // preview over a light, busy background
        Container(
          height: 44,
          decoration: const BoxDecoration(
            gradient: LinearGradient(colors: [Colors.white, Colors.lightBlueAccent, Colors.amber]),
          ),
          alignment: Alignment.center,
          child: Container(
            margin: const EdgeInsets.symmetric(horizontal: 12),
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            decoration: BoxDecoration(
                color: wizzBarColor(value), borderRadius: BorderRadius.circular(8)),
            child: Text(sample,
                style: const TextStyle(color: Colors.white, shadows: kWizzTextOutline)),
          ),
        ),
      ]),
    );
  }
}

class WizzKeysSettingsPage extends StatefulWidget {
  const WizzKeysSettingsPage({Key? key}) : super(key: key);
  @override
  State<WizzKeysSettingsPage> createState() => _WizzKeysSettingsPageState();
}

class _WizzKeysSettingsPageState extends State<WizzKeysSettingsPage> {
  late List<String> _fav = WizzPrefs.favKeys;

  void _save() => WizzPrefs.favKeys = _fav;

  @override
  Widget build(BuildContext context) {
    final others = kWizzKeys.keys.where((k) => !_fav.contains(k)).toList();
    return Scaffold(
      appBar: AppBar(title: const Text('Extra keys')),
      body: ListView(children: [
        _WizzSlider('Background', WizzPrefs.keysSeeThrough,
            (v) => setState(() => WizzPrefs.keysSeeThrough = v), 'Ctrl+C   Esc   Enter'),
        const ListTile(
          title: Text('Favourite keys', style: TextStyle(fontWeight: FontWeight.bold)),
          subtitle: Text('Shown in the slim row. Drag to reorder, untick to remove. '
              'The ⋯ button shows all keys.'),
        ),
        ReorderableListView(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          onReorder: (a, b) => setState(() {
            if (b > a) b--;
            _fav.insert(b, _fav.removeAt(a));
            _save();
          }),
          children: [
            for (final k in _fav)
              CheckboxListTile(
                key: ValueKey(k),
                value: true,
                title: Text(kWizzKeys[k]!.label),
                secondary: const Icon(Icons.drag_handle),
                onChanged: (_) => setState(() {
                  _fav.remove(k);
                  _save();
                }),
              ),
          ],
        ),
        const Divider(),
        const ListTile(title: Text('More keys'), dense: true),
        for (final k in others)
          CheckboxListTile(
            value: false,
            title: Text(kWizzKeys[k]!.label),
            onChanged: (_) => setState(() {
              _fav.add(k);
              _save();
            }),
          ),
        TextButton(
            onPressed: () => setState(() {
                  _fav = List.of(kWizzDefaultKeys);
                  _save();
                }),
            child: const Text('Reset to default')),
      ]),
    );
  }
}

class WizzFilesSettingsPage extends StatefulWidget {
  const WizzFilesSettingsPage({Key? key}) : super(key: key);
  @override
  State<WizzFilesSettingsPage> createState() => _WizzFilesSettingsPageState();
}

class _WizzFilesSettingsPageState extends State<WizzFilesSettingsPage> {
  @override
  Widget build(BuildContext context) {
    const hides = {0: 'Off', 5: 'After 5 seconds', 10: 'After 10 seconds'};
    const deletes = {0: 'Never', 24: 'After 24 hours', 168: 'After 7 days'};
    return Scaffold(
      appBar: AppBar(title: const Text('File copy & paste')),
      body: ListView(children: [
        _WizzSlider('Download bar', WizzPrefs.barSeeThrough,
            (v) => setState(() => WizzPrefs.barSeeThrough = v), 'Downloading 36% · 436 MB'),
        SwitchListTile(
          title: const Text('Show the bar at the bottom'),
          value: WizzPrefs.barBottom,
          onChanged: (v) => setState(() => WizzPrefs.barBottom = v),
        ),
        const ListTile(title: Text('Hide the bar when a download is done'), dense: true),
        for (final e in hides.entries)
          RadioListTile<int>(
            title: Text(e.value),
            value: e.key,
            groupValue: WizzPrefs.autoHide,
            onChanged: (v) => setState(() => WizzPrefs.autoHide = v ?? 0),
          ),
        const Divider(),
        const ListTile(title: Text('Save downloads to'), dense: true),
        for (final e in kWizzFolders.entries)
          RadioListTile<String>(
            title: Text(e.value),
            value: e.key,
            groupValue: WizzPrefs.saveFolder,
            onChanged: (v) => setState(() => WizzPrefs.saveFolder = v ?? 'dl_rd'),
          ),
        RadioListTile<String>(
          title: Text(WizzPrefs.customTree.isEmpty
              ? 'Custom folder…'
              : 'Custom: ${WizzPrefs.customTreeName}'),
          subtitle: WizzPrefs.customTree.isEmpty ? null : const Text('Tap the folder icon to change'),
          secondary: IconButton(
              icon: const Icon(Icons.folder_open),
              onPressed: () async {
                if (await wizzPickCustomFolder()) {
                  setState(() => WizzPrefs.saveFolder = 'custom');
                }
              }),
          value: 'custom',
          groupValue: WizzPrefs.saveFolder,
          onChanged: (v) async {
            if (WizzPrefs.customTree.isEmpty && !await wizzPickCustomFolder()) return;
            setState(() => WizzPrefs.saveFolder = 'custom');
          },
        ),
        SwitchListTile(
          title: const Text('Ask where to save each time'),
          value: WizzPrefs.askEach,
          onChanged: (v) => setState(() => WizzPrefs.askEach = v),
        ),
        const Divider(),
        const ListTile(title: Text('Delete downloads automatically'), dense: true),
        for (final e in deletes.entries)
          RadioListTile<int>(
            title: Text(e.value),
            value: e.key,
            groupValue: WizzPrefs.autoDeleteHours,
            onChanged: (v) => setState(() => WizzPrefs.autoDeleteHours = v ?? 0),
          ),
        const Padding(
          padding: EdgeInsets.all(16),
          child: Text('Only files downloaded by this app are deleted.'),
        ),
      ]),
    );
  }
}

class WizzToolbarSettingsPage extends StatefulWidget {
  const WizzToolbarSettingsPage({Key? key}) : super(key: key);
  @override
  State<WizzToolbarSettingsPage> createState() => _WizzToolbarSettingsPageState();
}

class _WizzToolbarSettingsPageState extends State<WizzToolbarSettingsPage> {
  late List<String> _order = WizzPrefs.tbOrder;
  late List<String> _hidden = WizzPrefs.tbHidden;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Session toolbar')),
      body: ListView(children: [
        // preview of the bar
        Container(
          margin: const EdgeInsets.all(16),
          padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 8),
          decoration: BoxDecoration(
            gradient: WizzPrefs.tbFloat
                ? const LinearGradient(colors: [Colors.white, Colors.lightBlueAccent, Colors.amber])
                : null,
            color: WizzPrefs.tbFloat ? null : Colors.black,
            borderRadius: BorderRadius.circular(8),
          ),
          child: Container(
            padding: const EdgeInsets.symmetric(vertical: 8),
            color: wizzToolbarColor(),
            child: Row(mainAxisAlignment: MainAxisAlignment.spaceEvenly, children: [
              for (final id in _order)
                if (!_hidden.contains(id))
                  Icon(kWizzTbIcons[id], color: Colors.white, shadows: kWizzTextOutline),
              const Icon(Icons.more_vert, color: Colors.white, shadows: kWizzTextOutline),
            ]),
          ),
        ),
        const ListTile(
          title: Text('Buttons', style: TextStyle(fontWeight: FontWeight.bold)),
          subtitle: Text('Untick to move a button under ⋮. Drag to reorder.'),
        ),
        ReorderableListView(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          onReorder: (a, b) => setState(() {
            if (b > a) b--;
            _order.insert(b, _order.removeAt(a));
            WizzPrefs.tbOrder = _order;
          }),
          children: [
            for (final id in _order)
              CheckboxListTile(
                key: ValueKey(id),
                value: !_hidden.contains(id),
                title: Text(kWizzTbLabels[id] ?? id),
                secondary: Icon(kWizzTbIcons[id]),
                onChanged: (v) => setState(() {
                  if (v == true) {
                    _hidden.remove(id);
                  } else {
                    _hidden.add(id);
                  }
                  WizzPrefs.tbHidden = _hidden;
                }),
              ),
          ],
        ),
        const Divider(),
        const ListTile(title: Text('Colour'), dense: true),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Wrap(spacing: 12, runSpacing: 12, children: [
            for (final e in kWizzTbColors.entries)
              GestureDetector(
                onTap: () => setState(() => WizzPrefs.tbColor = e.key),
                child: Container(
                  width: 40,
                  height: 40,
                  decoration: BoxDecoration(
                    color: e.value,
                    shape: BoxShape.circle,
                    border: Border.all(
                        color: WizzPrefs.tbColor == e.key ? Colors.white : Colors.white24,
                        width: WizzPrefs.tbColor == e.key ? 3 : 1),
                  ),
                  child: WizzPrefs.tbColor == e.key
                      ? const Icon(Icons.check, color: Colors.white, shadows: kWizzTextOutline)
                      : null,
                ),
              ),
          ]),
        ),
        const SizedBox(height: 8),
        SwitchListTile(
          title: const Text('Float over the screen'),
          subtitle: const Text('The PC picture uses the full height; the bar sits on top'),
          value: WizzPrefs.tbFloat,
          onChanged: (v) => setState(() => WizzPrefs.tbFloat = v),
        ),
        if (WizzPrefs.tbFloat)
          _WizzSlider('Toolbar', WizzPrefs.tbSeeThrough,
              (v) => setState(() => WizzPrefs.tbSeeThrough = v), '✕   🖵   ⧉   ⌨   ⋮'),
        TextButton(
            onPressed: () => setState(() {
                  _order = List.of(kWizzTbDefault);
                  _hidden = [];
                  WizzPrefs.tbOrder = _order;
                  WizzPrefs.tbHidden = _hidden;
                  WizzPrefs.tbColor = 'blue';
                  WizzPrefs.tbFloat = false;
                }),
            child: const Text('Reset to default')),
        const Padding(
          padding: EdgeInsets.all(16),
          child: Text('Changes show the next time the toolbar is drawn (tap the screen or switch PC).'),
        ),
      ]),
    );
  }
}

class WizzHomeTabsSettingsPage extends StatefulWidget {
  const WizzHomeTabsSettingsPage({Key? key}) : super(key: key);
  @override
  State<WizzHomeTabsSettingsPage> createState() => _WizzHomeTabsSettingsPageState();
}

class _WizzHomeTabsSettingsPageState extends State<WizzHomeTabsSettingsPage> {
  void _changed() {
    setState(() {});
    wizzHomeRev.value++;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Home screen tabs')),
      body: ListView(children: [
        const SwitchListTile(
            title: Text('Connection'), value: true, onChanged: null),
        SwitchListTile(
          title: const Text('PCs'),
          subtitle: const Text('Shown while PCs are open: tap to go back, hold for previews'),
          value: WizzPrefs.homePcs,
          onChanged: (v) {
            WizzPrefs.homePcs = v;
            _changed();
          },
        ),
        SwitchListTile(
          title: const Text('Chat'),
          value: WizzPrefs.homeChat,
          onChanged: (v) {
            WizzPrefs.homeChat = v;
            _changed();
          },
        ),
        SwitchListTile(
          title: const Text('Share screen'),
          subtitle: const Text('Hiding the tab does not change any security setting'),
          value: WizzPrefs.homeShare,
          onChanged: (v) {
            WizzPrefs.homeShare = v;
            _changed();
          },
        ),
        const SwitchListTile(
            title: Text('Settings'), value: true, onChanged: null),
      ]),
    );
  }
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
      if (!mounted) return;
      if (!widget.active) {
        _wizzBackground(true);
        return;
      }
      // a PC opened after something was copied elsewhere: offer it here too
      Future.delayed(const Duration(milliseconds: 500), () async {
        if (!mounted || !widget.active) return;
        await wizzTakeSharedFiles();
        final code = _wizzClipCall('wizz-clip-offer');
        if (code == '1') {
          showToast('Copied files are ready here: paste with Ctrl+V');
        } else if (code == '0') {
          _ffi.invokeMethod("wizz_force_sync_clipboard");
        }
      });
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
        color: Colors.black.withOpacity(0.40),
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

# ===== Wizz: settings (app lock, favourite keys, file copy & paste) =====
save('flutter/lib/mobile/pages/wizz_settings.dart', WIZZ_SETTINGS_DART)

p = 'flutter/lib/mobile/pages/settings_page.dart'
s = load(p)
s = rep(s, "import 'scan_page.dart';\n", "import 'scan_page.dart';\nimport 'wizz_settings.dart';\n")
s = rep(s, "        customClientSection,\n", "        customClientSection,\n        wizzSettingsSection(context, () => setState(() {})),\n")
save(p, s)

p = 'flutter/lib/mobile/pages/home_page.dart'
s = load(p)
s = rep(s, "import 'connection_page.dart';\n", "import 'connection_page.dart';\nimport 'wizz_settings.dart';\n")
s = rep(s, "    super.initState();\n    initPages();\n", "    super.initState();\n    initPages();\n    WizzLock.to.start();\n")
save(p, s)

p = 'flutter/lib/mobile/pages/remote_page.dart'
s = load(p)
s = rep(s, "import 'wizz_sessions.dart';\n", "import 'wizz_sessions.dart';\nimport 'wizz_settings.dart';\n")

# -- compact extra keys row: favourites + "⋯" to show everything
s = rep(s, "  var _pin = false;\n  final _keyboardVisibilityController", "  var _pin = false;\n  var _wizzAll = false;\n  final _keyboardVisibilityController")
s = rep(s, "            ? Icon(icon, size: 14, color: Colors.white)\n            : Text(translate(text),\n                style: TextStyle(color: Colors.white, fontSize: 11)),",
        "            ? Icon(icon, size: 14, color: Colors.white, shadows: kWizzTextOutline)\n            : Text(translate(text),\n                style: TextStyle(color: Colors.white, fontSize: 11, shadows: kWizzTextOutline)),")
s = rep(s, "        color: Color(0xAA000000),\n        padding: EdgeInsets.only(\n            top: _keyboardVisibilityController.isVisible ? 24 : 4, bottom: 8),",
        "        color: wizzBarColor(WizzPrefs.keysSeeThrough),\n        padding: EdgeInsets.only(\n            top: _keyboardVisibilityController.isVisible ? 24 : 4, bottom: 8),")
s = rep(s, """          children: <Widget>[SizedBox(width: 9999)] +
              modifiers +
              keys +
              (_fn ? fn : []) +
              (_more ? more : []),""", """          children: _wizzAll
              ? <Widget>[SizedBox(width: 9999)] +
                  modifiers +
                  keys +
                  [
                    wrap('', () => setState(() => _wizzAll = false),
                        icon: Icons.unfold_less)
                  ] +
                  (_fn ? fn : []) +
                  (_more ? more : [])
              : <Widget>[SizedBox(width: 9999)] +
                  _wizzFavs(isMac) +
                  [
                    wrap('', () => setState(() => _pin = !_pin),
                        active: _pin, icon: Icons.push_pin),
                    wrap(' ⋯ ', () => setState(() => _wizzAll = true)),
                  ],""")
s = rep(s, "  _updateRect() {\n    RenderObject? renderObject = _key.currentContext?.findRenderObject();",
        """  List<Widget> _wizzFavs(bool isMac) {
    final out = <Widget>[];
    for (final id in WizzPrefs.favKeys) {
      final k = kWizzKeys[id];
      if (k == null) continue;
      bool? on;
      switch (id) {
        case 'ctrl':
          on = inputModel.ctrl;
          break;
        case 'alt':
          on = inputModel.alt;
          break;
        case 'shift':
          on = inputModel.shift;
          break;
        case 'win':
          on = inputModel.command;
          break;
      }
      out.add(wrap(k.icon != null ? '' : k.label,
          () => setState(() => k.run(_ffi, isMac)),
          active: on, icon: k.icon));
    }
    return out;
  }

  _updateRect() {
    RenderObject? renderObject = _key.currentContext?.findRenderObject();""")

# -- download: pick the folder (saved setting or ask), custom folders via Android
i = s.index("  Future<void> _wizzClipDownload() async {")
j = s.index("  String _wizzSize(num b) {", i)
s = s[:i] + r"""  WizzSaveTarget? _wizzTarget;
  int _wizzDoneSeq = -1;
  bool _wizzTreeBusy = false;
  List<String> _wizzTreeUris = const [];
  Timer? _wizzHideTimer;
  int _wizzHideSeq = -1;

  Future<void> _wizzClipDownload() async {
    final t = await wizzChooseSaveTarget(context);
    if (t == null || !mounted) return;
    _wizzTarget = t;
    _wizzTreeUris = const [];
    var fallback = '';
    try {
      final d = await getExternalStorageDirectory();
      if (d != null) fallback = '${d.path}/RustDesk';
    } catch (_) {}
    _wizzClipCall('wizz-clip-download', '${t.path}\n$fallback');
    _wizzClipPoll();
  }

  bool get _wizzToTree => (_wizzTarget?.tree ?? '').isNotEmpty;

  // a download finished: copy into a custom folder, remember it for auto-delete
  Future<void> _wizzOnDone(Map<String, dynamic> m) async {
    final seq = (m['seq'] ?? 0) as int;
    if ((m['state'] ?? '') != 'done' || seq == _wizzDoneSeq) return;
    _wizzDoneSeq = seq;
    final saved = ((m['saved'] ?? []) as List).map((e) => e.toString()).toList();
    wizzRememberDownload(saved);
    if (_wizzToTree) {
      setState(() => _wizzTreeBusy = true);
      final r = await _ffi.invokeMethodWithResult<List<dynamic>>(
          'wizz_tree_copy', {'tree': _wizzTarget!.tree, 'paths': saved});
      final uris = (r ?? []).map((e) => e.toString()).toList();
      wizzRememberDownload(uris, uris: true);
      if (!mounted) return;
      setState(() {
        _wizzTreeBusy = false;
        _wizzTreeUris = uris;
      });
      if (uris.isEmpty) showToast('Could not save to ${_wizzTarget!.label}');
    }
  }

  Widget _wizzAct(String label, void Function() onPressed) => TextButton(
      onPressed: onPressed,
      child: Text(label,
          style: const TextStyle(
              fontWeight: FontWeight.bold, shadows: kWizzTextOutline)));

  Future<void> _wizzConfirmDelete(String what) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text('Delete $what from the phone?'),
        content: const Text("This can't be undone."),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(c, false),
              child: const Text('Cancel')),
          TextButton(
              onPressed: () => Navigator.pop(c, true),
              child: const Text('Delete', style: TextStyle(color: Colors.red))),
        ],
      ),
    );
    if (ok != true) return;
    if (_wizzToTree && _wizzTreeUris.isNotEmpty) {
      await _ffi.invokeMethodWithResult('wizz_tree_delete', _wizzTreeUris);
      _wizzTreeUris = const [];
    }
    _wizzClipCall('wizz-clip-delete');
    showToast('Deleted from the phone');
    _wizzClipPoll();
  }

""" + s[j:]

# poll hook
s = rep(s, "        setState(() => _wizzClip = m);\n        _wizzNotify(m);\n",
        "        setState(() => _wizzClip = m);\n        _wizzNotify(m);\n        _wizzOnDone(m);\n")
# notification text for custom folders
s = rep(s, """          'text': 'Saved to $dir · tap to open',
          'progress': 100,
          'path': single ? saved.first.toString() : '',""", """          'text': _wizzToTree
              ? 'Saved to ${_wizzTarget!.label}'
              : 'Saved to $dir · tap to open',
          'progress': 100,
          'path': single && !_wizzToTree ? saved.first.toString() : '',""")
s = rep(s, "    _wizzClipTimer?.cancel();\n", "    _wizzClipTimer?.cancel();\n    _wizzHideTimer?.cancel();\n")

# the bar itself: transparency, position, auto-hide, delete confirmation
i = s.index("  Widget _wizzClipBanner() {")
j = s.index("  // Background PCs: clipboard off", i)
s = s[:i] + r"""  Widget _wizzClipBanner() {
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
    final what =
        count == 1 && names.isNotEmpty ? names.first.toString() : '$count items';
    final dir = (_wizzClip['dir'] ?? '')
        .toString()
        .replaceFirst('/storage/emulated/0/', '');
    final msg = (_wizzClip['msg'] ?? '').toString();
    String text;
    double? progress;
    final actions = <Widget>[];
    switch (st) {
      case 'offered':
        text = 'Copied on PC: $what (${_wizzSize(bytes)})';
        actions.add(_wizzAct('Download', _wizzClipDownload));
        break;
      case 'downloading':
        final pv = bytes > 0 ? (done / bytes).clamp(0.0, 1.0).toDouble() : 0.0;
        progress = bytes > 0 ? pv : null;
        final pct = bytes > 0 ? '${(pv * 100).toStringAsFixed(0)}% · ' : '';
        text = 'Downloading $pct${_wizzSize(done)} / ${_wizzSize(bytes)}';
        actions.add(_wizzAct('Cancel', () => _wizzClipCall('wizz-clip-cancel')));
        break;
      case 'done':
        final saved = ((_wizzClip['saved'] ?? []) as List).cast<dynamic>();
        final single = msg == 'single' && saved.length == 1;
        if (_wizzToTree && _wizzTreeBusy) {
          text = 'Saving to ${_wizzTarget!.label}…';
          progress = null;
          break;
        }
        if (_wizzToTree) {
          text = 'Saved to ${_wizzTarget!.label}';
          actions.add(_wizzAct(single ? 'Open' : 'Show', () {
            if (single && _wizzTreeUris.length == 1) {
              _ffi.invokeMethod("wizz_open_uri", _wizzTreeUris.first);
            } else {
              _ffi.invokeMethod("wizz_open_uri", _wizzTarget!.tree);
            }
          }));
        } else {
          text = 'Saved to $dir';
          actions.add(_wizzAct(single ? 'Open' : 'Show', () {
            if (single) {
              _ffi.invokeMethod("wizz_open_file", saved.first.toString());
            } else {
              _ffi.invokeMethod("wizz_show_downloads");
            }
          }));
        }
        actions.add(_wizzAct('Delete', () => _wizzConfirmDelete(what)));
        final hide = WizzPrefs.autoHide;
        if (hide > 0 && _wizzHideSeq != seq) {
          _wizzHideSeq = seq;
          _wizzHideTimer?.cancel();
          _wizzHideTimer = Timer(Duration(seconds: hide), () {
            if (!mounted) return;
            setState(() {
              _wizzClipHiddenSeq = seq;
              _wizzClipHiddenState = 'done';
            });
          });
        }
        break;
      default:
        text = 'Download failed: $msg';
    }
    final atBottom = WizzPrefs.barBottom;
    return Positioned(
      top: atBottom ? null : 8,
      bottom: atBottom ? 8 : null,
      left: 8,
      right: 8,
      child: Material(
        color: wizzBarColor(WizzPrefs.barSeeThrough),
        borderRadius: BorderRadius.circular(10),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 4, 4, 4),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                children: [
                  const Icon(Icons.file_copy,
                      color: Colors.white, size: 18, shadows: kWizzTextOutline),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(text,
                        style: const TextStyle(
                            color: Colors.white, shadows: kWizzTextOutline),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis),
                  ),
                  ...actions,
                  IconButton(
                    icon: const Icon(Icons.close,
                        color: Colors.white, shadows: kWizzTextOutline),
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
              if (st == 'downloading' || (st == 'done' && _wizzTreeBusy))
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

""" + s[j:]
save(p, s)

# -- Android: fingerprint, custom folders
save(kt + 'WizzLock.kt', """package com.carriez.flutter_hbb

import android.annotation.TargetApi
import android.app.Activity
import android.content.Context
import android.hardware.biometrics.BiometricPrompt
import android.net.Uri
import android.os.CancellationSignal
import android.provider.DocumentsContract
import android.util.Log
import android.webkit.MimeTypeMap
import java.io.File

object WizzLock {
    @TargetApi(28)
    fun biometric(activity: Activity, done: (Boolean) -> Unit) {
        var replied = false
        val reply = { ok: Boolean ->
            if (!replied) {
                replied = true
                done(ok)
            }
        }
        try {
            val ex = activity.mainExecutor
            val prompt = BiometricPrompt.Builder(activity)
                .setTitle("Unlock RustDesk Multiview")
                .setNegativeButton("Use PIN", ex) { _, _ -> reply(false) }
                .build()
            prompt.authenticate(CancellationSignal(), ex,
                object : BiometricPrompt.AuthenticationCallback() {
                    override fun onAuthenticationSucceeded(r: BiometricPrompt.AuthenticationResult?) {
                        reply(true)
                    }

                    override fun onAuthenticationError(code: Int, msg: CharSequence?) {
                        reply(false)
                    }
                })
        } catch (e: Exception) {
            Log.e("Wizz", "biometric: $e")
            reply(false)
        }
    }

    fun treeName(uri: Uri): String {
        return try {
            val id = DocumentsContract.getTreeDocumentId(uri)
            val rel = id.substringAfter(':', "")
            if (rel.isEmpty()) "Phone storage" else rel
        } catch (e: Exception) {
            "Custom folder"
        }
    }

    private fun mimeOf(f: File): String =
        MimeTypeMap.getSingleton().getMimeTypeFromExtension(f.extension.lowercase())
            ?: "application/octet-stream"

    private fun copyInto(ctx: Context, parent: Uri, f: File): Uri? {
        val cr = ctx.contentResolver
        if (f.isDirectory) {
            val d = DocumentsContract.createDocument(cr, parent,
                DocumentsContract.Document.MIME_TYPE_DIR, f.name) ?: return null
            f.listFiles()?.forEach { copyInto(ctx, d, it) }
            return d
        }
        val u = DocumentsContract.createDocument(cr, parent, mimeOf(f), f.name) ?: return null
        cr.openOutputStream(u)?.use { out -> f.inputStream().use { it.copyTo(out, 1 shl 20) } }
        return u
    }

    /** Copies downloaded files into a folder the user picked; returns the new items. */
    fun copyToTree(ctx: Context, tree: String, paths: List<String>): List<String> {
        val out = mutableListOf<String>()
        try {
            val t = Uri.parse(tree)
            val root = DocumentsContract.buildDocumentUriUsingTree(t,
                DocumentsContract.getTreeDocumentId(t))
            for (p in paths) {
                try {
                    copyInto(ctx, root, File(p))?.let { out.add(it.toString()) }
                } catch (e: Exception) {
                    Log.e("Wizz", "tree copy $p: $e")
                }
            }
        } catch (e: Exception) {
            Log.e("Wizz", "tree copy: $e")
        }
        return out
    }

    fun deleteUris(ctx: Context, uris: List<String>) {
        for (u in uris) {
            try {
                DocumentsContract.deleteDocument(ctx.contentResolver, Uri.parse(u))
            } catch (e: Exception) {
                Log.e("Wizz", "tree delete: $e")
            }
        }
    }
}
""")

p = kt + 'MainActivity.kt'
s = load(p)
s = rep(s, "    private var wizzPickResult: MethodChannel.Result? = null\n",
        "    private var wizzPickResult: MethodChannel.Result? = null\n    private var wizzTreeResult: MethodChannel.Result? = null\n")
s = rep(s, "        if (requestCode == 7310) {\n", """        if (requestCode == 7311) {
            val r = wizzTreeResult ?: return
            wizzTreeResult = null
            val uri = data?.data
            if (resultCode != Activity.RESULT_OK || uri == null) {
                r.success(null)
                return
            }
            try {
                contentResolver.takePersistableUriPermission(uri,
                    Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
            } catch (e: Exception) {
                Log.e("Wizz", "tree permission: $e")
            }
            r.success(mapOf("uri" to uri.toString(), "name" to WizzLock.treeName(uri)))
            return
        }
        if (requestCode == 7310) {
""")
s = rep(s, '                "wizz_take_shared" -> ', """                "wizz_biometric" -> {
                    if (Build.VERSION.SDK_INT < 28) {
                        result.success(false)
                    } else {
                        WizzLock.biometric(this) { ok -> result.success(ok) }
                    }
                }
                "wizz_pick_tree" -> {
                    wizzTreeResult = result
                    try {
                        startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT_TREE)
                            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or
                                Intent.FLAG_GRANT_WRITE_URI_PERMISSION or
                                Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION), 7311)
                    } catch (e: Exception) {
                        wizzTreeResult = null
                        result.success(null)
                    }
                }
                "wizz_tree_copy" -> {
                    val a = call.arguments as Map<*, *>
                    val tree = a["tree"] as String
                    val paths = (a["paths"] as List<*>).map { it.toString() }
                    thread {
                        val out = WizzLock.copyToTree(this, tree, paths)
                        runOnUiThread { result.success(out) }
                    }
                }
                "wizz_tree_delete" -> {
                    val uris = (call.arguments as List<*>).map { it.toString() }
                    thread {
                        WizzLock.deleteUris(this, uris)
                        runOnUiThread { result.success(true) }
                    }
                }
                "wizz_open_uri" -> {
                    try {
                        var uri = Uri.parse(call.arguments as String)
                        var mime = contentResolver.getType(uri)
                        if (uri.pathSegments.size == 2 && uri.pathSegments[0] == "tree") {
                            uri = DocumentsContract.buildDocumentUriUsingTree(uri,
                                DocumentsContract.getTreeDocumentId(uri))
                            mime = DocumentsContract.Document.MIME_TYPE_DIR
                        }
                        val i = Intent(Intent.ACTION_VIEW).setDataAndType(uri, mime ?: "*/*")
                            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
                        startActivity(Intent.createChooser(i, null).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                        result.success(true)
                    } catch (e: Exception) {
                        Log.e("Wizz", "open uri: $e")
                        try {
                            startActivity(Intent(android.app.DownloadManager.ACTION_VIEW_DOWNLOADS)
                                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                        } catch (e2: Exception) {
                        }
                        result.success(false)
                    }
                }
                "wizz_take_shared" -> """)
save(p, s)

p = 'flutter/android/app/src/main/AndroidManifest.xml'
s = load(p)
s = rep(s, '    <uses-permission android:name="android.permission.MANAGE_EXTERNAL_STORAGE" tools:node="remove" />\n',
        '    <uses-permission android:name="android.permission.MANAGE_EXTERNAL_STORAGE" tools:node="remove" />\n    <uses-permission android:name="android.permission.USE_BIOMETRIC" />\n')
save(p, s)

# ===== Wizz: hold the sessions button for live previews; optional toolbar swipe =====
save('flutter/lib/mobile/pages/wizz_switcher.dart', WIZZ_SWITCHER_DART)
p = 'flutter/lib/mobile/pages/remote_page.dart'
s = load(p)
s = rep(s, "import 'wizz_settings.dart';\n", "import 'wizz_settings.dart';\nimport 'wizz_switcher.dart';\n")
s = rep(s, """                    IconButton(
                      color: Colors.white,
                      icon: wizzSessionsIcon(),
                      onPressed: () {
                        setState(() => _showEdit = false);
                        showWizzSessionsMenu(context);
                      },
                    ),
""", """                    WizzSessionsButton(onTap: () {
                      setState(() => _showEdit = false);
                      showWizzSessionsMenu(context);
                    }),
""")
s = rep(s, "? getBottomAppBar()", "? wizzSwipeSwitch(getBottomAppBar())")
save(p, s)

# ===== Wizz: minimize, PCs tab, live previews in the list, X menu, custom toolbar & home tabs =====
p = 'flutter/lib/mobile/pages/wizz_sessions.dart'
s = load(p)
s = rep(s, "  final RxInt current = 0.obs;\n", "  final RxInt current = 0.obs;\n  // the home screen is showing on top of the open PCs\n  final RxBool minimized = false.obs;\n")
s = rep(s, "  return i != m.current.value;\n}", "  return i != m.current.value || m.minimized.value;\n}")
s = rep(s, """Widget wizzSessionsIcon() {
  return Obx(() {
    final n = WizzSessions.to.sessions.length;
    final icon = Icon(Icons.filter_none, color: Colors.white);
    if (n <= 1) return icon;
    return Badge(label: Text('$n'), child: icon);
  });
}""", """Widget wizzSessionsIcon({Color? color = Colors.white}) {
  return Obx(() {
    final list = WizzSessions.to.sessions;
    final n = list.length;
    final dropped = list.any((s) => s.dropped.value);
    final icon = Icon(Icons.filter_none, color: color);
    if (n <= 1 && !dropped) return icon;
    return Badge(
        label: Text(dropped ? '!' : '$n'),
        backgroundColor: dropped ? Colors.red : const Color(0xFF424242),
        child: icon);
  });
}""")
s = rep(s, """    m.add(id,
        loginMethod: loginMethod,
        password: password,
        isSharedPassword: isSharedPassword,
        forceRelay: forceRelay);
    return;
  }""", """    m.add(id,
        loginMethod: loginMethod,
        password: password,
        isSharedPassword: isSharedPassword,
        forceRelay: forceRelay);
    wizzReturnToSessions();
    return;
  }""")
s = rep(s, "class _WizzRemoteHostState extends State<WizzRemoteHost> {", "class _WizzRemoteHostState extends State<WizzRemoteHost>\n    with WidgetsBindingObserver {")
s = rep(s, "    m.hostMounted = true;\n    // Android keeps", "    m.hostMounted = true;\n    WidgetsBinding.instance.addObserver(this);\n    // Android keeps")
s = rep(s, "  void dispose() {\n    _keepAlive?.dispose();\n", """  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) wizzTakeNotificationAction();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    wizzResetMinimized();
    _keepAlive?.dispose();
""")
s = rep(s, "    return Obx(() {\n      final list = m.sessions.toList();\n      final cur = m.current.value.clamp(0, list.isEmpty ? 0 : list.length - 1);\n",
        "    return Obx(() {\n      final list = m.sessions.toList();\n      final cur = m.current.value.clamp(0, list.isEmpty ? 0 : list.length - 1);\n      final mini = m.minimized.value;\n")
s = rep(s, "                active: i == cur,\n", "                active: i == cur && !mini,\n")
s = rep(s, "import 'remote_page.dart';\n", "import 'remote_page.dart';\nimport 'wizz_switcher.dart';\n")
save(p, s)

p = 'flutter/lib/mobile/pages/remote_page.dart'
s = load(p)
# back = keep the PCs in the background
s = rep(s, """          ? () async {
              clientClose(sessionId, _ffi);
              return false;
            }""", """          ? () async {
              if (WizzSessions.to.hostMounted) {
                wizzMinimize();
              } else {
                clientClose(sessionId, _ffi);
              }
              return false;
            }""")
# float over the screen
s = rep(s, "      child: Scaffold(\n          // workaround for https://github.com/rustdesk/rustdesk/issues/3131\n",
        "      child: Scaffold(\n          extendBody: WizzPrefs.tbFloat,\n          // workaround for https://github.com/rustdesk/rustdesk/issues/3131\n")
s = rep(s, "                        : SafeArea(\n                            child:\n                                OrientationBuilder(",
        "                        : SafeArea(\n                            bottom: !WizzPrefs.tbFloat,\n                            child:\n                                OrientationBuilder(")
s = rep(s, "    return BottomAppBar(\n      elevation: 10,\n      color: MyTheme.accent,\n      child: Row(",
        "    return BottomAppBar(\n      elevation: WizzPrefs.tbFloat ? 0 : 10,\n      color: wizzToolbarColor(),\n      child: IconTheme.merge(\n      data: const IconThemeData(shadows: kWizzTextOutline),\n      child: Row(")
s = rep(s, "              )),\n        ],\n      ),\n    );\n  }\n\n  bool get showCursorPaint",
        "              )),\n        ],\n      )),\n    );\n  }\n\n  bool get showCursorPaint")
# buttons with ids
s = rep(s, """              child: Row(
              children: <Widget>[
                    IconButton(
                      color: Colors.white,
                      icon: Icon(Icons.clear),
                      onPressed: () {
                        clientClose(sessionId, _ffi);
                      },
                    ),
                    IconButton(
                      color: Colors.white,
                      icon: Icon(Icons.tv),
                      onPressed: () {
                        setState(() => _showEdit = false);
                        showOptions(context, widget.id, _ffi.dialogManager,
                            ffiOverride: _ffi);
                      },
                    ),
                    WizzSessionsButton(onTap: () {
                      setState(() => _showEdit = false);
                      showWizzSessionsMenu(context);
                    }),
""", """              child: Row(
              children: wizzArrange(context, () {
                        setState(() => _showEdit = false);
                        showActions(widget.id);
                      }, <Widget>[
                    wizzTb('close', IconButton(
                      color: Colors.white,
                      icon: Icon(Icons.clear),
                      onPressed: () => wizzCloseTapped(
                          context, () => clientClose(sessionId, _ffi)),
                    )),
                    wizzTb('display', IconButton(
                      color: Colors.white,
                      icon: Icon(Icons.tv),
                      onPressed: () {
                        setState(() => _showEdit = false);
                        showOptions(context, widget.id, _ffi.dialogManager,
                            ffiOverride: _ffi);
                      },
                    )),
                    wizzTb('pcs', WizzSessionsButton(onTap: () {
                      setState(() => _showEdit = false);
                      showWizzSessionsMenu(context);
                    })),
                    wizzTb('minimize', IconButton(
                      color: Colors.white,
                      icon: const Icon(Icons.minimize),
                      onPressed: wizzMinimize,
                    )),
""")
s = rep(s, """                              IconButton(
                                  color: Colors.white,
                                  icon: Icon(Icons.keyboard),
                                  onPressed: openKeyboard),""", """                              wizzTb('keyboard', IconButton(
                                  color: Colors.white,
                                  icon: Icon(Icons.keyboard),
                                  onPressed: openKeyboard)),""", count=2)
s = rep(s, """                              IconButton(
                                color: Colors.white,
                                icon: const Icon(Icons.build),
                                onPressed: () => _ffi.dialogManager
                                    .toggleMobileActionsOverlay(ffi: _ffi),
                              )""", """                              wizzTb('touch', IconButton(
                                color: Colors.white,
                                icon: const Icon(Icons.build),
                                onPressed: () => _ffi.dialogManager
                                    .toggleMobileActionsOverlay(ffi: _ffi),
                              ))""")
s = rep(s, """                              IconButton(
                                color: Colors.white,
                                icon: Icon(_ffi.ffiModel.touchMode
                                    ? Icons.touch_app
                                    : Icons.mouse),
                                onPressed: () => setState(
                                    () => _showGestureHelp = !_showGestureHelp),
                              ),""", """                              wizzTb('touch', IconButton(
                                color: Colors.white,
                                icon: Icon(_ffi.ffiModel.touchMode
                                    ? Icons.touch_app
                                    : Icons.mouse),
                                onPressed: () => setState(
                                    () => _showGestureHelp = !_showGestureHelp),
                              )),""")
s = rep(s, """                          futureBuilder(
                              future: _ffi.invokeMethod(
                                  "get_value", "KEY_IS_SUPPORT_VOICE_CALL"),""", """                          wizzTb('chat', futureBuilder(
                              future: _ffi.invokeMethod(
                                  "get_value", "KEY_IS_SUPPORT_VOICE_CALL"),""")
s = rep(s, """                                  ))
                        ]) +""", """                                  )))
                        ]) +""")
s = rep(s, """                    IconButton(
                      color: Colors.white,
                      icon: Icon(Icons.more_vert),
                      onPressed: () {
                        setState(() => _showEdit = false);
                        showActions(widget.id);
                      },
                    ),
                  ]),""", """                    wizzTb('more', IconButton(
                      color: Colors.white,
                      icon: Icon(Icons.more_vert),
                      onPressed: () {
                        setState(() => _showEdit = false);
                        showActions(widget.id);
                      },
                    )),
                  ])),""")
save(p, s)

p = 'flutter/lib/mobile/pages/home_page.dart'
s = load(p)
s = rep(s, "import 'wizz_settings.dart';\n", "import 'wizz_settings.dart';\nimport 'wizz_switcher.dart';\n")
s = rep(s, "  HomePage() : super(key: homeKey);\n",
        "  /// A second home screen shown on top of the open PCs (minimized).\n  final bool wizzMini;\n\n  HomePage({this.wizzMini = false}) : super(key: wizzMini ? null : homeKey);\n")
s = rep(s, """  void refreshPages() {
    setState(() {
      initPages();
    });
  }
""", """  void refreshPages() {
    final wasSettings = _selectedIndex < _pages.length &&
        _pages[_selectedIndex] is SettingsPage;
    setState(() {
      initPages();
      if (wasSettings || _selectedIndex >= _pages.length) {
        _selectedIndex = _pages.length - 1;
      }
    });
  }

  Worker? _wizzRev;

  @override
  void dispose() {
    _wizzRev?.dispose();
    super.dispose();
  }
""")
s = rep(s, "    initPages();\n    WizzLock.to.start();\n",
        "    initPages();\n    WizzLock.to.start();\n    _wizzRev = ever(wizzHomeRev, (_) {\n      if (mounted) refreshPages();\n    });\n")
s = rep(s, "    _pages.clear();\n", "    _pages.clear();\n    _chatPageTabIndex = -1;\n")
s = rep(s, """    if (isAndroid && !bind.isOutgoingOnly()) {
      _chatPageTabIndex = _pages.length;
      _pages.addAll([ChatPage(type: ChatPageType.mobileMain), ServerPage()]);
    }""", """    if (widget.wizzMini && WizzPrefs.homePcs) {
      _pages.add(WizzPcsTab());
    }
    if (isAndroid && !bind.isOutgoingOnly()) {
      if (WizzPrefs.homeChat) {
        _chatPageTabIndex = _pages.length;
        _pages.add(ChatPage(type: ChatPageType.mobileMain));
      }
      if (WizzPrefs.homeShare) _pages.add(ServerPage());
    }""")
s = rep(s, "            key: navigationBarKey,\n", "            key: widget.wizzMini ? null : navigationBarKey,\n")
s = rep(s, "            onTap: (index) => setState(() {\n", "            onTap: (index) {\n              if (_pages[index] is WizzPcsTab) {\n                wizzReturnToSessions();\n                return;\n              }\n              setState(() {\n")
s = rep(s, """                }
              }
            }),
          ),
          body: _pages.elementAt(_selectedIndex),""", """                }
              }
            });
            },
          ),
          body: _pages.elementAt(_selectedIndex),""")
save(p, s)

p = 'flutter/lib/common/widgets/peer_card.dart'
s = load(p)
s = rep(s, "import '../../common.dart';\n", "import '../../common.dart';\nimport '../../mobile/pages/wizz_switcher.dart';\n")
s = rep(s, """                getPlatformImage(peer.platform, size: isPortrait ? 38 : 30)
                    .paddingAll(6),""", """                wizzPeerTile(
                    peer.id,
                    isPortrait ? 50 : 42,
                    getPlatformImage(peer.platform, size: isPortrait ? 38 : 30)
                        .paddingAll(6)),""")
save(p, s)

p = 'flutter/lib/mobile/pages/settings_page.dart'
s = load(p)
s = rep(s, '                  title: Text(translate("Fingerprint")),', "                  title: Text('Device key fingerprint'),")
save(p, s)

# notification: tap returns to the PCs, "Disconnect all" button
p = kt + 'WizzKeepAliveService.kt'
s = load(p)
s = rep(s, "Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),",
        "Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)\n                .putExtra(\"wizz_action\", \"return\"),")
s = rep(s, "        val builder = if", """        val closeAll = PendingIntent.getActivity(
            this, 1,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
                .putExtra("wizz_action", "closeall"),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val builder = if""")
s = rep(s, "        val notification = builder\n", "        @Suppress(\"DEPRECATION\")\n        val notification = builder\n")
s = rep(s, "            .setContentIntent(open)\n", "            .setContentIntent(open)\n            .addAction(0, \"Disconnect all\", closeAll)\n")
save(p, s)

p = kt + 'MainActivity.kt'
s = load(p)
s = rep(s, "    private var wizzTreeResult: MethodChannel.Result? = null\n", """    private var wizzTreeResult: MethodChannel.Result? = null
    private var wizzAction = ""

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        intent.getStringExtra("wizz_action")?.let { wizzAction = it }
    }
""")
s = rep(s, "    override fun onCreate(savedInstanceState: Bundle?) {\n        super.onCreate(savedInstanceState)\n",
        "    override fun onCreate(savedInstanceState: Bundle?) {\n        super.onCreate(savedInstanceState)\n        intent?.getStringExtra(\"wizz_action\")?.let { wizzAction = it }\n")
s = rep(s, '                "wizz_take_shared" -> ', """                "wizz_take_action" -> {
                    result.success(wizzAction)
                    wizzAction = ""
                }
                "wizz_take_shared" -> """)
save(p, s)

print('wizz multi-session patch applied')
