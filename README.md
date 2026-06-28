# Pundibari R.G.L High School Website

Full-stack school website — Flask + SQLite + Gold/Navy Design

## Quick Start
```bash
pip install -r requirements.txt
python app.py
# Open: http://localhost:5000
```

## Login Credentials
| Role    | Detail                              | Password     |
|---------|-------------------------------------|--------------|
| Admin   | Username: admin                     | admin123     |
| Student | Class: 10, Section: A, Roll: 1     | student123   |

## Features
- Public website (Home, About, Academics, Notices, Results, Gallery, Facilities, Contact)
- Result lookup by Class + Section + Roll Number (roll restarts from 1 per section)
- Student dashboard (Attendance, Assignments, Materials, Timetable, Results, Notices)
- Admin panel with 10 management sections
- School logo upload/change from Admin → Settings
- Facilities with photo upload, icon, description, feature tags
- Bulk result import via CSV paste

## Tech Stack
- Backend: Python Flask
- Database: SQLite (school.db auto-created)
- Frontend: HTML + CSS + JavaScript (no frameworks)
- Design: Dark Navy + Gold Glassmorphism
