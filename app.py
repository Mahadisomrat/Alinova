from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from datetime import datetime
import os, json, sqlite3

app = Flask(__name__)
app.secret_key = 'chatbd_secret_2024'
socketio = SocketIO(app, cors_allowed_origins="*")

online_users = set()
user_rooms = {}

# ─── Database ─────────────────────────────────────────────

def get_db():
    db = sqlite3.connect('chatbd.db')
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.execute('''CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT NOT NULL,
        profile_pic TEXT,
        about TEXT DEFAULT 'Hey! I am using ChatBD'
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room TEXT NOT NULL,
        sender TEXT NOT NULL,
        text TEXT,
        file TEXT,
        file_name TEXT,
        file_type TEXT,
        duration TEXT,
        reply_to TEXT,
        reactions TEXT DEFAULT '{}',
        seen INTEGER DEFAULT 0,
        edited INTEGER DEFAULT 0,
        deleted INTEGER DEFAULT 0,
        timestamp TEXT
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS groups (
        name TEXT PRIMARY KEY,
        members TEXT NOT NULL,
        created_by TEXT,
        pic TEXT
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS group_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_name TEXT NOT NULL,
        sender TEXT NOT NULL,
        text TEXT,
        file TEXT,
        file_name TEXT,
        file_type TEXT,
        duration TEXT,
        timestamp TEXT
    )''')
    db.commit()
    db.close()

init_db()

def get_room_id(u1, u2):
    return '_'.join(sorted([u1, u2]))

# ─── Routes ───────────────────────────────────────────────

@app.route('/')
def index():
    return redirect(url_for('login') if 'username' not in session else url_for('home'))

@app.route('/register', methods=['GET','POST'])
def register():
    error = None
    if request.method == 'POST':
        u = request.form['username'].strip()
        p = request.form['password'].strip()
        if not u or not p:
            error = 'সব তথ্য পূরণ করুন।'
        else:
            db = get_db()
            existing = db.execute('SELECT username FROM users WHERE username=?', (u,)).fetchone()
            if existing:
                error = 'এই নামে ইউজার আছে।'
            else:
                db.execute('INSERT INTO users (username, password) VALUES (?,?)', (u, p))
                db.commit()
                db.close()
                session['username'] = u
                return redirect(url_for('home'))
            db.close()
    return render_template('register.html', error=error)

@app.route('/login', methods=['GET','POST'])
def login():
    error = None
    if request.method == 'POST':
        u = request.form['username'].strip()
        p = request.form['password'].strip()
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username=? AND password=?', (u, p)).fetchone()
        db.close()
        if user:
            session['username'] = u
            return redirect(url_for('home'))
        error = 'ভুল নাম বা পাসওয়ার্ড।'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/home')
def home():
    if 'username' not in session: return redirect(url_for('login'))
    me = session['username']
    db = get_db()
    others = [row['username'] for row in db.execute('SELECT username FROM users WHERE username!=?', (me,)).fetchall()]
    users_data = {row['username']: dict(row) for row in db.execute('SELECT * FROM users').fetchall()}
    groups_rows = db.execute('SELECT * FROM groups').fetchall()
    groups = {}
    my_groups = []
    for g in groups_rows:
        members = json.loads(g['members'])
        groups[g['name']] = {'members': members, 'created_by': g['created_by']}
        if me in members:
            my_groups.append(g['name'])
    db.close()
    return render_template('home.html', username=me, users=others,
                           online=list(online_users), users_data=users_data,
                           groups=my_groups, groups_data=groups)

@app.route('/chat/<other>')
def chat(other):
    if 'username' not in session: return redirect(url_for('login'))
    me = session['username']
    db = get_db()
    user = db.execute('SELECT username FROM users WHERE username=?', (other,)).fetchone()
    if not user:
        db.close()
        return redirect(url_for('home'))
    room = get_room_id(me, other)
    msgs = db.execute('SELECT * FROM messages WHERE room=? ORDER BY id', (room,)).fetchall()
    history = []
    for m in msgs:
        msg = dict(m)
        msg['reactions'] = json.loads(m['reactions'] or '{}')
        msg['reply_to'] = json.loads(m['reply_to']) if m['reply_to'] else None
        history.append(msg)
    users_data = {row['username']: dict(row) for row in db.execute('SELECT * FROM users').fetchall()}
    db.close()
    return render_template('chat.html', me=me, other=other,
                           history=history, room=room, users_data=users_data,
                           online=list(online_users))

@app.route('/group/<name>')
def group_chat(name):
    if 'username' not in session: return redirect(url_for('login'))
    me = session['username']
    db = get_db()
    group = db.execute('SELECT * FROM groups WHERE name=?', (name,)).fetchone()
    if not group or me not in json.loads(group['members']):
        db.close()
        return redirect(url_for('home'))
    msgs = db.execute('SELECT * FROM group_messages WHERE group_name=? ORDER BY id', (name,)).fetchall()
    history = [dict(m) for m in msgs]
    users_data = {row['username']: dict(row) for row in db.execute('SELECT * FROM users').fetchall()}
    group_data = {'members': json.loads(group['members']), 'created_by': group['created_by']}
    db.close()
    return render_template('group_chat.html', me=me, group_name=name,
                           history=history, group=group_data, users_data=users_data)

@app.route('/upload_pic', methods=['POST'])
def upload_pic():
    if 'username' not in session: return jsonify({'error': 'not logged in'}), 401
    data = request.get_json()
    pic = data.get('pic')
    if pic:
        db = get_db()
        db.execute('UPDATE users SET profile_pic=? WHERE username=?', (pic, session['username']))
        db.commit()
        db.close()
        socketio.emit('profile_updated', {'username': session['username'], 'profile_pic': pic})
        return jsonify({'success': True})
    return jsonify({'error': 'no image'}), 400

@app.route('/create_group', methods=['POST'])
def create_group():
    if 'username' not in session: return jsonify({'error': 'not logged in'}), 401
    data = request.get_json()
    name = data.get('name', '').strip()
    members = data.get('members', [])
    me = session['username']
    if not name: return jsonify({'error': 'নাম দিন'}), 400
    db = get_db()
    existing = db.execute('SELECT name FROM groups WHERE name=?', (name,)).fetchone()
    if existing:
        db.close()
        return jsonify({'error': 'এই নামে গ্রুপ আছে'}), 400
    if me not in members: members.append(me)
    db.execute('INSERT INTO groups (name, members, created_by) VALUES (?,?,?)',
               (name, json.dumps(members), me))
    db.commit()
    db.close()
    socketio.emit('group_created', {'name': name, 'members': members})
    return jsonify({'success': True, 'name': name})

# ─── Socket Events ────────────────────────────────────────

@socketio.on('connect')
def on_connect():
    if 'username' in session:
        u = session['username']
        online_users.add(u)
        user_rooms[u] = request.sid
        emit('user_status', {'user': u, 'status': 'online'}, broadcast=True)

@socketio.on('disconnect')
def on_disconnect():
    if 'username' in session:
        u = session['username']
        online_users.discard(u)
        user_rooms.pop(u, None)
        emit('user_status', {'user': u, 'status': 'offline'}, broadcast=True)

@socketio.on('join')
def on_join(data):
    join_room(data['room'])

@socketio.on('typing')
def on_typing(data):
    emit('typing', {'user': data['user'], 'room': data['room']}, room=data['room'], include_self=False)

@socketio.on('stop_typing')
def on_stop_typing(data):
    emit('stop_typing', {'user': data['user'], 'room': data['room']}, room=data['room'], include_self=False)

@socketio.on('send_message')
def handle_message(data):
    room = data['room']
    sender = data['from']
    db = get_db()
    user = db.execute('SELECT profile_pic FROM users WHERE username=?', (sender,)).fetchone()
    profile_pic = user['profile_pic'] if user else None
    reply_to = json.dumps(data.get('reply_to')) if data.get('reply_to') else None
    timestamp = datetime.now().strftime('%I:%M %p')
    db.execute('''INSERT INTO messages (room, sender, text, file, file_name, file_type, duration, reply_to, timestamp)
                  VALUES (?,?,?,?,?,?,?,?,?)''',
               (room, sender, data.get('text',''), data.get('file'), data.get('file_name'),
                data.get('file_type'), data.get('duration'), reply_to, timestamp))
    msg_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.commit()
    db.close()
    msg = {
        'id': msg_id, 'from': sender, 'text': data.get('text',''),
        'file': data.get('file'), 'file_name': data.get('file_name'),
        'file_type': data.get('file_type'), 'duration': data.get('duration'),
        'reply_to': data.get('reply_to'), 'time': timestamp,
        'seen': False, 'profile_pic': profile_pic
    }
    emit('receive_message', msg, room=room)
    emit('new_notification', {'from': sender, 'text': data.get('text','📎 File'),
                               'room': room, 'profile_pic': profile_pic}, broadcast=True)

@socketio.on('send_group_message')
def handle_group_message(data):
    gname = data['group']
    sender = data['from']
    db = get_db()
    user = db.execute('SELECT profile_pic FROM users WHERE username=?', (sender,)).fetchone()
    profile_pic = user['profile_pic'] if user else None
    timestamp = datetime.now().strftime('%I:%M %p')
    db.execute('''INSERT INTO group_messages (group_name, sender, text, file, file_name, file_type, duration, timestamp)
                  VALUES (?,?,?,?,?,?,?,?)''',
               (gname, sender, data.get('text',''), data.get('file'), data.get('file_name'),
                data.get('file_type'), data.get('duration'), timestamp))
    db.commit()
    db.close()
    msg = {'from': sender, 'text': data.get('text',''), 'file': data.get('file'),
           'file_name': data.get('file_name'), 'file_type': data.get('file_type'),
           'duration': data.get('duration'), 'time': timestamp, 'profile_pic': profile_pic}
    emit('receive_group_message', msg, room='group_'+gname)

@socketio.on('join_group')
def on_join_group(data):
    join_room('group_' + data['group'])

@socketio.on('message_seen')
def on_seen(data):
    room = data['room']
    db = get_db()
    db.execute('UPDATE messages SET seen=1 WHERE room=?', (room,))
    db.commit()
    db.close()
    emit('message_seen', {'room': room}, room=room, include_self=False)

@socketio.on('delete_message')
def on_delete(data):
    room = data['room']
    msg_id = data['msg_id']
    db = get_db()
    db.execute('UPDATE messages SET deleted=1, text="" WHERE id=?', (msg_id,))
    db.commit()
    db.close()
    emit('message_deleted', {'room': room, 'msg_id': msg_id}, room=room)

@socketio.on('edit_message')
def on_edit(data):
    room = data['room']
    msg_id = data['msg_id']
    new_text = data['new_text']
    db = get_db()
    db.execute('UPDATE messages SET text=?, edited=1 WHERE id=?', (new_text, msg_id))
    db.commit()
    db.close()
    emit('message_edited', {'room': room, 'msg_id': msg_id, 'new_text': new_text}, room=room)

@socketio.on('react_message')
def on_react(data):
    room = data['room']
    msg_id = data['msg_id']
    emoji = data['emoji']
    db = get_db()
    msg = db.execute('SELECT reactions FROM messages WHERE id=?', (msg_id,)).fetchone()
    if msg:
        reactions = json.loads(msg['reactions'] or '{}')
        reactions[emoji] = reactions.get(emoji, 0) + 1
        db.execute('UPDATE messages SET reactions=? WHERE id=?', (json.dumps(reactions), msg_id))
        db.commit()
        emit('message_reaction', {'room': room, 'msg_id': msg_id, 'reactions': reactions}, room=room)
    db.close()

if __name__ == '__main__':
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True)