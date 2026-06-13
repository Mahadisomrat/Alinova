from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from datetime import datetime
import sqlite3, os, json

app = Flask(__name__)
app.secret_key = 'chatbd_secret_2024'
socketio = SocketIO(app, cors_allowed_origins="*")

online_users = set()
user_rooms = {}

# ─── Database Setup ────────────────────────────────────────
def get_db():
    db = sqlite3.connect('alinova.db')
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            profile_pic TEXT,
            about TEXT DEFAULT 'Hey! I am using ChatBD'
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room TEXT NOT NULL,
            sender TEXT NOT NULL,
            text TEXT,
            file TEXT,
            file_name TEXT,
            file_type TEXT,
            duration TEXT,
            reply_to TEXT,
            time TEXT,
            seen INTEGER DEFAULT 0,
            edited INTEGER DEFAULT 0,
            deleted INTEGER DEFAULT 0,
            reactions TEXT DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS groups_table (
            name TEXT PRIMARY KEY,
            created_by TEXT,
            pic TEXT,
            members TEXT
        );
        CREATE TABLE IF NOT EXISTS group_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_name TEXT NOT NULL,
            sender TEXT NOT NULL,
            text TEXT,
            file TEXT,
            file_name TEXT,
            file_type TEXT,
            duration TEXT,
            time TEXT
        );
    ''')
    db.commit()
    db.close()

init_db()

def get_room_id(u1, u2):
    return '_'.join(sorted([u1, u2]))

# ─── Routes ────────────────────────────────────────────────
@app.route('/')
def index():
    return redirect(url_for('login') if 'username' not in session else url_for('home'))

@app.route('/register', methods=['GET', 'POST'])
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
                db.execute('INSERT INTO users (username, password) VALUES (?, ?)', (u, p))
                db.commit()
                session['username'] = u
                db.close()
                return redirect(url_for('home'))
            db.close()
    return render_template('register.html', error=error)

@app.route('/login', methods=['GET', 'POST'])
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
    if 'username' not in session:
        return redirect(url_for('login'))
    me = session['username']
    db = get_db()
    others = db.execute('SELECT * FROM users WHERE username != ?', (me,)).fetchall()
    all_groups = db.execute('SELECT * FROM groups_table').fetchall()
    db.close()

    my_groups = []
    groups_data = {}
    for g in all_groups:
        members = json.loads(g['members'])
        groups_data[g['name']] = {'members': members, 'created_by': g['created_by'], 'pic': g['pic']}
        if me in members:
            my_groups.append(g['name'])

    users_data = {u['username']: dict(u) for u in others}
    return render_template('home.html', username=me, users=[u['username'] for u in others],
                           online=list(online_users), users_data=users_data,
                           groups=my_groups, groups_data=groups_data)

@app.route('/chat/<other>')
def chat(other):
    if 'username' not in session:
        return redirect(url_for('login'))
    me = session['username']
    db = get_db()
    other_user = db.execute('SELECT * FROM users WHERE username=?', (other,)).fetchone()
    if not other_user:
        db.close()
        return redirect(url_for('home'))
    room = get_room_id(me, other)
    history_rows = db.execute('SELECT * FROM messages WHERE room=? ORDER BY id ASC', (room,)).fetchall()
    all_users = db.execute('SELECT * FROM users').fetchall()
    db.close()

    history = []
    for m in history_rows:
        msg = dict(m)
        msg['reactions'] = json.loads(msg['reactions'] or '{}')
        history.append(msg)

    users_data = {u['username']: dict(u) for u in all_users}
    return render_template('chat.html', me=me, other=other,
                           history=history, room=room, users_data=users_data,
                           online=list(online_users))

# ✅ BUG FIX: <n> → <name>
@app.route('/group/<name>')
def group_chat(name):
    if 'username' not in session:
        return redirect(url_for('login'))
    me = session['username']
    db = get_db()
    group = db.execute('SELECT * FROM groups_table WHERE name=?', (name,)).fetchone()
    if not group or me not in json.loads(group['members']):
        db.close()
        return redirect(url_for('home'))
    history_rows = db.execute('SELECT * FROM group_messages WHERE group_name=? ORDER BY id ASC', (name,)).fetchall()
    all_users = db.execute('SELECT * FROM users').fetchall()
    db.close()

    history = [dict(m) for m in history_rows]
    users_data = {u['username']: dict(u) for u in all_users}
    group_dict = {'members': json.loads(group['members']), 'created_by': group['created_by'], 'pic': group['pic']}
    return render_template('group_chat.html', me=me, group_name=name,
                           history=history, group=group_dict, users_data=users_data)

@app.route('/upload_pic', methods=['POST'])
def upload_pic():
    if 'username' not in session:
        return jsonify({'error': 'not logged in'}), 401
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
    if 'username' not in session:
        return jsonify({'error': 'not logged in'}), 401
    data = request.get_json()
    name = data.get('name', '').strip()
    members = data.get('members', [])
    me = session['username']
    if not name:
        return jsonify({'error': 'নাম দিন'}), 400
    db = get_db()
    existing = db.execute('SELECT name FROM groups_table WHERE name=?', (name,)).fetchone()
    if existing:
        db.close()
        return jsonify({'error': 'এই নামে গ্রুপ আছে'}), 400
    if me not in members:
        members.append(me)
    db.execute('INSERT INTO groups_table (name, created_by, members) VALUES (?, ?, ?)',
               (name, me, json.dumps(members)))
    db.commit()
    db.close()
    socketio.emit('group_created', {'name': name, 'members': members})
    return jsonify({'success': True, 'name': name})

# ─── Socket Events ─────────────────────────────────────────
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
    time_str = datetime.now().strftime('%I:%M %p')

    db = get_db()
    sender_data = db.execute('SELECT profile_pic FROM users WHERE username=?', (sender,)).fetchone()
    profile_pic = sender_data['profile_pic'] if sender_data else None

    cursor = db.execute('''INSERT INTO messages 
        (room, sender, text, file, file_name, file_type, duration, reply_to, time, reactions)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (room, sender, data.get('text',''), data.get('file'), data.get('file_name'),
         data.get('file_type'), data.get('duration'), str(data.get('reply_to','')),
         time_str, '{}'))
    msg_id = cursor.lastrowid
    db.commit()
    db.close()

    msg = {
        'id': msg_id,
        'from': sender,
        'sender': sender,
        'text': data.get('text', ''),
        'file': data.get('file'),
        'file_name': data.get('file_name'),
        'file_type': data.get('file_type'),
        'duration': data.get('duration'),
        'reply_to': data.get('reply_to'),
        'time': time_str,
        'seen': False,
        'edited': False,
        'deleted': False,
        'reactions': {},
        'profile_pic': profile_pic
    }

    emit('receive_message', msg, room=room)

    # ✅ FIX: Notification শুধু receiver পাবে
    receiver = None
    parts = room.split('_')
    for p in parts:
        if p != sender:
            receiver = p
            break

    if receiver and receiver in user_rooms:
        emit('new_notification', {
            'from': sender,
            'text': data.get('text', '📎 File'),
            'room': room,
            'profile_pic': profile_pic
        }, room=user_rooms[receiver])

@socketio.on('send_group_message')
def handle_group_message(data):
    gname = data['group']
    sender = data['from']
    time_str = datetime.now().strftime('%I:%M %p')

    db = get_db()
    sender_data = db.execute('SELECT profile_pic FROM users WHERE username=?', (sender,)).fetchone()
    profile_pic = sender_data['profile_pic'] if sender_data else None

    cursor = db.execute('''INSERT INTO group_messages 
        (group_name, sender, text, file, file_name, file_type, duration, time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (gname, sender, data.get('text',''), data.get('file'),
         data.get('file_name'), data.get('file_type'), data.get('duration'), time_str))
    msg_id = cursor.lastrowid
    db.commit()
    db.close()

    msg = {
        'id': msg_id,
        'from': sender,
        'sender': sender,
        'text': data.get('text', ''),
        'file': data.get('file'),
        'file_name': data.get('file_name'),
        'file_type': data.get('file_type'),
        'duration': data.get('duration'),
        'time': time_str,
        'profile_pic': profile_pic
    }
    emit('receive_group_message', msg, room='group_' + gname)

@socketio.on('join_group')
def on_join_group(data):
    join_room('group_' + data['group'])

@socketio.on('message_seen')
def on_seen(data):
    emit('message_seen', {'room': data['room']}, room=data['room'], include_self=False)

@socketio.on('delete_message')
def on_delete(data):
    room = data['room']
    msg_id = data['msg_id']
    db = get_db()
    db.execute('UPDATE messages SET text="", deleted=1 WHERE id=? AND room=?', (msg_id, room))
    db.commit()
    db.close()
    emit('message_deleted', {'room': room, 'msg_id': msg_id}, room=room)

@socketio.on('edit_message')
def on_edit(data):
    room = data['room']
    msg_id = data['msg_id']
    new_text = data['new_text']
    db = get_db()
    db.execute('UPDATE messages SET text=?, edited=1 WHERE id=? AND room=?', (new_text, msg_id, room))
    db.commit()
    db.close()
    emit('message_edited', {'room': room, 'msg_id': msg_id, 'new_text': new_text}, room=room)

@socketio.on('react_message')
def on_react(data):
    room = data['room']
    msg_id = data['msg_id']
    emoji = data['emoji']
    db = get_db()
    row = db.execute('SELECT reactions FROM messages WHERE id=? AND room=?', (msg_id, room)).fetchone()
    if row:
        reactions = json.loads(row['reactions'] or '{}')
        reactions[emoji] = reactions.get(emoji, 0) + 1
        db.execute('UPDATE messages SET reactions=? WHERE id=?', (json.dumps(reactions), msg_id))
        db.commit()
        emit('message_reaction', {'room': room, 'msg_id': msg_id, 'reactions': reactions}, room=room)
    db.close()

if __name__ == '__main__':
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True)
