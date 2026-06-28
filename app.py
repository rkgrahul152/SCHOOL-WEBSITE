from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3, os, hashlib
from datetime import datetime
from functools import wraps
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'pundibari_rgl_2024_secret'
UPLOAD = 'static/images'
ALLOWED_IMG  = {'png','jpg','jpeg','gif','webp'}
ALLOWED_FILE = {'png','jpg','jpeg','gif','webp','pdf'}

def get_db():
    c = sqlite3.connect('school.db'); c.row_factory = sqlite3.Row; return c

def allowed_img(f):  return '.' in f and f.rsplit('.',1)[1].lower() in ALLOWED_IMG
def allowed_file(f): return '.' in f and f.rsplit('.',1)[1].lower() in ALLOWED_FILE

def save_file(fileobj, sub, check=None):
    if not fileobj or not fileobj.filename: return None
    check = check or allowed_file
    if not check(fileobj.filename): return None
    ts  = int(datetime.now().timestamp())
    fn  = secure_filename(fileobj.filename)
    fn  = f"{ts}_{fn}"
    dst = os.path.join(UPLOAD, sub)
    os.makedirs(dst, exist_ok=True)
    fileobj.save(os.path.join(dst, fn))
    return f"{sub}/{fn}"

def get_settings():
    db = get_db()
    rows = db.execute("SELECT key,value FROM settings").fetchall()
    db.close()
    return {r['key']: r['value'] for r in rows}

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

@app.context_processor
def globals():
    return dict(settings=get_settings(), now=datetime.now())

# ══════════════════════════════════════════
# INIT DB
# ══════════════════════════════════════════
def init_db():
    db = get_db(); c = db.cursor()
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
      class TEXT NOT NULL,section TEXT DEFAULT 'All',due_date TEXT,
      file_path TEXT,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
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
      is_active INTEGER DEFAULT 1,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS gallery(id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,category TEXT NOT NULL,image_path TEXT NOT NULL,
      description TEXT,event_date TEXT,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS attendance(id INTEGER PRIMARY KEY AUTOINCREMENT,
      roll_number TEXT NOT NULL,class TEXT NOT NULL,section TEXT NOT NULL,
      date TEXT NOT NULL,status TEXT NOT NULL,
      UNIQUE(roll_number,class,section,date));
    CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,description TEXT,event_date TEXT NOT NULL,
      event_type TEXT DEFAULT 'General',
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
    """)
    # admin
    pw = hashlib.sha256(b'admin123').hexdigest()
    c.execute("INSERT OR IGNORE INTO admins(username,password,name) VALUES(?,?,?)",
              ('admin',pw,'Administrator'))
    # settings
    for k,v in [
        ('school_name','Pundibari R.G.L High School'),
        ('tagline','Enlightening Minds, Building Futures'),
        ('principal_name','Mr. Rajendra Kumar Singh'),
        ('principal_message','Welcome to Pundibari R.G.L High School — an institution built on the pillars of excellence, integrity, and holistic development. Our dedicated faculty and modern infrastructure ensure every student reaches their fullest potential. Together, we build the leaders of tomorrow.'),
        ('phone','+91-XXXXX-XXXXX'),('email','pundibari.rgl@wb.gov.in'),
        ('address','Pundibari, Cooch Behar, West Bengal - 736121'),
        ('established','1965'),('hero_subtitle','A Centre of Academic Excellence Since 1965'),
        ('school_logo',''),
        ('hero_image',''),
        ('principal_photo',''),
        ('hero_badge_text','Government Aided High School · West Bengal'),
        ('stat1_val','800+'),('stat1_label','Students'),
        ('stat2_val','35+'),('stat2_label','Teachers'),
        ('stat3_val','8'),('stat3_label','Class Groups'),
        ('stat4_val','60+'),('stat4_label','Years Legacy'),
        ('ach1_val','98%'),('ach1_label','Pass Percentage'),
        ('ach2_val','15+'),('ach2_label','Sports Awards'),
        ('ach3_val','25+'),('ach3_label','Teachers Dedicated'),
        ('ach4_val','10+'),('ach4_label','Years of Excellence'),
        ('footer_about','Providing quality education to the youth of Pundibari since 1965.'),
        ('school_type','Government High School'),
        ('affiliation','WBBSE & WBCHSE'),
        ('notice_board_title','Notices & Announcements'),
        ('homepage_show_facilities','1'),
        ('homepage_show_gallery','1'),
        ('homepage_show_teachers','1'),
        ('homepage_show_achievements','1'),
        ('contact_map_embed',''),
        ('facebook_url',''),
        ('youtube_url',''),
        ('whatsapp_number',''),
    ]:
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",(k,v))
    # sample notices
    for t,ct,cat,u in [
        ('Annual Exam Schedule 2024-25','Exams start March 10. Admit cards from Feb 25.','Examination',1),
        ('Annual Sports Day','Sports Day on January 26, 2025.','Events',0),
        ('Parent-Teacher Meeting','PTM on February 8, 10AM–2PM.','Meeting',0),
        ('Winter Vacation','School closed Dec 25 – Jan 1.','Holiday',0),
    ]:
        c.execute("INSERT OR IGNORE INTO notices(title,content,category,is_urgent) VALUES(?,?,?,?)",(t,ct,cat,u))
    # sample events
    for t,d,et,dt in [
        ('Annual Sports Day','Inter-class sports competition.','Sports','2025-01-26'),
        ('Science Exhibition','Students showcase innovative projects.','Academic','2025-02-15'),
        ('Annual Function','Prize distribution & cultural night.','Cultural','2025-03-05'),
        ('Parent-Teacher Meeting','Review student progress.','Meeting','2025-02-08'),
    ]:
        c.execute("INSERT OR IGNORE INTO events(title,description,event_type,event_date) VALUES(?,?,?,?)",(t,d,et,dt))
    # teachers
    for nm,des,sub,q,ex,so in [
        ('Mr. Rajendra Kumar Singh','Headmaster','Administration','M.A., B.Ed.','25 years',1),
        ('Mrs. Priya Sharma','Assistant Teacher','Mathematics','M.Sc., B.Ed.','15 years',2),
        ('Mr. Arun Das','Assistant Teacher','Science','M.Sc., B.Ed.','12 years',3),
        ('Mrs. Sunita Roy','Assistant Teacher','Bengali','M.A., B.Ed.','18 years',4),
        ('Mr. Bipul Barman','Assistant Teacher','English','M.A., B.Ed.','10 years',5),
        ('Mrs. Kabita Dey','Assistant Teacher','History','M.A., B.Ed.','8 years',6),
        ('Mr. Sanjay Ghosh','Assistant Teacher','Geography','M.A., B.Ed.','11 years',7),
        ('Mrs. Rupa Paul','Assistant Teacher','Physics','M.Sc., B.Ed.','9 years',8),
        ('Mr. Debashis Sarkar','Assistant Teacher','Chemistry','M.Sc., B.Ed.','7 years',9),
    ]:
        c.execute("INSERT OR IGNORE INTO teachers(name,designation,subject,qualification,experience,sort_order) VALUES(?,?,?,?,?,?)",(nm,des,sub,q,ex,so))
    # facilities
    for nm,desc,det,ico,so in [
        ('Smart Classroom','Interactive digital teaching with projectors and smart boards in every classroom.','Projector System | Smart Board | Wi-Fi Enabled | Air Conditioned','🖥️',1),
        ('Library','Well-stocked library with over 10,000 books covering all subjects for all classes.','10,000+ Books | Separate Reading Room | Digital Catalogue | Reference Section','📚',2),
        ('Computer Laboratory','40+ modern computers with high-speed internet for digital literacy and education.','40+ Systems | High-Speed Internet | Latest Software | 24/7 UPS Backup','💻',3),
        ('Playground','Spacious sports ground for football, cricket, athletics and outdoor activities.','Football Field | Cricket Pitch | Athletics Track | Badminton Court','⚽',4),
        ('Science Laboratory','Fully equipped labs for Physics, Chemistry and Biology experiments and practicals.','Physics Lab | Chemistry Lab | Biology Lab | Safety Equipment','🔬',5),
        ('Mid-Day Meal','Government mid-day meal programme providing nutritious meals to all students.','Daily Hot Meals | Govt. Scheme | Hygienic Kitchen | All Students Covered','🍽️',6),
    ]:
        c.execute("INSERT OR IGNORE INTO facilities(name,description,details,icon,sort_order) VALUES(?,?,?,?,?)",(nm,desc,det,ico,so))
    # demo student (Class 10-A, Roll 1)
    spw = hashlib.sha256(b'student123').hexdigest()
    c.execute("INSERT OR IGNORE INTO students(roll_number,name,class,section,password,guardian,phone) VALUES(?,?,?,?,?,?,?)",
              ('1','Raju Barman','10','A',spw,'Ramesh Barman','9876543210'))
    # demo results
    for subj,mo,tot,gr in [('Mathematics',78,100,'B+'),('Science',85,100,'A'),('English',70,100,'B'),('Bengali',88,100,'A'),('History',65,100,'B+'),('Geography',72,100,'B')]:
        c.execute("INSERT OR IGNORE INTO results(roll_number,student_name,class,section,exam_name,subject,marks_obtained,total_marks,grade,year) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  ('1','Raju Barman','10','A','Annual Exam 2024-25',subj,mo,tot,gr,2025))
    db.commit(); db.close()

# ══════════════════════════════════════════
# PUBLIC
# ══════════════════════════════════════════
@app.route('/')
def index():
    db = get_db()
    notices    = db.execute("SELECT * FROM notices ORDER BY is_urgent DESC,created_at DESC LIMIT 5").fetchall()
    events     = db.execute("SELECT * FROM events ORDER BY event_date ASC LIMIT 4").fetchall()
    teachers   = db.execute("SELECT * FROM teachers WHERE is_active=1 ORDER BY sort_order LIMIT 6").fetchall()
    gallery    = db.execute("SELECT * FROM gallery ORDER BY created_at DESC LIMIT 6").fetchall()
    facilities = db.execute("SELECT * FROM facilities WHERE is_active=1 ORDER BY sort_order LIMIT 6").fetchall()
    db.close()
    return render_template('index.html',notices=notices,events=events,
                           teachers=teachers,gallery=gallery,facilities=facilities)

@app.route('/about')
def about():
    db = get_db()
    teachers = db.execute("SELECT * FROM teachers WHERE is_active=1 ORDER BY sort_order").fetchall()
    db.close()
    return render_template('about.html',teachers=teachers)

@app.route('/academics')
def academics(): return render_template('academics.html')

@app.route('/class/<cn>/<sec>')
def class_page(cn,sec):
    db = get_db()
    routines    = db.execute("SELECT * FROM routines WHERE class=? AND section=? ORDER BY day,period",(cn,sec)).fetchall()
    assignments = db.execute("SELECT * FROM assignments WHERE class=? AND (section=? OR section='All') ORDER BY created_at DESC LIMIT 10",(cn,sec)).fetchall()
    materials   = db.execute("SELECT * FROM materials WHERE class=? AND (section=? OR section='All') ORDER BY created_at DESC",(cn,sec)).fetchall()
    db.close()
    return render_template('class_page.html',class_name=cn,section=sec,
                           routines=routines,assignments=assignments,materials=materials)

@app.route('/notices')
def notices():
    db = get_db()
    n = db.execute("SELECT * FROM notices ORDER BY is_urgent DESC,created_at DESC").fetchall()
    db.close()
    return render_template('notices.html',notices=n)

@app.route('/gallery')
def gallery():
    db = get_db()
    cats = ['Annual Function','Sports','Science Exhibition','Cultural','Campus']
    gi   = {cat: db.execute("SELECT * FROM gallery WHERE category=? ORDER BY created_at DESC",(cat,)).fetchall() for cat in cats}
    all_ = db.execute("SELECT * FROM gallery ORDER BY created_at DESC").fetchall()
    db.close()
    return render_template('gallery.html',gallery_items=gi,all_items=all_,categories=cats)

@app.route('/facilities')
def facilities():
    db = get_db()
    fac = db.execute("SELECT * FROM facilities WHERE is_active=1 ORDER BY sort_order").fetchall()
    db.close()
    return render_template('facilities.html',facilities=fac)

@app.route('/contact')
def contact(): return render_template('contact.html')

# ── RESULTS (Class + Section + Roll) ──────
@app.route('/results', methods=['GET','POST'])
def results():
    data=None; error=None; searched=False
    if request.method=='POST':
        roll=request.form.get('roll_number','').strip()
        cls =request.form.get('class','').strip()
        sec =request.form.get('section','').strip()
        exam=request.form.get('exam_name','').strip()
        searched=True
        if not all([roll,cls,sec,exam]):
            error='Please fill in all four fields.'
        else:
            db = get_db()
            data = db.execute("SELECT * FROM results WHERE roll_number=? AND class=? AND section=? AND exam_name=? ORDER BY subject",(roll,cls,sec,exam)).fetchall()
            db.close()
            if not data: error=f'No result found for Roll {roll}, Class {cls}-{sec}, Exam: {exam}.'
    db = get_db()
    exams = db.execute("SELECT DISTINCT exam_name FROM results ORDER BY exam_name").fetchall()
    db.close()
    return render_template('results.html',result_data=data,error=error,exams=exams,searched=searched)

# ══════════════════════════════════════════
# STUDENT
# ══════════════════════════════════════════
@app.route('/student/login', methods=['GET','POST'])
def student_login():
    if request.method=='POST':
        roll=request.form.get('roll_number','').strip()
        cls =request.form.get('class','').strip()
        sec =request.form.get('section','').strip()
        pw  =hashlib.sha256(request.form.get('password','').encode()).hexdigest()
        db  =get_db()
        stu =db.execute("SELECT * FROM students WHERE roll_number=? AND class=? AND section=? AND password=?",(roll,cls,sec,pw)).fetchone()
        db.close()
        if stu:
            session.update({'student_id':stu['id'],'student_roll':stu['roll_number'],
                            'student_name':stu['name'],'student_class':stu['class'],
                            'student_section':stu['section']})
            return redirect(url_for('student_dashboard'))
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
    res  =db.execute("SELECT * FROM results WHERE roll_number=? AND class=? AND section=? ORDER BY created_at DESC",(roll,cls,sec)).fetchall()
    nts  =db.execute("SELECT * FROM notices ORDER BY is_urgent DESC,created_at DESC LIMIT 6").fetchall()
    db.close()
    total=len(att); present=sum(1 for a in att if a['status']=='Present')
    pct=round((present/total*100) if total else 0,1)
    return render_template('student_dashboard.html',attendance=att,assignments=asn,
        materials=mats,routines=rout,results=res,notices=nts,att_pct=pct,present=present,total=total)

@app.route('/student/logout')
def student_logout():
    session.clear(); return redirect(url_for('student_login'))

# ══════════════════════════════════════════
# ADMIN AUTH
# ══════════════════════════════════════════
@app.route('/admin/login', methods=['GET','POST'])
def admin_login():
    if request.method=='POST':
        u=request.form.get('username','').strip()
        pw=hashlib.sha256(request.form.get('password','').encode()).hexdigest()
        db=get_db()
        adm=db.execute("SELECT * FROM admins WHERE username=? AND password=?",(u,pw)).fetchone()
        db.close()
        if adm:
            session.update({'admin_id':adm['id'],'admin_name':adm['name']})
            return redirect(url_for('admin_dashboard'))
        flash('Invalid credentials.','error')
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout(): session.clear(); return redirect(url_for('admin_login'))

@app.route('/admin/')
@app.route('/admin/dashboard')
@admin_req
def admin_dashboard():
    db=get_db()
    stats={k:db.execute(q).fetchone()[0] for k,q in [
        ('students',"SELECT COUNT(*) FROM students"),
        ('teachers',"SELECT COUNT(*) FROM teachers WHERE is_active=1"),
        ('notices', "SELECT COUNT(*) FROM notices"),
        ('gallery', "SELECT COUNT(*) FROM gallery"),
        ('results', "SELECT COUNT(*) FROM results"),
        ('facilities',"SELECT COUNT(*) FROM facilities WHERE is_active=1"),
    ]}
    rn=db.execute("SELECT * FROM notices ORDER BY created_at DESC LIMIT 5").fetchall()
    re=db.execute("SELECT * FROM events ORDER BY event_date ASC LIMIT 5").fetchall()
    db.close()
    return render_template('admin_dashboard.html',stats=stats,recent_notices=rn,recent_events=re)

# ══════════════════════════════════════════
# ADMIN – LOGO
# ══════════════════════════════════════════
@app.route('/admin/logo/upload',methods=['POST'])
@admin_req
def admin_upload_logo():
    path=save_file(request.files.get('logo'),'logo',allowed_img)
    if path:
        db=get_db(); db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('school_logo',?)",(path,)); db.commit(); db.close()
        flash('Logo updated!','success')
    else: flash('Use PNG/JPG/GIF only.','error')
    return redirect(url_for('admin_settings'))

@app.route('/admin/logo/remove')
@admin_req
def admin_remove_logo():
    db=get_db()
    old=db.execute("SELECT value FROM settings WHERE key='school_logo'").fetchone()
    if old and old['value']:
        p=os.path.join(UPLOAD,old['value'])
        if os.path.exists(p): os.remove(p)
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('school_logo','')")
    db.commit(); db.close()
    flash('Logo removed.','success')
    return redirect(url_for('admin_settings'))

# ══════════════════════════════════════════
# ADMIN – HERO IMAGE
# ══════════════════════════════════════════
@app.route('/admin/hero/upload',methods=['POST'])
@admin_req
def admin_upload_hero():
    path=save_file(request.files.get('hero_image'),'hero',allowed_img)
    if path:
        db=get_db(); db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('hero_image',?)",(path,)); db.commit(); db.close()
        flash('Hero background updated!','success')
    else: flash('Use PNG/JPG/GIF/WEBP only.','error')
    return redirect(url_for('admin_settings'))

@app.route('/admin/hero/remove')
@admin_req
def admin_remove_hero():
    db=get_db()
    old=db.execute("SELECT value FROM settings WHERE key='hero_image'").fetchone()
    if old and old['value']:
        p=os.path.join(UPLOAD,old['value'])
        if os.path.exists(p): os.remove(p)
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('hero_image','')")
    db.commit(); db.close(); flash('Hero image removed.','success')
    return redirect(url_for('admin_settings'))

# ══════════════════════════════════════════
# ADMIN – PRINCIPAL PHOTO
# ══════════════════════════════════════════
@app.route('/admin/principal/upload',methods=['POST'])
@admin_req
def admin_upload_principal():
    path=save_file(request.files.get('principal_photo'),'principal',allowed_img)
    if path:
        db=get_db(); db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('principal_photo',?)",(path,)); db.commit(); db.close()
        flash('Principal photo updated!','success')
    else: flash('Use PNG/JPG only.','error')
    return redirect(url_for('admin_settings'))

@app.route('/admin/principal/remove')
@admin_req
def admin_remove_principal():
    db=get_db()
    old=db.execute("SELECT value FROM settings WHERE key='principal_photo'").fetchone()
    if old and old['value']:
        p=os.path.join(UPLOAD,old['value'])
        if os.path.exists(p): os.remove(p)
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('principal_photo','')")
    db.commit(); db.close(); flash('Photo removed.','success')
    return redirect(url_for('admin_settings'))

# ══════════════════════════════════════════
# ADMIN – NOTICES
# ══════════════════════════════════════════
@app.route('/admin/notices')
@admin_req
def admin_notices():
    db=get_db(); n=db.execute("SELECT * FROM notices ORDER BY created_at DESC").fetchall(); db.close()
    return render_template('admin_notices.html',notices=n)

@app.route('/admin/notices/add',methods=['POST'])
@admin_req
def admin_add_notice():
    db=get_db()
    db.execute("INSERT INTO notices(title,content,category,is_urgent) VALUES(?,?,?,?)",
        (request.form['title'],request.form['content'],request.form.get('category','General'),1 if request.form.get('urgent') else 0))
    db.commit(); db.close(); flash('Notice posted!','success')
    return redirect(url_for('admin_notices'))

@app.route('/admin/notices/delete/<int:i>')
@admin_req
def admin_delete_notice(i):
    db=get_db(); db.execute("DELETE FROM notices WHERE id=?",(i,)); db.commit(); db.close()
    flash('Notice deleted.','success'); return redirect(url_for('admin_notices'))

# ══════════════════════════════════════════
# ADMIN – RESULTS (class+section+roll)
# ══════════════════════════════════════════
@app.route('/admin/results')
@admin_req
def admin_results():
    cls=request.args.get('class',''); sec=request.args.get('section',''); exam=request.args.get('exam','')
    db=get_db()
    q="SELECT * FROM results WHERE 1=1"; p=[]
    if cls: q+=" AND class=?"; p.append(cls)
    if sec: q+=" AND section=?"; p.append(sec)
    if exam: q+=" AND exam_name=?"; p.append(exam)
    q+=" ORDER BY class,section,roll_number+0,subject"
    res=db.execute(q,p).fetchall()
    exams=db.execute("SELECT DISTINCT exam_name FROM results ORDER BY exam_name").fetchall()
    db.close()
    return render_template('admin_results.html',results=res,exams=exams,
                           filter_class=cls,filter_section=sec,filter_exam=exam)

@app.route('/admin/results/add',methods=['POST'])
@admin_req
def admin_add_result():
    f=request.form; db=get_db()
    db.execute("INSERT INTO results(roll_number,student_name,class,section,exam_name,subject,marks_obtained,total_marks,grade,year) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (f['roll_number'],f['student_name'],f['class'],f['section'],f['exam_name'],f['subject'],f['marks_obtained'],f['total_marks'],f.get('grade',''),f.get('year',datetime.now().year)))
    db.commit(); db.close(); flash('Result saved!','success')
    return redirect(url_for('admin_results'))

@app.route('/admin/results/delete/<int:i>')
@admin_req
def admin_delete_result(i):
    db=get_db(); db.execute("DELETE FROM results WHERE id=?",(i,)); db.commit(); db.close()
    flash('Deleted.','success'); return redirect(url_for('admin_results'))

@app.route('/admin/results/bulk',methods=['POST'])
@admin_req
def admin_bulk_results():
    cls=request.form.get('class',''); sec=request.form.get('section','')
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
    db.commit(); db.close(); flash(f'{count} results imported!','success')
    return redirect(url_for('admin_results'))

# ══════════════════════════════════════════
# ADMIN – ASSIGNMENTS
# ══════════════════════════════════════════
@app.route('/admin/assignments')
@admin_req
def admin_assignments():
    db=get_db(); a=db.execute("SELECT * FROM assignments ORDER BY created_at DESC").fetchall(); db.close()
    return render_template('admin_assignments.html',assignments=a)

@app.route('/admin/assignments/add',methods=['POST'])
@admin_req
def admin_add_assignment():
    path=save_file(request.files.get('file'),'assignments'); f=request.form; db=get_db()
    db.execute("INSERT INTO assignments(title,description,subject,class,section,due_date,file_path) VALUES(?,?,?,?,?,?,?)",
        (f['title'],f.get('description'),f['subject'],f['class'],f.get('section','All'),f.get('due_date'),path))
    db.commit(); db.close(); flash('Assignment added!','success')
    return redirect(url_for('admin_assignments'))

# ══════════════════════════════════════════
# ADMIN – MATERIALS
# ══════════════════════════════════════════
@app.route('/admin/materials')
@admin_req
def admin_materials():
    db=get_db(); m=db.execute("SELECT * FROM materials ORDER BY created_at DESC").fetchall(); db.close()
    return render_template('admin_materials.html',materials=m)

@app.route('/admin/materials/add',methods=['POST'])
@admin_req
def admin_add_material():
    path=save_file(request.files.get('file'),'materials'); f=request.form; db=get_db()
    db.execute("INSERT INTO materials(title,subject,class,section,file_path,description) VALUES(?,?,?,?,?,?)",
        (f['title'],f['subject'],f['class'],f.get('section','All'),path,f.get('description')))
    db.commit(); db.close(); flash('Material uploaded!','success')
    return redirect(url_for('admin_materials'))

# ══════════════════════════════════════════
# ADMIN – GALLERY
# ══════════════════════════════════════════
@app.route('/admin/gallery')
@admin_req
def admin_gallery():
    db=get_db(); g=db.execute("SELECT * FROM gallery ORDER BY created_at DESC").fetchall(); db.close()
    return render_template('admin_gallery.html',gallery=g)

@app.route('/admin/gallery/add',methods=['POST'])
@admin_req
def admin_add_gallery():
    cat=request.form.get('category','General')
    path=save_file(request.files.get('image'),f'gallery/{cat.lower().replace(" ","_")}',allowed_img)
    if path:
        db=get_db()
        db.execute("INSERT INTO gallery(title,category,image_path,description,event_date) VALUES(?,?,?,?,?)",
            (request.form['title'],cat,path,request.form.get('description'),request.form.get('event_date')))
        db.commit(); db.close(); flash('Photo added!','success')
    else: flash('Select a valid image file.','error')
    return redirect(url_for('admin_gallery'))

@app.route('/admin/gallery/delete/<int:i>')
@admin_req
def admin_delete_gallery(i):
    db=get_db(); item=db.execute("SELECT * FROM gallery WHERE id=?",(i,)).fetchone()
    if item:
        p=os.path.join(UPLOAD,item['image_path'])
        if os.path.exists(p): os.remove(p)
        db.execute("DELETE FROM gallery WHERE id=?",(i,)); db.commit()
    db.close(); flash('Deleted.','success'); return redirect(url_for('admin_gallery'))

# ══════════════════════════════════════════
# ADMIN – FACILITIES
# ══════════════════════════════════════════
@app.route('/admin/facilities')
@admin_req
def admin_facilities():
    db=get_db(); f=db.execute("SELECT * FROM facilities ORDER BY sort_order,id").fetchall(); db.close()
    return render_template('admin_facilities.html',facilities=f)

@app.route('/admin/facilities/add',methods=['POST'])
@admin_req
def admin_add_facility():
    photo=save_file(request.files.get('photo'),'facilities',allowed_img); f=request.form; db=get_db()
    db.execute("INSERT INTO facilities(name,description,details,photo,icon,sort_order) VALUES(?,?,?,?,?,?)",
        (f['name'],f.get('description',''),f.get('details',''),photo,f.get('icon','🏫'),int(f.get('sort_order',99))))
    db.commit(); db.close(); flash('Facility added!','success')
    return redirect(url_for('admin_facilities'))

@app.route('/admin/facilities/edit/<int:i>',methods=['POST'])
@admin_req
def admin_edit_facility(i):
    photo=save_file(request.files.get('photo'),'facilities',allowed_img); f=request.form; db=get_db()
    if photo:
        db.execute("UPDATE facilities SET name=?,description=?,details=?,photo=?,icon=?,sort_order=? WHERE id=?",
            (f['name'],f.get('description'),f.get('details'),photo,f.get('icon','🏫'),int(f.get('sort_order',99)),i))
    else:
        db.execute("UPDATE facilities SET name=?,description=?,details=?,icon=?,sort_order=? WHERE id=?",
            (f['name'],f.get('description'),f.get('details'),f.get('icon','🏫'),int(f.get('sort_order',99)),i))
    db.commit(); db.close(); flash('Facility updated!','success')
    return redirect(url_for('admin_facilities'))

@app.route('/admin/facilities/toggle/<int:i>')
@admin_req
def admin_toggle_facility(i):
    db=get_db(); cur=db.execute("SELECT is_active FROM facilities WHERE id=?",(i,)).fetchone()
    if cur: db.execute("UPDATE facilities SET is_active=? WHERE id=?",(0 if cur['is_active'] else 1,i)); db.commit()
    db.close(); flash('Visibility updated.','success'); return redirect(url_for('admin_facilities'))

@app.route('/admin/facilities/delete/<int:i>')
@admin_req
def admin_delete_facility(i):
    db=get_db(); item=db.execute("SELECT * FROM facilities WHERE id=?",(i,)).fetchone()
    if item and item['photo']:
        p=os.path.join(UPLOAD,item['photo'])
        if os.path.exists(p): os.remove(p)
    db.execute("DELETE FROM facilities WHERE id=?",(i,)); db.commit(); db.close()
    flash('Facility deleted.','success'); return redirect(url_for('admin_facilities'))

# ══════════════════════════════════════════
# ADMIN – TEACHERS
# ══════════════════════════════════════════
@app.route('/admin/teachers')
@admin_req
def admin_teachers():
    db=get_db(); t=db.execute("SELECT * FROM teachers ORDER BY sort_order,id").fetchall(); db.close()
    return render_template('admin_teachers.html',teachers=t)

@app.route('/admin/teachers/add',methods=['POST'])
@admin_req
def admin_add_teacher():
    photo=save_file(request.files.get('photo'),'teachers',allowed_img); f=request.form; db=get_db()
    db.execute("INSERT INTO teachers(name,designation,subject,qualification,experience,phone,email,photo,sort_order) VALUES(?,?,?,?,?,?,?,?,?)",
        (f['name'],f.get('designation'),f.get('subject'),f.get('qualification'),f.get('experience'),f.get('phone'),f.get('email'),photo,int(f.get('sort_order',99))))
    db.commit(); db.close(); flash('Teacher added!','success')
    return redirect(url_for('admin_teachers'))

@app.route('/admin/teachers/delete/<int:i>')
@admin_req
def admin_delete_teacher(i):
    db=get_db(); db.execute("DELETE FROM teachers WHERE id=?",(i,)); db.commit(); db.close()
    flash('Removed.','success'); return redirect(url_for('admin_teachers'))

# ══════════════════════════════════════════
# ADMIN – ROUTINES
# ══════════════════════════════════════════
@app.route('/admin/routines')
@admin_req
def admin_routines():
    db=get_db(); r=db.execute("SELECT * FROM routines ORDER BY class,section,day,period").fetchall(); db.close()
    return render_template('admin_routines.html',routines=r)

@app.route('/admin/routines/add',methods=['POST'])
@admin_req
def admin_add_routine():
    f=request.form; db=get_db()
    db.execute("INSERT INTO routines(class,section,day,period,subject,teacher,time_slot) VALUES(?,?,?,?,?,?,?)",
        (f['class'],f['section'],f['day'],f['period'],f['subject'],f.get('teacher'),f.get('time_slot')))
    db.commit(); db.close(); flash('Entry added!','success')
    return redirect(url_for('admin_routines'))

@app.route('/admin/routines/delete/<int:i>')
@admin_req
def admin_delete_routine(i):
    db=get_db(); db.execute("DELETE FROM routines WHERE id=?",(i,)); db.commit(); db.close()
    flash('Deleted.','success'); return redirect(url_for('admin_routines'))

# ══════════════════════════════════════════
# ADMIN – EVENTS
# ══════════════════════════════════════════
@app.route('/admin/events')
@admin_req
def admin_events():
    db=get_db(); e=db.execute("SELECT * FROM events ORDER BY event_date DESC").fetchall(); db.close()
    return render_template('admin_events.html',events=e)

@app.route('/admin/events/add',methods=['POST'])
@admin_req
def admin_add_event():
    f=request.form; db=get_db()
    db.execute("INSERT INTO events(title,description,event_date,event_type) VALUES(?,?,?,?)",
        (f['title'],f.get('description'),f['event_date'],f.get('event_type','General')))
    db.commit(); db.close(); flash('Event added!','success')
    return redirect(url_for('admin_events'))

@app.route('/admin/events/delete/<int:i>')
@admin_req
def admin_delete_event(i):
    db=get_db(); db.execute("DELETE FROM events WHERE id=?",(i,)); db.commit(); db.close()
    flash('Deleted.','success'); return redirect(url_for('admin_events'))

# ══════════════════════════════════════════
# ADMIN – STUDENTS
# ══════════════════════════════════════════
@app.route('/admin/students')
@admin_req
def admin_students():
    cls=request.args.get('class',''); sec=request.args.get('section','')
    db=get_db(); q="SELECT * FROM students WHERE 1=1"; p=[]
    if cls: q+=" AND class=?"; p.append(cls)
    if sec: q+=" AND section=?"; p.append(sec)
    q+=" ORDER BY class,section,roll_number+0"
    s=db.execute(q,p).fetchall(); db.close()
    return render_template('admin_students.html',students=s,filter_class=cls,filter_section=sec)

@app.route('/admin/students/add',methods=['POST'])
@admin_req
def admin_add_student():
    pw=hashlib.sha256(request.form.get('password','student123').encode()).hexdigest(); f=request.form; db=get_db()
    try:
        db.execute("INSERT INTO students(roll_number,name,class,section,password,guardian,phone) VALUES(?,?,?,?,?,?,?)",
            (f['roll_number'],f['name'],f['class'],f['section'],pw,f.get('guardian'),f.get('phone')))
        db.commit(); flash('Student added!','success')
    except: flash('Error: Roll already exists for this class-section.','error')
    db.close(); return redirect(url_for('admin_students'))

@app.route('/admin/students/delete/<int:i>')
@admin_req
def admin_delete_student(i):
    db=get_db(); db.execute("DELETE FROM students WHERE id=?",(i,)); db.commit(); db.close()
    flash('Removed.','success'); return redirect(url_for('admin_students'))

# ══════════════════════════════════════════
# ADMIN – ATTENDANCE
# ══════════════════════════════════════════
@app.route('/admin/attendance')
@admin_req
def admin_attendance():
    cls=request.args.get('class','10'); sec=request.args.get('section','A')
    db=get_db()
    students=db.execute("SELECT * FROM students WHERE class=? AND section=? ORDER BY roll_number+0",(cls,sec)).fetchall()
    att=db.execute("SELECT * FROM attendance WHERE class=? AND section=? ORDER BY date DESC LIMIT 200",(cls,sec)).fetchall()
    db.close()
    return render_template('admin_attendance.html',students=students,attendance=att,filter_class=cls,filter_section=sec)

@app.route('/admin/attendance/mark',methods=['POST'])
@admin_req
def admin_mark_attendance():
    f=request.form; db=get_db()
    db.execute("INSERT OR REPLACE INTO attendance(roll_number,class,section,date,status) VALUES(?,?,?,?,?)",
        (f['roll_number'],f['class'],f['section'],f['date'],f['status']))
    db.commit(); db.close(); flash('Attendance marked!','success')
    return redirect(url_for('admin_attendance',**{'class':f['class'],'section':f['section']}))

# ══════════════════════════════════════════
# ADMIN – SETTINGS
# ══════════════════════════════════════════
@app.route('/admin/settings')
@admin_req
def admin_settings(): return render_template('admin_settings.html',settings=get_settings())

@app.route('/admin/settings/save',methods=['POST'])
@admin_req
def admin_save_settings():
    db=get_db()
    for k in ['school_name','tagline','principal_name','principal_message','phone','email','address',
               'established','hero_subtitle','hero_badge_text','school_type','affiliation',
               'stat1_val','stat1_label','stat2_val','stat2_label','stat3_val','stat3_label','stat4_val','stat4_label',
               'ach1_val','ach1_label','ach2_val','ach2_label','ach3_val','ach3_label','ach4_val','ach4_label',
               'footer_about','notice_board_title','contact_map_embed',
               'facebook_url','youtube_url','whatsapp_number',
               'homepage_show_facilities','homepage_show_gallery','homepage_show_teachers','homepage_show_achievements']:
        v=request.form.get(k)
        if v is not None: db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",(k,v))
    db.commit(); db.close(); flash('Settings saved!','success')
    return redirect(url_for('admin_settings'))

if __name__=='__main__':
    init_db()
    app.run(debug=True,port=5000)
