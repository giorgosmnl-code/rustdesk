WIZZ_FILE_CLIP_RS = r'''// Wizz: file copy & paste for the Android client.
//
// PC -> phone: a PC announces copied files (FileGroupDescriptorW), we fetch the
// list and the user can download them into the phone's Download folder.
// Phone -> PC (and so PC -> PC): the downloaded files become the phone's
// "clipboard files"; when another PC is shown they are announced to it, and a
// Ctrl+V / Paste there pulls them from the phone.
use base::message_proto::*;
use std::collections::{HashMap, HashSet};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicI32, Ordering};
use std::sync::mpsc::{channel, Sender};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant, SystemTime};

const DESC_ID: i32 = 49334;
const DESC_NAME: &str = "FileGroupDescriptorW";
const CONTENTS_ID: i32 = 49267;
const CONTENTS_NAME: &str = "FileContents";
const DESC_SIZE: usize = 592;
const NAME_FIELD: usize = 520;
const CHUNK: u64 = 2 * 1024 * 1024;
const MAX_READ: usize = 16 * 1024 * 1024;
const FILECONTENTS_SIZE: i32 = 1;
const FILECONTENTS_RANGE: i32 = 2;
const RESP_OK: i32 = 1;
const RESP_FAIL: i32 = 2;
const EPOCH_DELTA: u64 = 116_444_736_000_000_000;
const OFFER_TTL: Duration = Duration::from_secs(30 * 60);

#[derive(Clone)]
struct Entry {
    name: String, // relative, '/' separated
    size: u64,
    dir: bool,
}

#[derive(Default)]
struct Remote {
    desc_id: i32,
    waiting_desc: bool,
    files: Vec<Entry>,
    clip_data_id: i32,
    seq: u64,
    state: String, // idle | offered | downloading | done | error
    total: u64,
    done: u64,
    dir: String,
    msg: String,
    cancel: Option<Arc<AtomicBool>>,
}

struct LocalFile {
    name: String,
    path: PathBuf,
    size: u64,
    dir: bool,
}

struct Local {
    id: u64,
    src: u64,
    files: Vec<LocalFile>,
    pdu: Vec<u8>,
    offered: HashSet<u64>,
    at: Instant,
}

fn remotes() -> &'static Mutex<HashMap<u64, Remote>> {
    static R: OnceLock<Mutex<HashMap<u64, Remote>>> = OnceLock::new();
    R.get_or_init(|| Mutex::new(HashMap::new()))
}

fn pending() -> &'static Mutex<HashMap<i32, Sender<(bool, Vec<u8>)>>> {
    static P: OnceLock<Mutex<HashMap<i32, Sender<(bool, Vec<u8>)>>>> = OnceLock::new();
    P.get_or_init(|| Mutex::new(HashMap::new()))
}

fn local() -> &'static Mutex<Option<Local>> {
    static L: OnceLock<Mutex<Option<Local>>> = OnceLock::new();
    L.get_or_init(|| Mutex::new(None))
}

static STREAM_ID: AtomicI32 = AtomicI32::new(0x5a00_0000);
static LOCAL_ID: AtomicI32 = AtomicI32::new(1);

fn wrap(u: cliprdr::Union) -> Message {
    let mut c = Cliprdr::new();
    c.union = Some(u);
    let mut m = Message::new();
    m.union = Some(message::Union::Cliprdr(c));
    m
}

fn format_data_request(id: i32) -> Message {
    let mut r = CliprdrServerFormatDataRequest::new();
    r.requested_format_id = id;
    wrap(cliprdr::Union::FormatDataRequest(r))
}

fn format_data_response(ok: bool, data: Vec<u8>) -> Message {
    let mut r = CliprdrServerFormatDataResponse::new();
    r.msg_flags = if ok { RESP_OK } else { RESP_FAIL };
    r.format_data = data.into();
    wrap(cliprdr::Union::FormatDataResponse(r))
}

fn contents_response(ok: bool, stream_id: i32, data: Vec<u8>) -> Message {
    let mut r = CliprdrFileContentsResponse::new();
    r.msg_flags = if ok { RESP_OK } else { RESP_FAIL };
    r.stream_id = stream_id;
    r.requested_data = data.into();
    wrap(cliprdr::Union::FileContentsResponse(r))
}

fn file_list_id(pdu: &[u8]) -> i32 {
    pdu.iter()
        .fold(0x811c_9dc5_u32, |id, b| (id ^ *b as u32).wrapping_mul(0x0100_0193)) as i32
}

fn u32_at(b: &[u8], o: usize) -> u32 {
    u32::from_le_bytes([b[o], b[o + 1], b[o + 2], b[o + 3]])
}

fn safe_name(raw: &str) -> Option<String> {
    let n = raw.replace('\\', "/");
    if n.is_empty() || n.starts_with('/') || n.contains(':') {
        return None;
    }
    if n.split('/').any(|c| c.is_empty() || c == "." || c == "..") {
        return None;
    }
    Some(n)
}

fn parse_descriptors(pdu: &[u8]) -> Option<Vec<Entry>> {
    if pdu.len() < 4 {
        return None;
    }
    let count = u32_at(pdu, 0) as usize;
    if pdu.len() != 4 + count * DESC_SIZE {
        return None;
    }
    let mut out = Vec::with_capacity(count);
    for i in 0..count {
        let d = &pdu[4 + i * DESC_SIZE..4 + (i + 1) * DESC_SIZE];
        let attrs = u32_at(d, 36);
        let high = u32_at(d, 64) as u64;
        let low = u32_at(d, 68) as u64;
        let name_bytes = &d[72..72 + NAME_FIELD];
        let mut units = Vec::new();
        for c in name_bytes.chunks_exact(2) {
            let u = u16::from_le_bytes([c[0], c[1]]);
            if u == 0 {
                break;
            }
            units.push(u);
        }
        let name = safe_name(&String::from_utf16(&units).ok()?)?;
        let dir = attrs & 0x10 != 0;
        out.push(Entry {
            name,
            size: if dir { 0 } else { (high << 32) | low },
            dir,
        });
    }
    Some(out)
}

fn build_pdu(files: &[LocalFile]) -> Vec<u8> {
    let now = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos() as u64
        / 100
        + EPOCH_DELTA;
    let mut b = Vec::with_capacity(4 + files.len() * DESC_SIZE);
    b.extend_from_slice(&(files.len() as u32).to_le_bytes());
    for f in files {
        // FD_ATTRIBUTES | FD_WRITESTIME | FD_FILESIZE | FD_PROGRESSUI
        b.extend_from_slice(&(0x04u32 | 0x20 | 0x40 | 0x4000).to_le_bytes());
        b.extend_from_slice(&[0u8; 32]);
        let attrs: u32 = if f.dir { 0x10 } else { 0x80 };
        b.extend_from_slice(&attrs.to_le_bytes());
        b.extend_from_slice(&[0u8; 16]);
        b.extend_from_slice(&now.to_le_bytes());
        b.extend_from_slice(&((f.size >> 32) as u32).to_le_bytes());
        b.extend_from_slice(&((f.size & 0xffff_ffff) as u32).to_le_bytes());
        let mut name = [0u8; NAME_FIELD];
        let units: Vec<u16> = f.name.replace('/', "\\").encode_utf16().take(259).collect();
        for (i, u) in units.iter().enumerate() {
            name[i * 2..i * 2 + 2].copy_from_slice(&u.to_le_bytes());
        }
        b.extend_from_slice(&name);
    }
    b
}

/// Handles a file clipboard message from the PC of session `sid`.
/// Returns the messages to send back to that PC.
pub fn on_msg(sid: u64, clip: Cliprdr) -> Vec<Message> {
    match clip.union {
        Some(cliprdr::Union::FormatList(list)) => {
            let desc = list.formats.iter().find(|f| f.format == DESC_NAME).map(|f| f.id);
            let has_contents = list.formats.iter().any(|f| f.format == CONTENTS_NAME);
            let mut rs = remotes().lock().unwrap();
            let r = rs.entry(sid).or_default();
            if r.state == "downloading" {
                return vec![];
            }
            match desc {
                Some(id) if has_contents => {
                    r.desc_id = id;
                    r.waiting_desc = true;
                    vec![format_data_request(id)]
                }
                _ => {
                    r.files.clear();
                    r.waiting_desc = false;
                    if r.state == "offered" {
                        r.state = "idle".into();
                    }
                    vec![]
                }
            }
        }
        Some(cliprdr::Union::FormatDataResponse(resp)) => {
            let mut rs = remotes().lock().unwrap();
            let r = rs.entry(sid).or_default();
            if !r.waiting_desc {
                return vec![];
            }
            r.waiting_desc = false;
            if resp.msg_flags != RESP_OK {
                return vec![];
            }
            let pdu: Vec<u8> = resp.format_data.to_vec();
            if let Some(files) = parse_descriptors(&pdu) {
                if files.is_empty() {
                    return vec![];
                }
                r.clip_data_id = file_list_id(&pdu);
                r.total = files.iter().map(|f| f.size).sum();
                r.files = files;
                r.done = 0;
                r.msg.clear();
                r.seq += 1;
                r.state = "offered".into();
            }
            vec![]
        }
        Some(cliprdr::Union::FileContentsResponse(resp)) => {
            if let Some(tx) = pending().lock().unwrap().remove(&resp.stream_id) {
                let _ = tx.send((resp.msg_flags == RESP_OK, resp.requested_data.to_vec()));
            }
            vec![]
        }
        Some(cliprdr::Union::TryEmpty(_)) => {
            let mut rs = remotes().lock().unwrap();
            if let Some(r) = rs.get_mut(&sid) {
                if r.state == "offered" {
                    r.state = "idle".into();
                    r.files.clear();
                }
            }
            vec![]
        }
        // The PC pastes files the phone announced to it.
        Some(cliprdr::Union::FormatDataRequest(req)) => {
            let l = local().lock().unwrap();
            match l.as_ref() {
                Some(l) if req.requested_format_id == DESC_ID => {
                    vec![format_data_response(true, l.pdu.clone())]
                }
                _ => vec![format_data_response(false, vec![])],
            }
        }
        Some(cliprdr::Union::FileContentsRequest(req)) => vec![serve_contents(&req)],
        _ => vec![],
    }
}

fn serve_contents(req: &CliprdrFileContentsRequest) -> Message {
    let fail = || contents_response(false, req.stream_id, vec![]);
    let guard = local().lock().unwrap();
    let Some(l) = guard.as_ref() else {
        return fail();
    };
    let Some(f) = l.files.get(req.list_index as usize) else {
        return fail();
    };
    if req.dw_flags == FILECONTENTS_SIZE {
        return contents_response(true, req.stream_id, f.size.to_le_bytes().to_vec());
    }
    if req.dw_flags != FILECONTENTS_RANGE || f.dir {
        return fail();
    }
    let pos = ((req.n_position_high as u32 as u64) << 32) | (req.n_position_low as u32 as u64);
    let want = (req.cb_requested as u32 as usize).min(MAX_READ);
    let path = f.path.clone();
    drop(guard);
    let read = || -> std::io::Result<Vec<u8>> {
        let mut file = std::fs::File::open(&path)?;
        file.seek(SeekFrom::Start(pos))?;
        let mut buf = Vec::with_capacity(want);
        file.take(want as u64).read_to_end(&mut buf)?;
        Ok(buf)
    };
    match read() {
        Ok(buf) => contents_response(true, req.stream_id, buf),
        Err(_) => fail(),
    }
}

fn set_state(sid: u64, f: impl FnOnce(&mut Remote)) {
    if let Some(r) = remotes().lock().unwrap().get_mut(&sid) {
        f(r);
    }
}

fn unique_top(dir: &Path, name: &str) -> String {
    if !dir.join(name).exists() {
        return name.to_owned();
    }
    let (stem, ext) = match name.rfind('.') {
        Some(i) if i > 0 => (&name[..i], &name[i..]),
        _ => (name, ""),
    };
    for n in 1..1000 {
        let c = format!("{stem} ({n}){ext}");
        if !dir.join(&c).exists() {
            return c;
        }
    }
    name.to_owned()
}

/// Downloads the files the PC of session `sid` announced, in a background thread.
pub fn start_download(
    sid: u64,
    dest: String,
    fallback: String,
    send: Box<dyn Fn(Message) + Send + 'static>,
) {
    let (files, clip_data_id, cancel) = {
        let mut rs = remotes().lock().unwrap();
        let Some(r) = rs.get_mut(&sid) else { return };
        if r.state == "downloading" || r.files.is_empty() {
            return;
        }
        let cancel = Arc::new(AtomicBool::new(false));
        r.cancel = Some(cancel.clone());
        r.state = "downloading".into();
        r.done = 0;
        r.msg.clear();
        (r.files.clone(), r.clip_data_id, cancel)
    };
    std::thread::spawn(move || {
        let mut root = PathBuf::from(&dest);
        if std::fs::create_dir_all(&root).is_err() || !writable(&root) {
            root = PathBuf::from(&fallback);
            let _ = std::fs::create_dir_all(&root);
        }
        let root_s = root.to_string_lossy().to_string();
        set_state(sid, |r| r.dir = root_s.clone());
        match download(sid, &root, &files, clip_data_id, &cancel, &send) {
            Ok(saved) => {
                let pdu = build_pdu(&saved);
                *local().lock().unwrap() = Some(Local {
                    id: LOCAL_ID.fetch_add(1, Ordering::SeqCst) as u64,
                    src: sid,
                    files: saved,
                    pdu,
                    offered: HashSet::new(),
                    at: Instant::now(),
                });
                set_state(sid, |r| {
                    r.state = "done".into();
                    r.cancel = None;
                });
            }
            Err(e) => set_state(sid, |r| {
                r.state = "error".into();
                r.msg = e;
                r.cancel = None;
            }),
        }
    });
}

fn writable(dir: &Path) -> bool {
    let p = dir.join(".wizz_write_test");
    let ok = std::fs::write(&p, b"x").is_ok();
    let _ = std::fs::remove_file(&p);
    ok
}

fn download(
    sid: u64,
    root: &Path,
    files: &[Entry],
    clip_data_id: i32,
    cancel: &AtomicBool,
    send: &Box<dyn Fn(Message) + Send + 'static>,
) -> Result<Vec<LocalFile>, String> {
    // top-level names that already exist get " (1)" etc.
    let mut tops: HashMap<String, String> = HashMap::new();
    let mut saved = Vec::new();
    let mut done: u64 = 0;
    for (idx, e) in files.iter().enumerate() {
        let (top, rest) = match e.name.find('/') {
            Some(i) => (e.name[..i].to_owned(), Some(e.name[i..].to_owned())),
            None => (e.name.clone(), None),
        };
        let new_top = tops
            .entry(top.clone())
            .or_insert_with(|| unique_top(root, &top))
            .clone();
        let rel = match rest {
            Some(r) => format!("{new_top}{r}"),
            None => new_top,
        };
        let path = root.join(&rel);
        if e.dir {
            std::fs::create_dir_all(&path).map_err(|x| x.to_string())?;
            saved.push(LocalFile { name: rel, path, size: 0, dir: true });
            continue;
        }
        if let Some(p) = path.parent() {
            std::fs::create_dir_all(p).map_err(|x| x.to_string())?;
        }
        let mut out = std::fs::File::create(&path).map_err(|x| x.to_string())?;
        let mut off: u64 = 0;
        while off < e.size {
            if cancel.load(Ordering::SeqCst) {
                drop(out);
                let _ = std::fs::remove_file(&path);
                return Err("Cancelled".into());
            }
            let n = CHUNK.min(e.size - off);
            let data = request_range(idx as i32, off, n as i32, clip_data_id, send)?;
            if data.is_empty() {
                return Err("The PC stopped sending the file".into());
            }
            out.write_all(&data).map_err(|x| x.to_string())?;
            off += data.len() as u64;
            done += data.len() as u64;
            set_state(sid, |r| r.done = done);
        }
        saved.push(LocalFile { name: rel, path, size: e.size, dir: false });
    }
    Ok(saved)
}

fn request_range(
    index: i32,
    pos: u64,
    n: i32,
    clip_data_id: i32,
    send: &Box<dyn Fn(Message) + Send + 'static>,
) -> Result<Vec<u8>, String> {
    let stream_id = STREAM_ID.fetch_add(1, Ordering::SeqCst);
    let (tx, rx) = channel();
    pending().lock().unwrap().insert(stream_id, tx);
    let mut req = CliprdrFileContentsRequest::new();
    req.stream_id = stream_id;
    req.list_index = index;
    req.dw_flags = FILECONTENTS_RANGE;
    req.n_position_low = (pos & 0xffff_ffff) as u32 as i32;
    req.n_position_high = (pos >> 32) as u32 as i32;
    req.cb_requested = n;
    req.have_clip_data_id = true;
    req.clip_data_id = clip_data_id;
    send(wrap(cliprdr::Union::FileContentsRequest(req)));
    let res = rx.recv_timeout(Duration::from_secs(60));
    pending().lock().unwrap().remove(&stream_id);
    match res {
        Ok((true, data)) => Ok(data),
        Ok((false, _)) => Err("The PC refused the file (copy it again)".into()),
        Err(_) => Err("Timed out waiting for the PC".into()),
    }
}

pub fn cancel(sid: u64) {
    if let Some(r) = remotes().lock().unwrap().get(&sid) {
        if let Some(c) = &r.cancel {
            c.store(true, Ordering::SeqCst);
        }
    }
}

pub fn dismiss(sid: u64) {
    if let Some(r) = remotes().lock().unwrap().get_mut(&sid) {
        if r.state != "downloading" {
            r.state = "idle".into();
        }
    }
}

/// Announces the phone's files to the PC of session `sid`, once per file set.
pub fn offer(sid: u64) -> Option<Message> {
    let mut l = local().lock().unwrap();
    let l = l.as_mut()?;
    if l.src == sid || l.offered.contains(&sid) || l.at.elapsed() > OFFER_TTL {
        return None;
    }
    l.offered.insert(sid);
    let mut list = CliprdrServerFormatList::new();
    for (id, name) in [(DESC_ID, DESC_NAME), (CONTENTS_ID, CONTENTS_NAME)] {
        let mut f = CliprdrFormat::new();
        f.id = id;
        f.format = name.to_owned();
        list.formats.push(f);
    }
    Some(wrap(cliprdr::Union::FormatList(list)))
}

fn json_escape(s: &str) -> String {
    let mut o = String::with_capacity(s.len() + 2);
    for c in s.chars() {
        match c {
            '"' => o.push_str("\\\""),
            '\\' => o.push_str("\\\\"),
            '\n' => o.push_str("\\n"),
            c if (c as u32) < 0x20 => o.push(' '),
            c => o.push(c),
        }
    }
    o
}

/// State of session `sid` for the Flutter banner, as JSON.
pub fn status(sid: u64) -> String {
    let rs = remotes().lock().unwrap();
    let (state, seq, count, total, done, dir, msg, names) = match rs.get(&sid) {
        Some(r) => {
            let tops: Vec<&Entry> = r.files.iter().filter(|f| !f.name.contains('/')).collect();
            let names: Vec<String> = tops
                .iter()
                .take(3)
                .map(|f| format!("\"{}\"", json_escape(&f.name)))
                .collect();
            (
                r.state.clone(),
                r.seq,
                tops.len(),
                r.total,
                r.done,
                r.dir.clone(),
                r.msg.clone(),
                names.join(","),
            )
        }
        None => ("idle".to_owned(), 0, 0, 0, 0, String::new(), String::new(), String::new()),
    };
    let state = if state.is_empty() { "idle".to_owned() } else { state };
    format!(
        "{{\"state\":\"{}\",\"seq\":{},\"count\":{},\"bytes\":{},\"done\":{},\"dir\":\"{}\",\"msg\":\"{}\",\"names\":[{}]}}",
        state,
        seq,
        count,
        total,
        done,
        json_escape(&dir),
        json_escape(&msg),
        names
    )
}

/// Forget a closed session.
pub fn remove_session(sid: u64) {
    cancel(sid);
    remotes().lock().unwrap().remove(&sid);
}
'''

# Wizz: Rust-side changes (file copy & paste on Android).
# Kept apart from wizz_apply.py because the build caches the Rust library by a
# hash that includes this file: Dart-only changes stay fast.
import os

def load(p):
    with open(p, encoding='utf-8') as f:
        return f.read()

def save(p, s):
    with open(p, 'w', encoding='utf-8') as f:
        f.write(s)

def rep(s, a, b):
    assert s.count(a) == 1, (s.count(a), a[:120])
    return s.replace(a, b)

save('src/wizz_file_clip.rs', WIZZ_FILE_CLIP_RS)

p = 'src/lib.rs'
s = load(p)
s = rep(s, "pub mod clipboard_file;\n",
        "pub mod clipboard_file;\n\n#[cfg(target_os = \"android\")]\npub mod wizz_file_clip;\n")
save(p, s)

p = 'src/client/io_loop.rs'
s = load(p)
s = rep(s, "                Some(message::Union::FileResponse(fr)) => {\n",
        "                #[cfg(target_os = \"android\")]\n"
        "                Some(message::Union::Cliprdr(clip)) => {\n"
        "                    if self.is_connected {\n"
        "                        let sid = self.handler.lc.read().unwrap().session_id;\n"
        "                        for m in crate::wizz_file_clip::on_msg(sid, clip) {\n"
        "                            allow_err!(peer.send(&m).await);\n"
        "                        }\n"
        "                    }\n"
        "                }\n"
        "                Some(message::Union::FileResponse(fr)) => {\n")
save(p, s)

p = 'src/flutter_ffi.rs'
s = load(p)
s = rep(s, '''        } else if key == "login_method" {
            s.lc.read().unwrap().get_login_method().to_owned()
''', '''        } else if key == "login_method" {
            s.lc.read().unwrap().get_login_method().to_owned()
        } else if key.starts_with("wizz-clip-") {
            wizz_clip_common(&s, &key, &param)
''')
s = rep(s, "pub fn session_get_common(\n", '''#[cfg(target_os = "android")]
fn wizz_clip_common(s: &flutter::FlutterSession, key: &str, param: &str) -> String {
    let sid = s.lc.read().unwrap().session_id;
    match key {
        "wizz-clip-status" => crate::wizz_file_clip::status(sid),
        "wizz-clip-download" => {
            let mut it = param.splitn(2, '\\n');
            let dest = it.next().unwrap_or("").to_owned();
            let fallback = it.next().unwrap_or("").to_owned();
            let s2 = s.clone();
            crate::wizz_file_clip::start_download(
                sid,
                dest,
                fallback,
                Box::new(move |m| {
                    crate::client::Interface::send(&*s2, crate::client::Data::Message(m));
                }),
            );
            "1".to_owned()
        }
        "wizz-clip-cancel" => {
            crate::wizz_file_clip::cancel(sid);
            "1".to_owned()
        }
        "wizz-clip-dismiss" => {
            crate::wizz_file_clip::dismiss(sid);
            "1".to_owned()
        }
        "wizz-clip-offer" => match crate::wizz_file_clip::offer(sid) {
            Some(m) => {
                crate::client::Interface::send(&**s, crate::client::Data::Message(m));
                "1".to_owned()
            }
            None => "0".to_owned(),
        },
        _ => "".to_owned(),
    }
}

#[cfg(not(target_os = "android"))]
fn wizz_clip_common(_s: &flutter::FlutterSession, _key: &str, _param: &str) -> String {
    "".to_owned()
}

pub fn session_get_common(
''')
save(p, s)
print('wizz rust patch applied')
