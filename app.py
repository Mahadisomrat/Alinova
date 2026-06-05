from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from datetime import datetime
import os
from supabase import create_client, Client

app = Flask(__name__)
app.secret_key = 'chatbd_secret_2024
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent', ping_timeout=60, ping_interval=25)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

online_users = set()
user_rooms = {}

def get_room_id(u1, u2):
    return '_'.join(sorted([u1, u2]))

def db_get_user(username):
    res = supabase.table("users").select("*").eq("username", username).execute()
    return res.data[0] if res.data else None

def db_create_user(username, password):
    supabase.table("users").insert({
        "username": username,
        "password": password,
        "profile_pic": None,
        "about": "Hey! I am using Alinova"
    }).execute()

def db_get_all_users():
    res = supabase.table("users").select("*").execute()
    return {u["username"]: u for u in res.data}

def db_get_messages(room):
    res = supabase.table("messages").select("*").eq("room", room).order("created_at").execute()
    return res.data

def db_save_message(room, msg):
    supabase.table("messages").insert({
        "room": room,
        "sender": msg["from"],
        "text": msg.get("text", ""),
        "file": msg.get("file"),
        "file_name": msg.get("file_name"),
        "file_type": msg.get("file_type"),
        "duration": msg.get("duration"),
        "reply_to": msg.get("reply_to"),
        "time": msg["time"],
        "seen": False,
        "edited": False,
        "deleted": False,
        "reactions": {},
        "msg_id": msg["id"],
        "profile_pic": msg.get("profile_pic")
    }).execute()

def db_get_groups():
    res = supabase.table("groups").select("*").execute()
    return {g["name"]: g for g in res.data}

def db_create_group(name, members, created_by):
    supabase.table("groups").insert({
        "name": name,
        "members": members,
        "created_by": created_by,
        "pic": None
    }).execute()

def db_get_group_messages(group_name):
    res = supabase.table("group_messages").select("*").eq("group_name", group_name).order("created_at").execute()
    return res.data

def db_save_group_message(group_name, msg):
    supabase.table("group_messages").insert({
        "group_name": group_name,
        "sender": msg["from"],
        "text": msg.get("text", ""),
        "file": msg.get("file"),
        "file_name": msg.get("file_name"),
        "file_type": msg.get("file_type"),
        "duration": msg.get("duration"),
        "time": msg["time"],
        "profile_pic": msg.get("profile_pic"),
        "msg_id": msg["id"]
    }).execute()

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
        elif db_get_user(u):
            error = 'এই নামে ইউজার আছে।'
        else:
            db_create_user(u, p)
            session['username'] = u
            return redirect(url_for('home'))
    return render_template('register.html', error=error)

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        u = request.form['username'].strip()
        p = request.form['password'].strip()
        user = db_get_user(u)
        if user and user['password'] == p:
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
    all_users = db_get_all_users()
    others = [u for u in all_users if u != me]
    groups = db_get_groups()
    my_groups = [g for g, d in groups.items() if me in d.get('members', [])]
    return render_template('home.html', username=me, users=others,
                           online=list(online_users), users_data=all_users,
                           groups=my_groups, groups_data=groups)

@app.route('/chat/<other>')
def chat(other):
    if 'username' not in session: return redirect(url_for('login'))
    me = session['username']
    if not db_get_user(other): return redirect(url_for('home'))
    room = get_room_id(me, other)
    history = db_get_messages(room)
    all_users = db_get_all_users()
    return render_template('chat.html', me=me, other=other,
                           history=history, room=room, users_data=all_users,
                           online=list(online_users))

@app.route('/group/<name>')
def group_chat(name):
    if 'username' not in session: return redirect(url_for('login'))
    me = session['username']
    groups = db_get_groups()
    if name not in groups or me not in groups[name].get('members', []):
        return redirect(url_for('home'))
    history = db_get_group_messages(name)
    all_users = db_get_all_users()
    return render_template('group_chat.html', me=me, group_name=name,
                           history=history, group=groups[name], users_data=all_users)

@app.route('/upload_pic', methods=['POST'])
def upload_pic():
    if 'username' not in session: return jsonify({'error': 'not logged in'}), 401
    data = request.get_json()
    pic = data.get('pic')
    if pic:
        supabase.table("users").update({"profile_pic": pic}).eq("username", session['username']).execute()
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
    groups = db_get_groups()
    if name in groups: return jsonify({'error': 'এই নামে গ্রুপ আছে'}), 400
    if me not in members: members.append(me)
    db_create_group(name, members, me)
    socketio.emit('group_created', {'name': name, 'members': members})
    return jsonify({'success': True, 'name': name})

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
    msg = {
        'from': sender,
        'text': data.get('text', ''),
        'file': data.get('file'),
        'file_name': data.get('file_name'),
        'file_type': data.get('file_type'),
        'duration': data.get('duration'),
        'reply_to': data.get('reply_to'),
        'time': datetime.now().strftime('%I:%M %p'),
        'seen': False,
        'edited': False,
        'deleted': False,
        'reactions': {},
        'profile_pic': data.get('profile_pic'),
        'id': datetime.now().strftime('%f')
    }
    emit('receive_message', msg, room=room)
    emit('new_notification', {
        'from': sender,
        'text': data.get('text', '📎 File'),
        'room': room,
        'profile_pic': data.get('profile_pic')
    }, broadcast=True)
    db_save_message(room, msg)

@socketio.on('send_group_message')
def handle_group_message(data):
    gname = data['group']
    sender = data['from']
    msg = {
        'from': sender,
        'text': data.get('text', ''),
        'file': data.get('file'),
        'file_name': data.get('file_name'),
        'file_type': data.get('file_type'),
        'duration': data.get('duration'),
        'time': datetime.now().strftime('%I:%M %p'),
        'profile_pic': data.get('profile_pic'),
        'id': datetime.now().strftime('%f')
    }
    emit('receive_group_message', msg, room='group_' + gname)
    db_save_group_message(gname, msg)

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
    supabase.table("messages").update({"deleted": True, "text": ""}).eq("room", room).eq("msg_id", msg_id).execute()
    emit('message_deleted', {'room': room, 'msg_id': msg_id}, room=room)

@socketio.on('edit_message')
def on_edit(data):
    room = data['room']
    msg_id = data['msg_id']
    new_text = data['new_text']
    supabase.table("messages").update({"text": new_text, "edited": True}).eq("room", room).eq("msg_id", msg_id).execute()
    emit('message_edited', {'room': room, 'msg_id': msg_id, 'new_text': new_text}, room=room)

@socketio.on('react_message')
def on_react(data):
    room = data['room']
    msg_id = data['msg_id']
    emoji = data['emoji']
    res = supabase.table("messages").select("reactions").eq("room", room).eq("msg_id", msg_id).execute()
    if res.data:
        reactions = res.data[0].get("reactions") or {}
        reactions[emoji] = reactions.get(emoji, 0) + 1
        supabase.table("messages").update({"reactions": reactions}).eq("room", room).eq("msg_id", msg_id).execute()
        emit('message_reaction', {'room': room, 'msg_id': msg_id, 'reactions': reactions}, room=room)

if __name__ == '__main__':
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True)
