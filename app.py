# -*- coding: utf-8 -*-
# =============================================================================
#  YouTube Downloader Studio
#  خلية واحدة لـ Google Colab  |  Gradio 5  +  yt-dlp  +  FFmpeg
#  - قائمة عمودية حقيقية (صورة مصغرة + عنوان + مدة + تاريخ + Checkbox مستقل)
#  - 50 فيديو في الصفحة مع الاحتفاظ بالتحديد بين الصفحات
#  - تحميل حتى 1080p بصيغة MP4، حتى 10 عمليات بالتوازي
#  - لوحة تقدم مباشرة + ZIP للتنزيل عبر المتصفح (بدون Google Drive)
#  تنبيه: استخدمه فقط مع فيديوهات تملك حق تنزيلها. الأداة لا تتجاوز أي حماية.
# =============================================================================
import os, sys, subprocess, shutil

# ---------------------------------------------------------------- 1) التثبيت والبيئة
import multiprocessing
multiprocessing.freeze_support()

FROZEN = getattr(sys, "frozen", False)                       # نسخة PyInstaller المبنية على GitHub
IN_COLAB = "google.colab" in sys.modules or os.path.isdir("/content")
APP_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))

def _pip(*pkgs):
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "-U", *pkgs])

if not FROZEN:
    _need_gradio = True
    try:
        import gradio as _g
        _need_gradio = int(_g.__version__.split(".")[0]) < 5
    except Exception:
        pass
    if _need_gradio:
        _was_loaded = "gradio" in sys.modules
        _pip("gradio>=5.9,<6")
        if _was_loaded:
            raise SystemExit("⚠️ تم تحديث Gradio. اختر: Runtime ▸ Restart session ثم شغّل الخلية مرة أخرى.")
    _pip("yt-dlp[default]")          # YouTube يتغير باستمرار، لذلك نستخدم أحدث yt-dlp
    if not IN_COLAB:
        try:
            import imageio_ffmpeg
        except ImportError:
            _pip("imageio-ffmpeg")

def find_ffmpeg():
    try:
        import imageio_ffmpeg
        p = imageio_ffmpeg.get_ffmpeg_exe()
        if p and os.path.exists(p):
            return p
    except Exception:
        pass
    return shutil.which("ffmpeg")

FFMPEG = find_ffmpeg()
if FFMPEG is None and IN_COLAB:
    subprocess.run("apt-get -qq update && apt-get -qq install -y ffmpeg", shell=True, check=False)
    FFMPEG = shutil.which("ffmpeg")
if FFMPEG is None:
    print("⚠️ FFmpeg غير متوفر. على Mac نفّذ: brew install ffmpeg")
    raise SystemExit(1)

# ---------------------------------------------------------------- 2) الإعدادات
import re, time, math, glob, html, threading, zipfile, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

WORK = "/content/yt_studio" if IN_COLAB else os.path.join(os.path.expanduser("~"), "yt_studio")
DL_DIR = os.path.join(WORK, "downloads")
ZIP_DIR = os.path.join(WORK, "zips")
for _d in (WORK, DL_DIR, ZIP_DIR):
    os.makedirs(_d, exist_ok=True)

FFMPEG_LOC = None
if FFMPEG and os.path.basename(FFMPEG) != "ffmpeg":
    _bd = os.path.join(WORK, "bin"); os.makedirs(_bd, exist_ok=True)
    _lk = os.path.join(_bd, "ffmpeg")
    try:
        if os.path.lexists(_lk):
            os.remove(_lk)
        os.symlink(FFMPEG, _lk)
    except OSError:
        shutil.copyfile(FFMPEG, _lk); os.chmod(_lk, 0o755)
    FFMPEG_LOC = _bd

import gradio as gr
import yt_dlp

try:                                   # ملفات ZIP تُخدَّم مباشرة دون نسخها إلى cache (توفير مساحة)
    gr.set_static_paths(paths=[ZIP_DIR])
except Exception:
    pass

PAGE_SIZE = 50
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
ANSI = re.compile(r"\x1b\[[0-9;]*m")
DATE_CACHE = {}

# ---------------------------------------------------------------- 3) أدوات مساعدة
def human_size(n):
    n = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.1f} {u}" if u != "B" else f"{int(n)} B"
        n /= 1024

def fmt_duration(sec):
    if not sec:
        return "—"
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def fmt_date(entry):
    ud = entry.get("upload_date")
    if ud and len(str(ud)) == 8:
        ud = str(ud)
        return f"{ud[:4]}-{ud[4:6]}-{ud[6:]}"
    ts = entry.get("timestamp") or entry.get("release_timestamp")
    if ts:
        try:
            return time.strftime("%Y-%m-%d", time.gmtime(int(ts)))
        except Exception:
            pass
    return None

def clean_err(msg):
    msg = ANSI.sub("", str(msg)).strip().splitlines()[-1] if str(msg).strip() else "خطأ غير معروف"
    msg = re.sub(r"^ERROR:\s*", "", msg)
    msg = re.sub(r"^\[[^\]]+\]\s*[\w-]{6,}:\s*", "", msg)
    return msg[:300]

NON_RETRIABLE = ("private video", "video unavailable", "members-only", "members only",
                 "has been removed", "copyright", "not available", "premieres in",
                 "live event will begin", "age", "sign in to confirm", "join this channel",
                 "this video is no longer", "account associated")
def retriable(msg):
    m = msg.lower()
    return not any(k in m for k in NON_RETRIABLE)

def js_runtime_opts():
    for p in (os.path.join(APP_DIR, "deno"), os.path.join(APP_DIR, "bin", "deno")):
        if os.path.isfile(p):
            try:
                os.chmod(p, 0o755)
            except OSError:
                pass
            return {"js_runtimes": {"deno": {"path": p}}}
    for name in ("deno", "node"):
        if shutil.which(name):
            return {"js_runtimes": {name: {}}}
    return {}

COOKIES_PATH = os.path.join(WORK, "cookies.txt")

def base_opts():
    o = {"quiet": True, "no_warnings": True, "noprogress": True,
         "socket_timeout": 30, "nocheckcertificate": False}
    o.update(js_runtime_opts())
    if FFMPEG_LOC:
        o["ffmpeg_location"] = FFMPEG_LOC
    if os.path.exists(COOKIES_PATH):
        # yt-dlp قد يعدّل الملف أثناء التشغيل، لذلك نعطي كل عملية نسخة خاصة بها
        tmp = f"{COOKIES_PATH}.{threading.get_ident()}"
        try:
            shutil.copyfile(COOKIES_PATH, tmp)
            o["cookiefile"] = tmp
        except OSError:
            o["cookiefile"] = COOKIES_PATH
    return o

def save_cookies(fp):
    if not fp:
        if os.path.exists(COOKIES_PATH):
            os.remove(COOKIES_PATH)
        return "ℹ️ لا يوجد ملف cookies (التحميل بدون تسجيل دخول)."
    try:
        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
            txt = f.read()
    except Exception as e:
        return f"❌ تعذّر قراءة الملف: {clean_err(e)}"
    if "youtube.com" not in txt or "\t" not in txt:
        return ("❌ الملف لا يبدو بصيغة Netscape cookies الخاصة بـ youtube.com. "
                "صدّره من المتصفح بإضافة مثل «Get cookies.txt LOCALLY».")
    shutil.copyfile(fp, COOKIES_PATH)
    return "✅ تم حفظ ملف cookies وسيُستخدم في الاستيراد والتحميل."

# ---------------------------------------------------------------- 4) استيراد القناة
TAB_RE = re.compile(r"/(videos|shorts|streams|live|featured|playlists|community|about|releases)/?$")

def build_urls(raw, tabs):
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("أدخل رابط القناة أو اسم المستخدم (@handle).")
    if raw.startswith("@"):
        raw = "https://www.youtube.com/" + raw
    elif not raw.lower().startswith("http"):
        raw = ("https://www.youtube.com/@" + raw) if "/" not in raw and "." not in raw else "https://" + raw
    if "list=" in raw or "watch?v=" in raw:
        return [raw]                                   # قائمة تشغيل / فيديو مباشر
    base = raw.split("?")[0].rstrip("/")
    base = TAB_RE.sub("", base)
    return [f"{base}/{t}" for t in tabs]

def flatten(entries, out):
    for e in entries or []:
        if not e:
            continue
        if e.get("entries"):
            flatten(e["entries"], out)
        else:
            out.append(e)

UNAVAIL = re.compile(r"^\[(private|deleted|unavailable)", re.I)

def fetch_channel_videos(raw, tabs):
    urls = build_urls(raw, tabs)
    opts = base_opts()
    opts.update({"extract_flat": True, "skip_download": True, "ignoreerrors": True,
                 "lazy_playlist": False, "retries": 3, "extractor_retries": 3})
    seen, videos, skipped, errors = set(), [], 0, []
    for u in urls:
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(u, download=False)
        except Exception as e:
            errors.append(f"{u.rsplit('/', 1)[-1]}: {clean_err(e)}")
            continue
        if not info:
            continue
        flat = []
        if info.get("entries"):
            flatten(info["entries"], flat)
        elif info.get("id"):
            flat = [info]
        for e in flat:
            vid = e.get("id")
            title = e.get("title") or ""
            if not vid or vid in seen:
                continue
            if UNAVAIL.match(title) or not title:
                skipped += 1
                continue
            seen.add(vid)
            videos.append({"id": vid, "title": title,
                           "duration": e.get("duration"),
                           "date": fmt_date(e),
                           "url": f"https://www.youtube.com/watch?v={vid}"})
    return videos, skipped, errors

def scrape_date(vid):
    if vid in DATE_CACHE:
        return DATE_CACHE[vid]
    d = None
    try:
        req = urllib.request.Request(
            f"https://www.youtube.com/watch?v={vid}",
            headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
                     "Cookie": "CONSENT=YES+1"})
        with urllib.request.urlopen(req, timeout=15) as r:
            page = r.read(700000).decode("utf-8", "ignore")
        m = (re.search(r'itemprop="datePublished"\s+content="([^"]+)"', page)
             or re.search(r'"uploadDate":"([^"]+)"', page)
             or re.search(r'"publishDate":"([^"]+)"', page))
        if m:
            d = m.group(1)[:10]
    except Exception:
        d = None
    DATE_CACHE[vid] = d
    return d

def enrich_dates(videos, page):
    start = (page - 1) * PAGE_SIZE
    chunk = videos[start:start + PAGE_SIZE]
    missing = [v for v in chunk if not v.get("date")]
    if not missing:
        return videos
    with ThreadPoolExecutor(max_workers=10) as ex:
        res = list(ex.map(lambda v: scrape_date(v["id"]), missing))
    new = list(videos)
    byid = {v["id"]: d for v, d in zip(missing, res)}
    for i in range(start, min(start + PAGE_SIZE, len(new))):
        d = byid.get(new[i]["id"])
        if d:
            new[i] = dict(new[i], date=d)
    return new

# ---------------------------------------------------------------- 5) واجهة القائمة
def n_pages(videos):
    return max(1, math.ceil(len(videos) / PAGE_SIZE))

def page_label(videos, page):
    if not videos:
        return "<div class='pg'>لا توجد فيديوهات بعد</div>"
    a = (page - 1) * PAGE_SIZE + 1
    b = min(page * PAGE_SIZE, len(videos))
    return f"<div class='pg'>صفحة <b>{page}</b> من <b>{n_pages(videos)}</b> &nbsp;•&nbsp; عرض {a}–{b} من {len(videos):,}</div>"

def counter_text(n, total):
    return f"### ✅ المحدد: **{n:,}** من أصل {total:,} فيديو"

def thumb_html(v):
    return (f"<div class='thumb'><img loading='lazy' alt='' "
            f"src='https://i.ytimg.com/vi/{v['id']}/mqdefault.jpg'>"
            f"<span class='dur'>{fmt_duration(v.get('duration'))}</span></div>")

def info_html(v):
    return (f"<div class='vtitle' dir='auto'>{html.escape(v['title'])}</div>"
            f"<div class='vmeta'><span>⏱ {fmt_duration(v.get('duration'))}</span>"
            f"<span>📅 {v.get('date') or '—'}</span>"
            f"<span class='vid'>🆔 {v['id']}</span></div>")

# ---------------------------------------------------------------- 6) نظام التحميل
class Job:
    def __init__(self):
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.finished = threading.Event()
        self.total = self.ok = self.fail = self.skipped = 0
        self.active = {}      # vid -> [title, frac]
        self.results = {}     # vid -> filepath
        self.errors = []
        self.logs = []
        self.t0 = time.time()

    def log(self, m):
        with self.lock:
            self.logs.append(time.strftime("%H:%M:%S") + "  " + m)

JOB = Job()

def download_one(job, v, maxh, retries):
    vid, title = v["id"], v["title"]
    if job.cancel.is_set():
        with job.lock:
            job.skipped += 1
        return
    out_dir = os.path.join(DL_DIR, vid)
    os.makedirs(out_dir, exist_ok=True)
    with job.lock:
        job.active[vid] = [title, 0.0]
    job.log(f"▶️ بدء: {title}")
    last_err = ""
    for attempt in range(retries + 1):
        if job.cancel.is_set():
            break
        st = {"seen": []}

        def hook(d, st=st):
            if job.cancel.is_set():
                raise yt_dlp.utils.DownloadCancelled()
            if d.get("status") == "downloading":
                fn = d.get("filename")
                if fn not in st["seen"]:
                    st["seen"].append(fn)
                tot = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                frac = (d.get("downloaded_bytes") or 0) / tot if tot else 0
                n = len((d.get("info_dict") or {}).get("requested_formats") or [1]) or 1
                val = min(0.97, (max(0, len(st["seen"]) - 1) + frac) / n)
                with job.lock:
                    if vid in job.active:
                        job.active[vid][1] = max(job.active[vid][1], val)
            elif d.get("status") == "finished":
                with job.lock:
                    if vid in job.active:
                        job.active[vid][1] = max(job.active[vid][1], 0.97)

        opts = base_opts()
        opts.update({
            "format": f"bv*[height<={maxh}]+ba/b[height<={maxh}]",
            "format_sort": [f"res:{maxh}", "vcodec:h264", "acodec:aac"],
            "merge_output_format": "mp4",
            "outtmpl": os.path.join(out_dir, "%(title).120B [%(id)s].%(ext)s"),
            "windowsfilenames": True,
            "noplaylist": True,
            "retries": 5, "fragment_retries": 5,
            "progress_hooks": [hook],
        })
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([v["url"]])
            files = [f for f in glob.glob(os.path.join(out_dir, "*.mp4"))
                     if not re.search(r"\.f\d+\.", os.path.basename(f))]
            if not files:
                raise RuntimeError("لم يتم إنتاج ملف MP4")
            path = max(files, key=os.path.getsize)
            with job.lock:
                job.ok += 1
                job.results[vid] = path
                job.active.pop(vid, None)
            job.log(f"✅ تم: {title}")
            return
        except yt_dlp.utils.DownloadCancelled:
            break
        except Exception as e:
            last_err = clean_err(e)
            if attempt >= retries or not retriable(last_err) or job.cancel.is_set():
                break
            job.log(f"🔁 إعادة المحاولة ({attempt + 1}/{retries}): {title} — {last_err}")
            time.sleep(min(30, 3 * (attempt + 1)))
    with job.lock:
        job.active.pop(vid, None)
        if job.cancel.is_set() and not last_err:
            job.skipped += 1
        else:
            job.fail += 1
            job.errors.append(f"❌ {title} [{vid}]\n    السبب: {last_err or 'خطأ غير معروف'}")
    if last_err:
        job.log(f"❌ فشل: {title} — {last_err}")
        if "not a bot" in last_err.lower() or "sign in" in last_err.lower():
            with job.lock:
                first = not getattr(job, "hint_shown", False)
                job.hint_shown = True
            if first:
                if os.path.exists(COOKIES_PATH):
                    job.log("💡 الـ cookies مرفوعة لكن YouTube رفضها (منتهية أو مُلغاة). صدّرها من جديد: افتح "
                            "نافذة تصفح خاصة، سجّل دخولك، افتح youtube.com/robots.txt، صدّر الـ cookies، "
                            "ثم أغلق النافذة فوراً.")
                else:
                    job.log("💡 YouTube يطلب تسجيل الدخول: ارفع ملف cookies.txt من قسم «إعدادات التحميل ▸ cookies» "
                            "وخفّض التوازي إلى 2–3 ثم أعد المحاولة.")

def run_pool(job, chosen, maxh, workers, retries):
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(download_one, job, v, maxh, retries) for v in chosen]
            for f in as_completed(futs):
                try:
                    f.result()
                except Exception as e:
                    job.log(f"⚠️ خطأ داخلي: {clean_err(e)}")
    finally:
        job.finished.set()

def dash_html(job, status, pct=None):
    with job.lock:
        total, ok, fail, skip = job.total, job.ok, job.fail, job.skipped
        done = ok + fail + skip
        partial = sum(f for _, f in job.active.values())
        act = [(t, f) for t, f in list(job.active.values())[:10]]
    if pct is None:
        pct = 0 if not total else min(100.0, (done + partial) / total * 100)
    el = time.time() - job.t0
    eta = ""
    if 3 < pct < 99.5:
        rem = el * (100 - pct) / pct
        eta = f"<span>⏳ المتبقي تقريباً: {int(rem // 60)}د {int(rem % 60)}ث</span>"
    rows = "".join(
        f"<div class='arow'><div class='at' dir='auto'>{html.escape(t[:80])}</div>"
        f"<div class='mini'><i style='width:{f * 100:.0f}%'></i></div></div>" for t, f in act)
    return f"""
<div class='dash'>
  <div class='stats'>
    <div class='st'><b>{total}</b><small>المحدد</small></div>
    <div class='st'><b>{done}</b><small>تمت معالجته</small></div>
    <div class='st good'><b>{ok}</b><small>ناجح</small></div>
    <div class='st bad'><b>{fail}</b><small>فاشل</small></div>
  </div>
  <div class='bar'><i style='width:{pct:.1f}%'></i><span>{pct:.1f}%</span></div>
  <div class='stat-line'><span>{html.escape(status)}</span>{eta}<span>⏱ {int(el // 60)}د {int(el % 60)}ث</span></div>
  <div class='actives'>{rows}</div>
</div>"""

def run_download(sel, videos, maxh, workers, retries, delete_after, zip_gb):
    global JOB
    btn_on, btn_off = gr.update(interactive=True), gr.update(interactive=False)
    keep = gr.update()
    try:
        chosen = [v for v in videos if v["id"] in sel]
        if not chosen:
            yield ("<div class='dash'>⚠️ لم تحدد أي فيديو.</div>", "", "", keep, keep, btn_on)
            return
        free = shutil.disk_usage(WORK).free
        if free < 1.5 * 1024 ** 3:
            yield (f"<div class='dash'>⚠️ المساحة الحرة غير كافية ({human_size(free)}).</div>",
                   "", "", keep, keep, btn_on)
            return
        shutil.rmtree(DL_DIR, ignore_errors=True); os.makedirs(DL_DIR, exist_ok=True)
        shutil.rmtree(ZIP_DIR, ignore_errors=True); os.makedirs(ZIP_DIR, exist_ok=True)

        job = Job(); job.total = len(chosen); JOB = job
        maxh, workers, retries = int(maxh), int(workers), int(retries)
        job.log(f"بدء تحميل {len(chosen)} فيديو • حد الجودة {maxh}p • {workers} بالتوازي")
        if os.path.exists(COOKIES_PATH):
            job.log(f"🍪 ملف cookies مُفعَّل ({human_size(os.path.getsize(COOKIES_PATH))})")
        else:
            job.log("🍪 لا يوجد ملف cookies — لم يتم رفعه أو لم يُحفظ. ارفعه ثم انتظر ظهور ✅ قبل البدء.")
        th = threading.Thread(target=run_pool, args=(job, chosen, maxh, workers, retries), daemon=True)
        th.start()

        yield (dash_html(job, "جاري التحميل…"), "", "", gr.update(value=None), "", btn_off)
        low_disk = False
        while not job.finished.is_set():
            time.sleep(1)
            if not low_disk and shutil.disk_usage(WORK).free < 400 * 1024 ** 2:
                low_disk = True
                job.cancel.set()
                job.log("⛔ المساحة المتبقية قليلة جداً — تم إيقاف التحميل لحماية الجلسة.")
            with job.lock:
                logs, errs = "\n".join(job.logs[-150:]), "\n\n".join(job.errors)
            status = "جاري إيقاف العمليات…" if job.cancel.is_set() else "جاري التحميل…"
            yield (dash_html(job, status), logs, errs, keep, keep, btn_off)

        # ---------------- مرحلة إنشاء ZIP ----------------
        order = [v for v in chosen if v["id"] in job.results]
        parts, limit = [], float(zip_gb) * 1024 ** 3
        stamp = time.strftime("%Y%m%d_%H%M%S")
        zf, cur_size, idx = None, 0, 0
        try:
            for i, v in enumerate(order, 1):
                fp = job.results[v["id"]]
                if not os.path.exists(fp):
                    continue
                fsz = os.path.getsize(fp)
                if zf is None or (cur_size > 0 and cur_size + fsz > limit):
                    if zf:
                        zf.close()
                    idx += 1
                    p = os.path.join(ZIP_DIR, f"YT_Studio_{stamp}_part{idx:02d}.zip")
                    zf = zipfile.ZipFile(p, "w", zipfile.ZIP_STORED, allowZip64=True)
                    parts.append(p); cur_size = 0
                zf.write(fp, arcname=os.path.basename(fp))
                cur_size += fsz
                if delete_after:
                    try: os.remove(fp)
                    except OSError: pass
                with job.lock:
                    logs, errs = "\n".join(job.logs[-150:]), "\n\n".join(job.errors)
                yield (dash_html(job, f"📦 إنشاء ملف ZIP… ({i}/{len(order)})",
                                 pct=95 + 5 * i / max(1, len(order))), logs, errs, keep, keep, btn_off)
        finally:
            if zf:
                zf.close()
        if len(parts) == 1:
            single = os.path.join(ZIP_DIR, f"YT_Studio_{stamp}.zip")
            os.replace(parts[0], single); parts = [single]
        shutil.rmtree(DL_DIR, ignore_errors=True); os.makedirs(DL_DIR, exist_ok=True)

        # ---------------- التقرير النهائي ----------------
        total_zip = sum(os.path.getsize(p) for p in parts) if parts else 0
        el = time.time() - job.t0
        lines = ["## 📋 التقرير النهائي",
                 f"- ✅ ناجح: **{job.ok}**",
                 f"- ❌ فاشل: **{job.fail}**"]
        if job.skipped:
            lines.append(f"- ⏹ لم يُنفَّذ (إيقاف): **{job.skipped}**")
        lines.append(f"- ⏱ المدة: {int(el // 60)}د {int(el % 60)}ث")
        if parts:
            lines.append(f"- 📦 الحجم الإجمالي لملفات ZIP: **{human_size(total_zip)}** ({len(parts)} ملف)")
            for p in parts:
                lines.append(f"  - `{os.path.basename(p)}` — {human_size(os.path.getsize(p))}")
        else:
            lines.append("- لا توجد ملفات ناجحة لإنشاء ZIP.")
        if job.fail:
            lines.append("\nالتفاصيل الكاملة للأخطاء في صندوق «تفاصيل الأخطاء».")
        with job.lock:
            logs, errs = "\n".join(job.logs[-150:]), "\n\n".join(job.errors)
        final_status = "✅ اكتملت العملية" if not job.cancel.is_set() else "⏹ توقفت العملية (تم تجهيز ما تم تحميله)"
        yield (dash_html(job, final_status, pct=100), logs, errs,
               gr.update(value=parts or None), "\n".join(lines), btn_on)
    except Exception as e:
        yield (f"<div class='dash'>❌ خطأ غير متوقع: {html.escape(clean_err(e))}</div>",
               "", "", keep, keep, btn_on)

def stop_download():
    JOB.cancel.set()
    JOB.log("⏹ تم طلب الإيقاف…")
    return "⏹ جاري إيقاف التحميل… سيُجهَّز ما تم تحميله بنجاح."

# ---------------------------------------------------------------- 7) التصميم
CSS = """
.gradio-container{background:#0e0f14 !important;direction:rtl;max-width:1100px !important;margin:auto;
  font-family:'Segoe UI',Tahoma,'Noto Naskh Arabic',system-ui,sans-serif !important}
#hero{padding:22px 24px;border-radius:18px;background:linear-gradient(135deg,#ff2d2d 0%,#7a1fff 100%);color:#fff;margin-bottom:8px}
#hero h1{margin:0;font-size:1.9rem;color:#fff}
#hero p{margin:6px 0 0;opacity:.9;color:#fff}
.sec{background:#171923;border:1px solid #262a3a;border-radius:16px;padding:14px 16px;margin-top:12px}
.sec h3{margin:0 0 6px}
#vlist{max-height:68vh;overflow-y:auto;padding:6px;border:1px solid #262a3a;border-radius:14px;background:#12131a;gap:8px}
.vrow{direction:ltr;flex-wrap:nowrap !important;align-items:center;gap:12px !important;background:#1b1e2b;
  border:1px solid #272b3d;border-radius:14px;padding:8px 12px !important}
.vrow:hover{border-color:#ff4d4d}
.vrow > *{min-width:0 !important}
.vthumb{flex:0 0 176px !important}
.vinfo{flex:1 1 auto !important;direction:rtl}
.vcheck{flex:0 0 52px !important}
.vcheck input[type=checkbox]{width:24px;height:24px;accent-color:#ff3b3b;cursor:pointer}
.thumb{position:relative;width:168px;aspect-ratio:16/9;border-radius:12px;overflow:hidden;background:#000}
.thumb img{width:100%;height:100%;object-fit:cover;display:block}
.thumb .dur{position:absolute;bottom:6px;right:6px;background:rgba(0,0,0,.8);color:#fff;font-size:.75rem;padding:1px 6px;border-radius:6px}
.vtitle{font-weight:600;font-size:1rem;line-height:1.5;color:#f1f1f5;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.vmeta{display:flex;flex-wrap:wrap;gap:14px;margin-top:6px;font-size:.82rem;color:#a3a8bd}
.vid{opacity:.65;font-family:monospace}
.pg{text-align:center;padding:6px;color:#c9cde0}
#selbar{position:sticky;bottom:8px;z-index:20;background:#171923ee;backdrop-filter:blur(6px);border:1px solid #33374d;
  border-radius:14px;padding:10px 12px !important}
.dash{background:#12131a;border:1px solid #262a3a;border-radius:14px;padding:14px;color:#e8e9f1}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:12px}
.st{background:#1b1e2b;border-radius:12px;padding:10px;text-align:center}
.st b{display:block;font-size:1.5rem}.st small{color:#a3a8bd}
.st.good b{color:#3ddc84}.st.bad b{color:#ff5c5c}
.bar{position:relative;height:26px;border-radius:13px;background:#232738;overflow:hidden}
.bar i{display:block;height:100%;background:linear-gradient(90deg,#ff2d2d,#ff8a3d);transition:width .4s}
.bar span{position:absolute;inset:0;text-align:center;line-height:26px;font-weight:700;font-size:.85rem;color:#fff}
.stat-line{display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-top:8px;color:#c9cde0;font-size:.9rem}
.arow{margin-top:8px}.at{font-size:.8rem;color:#cfd2e4;margin-bottom:3px}
.mini{height:6px;border-radius:3px;background:#232738;overflow:hidden}.mini i{display:block;height:100%;background:#7a5cff}
@media (max-width:640px){
  .vthumb{flex:0 0 108px !important}.thumb{width:104px}
  .vtitle{font-size:.88rem}.vmeta{gap:8px;font-size:.72rem}
  .stats{grid-template-columns:repeat(2,1fr)}#hero h1{font-size:1.4rem}
}
"""

theme = gr.themes.Base(primary_hue="red", neutral_hue="slate")

with gr.Blocks(title="YouTube Downloader Studio", theme=theme, css=CSS,
               js="() => { document.body.classList.add('dark'); }") as demo:

    videos_st = gr.State([])
    sel_st = gr.State({})
    page_st = gr.State(1)
    tick_st = gr.State(0)

    gr.HTML("<div id='hero'><h1>🎬 YouTube Downloader Studio</h1>"
            "<p>استورد فيديوهات قناة، حدّد ما تريد، حمّله حتى 1080p بصيغة MP4 ونزّله كملف ZIP.</p></div>")

    # ---------------- 1) استيراد القناة ----------------
    with gr.Group(elem_classes="sec"):
        gr.Markdown("### 1️⃣ استيراد القناة")
        url_tb = gr.Textbox(label="رابط القناة أو @handle",
                            placeholder="https://www.youtube.com/@channel  أو  @channel", rtl=False)
        with gr.Row():
            tab_v = gr.Checkbox(value=True, label="الفيديوهات")
            tab_s = gr.Checkbox(value=False, label="Shorts")
            tab_l = gr.Checkbox(value=False, label="البثوث المباشرة المنتهية")
            dates_cb = gr.Checkbox(value=True, label="جلب تواريخ النشر الدقيقة للصفحة (أبطأ قليلاً)")
        fetch_btn = gr.Button("📥 استيراد كل الفيديوهات العامة", variant="primary", size="lg")
        fetch_status = gr.Markdown("")

    # ---------------- 2) مكتبة الفيديوهات ----------------
    with gr.Group(elem_classes="sec"):
        gr.Markdown("### 2️⃣ مكتبة الفيديوهات")
        with gr.Row():
            prev_top = gr.Button("◀ السابق", size="sm")
            lbl_top = gr.HTML(page_label([], 1))
            next_top = gr.Button("التالي ▶", size="sm")
        with gr.Column(elem_id="vlist"):
            @gr.render(inputs=[videos_st, page_st, sel_st, tick_st],
                       triggers=[videos_st.change, page_st.change, tick_st.change])
            def render_list(videos, page, sel, tick):
                if not videos:
                    gr.HTML("<div class='pg' style='padding:40px'>ابدأ باستيراد قناة لعرض الفيديوهات هنا.</div>")
                    return
                total = len(videos)
                start = (page - 1) * PAGE_SIZE
                for v in videos[start:start + PAGE_SIZE]:
                    with gr.Row(elem_classes="vrow"):
                        gr.HTML(thumb_html(v), elem_classes="vthumb")
                        gr.HTML(info_html(v), elem_classes="vinfo")
                        cb = gr.Checkbox(value=(v["id"] in sel), label="", show_label=False,
                                         container=False, elem_classes="vcheck")

                        def make_toggle(vid, total=total):
                            def _t(val, cur):
                                new = dict(cur or {})
                                if val:
                                    new[vid] = True
                                else:
                                    new.pop(vid, None)
                                return new, counter_text(len(new), total)
                            return _t

                        cb.change(make_toggle(v["id"]), inputs=[cb, sel_st],
                                  outputs=[sel_st, counter_md],
                                  concurrency_limit=1, concurrency_id="selection",
                                  show_progress="hidden")
        with gr.Row():
            prev_bot = gr.Button("◀ السابق", size="sm")
            lbl_bot = gr.HTML(page_label([], 1))
            next_bot = gr.Button("التالي ▶", size="sm")

    # ---------------- 3) تحديد الفيديوهات ----------------
    with gr.Row(elem_id="selbar"):
        counter_md = gr.Markdown(counter_text(0, 0))
        sel_page_btn = gr.Button("☑️ تحديد صفحة", size="sm")
        sel_all_btn = gr.Button("✅ تحديد كل القناة", size="sm", variant="primary")
        clear_btn = gr.Button("⬜ إلغاء التحديد", size="sm")

    # ---------------- 4) إعدادات التحميل ----------------
    with gr.Group(elem_classes="sec"):
        gr.Markdown("### 4️⃣ إعدادات التحميل")
        with gr.Row():
            res_dd = gr.Dropdown(choices=[("1080p Full HD", 1080), ("720p", 720), ("480p", 480), ("360p", 360)],
                                 value=1080, label="أقصى جودة (MP4)")
            workers_sl = gr.Slider(1, 10, value=10, step=1, label="عمليات تحميل متوازية")
            retries_sl = gr.Slider(0, 5, value=3, step=1, label="محاولات إعادة عند الأخطاء المؤقتة")
        with gr.Row():
            zip_sl = gr.Slider(0.5, 10, value=2, step=0.5, label="الحد الأقصى لحجم كل ملف ZIP (GB)")
            del_cb = gr.Checkbox(value=True, label="حذف MP4 بعد إضافته إلى ZIP (يوفر مساحة Colab)")
        with gr.Accordion("🍪 ملف cookies (مطلوب عندما يظهر «Sign in to confirm you're not a bot»)", open=False):
            gr.Markdown(
                "يحجب YouTube أحياناً عناوين Colab. الحل: سجّل دخولك في YouTube على متصفحك، "
                "ثم صدّر الـ cookies بصيغة **Netscape (cookies.txt)** وارفعه هنا.\n\n"
                "⚠️ الملف يعطي صلاحية الدخول لحسابك، فلا تشاركه مع أحد. "
                "يُفضَّل استخدام حساب ثانوي، لأن التحميل الكثيف قد يعرّض الحساب لقيود من YouTube.")
            cookies_file = gr.File(label="cookies.txt", file_types=[".txt"], type="filepath")
            cookies_status = gr.Markdown("ℹ️ لا يوجد ملف cookies.")
            cookies_file.change(save_cookies, cookies_file, cookies_status)

    # ---------------- 5) مراقبة التقدم ----------------
    with gr.Group(elem_classes="sec"):
        gr.Markdown("### 5️⃣ مراقبة تقدم التحميل")
        with gr.Row():
            start_btn = gr.Button("🚀 ابدأ تحميل المحدد", variant="primary", size="lg")
            stop_btn = gr.Button("⏹ إيقاف", variant="stop", size="lg")
        dash = gr.HTML("<div class='dash'>في الانتظار…</div>")
        with gr.Row():
            log_tb = gr.Textbox(label="سجل العمليات", lines=8, max_lines=8, interactive=False, autoscroll=True)
            err_tb = gr.Textbox(label="تفاصيل الأخطاء", lines=8, max_lines=8, interactive=False)

    # ---------------- 6) التصدير ----------------
    with gr.Group(elem_classes="sec"):
        gr.Markdown("### 6️⃣ تصدير الملفات وتنزيلها")
        zip_out = gr.File(label="ملفات ZIP (اضغط للتنزيل إلى جهازك)", file_count="multiple", interactive=False)
        report_md = gr.Markdown("")

    # ---------------- الأحداث ----------------
    def set_loading():
        return "⏳ جاري استخراج الفيديوهات… قد يستغرق الأمر دقيقة للقنوات الكبيرة.", gr.update(interactive=False)

    def on_fetch(url, tv, ts, tl, dates, tick):
        tabs = [t for t, on in (("videos", tv), ("shorts", ts), ("streams", tl)) if on]
        if not tabs:
            return ("⚠️ اختر قسماً واحداً على الأقل.", [], {}, 1, tick, counter_text(0, 0),
                    page_label([], 1), page_label([], 1), gr.update(interactive=True))
        try:
            videos, skipped, errors = fetch_channel_videos(url, tabs)
        except Exception as e:
            return (f"❌ {clean_err(e)}", [], {}, 1, tick, counter_text(0, 0),
                    page_label([], 1), page_label([], 1), gr.update(interactive=True))
        if not videos:
            msg = "⚠️ لم يتم العثور على فيديوهات عامة."
            if errors:
                msg += "\n\n" + "\n".join(f"- {e}" for e in errors)
            return (msg, [], {}, 1, tick + 1, counter_text(0, 0),
                    page_label([], 1), page_label([], 1), gr.update(interactive=True))
        if dates:
            videos = enrich_dates(videos, 1)
        msg = f"✅ تم استخراج **{len(videos):,}** فيديو"
        if skipped:
            msg += f" • تم تجاهل {skipped} فيديو محذوف/خاص/غير متاح"
        if errors:
            msg += "\n\n⚠️ " + " | ".join(errors)
        lbl = page_label(videos, 1)
        return (msg, videos, {}, 1, tick + 1, counter_text(0, len(videos)), lbl, lbl, gr.update(interactive=True))

    fetch_btn.click(set_loading, None, [fetch_status, fetch_btn], show_progress="hidden").then(
        on_fetch, [url_tb, tab_v, tab_s, tab_l, dates_cb, tick_st],
        [fetch_status, videos_st, sel_st, page_st, tick_st, counter_md, lbl_top, lbl_bot, fetch_btn])

    def go_page(videos, page, delta, dates):
        if not videos:
            return page, videos, page_label(videos, page), page_label(videos, page)
        new = min(max(1, page + delta), n_pages(videos))
        if dates:
            videos = enrich_dates(videos, new)
        lbl = page_label(videos, new)
        return new, videos, lbl, lbl

    def prev_page(videos, page, dates): return go_page(videos, page, -1, dates)
    def next_page(videos, page, dates): return go_page(videos, page, +1, dates)

    for b in (prev_top, prev_bot):
        b.click(prev_page, [videos_st, page_st, dates_cb], [page_st, videos_st, lbl_top, lbl_bot])
    for b in (next_top, next_bot):
        b.click(next_page, [videos_st, page_st, dates_cb], [page_st, videos_st, lbl_top, lbl_bot])

    def select_page(videos, page, sel, tick):
        new = dict(sel or {})
        for v in videos[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]:
            new[v["id"]] = True
        return new, counter_text(len(new), len(videos)), tick + 1

    def select_all(videos, sel, tick):
        new = {v["id"]: True for v in videos}
        return new, counter_text(len(new), len(videos)), tick + 1

    def clear_all(videos, sel, tick):
        return {}, counter_text(0, len(videos)), tick + 1

    sel_page_btn.click(select_page, [videos_st, page_st, sel_st, tick_st], [sel_st, counter_md, tick_st],
                       concurrency_limit=1, concurrency_id="selection")
    sel_all_btn.click(select_all, [videos_st, sel_st, tick_st], [sel_st, counter_md, tick_st],
                      concurrency_limit=1, concurrency_id="selection")
    clear_btn.click(clear_all, [videos_st, sel_st, tick_st], [sel_st, counter_md, tick_st],
                    concurrency_limit=1, concurrency_id="selection")

    start_btn.click(run_download,
                    [sel_st, videos_st, res_dd, workers_sl, retries_sl, del_cb, zip_sl],
                    [dash, log_tb, err_tb, zip_out, report_md, start_btn],
                    concurrency_limit=1, concurrency_id="download")
    stop_btn.click(stop_download, None, report_md, concurrency_limit=None, show_progress="hidden")

if not IN_COLAB:
    # تشغيل محلي: يفتح في المتصفح على جهازك، بدون رابط عام
    print(f"📁 الملفات تُحفظ في: {WORK}")
    demo.queue(max_size=32).launch(share=False, inbrowser=True, show_error=True,
                                   allowed_paths=[ZIP_DIR])
else:
    _app, _local, _public = demo.queue(max_size=32).launch(
        share=True, inline=False, show_error=True,
        allowed_paths=[ZIP_DIR], prevent_thread_lock=True)

    try:
        from IPython.display import display, HTML
        display(HTML(f"""
        <div style="direction:rtl;font-family:system-ui,Tahoma,sans-serif;padding:18px;border-radius:14px;
                    background:#171923;color:#fff;border:1px solid #33374d;max-width:640px">
          <div style="font-size:18px;margin-bottom:10px">🎬 التطبيق يعمل — افتحه في صفحة مستقلة خارج Colab:</div>
          <a href="{_public}" target="_blank" rel="noopener"
             style="display:inline-block;padding:12px 22px;border-radius:10px;background:linear-gradient(135deg,#ff2d2d,#7a1fff);
                    color:#fff;text-decoration:none;font-weight:700;font-size:16px">🚀 فتح YouTube Downloader Studio</a>
          <div style="margin-top:12px;font-size:13px;opacity:.8;direction:ltr;word-break:break-all">{_public}</div>
          <div style="margin-top:8px;font-size:12px;opacity:.7">لا تغلق هذه الخلية ولا تُوقف التشغيل أثناء استخدام التطبيق. الرابط يتوقف بإيقافها.</div>
        </div>"""))
    except Exception:
        print("افتح التطبيق من هذا الرابط:", _public)

    demo.block_thread()   # يُبقي الخلية شغّالة طالما التطبيق مفتوح
