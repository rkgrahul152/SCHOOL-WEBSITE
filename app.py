"""
Pundibari R.G.L High School — Production Flask App
SQLite WAL + 12 Indexes + Caching + Pagination + PostgreSQL Support
Handles 5,000–10,000+ students
"""
from flask import Flask,render_template,request,redirect,url_for,session,flash,jsonify,send_file
import sqlite3,os,hashlib,shutil,sys,platform
from datetime import datetime
from functools import wraps
from werkzeug.utils import secure_filename

_START_TIME = datetime.now()  # for developer uptime display

try:
    import psycopg2,psycopg2.extras
    PSYCOPG2=True
except ImportError:
    PSYCOPG2=False

app=Flask(__name__)
app.secret_key=os.environ.get('SECRET_KEY','pundibari_rgl_change_in_production')

UPLOAD      =os.environ.get('UPLOAD_FOLDER','static/images')
VIDEO_UPLOAD=os.environ.get('VIDEO_UPLOAD_FOLDER','static/videos')
DB_PATH     =os.environ.get('SQLITE_DB','school.db')
DATABASE_URL=os.environ.get('DATABASE_URL','')
USE_PG      =bool(DATABASE_URL and PSYCOPG2)
PER_PAGE    =50

ALLOWED_IMG  ={'png','jpg','jpeg','gif','webp'}
ALLOWED_FILE ={'png','jpg','jpeg','gif','webp','pdf'}
ALLOWED_VIDEO={'mp4','webm','ogg','mov'}
app.config['MAX_CONTENT_LENGTH']=300*1024*1024  # 300MB — allows short school video uploads

# ── In-memory settings cache ─────────────────────────
_cache={}; _cache_ts={}

def cache_get(k):
    if k in _cache and _cache_ts.get(k,0)>datetime.now().timestamp():
        return _cache[k]
    return None

def cache_set(k,v,ttl=300):
    _cache[k]=v; _cache_ts[k]=datetime.now().timestamp()+ttl

def cache_clear():
    _cache.clear(); _cache_ts.clear()

# ── DB connect ────────────────────────────────────────
def get_db():
    if USE_PG:
        conn=psycopg2.connect(DATABASE_URL,cursor_factory=psycopg2.extras.RealDictCursor)
        return conn
    conn=sqlite3.connect(DB_PATH,timeout=30,check_same_thread=False)
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-32000")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=268435456")
    conn.execute("PRAGMA optimize")
    return conn

# ── Helpers ───────────────────────────────────────────
def hash_pw(p): return hashlib.sha256(p.encode()).hexdigest()
def allowed_img(f): return '.' in f and f.rsplit('.',1)[1].lower() in ALLOWED_IMG
def allowed_file(f): return '.' in f and f.rsplit('.',1)[1].lower() in ALLOWED_FILE

def save_file(fo,sub,chk=None):
    if not fo or not fo.filename: return None
    chk=chk or allowed_file
    if not chk(fo.filename): return None
    fn=f"{int(datetime.now().timestamp())}_{secure_filename(fo.filename)}"
    dst=os.path.join(UPLOAD,sub); os.makedirs(dst,exist_ok=True)
    fo.save(os.path.join(dst,fn)); return f"{sub}/{fn}"

def save_video(fo):
    """Save an uploaded video into VIDEO_UPLOAD and return just its filename."""
    if not fo or not fo.filename: return None
    ext = fo.filename.rsplit('.',1)[-1].lower() if '.' in fo.filename else ''
    if ext not in ALLOWED_VIDEO: return None
    fn=f"{int(datetime.now().timestamp())}_{secure_filename(fo.filename)}"
    os.makedirs(VIDEO_UPLOAD, exist_ok=True)
    fo.save(os.path.join(VIDEO_UPLOAD, fn))
    return fn

def get_settings():
    cached=cache_get('settings')
    if cached: return cached
    db=get_db()
    rows=db.execute("SELECT key,value FROM settings").fetchall()
    db.close()
    r={row['key']:row['value'] for row in rows}
    cache_set('settings',r); return r

@app.context_processor
def inject_globals():
    ctx = dict(settings=get_settings(), now=datetime.now())
    if 'admin_id' in session:
        ctx['current_admin_perms'] = get_admin_perms(session['admin_id'])
        ctx['is_impersonating'] = session.get('impersonating', False)
    return ctx

# ── Auth ──────────────────────────────────────────────
def admin_req(f):
    @wraps(f)
    def d(*a,**k):
        if 'admin_id' not in session: return redirect(url_for('admin_login'))
        return f(*a,**k)
    return d

def student_req(f):
    @wraps(f)
    def d(*a,**k):
        if 'student_id' not in session: return redirect(url_for('student_login'))
        return f(*a,**k)
    return d

def perm_req(key):
    """Require admin login AND a specific permission flag (e.g. 'can_manage_results').
    Developers and full-scope defaults always pass. Restricted admins are blocked
    if the flag is off, with a flash message and redirect to the dashboard."""
    def outer(f):
        @wraps(f)
        def d(*a, **k):
            if 'admin_id' not in session:
                return redirect(url_for('admin_login'))
            perms = get_admin_perms(session['admin_id'])
            if not perms.get(key, 0):
                flash("You don't have permission to access this section. Contact your administrator.", 'error')
                return redirect(url_for('admin_dashboard'))
            return f(*a, **k)
        return d
    return outer

def access_filter(admin_id, cls_col='class', sec_col='section'):
    """Returns (sql_fragment, params) restricting rows to an admin's allowed
    class-sections. Empty fragment for full-scope admins. Blocks all rows
    for restricted admins with no assigned classes."""
    perms = get_admin_perms(admin_id)
    if perms['scope'] == 'all':
        return '', []
    if not perms['classes']:
        return ' AND 1=0', []
    conds = ' OR '.join([f"({cls_col}=? AND {sec_col}=?)" for _ in perms['classes']])
    params = []
    for cls, sec in perms['classes']:
        params += [cls, sec]
    return f" AND ({conds})", params

def can_touch_class(cls, sec):
    """Check whether the CURRENT session admin may add/edit/delete a record
    belonging to this class+section. True for full-scope admins."""
    if 'admin_id' not in session: return False
    perms = get_admin_perms(session['admin_id'])
    if perms['scope'] == 'all': return True
    return (cls, sec) in perms['classes']

def can_touch_class_loose(cls, sec):
    """Like can_touch_class, but treats section=='All' as matching if the
    admin owns ANY section within that class (used for assignments/materials
    which can be posted to a whole class at once)."""
    if 'admin_id' not in session: return False
    perms = get_admin_perms(session['admin_id'])
    if perms['scope'] == 'all': return True
    if sec == 'All':
        return any(c == cls for c, s in perms['classes'])
    return (cls, sec) in perms['classes']

def access_filter_loose(admin_id, cls_col='class', sec_col='section'):
    """Like access_filter, but also includes rows where section='All' and the
    class matches one of the admin's assigned classes."""
    perms = get_admin_perms(admin_id)
    if perms['scope'] == 'all':
        return '', []
    if not perms['classes']:
        return ' AND 1=0', []
    conds = []; params = []
    for cls, sec in perms['classes']:
        conds.append(f"({cls_col}=? AND ({sec_col}=? OR {sec_col}='All'))")
        params += [cls, sec]
    return f" AND ({' OR '.join(conds)})", params

# ══════════════════════════════════════════════════════
# DATABASE INIT + 12 PERFORMANCE INDEXES
# ══════════════════════════════════════════════════════
def init_db():
    db=get_db(); c=db.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE NOT NULL,password TEXT NOT NULL,name TEXT);
    CREATE TABLE IF NOT EXISTS students(id INTEGER PRIMARY KEY AUTOINCREMENT,
      roll_number TEXT NOT NULL,name TEXT NOT NULL,class TEXT NOT NULL,
      section TEXT NOT NULL,password TEXT NOT NULL,guardian TEXT,phone TEXT,
      UNIQUE(class,section,roll_number));
    CREATE TABLE IF NOT EXISTS notices(id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,content TEXT NOT NULL,category TEXT DEFAULT 'General',
      is_urgent INTEGER DEFAULT 0,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS results(id INTEGER PRIMARY KEY AUTOINCREMENT,
      roll_number TEXT NOT NULL,student_name TEXT NOT NULL,
      class TEXT NOT NULL,section TEXT NOT NULL,exam_name TEXT NOT NULL,
      subject TEXT NOT NULL,marks_obtained REAL,total_marks REAL,grade TEXT,
      year INTEGER,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS assignments(id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,description TEXT,subject TEXT NOT NULL,
      class TEXT NOT NULL,section TEXT DEFAULT 'All',due_date TEXT,file_path TEXT,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS materials(id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,subject TEXT NOT NULL,class TEXT NOT NULL,
      section TEXT DEFAULT 'All',file_path TEXT,description TEXT,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS routines(id INTEGER PRIMARY KEY AUTOINCREMENT,
      class TEXT NOT NULL,section TEXT NOT NULL,day TEXT NOT NULL,
      period INTEGER NOT NULL,subject TEXT NOT NULL,teacher TEXT,time_slot TEXT);
    CREATE TABLE IF NOT EXISTS teachers(id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,designation TEXT,subject TEXT,qualification TEXT,
      experience TEXT,phone TEXT,email TEXT,photo TEXT,
      sort_order INTEGER DEFAULT 99,is_active INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS facilities(id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,description TEXT,details TEXT,photo TEXT,
      icon TEXT DEFAULT '🏫',sort_order INTEGER DEFAULT 99,
      is_active INTEGER DEFAULT 1,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS gallery(id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,category TEXT NOT NULL,image_path TEXT NOT NULL,
      description TEXT,event_date TEXT,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS attendance(id INTEGER PRIMARY KEY AUTOINCREMENT,
      roll_number TEXT NOT NULL,class TEXT NOT NULL,section TEXT NOT NULL,
      date TEXT NOT NULL,status TEXT NOT NULL,
      UNIQUE(roll_number,class,section,date));
    CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,description TEXT,event_date TEXT NOT NULL,
      event_type TEXT DEFAULT 'General',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);

    -- ══ PERFORMANCE INDEXES (critical for 5000+ students) ══
    CREATE INDEX IF NOT EXISTS idx_students_login ON students(class,section,roll_number);
    CREATE INDEX IF NOT EXISTS idx_students_name  ON students(name);
    CREATE INDEX IF NOT EXISTS idx_results_lookup ON results(class,section,roll_number,exam_name);
    CREATE INDEX IF NOT EXISTS idx_results_exam   ON results(exam_name,class,section);
    CREATE INDEX IF NOT EXISTS idx_results_year   ON results(year,class,section);
    CREATE INDEX IF NOT EXISTS idx_attendance_lookup ON attendance(roll_number,class,section,date);
    CREATE INDEX IF NOT EXISTS idx_attendance_date   ON attendance(class,section,date);
    CREATE INDEX IF NOT EXISTS idx_assignments_class ON assignments(class,section);
    CREATE INDEX IF NOT EXISTS idx_materials_class   ON materials(class,section);
    CREATE INDEX IF NOT EXISTS idx_routines_class    ON routines(class,section,day);
    CREATE INDEX IF NOT EXISTS idx_notices_urgent    ON notices(is_urgent,created_at);
    CREATE INDEX IF NOT EXISTS idx_gallery_category  ON gallery(category,created_at);
    """)

    # Defaults
    pw=hash_pw('admin123')
    c.execute("INSERT OR IGNORE INTO admins(username,password,name) VALUES(?,?,?)",('admin',pw,'Administrator'))

    for k,v in [
        ('school_name','Pundibari R.G.L High School'),
        ('tagline','Enlightening Minds, Building Futures'),
        ('principal_name','Mr. Rajendra Kumar Singh'),
        ('principal_message','Welcome to Pundibari R.G.L High School — an institution built on the pillars of excellence, integrity, and holistic development. Our dedicated faculty ensure every student reaches their fullest potential.'),
        ('phone','+91-XXXXX-XXXXX'),('email','pundibari.rgl@wb.gov.in'),
        ('address','Pundibari, Cooch Behar, West Bengal - 736121'),
        ('established','1965'),('hero_subtitle','A Centre of Academic Excellence Since 1965'),
        ('school_logo',''),('hero_image',''),('principal_photo',''),
        ('hero_badge_text','Government Aided High School · West Bengal'),
        ('stat1_val','6000+'),('stat1_label','Students'),
        ('stat2_val','35+'),('stat2_label','Teachers'),
        ('stat3_val','27'),('stat3_label','Classes'),
        ('stat4_val','60+'),('stat4_label','Years Legacy'),
        ('ach1_val','98%'),('ach1_label','Pass Percentage (2024)'),
        ('ach2_val','15+'),('ach2_label','Sports Awards (2024)'),
        ('ach3_val','25+'),('ach3_label','Teachers Dedicated'),
        ('ach4_val','10+'),('ach4_label','Years of Excellence'),
        ('footer_about','Providing quality education to the youth of Pundibari since 1965.'),
        ('school_type','Government High School'),('affiliation','WBBSE & WBCHSE'),
        ('notice_board_title','Notices & Announcements'),
        ('homepage_show_facilities','1'),('homepage_show_gallery','1'),
        ('homepage_show_teachers','1'),('homepage_show_achievements','1'),
        ('facebook_url',''),('youtube_url',''),('whatsapp_number',''),('contact_map_embed',''),
        ('school_video',''),('school_video_youtube',''),('video_section_title','Experience Our School'),
    ]:
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",(k,v))

    for t,ct,cat,u in [
        ('Annual Exam Schedule 2024-25','Exams start March 10, 2025. Admit cards from Feb 25.','Examination',1),
        ('Annual Sports Day','Sports Day on January 26, 2025.','Events',0),
        ('Parent-Teacher Meeting','PTM on February 8, 10AM–2PM.','Meeting',0),
        ('Winter Vacation','School closed Dec 25 – Jan 1.','Holiday',0),
    ]:
        c.execute("INSERT OR IGNORE INTO notices(title,content,category,is_urgent) VALUES(?,?,?,?)",(t,ct,cat,u))

    for t,d,et,dt in [
        ('Annual Sports Day','Inter-class sports competition.','Sports','2025-01-26'),
        ('Science Exhibition','Student science projects.','Academic','2025-02-15'),
        ('Annual Function','Prize distribution ceremony.','Cultural','2025-03-05'),
        ('Parent-Teacher Meeting','Review student progress.','Meeting','2025-02-08'),
    ]:
        c.execute("INSERT OR IGNORE INTO events(title,description,event_type,event_date) VALUES(?,?,?,?)",(t,d,et,dt))

    for nm,des,sub,q,ex,so in [
        ('Mr. Rajendra Kumar Singh','Headmaster','Administration','M.A., B.Ed.','25 years',1),
        ('Mrs. Priya Sharma','Assistant Teacher','Mathematics','M.Sc., B.Ed.','15 years',2),
        ('Mr. Arun Das','Assistant Teacher','Science','M.Sc., B.Ed.','12 years',3),
        ('Mrs. Sunita Roy','Assistant Teacher','Bengali','M.A., B.Ed.','18 years',4),
        ('Mr. Bipul Barman','Assistant Teacher','English','M.A., B.Ed.','10 years',5),
        ('Mrs. Kabita Dey','Assistant Teacher','History','M.A., B.Ed.','8 years',6),
    ]:
        c.execute("INSERT OR IGNORE INTO teachers(name,designation,subject,qualification,experience,sort_order) VALUES(?,?,?,?,?,?)",(nm,des,sub,q,ex,so))

    for nm,desc,det,ico,so in [
        ('Smart Classroom','Interactive digital teaching with projectors and smart boards.','Projector System | Smart Board | Wi-Fi | Air Conditioned','🖥️',1),
        ('Library','Well-stocked library with 10,000+ books for all subjects.','10,000+ Books | Reading Room | Digital Catalogue | Reference','📚',2),
        ('Computer Laboratory','40+ modern computers with high-speed internet.','40+ Systems | High-Speed Internet | Latest Software | UPS','💻',3),
        ('Playground','Spacious sports ground for all outdoor activities.','Football Field | Cricket Pitch | Athletics Track | Badminton','⚽',4),
        ('Science Laboratory','Fully equipped labs for Physics, Chemistry & Biology.','Physics Lab | Chemistry Lab | Biology Lab | Safety Equipment','🔬',5),
        ('Mid-Day Meal','Government nutritious meal programme for all students.','Daily Hot Meals | Govt. Scheme | Hygienic Kitchen | Free','🍽️',6),
    ]:
        c.execute("INSERT OR IGNORE INTO facilities(name,description,details,icon,sort_order) VALUES(?,?,?,?,?)",(nm,desc,det,ico,so))

    spw=hash_pw('student123')
    c.execute("INSERT OR IGNORE INTO students(roll_number,name,class,section,password,guardian,phone) VALUES(?,?,?,?,?,?,?)",
              ('1','Raju Barman','10','A',spw,'Ramesh Barman','9876543210'))
    for subj,mo,gr in [('Mathematics',78,'B+'),('Science',85,'A'),('English',70,'B'),
                        ('Bengali',88,'A'),('History',65,'B+'),('Geography',72,'B')]:
        c.execute("INSERT OR IGNORE INTO results(roll_number,student_name,class,section,exam_name,subject,marks_obtained,total_marks,grade,year) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  ('1','Raju Barman','10','A','Annual Exam 2024-25',subj,mo,100,gr,2025))
    db.commit(); db.close()

# ══════════════════════════════════════════════════════
# PUBLIC ROUTES
# ══════════════════════════════════════════════════════
def extract_youtube_id(url):
    """Pull the video ID out of common YouTube URL formats."""
    if not url: return ''
    import re as _re
    m = _re.search(r'(?:v=|youtu\.be/|embed/)([A-Za-z0-9_-]{11})', url)
    return m.group(1) if m else ''

@app.route('/')
def index():
    db=get_db()
    notices   =db.execute("SELECT * FROM notices ORDER BY is_urgent DESC,created_at DESC LIMIT 5").fetchall()
    events    =db.execute("SELECT * FROM events ORDER BY event_date ASC LIMIT 4").fetchall()
    teachers  =db.execute("SELECT * FROM teachers WHERE is_active=1 ORDER BY sort_order LIMIT 6").fetchall()
    gallery   =db.execute("SELECT * FROM gallery ORDER BY created_at DESC LIMIT 6").fetchall()
    facilities=db.execute("SELECT * FROM facilities WHERE is_active=1 ORDER BY sort_order LIMIT 6").fetchall()
    db.close()
    settings = get_settings()
    yt_id = extract_youtube_id(settings.get('school_video_youtube',''))
    return render_template('index.html',notices=notices,events=events,
                           teachers=teachers,gallery=gallery,facilities=facilities,yt_id=yt_id)

@app.route('/about')
def about():
    db=get_db(); t=db.execute("SELECT * FROM teachers WHERE is_active=1 ORDER BY sort_order").fetchall(); db.close()
    return render_template('about.html',teachers=t)

@app.route('/academics')
def academics(): return render_template('academics.html')

@app.route('/class/<cn>/<sec>')
def class_page(cn,sec):
    db=get_db()
    routines   =db.execute("SELECT * FROM routines WHERE class=? AND section=? ORDER BY day,period",(cn,sec)).fetchall()
    assignments=db.execute("SELECT * FROM assignments WHERE class=? AND (section=? OR section='All') ORDER BY created_at DESC LIMIT 10",(cn,sec)).fetchall()
    materials  =db.execute("SELECT * FROM materials WHERE class=? AND (section=? OR section='All') ORDER BY created_at DESC",(cn,sec)).fetchall()
    db.close()
    return render_template('class_page.html',class_name=cn,section=sec,
                           routines=routines,assignments=assignments,materials=materials)

@app.route('/notices')
def notices():
    db=get_db(); n=db.execute("SELECT * FROM notices ORDER BY is_urgent DESC,created_at DESC").fetchall(); db.close()
    return render_template('notices.html',notices=n)

@app.route('/gallery')
def gallery():
    db=get_db()
    cats=['Annual Function','Sports','Science Exhibition','Cultural','Campus']
    gi={c:db.execute("SELECT * FROM gallery WHERE category=? ORDER BY created_at DESC",(c,)).fetchall() for c in cats}
    all_=db.execute("SELECT * FROM gallery ORDER BY created_at DESC").fetchall()
    db.close()
    return render_template('gallery.html',gallery_items=gi,all_items=all_,categories=cats)

@app.route('/facilities')
def facilities():
    db=get_db(); f=db.execute("SELECT * FROM facilities WHERE is_active=1 ORDER BY sort_order").fetchall(); db.close()
    return render_template('facilities.html',facilities=f)

@app.route('/contact')
def contact(): return render_template('contact.html')

@app.route('/results',methods=['GET','POST'])
def results():
    data=None; error=None; searched=False
    if request.method=='POST':
        roll=request.form.get('roll_number','').strip()
        cls=request.form.get('class','').strip()
        sec=request.form.get('section','').strip()
        exam=request.form.get('exam_name','').strip()
        searched=True
        if not all([roll,cls,sec,exam]): error='Please fill all four fields.'
        else:
            db=get_db()
            data=db.execute("SELECT * FROM results WHERE roll_number=? AND class=? AND section=? AND exam_name=? ORDER BY subject",(roll,cls,sec,exam)).fetchall()
            db.close()
            if not data: error=f'No result found for Roll {roll}, Class {cls}-{sec}, Exam: {exam}.'
    db=get_db(); exams=db.execute("SELECT DISTINCT exam_name FROM results ORDER BY exam_name").fetchall(); db.close()
    return render_template('results.html',result_data=data,error=error,exams=exams,searched=searched)

# ══════════════════════════════════════════════════════
# STUDENT
# ══════════════════════════════════════════════════════
@app.route('/student/login',methods=['GET','POST'])
def student_login():
    if request.method=='POST':
        roll=request.form.get('roll_number','').strip()
        cls=request.form.get('class','').strip()
        sec=request.form.get('section','').strip()
        pw=hash_pw(request.form.get('password',''))
        db=get_db()
        stu=db.execute("SELECT * FROM students WHERE class=? AND section=? AND roll_number=? AND password=?",(cls,sec,roll,pw)).fetchone()
        db.close()
        if stu:
            session.update({'student_id':stu['id'],'student_roll':stu['roll_number'],
                            'student_name':stu['name'],'student_class':stu['class'],'student_section':stu['section']})
            log_activity('student', stu['id'], stu['name'], 'LOGIN', f"Class {cls}-{sec}, Roll {roll}")
            return redirect(url_for('student_dashboard'))
        log_activity('student', None, f"{cls}-{sec} Roll {roll}", 'LOGIN_FAILED', 'Invalid credentials')
        flash('Invalid credentials – check class, section, roll & password.','error')
    return render_template('student_login.html')

@app.route('/student/dashboard')
@student_req
def student_dashboard():
    roll=session['student_roll']; cls=session['student_class']; sec=session['student_section']
    db=get_db()
    att  =db.execute("SELECT * FROM attendance WHERE roll_number=? AND class=? AND section=? ORDER BY date DESC LIMIT 60",(roll,cls,sec)).fetchall()
    asn  =db.execute("SELECT * FROM assignments WHERE class=? AND (section=? OR section='All') ORDER BY created_at DESC LIMIT 6",(cls,sec)).fetchall()
    mats =db.execute("SELECT * FROM materials WHERE class=? AND (section=? OR section='All') ORDER BY created_at DESC LIMIT 8",(cls,sec)).fetchall()
    rout =db.execute("SELECT * FROM routines WHERE class=? AND section=? ORDER BY day,period",(cls,sec)).fetchall()
    res  =db.execute("SELECT * FROM results WHERE roll_number=? AND class=? AND section=? ORDER BY exam_name,subject",(roll,cls,sec)).fetchall()
    nts  =db.execute("SELECT * FROM notices ORDER BY is_urgent DESC,created_at DESC LIMIT 6").fetchall()
    db.close()
    total=len(att); present=sum(1 for a in att if a['status']=='Present')
    pct=round((present/total*100) if total else 0,1)
    return render_template('student_dashboard.html',attendance=att,assignments=asn,
        materials=mats,routines=rout,results=res,notices=nts,att_pct=pct,present=present,total=total)

@app.route('/student/logout')
def student_logout():
    if 'student_id' in session:
        log_activity('student', session['student_id'], session.get('student_name',''), 'LOGOUT')
    session.clear(); return redirect(url_for('student_login'))

# ══════════════════════════════════════════════════════
# ADMIN AUTH
# ══════════════════════════════════════════════════════
@app.route('/admin/login',methods=['GET','POST'])
def admin_login():
    if request.method=='POST':
        u=request.form.get('username','').strip()
        pw=hash_pw(request.form.get('password',''))
        db=get_db(); adm=db.execute("SELECT * FROM admins WHERE username=? AND password=?",(u,pw)).fetchone(); db.close()
        if adm:
            session.update({'admin_id':adm['id'],'admin_name':adm['name']})
            log_activity('admin', adm['id'], adm['name'], 'LOGIN')
            return redirect(url_for('admin_dashboard'))
        log_activity('admin', None, u, 'LOGIN_FAILED', 'Invalid credentials')
        flash('Invalid credentials.','error')
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    if 'admin_id' in session:
        log_activity('admin', session['admin_id'], session.get('admin_name',''), 'LOGOUT')
    session.clear(); return redirect(url_for('admin_login'))

@app.route('/admin/')
@app.route('/admin/dashboard')
@admin_req
def admin_dashboard():
    db=get_db()
    stats={k:db.execute(q).fetchone()[0] for k,q in [
        ('students',"SELECT COUNT(*) FROM students"),
        ('teachers',"SELECT COUNT(*) FROM teachers WHERE is_active=1"),
        ('notices',"SELECT COUNT(*) FROM notices"),
        ('gallery',"SELECT COUNT(*) FROM gallery"),
        ('results',"SELECT COUNT(*) FROM results"),
        ('facilities',"SELECT COUNT(*) FROM facilities WHERE is_active=1"),
        ('assignments',"SELECT COUNT(*) FROM assignments"),
        ('attendance',"SELECT COUNT(*) FROM attendance"),
    ]}
    rn=db.execute("SELECT * FROM notices ORDER BY created_at DESC LIMIT 5").fetchall()
    re=db.execute("SELECT * FROM events ORDER BY event_date ASC LIMIT 5").fetchall()
    db.close()
    return render_template('admin_dashboard.html',stats=stats,recent_notices=rn,recent_events=re)

# ── Image uploads (shared helper) ─────────────────────
def _upload_img(key,sub,fkey):
    path=save_file(request.files.get(fkey),sub,allowed_img)
    if path:
        db=get_db()
        old=db.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone()
        if old and old['value']:
            p=os.path.join(UPLOAD,old['value'])
            if os.path.exists(p): os.remove(p)
        db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",(key,path)); db.commit(); db.close()
        cache_clear(); flash('Image updated!','success')
    else: flash('Please select a valid image (PNG/JPG/GIF/WEBP).','error')
    return redirect(url_for('admin_settings'))

def _remove_img(key):
    db=get_db()
    old=db.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone()
    if old and old['value']:
        p=os.path.join(UPLOAD,old['value'])
        if os.path.exists(p): os.remove(p)
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,'')",(key,)); db.commit(); db.close()
    cache_clear(); flash('Removed.','success'); return redirect(url_for('admin_settings'))

@app.route('/admin/logo/upload',methods=['POST'])
@perm_req('can_view_settings')
def admin_upload_logo(): return _upload_img('school_logo','logo','logo')
@app.route('/admin/logo/remove')
@perm_req('can_view_settings')
def admin_remove_logo(): return _remove_img('school_logo')

@app.route('/admin/hero/upload',methods=['POST'])
@perm_req('can_view_settings')
def admin_upload_hero(): return _upload_img('hero_image','hero','hero_image')
@app.route('/admin/hero/remove')
@perm_req('can_view_settings')
def admin_remove_hero(): return _remove_img('hero_image')

@app.route('/admin/principal/upload',methods=['POST'])
@perm_req('can_view_settings')
def admin_upload_principal(): return _upload_img('principal_photo','principal','principal_photo')
@app.route('/admin/principal/remove')
@perm_req('can_view_settings')
def admin_remove_principal(): return _remove_img('principal_photo')

# ── SCHOOL VIDEO (door-reveal on homepage) ─────────────
@app.route('/admin/video/upload', methods=['POST'])
@perm_req('can_view_settings')
def admin_upload_video():
    fn = save_video(request.files.get('school_video'))
    if fn:
        db = get_db()
        old = db.execute("SELECT value FROM settings WHERE key='school_video'").fetchone()
        if old and old['value']:
            p = os.path.join(VIDEO_UPLOAD, old['value'])
            if os.path.exists(p):
                try: os.remove(p)
                except Exception: pass
        db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('school_video',?)", (fn,))
        db.commit(); db.close()
        cache_clear()
        flash('School video uploaded! It will now play in the homepage door reveal.', 'success')
    else:
        flash('Please upload a valid video file (MP4, WEBM, OGG, or MOV).', 'error')
    return redirect(url_for('admin_settings'))

@app.route('/admin/video/remove')
@perm_req('can_view_settings')
def admin_remove_video():
    db = get_db()
    old = db.execute("SELECT value FROM settings WHERE key='school_video'").fetchone()
    if old and old['value']:
        p = os.path.join(VIDEO_UPLOAD, old['value'])
        if os.path.exists(p):
            try: os.remove(p)
            except Exception: pass
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('school_video','')")
    db.commit(); db.close()
    cache_clear()
    flash('School video removed.', 'success')
    return redirect(url_for('admin_settings'))

# ══════════════════════════════════════════════════════
# ADMIN – NOTICES
# ══════════════════════════════════════════════════════
@app.route('/admin/notices')
@perm_req('can_manage_notices')
def admin_notices():
    db=get_db(); n=db.execute("SELECT * FROM notices ORDER BY created_at DESC").fetchall(); db.close()
    return render_template('admin_notices.html',notices=n)

@app.route('/admin/notices/add',methods=['POST'])
@perm_req('can_manage_notices')
def admin_add_notice():
    db=get_db()
    db.execute("INSERT INTO notices(title,content,category,is_urgent) VALUES(?,?,?,?)",
        (request.form['title'],request.form['content'],request.form.get('category','General'),1 if request.form.get('urgent') else 0))
    db.commit(); db.close(); flash('Notice posted!','success'); return redirect(url_for('admin_notices'))

@app.route('/admin/notices/delete/<int:i>')
@perm_req('can_manage_notices')
def admin_delete_notice(i):
    db=get_db(); db.execute("DELETE FROM notices WHERE id=?",(i,)); db.commit(); db.close()
    flash('Deleted.','success'); return redirect(url_for('admin_notices'))

# ══════════════════════════════════════════════════════
# ADMIN – RESULTS (paginated + bulk import)
# ══════════════════════════════════════════════════════
@app.route('/admin/results')
@perm_req('can_manage_results')
def admin_results():
    cls=request.args.get('class',''); sec=request.args.get('section','')
    exam=request.args.get('exam',''); page=max(1,int(request.args.get('page',1)))
    db=get_db()
    q="SELECT * FROM results WHERE 1=1"; p=[]
    if cls: q+=" AND class=?"; p.append(cls)
    if sec: q+=" AND section=?"; p.append(sec)
    if exam: q+=" AND exam_name=?"; p.append(exam)
    af, afp = access_filter(session['admin_id']); q += af; p += afp
    total=db.execute(f"SELECT COUNT(*) FROM ({q}) t",p).fetchone()[0]
    offset=(page-1)*PER_PAGE
    res=db.execute(f"{q} ORDER BY class,section,roll_number+0,subject LIMIT {PER_PAGE} OFFSET {offset}",p).fetchall()
    exams=db.execute("SELECT DISTINCT exam_name FROM results ORDER BY exam_name").fetchall()
    db.close()
    tp=max(1,(total+PER_PAGE-1)//PER_PAGE)
    pag=dict(page=page,total=total,total_pages=tp,has_prev=page>1,has_next=page<tp)
    perms = get_admin_perms(session['admin_id'])
    return render_template('admin_results.html',results=res,exams=exams,pagination=pag,
                           filter_class=cls,filter_section=sec,filter_exam=exam,admin_perms=perms)

@app.route('/admin/results/add',methods=['POST'])
@perm_req('can_manage_results')
def admin_add_result():
    f=request.form
    if not can_touch_class(f['class'], f['section']):
        flash("You don't have permission to add results for this class/section.", 'error')
        return redirect(url_for('admin_results'))
    db=get_db()
    db.execute("INSERT INTO results(roll_number,student_name,class,section,exam_name,subject,marks_obtained,total_marks,grade,year) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (f['roll_number'],f['student_name'],f['class'],f['section'],f['exam_name'],f['subject'],f['marks_obtained'],f['total_marks'],f.get('grade',''),f.get('year',datetime.now().year)))
    db.commit(); db.close(); flash('Result saved!','success'); return redirect(url_for('admin_results'))

@app.route('/admin/results/delete/<int:i>')
@perm_req('can_manage_results')
def admin_delete_result(i):
    db=get_db()
    row = db.execute("SELECT class,section FROM results WHERE id=?", (i,)).fetchone()
    if row and not can_touch_class(row['class'], row['section']):
        db.close(); flash("You don't have permission to delete this record.", 'error')
        return redirect(url_for('admin_results'))
    db.execute("DELETE FROM results WHERE id=?",(i,)); db.commit(); db.close()
    flash('Deleted.','success'); return redirect(url_for('admin_results'))

@app.route('/admin/results/bulk',methods=['POST'])
@perm_req('can_manage_results')
def admin_bulk_results():
    cls=request.form.get('class',''); sec=request.form.get('section','')
    if not can_touch_class(cls, sec):
        flash("You don't have permission to import results for this class/section.", 'error')
        return redirect(url_for('admin_results'))
    exam=request.form.get('exam_name',''); yr=request.form.get('year',datetime.now().year)
    raw=request.form.get('bulk_data','').strip(); count=0; db=get_db()
    for line in raw.splitlines():
        p=[x.strip() for x in line.split(',')]
        if len(p)<4: continue
        try:
            db.execute("INSERT INTO results(roll_number,student_name,class,section,exam_name,subject,marks_obtained,total_marks,grade,year) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (p[0],p[1],cls,sec,exam,p[2],float(p[3]),float(p[4]) if len(p)>4 else 100,p[5] if len(p)>5 else '',yr))
            count+=1
        except: pass
    db.commit(); db.close(); flash(f'{count} results imported!','success'); return redirect(url_for('admin_results'))


# ══════════════════════════════════════════════════════
# ADMIN – ASSIGNMENTS / MATERIALS / GALLERY
# ══════════════════════════════════════════════════════
@app.route('/admin/assignments')
@perm_req('can_manage_assignments')
def admin_assignments():
    db=get_db()
    af, afp = access_filter_loose(session['admin_id'])
    a=db.execute(f"SELECT * FROM assignments WHERE 1=1{af} ORDER BY created_at DESC", afp).fetchall()
    db.close()
    return render_template('admin_assignments.html',assignments=a,admin_perms=get_admin_perms(session['admin_id']))

@app.route('/admin/assignments/add',methods=['POST'])
@perm_req('can_manage_assignments')
def admin_add_assignment():
    f=request.form
    if not can_touch_class_loose(f['class'], f.get('section','All')):
        flash("You don't have permission to post assignments for this class/section.", 'error')
        return redirect(url_for('admin_assignments'))
    path=save_file(request.files.get('file'),'assignments'); db=get_db()
    db.execute("INSERT INTO assignments(title,description,subject,class,section,due_date,file_path) VALUES(?,?,?,?,?,?,?)",
        (f['title'],f.get('description'),f['subject'],f['class'],f.get('section','All'),f.get('due_date'),path))
    db.commit(); db.close(); flash('Assignment added!','success'); return redirect(url_for('admin_assignments'))

@app.route('/admin/materials')
@perm_req('can_manage_materials')
def admin_materials():
    db=get_db()
    af, afp = access_filter_loose(session['admin_id'])
    m=db.execute(f"SELECT * FROM materials WHERE 1=1{af} ORDER BY created_at DESC", afp).fetchall()
    db.close()
    return render_template('admin_materials.html',materials=m,admin_perms=get_admin_perms(session['admin_id']))

@app.route('/admin/materials/add',methods=['POST'])
@perm_req('can_manage_materials')
def admin_add_material():
    f=request.form
    if not can_touch_class_loose(f['class'], f.get('section','All')):
        flash("You don't have permission to upload materials for this class/section.", 'error')
        return redirect(url_for('admin_materials'))
    path=save_file(request.files.get('file'),'materials'); db=get_db()
    db.execute("INSERT INTO materials(title,subject,class,section,file_path,description) VALUES(?,?,?,?,?,?)",
        (f['title'],f['subject'],f['class'],f.get('section','All'),path,f.get('description')))
    db.commit(); db.close(); flash('Material uploaded!','success'); return redirect(url_for('admin_materials'))


@app.route('/admin/gallery')
@perm_req('can_manage_gallery')
def admin_gallery():
    db=get_db(); g=db.execute("SELECT * FROM gallery ORDER BY created_at DESC").fetchall(); db.close()
    return render_template('admin_gallery.html',gallery=g)

@app.route('/admin/gallery/add',methods=['POST'])
@perm_req('can_manage_gallery')
def admin_add_gallery():
    cat=request.form.get('category','General')
    path=save_file(request.files.get('image'),f'gallery/{cat.lower().replace(" ","_")}',allowed_img)
    if path:
        db=get_db()
        db.execute("INSERT INTO gallery(title,category,image_path,description,event_date) VALUES(?,?,?,?,?)",
            (request.form['title'],cat,path,request.form.get('description'),request.form.get('event_date')))
        db.commit(); db.close(); flash('Photo added!','success')
    else: flash('Select a valid image.','error')
    return redirect(url_for('admin_gallery'))

@app.route('/admin/gallery/delete/<int:i>')
@perm_req('can_manage_gallery')
def admin_delete_gallery(i):
    db=get_db(); item=db.execute("SELECT * FROM gallery WHERE id=?",(i,)).fetchone()
    if item:
        p=os.path.join(UPLOAD,item['image_path'])
        if os.path.exists(p): os.remove(p)
        db.execute("DELETE FROM gallery WHERE id=?",(i,)); db.commit()
    db.close(); flash('Deleted.','success'); return redirect(url_for('admin_gallery'))

# ══════════════════════════════════════════════════════
# ADMIN – FACILITIES
# ══════════════════════════════════════════════════════
@app.route('/admin/facilities')
@perm_req('can_manage_facilities')
def admin_facilities():
    db=get_db(); f=db.execute("SELECT * FROM facilities ORDER BY sort_order,id").fetchall(); db.close()
    return render_template('admin_facilities.html',facilities=f)

@app.route('/admin/facilities/add',methods=['POST'])
@perm_req('can_manage_facilities')
def admin_add_facility():
    photo=save_file(request.files.get('photo'),'facilities',allowed_img); f=request.form; db=get_db()
    db.execute("INSERT INTO facilities(name,description,details,photo,icon,sort_order) VALUES(?,?,?,?,?,?)",
        (f['name'],f.get('description',''),f.get('details',''),photo,f.get('icon','🏫'),int(f.get('sort_order',99))))
    db.commit(); db.close(); flash('Facility added!','success'); return redirect(url_for('admin_facilities'))

@app.route('/admin/facilities/edit/<int:i>',methods=['POST'])
@perm_req('can_manage_facilities')
def admin_edit_facility(i):
    photo=save_file(request.files.get('photo'),'facilities',allowed_img); f=request.form; db=get_db()
    if photo: db.execute("UPDATE facilities SET name=?,description=?,details=?,photo=?,icon=?,sort_order=? WHERE id=?",
        (f['name'],f.get('description'),f.get('details'),photo,f.get('icon','🏫'),int(f.get('sort_order',99)),i))
    else: db.execute("UPDATE facilities SET name=?,description=?,details=?,icon=?,sort_order=? WHERE id=?",
        (f['name'],f.get('description'),f.get('details'),f.get('icon','🏫'),int(f.get('sort_order',99)),i))
    db.commit(); db.close(); flash('Updated!','success'); return redirect(url_for('admin_facilities'))

@app.route('/admin/facilities/toggle/<int:i>')
@perm_req('can_manage_facilities')
def admin_toggle_facility(i):
    db=get_db(); cur=db.execute("SELECT is_active FROM facilities WHERE id=?",(i,)).fetchone()
    if cur: db.execute("UPDATE facilities SET is_active=? WHERE id=?",(0 if cur['is_active'] else 1,i)); db.commit()
    db.close(); flash('Updated.','success'); return redirect(url_for('admin_facilities'))

@app.route('/admin/facilities/delete/<int:i>')
@perm_req('can_manage_facilities')
def admin_delete_facility(i):
    db=get_db(); item=db.execute("SELECT * FROM facilities WHERE id=?",(i,)).fetchone()
    if item and item['photo']:
        p=os.path.join(UPLOAD,item['photo'])
        if os.path.exists(p): os.remove(p)
    db.execute("DELETE FROM facilities WHERE id=?",(i,)); db.commit(); db.close()
    flash('Deleted.','success'); return redirect(url_for('admin_facilities'))

# ══════════════════════════════════════════════════════
# ADMIN – TEACHERS / ROUTINES / EVENTS
# ══════════════════════════════════════════════════════
@app.route('/admin/teachers')
@perm_req('can_manage_teachers')
def admin_teachers():
    db=get_db(); t=db.execute("SELECT * FROM teachers ORDER BY sort_order,id").fetchall(); db.close()
    return render_template('admin_teachers.html',teachers=t)

@app.route('/admin/teachers/add',methods=['POST'])
@perm_req('can_manage_teachers')
def admin_add_teacher():
    photo=save_file(request.files.get('photo'),'teachers',allowed_img); f=request.form; db=get_db()
    db.execute("INSERT INTO teachers(name,designation,subject,qualification,experience,phone,email,photo,sort_order) VALUES(?,?,?,?,?,?,?,?,?)",
        (f['name'],f.get('designation'),f.get('subject'),f.get('qualification'),f.get('experience'),
         f.get('phone'),f.get('email'),photo,int(f.get('sort_order',99))))
    db.commit(); db.close(); flash('Teacher added!','success'); return redirect(url_for('admin_teachers'))

@app.route('/admin/teachers/delete/<int:i>')
@perm_req('can_manage_teachers')
def admin_delete_teacher(i):
    db=get_db(); db.execute("DELETE FROM teachers WHERE id=?",(i,)); db.commit(); db.close()
    flash('Removed.','success'); return redirect(url_for('admin_teachers'))

@app.route('/admin/routines')
@perm_req('can_manage_routines')
def admin_routines():
    db=get_db()
    af, afp = access_filter(session['admin_id'])
    r=db.execute(f"SELECT * FROM routines WHERE 1=1{af} ORDER BY class,section,day,period", afp).fetchall()
    db.close()
    return render_template('admin_routines.html',routines=r,admin_perms=get_admin_perms(session['admin_id']))

@app.route('/admin/routines/add',methods=['POST'])
@perm_req('can_manage_routines')
def admin_add_routine():
    f=request.form
    if not can_touch_class(f['class'], f['section']):
        flash("You don't have permission to add a routine entry for this class/section.", 'error')
        return redirect(url_for('admin_routines'))
    db=get_db()
    db.execute("INSERT INTO routines(class,section,day,period,subject,teacher,time_slot) VALUES(?,?,?,?,?,?,?)",
        (f['class'],f['section'],f['day'],f['period'],f['subject'],f.get('teacher'),f.get('time_slot')))
    db.commit(); db.close(); flash('Entry added!','success'); return redirect(url_for('admin_routines'))

@app.route('/admin/routines/delete/<int:i>')
@perm_req('can_manage_routines')
def admin_delete_routine(i):
    db=get_db()
    row = db.execute("SELECT class,section FROM routines WHERE id=?", (i,)).fetchone()
    if row and not can_touch_class(row['class'], row['section']):
        db.close(); flash("You don't have permission to delete this entry.", 'error')
        return redirect(url_for('admin_routines'))
    db.execute("DELETE FROM routines WHERE id=?",(i,)); db.commit(); db.close()
    flash('Deleted.','success'); return redirect(url_for('admin_routines'))


@app.route('/admin/events')
@perm_req('can_manage_events')
def admin_events():
    db=get_db(); e=db.execute("SELECT * FROM events ORDER BY event_date DESC").fetchall(); db.close()
    return render_template('admin_events.html',events=e)

@app.route('/admin/events/add',methods=['POST'])
@perm_req('can_manage_events')
def admin_add_event():
    f=request.form; db=get_db()
    db.execute("INSERT INTO events(title,description,event_date,event_type) VALUES(?,?,?,?)",
        (f['title'],f.get('description'),f['event_date'],f.get('event_type','General')))
    db.commit(); db.close(); flash('Event added!','success'); return redirect(url_for('admin_events'))

@app.route('/admin/events/delete/<int:i>')
@perm_req('can_manage_events')
def admin_delete_event(i):
    db=get_db(); db.execute("DELETE FROM events WHERE id=?",(i,)); db.commit(); db.close()
    flash('Deleted.','success'); return redirect(url_for('admin_events'))

# ══════════════════════════════════════════════════════
# ADMIN – STUDENTS (paginated + search + bulk import)
# ══════════════════════════════════════════════════════
@app.route('/admin/students')
@perm_req('can_manage_students')
def admin_students():
    cls=request.args.get('class',''); sec=request.args.get('section','')
    search=request.args.get('search','').strip(); page=max(1,int(request.args.get('page',1)))
    db=get_db()
    q="SELECT * FROM students WHERE 1=1"; p=[]
    if cls: q+=" AND class=?"; p.append(cls)
    if sec: q+=" AND section=?"; p.append(sec)
    if search: q+=" AND (name LIKE ? OR roll_number LIKE ?)"; p+=[f'%{search}%',f'%{search}%']
    af, afp = access_filter(session['admin_id']); q += af; p += afp
    total=db.execute(f"SELECT COUNT(*) FROM ({q}) t",p).fetchone()[0]
    offset=(page-1)*PER_PAGE
    students=db.execute(f"{q} ORDER BY class,section,roll_number+0 LIMIT {PER_PAGE} OFFSET {offset}",p).fetchall()
    db.close()
    tp=max(1,(total+PER_PAGE-1)//PER_PAGE)
    pag=dict(page=page,total=total,total_pages=tp,has_prev=page>1,has_next=page<tp)
    perms = get_admin_perms(session['admin_id'])
    return render_template('admin_students.html',students=students,pagination=pag,
                           filter_class=cls,filter_section=sec,search=search,admin_perms=perms)

@app.route('/admin/students/add',methods=['POST'])
@perm_req('can_manage_students')
def admin_add_student():
    f=request.form
    if not can_touch_class(f['class'], f['section']):
        flash("You don't have permission to add students to this class/section.", 'error')
        return redirect(url_for('admin_students'))
    pw=hash_pw(request.form.get('password','student123')); db=get_db()
    try:
        db.execute("INSERT INTO students(roll_number,name,class,section,password,guardian,phone) VALUES(?,?,?,?,?,?,?)",
            (f['roll_number'],f['name'],f['class'],f['section'],pw,f.get('guardian'),f.get('phone')))
        db.commit(); flash('Student added!','success')
    except: flash(f'Error: Roll {f["roll_number"]} already exists in Class {f["class"]}-{f["section"]}.','error')
    db.close(); return redirect(url_for('admin_students'))

@app.route('/admin/students/delete/<int:i>')
@perm_req('can_manage_students')
def admin_delete_student(i):
    db=get_db()
    row = db.execute("SELECT class,section FROM students WHERE id=?", (i,)).fetchone()
    if row and not can_touch_class(row['class'], row['section']):
        db.close(); flash("You don't have permission to remove this student.", 'error')
        return redirect(url_for('admin_students'))
    db.execute("DELETE FROM students WHERE id=?",(i,)); db.commit(); db.close()
    flash('Removed.','success'); return redirect(url_for('admin_students'))

@app.route('/admin/students/bulk',methods=['POST'])
@perm_req('can_manage_students')
def admin_bulk_students():
    """CSV bulk: roll,name,guardian,phone"""
    cls=request.form.get('class',''); sec=request.form.get('section','')
    if not can_touch_class(cls, sec):
        flash("You don't have permission to import students into this class/section.", 'error')
        return redirect(url_for('admin_students'))
    raw=request.form.get('bulk_data','').strip()
    dpw=hash_pw('student123'); count=0; errs=0; db=get_db()
    for line in raw.splitlines():
        p=[x.strip() for x in line.split(',')]
        if len(p)<2: continue
        try:
            db.execute("INSERT OR IGNORE INTO students(roll_number,name,class,section,password,guardian,phone) VALUES(?,?,?,?,?,?,?)",
                (p[0],p[1],cls,sec,dpw,p[2] if len(p)>2 else '',p[3] if len(p)>3 else ''))
            count+=1
        except: errs+=1
    db.commit(); db.close()
    flash(f'{count} students imported!{" ("+str(errs)+" skipped)" if errs else ""}','success')
    return redirect(url_for('admin_students'))


# ══════════════════════════════════════════════════════
# ADMIN – ATTENDANCE (single + bulk daily marking)
# ══════════════════════════════════════════════════════
@app.route('/admin/attendance')
@perm_req('can_manage_attendance')
def admin_attendance():
    perms = get_admin_perms(session['admin_id'])
    cls=request.args.get('class',''); sec=request.args.get('section','')
    # Restricted admins default to (and are locked to) their first assigned class
    if perms['scope'] == 'restricted':
        if not perms['classes']:
            flash('No classes have been assigned to your account yet. Contact your developer/admin.', 'error')
            return render_template('admin_attendance.html', students=[], attendance=[],
                                   filter_class='', filter_section='', date_filter='', admin_perms=perms)
        if (cls, sec) not in perms['classes']:
            cls, sec = perms['classes'][0]
    else:
        cls = cls or '10'; sec = sec or 'A'
    date_f=request.args.get('date','')
    db=get_db()
    students=db.execute("SELECT * FROM students WHERE class=? AND section=? ORDER BY roll_number+0",(cls,sec)).fetchall()
    q="SELECT * FROM attendance WHERE class=? AND section=?"; p=[cls,sec]
    if date_f: q+=" AND date=?"; p.append(date_f)
    att=db.execute(q+" ORDER BY date DESC LIMIT 300",p).fetchall()
    db.close()
    return render_template('admin_attendance.html',students=students,attendance=att,
                           filter_class=cls,filter_section=sec,date_filter=date_f,admin_perms=perms)

@app.route('/admin/attendance/mark',methods=['POST'])
@perm_req('can_manage_attendance')
def admin_mark_attendance():
    f=request.form
    if not can_touch_class(f['class'], f['section']):
        flash("You don't have permission to mark attendance for this class/section.", 'error')
        return redirect(url_for('admin_attendance'))
    db=get_db()
    db.execute("INSERT OR REPLACE INTO attendance(roll_number,class,section,date,status) VALUES(?,?,?,?,?)",
        (f['roll_number'],f['class'],f['section'],f['date'],f['status']))
    db.commit(); db.close(); flash('Marked!','success')
    return redirect(url_for('admin_attendance',**{'class':f['class'],'section':f['section']}))

@app.route('/admin/attendance/bulk',methods=['POST'])
@perm_req('can_manage_attendance')
def admin_bulk_attendance():
    """Mark ALL students present/absent for a date."""
    cls=request.form.get('class'); sec=request.form.get('section')
    if not can_touch_class(cls, sec):
        flash("You don't have permission to mark attendance for this class/section.", 'error')
        return redirect(url_for('admin_attendance'))
    date=request.form.get('date'); status=request.form.get('status','Present')
    db=get_db()
    students=db.execute("SELECT roll_number FROM students WHERE class=? AND section=?",(cls,sec)).fetchall()
    for s in students:
        db.execute("INSERT OR REPLACE INTO attendance(roll_number,class,section,date,status) VALUES(?,?,?,?,?)",(s[0],cls,sec,date,status))
    db.commit(); db.close()
    flash(f'{len(students)} students marked as {status} for {date}.','success')
    return redirect(url_for('admin_attendance',**{'class':cls,'section':sec}))

# ══════════════════════════════════════════════════════
# ADMIN – SETTINGS
# ══════════════════════════════════════════════════════
@app.route('/admin/settings')
@perm_req('can_view_settings')
def admin_settings(): return render_template('admin_settings.html',settings=get_settings())

@app.route('/admin/settings/save',methods=['POST'])
@perm_req('can_view_settings')
def admin_save_settings():
    db=get_db()
    for k in ['school_name','tagline','principal_name','principal_message','phone','email','address',
               'established','hero_subtitle','hero_badge_text','school_type','affiliation',
               'stat1_val','stat1_label','stat2_val','stat2_label','stat3_val','stat3_label','stat4_val','stat4_label',
               'ach1_val','ach1_label','ach2_val','ach2_label','ach3_val','ach3_label','ach4_val','ach4_label',
               'footer_about','notice_board_title','facebook_url','youtube_url','whatsapp_number',
               'contact_map_embed','homepage_show_facilities','homepage_show_gallery',
               'homepage_show_teachers','homepage_show_achievements',
               'school_video_youtube','video_section_title']:
        v=request.form.get(k)
        if v is not None:
            db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",(k,v))
    db.commit(); db.close(); cache_clear()
    flash('Settings saved!','success'); return redirect(url_for('admin_settings'))

# ══════════════════════════════════════════════════════
# ADMIN – DATABASE TOOLS
# ══════════════════════════════════════════════════════
@app.route('/admin/db/stats')
@perm_req('can_view_settings')
def admin_db_stats():
    import time
    db=get_db()
    stats={'engine':'PostgreSQL' if USE_PG else 'SQLite (WAL mode)'}
    for t in ['students','results','attendance','notices','assignments','materials','routines','gallery']:
        try: stats[t]=db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except: stats[t]=0
    t0=time.time()
    db.execute("SELECT * FROM results WHERE class='10' AND section='A' AND exam_name='Annual Exam 2024-25' LIMIT 50").fetchall()
    stats['result_query_ms']=round((time.time()-t0)*1000,2)
    t0=time.time()
    db.execute("SELECT * FROM students WHERE class='10' AND section='A' LIMIT 50").fetchall()
    stats['student_query_ms']=round((time.time()-t0)*1000,2)
    if not USE_PG:
        stats['journal_mode']=db.execute("PRAGMA journal_mode").fetchone()[0]
        stats['cache_size_kb']=abs(db.execute("PRAGMA cache_size").fetchone()[0])*4
        idxs=db.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        stats['index_count']=len(idxs)
    db.close()
    return jsonify(stats)

@app.route('/admin/db/vacuum')
@perm_req('can_view_settings')
def admin_db_vacuum():
    if not USE_PG:
        db=get_db(); db.execute("VACUUM"); db.execute("ANALYZE"); db.close()
        flash('Database vacuumed and optimized!','success')
    else: flash('Not needed for PostgreSQL.','info')
    return redirect(url_for('admin_settings'))

@app.route('/admin/db/backup')
@perm_req('can_view_settings')
def admin_db_backup():
    if USE_PG: flash('Use pg_dump for PostgreSQL backups.','info'); return redirect(url_for('admin_settings'))
    ts=datetime.now().strftime("%Y%m%d_%H%M%S")
    bp=f'/tmp/school_backup_{ts}.db'
    shutil.copy2(DB_PATH,bp)
    return send_file(bp,as_attachment=True,download_name=f'pundibari_school_{ts}.db')

# ══════════════════════════════════════════════════════
# ★ DEVELOPER MODE — Super Admin (above all admins)
# ══════════════════════════════════════════════════════

def init_dev():
    """Initialize developer/super-admin tables + migrate existing DBs safely."""
    db = get_db(); c = db.cursor()
    c.executescript("""
    -- Developer accounts (super-admins)
    CREATE TABLE IF NOT EXISTS dev_accounts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
        name TEXT, email TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);

    -- Permission scopes: what class/section each admin/teacher controls
    CREATE TABLE IF NOT EXISTS admin_permissions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER NOT NULL,
        scope TEXT DEFAULT 'all',
        can_manage_notices INTEGER DEFAULT 1,
        can_manage_results INTEGER DEFAULT 1,
        can_manage_attendance INTEGER DEFAULT 1,
        can_manage_assignments INTEGER DEFAULT 1,
        can_manage_materials INTEGER DEFAULT 1,
        can_manage_gallery INTEGER DEFAULT 0,
        can_manage_teachers INTEGER DEFAULT 0,
        can_manage_students INTEGER DEFAULT 0,
        can_manage_routines INTEGER DEFAULT 1,
        can_manage_events INTEGER DEFAULT 0,
        can_manage_facilities INTEGER DEFAULT 0,
        can_view_settings INTEGER DEFAULT 0,
        FOREIGN KEY(admin_id) REFERENCES admins(id) ON DELETE CASCADE);

    -- Which classes/sections each restricted admin can access
    CREATE TABLE IF NOT EXISTS admin_class_access(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER NOT NULL,
        class TEXT NOT NULL, section TEXT NOT NULL,
        FOREIGN KEY(admin_id) REFERENCES admins(id) ON DELETE CASCADE);

    -- Activity log
    CREATE TABLE IF NOT EXISTS activity_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_type TEXT, actor_id INTEGER, actor_name TEXT,
        action TEXT, detail TEXT,
        ip TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    """)

    # Safe migrations for DBs created before these columns existed
    for stmt in [
        "ALTER TABLE admins ADD COLUMN role TEXT DEFAULT 'admin'",
        "ALTER TABLE admins ADD COLUMN email TEXT DEFAULT ''",
        "ALTER TABLE admins ADD COLUMN is_active INTEGER DEFAULT 1",
        "ALTER TABLE admins ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE admin_permissions ADD COLUMN can_manage_routines INTEGER DEFAULT 1",
        "ALTER TABLE admin_permissions ADD COLUMN can_manage_events INTEGER DEFAULT 0",
        "ALTER TABLE admin_permissions ADD COLUMN can_manage_facilities INTEGER DEFAULT 0",
    ]:
        try: c.execute(stmt)
        except Exception: pass

    # Default developer account
    dpw = hash_pw('dev@rgl2024')
    c.execute("INSERT OR IGNORE INTO dev_accounts(username,password,name,email) VALUES(?,?,?,?)",
              ('developer', dpw, 'Developer / Super Admin', 'dev@pundibari.in'))

    # Full permissions for the default admin account
    admin = db.execute("SELECT id FROM admins WHERE username='admin'").fetchone()
    if admin:
        c.execute("""INSERT OR IGNORE INTO admin_permissions
            (admin_id,scope,can_manage_notices,can_manage_results,can_manage_attendance,
             can_manage_assignments,can_manage_materials,can_manage_gallery,
             can_manage_teachers,can_manage_students,can_manage_routines,
             can_manage_events,can_manage_facilities,can_view_settings)
            VALUES(?,?,1,1,1,1,1,1,1,1,1,1,1,1)""", (admin['id'], 'all'))

    db.commit(); db.close()

def log_activity(actor_type, actor_id, actor_name, action, detail=''):
    try:
        db = get_db()
        ip = request.remote_addr or ''
        db.execute("INSERT INTO activity_log(actor_type,actor_id,actor_name,action,detail,ip) VALUES(?,?,?,?,?,?)",
                   (actor_type, actor_id, actor_name, action, detail, ip))
        db.commit(); db.close()
    except: pass

# ── Auto-log every admin write action (adds, edits, deletes, uploads) ──
# Maps Flask endpoint name -> (short action code, function returning a detail string)
ADMIN_LOG_ENDPOINTS = {
    'admin_add_notice':        ('ADD_NOTICE',        lambda: request.form.get('title','')),
    'admin_delete_notice':     ('DELETE_NOTICE',      lambda: f"id={request.view_args.get('i')}"),
    'admin_add_result':        ('ADD_RESULT',         lambda: f"{request.form.get('student_name','')} · {request.form.get('subject','')} · {request.form.get('class','')}-{request.form.get('section','')}"),
    'admin_delete_result':     ('DELETE_RESULT',      lambda: f"id={request.view_args.get('i')}"),
    'admin_bulk_results':      ('BULK_IMPORT_RESULTS',lambda: f"Class {request.form.get('class','')}-{request.form.get('section','')}, exam: {request.form.get('exam_name','')}"),
    'admin_add_assignment':    ('ADD_ASSIGNMENT',     lambda: request.form.get('title','')),
    'admin_add_material':      ('ADD_MATERIAL',       lambda: request.form.get('title','')),
    'admin_add_gallery':       ('ADD_GALLERY_PHOTO',  lambda: request.form.get('title','')),
    'admin_delete_gallery':    ('DELETE_GALLERY_PHOTO',lambda: f"id={request.view_args.get('i')}"),
    'admin_add_facility':      ('ADD_FACILITY',       lambda: request.form.get('name','')),
    'admin_edit_facility':     ('EDIT_FACILITY',      lambda: f"id={request.view_args.get('i')}"),
    'admin_toggle_facility':   ('TOGGLE_FACILITY',    lambda: f"id={request.view_args.get('i')}"),
    'admin_delete_facility':   ('DELETE_FACILITY',    lambda: f"id={request.view_args.get('i')}"),
    'admin_add_teacher':       ('ADD_TEACHER',        lambda: request.form.get('name','')),
    'admin_edit_teacher':      ('EDIT_TEACHER',       lambda: f"id={request.view_args.get('tid')}"),
    'admin_delete_teacher':    ('DELETE_TEACHER',     lambda: f"id={request.view_args.get('i')}"),
    'admin_add_routine':       ('ADD_ROUTINE',        lambda: f"{request.form.get('class','')}-{request.form.get('section','')} {request.form.get('day','')}"),
    'admin_delete_routine':    ('DELETE_ROUTINE',     lambda: f"id={request.view_args.get('i')}"),
    'admin_add_event':         ('ADD_EVENT',          lambda: request.form.get('title','')),
    'admin_delete_event':      ('DELETE_EVENT',       lambda: f"id={request.view_args.get('i')}"),
    'admin_add_student':       ('ADD_STUDENT',        lambda: f"{request.form.get('name','')} ({request.form.get('class','')}-{request.form.get('section','')})"),
    'admin_delete_student':    ('DELETE_STUDENT',     lambda: f"id={request.view_args.get('i')}"),
    'admin_bulk_students':     ('BULK_IMPORT_STUDENTS',lambda: f"Class {request.form.get('class','')}-{request.form.get('section','')}"),
    'admin_mark_attendance':   ('MARK_ATTENDANCE',    lambda: f"Roll {request.form.get('roll_number','')} → {request.form.get('status','')} ({request.form.get('date','')})"),
    'admin_bulk_attendance':   ('BULK_ATTENDANCE',    lambda: f"Class {request.form.get('class','')}-{request.form.get('section','')} → {request.form.get('status','')} ({request.form.get('date','')})"),
    'admin_save_settings':     ('UPDATE_SETTINGS',    lambda: 'Site settings updated'),
    'admin_upload_logo':       ('UPLOAD_LOGO',        lambda: ''),
    'admin_remove_logo':       ('REMOVE_LOGO',        lambda: ''),
    'admin_upload_hero':       ('UPLOAD_HERO_IMAGE',  lambda: ''),
    'admin_remove_hero':       ('REMOVE_HERO_IMAGE',  lambda: ''),
    'admin_upload_principal':  ('UPLOAD_PRINCIPAL_PHOTO', lambda: ''),
    'admin_remove_principal':  ('REMOVE_PRINCIPAL_PHOTO', lambda: ''),
    'admin_upload_video':      ('UPLOAD_SCHOOL_VIDEO', lambda: ''),
    'admin_remove_video':      ('REMOVE_SCHOOL_VIDEO', lambda: ''),
    'admin_db_vacuum':         ('VACUUM_DB',          lambda: ''),
    'admin_db_backup':         ('DOWNLOAD_BACKUP',    lambda: ''),
}

@app.after_request
def _auto_log_admin_activity(response):
    try:
        ep = request.endpoint
        if ep in ADMIN_LOG_ENDPOINTS and 'admin_id' in session:
            action, detail_fn = ADMIN_LOG_ENDPOINTS[ep]
            try: detail = detail_fn()
            except Exception: detail = ''
            log_activity('admin', session['admin_id'], session.get('admin_name',''), action, detail)
    except Exception:
        pass
    return response

def dev_req(f):
    @wraps(f)
    def d(*a, **k):
        if 'dev_id' not in session:
            flash('Developer access required.', 'error')
            return redirect(url_for('dev_login'))
        return f(*a, **k)
    return d

def get_admin_perms(admin_id):
    """Get permissions for an admin. Returns dict."""
    db = get_db()
    perm = db.execute("SELECT * FROM admin_permissions WHERE admin_id=?", (admin_id,)).fetchone()
    classes = db.execute("SELECT class, section FROM admin_class_access WHERE admin_id=?", (admin_id,)).fetchall()
    db.close()
    if not perm:
        return {'scope': 'all', 'classes': [], 'can_manage_notices':1,'can_manage_results':1,
                'can_manage_attendance':1,'can_manage_assignments':1,'can_manage_materials':1,
                'can_manage_gallery':1,'can_manage_teachers':1,'can_manage_students':1,
                'can_manage_routines':1,'can_manage_events':1,'can_manage_facilities':1,
                'can_view_settings':1}
    d = dict(perm)
    d['classes'] = [(r['class'], r['section']) for r in classes]
    return d

def check_class_access(admin_id, cls, sec):
    """Returns True if admin can access this class-section."""
    perms = get_admin_perms(admin_id)
    if perms['scope'] == 'all': return True
    return (cls, sec) in perms['classes']

# ── DEV LOGIN ──────────────────────────────────────────
@app.route('/dev/login', methods=['GET', 'POST'])
def dev_login():
    if request.method == 'POST':
        u = request.form.get('username','').strip()
        pw = hash_pw(request.form.get('password',''))
        db = get_db()
        try:
            dev = db.execute("SELECT * FROM dev_accounts WHERE username=? AND password=?", (u, pw)).fetchone()
        except Exception:
            dev = None
        db.close()
        if dev:
            session.update({'dev_id': dev['id'], 'dev_name': dev['name']})
            log_activity('developer', dev['id'], dev['name'], 'LOGIN')
            return redirect(url_for('dev_dashboard'))
        log_activity('developer', None, u, 'LOGIN_FAILED', 'Invalid credentials')
        flash('Invalid developer credentials.', 'error')
    return render_template('dev_login.html')

@app.route('/dev/logout')
def dev_logout():
    if 'dev_id' in session:
        log_activity('developer', session['dev_id'], session.get('dev_name',''), 'LOGOUT')
    session.pop('dev_id', None); session.pop('dev_name', None)
    return redirect(url_for('dev_login'))

# ── DEV DASHBOARD ──────────────────────────────────────
@app.route('/dev/')
@app.route('/dev/dashboard')
@dev_req
def dev_dashboard():
    db = get_db()
    stats = {k: db.execute(q).fetchone()[0] for k,q in [
        ('students', "SELECT COUNT(*) FROM students"),
        ('teachers', "SELECT COUNT(*) FROM teachers WHERE is_active=1"),
        ('admins',   "SELECT COUNT(*) FROM admins WHERE is_active=1"),
        ('notices',  "SELECT COUNT(*) FROM notices"),
        ('results',  "SELECT COUNT(*) FROM results"),
        ('attendance',"SELECT COUNT(*) FROM attendance"),
        ('assignments',"SELECT COUNT(*) FROM assignments"),
        ('facilities',"SELECT COUNT(*) FROM facilities WHERE is_active=1"),
    ]}
    admins   = db.execute("SELECT a.*,p.scope FROM admins a LEFT JOIN admin_permissions p ON a.id=p.admin_id ORDER BY a.id").fetchall()
    logs     = db.execute("SELECT * FROM activity_log ORDER BY created_at DESC LIMIT 20").fetchall()
    # Students per class (used in dev dashboard chart)
    monthly  = db.execute("""
        SELECT class as m, COUNT(*) as cnt
        FROM students
        GROUP BY class ORDER BY class+0
    """).fetchall()
    db.close()
    return render_template('dev_dashboard.html', stats=stats, admins=admins,
                           logs=logs, monthly=monthly)

# ── DEV — MANAGE ADMINS ────────────────────────────────
@app.route('/dev/admins')
@dev_req
def dev_admins():
    db = get_db()
    admins = db.execute("""
        SELECT a.*, p.scope,
               p.can_manage_notices, p.can_manage_results, p.can_manage_attendance,
               p.can_manage_assignments, p.can_manage_materials, p.can_manage_gallery,
               p.can_manage_teachers, p.can_manage_students, p.can_manage_routines,
               p.can_manage_events, p.can_manage_facilities, p.can_view_settings
        FROM admins a
        LEFT JOIN admin_permissions p ON a.id=p.admin_id
        ORDER BY a.id
    """).fetchall()
    db.close()
    return render_template('dev_admins.html', admins=admins)

@app.route('/dev/admins/add', methods=['POST'])
@dev_req
def dev_add_admin():
    f = request.form
    pw = hash_pw(f.get('password','admin123'))
    db = get_db()
    try:
        db.execute("INSERT INTO admins(username,password,name,email,role) VALUES(?,?,?,?,?)",
                   (f['username'], pw, f['name'], f.get('email',''), f.get('role','admin')))
        admin_id = db.execute("SELECT id FROM admins WHERE username=?", (f['username'],)).fetchone()['id']
        scope = f.get('scope', 'all')
        db.execute("""INSERT INTO admin_permissions
            (admin_id,scope,can_manage_notices,can_manage_results,can_manage_attendance,
             can_manage_assignments,can_manage_materials,can_manage_gallery,
             can_manage_teachers,can_manage_students,can_manage_routines,
             can_manage_events,can_manage_facilities,can_view_settings)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (admin_id, scope,
             1 if f.get('p_notices') else 0,
             1 if f.get('p_results') else 0,
             1 if f.get('p_attendance') else 0,
             1 if f.get('p_assignments') else 0,
             1 if f.get('p_materials') else 0,
             1 if f.get('p_gallery') else 0,
             1 if f.get('p_teachers') else 0,
             1 if f.get('p_students') else 0,
             1 if f.get('p_routines') else 0,
             1 if f.get('p_events') else 0,
             1 if f.get('p_facilities') else 0,
             1 if f.get('p_settings') else 0))

        # Add class access if restricted
        if scope == 'restricted':
            classes = request.form.getlist('classes[]')
            sections = request.form.getlist('sections[]')
            for cls, sec in zip(classes, sections):
                if cls and sec:
                    db.execute("INSERT INTO admin_class_access(admin_id,class,section) VALUES(?,?,?)",
                               (admin_id, cls, sec))
        db.commit()
        log_activity('developer', session['dev_id'], session['dev_name'],
                     'ADD_ADMIN', f"Added admin: {f['username']}")
        flash(f'Admin "{f["username"]}" created successfully!', 'success')
    except Exception as e:
        flash(f'Error: Username may already exist.', 'error')
    db.close()
    return redirect(url_for('dev_admins'))

@app.route('/dev/admins/permissions/<int:aid>', methods=['POST'])
@dev_req
def dev_update_permissions(aid):
    f = request.form; db = get_db()
    scope = f.get('scope','all')
    db.execute("""INSERT OR REPLACE INTO admin_permissions
        (admin_id,scope,can_manage_notices,can_manage_results,can_manage_attendance,
         can_manage_assignments,can_manage_materials,can_manage_gallery,
         can_manage_teachers,can_manage_students,can_manage_routines,
         can_manage_events,can_manage_facilities,can_view_settings)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (aid, scope,
         1 if f.get('p_notices') else 0,
         1 if f.get('p_results') else 0,
         1 if f.get('p_attendance') else 0,
         1 if f.get('p_assignments') else 0,
         1 if f.get('p_materials') else 0,
         1 if f.get('p_gallery') else 0,
         1 if f.get('p_teachers') else 0,
         1 if f.get('p_students') else 0,
         1 if f.get('p_routines') else 0,
         1 if f.get('p_events') else 0,
         1 if f.get('p_facilities') else 0,
         1 if f.get('p_settings') else 0))
    # Update class access
    db.execute("DELETE FROM admin_class_access WHERE admin_id=?", (aid,))
    if scope == 'restricted':
        classes  = request.form.getlist('classes[]')
        sections = request.form.getlist('sections[]')
        for cls, sec in zip(classes, sections):
            if cls and sec:
                db.execute("INSERT INTO admin_class_access(admin_id,class,section) VALUES(?,?,?)",
                           (aid, cls, sec))
    db.commit(); db.close()
    log_activity('developer', session['dev_id'], session['dev_name'],
                 'UPDATE_PERM', f"Updated permissions for admin id={aid}")
    flash('Permissions updated!', 'success')
    return redirect(url_for('dev_admins'))

@app.route('/dev/admins/toggle/<int:aid>')
@dev_req
def dev_toggle_admin(aid):
    db = get_db()
    cur = db.execute("SELECT is_active FROM admins WHERE id=?", (aid,)).fetchone()
    if cur:
        db.execute("UPDATE admins SET is_active=? WHERE id=?", (0 if cur['is_active'] else 1, aid))
        db.commit()
    db.close(); flash('Admin status updated.', 'success')
    return redirect(url_for('dev_admins'))

@app.route('/dev/admins/delete/<int:aid>')
@dev_req
def dev_delete_admin(aid):
    db = get_db()
    a = db.execute("SELECT username FROM admins WHERE id=?", (aid,)).fetchone()
    if a and a['username'] != 'admin':  # protect default admin
        db.execute("DELETE FROM admins WHERE id=?", (aid,))
        db.execute("DELETE FROM admin_permissions WHERE admin_id=?", (aid,))
        db.execute("DELETE FROM admin_class_access WHERE admin_id=?", (aid,))
        db.commit()
        flash(f'Admin removed.', 'success')
    else:
        flash('Cannot delete the default admin account.', 'error')
    db.close()
    return redirect(url_for('dev_admins'))

@app.route('/dev/admins/reset-password/<int:aid>', methods=['POST'])
@dev_req
def dev_reset_password(aid):
    new_pw = request.form.get('new_password','admin123')
    db = get_db()
    db.execute("UPDATE admins SET password=? WHERE id=?", (hash_pw(new_pw), aid))
    db.commit(); db.close()
    flash('Password reset successfully!', 'success')
    return redirect(url_for('dev_admins'))

# ── DEV — ACTIVITY LOG ─────────────────────────────────
@app.route('/dev/logs')
@dev_req
def dev_logs():
    page = max(1, int(request.args.get('page', 1)))
    actor_filter = request.args.get('actor', '')
    db = get_db()
    q = "SELECT * FROM activity_log WHERE 1=1"; p = []
    if actor_filter:
        q += " AND actor_type=?"; p.append(actor_filter)
    total = db.execute(f"SELECT COUNT(*) FROM ({q}) t", p).fetchone()[0]
    offset = (page - 1) * PER_PAGE
    logs = db.execute(f"{q} ORDER BY created_at DESC LIMIT {PER_PAGE} OFFSET {offset}", p).fetchall()
    db.close()
    tp = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    return render_template('dev_logs.html', logs=logs, actor_filter=actor_filter,
                           pagination=dict(page=page,total=total,total_pages=tp,
                                          has_prev=page>1,has_next=page<tp))

# ── DEV — DB TOOLS ────────────────────────────────────
@app.route('/dev/db')
@dev_req
def dev_db():
    db = get_db()
    tables = {}
    for t in ['students','results','attendance','notices','admins','teachers',
              'facilities','gallery','assignments','materials','routines','events','settings']:
        try: tables[t] = db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except: tables[t] = 0
    idxs = db.execute("SELECT name,tbl_name FROM sqlite_master WHERE type='index' ORDER BY tbl_name").fetchall()
    db.close()
    return render_template('dev_db.html', tables=tables, indexes=idxs)

@app.route('/dev/db/vacuum')
@dev_req
def dev_vacuum():
    db = get_db(); db.execute("VACUUM"); db.execute("ANALYZE"); db.close()
    log_activity('developer', session['dev_id'], session['dev_name'], 'VACUUM_DB')
    flash('Database vacuumed and optimized!', 'success')
    return redirect(url_for('dev_db'))

@app.route('/dev/db/backup')
@dev_req
def dev_backup():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bp = f'/tmp/pundibari_backup_{ts}.db'
    shutil.copy2(DB_PATH, bp)
    return send_file(bp, as_attachment=True,
                     download_name=f'pundibari_school_{ts}.db')

# ── DEV — SETTINGS ─────────────────────────────────────
@app.route('/dev/settings', methods=['GET', 'POST'])
@dev_req
def dev_settings():
    if request.method == 'POST':
        f = request.form
        db = get_db()
        dev_id = session['dev_id']
        # Update dev account info
        if f.get('new_password'):
            db.execute("UPDATE dev_accounts SET name=?,email=?,password=? WHERE id=?",
                       (f.get('name'), f.get('email'), hash_pw(f['new_password']), dev_id))
        else:
            db.execute("UPDATE dev_accounts SET name=?,email=? WHERE id=?",
                       (f.get('name'), f.get('email'), dev_id))
        db.commit(); db.close()
        flash('Developer settings saved!', 'success')
        return redirect(url_for('dev_settings'))
    db = get_db()
    dev = db.execute("SELECT * FROM dev_accounts WHERE id=?", (session['dev_id'],)).fetchone()
    db.close()
    return render_template('dev_settings.html', dev=dev)

# ── DEV — IMPERSONATION ("Login as Admin") ─────────────
@app.route('/dev/admins/login-as/<int:aid>')
@dev_req
def dev_login_as(aid):
    db = get_db()
    admin = db.execute("SELECT * FROM admins WHERE id=?", (aid,)).fetchone()
    db.close()
    if not admin:
        flash('Admin not found.', 'error')
        return redirect(url_for('dev_admins'))
    session['admin_id'] = admin['id']
    session['admin_name'] = admin['name']
    session['impersonating'] = True
    log_activity('developer', session['dev_id'], session['dev_name'],
                 'IMPERSONATE', f"Viewing panel as: {admin['username']}")
    flash(f"You're now viewing the panel as {admin['name']}.", 'info')
    return redirect(url_for('admin_dashboard'))

@app.route('/dev/exit-impersonation')
def dev_exit_impersonation():
    session.pop('admin_id', None)
    session.pop('admin_name', None)
    session.pop('impersonating', None)
    flash('Returned to Developer Panel.', 'success')
    if 'dev_id' in session:
        return redirect(url_for('dev_dashboard'))
    return redirect(url_for('dev_login'))

# ── DEV — SYSTEM INFO ───────────────────────────────────
@app.route('/dev/system')
@dev_req
def dev_system():
    import flask as _flask
    db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    img_size = 0
    if os.path.exists(UPLOAD):
        for root, dirs, files in os.walk(UPLOAD):
            for fn in files:
                try: img_size += os.path.getsize(os.path.join(root, fn))
                except Exception: pass
    uptime = datetime.now() - _START_TIME
    hrs, rem = divmod(int(uptime.total_seconds()), 3600)
    mins, secs = divmod(rem, 60)
    info = {
        'python_version': sys.version.split()[0],
        'flask_version': _flask.__version__,
        'platform': platform.system() + ' ' + platform.release(),
        'db_size_mb': round(db_size/1024/1024, 2),
        'images_size_mb': round(img_size/1024/1024, 2),
        'uptime': f"{hrs}h {mins}m {secs}s",
        'cache_entries': len(_cache),
        'engine': 'PostgreSQL' if USE_PG else 'SQLite (WAL mode)',
        'per_page': PER_PAGE,
    }
    return render_template('dev_system.html', info=info)

@app.route('/dev/cache/clear')
@dev_req
def dev_clear_cache():
    cache_clear()
    log_activity('developer', session['dev_id'], session['dev_name'], 'CLEAR_CACHE')
    flash('In-memory cache cleared — settings will reload fresh.', 'success')
    return redirect(request.referrer or url_for('dev_system'))

# ── DEV — GLOBAL SEARCH ─────────────────────────────────
@app.route('/dev/search')
@dev_req
def dev_search():
    q = request.args.get('q', '').strip()
    results = {'students': [], 'teachers': [], 'admins': []}
    if q and len(q) >= 2:
        db = get_db()
        results['students'] = db.execute(
            "SELECT * FROM students WHERE name LIKE ? OR roll_number LIKE ? ORDER BY class,section LIMIT 25",
            (f'%{q}%', f'%{q}%')).fetchall()
        results['teachers'] = db.execute(
            "SELECT * FROM teachers WHERE name LIKE ? OR subject LIKE ? LIMIT 25",
            (f'%{q}%', f'%{q}%')).fetchall()
        results['admins'] = db.execute(
            "SELECT * FROM admins WHERE name LIKE ? OR username LIKE ? LIMIT 25",
            (f'%{q}%', f'%{q}%')).fetchall()
        db.close()
    return render_template('dev_search.html', query=q, results=results)

# ── DEV — BULK: RESET ALL STUDENT PASSWORDS ────────────
@app.route('/dev/students/reset-all-passwords', methods=['POST'])
@dev_req
def dev_reset_all_passwords():
    new_pw = request.form.get('new_password', 'student123')
    db = get_db()
    count = db.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    db.execute("UPDATE students SET password=?", (hash_pw(new_pw),))
    db.commit(); db.close()
    log_activity('developer', session['dev_id'], session['dev_name'],
                 'BULK_RESET_PASSWORDS', f"Reset password for all {count} students")
    flash(f'Password reset to "{new_pw}" for all {count} students.', 'success')
    return redirect(url_for('dev_system'))

# ══════════════════════════════════════════════════════
# ★ TEACHER EDIT (with photo, full CRUD)
# ══════════════════════════════════════════════════════
@app.route('/admin/teachers/edit/<int:tid>', methods=['GET', 'POST'])
@perm_req('can_manage_teachers')
def admin_edit_teacher(tid):
    db = get_db()
    t = db.execute("SELECT * FROM teachers WHERE id=?", (tid,)).fetchone()
    db.close()
    if not t:
        flash('Teacher not found.', 'error')
        return redirect(url_for('admin_teachers'))
    if request.method == 'POST':
        f = request.form
        photo = save_file(request.files.get('photo'), 'teachers', allowed_img)
        db = get_db()
        if photo:
            # Remove old photo
            if t['photo']:
                old = os.path.join(UPLOAD, t['photo'])
                if os.path.exists(old): os.remove(old)
            db.execute("""UPDATE teachers SET name=?,designation=?,subject=?,qualification=?,
                experience=?,phone=?,email=?,photo=?,sort_order=?,is_active=? WHERE id=?""",
                (f['name'],f.get('designation'),f.get('subject'),f.get('qualification'),
                 f.get('experience'),f.get('phone'),f.get('email'),photo,
                 int(f.get('sort_order',99)),1 if f.get('is_active') else 0, tid))
        else:
            db.execute("""UPDATE teachers SET name=?,designation=?,subject=?,qualification=?,
                experience=?,phone=?,email=?,sort_order=?,is_active=? WHERE id=?""",
                (f['name'],f.get('designation'),f.get('subject'),f.get('qualification'),
                 f.get('experience'),f.get('phone'),f.get('email'),
                 int(f.get('sort_order',99)),1 if f.get('is_active') else 0, tid))
        db.commit(); db.close()
        flash(f'Teacher "{f["name"]}" updated!', 'success')
        return redirect(url_for('admin_teachers'))
    return render_template('admin_teacher_edit.html', teacher=t)

# ══════════════════════════════════════════════════════
# ★ ATTENDANCE GRAPHS — API endpoints
# ══════════════════════════════════════════════════════
@app.route('/admin/attendance/stats')
@perm_req('can_manage_attendance')
def admin_attendance_stats():
    cls = request.args.get('class','10')
    sec = request.args.get('section','A')
    db = get_db()

    # Daily attendance for last 30 days
    daily = db.execute("""
        SELECT date, status, COUNT(*) as cnt
        FROM attendance WHERE class=? AND section=?
        AND date >= date('now','-30 days')
        GROUP BY date, status ORDER BY date
    """, (cls, sec)).fetchall()

    # Weekly summary
    weekly = db.execute("""
        SELECT strftime('%W', date) as week,
               SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END) as present,
               SUM(CASE WHEN status='Absent' THEN 1 ELSE 0 END) as absent,
               COUNT(*) as total
        FROM attendance WHERE class=? AND section=?
        AND date >= date('now','-8 weeks')
        GROUP BY week ORDER BY week
    """, (cls, sec)).fetchall()

    # Per-student attendance summary
    student_att = db.execute("""
        SELECT s.roll_number, s.name,
               SUM(CASE WHEN a.status='Present' THEN 1 ELSE 0 END) as present,
               COUNT(a.id) as total
        FROM students s
        LEFT JOIN attendance a ON a.roll_number=s.roll_number AND a.class=s.class AND a.section=s.section
        WHERE s.class=? AND s.section=?
        GROUP BY s.id ORDER BY s.roll_number+0 LIMIT 30
    """, (cls, sec)).fetchall()

    # Overall stats
    overall = db.execute("""
        SELECT
            SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END) as present,
            SUM(CASE WHEN status='Absent' THEN 1 ELSE 0 END) as absent,
            SUM(CASE WHEN status='Late' THEN 1 ELSE 0 END) as late,
            COUNT(*) as total
        FROM attendance WHERE class=? AND section=?
    """, (cls, sec)).fetchone()

    # Monthly breakdown
    monthly = db.execute("""
        SELECT strftime('%m', date) as month,
               SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END) as present,
               COUNT(*) as total
        FROM attendance WHERE class=? AND section=?
        GROUP BY month ORDER BY month
    """, (cls, sec)).fetchall()

    db.close()

    # Process daily into chart data
    dates_set = sorted(set(r['date'] for r in daily))
    present_by_date = {}; absent_by_date = {}
    for r in daily:
        if r['status'] == 'Present': present_by_date[r['date']] = r['cnt']
        elif r['status'] == 'Absent': absent_by_date[r['date']] = r['cnt']

    return jsonify({
        'daily': {
            'labels': dates_set,
            'present': [present_by_date.get(d, 0) for d in dates_set],
            'absent':  [absent_by_date.get(d, 0) for d in dates_set],
        },
        'weekly': {
            'labels':  [f"Week {r['week']}" for r in weekly],
            'present': [r['present'] for r in weekly],
            'absent':  [r['absent'] for r in weekly],
        },
        'overall': dict(overall) if overall else {},
        'monthly': {
            'labels':  [r['month'] for r in monthly],
            'present': [r['present'] for r in monthly],
            'total':   [r['total'] for r in monthly],
        },
        'students': [
            {'roll': r['roll_number'], 'name': r['name'],
             'present': r['present'] or 0, 'total': r['total'] or 0,
             'pct': round((r['present'] or 0)/(r['total'] or 1)*100, 1)}
            for r in student_att
        ]
    })

# ── Fix admin dashboard chart data ─────────────────────
@app.route('/admin/dashboard/chart-data')
@admin_req
def admin_chart_data():
    """Real data for admin dashboard charts."""
    db = get_db()
    months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    # Student count (total, not monthly — show class-wise breakdown instead)
    class_data = db.execute("""
        SELECT class, COUNT(*) as cnt FROM students
        GROUP BY class ORDER BY class+0
    """).fetchall()

    # Notice counts by category
    notice_cats = db.execute("""
        SELECT category, COUNT(*) as cnt FROM notices
        GROUP BY category
    """).fetchall()

    # Results distribution (grade counts)
    grade_dist = db.execute("""
        SELECT grade, COUNT(*) as cnt FROM results
        WHERE grade != '' GROUP BY grade ORDER BY grade
    """).fetchall()

    # Recent attendance (last 7 days school-wide)
    att_week = db.execute("""
        SELECT date, status, COUNT(*) as cnt FROM attendance
        WHERE date >= date('now','-7 days')
        GROUP BY date, status ORDER BY date
    """).fetchall()

    db.close()

    # Pivot attendance rows into date-indexed present/absent series
    att_dates = sorted(set(r['date'] for r in att_week))
    att_present = {r['date']: r['cnt'] for r in att_week if r['status'] == 'Present'}
    att_absent  = {r['date']: r['cnt'] for r in att_week if r['status'] == 'Absent'}

    return jsonify({
        'classes': {'labels': [f"Class {r['class']}" for r in class_data],
                    'data':   [r['cnt'] for r in class_data]},
        'notices': {'labels': [r['category'] for r in notice_cats],
                    'data':   [r['cnt'] for r in notice_cats]},
        'grades':  {'labels': [r['grade'] for r in grade_dist],
                    'data':   [r['cnt'] for r in grade_dist]},
        'attendance': {
            'labels':  [d[5:] for d in att_dates],  # MM-DD
            'present': [att_present.get(d, 0) for d in att_dates],
            'absent':  [att_absent.get(d, 0) for d in att_dates],
        },
    })

# ══════════════════════════════════════════════════════
# MAIN (updated to run init_dev too)
# ══════════════════════════════════════════════════════
if __name__ == '__main__':
    init_db()
    try:
        init_dev()
    except Exception as e:
        print(f"init_dev warning: {e}")
    print(f"\n{'='*52}")
    print(f"  Pundibari R.G.L High School — School Portal")
    print(f"  🌐  Website:   http://localhost:5000")
    print(f"  🛡️   Admin:     http://localhost:5000/admin/login")
    print(f"  👨‍💻  Developer:  http://localhost:5000/dev/login")
    print(f"  🗄️   DB:        SQLite WAL + 15 Indexes")
    print(f"{'='*52}\n")
    app.run(debug=True, port=5000)
